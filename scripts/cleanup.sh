#!/bin/sh
# Removes all Sourcera users, licensed imports, derived material, queues and audio.
set -eu
cd "$(dirname "$0")/.."
if [ "${1:-}" != "--confirm" ]; then
  echo "Use scripts/cleanup.sh --confirm to erase this deployment, all volumes and the contents of its dedicated datasets/ directory."
  exit 2
fi
scripts/compose.sh down --volumes --remove-orphans
python3 - <<'PY'
from pathlib import Path
import shutil
root=Path.cwd()
for name in ("datasets",".data"):
    target=root/name
    if target.is_symlink():
        raise SystemExit("Refusing to traverse linked data directory: "+str(target))
    if target.is_dir():
        shutil.rmtree(target)
for path in (root/".local"/"demo",root/"backend"/".data",root/"backend"/".local"):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
for location in [root,root/"backend"]:
    for filename in ("sourcera.db","sourcera.db-wal","sourcera.db-shm"):
        (location/filename).unlink(missing_ok=True)
PY
echo "Deployment data removed. Remove separately held original exports, snapshots and backups under your retention terms."
