#!/usr/bin/env bash
# Generic coding extraction runner — works for SI, R0, and CFR.
#
# Usage:
#   ./run_extract_coding.sh --topic serial_interval --profile P13
#   ./run_extract_coding.sh --topic reproduction_number --profile P7
#   ./run_extract_coding.sh --topic fatality --profile P4
#   ./run_extract_coding.sh --topic serial_interval --profile P13 --stage fetch
#   ./run_extract_coding.sh --topic serial_interval --profile P13 --fetch-mode pmc_scihub

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Defaults
TOPIC="serial_interval"
PROFILE="P13"
STAGE="all"
FETCH_MODE="pmc_scihub"
OUT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --topic)      TOPIC="$2";      shift 2 ;;
        --profile)    PROFILE="$2";    shift 2 ;;
        --stage)      STAGE="$2";      shift 2 ;;
        --fetch-mode) FETCH_MODE="$2"; shift 2 ;;
        --out)        OUT="$2";        shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Resolve codebook from topic
case "$TOPIC" in
    serial_interval)      CODEBOOK="configs/codebook_serial_interval.yaml" ;;
    reproduction_number)  CODEBOOK="configs/codebook_reproduction_number.yaml" ;;
    fatality)             CODEBOOK="configs/codebook_fatality.yaml" ;;
    *)
        echo "Unknown topic: $TOPIC. Supported: serial_interval, reproduction_number, fatality"
        exit 1
        ;;
esac

# Resolve pmids.txt from topic+profile (lowercase project id)
PROJECT_ID=$(echo "$PROFILE" | tr '[:upper:]' '[:lower:]')
PMIDS="$REPO_ROOT/evaluation/coding/$TOPIC/$PROJECT_ID/pmids.txt"

if [[ ! -f "$PMIDS" ]]; then
    echo "ERROR: pmids.txt not found: $PMIDS"
    exit 1
fi

echo "Topic:      $TOPIC"
echo "Profile:    $PROFILE"
echo "Codebook:   $CODEBOOK"
echo "PMIDs:      $PMIDS  ($(wc -l < "$PMIDS") entries)"
echo "Stage:      $STAGE"
echo "Fetch mode: $FETCH_MODE"
echo ""

if [[ -n "$OUT" ]]; then
    OUT_ARGS=(--out "$OUT")
else
    OUT_ARGS=(--profile "$PROFILE")
fi

BASE_ARGS=(
    --input    "$PMIDS"
    --codebook "$CODEBOOK"
    "${OUT_ARGS[@]}"
)

# Phase 1: fetch + MinerU
if [[ "$STAGE" == "all" || "$STAGE" == "fetch" ]]; then
    echo "══ Phase 1: fetch + MinerU ══"
    uv run python cli/extract_epi.py "${BASE_ARGS[@]}" --stage fetch --fetch-mode "$FETCH_MODE"
    echo ""
fi

# Phase 2: LLM extraction
if [[ "$STAGE" == "all" || "$STAGE" == "both" || "$STAGE" == "index" || "$STAGE" == "extract" ]]; then
    echo "══ Phase 2: LLM extraction ══"
    LLM_STAGE="${STAGE}"
    [[ "$STAGE" == "all" ]] && LLM_STAGE="both"
    uv run python cli/extract_epi.py "${BASE_ARGS[@]}" --stage "$LLM_STAGE" --fetch-mode pmc_only
fi
