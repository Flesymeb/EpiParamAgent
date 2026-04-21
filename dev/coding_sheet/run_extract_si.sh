#!/usr/bin/env bash
# SI parameter extraction — Linux entry point
# Usage:
#   ./run_extract_si.sh                                   # P13 GT, auto-routed to evaluation/coding/
#   ./run_extract_si.sh --profile P10 --pmids ../../evaluation/coding/serial_interval/p10/pmids.txt
#   ./run_extract_si.sh --out /custom/path --stage index

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROFILE="P13"
PMIDS="$REPO_ROOT/evaluation/coding/serial_interval/p13/pmids.txt"
OUT=""
STAGE="both"
CODEBOOK="configs/codebook_serial_interval.yaml"
FETCH_MODE="pmc_only"   # pmc_only | pmc_scihub | pmc_scihub_manual

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)    PROFILE="$2";    shift 2 ;;
        --pmids)      PMIDS="$2";      shift 2 ;;
        --out)        OUT="$2";        shift 2 ;;
        --stage)      STAGE="$2";      shift 2 ;;
        --codebook)   CODEBOOK="$2";   shift 2 ;;
        --fetch-mode) FETCH_MODE="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "Profile:    $PROFILE"
echo "PMIDs:      $PMIDS"
echo "Stage:      $STAGE"
echo "Fetch mode: $FETCH_MODE"
echo "Codebook:   $CODEBOOK"
echo ""

if [[ -n "$OUT" ]]; then
    OUT_ARGS=(--out "$OUT")
else
    OUT_ARGS=(--profile "$PROFILE")
fi

uv run python cli/extract_epi.py \
    --input      "$PMIDS" \
    --stage      "$STAGE" \
    --codebook   "$CODEBOOK" \
    --fetch-mode "$FETCH_MODE" \
    "${OUT_ARGS[@]}"
