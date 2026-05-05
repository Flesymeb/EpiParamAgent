#!/usr/bin/env bash
# Run workbench backend
# Usage: ./run_workbench_backend.sh [--port 8008]
set -euo pipefail

PORT=8008
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKBENCH_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$WORKBENCH_DIR/backend"

export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"

echo "Running workbench backend..."
cd "$BACKEND_DIR"

[[ ! -d ".venv" ]] && uv venv .venv
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT"
