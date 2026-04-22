#!/usr/bin/env bash
# Evaluate coding extraction results: compute pooled means per project.
# Usage:
#   ./run_evaluate_coding.sh                        # all projects
#   ./run_evaluate_coding.sh --topic serial_interval
#   ./run_evaluate_coding.sh --topic serial_interval --project p13
#   ./run_evaluate_coding.sh --include-median

set -euo pipefail
cd "$(cd "$(dirname "$0")/../.." && pwd)"  # dev/literature_search/

uv run python scripts/cli/evaluate_coding.py "$@"
