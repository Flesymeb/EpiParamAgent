#!/usr/bin/env bash
set -euo pipefail

# One-click strict/simple LEADS-Mistral screening evaluation for COVID-19 + mpox.
#
# Usage:
#   bash tools/scripts/run_leads_mistral_covid_mpox_eval.sh
#
# Common overrides:
#   CONCURRENCY=20 EXPERIMENT=my_run bash tools/scripts/run_leads_mistral_covid_mpox_eval.sh
#   LIMIT=20 bash tools/scripts/run_leads_mistral_covid_mpox_eval.sh      # smoke test
#   PULL_DATA=1 bash tools/scripts/run_leads_mistral_covid_mpox_eval.sh  # fetch raw/GT CSVs from branch

PROJECT_ROOT="${PROJECT_ROOT:-.}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000/v1}"
MODEL="${MODEL:-zifeng-ai/leads-mistral-7b-v1}"
CONCURRENCY="${CONCURRENCY:-20}"
EXPERIMENT="${EXPERIMENT:-leads_mistral_strict_simple_$(date +%Y%m%d_%H%M%S)}"
LOG_DIR="${LOG_DIR:-logs}"
LIMIT="${LIMIT:-0}"
PULL_DATA="${PULL_DATA:-0}"
DATA_BRANCH="${DATA_BRANCH:-origin/feat/cascade-screening}"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$PROJECT_ROOT"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${EXPERIMENT}.log"

pull_data() {
  echo "[data] Pulling raw/groundtruth CSVs from $DATA_BRANCH"
  git fetch origin feat/cascade-screening

  git ls-tree -r --name-only "$DATA_BRANCH" \
    | grep '^evaluation/\(covid19\|mpox\)/.*/ground_truth/p[0-9][0-9]*/project_[0-9][0-9]*_\(raw\|groundtruth\)\.csv$' \
    > /tmp/leads_eval_files_$$.txt || true

  local count
  count=$(sed '/^$/d' /tmp/leads_eval_files_$$.txt | wc -l)
  echo "[data] Matched CSV files: $count"
  if [[ "$count" -eq 0 ]]; then
    echo "[data] ERROR: no raw/groundtruth CSVs found on $DATA_BRANCH" >&2
    rm -f /tmp/leads_eval_files_$$.txt
    exit 1
  fi

  xargs -r git checkout "$DATA_BRANCH" -- < /tmp/leads_eval_files_$$.txt
  rm -f /tmp/leads_eval_files_$$.txt
}

check_server() {
  echo "[server] Checking $BASE_URL/models"
  if ! curl -fsS "$BASE_URL/models" >/tmp/leads_eval_models_$$.json; then
    echo "[server] ERROR: cannot reach vLLM at $BASE_URL/models" >&2
    echo "[server] Start it first, e.g. bash scripts/deploy/serve_leads_mistral_vllm.sh" >&2
    rm -f /tmp/leads_eval_models_$$.json
    exit 1
  fi
  if ! grep -q "$MODEL" /tmp/leads_eval_models_$$.json; then
    echo "[server] WARN: model '$MODEL' not found in /models response. Continuing anyway." >&2
    cat /tmp/leads_eval_models_$$.json >&2
  fi
  rm -f /tmp/leads_eval_models_$$.json
}

run_disease() {
  local disease="$1"
  echo
  echo "===== Running $disease ====="

  local limit_args=()
  if [[ "$LIMIT" != "0" ]]; then
    limit_args+=(--limit "$LIMIT")
  fi

  "$PYTHON_BIN" -u tools/scripts/leads_mistral_screening_eval.py \
    --project-root . \
    --disease "$disease" \
    --experiment "$EXPERIMENT" \
    --base-url "$BASE_URL" \
    --model "$MODEL" \
    --concurrency "$CONCURRENCY" \
    "${limit_args[@]}"
}

{
  echo "Experiment:  $EXPERIMENT"
  echo "Project:     $(pwd)"
  echo "Base URL:    $BASE_URL"
  echo "Model:       $MODEL"
  echo "Concurrency: $CONCURRENCY"
  echo "Limit:       $LIMIT"
  echo "Pull data:   $PULL_DATA"
  echo "Log file:    $LOG_FILE"
  echo

  if [[ "$PULL_DATA" == "1" ]]; then
    pull_data
    echo
  fi

  check_server
  run_disease covid19
  run_disease mpox

  echo
  echo "Done. Summaries:"
  echo "  COVID: evaluation/experiments/$EXPERIMENT/screening/covid19/summary.csv"
  echo "  mpox:  evaluation/experiments/$EXPERIMENT/screening/mpox/summary.csv"
} 2>&1 | tee "$LOG_FILE"
