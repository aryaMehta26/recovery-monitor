"""Backend settings. Everything is local: data under RM_APP_DATA, models from the repo's model/ package."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(REPO_ROOT) not in sys.path:  # make the repo's `model` package importable
    sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = Path(os.getenv("RM_APP_DATA", BACKEND_DIR / "data"))
DB_PATH = DATA_DIR / "recovery_monitor.sqlite3"
VIDEO_DIR = DATA_DIR / "videos"
REFERENCE_DIR = DATA_DIR / "reference_videos"
TUTORIAL_MEDIA_DIR = DATA_DIR / "tutorial_media"
for d in (DATA_DIR, VIDEO_DIR, REFERENCE_DIR, TUTORIAL_MEDIA_DIR):
    d.mkdir(parents=True, exist_ok=True)

MODEL_RESULTS = REPO_ROOT / "model" / "results"

MAX_UPLOAD_MB = int(os.getenv("RM_MAX_UPLOAD_MB", "300"))
ALLOWED_VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
MAX_CONCURRENT_ANALYSES = int(os.getenv("RM_MAX_CONCURRENT_ANALYSES", "2"))

# Local AI endpoints (LLM summary / Whisper, later). Checked at startup: must be on this device.
LLM_URL = os.getenv("RM_LLM_URL", "http://127.0.0.1:11434")          # Ollama now; ZRT when enabled
LLM_MODEL = os.getenv("RM_LLM_MODEL", "nemotron-3.5-lightning")
AI_SERVICE_URL = os.getenv("RM_AI_SERVICE_URL", "http://127.0.0.1:8100")  # fine-tuned VLM + Whisper (GPU)
AI_ENDPOINTS = [LLM_URL, AI_SERVICE_URL]

DEVICE_NAME = os.getenv("RM_DEVICE_NAME", "HP ZGX Nano (NVIDIA GB10)")
CORS_ORIGINS = os.getenv("RM_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
