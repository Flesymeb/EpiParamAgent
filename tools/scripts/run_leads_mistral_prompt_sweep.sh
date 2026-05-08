#!/usr/bin/env bash
set -euo pipefail

# Sweep several LEADS-Mistral prompt variants and print a compact comparison
# table after all runs finish.

PROJECT_ROOT="${PROJECT_ROOT:-.}"
DATA_ROOT="${DATA_ROOT:-dataset}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000/v1}"
MODEL="${MODEL:-zifeng-ai/leads-mistral-7b-v1}"
CONCURRENCY="${CONCURRENCY:-20}"
LIMIT="${LIMIT:-0}"
PULL_DATA="${PULL_DATA:-0}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LOG_DIR="${LOG_DIR:-logs}"
SWEEP_NAME="${SWEEP_NAME:-leads_mistral_prompt_sweep_$(date +%Y%m%d_%H%M%S)}"
STYLES="${STYLES:-strict_simple disease_parameter_minimal disease_parameter_relevance disease_parameter_useful disease_parameter_about_topic disease_parameter_direct_estimate disease_parameter_numerical_value disease_parameter_primary_study disease_parameter_all_conditions}"

cd "$PROJECT_ROOT"
mkdir -p "$LOG_DIR"

RUNNER="tools/scripts/run_leads_mistral_covid_mpox_eval.sh"
if [[ ! -x "$RUNNER" && ! -f "$RUNNER" ]]; then
  echo "ERROR: runner script not found: $RUNNER" >&2
  exit 1
fi

read -r -a STYLE_ARRAY <<< "$STYLES"
if [[ "${#STYLE_ARRAY[@]}" -eq 0 ]]; then
  echo "ERROR: no prompt styles configured" >&2
  exit 1
fi

SWEEP_DIR="evaluation/experiments/$SWEEP_NAME"
SUMMARY_CSV="$SWEEP_DIR/prompt_style_micro_summary.csv"
SUMMARY_MD="$SWEEP_DIR/prompt_style_micro_summary.md"
mkdir -p "$SWEEP_DIR"

EXPERIMENT_ARGS=()
pull_flag="$PULL_DATA"

echo "Sweep:       $SWEEP_NAME"
echo "Project:     $(pwd)"
echo "Data root:   $DATA_ROOT"
echo "Base URL:    $BASE_URL"
echo "Model:       $MODEL"
echo "Concurrency: $CONCURRENCY"
echo "Limit:       $LIMIT"
echo "Pull data:   $PULL_DATA"
echo "Styles:      ${STYLE_ARRAY[*]}"
echo

for style in "${STYLE_ARRAY[@]}"; do
  experiment="${SWEEP_NAME}_${style}"
  EXPERIMENT_ARGS+=("$style" "$experiment")

  echo "============================================================"
  echo "Prompt style: $style"
  echo "Experiment:   $experiment"
  echo "============================================================"

  PROMPT_STYLE="$style" \
  EXPERIMENT="$experiment" \
  DATA_ROOT="$DATA_ROOT" \
  BASE_URL="$BASE_URL" \
  MODEL="$MODEL" \
  CONCURRENCY="$CONCURRENCY" \
  LIMIT="$LIMIT" \
  PULL_DATA="$pull_flag" \
  LOG_DIR="$LOG_DIR" \
  PYTHON_BIN="$PYTHON_BIN" \
  bash "$RUNNER"

  pull_flag=0
  echo
done

"$PYTHON_BIN" - "$SUMMARY_CSV" "$SUMMARY_MD" "${EXPERIMENT_ARGS[@]}" <<'PY'
import csv
import sys
from pathlib import Path


def safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def aggregate(rows: list[dict[str, str]]) -> dict[str, int]:
    total = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "ground_truth_count": 0, "screened_count": 0}
    for row in rows:
        if row.get("status") != "ok":
            continue
        for key in total:
            total[key] += int(row.get(key) or 0)
    return total


def build_metric_row(style: str, experiment: str, scope: str, rows: list[dict[str, str]]) -> dict[str, str]:
    counts = aggregate(rows)
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    tn = counts["tn"]
    screened = counts["screened_count"]
    recall = safe_div(tp, tp + fn)
    precision = safe_div(tp, tp + fp)
    specificity = safe_div(tn, tn + fp)
    f1 = safe_div(2 * precision * recall, precision + recall)
    workload_reduction = safe_div(tn + fn, screened)
    return {
        "style": style,
        "experiment": experiment,
        "scope": scope,
        "ground_truth_count": str(counts["ground_truth_count"]),
        "screened_count": str(screened),
        "predicted_include": str(tp + fp),
        "tp": str(tp),
        "fp": str(fp),
        "fn": str(fn),
        "tn": str(tn),
        "recall": f"{recall:.6f}",
        "precision": f"{precision:.6f}",
        "f1": f"{f1:.6f}",
        "workload_reduction": f"{workload_reduction:.6f}",
        "specificity": f"{specificity:.6f}",
    }


def render_table(rows: list[dict[str, str]]) -> str:
    headers = [
        "style",
        "scope",
        "recall",
        "precision",
        "f1",
        "workload_reduction",
        "predicted_include",
        "tp",
        "fp",
        "fn",
        "tn",
    ]
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(row[header]))

    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    divider = "  ".join("-" * widths[header] for header in headers)
    body = [
        "  ".join(row[header].ljust(widths[header]) for header in headers)
        for row in rows
    ]
    return "\n".join([header_line, divider, *body])


summary_csv = Path(sys.argv[1])
summary_md = Path(sys.argv[2])
items = sys.argv[3:]
pairs = list(zip(items[0::2], items[1::2]))

all_rows: list[dict[str, str]] = []
for style, experiment in pairs:
    combined_path = Path("evaluation/experiments") / experiment / "screening" / "combined_summary.csv"
    rows = read_rows(combined_path)
    covid_rows = [row for row in rows if row.get("disease") == "covid19"]
    mpox_rows = [row for row in rows if row.get("disease") == "mpox"]
    all_rows.append(build_metric_row(style, experiment, "covid19", covid_rows))
    all_rows.append(build_metric_row(style, experiment, "mpox", mpox_rows))
    all_rows.append(build_metric_row(style, experiment, "overall", rows))

summary_csv.parent.mkdir(parents=True, exist_ok=True)
with summary_csv.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "style",
            "experiment",
            "scope",
            "ground_truth_count",
            "screened_count",
            "predicted_include",
            "tp",
            "fp",
            "fn",
            "tn",
            "recall",
            "precision",
            "f1",
            "workload_reduction",
            "specificity",
        ],
    )
    writer.writeheader()
    writer.writerows(all_rows)

table_text = render_table(all_rows)
summary_md.write_text(
    "# LEADS prompt sweep micro summary\n\n```\n" + table_text + "\n```\n",
    encoding="utf-8",
)
print(table_text)
print()
print(f"CSV: {summary_csv}")
print(f"MD:  {summary_md}")
PY
