#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if docker compose version >/dev/null 2>&1; then
  exec docker compose "$@"
fi
exec docker-compose "$@"
