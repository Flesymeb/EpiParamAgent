#!/usr/bin/env bash
# SI parameter extraction — Linux entry point
# Usage:
#   ./run_extract_si.sh                              # P13 GT, auto-timestamped output
#   ./run_extract_si.sh --pmids inputs/p10_gt.txt --profile p10_si
#   ./run_extract_si.sh --pmids inputs/p13_gt.txt --out runs/my_test --stage index

set -euo pipefail
cd "$(dirname "$0")"

PMIDS="inputs/p13_gt.txt"
PROFILE="p13_si"
OUT=""
STAGE="both"
CODEBOOK="configs/codebook_serial_interval.yaml"

while [[ $# -gt 0 ]]; do
    case $1 in
        --pmids)    PMIDS="$2";    shift 2 ;;
        --profile)  PROFILE="$2";  shift 2 ;;
        --out)      OUT="$2";      shift 2 ;;
        --stage)    STAGE="$2";    shift 2 ;;
        --codebook) CODEBOOK="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "PMIDs:    $PMIDS"
echo "Stage:    $STAGE"
echo "Codebook: $CODEBOOK"

# Build CLI args: prefer explicit --out, otherwise pass --profile for auto-timestamping
if [[ -n "$OUT" ]]; then
    echo "Output:   $OUT"
    OUT_ARGS=(--out "$OUT")
else
    echo "Profile:  $PROFILE  (output → runs/${PROFILE}_<timestamp>/)"
    OUT_ARGS=(--profile "$PROFILE")
fi
echo ""

uv run python cli/extract_epi.py \
    --input    "$PMIDS" \
    --stage    "$STAGE" \
    --codebook "$CODEBOOK" \
    "${OUT_ARGS[@]}"
