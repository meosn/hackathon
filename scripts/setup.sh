#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
mkdir -p datasets
scripts/compose.sh up --build -d
