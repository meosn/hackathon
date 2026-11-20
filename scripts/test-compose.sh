#!/bin/sh
# Fresh disposable deployment against the already-built backend image.
set -eu
cd "$(dirname "$0")/.."
project="sourcera-test-$(date +%s)-$$"
export API_PORT=0 FRONTEND_PORT=0 MINIO_CONSOLE_PORT=0 RABBITMQ_MANAGEMENT_PORT=0
export DEMO_MODE=true
compose() { ./scripts/compose.sh -p "$project" "$@"; }
cleanup() { compose down --volumes --remove-orphans; }
trap cleanup EXIT
trap 'exit 1' INT TERM
compose up --no-build --wait --wait-timeout 240 -d api ingestion-worker analysis-worker briefing-worker voice-worker scheduler
address="$(compose port api 8000)"
python3 scripts/demo.py --api "http://$address/api/v1" --third-profile
i=0
while [ "$i" -lt 24 ]; do
  if compose exec -T api python -m app.cli diagnostics --check-delivery; then
    compose exec -T api python -c "from app.diagnostics import diagnostics; d=diagnostics(); assert d['work'].get('ingestion/done')==1 and d['work'].get('analysis/done')==1 and d['pgvector'] and d['vector_index'] and d['audio_objects']>=2, d"
    exit 0
  fi
  i=$((i+1))
  sleep 5
done
exit 1
