"""Therapist-reviewed tutorial drafts built only from verified session facts."""

import json
import re
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import db
from app.config import LLM_MODEL, LLM_URL


class TutorialDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise: str = Field(min_length=1, max_length=80)
    target_repetitions: int = Field(ge=1, le=100)
    target_depth_deg: float | None = Field(None, ge=30, le=175)
    verified_findings: list[str] = Field(min_length=1, max_length=8)
    coaching_cues: list[str] = Field(max_length=6)
    warnings: list[str] = Field(max_length=6)
    captions: list[str] = Field(min_length=1, max_length=8)
    script: str = Field(min_length=20, max_length=1200)


SYSTEM = """Create a therapist-review tutorial draft from VERIFIED_FACTS only.
Return JSON matching the supplied schema and no markdown.
Rules:
- Do not diagnose, prescribe, or invent measurements, symptoms, warnings, or treatment instructions.
- exercise, target_repetitions, and target_depth_deg must exactly match the verified facts.
- verified_findings may only restate the verified movement findings.
- coaching_cues and warnings must be grounded in the findings, quality instructions, or approved plan.
- captions and script are educational wording for the approved exercise, not a new treatment plan.
- Never add a number that is not present in VERIFIED_FACTS.
"""


def _numbers(value: str) -> set[str]:
    return {n.rstrip(".").lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", value)}


def _verified_facts(session_id: str, reference_video_id: int) -> dict:
    session = db.one("SELECT * FROM sessions WHERE id = ?", session_id)
    if not session or not session["result_json"]:
        raise ValueError("session not found or not analysed")
    result = db.loads(session["result_json"]) or {}
    protocol = db.one("SELECT * FROM protocols WHERE id = ?", session["protocol_id"]) if session["protocol_id"] else None
    reference = db.one("SELECT id, exercise, title FROM reference_videos WHERE id = ? AND approval_status='approved'",
                       reference_video_id)
    if not reference:
        raise ValueError("approved reference video not found")

    exercise = result.get("exercise") or session["exercise"]
    if reference["exercise"] != exercise:
        raise ValueError("reference video exercise does not match the source session")
    metrics = result.get("metrics") or {}
    reps = result.get("reps") or []
    findings = [f"Video analysis measured {result.get('repetitions') or 0} repetitions."]
    if result.get("correct_repetitions") is not None:
        findings.append(f"{result['correct_repetitions']} repetitions were classified as correct by the movement model.")
    if metrics.get("median_depth_deg") is not None:
        findings.append(f"Median measured depth was {metrics['median_depth_deg']} degrees.")
    seen = set()
    for rep in reps:
        for reason in rep.get("flag_reasons") or []:
            message = reason.get("message")
            if message and message not in seen:
                findings.append(message)
                seen.add(message)
    quality = result.get("quality") or {}
    warnings = list(quality.get("instructions") or [])
    check_in = db.one("SELECT pain_score, comment, transcript FROM check_ins WHERE session_id = ?", session_id) or {}
    if check_in.get("pain_score") is not None:
        warnings.append(f"Patient reported pain {check_in['pain_score']}/10 during check-in.")
    patient_words = " / ".join(x for x in (check_in.get("transcript"), check_in.get("comment")) if x) or "(nothing yet)"
    target_reps = protocol["target_reps"] if protocol else result.get("repetitions") or 1
    target_depth = protocol["target_depth_deg"] if protocol else None
    return {
        "source_session_id": session_id,
        "exercise": exercise,
        "target_repetitions": target_reps,
        "target_depth_deg": target_depth,
        "verified_findings": findings[:8],
        "warnings": warnings[:6],
        "patient_words": patient_words[:400],
        "approved_reference_video": {"id": reference["id"], "title": reference["title"], "exercise": reference["exercise"]},
        "approved_plan": protocol and {"target_reps": protocol["target_reps"], "target_depth_deg": protocol["target_depth_deg"],
                                        "tempo": protocol["tempo"], "notes": protocol["notes"]},
    }


def _fallback(facts: dict) -> TutorialDraft:
    cues = [item for item in facts["verified_findings"] if any(word in item.lower() for word in ("lean", "depth", "pause", "speed"))][:3]
    cues = cues or ["Follow the approved exercise plan and move with control."]
    warnings = facts["warnings"][:]
    captions = [f"Perform {facts['target_repetitions']} repetitions of the approved {facts['exercise']}.",
                "Use the movement cues from your physiotherapist."]
    script = (f"Set up for the approved {facts['exercise']} exercise. Follow the reference video, "
              f"complete {facts['target_repetitions']} repetitions, and stop if the warnings apply. "
              "Your physiotherapist will review this tutorial before it is shared.")
    return TutorialDraft(exercise=facts["exercise"], target_repetitions=facts["target_repetitions"],
                         target_depth_deg=facts["target_depth_deg"], verified_findings=facts["verified_findings"],
                         coaching_cues=cues, warnings=warnings, captions=captions, script=script)


def _validate_against_facts(draft: TutorialDraft, facts: dict) -> list[str]:
    errors = []
    if draft.exercise != facts["exercise"]:
        errors.append("exercise differs from verified session")
    if draft.target_repetitions != facts["target_repetitions"]:
        errors.append("target repetitions differ from approved plan")
    if draft.target_depth_deg != facts["target_depth_deg"]:
        errors.append("target depth differs from approved plan")
    allowed = _numbers(json.dumps(facts)) | {str(i) for i in range(0, 11)}
    text = " ".join(draft.verified_findings + draft.coaching_cues + draft.warnings + draft.captions + [draft.script])
    unknown = {n for n in _numbers(text) if n not in allowed and n.split(".")[0] not in allowed}
    if unknown:
        errors.append("contains numbers absent from verified facts: " + ", ".join(sorted(unknown)))
    return errors


def _validate_facts(facts: dict) -> list[str]:
    errors = []
    if not isinstance(facts.get("exercise"), str) or not facts["exercise"].strip():
        errors.append("exercise is missing from verified facts")
    target_reps = facts.get("target_repetitions")
    if not isinstance(target_reps, int) or isinstance(target_reps, bool) or not 1 <= target_reps <= 100:
        errors.append("target repetitions are unsupported")
    target_depth = facts.get("target_depth_deg")
    if target_depth is not None and (not isinstance(target_depth, (int, float)) or not 30 <= target_depth <= 175):
        errors.append("target depth is unsupported")
    reference = facts.get("approved_reference_video") or {}
    if reference.get("exercise") != facts.get("exercise"):
        errors.append("approved reference exercise does not match verified exercise")
    if not facts.get("verified_findings"):
        errors.append("verified findings are missing")
    return errors


def generate(session_id: str, reference_video_id: int) -> tuple[dict, dict]:
    facts = _verified_facts(session_id, reference_video_id)
    fact_errors = _validate_facts(facts)
    if fact_errors:
        raise ValueError("Unsupported verified facts: " + "; ".join(fact_errors))
    started = time.time()
    source = "fallback"
    problems = []
    draft = None
    try:
        response = httpx.post(f"{LLM_URL}/api/chat", timeout=180, json={
            "model": LLM_MODEL, "stream": False, "think": False, "format": TutorialDraft.model_json_schema(),
            "keep_alive": "2h", "options": {"temperature": 0.1, "num_ctx": 12000},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "VERIFIED_FACTS:\n" + json.dumps(facts, indent=2)}],
        })
        response.raise_for_status()
        content = response.json()["message"]["content"]
        draft = TutorialDraft.model_validate(json.loads(content))
        errors = _validate_against_facts(draft, facts)
        if errors:
            problems.extend(errors)
            draft = None
        else:
            source = "llm"
    except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as error:
        problems.append(str(error)[:240])
    if draft is None:
        draft = _fallback(facts)
    deterministic_errors = _validate_against_facts(draft, facts)
    validation = {"schema_valid": True, "facts_verified": not deterministic_errors,
                  "deterministic_errors": deterministic_errors,
                  "problems": problems, "seconds": round(time.time() - started, 1)}
    return draft.model_dump(), {"source": source, "validation": validation, "facts": facts}
