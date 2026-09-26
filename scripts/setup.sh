#!/usr/bin/env bash
# One-time setup on the HP ZGX Nano (aarch64, NVIDIA GB10) or any Linux box with an NVIDIA GPU.
# Rebuilds the fine-tuned VLM adapter from its parts, installs Python/Node deps, fetches the base models.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="${RM_MODELS:-$HOME/models}"
APP_VENV="${RM_APP_VENV:-$HOME/rm-venv}"   # backend + MediaPipe + XGBoost
AI_VENV="${RM_AI_VENV:-$HOME/ft-venv}"     # torch + transformers + peft (VLM, Whisper)

echo "== 1/5 fine-tuned VLM adapter (Qwen3-VL-4B + LoRA, REHAB24-6)"
cd "$ROOT/model/weights/vlm_adapter"
if [ ! -f adapter_model.safetensors ]; then cat adapter_model.safetensors.part-* > adapter_model.safetensors; fi
sha256sum -c SHA256SUMS

echo "== 2/5 app environment ($APP_VENV)"
[ -x "$APP_VENV/bin/python" ] || python3 -m venv "$APP_VENV"
"$APP_VENV/bin/pip" install -q -r "$ROOT/recovery-monitor-backend/requirements.txt" -r "$ROOT/model/requirements.txt"

echo "== 3/5 AI environment ($AI_VENV)"
[ -x "$AI_VENV/bin/python" ] || python3 -m venv "$AI_VENV"
# Tested with torch 2.11 (cu130), transformers 5.17, peft 0.21 on the GB10.
"$AI_VENV/bin/pip" install -q torch torchvision --index-url https://download.pytorch.org/whl/cu130 || "$AI_VENV/bin/pip" install -q torch torchvision
"$AI_VENV/bin/pip" install -q "transformers>=5.17" "peft>=0.21" accelerate fastapi uvicorn pillow numpy soundfile python-multipart huggingface_hub

echo "== 4/5 base models in $MODELS and the MediaPipe pose model"
mkdir -p "$MODELS"
[ -d "$MODELS/Qwen3-VL-4B-Instruct" ] || "$AI_VENV/bin/hf" download Qwen/Qwen3-VL-4B-Instruct --local-dir "$MODELS/Qwen3-VL-4B-Instruct"
[ -d "$MODELS/whisper-large-v3-turbo" ] || "$AI_VENV/bin/hf" download openai/whisper-large-v3-turbo --local-dir "$MODELS/whisper-large-v3-turbo"
if command -v ollama >/dev/null; then ollama pull "${RM_LLM_MODEL:-nemotron-3.5-lightning}" || true
else echo "   Ollama not found: install it for the AI report (the app falls back to a template report without it)."; fi

POSE="${RM_DATA:-$HOME/rm-data}/pose_models"; mkdir -p "$POSE"
[ -f "$POSE/pose_landmarker_full.task" ] || curl -fsSL -o "$POSE/pose_landmarker_full.task" \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task

# Piper text-to-speech (tutorial voice-over), voice en_US-lessac-medium
"$APP_VENV/bin/pip" install -q piper-tts
VOICE="${RM_APP_DATA:-$HOME/rm-data/app8020}/tts/piper"; mkdir -p "$VOICE"
for f in en_US-lessac-medium.onnx en_US-lessac-medium.onnx.json; do
  [ -f "$VOICE/$f" ] || curl -fsSL -o "$VOICE/$f" "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$f"
done

echo "== 5/5 frontend build"
cd "$ROOT/recovery-monitor-frontend" && npm install --no-audit --no-fund && npm run build
echo "Done. Start everything with: scripts/run_all.sh"
