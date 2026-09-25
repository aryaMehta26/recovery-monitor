"""SQLite persistence (#12). One file, no ORM; JSON columns for the analysis result and rep labels."""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    condition TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS protocols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    version INTEGER NOT NULL,
    exercise TEXT NOT NULL,
    target_reps INTEGER NOT NULL,
    target_depth_deg REAL NOT NULL,
    pain_threshold INTEGER NOT NULL,
    tempo TEXT,
    reference_video_id INTEGER REFERENCES reference_videos(id),
    notes TEXT,
    approved_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (patient_id, version)
);
CREATE TABLE IF NOT EXISTS reference_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    protocol_id INTEGER REFERENCES protocols(id),
    exercise TEXT NOT NULL,
    status TEXT NOT NULL,          -- uploaded | processing | complete | uncertain | rejected_quality | failed
    stage TEXT,                    -- current processing stage for the progress UI
    progress REAL DEFAULT 0,
    error TEXT,
    source TEXT,
    video_path TEXT,
    annotated_path TEXT,
    thumbnail_path TEXT,
    duration_s REAL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS check_ins (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    pain_score INTEGER NOT NULL,
    stiffness INTEGER,
    comment TEXT,
    transcript TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,        -- approve | request_changes
    notes TEXT,
    rep_labels_json TEXT,          -- {"3": "incorrect", "5": "correct"} physio corrections per rep
    reference_video_id INTEGER REFERENCES reference_videos(id),
    reviewer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    report_json TEXT NOT NULL,     -- AI draft for the physiotherapist (see app/report.py)
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('patient', 'therapist')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patient_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    affected_areas_json TEXT NOT NULL DEFAULT '[]',
    goals_json TEXT NOT NULL DEFAULT '[]',
    consent_local_analysis INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS therapist_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS therapist_specializations (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    specialization TEXT NOT NULL,
    PRIMARY KEY (user_id, specialization)
);
CREATE TABLE IF NOT EXISTS therapist_exercises (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise TEXT NOT NULL,
    PRIMARY KEY (user_id, exercise)
);
CREATE TABLE IF NOT EXISTS patient_intakes (
    id TEXT PRIMARY KEY,
    patient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    affected_areas_json TEXT NOT NULL,
    issue_types_json TEXT NOT NULL,
    when_it_happens_json TEXT NOT NULL,
    pain_score INTEGER NOT NULL CHECK (pain_score BETWEEN 0 AND 10),
    duration TEXT NOT NULL,
    trend TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    goals_json TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_therapist_id TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_drafts (
    id TEXT PRIMARY KEY,
    intake_id TEXT NOT NULL REFERENCES patient_intakes(id) ON DELETE CASCADE,
    therapist_user_id TEXT NOT NULL REFERENCES users(id),
    exercise TEXT NOT NULL,
    reference_video_id INTEGER REFERENCES reference_videos(id),
    target_reps INTEGER NOT NULL,
    target_sets INTEGER NOT NULL,
    target_depth_deg REAL,
    pain_threshold INTEGER NOT NULL,
    instructions TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'plan_drafted',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES plan_drafts(id) ON DELETE CASCADE,
    therapist_user_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS therapist_intake_decisions (intake_id TEXT NOT NULL REFERENCES patient_intakes(id) ON DELETE CASCADE, therapist_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, decision TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (intake_id, therapist_user_id));
CREATE INDEX IF NOT EXISTS sessions_patient ON sessions(patient_id, created_at);
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute("PRAGMA journal_mode = WAL")
        _conn.executescript(SCHEMA)
        _migrate(_conn)
    return _conn


# Columns added after the first release; existing databases get them on startup.
ADDED_COLUMNS = {"patient_intakes": {"voice_transcript": "TEXT", "ai_json": "TEXT"}}


def _migrate(c: sqlite3.Connection) -> None:
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, kind in cols.items():
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    c.commit()


@contextmanager
def tx():
    """Serialized write transaction (analysis jobs run in worker threads)."""
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def one(sql: str, *args) -> dict | None:
    with _lock:
        row = conn().execute(sql, args).fetchone()
    return dict(row) if row else None


def all_(sql: str, *args) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def loads(s: str | None):
    return json.loads(s) if s else None


def reset_for_tests(path) -> None:
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None
    import app.config as cfg

    cfg.DB_PATH = path
    globals()["DB_PATH"] = path
