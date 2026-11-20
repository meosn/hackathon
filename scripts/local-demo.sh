#!/bin/sh
# Lightweight single-machine profile. All runtime data lives outside source directories.
set -eu
cd "$(dirname "$0")/.."
root="$(pwd)"
mkdir -p .local/demo
if [ ! -x .venv/bin/python ]; then python3.12 -m venv .venv; fi
.venv/bin/pip install -e './backend[test]'
(cd frontend && npm ci)
export DATABASE_URL="sqlite:///$root/.local/demo/sourcera.db"
export AUDIO_DIR="$root/.local/demo/audio" STATE_DIR="$root/.local/demo/state" AUDIO_STORAGE=local JOB_MODE=local
export DEMO_MODE=true TTS_PROVIDER=local LLM_PROVIDER=mock STT_PROVIDER=mock
export EMBEDDING_PROVIDER=local_hash
export API_PORT="${API_PORT:-8000}" FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export CORS_ORIGINS="http://127.0.0.1:$FRONTEND_PORT,http://localhost:$FRONTEND_PORT"
(cd backend && ../.venv/bin/python -m app.cli bootstrap)
(cd backend && exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --no-access-log) &
api=$!
trap 'kill "$api" "${ui:-}" 2>/dev/null || true' EXIT
trap 'exit 0' HUP INT TERM
(cd frontend && API_PROXY_TARGET="http://127.0.0.1:$API_PORT" exec npm run dev -- --port "$FRONTEND_PORT" --strictPort --host 127.0.0.1) &
ui=$!
wait "$ui"
