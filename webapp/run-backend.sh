#!/usr/bin/env bash
# Launch the demo FastAPI backend.
#
# The backend package lives at webapp/app, but it must run with the *repo root*
# as the working directory so that:
#   - `metaagent` (not pip-installed) resolves from the repo root
#   - relative artifact paths like Path("data")/runs resolve under <repo>/data
#   - coding and screening steps find the tracked configs under <repo>/configs
# `--app-dir webapp` puts the `app` package on sys.path without changing cwd.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../webapp
REPO_ROOT="$(dirname "$SCRIPT_DIR")"                          # repo root

cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

exec "$REPO_ROOT/.venv/bin/uvicorn" app.main:app \
  --app-dir "$SCRIPT_DIR" \
  --host 127.0.0.1 \
  --port "${PORT:-8000}" \
  "$@"
