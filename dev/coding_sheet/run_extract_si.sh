#!/usr/bin/env bash
# SI parameter extraction — Linux entry point
#
# Two-phase workflow:
#   Phase 1: download missing PDFs + warm MinerU cache  (--stage fetch)
#   Phase 2: LLM extraction Stage A + B                (--stage both)
#
# Usage:
#   ./run_extract_si.sh                              # full run (both phases)
#   ./run_extract_si.sh --stage fetch                # phase 1 only
#   ./run_extract_si.sh --stage both                 # phase 2 only (PDFs already cached)
#   ./run_extract_si.sh --profile P10 --pmids ../../evaluation/coding/serial_interval/p10/pmids.txt
#   ./run_extract_si.sh --fetch-mode pmc_scihub      # use Sci-Hub fallback in phase 1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROFILE="P13"
PMIDS="$REPO_ROOT/evaluation/coding/covid19/serial_interval/p13/pmids.txt"
OUT=""
STAGE="all"     # all = fetch then both; or: fetch | index | extract | both
CODEBOOK="configs/codebook_serial_interval.yaml"
FETCH_MODE="pmc_scihub"   # pmc_only | pmc_scihub | pmc_scihub_manual

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

echo "Profile:    $PROFILE"
echo "PMIDs:      $PMIDS"
echo "Stage:      $STAGE"
echo "Fetch mode: $FETCH_MODE"
echo "Codebook:   $CODEBOOK"
echo ""

if [[ "$STAGE" == "all" || "$STAGE" == "fetch" ]]; then
    echo "══ Phase 1: fetch + MinerU cache ══"
    uv run python cli/extract_epi.py "${BASE_ARGS[@]}" --stage fetch --fetch-mode "$FETCH_MODE"
    echo ""
fi

if [[ "$STAGE" == "all" || "$STAGE" == "both" || "$STAGE" == "index" || "$STAGE" == "extract" ]]; then
    echo "══ Phase 2: LLM extraction ══"
    LLM_STAGE="${STAGE}"
    [[ "$STAGE" == "all" ]] && LLM_STAGE="both"
    uv run python cli/extract_epi.py "${BASE_ARGS[@]}" --stage "$LLM_STAGE" --fetch-mode pmc_only
fi

