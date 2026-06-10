#!/usr/bin/env bash
# Launch the demo frontend (Vite dev server) on :5173.
# The dev server proxies /api -> http://127.0.0.1:8000 (see vite.config.ts),
# so start the backend first with ./run-backend.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/frontend"

exec pnpm dev "$@"
