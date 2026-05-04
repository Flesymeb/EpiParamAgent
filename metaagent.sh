#!/usr/bin/env bash
# MetaAgent-Epi entry point
# Usage: ./metaagent.sh [command]
cd "$(dirname "$0")"
python -m metaagent.cli "$@"
