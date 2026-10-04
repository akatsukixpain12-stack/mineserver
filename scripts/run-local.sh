#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
export CONTROL_URL="http://127.0.0.1:8080"
export CORS_ORIGINS="*"
export LOCAL_DB="$PWD/mineserver.db"
exec uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
