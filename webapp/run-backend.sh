#!/usr/bin/env bash
set -euo pipefail

WEB_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_REPO_ROOT="$(dirname "$WEB_SCRIPT_DIR")"
WEB_PYTHON="${METAAGENT_PYTHON:-$WEB_REPO_ROOT/.venv/bin/python}"
cd "$WEB_REPO_ROOT"

if [[ ! -x "$WEB_PYTHON" ]]; then
  echo "Python environment missing: create .venv and install the project's web and langextract extras." >&2
  exit 1
fi
if ! "$WEB_PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Web dependencies missing: install the project's web extra into .venv." >&2
  exit 1
fi
exec "$WEB_PYTHON" -m uvicorn webapp.app.main:app \
  --host "${WEB_HOST:-127.0.0.1}" --port "${WEB_PORT:-8000}" "$@"
