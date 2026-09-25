"""AI intake assistant: the patient describes their problem by voice (Whisper, on this device) and the local LLM
turns it into a structured care request plus a warm reply.
Same safety approach as the session report:
- red flags come from fixed rules, never from the LLM
- the pain score is only filled in if the patient actually said a number
- the suggested exercise must fit the body area; otherwise a rule-based default is used
- if the LLM is unavailable, simple keyword rules still produce a usable request
The therapist makes every clinical decision; the AI only prepares the request."""

import json
import re
import time

import httpx

from app.config import LLM_MODEL, LLM_URL
from app.report import RED_FLAG_WORDS

AREAS = ["knee", "hip", "ankle_foot", "back_core", "shoulder_arm", "elbow_forearm", "wrist_hand", "general_mobility", "other"]
ISSUES = ["pain_during_movement", "weakness", "limited_range_of_motion", "balance_or_stability", "difficulty_exercising", "stiffness"]
WHEN = ["during_movement", "at_rest", "at_night", "morning", "after_exercise"]
DURATIONS = ["less_than_two_weeks", "two_to_six_weeks", "one_to_three_months", "more_than_three_months", "unknown"]
TRENDS = ["improving", "unchanged", "getting_worse", "unknown"]
GOALS = ["improve_strength", "daily_activities", "general_conditioning", "return_to_sport", "reduce_pain"]
MOODS = ["calm", "hopeful", "worried", "frustrated", "in_pain"]
EXERCISES = ["squat", "leg_lunge", "leg_abduction", "arm_abduction", "arm_vw", "push_ups"]
LOWER, UPPER = {"knee", "hip", "ankle_foot", "back_core"}, {"shoulder_arm", "elbow_forearm", "wrist_hand"}
# Which of our six analysable exercises make sense to start from, per area (the physio can pick any).
FITS = {"knee": {"squat", "leg_lunge"}, "hip": {"leg_abduction", "squat", "leg_lunge"}, "ankle_foot": {"leg_lunge", "squat"},
        "back_core": {"squat", "leg_abduction"}, "shoulder_arm": {"arm_abduction", "arm_vw"},
        "elbow_forearm": {"push_ups", "arm_vw"}, "wrist_hand": {"push_ups"}}
DEFAULT_EXERCISE = {"knee": "squat", "hip": "leg_abduction", "ankle_foot": "leg_lunge", "back_core": "squat",
                    "shoulder_arm": "arm_abduction", "elbow_forearm": "push_ups", "wrist_hand": "push_ups"}

_arr = lambda enum, n: {"type": "array", "items": {"type": "string", "enum": enum}, "maxItems": n}  # noqa: E731
SCHEMA = {
    "type": "object",
    "properties": {
        "reply_to_patient": {"type": "string", "minLength": 40, "maxLength": 420},
        "summary_for_therapist": {"type": "string", "minLength": 40, "maxLength": 600},
        "affected_areas": _arr(AREAS, 3),
        "issue_types": _arr(ISSUES, 4),
        "when_it_happens": _arr(WHEN, 4),
        "pain_score": {"type": "integer", "minimum": -1, "maximum": 10},
        "duration": {"type": "string", "enum": DURATIONS},
        "trend": {"type": "string", "enum": TRENDS},
        "limitations": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 4},
        "goals": _arr(GOALS, 3),
        "mood": {"type": "string", "enum": MOODS},
        "suggested_exercise": {"type": "string", "enum": EXERCISES},
        "exercise_reason": {"type": "string", "maxLength": 200},
        "follow_up_questions": {"type": "array", "items": {"type": "string", "maxLength": 140}, "maxItems": 3},
    },
    "required": ["reply_to_patient", "summary_for_therapist", "affected_areas", "issue_types", "when_it_happens",
                 "pain_score", "duration", "trend", "limitations", "goals", "mood", "suggested_exercise",
                 "exercise_reason", "follow_up_questions"],
}
SYSTEM = f"""You are the intake assistant of a physiotherapy clinic. A patient describes, in their own words, the
problem they want help with. You prepare a request for a physiotherapist and reply kindly to the patient.
Rules:
- Use ONLY what the patient said (and the areas they ticked). Never invent symptoms, history or numbers.
- pain_score: the number the patient said (0-10). If they did not say a number, use -1.
- duration / trend: only if the patient said it, otherwise "unknown".
- Do not diagnose, do not name medical conditions, do not give medical advice.
- reply_to_patient: 2-3 warm sentences, speaking to the patient ("you"). Acknowledge how they feel, show you
  understood the main problem, and say a physiotherapist will look at their request. Never promise timing
  (no "right away", "soon", "today"), no promises, no advice.
- summary_for_therapist: 2-3 factual sentences for a clinician: where, what, when it happens, how long, what they
  want to get back to.
- mood: the patient's emotional tone.
- suggested_exercise: the best fit from this list for the affected area, for the physiotherapist to consider:
  squat, leg_lunge, leg_abduction (knee/hip/leg), arm_abduction, arm_vw, push_ups (shoulder/arm). exercise_reason: one
  short sentence.
- follow_up_questions: 1-3 short questions the physiotherapist could ask next.
Allowed values: areas {AREAS}; issues {ISSUES}; when {WHEN}; goals {GOALS}."""

NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10}
AREA_WORDS = {"knee": ["knee"], "hip": ["hip", "groin"], "ankle_foot": ["ankle", "foot", "feet", "heel"],
              "back_core": ["back", "spine", "core"], "shoulder_arm": ["shoulder", "arm", "rotator"],
              "elbow_forearm": ["elbow", "forearm"], "wrist_hand": ["wrist", "hand", "finger"]}


def said_numbers(text: str) -> set[int]:
    t = text.lower()
    found = {int(n) for n in re.findall(r"\b(\d{1,2})\b", t) if int(n) <= 10}
    found |= {v for w, v in NUMBER_WORDS.items() if re.search(rf"\b{w}\b", t)}
    return found


def said_pain(text: str) -> int | None:
    """"six out of ten", "6/10", "pain is about 7" -> the number the patient gave for their pain."""
    t = text.lower()
    num = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"
    m = re.search(num + r"\s*(?:out of|/)\s*(?:10|ten)\b", t) or re.search(r"pain[^.]{0,25}?\b" + num + r"\b(?!\s*(?:day|week|month|year))", t)
    if not m:
        return None
    v = NUMBER_WORDS.get(m.group(1), None)
    v = int(m.group(1)) if v is None else v
    return v if 0 <= v <= 10 else None


def red_flags(text: str, pain: int | None) -> list[str]:
    flags = []
    if pain is not None and pain >= 8:
        flags.append(f"Severe pain reported ({pain}/10)")
    hits = sorted({w.strip() for w in RED_FLAG_WORDS if w in text.lower()})
    if hits:
        flags.append("Patient mentioned: " + ", ".join(hits))
    return flags


def keyword_areas(text: str) -> list[str]:
    """Whole words only ("football" is not a foot, "get back to it" is not a back)."""
    t = text.lower()
    return [a for a, words in AREA_WORDS.items()
            if any(re.search(rf"\b{w}s?\b(?! to\b)", t) for w in words)]


UNIT_WEEKS = {"day": 1 / 7, "week": 1, "month": 4.35, "year": 52}


def said_duration(text: str) -> str | None:
    """Duration from the patient's own words ("about two months", "3 weeks", "a year"), bucketed."""
    t = text.lower()
    m = re.search(r"\b(\d{1,2}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|few|couple of)\s+(day|week|month|year)s?\b", t)
    if not m:
        return None
    n = {"a": 1, "an": 1, "few": 3, "couple of": 2}.get(m.group(1)) or NUMBER_WORDS.get(m.group(1)) or int(m.group(1))
    weeks = n * UNIT_WEEKS[m.group(2)]
    return ("less_than_two_weeks" if weeks < 2 else "two_to_six_weeks" if weeks < 6
            else "one_to_three_months" if weeks <= 13.1 else "more_than_three_months")


def fit_exercise(exercise: str | None, areas: list[str]) -> str:
    """Keep the model's suggestion only if it suits the main (first) body area; otherwise that area's default."""
    main = next((a for a in areas if a in FITS), None)
    if main is None:
        return exercise if exercise in EXERCISES else "squat"
    return exercise if exercise in FITS[main] else DEFAULT_EXERCISE[main]


def fallback(text: str, areas: list[str]) -> dict:
    pain = said_pain(text)
    pain = -1 if pain is None else pain
    return {
        "reply_to_patient": "Thank you for telling us about this. We have noted what you described, and a "
                            "physiotherapist will look at your request and get back to you with a plan.",
        "summary_for_therapist": ("Patient's own words: " + text.strip())[:600] if text.strip() else "No description given.",
        "affected_areas": areas, "issue_types": ["pain_during_movement"] if "pain" in text.lower() else [],
        "when_it_happens": [], "pain_score": pain, "duration": "unknown", "trend": "unknown", "limitations": [],
        "goals": [], "mood": "worried" if "pain" in text.lower() else "calm", "suggested_exercise": None,
        "exercise_reason": "Default exercise for this body area.", "follow_up_questions": [],
    }


def assist(text: str, ticked_areas: list[str] | None = None) -> dict:
    ticked = [a for a in (ticked_areas or []) if a in AREAS]
    t0 = time.time()
    out, source = None, "rules"
    try:
        r = httpx.post(f"{LLM_URL}/api/chat", timeout=120, json={
            "model": LLM_MODEL, "stream": False, "think": False, "format": SCHEMA, "keep_alive": "2h",
            "options": {"temperature": 0.3, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps({"areas_ticked": ticked, "patient_said": text})}]})
        r.raise_for_status()
        out, source = json.loads(r.json()["message"]["content"]), "llm"
    except Exception:  # noqa: BLE001 — the request still works without the LLM
        out = fallback(text, ticked or keyword_areas(text))
    # Guards: nothing the patient did not say.
    stated = said_pain(text)
    if stated is not None:
        out["pain_score"] = stated
    elif out.get("pain_score", -1) not in said_numbers(text):
        out["pain_score"] = -1
    out["duration"] = said_duration(text) or "unknown"
    llm_areas = [a for a in out.get("affected_areas", []) if a in AREAS]
    # Keep model areas that the patient ticked or named; ticked areas always count.
    named = set(keyword_areas(text)) | set(ticked)
    areas = list(dict.fromkeys(ticked + [a for a in llm_areas if a in named or not named]))[:4]
    out["affected_areas"] = areas or ["general_mobility"]
    out["suggested_exercise"] = fit_exercise(out.get("suggested_exercise"), out["affected_areas"])
    pain = out["pain_score"] if out["pain_score"] >= 0 else None
    return {**out, "pain_score": pain, "red_flags": red_flags(text, pain), "urgent": bool(red_flags(text, pain)),
            "source": source, "model": LLM_MODEL if source == "llm" else None, "seconds": round(time.time() - t0, 1)}
