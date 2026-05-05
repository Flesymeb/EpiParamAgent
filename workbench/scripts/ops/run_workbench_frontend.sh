#!/usr/bin/env bash
# Run workbench frontend
# Usage: ./run_workbench_frontend.sh [--port 5174]
set -euo pipefail

PORT=5174
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKBENCH_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$WORKBENCH_DIR/frontend"

export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"

echo "Running workbench frontend..."
cd "$FRONTEND_DIR"

[[ ! -d "node_modules" ]] && npm install
npm run build
python -m http.server "$PORT" -d dist --bind localhost
