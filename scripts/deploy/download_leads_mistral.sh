#!/usr/bin/env bash
set -euo pipefail

# Download LEADS-Mistral-7B-v1 weights into a local directory for vLLM serving.
# Override MODEL_DIR if the cluster uses a different shared model cache.
MODEL_ID="${MODEL_ID:-zifeng-ai/leads-mistral-7b-v1}"
MODEL_DIR="${MODEL_DIR:-/mnt/shared-storage-user/yanhaoyang/models/new/leads-mistral-7b-v1}"
REVISION="${REVISION:-main}"

export MODEL_ID MODEL_DIR REVISION
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"

mkdir -p "$(dirname "$MODEL_DIR")"

echo "Downloading $MODEL_ID@$REVISION"
echo "Target: $MODEL_DIR"

python - <<'PY'
import os
import sys

model_id = os.environ["MODEL_ID"]
model_dir = os.environ["MODEL_DIR"]
revision = os.environ["REVISION"]

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print(
        "ERROR: huggingface_hub is not installed. Install it with:\n"
        "  pip install -U huggingface_hub hf_transfer",
        file=sys.stderr,
    )
    raise SystemExit(1)

snapshot_download(
    repo_id=model_id,
    revision=revision,
    local_dir=model_dir,
)
print(f"Done: {model_dir}")
PY
