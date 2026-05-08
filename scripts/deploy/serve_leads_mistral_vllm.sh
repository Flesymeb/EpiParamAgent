#!/usr/bin/env bash
set -euo pipefail

# Serve zifeng-ai/leads-mistral-7b-v1 through the OpenAI-compatible vLLM API.
# Typical flow:
#   bash scripts/deploy/download_leads_mistral.sh
#   bash scripts/deploy/serve_leads_mistral_vllm.sh

export VLLM_LOGGING_LEVEL="${VLLM_LOGGING_LEVEL:-INFO}"
export TORCH_USE_CUDA_DSA="${TORCH_USE_CUDA_DSA:-1}"

HF_MODEL_ID="${HF_MODEL_ID:-zifeng-ai/leads-mistral-7b-v1}"
MODEL="${MODEL:-/mnt/shared-storage-user/yanhaoyang/models/new/leads-mistral-7b-v1}"
MODEL_NAME="${MODEL_NAME:-zifeng-ai/leads-mistral-7b-v1}"

LOG_ROOT="${LOG_ROOT:-leads_mistral}"
mkdir -p "vllm_logs/$LOG_ROOT"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.93}"
DTYPE="${DTYPE:-bfloat16}"

if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: nvidia-smi not found; this script expects an NVIDIA GPU node." >&2
    exit 1
fi

GPU_COUNTS="${GPU_COUNTS:-$(nvidia-smi -L | wc -l)}"
if [[ "$GPU_COUNTS" -lt 1 ]]; then
    echo "ERROR: no GPU detected by nvidia-smi" >&2
    nvidia-smi || true
    exit 1
fi

if [[ ! -e "$MODEL" ]]; then
    if [[ "${VLLM_USE_HF_ID:-0}" == "1" ]]; then
        echo "WARN: local MODEL path does not exist; serving HF repo id $HF_MODEL_ID instead."
        MODEL="$HF_MODEL_ID"
    else
        cat >&2 <<MSG
ERROR: MODEL path not found: $MODEL
Download first, or override MODEL, for example:
  MODEL_DIR=$MODEL bash scripts/deploy/download_leads_mistral.sh
  MODEL=/path/to/leads-mistral-7b-v1 bash scripts/deploy/serve_leads_mistral_vllm.sh
Set VLLM_USE_HF_ID=1 to let vLLM download from Hugging Face at startup.
MSG
        exit 1
    fi
fi

LOG_MODEL_NAME="${MODEL_NAME//\//__}"
LOGFILE="vllm_logs/$LOG_ROOT/${LOG_MODEL_NAME}_$(date +%Y%m%dT%H%M%S).log"

echo "Starting vLLM OpenAI API server..."
echo "MODEL=$MODEL"
echo "MODEL_NAME=$MODEL_NAME"
echo "HOST=$HOST"
echo "PORT=$PORT"
echo "GPU_COUNTS=$GPU_COUNTS"
echo "MAX_MODEL_LEN=$MAX_MODEL_LEN"
echo "GPU_MEMORY_UTILIZATION=$GPU_MEMORY_UTILIZATION"
echo "DTYPE=$DTYPE"
echo "LOGFILE=$LOGFILE"

COMMON_ARGS=(
    --model "$MODEL"
    --trust-remote-code
    --seed 42
    --enforce-eager
    --max-model-len "$MAX_MODEL_LEN"
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
    --tensor-parallel-size "$GPU_COUNTS"
    --served-model-name "$MODEL_NAME"
)

if [[ -n "$DTYPE" ]]; then
    COMMON_ARGS+=(--dtype "$DTYPE")
fi

python -m vllm.entrypoints.openai.api_server \
    "${COMMON_ARGS[@]}" \
    --host "$HOST" \
    --port "$PORT" \
    2>&1 | tee "$LOGFILE"
