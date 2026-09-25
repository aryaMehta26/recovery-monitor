#!/usr/bin/env bash
# Start the local AI service (VLM + Whisper, GPU) on :8100 and the app (API + built UI) on :8020.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_VENV="${RM_APP_VENV:-$HOME/rm-venv}"
AI_VENV="${RM_AI_VENV:-$HOME/ft-venv}"
export RM_APP_DATA="${RM_APP_DATA:-$HOME/rm-data/app8020}"   # the demo data on the Nano
export RM_VLM_ADAPTER="${RM_VLM_ADAPTER:-$ROOT/model/weights/vlm_adapter}"
AI_PORT="${RM_AI_PORT:-8100}"; APP_PORT="${RM_APP_PORT:-8020}"
LOGS="${RM_LOGS:-$HOME/rm-data/logs}"; mkdir -p "$LOGS" "$RM_APP_DATA"

[ -f "$RM_VLM_ADAPTER/adapter_model.safetensors" ] || { echo "Run scripts/setup.sh first (adapter not assembled)"; exit 1; }
up() { ss -ltn | grep -q ":$1 "; }

# Fresh data folder: add the demo patients (needs the REHAB24-6 videos; skipped if they are not on this machine).
if [ ! -f "$RM_APP_DATA/recovery_monitor.sqlite3" ]; then
  (cd "$ROOT/recovery-monitor-backend" && "$APP_VENV/bin/python" -m app.seed) || echo "Demo seed skipped (dataset not found); sign up to create accounts."
fi
# Correct-form reference clips for all six exercises (skips exercises that already have one).
(cd "$ROOT/recovery-monitor-backend" && "$APP_VENV/bin/python" -m app.reference_seed) || echo "Reference clips skipped (dataset not found)."

if up "$AI_PORT"; then echo "AI service already on :$AI_PORT"
else (cd "$ROOT" && nohup "$AI_VENV/bin/uvicorn" model.ai_service:app --host 127.0.0.1 --port "$AI_PORT" > "$LOGS/ai.log" 2>&1 &); echo "AI service starting on :$AI_PORT (log $LOGS/ai.log)"; fi

if up "$APP_PORT"; then echo "App already on :$APP_PORT"
else (cd "$ROOT/recovery-monitor-backend" && RM_AI_SERVICE_URL="http://127.0.0.1:$AI_PORT" nohup "$APP_VENV/bin/uvicorn" main:app --host 127.0.0.1 --port "$APP_PORT" > "$LOGS/app.log" 2>&1 &); echo "App starting on :$APP_PORT (log $LOGS/app.log)"; fi

for i in $(seq 1 60); do curl -sf "http://127.0.0.1:$APP_PORT/api/health" >/dev/null && break; sleep 2; done
curl -s "http://127.0.0.1:$APP_PORT/api/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d["ai"]; print("health:", d["status"], "| vision+speech:", a["vision_and_speech"].get("ok"), "| report LLM:", a["llm"].get("ok"))' || true
echo "Open http://localhost:$APP_PORT  (demo password for seeded accounts: recovery-demo)"
