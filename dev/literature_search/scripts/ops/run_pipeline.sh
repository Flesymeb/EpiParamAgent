#!/usr/bin/env bash
# Usage examples:
#   ./run_pipeline.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P13 --topic serial_interval --include-gt --fix-missing --batch-size 10 --batch-concurrency 1 --auto-fulltext
#   ./run_pipeline.sh --project-dir /home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi --profile P8 --topic reproduction_number --include-gt --fix-missing --batch-size 20 --batch-concurrency 3
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_SCRIPT="$SCRIPT_DIR/run_prepare_raw.sh"
SCREENING_EVAL_SCRIPT="$SCRIPT_DIR/run_screening_eval.sh"

PROJECT_DIR=""
PROFILE=""
TOPIC=""
INCLUDE_GT=0
FIX_MISSING=0
BATCH_SIZE=10
BATCH_CONCURRENCY=1
AUTO_FULLTEXT=0
FULLTEXT_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)        PROJECT_DIR="$2";      shift 2 ;;
    --profile)            PROFILE="$2";           shift 2 ;;
    --topic)              TOPIC="$2";             shift 2 ;;
    --include-gt)         INCLUDE_GT=1;           shift   ;;
    --fix-missing)        FIX_MISSING=1;          shift   ;;
    --batch-size)         BATCH_SIZE="$2";        shift 2 ;;
    --batch-concurrency)  BATCH_CONCURRENCY="$2"; shift 2 ;;
    --auto-fulltext)      AUTO_FULLTEXT=1;        shift   ;;
    --fulltext-only)      FULLTEXT_ONLY=1;        shift   ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PROJECT_DIR" ]] && { echo "--project-dir is required" >&2; exit 1; }
[[ -z "$PROFILE" ]]     && { echo "--profile is required" >&2; exit 1; }

PREPARE_ARGS=("--project-dir" "$PROJECT_DIR" "--profile" "$PROFILE")
[[ -n "$TOPIC" ]]         && PREPARE_ARGS+=("--topic" "$TOPIC")
[[ "$INCLUDE_GT" -eq 1 ]] && PREPARE_ARGS+=("--include-gt")
[[ "$FIX_MISSING" -eq 1 ]] && PREPARE_ARGS+=("--fix-missing")

SCREEN_ARGS=("--project-dir" "$PROJECT_DIR" "--profile" "$PROFILE"
  "--batch-size" "$BATCH_SIZE" "--batch-concurrency" "$BATCH_CONCURRENCY")
[[ -n "$TOPIC" ]]             && SCREEN_ARGS+=("--topic" "$TOPIC")
[[ "$AUTO_FULLTEXT" -eq 1 ]]  && SCREEN_ARGS+=("--auto-fulltext")
[[ "$FULLTEXT_ONLY" -eq 1 ]]  && SCREEN_ARGS+=("--fulltext-only")

echo "Step 1/2: prepare_raw"
bash "$PREPARE_SCRIPT" "${PREPARE_ARGS[@]}"

echo "Step 2/2: screening_eval"
bash "$SCREENING_EVAL_SCRIPT" "${SCREEN_ARGS[@]}"
