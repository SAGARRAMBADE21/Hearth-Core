#!/usr/bin/env bash
# hearth-core.sh — run Hearth-Core locally.
#
#   ./hearth-core.sh install   create venv/ and install requirements-dev.txt
#   ./hearth-core.sh dev       run the API with auto-reload
#   ./hearth-core.sh test      run the unittest gate
#
# Shape mirrors xo-space cowork-api.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=venv/bin/python
[[ -x "$PY" ]] || PY=venv/Scripts/python.exe   # Windows venv layout

case "${1:-}" in
  install)
    python3 -m venv venv 2>/dev/null || python -m venv venv
    [[ -x venv/bin/python ]] && PY=venv/bin/python || PY=venv/Scripts/python.exe
    "$PY" -m pip install -q -r requirements-dev.txt
    [[ -f .env ]] || cp .env.example .env
    echo "installed; edit .env, then ./hearth-core.sh dev"
    ;;
  dev)
    UVICORN_RELOAD=true exec "$PY" server.py
    ;;
  test)
    exec "$PY" -m unittest discover -s tests -t .
    ;;
  *)
    echo "usage: $0 install|dev|test" >&2
    exit 2
    ;;
esac
