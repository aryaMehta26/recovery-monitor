"""Background analysis jobs (#34). Upload returns immediately; a worker thread converts the video,
runs the model pipeline and stores the result. Progress lives in the sessions table so any client
(SSE stream, polling, a page reload) sees the same state."""

import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import db
from app.config import MAX_CONCURRENT_ANALYSES
from app.video import VideoError, normalize, thumbnail

_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_ANALYSES, thread_name_prefix="analysis")

# Share of the progress bar each stage takes (pose estimation dominates).
STAGES = {"queued": (0.0, 0.0), "converting": (0.0, 0.1), "pose": (0.1, 0.8), "analyze": (0.8, 0.85),
          "render": (0.85, 1.0)}


def set_stage(session_id: str, stage: str, fraction: float = 0.0, **extra) -> None:
    lo, hi = STAGES.get(stage, (0.0, 1.0))
    fields = {"stage": stage, "progress": round(lo + (hi - lo) * max(0.0, min(fraction, 1.0)), 3),
              "updated_at": db.now(), **extra}
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db.tx() as c:
        c.execute(f"UPDATE sessions SET {cols} WHERE id = ?", (*fields.values(), session_id))


def _protocol(protocol_id: int | None) -> dict:
    p = db.one("SELECT * FROM protocols WHERE id = ?", protocol_id) if protocol_id else None
    if not p:
        return {}
    return {"target_reps": p["target_reps"], "target_depth_deg": p["target_depth_deg"],
            "pain_threshold": p["pain_threshold"]}


MAX_BASELINE_REPS = 10
MODEL_EXERCISES = {"squat", "leg_lunge", "leg_abduction", "arm_abduction", "arm_vw", "push_ups"}


def baseline_for(patient_id: str, before: str, exclude_id: str | None = None, exercise: str = "squat") -> list[dict]:
    """Per-rep features from the patient's physio-approved sessions of the same exercise, newest first: every
    rep the physio didn't mark incorrect (unlabelled reps count if the analysis judged them correct)."""
    out = []
    for r in db.all_("SELECT s.result_json, v.rep_labels_json FROM sessions s JOIN reviews v ON v.session_id = s.id "
                     "WHERE s.patient_id = ? AND v.decision = 'approve' AND s.created_at <= ? AND s.id != ? "
                     "ORDER BY s.created_at DESC", patient_id, before, exclude_id or ""):
        labels = db.loads(r["rep_labels_json"]) or {}
        result = db.loads(r["result_json"]) or {}
        if result.get("exercise", "squat") != exercise:
            continue
        for rep in result.get("reps", []):
            label = labels.get(str(rep["index"]))
            if rep.get("features") and (label == "correct" or (label is None and rep["predicted_correct"])):
                out.append(rep["features"])
        if len(out) >= MAX_BASELINE_REPS:
            break
    return out[:MAX_BASELINE_REPS]


def run(session_id: str, raw_path: Path) -> None:
    s = db.one("SELECT * FROM sessions WHERE id = ?", session_id)
    folder = raw_path.parent
    try:
        set_stage(session_id, "converting", status="processing")
        video = folder / "video.mp4"
        duration = normalize(raw_path, video)
        raw_path.unlink(missing_ok=True)  # keep only the normalized copy
        thumb = thumbnail(video, folder / "thumbnail.jpg", at_s=min(1.0, duration / 2))
        set_stage(session_id, "pose", video_path=str(video), duration_s=round(duration, 2),
                  thumbnail_path=str(thumb) if thumb else None)

        protocol = _protocol(s["protocol_id"])
        if s["exercise"] in MODEL_EXERCISES:
            from model.pipeline import run_pipeline

            result = run_pipeline(str(video), s["exercise"], protocol, annotated_path=str(folder / "annotated.mp4"),
                                  progress=lambda stage, f: set_stage(session_id, stage, f),
                                  baseline=lambda ex: baseline_for(s["patient_id"], s["created_at"], session_id, ex),
                                  work_dir=str(folder))
            annotated = str(folder / "annotated.mp4")
        else:
            from app.legacy import analyze_uploaded_video

            result = analyze_uploaded_video(str(video))
            result.update(exercise=s["exercise"], origin="local_mediapipe_heuristic", protocol=protocol)
            annotated = None
        result["session_id"] = session_id
        result["source"] = s["source"]
        result["annotated_video_url"] = f"/api/sessions/{session_id}/annotated-video" if annotated else None
        result.pop("annotated_video_path", None)
        with db.tx() as c:
            c.execute("UPDATE sessions SET status = ?, stage = 'done', progress = 1, result_json = ?, "
                      "annotated_path = ?, updated_at = ? WHERE id = ?",
                      (result["status"], json.dumps(result), annotated, db.now(), session_id))
        submit_report(session_id)
    except VideoError as e:
        set_stage(session_id, "failed", status="failed", error=str(e))
    except Exception as e:  # noqa: BLE001 — a failed analysis must be visible, never a silent hang
        traceback.print_exc()
        set_stage(session_id, "failed", status="failed", error=f"Analysis failed: {e}"[:300])


def submit(session_id: str, raw_path: Path):
    return _pool.submit(run, session_id, raw_path)


_media_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tutorial-media")


def run_tutorial_media(tutorial_id: str, voice_enabled: bool = False) -> None:
    with db.tx() as c:
        c.execute("UPDATE tutorials SET media_status='processing', media_error=NULL, media_voice_enabled=?, "
                  "media_voice_status=? WHERE id=?", (int(voice_enabled), "not_requested", tutorial_id))
    try:
        from app.media import render_tutorial_media

        artifact, voice_status = render_tutorial_media(tutorial_id, voice_enabled)
        with db.tx() as c:
            c.execute("UPDATE tutorials SET media_status='ready', media_path=?, media_error=NULL, "
                      "media_voice_status=?, media_generated_at=?, updated_at=? WHERE id=?",
                      (str(artifact), voice_status, db.now(), db.now(), tutorial_id))
    except Exception as error:  # noqa: BLE001 — media failure must be visible to the therapist
        traceback.print_exc()
        with db.tx() as c:
            c.execute("UPDATE tutorials SET media_status='failed', media_error=?, updated_at=? WHERE id=?",
                      (str(error)[:500], db.now(), tutorial_id))


def submit_tutorial_media(tutorial_id: str, voice_enabled: bool = False):
    return _media_pool.submit(run_tutorial_media, tutorial_id, voice_enabled)


_report_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report")


def submit_report(session_id: str):
    """(Re)generate the AI draft report in the background; failures are logged, never block the app."""
    def job():
        try:
            from app import report

            report.generate(session_id)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return _report_pool.submit(job)
