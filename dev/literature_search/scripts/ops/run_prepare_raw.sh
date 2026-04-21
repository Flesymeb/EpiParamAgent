#!/usr/bin/env bash
# Usage examples:
#   ./run_prepare_raw.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P10 --topic serial_interval --include-gt --fix-missing
#   ./run_prepare_raw.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P4 --topic fatality --include-gt
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$SCRIPT_DIR/../cli"
MODULE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCAL_PYTHON="$MODULE_DIR/.venv/bin/python"
PYTHON_EXE=$([ -f "$LOCAL_PYTHON" ] && echo "$LOCAL_PYTHON" || echo "python")

PROJECT_DIR=""
PROFILE=""
TOPIC=""
INCLUDE_GT=0
FIX_MISSING=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)   PROJECT_DIR="$2"; shift 2 ;;
    --profile)       PROFILE="$2";     shift 2 ;;
    --topic)         TOPIC="$2";       shift 2 ;;
    --include-gt)    INCLUDE_GT=1;     shift   ;;
    --fix-missing)   FIX_MISSING=1;    shift   ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PROJECT_DIR" ]] && { echo "--project-dir is required" >&2; exit 1; }
[[ -z "$PROFILE" ]]     && { echo "--profile is required" >&2; exit 1; }

ARGS=("$CLI_DIR/screening_prepare_raw.py" "--project-root" "$PROJECT_DIR" "--profile" "$PROFILE")
[[ -n "$TOPIC" ]]    && ARGS+=("--topic" "$TOPIC")
[[ "$INCLUDE_GT" -eq 1 ]] && ARGS+=("--include-gt")
[[ "$FIX_MISSING" -eq 1 ]] && ARGS+=("--fix-missing")

echo "Running prepare-raw..."
"$PYTHON_EXE" "${ARGS[@]}"
