#!/usr/bin/env bash
# Usage examples:
#   ./run_screening_eval.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P10 --topic serial_interval --batch-size 10 --batch-concurrency 3 --auto-fulltext
#   ./run_screening_eval.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P4 --topic fatality --batch-size 30 --batch-concurrency 3 --skip-no-abstract
#   ./run_screening_eval.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P4 --topic fatality --batch-size 10 --batch-concurrency 3 --resume-fulltext
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$SCRIPT_DIR/../cli"
MODULE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCAL_PYTHON="$MODULE_DIR/.venv/bin/python"
PYTHON_EXE=$([ -f "$LOCAL_PYTHON" ] && echo "$LOCAL_PYTHON" || echo "python")

PROJECT_DIR=""
PROFILE=""
TOPIC=""
BATCH_SIZE=10
BATCH_CONCURRENCY=1
AUTO_FULLTEXT=0
FULLTEXT_ONLY=0
SKIP_NO_ABSTRACT=0
RESUME_FULLTEXT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)        PROJECT_DIR="$2";      shift 2 ;;
    --profile)            PROFILE="$2";           shift 2 ;;
    --topic)              TOPIC="$2";             shift 2 ;;
    --batch-size)         BATCH_SIZE="$2";        shift 2 ;;
    --batch-concurrency)  BATCH_CONCURRENCY="$2"; shift 2 ;;
    --auto-fulltext)      AUTO_FULLTEXT=1;        shift   ;;
    --fulltext-only)      FULLTEXT_ONLY=1;        shift   ;;
    --skip-no-abstract)   SKIP_NO_ABSTRACT=1;     shift   ;;
    --resume-fulltext)    RESUME_FULLTEXT=1;      shift   ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PROJECT_DIR" ]] && { echo "--project-dir is required" >&2; exit 1; }
[[ -z "$PROFILE" ]]     && { echo "--profile is required" >&2; exit 1; }

echo "Running screening..."
SCREEN_ARGS=("$CLI_DIR/screening_llm_batch.py"
  "--project-root" "$PROJECT_DIR"
  "--profile" "$PROFILE"
  "--batch-size" "$BATCH_SIZE"
  "--batch-concurrency" "$BATCH_CONCURRENCY")
[[ -n "$TOPIC" ]]             && SCREEN_ARGS+=("--topic" "$TOPIC")
[[ "$FULLTEXT_ONLY" -eq 1 ]]  && SCREEN_ARGS+=("--fulltext-only")
[[ "$AUTO_FULLTEXT" -eq 1 ]]  && SCREEN_ARGS+=("--auto-fulltext")
[[ "$SKIP_NO_ABSTRACT" -eq 1 ]] && SCREEN_ARGS+=("--skip-no-abstract")
[[ "$RESUME_FULLTEXT" -eq 1 ]] && SCREEN_ARGS+=("--resume-fulltext")
"$PYTHON_EXE" "${SCREEN_ARGS[@]}"

echo "Running evaluation..."
EVAL_ARGS=("$CLI_DIR/screening_evaluation.py" "screening-performance"
  "--project-root" "$PROJECT_DIR"
  "--profile" "$PROFILE")
[[ -n "$TOPIC" ]] && EVAL_ARGS+=("--topic" "$TOPIC")
"$PYTHON_EXE" "${EVAL_ARGS[@]}"
