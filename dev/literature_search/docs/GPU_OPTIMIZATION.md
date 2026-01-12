# GPU Optimization Guide for NVIDIA A6000

## Overview

This guide covers GPU acceleration strategies for Research Pilot using NVIDIA A6000 (48GB VRAM) with CUDA.

## CUDA Installation

### Check Existing Installation
```bash
# Check NVIDIA driver
nvidia-smi

# Check CUDA version
nvcc --version
```

### Install CUDA Toolkit (if needed)
```bash
# Ubuntu/Debian
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.0-1_all.deb
sudo dpkg -i cuda-keyring_1.0-1_all.deb
sudo apt-get update
sudo apt-get -y install cuda

# Add to PATH
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

## PyTorch with CUDA

### Installation
```bash
# Install PyTorch with CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Or CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### Verify GPU Access
```python
import torch

print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA version: {torch.version.cuda}")
print(f"Device count: {torch.cuda.device_count()}")
print(f"Device name: {torch.cuda.get_device_name(0)}")
print(f"Device memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")

# Expected output:
# CUDA available: True
# Device name: NVIDIA A6000
# Device memory: 48.00 GB
```

## Embedding Generation Optimization

### Sentence Transformers with GPU

```python
from sentence_transformers import SentenceTransformer
import torch

# Load model on GPU
model = SentenceTransformer(
    'sentence-transformers/all-mpnet-base-v2',
    device='cuda'
)

# Enable mixed precision for 2x+ speedup with tensor cores
model.half()  # FP16

# Batch encoding
chunks = ["text 1", "text 2", ...]
embeddings = model.encode(
    chunks,
    batch_size=128,  # A6000 can handle larger batches
    convert_to_tensor=True,
    show_progress_bar=True,
    normalize_embeddings=True
)
```

### Performance Tuning

**Optimal Batch Sizes for A6000:**
- `all-mpnet-base-v2`: 128-256
- `all-MiniLM-L6-v2`: 256-512
- Large models (e5-large): 64-128

**Benchmark Script:**
```python
import time
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-mpnet-base-v2', device='cuda').half()
texts = ["Sample research paper text"] * 1000

for batch_size in [32, 64, 128, 256]:
    start = time.time()
    embeddings = model.encode(texts, batch_size=batch_size)
    duration = time.time() - start
    print(f"Batch {batch_size}: {duration:.2f}s ({len(texts)/duration:.0f} docs/s)")
```

**Expected Performance:**
- Batch 32: ~1500 docs/sec
- Batch 128: ~4000 docs/sec
- Batch 256: ~5500 docs/sec

## Local LLM Inference

### vLLM Setup

```bash
# Install vLLM
pip install vllm

# Install flash-attention for faster inference
pip install flash-attn --no-build-isolation
```

### Running Local Models

```python
from vllm import LLM, SamplingParams

# Initialize model
llm = LLM(
    model="meta-llama/Llama-3.1-8B-Instruct",
    tensor_parallel_size=1,
    gpu_memory_utilization=0.85,
    max_model_len=8192,
    dtype="float16"  # Use FP16 for faster inference
)

# Sampling parameters
sampling_params = SamplingParams(
    temperature=0.7,
    top_p=0.9,
    max_tokens=2048
)

# Generate
outputs = llm.generate(
    ["Summarize recent advances in transformer architectures"],
    sampling_params
)
```

### Model Recommendations for 48GB VRAM

| Model | Params | VRAM (FP16) | Speed (tok/s) | Quality | Use Case |
|-------|--------|-------------|---------------|---------|----------|
| Llama 3.1 8B | 8B | ~16GB | 80-120 | Good | Fast inference |
| Llama 3.1 70B | 70B | ~140GB | N/A | Excellent | Too large |
| Llama 3.1 70B (4-bit) | 70B | ~40GB | 15-25 | Excellent | Best quality |
| Mixtral 8x7B | 47B | ~47GB | 40-60 | Excellent | Good balance |
| Qwen2.5 14B | 14B | ~28GB | 60-90 | Very Good | Research |
| Mistral 7B | 7B | ~14GB | 90-140 | Good | Fast + quality |

**Recommended Setup:**
```python
# Option 1: Mixtral (uses almost all VRAM)
llm = LLM("mistralai/Mixtral-8x7B-Instruct-v0.1", gpu_memory_utilization=0.95)

# Option 2: Llama 70B quantized
llm = LLM("meta-llama/Llama-3.1-70B-Instruct", quantization="awq", gpu_memory_utilization=0.9)

# Option 3: Dual model (embeddings + LLM)
# Keep embeddings in VRAM (4GB) + Llama 3.1 8B (16GB) = 20GB total
```

## Memory Management

### VRAM Allocation Strategies

**Strategy 1: Embedding Focus**
- Embedding model: 2-4GB
- Large batch buffer: 10GB
- Free VRAM: ~34GB
- **Use case**: Processing thousands of papers

**Strategy 2: Balanced (Recommended)**
- Embedding model: 2GB
- LLM (Qwen2.5 14B): 28GB
- Working memory: 12GB
- **Use case**: Full pipeline with local LLM

**Strategy 3: Maximum Quality**
- Embedding on CPU or shared
- LLM (Mixtral or Llama 70B-4bit): 45GB
- **Use case**: Highest quality synthesis

### Dynamic Memory Management

```python
import torch
import gc

class GPUMemoryManager:
    """Efficient GPU memory management"""

    @staticmethod
    def clear():
        """Force cleanup"""
        gc.collect()
        torch.cuda.empty_cache()

    @staticmethod
    def get_free_memory():
        """Get free VRAM in GB"""
        return torch.cuda.mem_get_info()[0] / 1e9

    @staticmethod
    def optimize_batch_size(base_size=32, target_util=0.8):
        """Dynamically adjust batch size"""
        total_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        free_mem = GPUMemoryManager.get_free_memory()
        ratio = free_mem / total_mem

        if ratio > 0.5:
            return base_size * 2
        elif ratio > 0.3:
            return base_size
        else:
            return base_size // 2

# Usage
manager = GPUMemoryManager()
batch_size = manager.optimize_batch_size(base_size=64)
```

## Advanced Optimizations

### Tensor Cores (A6000 Ampere Architecture)

```python
# Enable TF32 for A6000 tensor cores (2-4x speedup)
import torch
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

# Use mixed precision training/inference
from torch.cuda.amp import autocast

with autocast():
    embeddings = model.encode(texts)
```

### Flash Attention

```python
# For local LLMs with vLLM
llm = LLM(
    model="meta-llama/Llama-3.1-8B-Instruct",
    # Flash attention automatically enabled if available
    max_model_len=16384  # Longer context with flash attention
)
```

### Multi-Stream Processing

```python
import torch
from torch.cuda import Stream

# Process batches in parallel streams
def parallel_encode(model, batch_lists):
    streams = [Stream() for _ in batch_lists]
    results = []

    for stream, batch in zip(streams, batch_lists):
        with torch.cuda.stream(stream):
            result = model.encode(batch)
            results.append(result)

    torch.cuda.synchronize()
    return results
```

## Monitoring & Profiling

### Real-time Monitoring

```bash
# Watch GPU usage
watch -n 0.5 nvidia-smi

# Detailed monitoring
nvidia-smi dmon -i 0 -s pucvmet

# Log to file
nvidia-smi --query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used,memory.free --format=csv -l 1 > gpu_log.csv
```

### Python Profiling

```python
import torch

# Track memory
print(f"Allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
print(f"Reserved: {torch.cuda.memory_reserved() / 1e9:.2f} GB")
print(f"Max allocated: {torch.cuda.max_memory_allocated() / 1e9:.2f} GB")

# Detailed memory stats
print(torch.cuda.memory_summary())

# Profile performance
from torch.profiler import profile, ProfilerActivity

with profile(activities=[ProfilerActivity.CUDA]) as prof:
    embeddings = model.encode(texts, batch_size=128)

print(prof.key_averages().table(sort_by="cuda_time_total"))
```

## Performance Benchmarks

### Expected Performance on A6000

**Embedding Generation:**
- All-mpnet-base (768d): **5000-7000 chunks/sec** @ batch 128
- Processing 1000 papers (10 pages avg): **3-5 minutes**

**Local LLM Inference:**
- Llama 3.1 8B: **80-120 tokens/sec**
- Mixtral 8x7B: **40-60 tokens/sec**
- Llama 70B (4-bit): **15-25 tokens/sec**

**Vector Search (Qdrant on GPU):**
- 100K vectors: <50ms
- 1M vectors: <200ms

**End-to-End Pipeline:**
- Search query → 10 papers → embeddings → synthesis: **5-10 minutes**

## Best Practices

### 1. Model Loading
```python
# Load once, reuse
@lru_cache(maxsize=1)
def get_embedding_model():
    return SentenceTransformer('all-mpnet-base-v2', device='cuda').half()

model = get_embedding_model()
```

### 2. Batch Processing
```python
# Process in chunks
def process_large_dataset(texts, batch_size=128):
    results = []
    for i in range(0, len(texts), batch_size * 10):
        batch = texts[i:i + batch_size * 10]
        embeddings = model.encode(batch, batch_size=batch_size)
        results.append(embeddings)
        torch.cuda.empty_cache()  # Periodic cleanup
    return torch.cat(results)
```

### 3. Pinned Memory for Fast Transfers
```python
import torch

# Use pinned memory for CPU→GPU transfers
texts_tensor = torch.tensor(texts).pin_memory()
embeddings = model.encode(texts_tensor)
```

### 4. Warm-up
```python
# Run dummy batch to initialize CUDA
dummy = model.encode(["warmup"] * 32)
torch.cuda.synchronize()
```

## Troubleshooting

### Out of Memory Errors
1. Reduce batch_size
2. Clear cache: `torch.cuda.empty_cache()`
3. Use gradient checkpointing
4. Lower precision: FP16 or even INT8

### Slow Performance
1. Check GPU utilization: `nvidia-smi`
2. Enable TF32 for tensor cores
3. Use flash attention
4. Profile with torch.profiler

### CUDA Errors
```bash
# Reset GPU
nvidia-smi --gpu-reset

# Check for issues
nvidia-smi -q

# Test CUDA
python -c "import torch; print(torch.cuda.is_available())"
```

## Production Deployment

### Docker with GPU Support
```dockerfile
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Install PyTorch
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run with GPU
# docker run --gpus all research-pilot
```

### Multi-GPU (Future)
```python
# Data parallelism for embeddings
model = torch.nn.DataParallel(model)

# Tensor parallelism for LLMs
llm = LLM(model="...", tensor_parallel_size=2)
```

## References

- [CUDA Toolkit Documentation](https://docs.nvidia.com/cuda/)
- [PyTorch CUDA Semantics](https://pytorch.org/docs/stable/notes/cuda.html)
- [vLLM Documentation](https://docs.vllm.ai/)
- [NVIDIA A6000 Specs](https://www.nvidia.com/en-us/design-visualization/rtx-a6000/)
