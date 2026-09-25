"""Backend-only Phase 1 tests for therapist-reviewed AI tutorial drafts."""

import json
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app import tutorial as tutorial_module
from app.auth import hash_password

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "analysis_result.json").read_text())


@pytest.fixture()
def client(monkeypatch):
    import app.jobs
    import model.pipeline

    def fake_pipeline(path, planned_exercise, protocol, baseline=None, annotated_path=None, progress=None,
                      work_dir=None):
        if annotated_path:
            shutil.copy(path, annotated_path)
        result = json.loads(json.dumps(FIXTURE))
        result.update(protocol=protocol)
        return result

    monkeypatch.setattr(model.pipeline, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(app.jobs, "submit_report", lambda sid: None)
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": self.content}}


def _source(client, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    email = f"tutorial-patient-{suffix}@example.com"
    assert client.post("/api/auth/signup", json={"email": email, "password": "development-password", "role": "patient"}).status_code == 201
    patient = client.get("/api/auth/me").json()["user"]
    assert client.put("/api/onboarding/patient", json={"name": "Tutorial Patient", "affected_areas": ["knee"],
                                                        "goals": ["improve_strength"], "consent_local_analysis": True}).status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "therapist.demo@example.com", "password": "recovery-demo"}).status_code == 200
    with db.tx() as c:
        c.execute("INSERT INTO patients (id,name,condition,created_at) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                  (patient["id"], "Tutorial Patient", "knee", db.now()))
        protocol_id = c.execute(
            "INSERT INTO protocols (patient_id,version,exercise,target_reps,target_depth_deg,pain_threshold,tempo,notes,approved_by,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", (patient["id"], 1, "squat", 5, 100, 5, "Slow and controlled", "Use a side view", "Test Therapist", db.now())
        ).lastrowid
        reference_id = c.execute(
            "INSERT INTO reference_videos (exercise,title,path,source,created_at) VALUES (?,?,?,?,?)",
            ("squat", "Approved squat reference", "/tmp/reference.mp4", "test", db.now()),
        ).lastrowid
        session_id = f"tutorial-session-{suffix}"
        result = {"exercise": "squat", "status": "complete", "repetitions": 5, "correct_repetitions": 4,
                  "metrics": {"median_depth_deg": 98.0}, "reps": [{"index": 1, "predicted_correct": False,
                  "flag_reasons": [{"message": "Moved too quickly", "value": 2, "unit": "s"}]}],
                  "quality": {"instructions": ["Stand side-on to the camera."]}}
        c.execute("INSERT INTO sessions (id,patient_id,protocol_id,exercise,status,stage,progress,result_json,created_at,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", (session_id, patient["id"], protocol_id, "squat", "complete", "done", 1,
                                                    json.dumps(result), db.now(), db.now()))
        c.execute(
            "INSERT INTO patient_intakes (id,patient_user_id,affected_areas_json,issue_types_json,when_it_happens_json,"
            "pain_score,duration,trend,limitations_json,goals_json,notes,status,assigned_therapist_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"intake-{suffix}", patient["id"], '["knee"]', '["stiffness"]', '["exercise"]', 2,
             "1 week", "stable", '[]', '["strength"]', "", "under_review", "demo-therapist", db.now(), db.now()),
        )
        c.execute("INSERT INTO reviews (session_id,decision,notes,rep_labels_json,reviewer,created_at) VALUES (?,?,?,?,?,?)",
                  (session_id, "approve", "Reviewed for tutorial", "{}", "Test Therapist", db.now()))
    return patient, session_id, reference_id


def _valid_llm(monkeypatch):
    content = json.dumps({
        "exercise": "squat", "target_repetitions": 5, "target_depth_deg": 100,
        "verified_findings": ["Video analysis measured 5 repetitions.", "Moved too quickly."],
        "coaching_cues": ["Use a controlled pace."],
        "warnings": ["Stand side-on to the camera."],
        "captions": ["Perform 5 repetitions of the approved squat."],
        "script": "Follow the approved squat reference and complete 5 repetitions. Stop if the warning applies.",
    })
    monkeypatch.setattr(tutorial_module.httpx, "post", lambda *args, **kwargs: FakeLLMResponse(content))


def test_valid_tutorial_creation(monkeypatch, client):
    _, session_id, reference_id = _source(client, "valid")
    _valid_llm(monkeypatch)
    response = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["generation_source"] == "llm"
    assert body["exercise"] == "squat"
    assert body["source_session_id"] == session_id
    assert body["reference_video"]["id"] == reference_id


def test_invalid_llm_output_uses_deterministic_fallback(monkeypatch, client):
    _, session_id, reference_id = _source(client, "fallback")
    monkeypatch.setattr(tutorial_module.httpx, "post", lambda *args, **kwargs: FakeLLMResponse('{"exercise":"made_up"}'))
    response = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["generation_source"] == "fallback"
    assert body["validation"]["problems"]
    assert body["target_reps"] == 5


def test_tutorial_approval_and_patient_visibility(monkeypatch, client):
    patient, session_id, reference_id = _source(client, "approval")
    _valid_llm(monkeypatch)
    draft = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).json()
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": f"tutorial-patient-approval@example.com", "password": "development-password"}).status_code == 200
    assert client.get(f"/api/tutorials/{draft['id']}").status_code == 403
    assert client.get("/api/patient/tutorials").json() == []
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "therapist.demo@example.com", "password": "recovery-demo"}).status_code == 200
    approved = client.post(f"/api/tutorials/{draft['id']}/approve", json={"notes": "Reviewed"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "tutorial-patient-approval@example.com", "password": "development-password"}).status_code == 200
    assert client.get(f"/api/tutorials/{draft['id']}").json()["status"] == "approved"
    assert client.get("/api/patient/tutorials").json()[0]["id"] == draft["id"]


def test_tutorial_unauthorized_access(client):
    _, session_id, reference_id = _source(client, "unauthorized")
    client.cookies.clear()
    assert client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).status_code == 401


def test_unapproved_reference_video_is_rejected(monkeypatch, client):
    _, session_id, reference_id = _source(client, "unapproved-reference")
    with db.tx() as c:
        c.execute("UPDATE reference_videos SET approval_status='pending' WHERE id=?", (reference_id,))
    response = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id})
    assert response.status_code == 422
    assert "approved reference video" in response.json()["detail"]


def test_unassigned_therapist_cannot_access_session_or_tutorial(monkeypatch, client):
    _, session_id, reference_id = _source(client, "cross-therapist")
    _valid_llm(monkeypatch)
    draft = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).json()
    with db.tx() as c:
        c.execute("INSERT INTO users (id,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                  ("other-therapist", "other-therapist@example.com", hash_password("development-password"),
                   "therapist", db.now()))
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "other-therapist@example.com",
                                                 "password": "development-password"}).status_code == 200
    assert client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).status_code == 403
    assert client.get(f"/api/tutorials/{draft['id']}").status_code == 403
    assert client.post(f"/api/tutorials/{draft['id']}/approve", json={"notes": "no"}).status_code == 403
    assert client.post(f"/api/tutorials/{draft['id']}/request-changes", json={"notes": "no"}).status_code == 403


def test_unsupported_facts_are_rejected_deterministically():
    facts = {"exercise": "squat", "target_repetitions": 0, "target_depth_deg": 100,
             "approved_reference_video": {"exercise": "squat"}, "verified_findings": ["measured"]}
    assert "target repetitions are unsupported" in tutorial_module._validate_facts(facts)


def test_request_changes_notes_are_saved_and_returned(monkeypatch, client):
    _, session_id, reference_id = _source(client, "request-notes")
    _valid_llm(monkeypatch)
    draft = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).json()
    response = client.post(f"/api/tutorials/{draft['id']}/request-changes",
                           json={"notes": "Please clarify the controlled pace cue."})
    assert response.status_code == 200
    assert response.json()["status"] == "request_changes"
    assert response.json()["request_changes_notes"] == "Please clarify the controlled pace cue."
    assert client.get(f"/api/tutorials/{draft['id']}").json()["request_changes_notes"] == \
        "Please clarify the controlled pace cue."


def test_media_generation_is_local_and_patient_gated(monkeypatch, client, tiny_video):
    _, session_id, reference_id = _source(client, "media")
    with db.tx() as c:
        c.execute("UPDATE reference_videos SET path=? WHERE id=?", (str(tiny_video), reference_id))
    _valid_llm(monkeypatch)
    draft = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).json()

    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "tutorial-patient-media@example.com",
                                                 "password": "development-password"}).status_code == 200
    assert client.get(f"/api/tutorials/{draft['id']}/media").status_code == 403

    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "therapist.demo@example.com",
                                                 "password": "recovery-demo"}).status_code == 200
    from app import jobs as jobs_module
    monkeypatch.setattr(jobs_module, "submit_tutorial_media",
                        lambda tutorial_id, voice_enabled=False: jobs_module.run_tutorial_media(tutorial_id, voice_enabled))
    queued = client.post(f"/api/tutorials/{draft['id']}/media", json={"voice_enabled": True})
    assert queued.status_code == 202
    assert queued.json()["media_status"] == "queued"

    ready = client.get(f"/api/tutorials/{draft['id']}").json()
    assert ready["media"]["status"] == "ready"
    assert ready["media"]["voice_status"] == "unavailable"

    approved = client.post(f"/api/tutorials/{draft['id']}/approve", json={"notes": "Media reviewed"})
    assert approved.status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "tutorial-patient-media@example.com",
                                                 "password": "development-password"}).status_code == 200
    media = client.get(f"/api/tutorials/{draft['id']}/media")
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("video/mp4")
    assert len(media.content) > 100


def test_patient_cannot_start_tutorial_media(monkeypatch, client, tiny_video):
    _, session_id, reference_id = _source(client, "media-auth")
    with db.tx() as c:
        c.execute("UPDATE reference_videos SET path=? WHERE id=?", (str(tiny_video), reference_id))
    _valid_llm(monkeypatch)
    draft = client.post(f"/api/sessions/{session_id}/tutorials", json={"reference_video_id": reference_id}).json()
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "tutorial-patient-media-auth@example.com",
                                                 "password": "development-password"}).status_code == 200
    assert client.post(f"/api/tutorials/{draft['id']}/media", json={}).status_code == 403
