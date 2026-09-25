"""Patient issue intake and therapist-approved exercise-plan workflow."""

import asyncio
import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app import db
from app.auth import current_user

router = APIRouter(prefix="/api", tags=["intakes"])
EXERCISES = {"arm_abduction", "arm_vw", "push_ups", "leg_abduction", "leg_lunge", "squat"}
AREA_SPECIALIZATIONS = {
    "shoulder_arm": {"upper_body"}, "elbow_forearm": {"upper_body"}, "wrist_hand": {"upper_body"},
    "hip": {"lower_body"}, "knee": {"lower_body"}, "ankle_foot": {"lower_body"},
    "back_core": {"lower_body", "general_mobility"}, "general_mobility": {"general_mobility"},
    "other": {"general_mobility"},
}


class IntakeIn(BaseModel):
    affected_areas: list[str] = Field(min_length=1, max_length=10)
    issue_types: list[str] = Field(min_length=1, max_length=10)
    when_it_happens: list[str] = Field(default_factory=list, max_length=10)
    pain_score: int = Field(ge=0, le=10)
    duration: str = Field(min_length=1, max_length=40)
    trend: str = Field(min_length=1, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    goals: list[str] = Field(min_length=1, max_length=10)
    notes: str | None = Field(None, max_length=2000)
    voice_transcript: str | None = Field(None, max_length=5000)
    ai: dict | None = None  # the AI intake assistant's structured summary, as reviewed by the patient


class PlanIn(BaseModel):
    exercise: str
    reference_video_id: int | None = None
    target_reps: int = Field(ge=1, le=100)
    target_sets: int = Field(ge=1, le=20)
    target_depth_deg: float | None = Field(None, ge=30, le=175)
    pain_threshold: int = Field(ge=0, le=10)
    instructions: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=2000)


class DecisionIn(BaseModel):
    notes: str | None = Field(None, max_length=2000)


def _json(value):
    return json.dumps(value, separators=(",", ":"))


def _intake(row: dict) -> dict:
    if not row:
        raise HTTPException(404, "No such intake")
    result = dict(row)
    for key in ("affected_areas_json", "issue_types_json", "when_it_happens_json", "limitations_json", "goals_json"):
        result[key.removesuffix("_json")] = json.loads(result.pop(key))
    result["ai"] = json.loads(result.pop("ai_json") or "null")
    plan = db.one("SELECT * FROM plan_drafts WHERE intake_id=? ORDER BY created_at DESC LIMIT 1", row["id"])
    result["plan"] = plan
    result["patient"] = db.one("SELECT u.id, u.email, pp.name FROM users u LEFT JOIN patient_profiles pp ON pp.user_id=u.id WHERE u.id=?", row["patient_user_id"])
    result["therapist"] = row["assigned_therapist_id"] and db.one(
        "SELECT u.id, u.email, tp.name FROM users u LEFT JOIN therapist_profiles tp ON tp.user_id=u.id WHERE u.id=?",
        row["assigned_therapist_id"])
    return result


def _therapist(user: dict) -> None:
    if user["role"] != "therapist":
        raise HTTPException(403, "Therapist account required")


def _matches_specialization(user_id: str, row: dict) -> bool:
    specializations = {item["specialization"] for item in db.all_(
        "SELECT specialization FROM therapist_specializations WHERE user_id=?", user_id
    )}
    if not specializations:
        return False
    areas = json.loads(row["affected_areas_json"])
    return any(specializations.intersection(AREA_SPECIALIZATIONS.get(area, {"general_mobility"})) for area in areas)


def _accessible_to(user_id: str, row: dict) -> bool:
    return row["assigned_therapist_id"] == user_id or (
        row["assigned_therapist_id"] is None and _matches_specialization(user_id, row)
    )


def _ensure_patient_record(c, patient_user_id: str) -> None:
    """The care-team pages (patient list, plan editor, sessions) work on the patients table."""
    prof = c.execute("SELECT name FROM patient_profiles WHERE user_id=?", (patient_user_id,)).fetchone()
    c.execute("INSERT OR IGNORE INTO patients (id,name,condition,created_at) VALUES (?,?,?,?)",
              (patient_user_id, prof["name"] if prof and prof["name"] else patient_user_id, None, db.now()))


def _pick_therapist(areas: list[str], exclude: set[str] = frozenset()) -> str | None:
    """Matching specialisation, fewest patients currently assigned; ties go to the longest-registered therapist."""
    row = {"affected_areas_json": json.dumps(areas)}
    best = None
    for t in db.all_("SELECT id FROM users WHERE role='therapist' ORDER BY created_at"):
        if t["id"] in exclude or not _matches_specialization(t["id"], row):
            continue
        load = db.one("SELECT COUNT(*) n FROM patient_intakes WHERE assigned_therapist_id=?", t["id"])["n"]
        if best is None or load < best[1]:
            best = (t["id"], load)
    return best[0] if best else None


@router.post("/patient/intakes/assist")
async def intake_assist(request: Request, audio: UploadFile | None = File(None), text: str = Form(""),
                        areas: str = Form("[]")):
    """Voice (or typed) description -> Whisper transcript -> structured request + a reply for the patient."""
    user = current_user(request)
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    from app import intake_ai
    from app.config import DATA_DIR
    from app.routes.sessions import _transcribe

    transcript = ""
    if audio is not None:
        folder = DATA_DIR / "intake_audio" / user["id"]
        folder.mkdir(parents=True, exist_ok=True)
        raw = folder / f"{uuid.uuid4().hex[:10]}.webm"
        raw.write_bytes(await audio.read())
        transcript = (await asyncio.to_thread(_transcribe, raw))["text"].strip()
    words = " ".join(filter(None, [text.strip(), transcript]))
    if len(words) < 3:
        raise HTTPException(422, "We could not hear anything. Try again a little closer to the microphone, or type it.")
    try:
        ticked = json.loads(areas)
    except ValueError:
        ticked = []
    result = await asyncio.to_thread(intake_ai.assist, words, ticked)
    return {"transcript": transcript, "text": words, **result}


@router.post("/patient/intakes", status_code=201)
def create_intake(body: IntakeIn, request: Request):
    user = current_user(request)
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    if not db.one("SELECT 1 FROM patient_profiles WHERE user_id=? AND completed_at IS NOT NULL", user["id"]):
        raise HTTPException(409, "Complete patient onboarding first")
    intake_id = f"intake-{uuid.uuid4().hex[:12]}"
    now = db.now()
    therapist = _pick_therapist(body.affected_areas)
    with db.tx() as c:
        c.execute("INSERT INTO patient_intakes (id,patient_user_id,affected_areas_json,issue_types_json,when_it_happens_json,"
                  "pain_score,duration,trend,limitations_json,goals_json,notes,status,assigned_therapist_id,"
                  "voice_transcript,ai_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (intake_id, user["id"], _json(body.affected_areas), _json(body.issue_types), _json(body.when_it_happens),
                   body.pain_score, body.duration, body.trend, _json(body.limitations), _json(body.goals), body.notes,
                   "assigned" if therapist else "pending", therapist, body.voice_transcript,
                   _json(body.ai) if body.ai else None, now, now))
        if therapist:
            _ensure_patient_record(c, user["id"])
    return _intake(db.one("SELECT * FROM patient_intakes WHERE id=?", intake_id))


@router.get("/patient/intakes")
def patient_intakes(request: Request):
    user = current_user(request)
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    return [_intake(row) for row in db.all_("SELECT * FROM patient_intakes WHERE patient_user_id=? ORDER BY created_at DESC", user["id"])]


@router.get("/therapist/intakes")
def therapist_intakes(request: Request, status: str | None = None):
    user = current_user(request)
    _therapist(user)
    sql = "SELECT * FROM patient_intakes WHERE (assigned_therapist_id IS NULL OR assigned_therapist_id=?) AND NOT EXISTS (SELECT 1 FROM therapist_intake_decisions d WHERE d.intake_id=patient_intakes.id AND d.therapist_user_id=? AND d.decision='declined')"
    args = [user["id"], user["id"]]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC"
    rows = db.all_(sql, *args)
    return [_intake(row) for row in rows if _accessible_to(user["id"], row)]


@router.get("/therapist/intakes/{intake_id}")
def therapist_intake(intake_id: str, request: Request):
    user = current_user(request)
    _therapist(user)
    row = db.one("SELECT * FROM patient_intakes WHERE id=? AND (assigned_therapist_id IS NULL OR assigned_therapist_id=?)",
                 intake_id, user["id"])
    if row and not _accessible_to(user["id"], row):
        raise HTTPException(404, "No matching intake")
    return _intake(row)


@router.post("/therapist/intakes/{intake_id}/plan", status_code=201)
def create_plan(intake_id: str, body: PlanIn, request: Request):
    user = current_user(request)
    _therapist(user)
    if body.exercise not in EXERCISES:
        raise HTTPException(422, "Unsupported exercise")
    intake = db.one("SELECT * FROM patient_intakes WHERE id=? AND (assigned_therapist_id IS NULL OR assigned_therapist_id=?)",
                    intake_id, user["id"])
    if not intake or not _accessible_to(user["id"], intake):
        raise HTTPException(404, "No accessible intake")
    if body.reference_video_id and not db.one("SELECT id FROM reference_videos WHERE id=?", body.reference_video_id):
        raise HTTPException(422, "Unknown reference video")
    plan_id = f"plan-{uuid.uuid4().hex[:12]}"
    now = db.now()
    with db.tx() as c:
        c.execute("INSERT INTO plan_drafts (id,intake_id,therapist_user_id,exercise,reference_video_id,target_reps,target_sets,"
                  "target_depth_deg,pain_threshold,instructions,notes,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (plan_id, intake_id, user["id"], body.exercise, body.reference_video_id, body.target_reps, body.target_sets,
                   body.target_depth_deg, body.pain_threshold, body.instructions, body.notes, "plan_drafted", now, now))
        c.execute("UPDATE patient_intakes SET assigned_therapist_id=?, status='plan_drafted', updated_at=? WHERE id=?",
                  (user["id"], now, intake_id))
    return db.one("SELECT * FROM plan_drafts WHERE id=?", plan_id)


def _decision(plan_id: str, action: str, body: DecisionIn, request: Request):
    user = current_user(request)
    _therapist(user)
    plan = db.one("SELECT * FROM plan_drafts WHERE id=? AND therapist_user_id=?", plan_id, user["id"])
    if not plan:
        raise HTTPException(404, "No accessible plan")
    status = "approved" if action == "approve" else "changes_requested"
    now = db.now()
    with db.tx() as c:
        c.execute("UPDATE plan_drafts SET status=?, updated_at=? WHERE id=?", (status, now, plan_id))
        c.execute("UPDATE patient_intakes SET status=?, updated_at=? WHERE id=?", (status, now, plan["intake_id"]))
        c.execute("INSERT INTO plan_approvals (plan_id,therapist_user_id,action,notes,created_at) VALUES (?,?,?,?,?)",
                  (plan_id, user["id"], action, body.notes, now))
        if action == "approve":
            # The approved plan becomes the patient's exercise protocol, which is what the video analysis uses
            # (exercise-specific models, rep target, pain threshold, reference video).
            intake = c.execute("SELECT patient_user_id FROM patient_intakes WHERE id=?", (plan["intake_id"],)).fetchone()
            pid = intake["patient_user_id"]
            prof = c.execute("SELECT name FROM patient_profiles WHERE user_id=?", (pid,)).fetchone()
            c.execute("INSERT OR IGNORE INTO patients (id,name,condition,created_at) VALUES (?,?,?,?)",
                      (pid, prof["name"] if prof else pid, None, now))
            ver = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM protocols WHERE patient_id=?", (pid,)).fetchone()[0]
            therapist = c.execute("SELECT name FROM therapist_profiles WHERE user_id=?", (user["id"],)).fetchone()
            c.execute("INSERT INTO protocols (patient_id,version,exercise,target_reps,target_depth_deg,pain_threshold,tempo,"
                      "reference_video_id,notes,approved_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (pid, ver, plan["exercise"], plan["target_reps"], plan["target_depth_deg"] or 100,
                       plan["pain_threshold"], plan["instructions"], plan["reference_video_id"], plan["notes"],
                       therapist["name"] if therapist else user["email"], now))
    return db.one("SELECT * FROM plan_drafts WHERE id=?", plan_id)


@router.post("/therapist/plans/{plan_id}/approve")
def approve_plan(plan_id: str, body: DecisionIn, request: Request):
    return _decision(plan_id, "approve", body, request)


@router.post("/therapist/plans/{plan_id}/request-changes")
def request_changes(plan_id: str, body: DecisionIn, request: Request):
    return _decision(plan_id, "request_changes", body, request)

@router.get("/patient/care-team")
def patient_care_team(request: Request):
    user = current_user(request)
    if user["role"] != "patient":
        raise HTTPException(403, "Patient account required")
    rows = db.all_("SELECT DISTINCT u.id, u.email, tp.name FROM patient_intakes i JOIN users u ON u.id=i.assigned_therapist_id LEFT JOIN therapist_profiles tp ON tp.user_id=u.id WHERE i.patient_user_id=? AND i.assigned_therapist_id IS NOT NULL ORDER BY i.updated_at DESC", user["id"])
    return {"therapist": rows[0] if rows else None}

@router.post("/therapist/intakes/{intake_id}/claim")
def claim_intake(intake_id: str, request: Request):
    user = current_user(request)
    _therapist(user)
    intake = db.one("SELECT * FROM patient_intakes WHERE id=?", intake_id)
    if not intake:
        raise HTTPException(404, "No such intake")
    if intake["assigned_therapist_id"] and intake["assigned_therapist_id"] != user["id"]:
        raise HTTPException(409, "This patient already has a therapist")
    if not _matches_specialization(user["id"], intake):
        raise HTTPException(403, "This request does not match your specialization")
    with db.tx() as c:
        c.execute("UPDATE patient_intakes SET assigned_therapist_id=?, status='under_review', updated_at=? WHERE id=?", (user["id"], db.now(), intake_id))
        _ensure_patient_record(c, intake["patient_user_id"])
        c.execute("INSERT OR REPLACE INTO therapist_intake_decisions (intake_id,therapist_user_id,decision,created_at) VALUES (?,?,?,?)", (intake_id, user["id"], "accepted", db.now()))
    return _intake(db.one("SELECT * FROM patient_intakes WHERE id=?", intake_id))

@router.post("/therapist/intakes/{intake_id}/decline")
def decline_intake(intake_id: str, request: Request):
    user = current_user(request)
    _therapist(user)
    intake = db.one("SELECT * FROM patient_intakes WHERE id=?", intake_id)
    if not intake:
        raise HTTPException(404, "No such intake")
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO therapist_intake_decisions (intake_id,therapist_user_id,decision,created_at) VALUES (?,?,?,?)", (intake_id, user["id"], "declined", db.now()))
    if intake["assigned_therapist_id"] == user["id"]:
        # Pass the request on to the next matching therapist who has not declined it (or back to the open pool).
        declined = {r["therapist_user_id"] for r in db.all_(
            "SELECT therapist_user_id FROM therapist_intake_decisions WHERE intake_id=? AND decision='declined'", intake_id)}
        nxt = _pick_therapist(json.loads(intake["affected_areas_json"]), declined)
        with db.tx() as c:
            c.execute("UPDATE patient_intakes SET assigned_therapist_id=?, status=?, updated_at=? WHERE id=?",
                      (nxt, "assigned" if nxt else "pending", db.now(), intake_id))
            if nxt:
                _ensure_patient_record(c, intake["patient_user_id"])
    return {"id": intake_id, "decision": "declined"}
