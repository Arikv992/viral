#!/usr/bin/env bash
# Arranque completo: instala dependências (1ª vez), compila a UI e serve tudo em http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r backend/requirements.txt
if [ ! -d web/dist ] || [ "${REBUILD:-0}" = "1" ]; then (cd web && npm install --no-fund --no-audit && npm run build); fi
cd backend && exec uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
