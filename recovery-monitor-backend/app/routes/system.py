"""Health, evaluation numbers and the reference video library (#21, #29, #16)."""

import asyncio
import json
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app import db
from app.auth import current_user, require_therapist
from app.config import AI_ENDPOINTS, AI_SERVICE_URL, DEVICE_NAME, LLM_MODEL, LLM_URL, MODEL_RESULTS, REFERENCE_DIR
from app.guards import is_local, network_reachable
from app.video import VideoError, normalize

router = APIRouter(prefix="/api", tags=["system"])


async def _ai_status() -> dict:
    import httpx

    out = {}
    async with httpx.AsyncClient(timeout=2) as c:
        try:
            r = await c.get(f"{AI_SERVICE_URL}/health")
            out["vision_and_speech"] = r.json() if r.status_code == 200 else {"ok": False}
        except httpx.HTTPError:
            out["vision_and_speech"] = {"ok": False}
        try:
            r = await c.get(f"{LLM_URL}/api/tags")
            out["llm"] = {"ok": r.status_code == 200, "model": LLM_MODEL, "server": LLM_URL}
        except httpx.HTTPError:
            out["llm"] = {"ok": False, "model": LLM_MODEL}
    return out


@router.get("/health")
async def health():
    return {
        "ai": await _ai_status(),
        "status": "ready",
        "device": DEVICE_NAME,
        "inference_local": all(is_local(u) for u in AI_ENDPOINTS),  # also enforced at startup
        "cloud_ai_disabled": True,
        "network_required": False,
        "network_reachable": await asyncio.to_thread(network_reachable),
        "models": {"pose": "MediaPipe Pose Landmarker (full), on-device CPU",
                   "classifier": "XGBoost rep-correctness models, one per exercise (6)",
                   "vision": "Qwen3-VL-4B + LoRA fine-tuned on REHAB24-6 (exercise, view, form)",
                   "speech": "Whisper large-v3-turbo", "report": f"{LLM_MODEL} (local)"},
    }


@router.get("/eval/summary")
def eval_summary():
    """Measured model numbers for the Evaluation page (#29). Anything not measured is null."""
    def load(name):
        p = MODEL_RESULTS / name
        return json.loads(p.read_text()) if p.exists() else None

    angles, reps, clf = load("angle_accuracy_squat.json"), load("rep_counting_squat.json"), load("classifier_squat.json")
    return {
        "dataset": "REHAB24-6 squats (Ex6): 9 subjects, 390 annotated reps; CC BY-NC 4.0 (Černek et al., SISAP 2024)",
        "angle_accuracy": angles and {"per_frame": angles["per_frame_error"]["image_2d"],
                                      "rep_depth": angles["rep_depth_error"]["image_2d"],
                                      "ground_truth": angles["ground_truth"], "example_rep": angles.get("example_rep")},
        "rep_counting": reps and {"overall": reps["summary"]["all"], "recall_by_view": reps["recall_by_view"]},
        "classifier": clf and {k: clf[k] for k in ("evaluation", "threshold", "n_reps", "n_incorrect", "n_subjects",
                                                   "xgboost", "rules_baseline", "xgboost_by_view")},
        "exercises": {e: load(f"exercise_{e}.json") for e in
                      ("squat", "leg_lunge", "leg_abduction", "arm_abduction", "arm_vw", "push_ups")},
        "vlm": {"before": load("vlm_zeroshot_test.json"), "after": load("vlm_qwen3vl4b_lora_test.json")},
        "caveats": [
            "Healthy volunteers acting out mistakes, not patients; not clinical validation.",
            "Rep-counter settings and the classifier's feature set were chosen while looking at this data.",
            "Angles are only accurate from a side view.",
        ],
    }


@router.get("/reference-videos")
def list_reference_videos(request: Request, exercise: str | None = None):
    current_user(request)
    rows = db.all_("SELECT * FROM reference_videos WHERE approval_status='approved' AND (? IS NULL OR exercise = ?) ORDER BY id",
                   exercise, exercise)
    return [{**r, "url": f"/api/reference-videos/{r['id']}/video", "path": None} for r in rows]


@router.get("/reference-videos/{video_id}/video")
def reference_video(video_id: int, request: Request):
    current_user(request)
    r = db.one("SELECT * FROM reference_videos WHERE id = ?", video_id)
    if not r or r["approval_status"] != "approved":
        raise HTTPException(404, "No such reference video")
    return FileResponse(r["path"], media_type="video/mp4")


@router.post("/reference-videos", status_code=201)
async def add_reference_video(request: Request, video: UploadFile = File(...), title: str = Form(...), exercise: str = Form("squat"),
                              source: str = Form("recorded by the physiotherapist")):
    require_therapist(request)
    from app.routes.sessions import save_upload

    folder = REFERENCE_DIR / uuid.uuid4().hex[:12]
    raw = await save_upload(video, folder)
    try:
        await asyncio.to_thread(normalize, raw, folder / "video.mp4")
    except VideoError as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, str(e)) from e
    raw.unlink(missing_ok=True)
    with db.tx() as c:
        cur = c.execute("INSERT INTO reference_videos (exercise, title, path, source, approval_status, created_at) VALUES (?,?,?,?,?,?)",
                        (exercise, title, str(folder / "video.mp4"), source, "approved", db.now()))
    return {"id": cur.lastrowid, "title": title, "url": f"/api/reference-videos/{cur.lastrowid}/video"}
