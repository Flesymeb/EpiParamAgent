#!/usr/bin/env bash
# Run MetaAgent workbench (backend + frontend) in parallel
# Usage: ./run_workbench.sh [--backend-port 8008] [--frontend-port 5174]
set -euo pipefail

BACKEND_PORT=8008
FRONTEND_PORT=5174
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-port)  BACKEND_PORT="$2";  shift 2 ;;
    --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_SCRIPT="$SCRIPT_DIR/run_workbench_backend.sh"
FRONTEND_SCRIPT="$SCRIPT_DIR/run_workbench_frontend.sh"

export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"

# Kill any process already listening on the frontend port
fuser -k "${FRONTEND_PORT}/tcp" 2>/dev/null || true

echo "Starting workbench backend and frontend..."
bash "$BACKEND_SCRIPT" --port "$BACKEND_PORT" &
BACKEND_PID=$!
sleep 2
bash "$FRONTEND_SCRIPT" --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

wait_port() {
  local port=$1 timeout=60 elapsed=0
  while [[ $elapsed -lt $timeout ]]; do
    ss -tlnp 2>/dev/null | grep -q ":${port} " && return 0
    sleep 0.5; ((elapsed++)) || true
  done
  return 1
}

if wait_port "$BACKEND_PORT"; then
  echo "Backend ready:  http://localhost:$BACKEND_PORT"
else
  echo "Warning: backend did not become ready on port $BACKEND_PORT within timeout"
fi

if wait_port "$FRONTEND_PORT"; then
  echo "Frontend ready: http://localhost:$FRONTEND_PORT"
else
  echo "Warning: frontend did not become ready on port $FRONTEND_PORT within timeout"
fi

wait $BACKEND_PID $FRONTEND_PID
