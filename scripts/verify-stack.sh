#!/bin/sh
# Run from an already-started demo deployment. Creates private test listeners and briefings.
set -eu
cd "$(dirname "$0")/.."
python3 scripts/demo.py --third-profile --api "${SOURCERA_API:-http://127.0.0.1:8000/api/v1}"
# Wait for the next Beat delivery tick, validating real committed consumer receipts.
i=0
while [ "$i" -lt 24 ]; do
  if ./scripts/compose.sh exec -T api python -m app.cli diagnostics --check-delivery; then exit 0; fi
  i=$((i+1))
  sleep 5
done
exit 1
