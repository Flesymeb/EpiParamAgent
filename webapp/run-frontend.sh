#!/usr/bin/env bash
set -euo pipefail

WEB_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WEB_SCRIPT_DIR/frontend"
if [[ ! -d node_modules ]]; then
  echo "Frontend dependencies missing: run npm install in webapp/frontend first." >&2
  exit 1
fi
exec npm run dev -- --host "${WEB_FRONTEND_HOST:-127.0.0.1}" \
  --port "${WEB_FRONTEND_PORT:-5173}" "$@"
