"""Therapist-reviewed AI tutorial drafts; patients receive approved tutorials only."""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import db, jobs
from app.auth import current_user, require_assigned_therapist_session
from app.tutorial import generate

router = APIRouter(prefix="/api", tags=["tutorials"])


class TutorialCreateIn(BaseModel):
    reference_video_id: int = Field(gt=0)


class TutorialActionIn(BaseModel):
    notes: str = Field("", max_length=2000)


class TutorialMediaIn(BaseModel):
    voice_enabled: bool = False


class TutorialEditIn(BaseModel):
    verified_findings: list[str] = Field(min_length=1, max_length=8)
    coaching_cues: list[str] = Field(max_length=6)
    warnings: list[str] = Field(max_length=6)
    captions: list[str] = Field(min_length=1, max_length=8)
    script: str = Field(min_length=20, max_length=1200)


def _row(tutorial_id: str) -> dict:
    row = db.one("SELECT * FROM tutorials WHERE id = ?", tutorial_id)
    if not row:
        raise HTTPException(404, "No such tutorial")
    result = dict(row)
    for key in ("verified_findings_json", "coaching_cues_json", "warnings_json", "captions_json", "validation_json"):
        result[key.removesuffix("_json")] = json.loads(result.pop(key))
    result["reference_video"] = db.one("SELECT id, exercise, title, '/api/reference-videos/' || id || '/video' AS url "
                                       "FROM reference_videos WHERE id = ?", row["reference_video_id"])
    result["source_session"] = {"id": row["source_session_id"]}
    result["request_changes_notes"] = row.get("request_changes_notes")
    result.pop("media_path", None)
    result["media"] = {
        "status": row.get("media_status", "not_requested"),
        "voice_enabled": bool(row.get("media_voice_enabled", 0)),
        "voice_status": row.get("media_voice_status", "not_requested"),
        "generated_at": row.get("media_generated_at"),
        "error": row.get("media_error"),
        "url": f"/api/tutorials/{tutorial_id}/media" if row.get("media_status") == "ready" else None,
    }
    return result


@router.get("/sessions/{session_id}/tutorials")
def session_tutorials(session_id: str, request: Request):
    user = require_assigned_therapist_session(request, session_id)
    rows = db.all_("SELECT id FROM tutorials WHERE source_session_id=? AND therapist_user_id=? ORDER BY created_at DESC",
                   session_id, user["id"])
    return [_row(row["id"]) for row in rows]


def _therapist_can_edit(request: Request, tutorial: dict) -> dict:
    user = require_assigned_therapist_session(request, tutorial["source_session_id"])
    if user["id"] != tutorial["therapist_user_id"]:
        raise HTTPException(403, "Only the creating therapist can edit this tutorial")
    return user


@router.post("/sessions/{session_id}/tutorials", status_code=201)
def create_tutorial(session_id: str, body: TutorialCreateIn, request: Request):
    therapist = require_assigned_therapist_session(request, session_id)
    session = db.one("SELECT * FROM sessions WHERE id = ?", session_id)
    if not session or not session["result_json"]:
        raise HTTPException(404, "Session not found or not analysed yet")
    if not db.one("SELECT 1 FROM reviews WHERE session_id=?", session_id):
        raise HTTPException(409, "Review the session before generating a tutorial")
    try:
        draft, meta = generate(session_id, body.reference_video_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    tutorial_id = f"tutorial-{uuid.uuid4().hex[:12]}"
    now = db.now()
    with db.tx() as c:
        c.execute(
            "INSERT INTO tutorials (id,patient_id,source_session_id,therapist_user_id,exercise,target_reps,target_depth_deg,"
            "reference_video_id,verified_findings_json,coaching_cues_json,warnings_json,captions_json,script,generation_source,"
            "validation_json,status,request_changes_notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tutorial_id, session["patient_id"], session_id, therapist["id"], draft["exercise"], draft["target_repetitions"],
             draft["target_depth_deg"], body.reference_video_id, json.dumps(draft["verified_findings"]),
             json.dumps(draft["coaching_cues"]), json.dumps(draft["warnings"]), json.dumps(draft["captions"]), draft["script"],
             meta["source"], json.dumps(meta["validation"]), "draft", None, now, now),
        )
    return _row(tutorial_id)


@router.get("/tutorials/{tutorial_id}")
def get_tutorial(tutorial_id: str, request: Request):
    user = current_user(request)
    tutorial = _row(tutorial_id)
    if user["role"] == "therapist":
        require_assigned_therapist_session(request, tutorial["source_session_id"])
    elif tutorial["patient_id"] != user["id"] or tutorial["status"] != "approved":
        raise HTTPException(403, "This tutorial is not available")
    return tutorial


@router.patch("/tutorials/{tutorial_id}")
def edit_tutorial(tutorial_id: str, body: TutorialEditIn, request: Request):
    tutorial = _row(tutorial_id)
    _therapist_can_edit(request, tutorial)
    if tutorial["status"] == "approved":
        raise HTTPException(409, "Approved tutorials cannot be edited")
    now = db.now()
    with db.tx() as c:
        c.execute("UPDATE tutorials SET verified_findings_json=?, coaching_cues_json=?, warnings_json=?, captions_json=?, "
                  "script=?, updated_at=? WHERE id=?",
                  (json.dumps(body.verified_findings), json.dumps(body.coaching_cues), json.dumps(body.warnings),
                   json.dumps(body.captions), body.script, now, tutorial_id))
    return _row(tutorial_id)


@router.post("/tutorials/{tutorial_id}/approve")
def approve_tutorial(tutorial_id: str, body: TutorialActionIn, request: Request):
    tutorial = _row(tutorial_id)
    _therapist_can_edit(request, tutorial)
    now = db.now()
    with db.tx() as c:
        c.execute("UPDATE tutorials SET status='approved', updated_at=?, approved_at=? WHERE id=?", (now, now, tutorial_id))
    return _row(tutorial_id)


@router.post("/tutorials/{tutorial_id}/request-changes")
def request_tutorial_changes(tutorial_id: str, body: TutorialActionIn, request: Request):
    tutorial = _row(tutorial_id)
    _therapist_can_edit(request, tutorial)
    now = db.now()
    with db.tx() as c:
        c.execute("UPDATE tutorials SET status='request_changes', request_changes_notes=?, updated_at=?, approved_at=NULL WHERE id=?",
                  (body.notes, now, tutorial_id))
    return _row(tutorial_id)


@router.post("/tutorials/{tutorial_id}/media", status_code=202)
def generate_tutorial_media(tutorial_id: str, body: TutorialMediaIn, request: Request):
    tutorial = _row(tutorial_id)
    _therapist_can_edit(request, tutorial)
    if tutorial["status"] == "approved" and tutorial["media"]["status"] == "ready":
        return tutorial
    if tutorial["media"]["status"] in ("queued", "processing"):
        raise HTTPException(409, "Tutorial media generation is already running")
    with db.tx() as c:
        c.execute("UPDATE tutorials SET media_status='queued', media_error=NULL, media_voice_enabled=?, "
                  "media_voice_status=?, updated_at=? WHERE id=?",
                  (int(body.voice_enabled), "not_requested", db.now(), tutorial_id))
    jobs.submit_tutorial_media(tutorial_id, body.voice_enabled)
    return {"tutorial_id": tutorial_id, "media_status": "queued", "voice_enabled": body.voice_enabled}


@router.get("/tutorials/{tutorial_id}/media")
def tutorial_media(tutorial_id: str, request: Request):
    user = current_user(request)
    tutorial = db.one("SELECT * FROM tutorials WHERE id = ?", tutorial_id)
    if not tutorial:
        raise HTTPException(404, "No such tutorial")
    if user["role"] == "patient":
        if tutorial["patient_id"] != user["id"] or tutorial["status"] != "approved":
            raise HTTPException(403, "This tutorial media is not available")
    elif user["role"] == "therapist":
        require_assigned_therapist_session(request, tutorial["source_session_id"])
    else:
        raise HTTPException(403, "Unsupported account role")
    if tutorial["media_status"] != "ready" or not tutorial["media_path"]:
        raise HTTPException(404, "Tutorial media is not ready")
    path = Path(tutorial["media_path"])
    if not path.is_file():
        raise HTTPException(404, "Tutorial media is not available")
    return FileResponse(path, media_type="video/mp4", filename=f"{tutorial_id}.mp4")


@router.get("/patient/tutorials")
def patient_tutorials(request: Request):
    user = current_user(request)
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    rows = db.all_("SELECT id FROM tutorials WHERE patient_id=? AND status='approved' ORDER BY created_at DESC", user["id"])
    return [_row(row["id"]) for row in rows]
