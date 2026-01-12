# Research Pilot Architecture

## System Overview

Research Pilot is built as a multi-agent system using LangGraph, designed to autonomously perform academic research tasks. The architecture follows modern RAG (Retrieval-Augmented Generation) patterns with GPU acceleration for performance-critical operations.

## Core Components

### 1. Agent Layer (LangGraph)

The agent orchestrates the entire research workflow using a state machine approach:

```python
States:
- START: Initial query analysis
- SEARCH: Paper discovery from multiple sources
- RETRIEVE: PDF download and parsing
- PROCESS: Embedding generation and storage
- ANALYZE: RAG-based synthesis
- REVIEW: Literature review generation
- END: Final output
```

**Agent Capabilities:**
- Query decomposition (complex → simple sub-queries)
- Multi-source search coordination
- Adaptive retrieval based on result quality
- Self-correction when encountering errors
- Progress tracking and state persistence

### 2. Data Sources Layer

#### PubMed/MEDLINE Integration
- Uses NCBI E-utilities API
- Supports boolean queries and date filters
- Metadata extraction (title, authors, abstract, journal, DOI)

#### ERIC Integration (optional)
- Uses IES ERIC API
- DOI enrichment via Crossref (optional)
- Education-focused coverage (optional for epidemiology)

#### Future Sources
- Embase (institutional)
- Google Scholar (via SerpAPI)
- CORE (open access repository)

### 3. PDF Processing Pipeline

```
PDF → Text Extraction → Chunking → Cleaning → Metadata
```

**Components:**
- **Parser**: PyMuPDF for fast extraction
- **OCR Fallback**: Tesseract for scanned PDFs
- **Chunking Strategy**:
  - Semantic chunking (respects section boundaries)
  - Fixed-size with overlap
  - Sentence-aware splitting
- **Metadata Extraction**: Title, sections, figures, tables, references

### 4. Embedding System

**GPU-Accelerated Embedding Generation:**
- Model: `sentence-transformers/all-mpnet-base-v2` (768-dim)
- Batch processing on AMD GPU (ROCm)
- Automatic device selection (GPU → CPU fallback)
- Embedding cache for efficiency

**Performance Optimization:**
- FP16 precision on GPU
- Dynamic batching based on VRAM
- Async processing for I/O operations

**Code Example:**
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    'all-mpnet-base-v2',
    device='cuda'  # ROCm compatible
)

embeddings = model.encode(
    chunks,
    batch_size=32,
    show_progress_bar=True,
    convert_to_tensor=True
)
```

### 5. Vector Store

**Primary: Qdrant**
- Efficient similarity search (HNSW index)
- Metadata filtering
- Payload storage for document chunks
- RESTful API

**Schema:**
```json
{
  "vector": [768-dimensional embedding],
  "payload": {
    "paper_id": "pubmed:12345678",
    "title": "Paper Title",
    "chunk_id": 42,
    "text": "Original text content",
    "section": "Introduction",
    "metadata": {...}
  }
}
```

**Alternative: ChromaDB**
- Embedded option (no server required)
- Good for development/testing

### 6. RAG Pipeline

#### Query Processing
1. Query expansion using LLM
2. Hybrid search (semantic + keyword)
3. Metadata filtering (date, citations, etc.)
4. Top-k retrieval (k=10-20)

#### Re-ranking
- Cross-encoder for relevance scoring
- Citation-aware ranking (prefer highly-cited papers)
- Diversity promotion (avoid redundant results)

#### Synthesis
- Context window management (Claude: 200k tokens)
- Multi-document reasoning
- Citation generation
- Conflict detection across papers

### 7. LLM Integration

**Primary: Claude (Anthropic)**
- Model: `claude-3-5-sonnet-20241022` or newer
- Long context for full paper analysis
- Strong reasoning for synthesis

**Secondary: OpenAI**
- Model: `gpt-4-turbo` or `gpt-4o`
- Fallback option

**Local Models (Optional):**
- Llama 3.1 (8B/70B via vLLM)
- Mixtral 8x7B
- Requires ROCm setup for AMD GPU

## Data Flow

### Research Query Flow
```
User Query
    ↓
[Agent: Query Analysis]
    ↓
[Search APIs: PubMed + ERIC]
    ↓
[Paper Ranking & Filtering]
    ↓
[PDF Download & Parse]
    ↓
[Chunking & Embedding (GPU)]
    ↓
[Vector Store: Insert]
    ↓
[RAG: Retrieve Relevant Chunks]
    ↓
[LLM: Synthesize Review]
    ↓
Final Output
```

### Embedding Generation Flow
```
PDF Documents
    ↓
[Text Extraction: PyMuPDF]
    ↓
[Chunking: Semantic]
    ↓
[Batch Formation: 32 chunks]
    ↓
[GPU Encoding: sentence-transformers]
    ↓
[Vector Store: Qdrant]
    ↓
[Cache: Local Storage]
```

## GPU Utilization Strategy

### AMD Radeon RX 6000 (40GB VRAM)

**Workload Distribution:**
1. **Embedding Generation (Primary)**
   - Batch size: 64-128 (depends on chunk length)
   - Expected throughput: 1000-5000 chunks/sec
   - VRAM usage: 2-4GB

2. **Local LLM Inference (Optional)**
   - Model size: Up to 70B parameters (quantized)
   - Inference speed: 10-30 tokens/sec
   - VRAM usage: 30-35GB

3. **Re-ranking Models**
   - Cross-encoders on GPU
   - Fast pairwise scoring
   - VRAM usage: 1-2GB

**ROCm Setup:**
```bash
# Install ROCm
sudo amdgpu-install --usecase=rocm

# Set environment variables
export HSA_OVERRIDE_GFX_VERSION=10.3.0  # For RX 6000
export ROCM_PATH=/opt/rocm

# Install PyTorch with ROCm
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm5.7
```

**Performance Benchmarks (Expected):**
- Embedding 1000 papers (avg 10 pages): 5-10 minutes
- Vector search (10k vectors): <100ms
- LLM generation (1000 tokens): 30-100 seconds

## Agent Decision Logic

### Search Strategy
```python
if initial_results < 5:
    expand_query()
    search_again()
elif initial_results > 100:
    add_filters(date_range, min_citations)
else:
    proceed_to_ranking()
```

### Quality Control
- Minimum citation threshold (configurable)
- Publication date relevance
- Full-text availability check
- Language filtering (English preferred)

### Error Handling
- Retry logic for API failures (exponential backoff)
- Fallback to alternative sources
- Graceful degradation (continue with partial results)

## Scalability Considerations

### Current Design
- Single machine deployment
- In-memory caching
- Local vector store

### Future Scaling
- Distributed vector search (Qdrant cluster)
- Job queue for async processing (Celery + Redis)
- Caching layer (Redis/Memcached)
- API rate limiting and quotas

## Security & Privacy

- API keys stored in environment variables
- No data sent to external services except chosen LLM API
- Local embedding generation (no data leakage)
- Optional: Fully local setup with local LLMs

## Configuration

See `configs/agent_config.yaml` for tunable parameters:
- Search limits and filters
- Embedding batch sizes
- RAG retrieval parameters
- LLM model selection
- GPU/CPU allocation

## Development Roadmap

### Phase 1 (MVP)
- [x] Basic agent structure
- [x] PubMed/ERIC integration
- [x] PDF parsing
- [x] Embedding generation
- [x] Vector store setup
- [ ] RAG pipeline
- [ ] Literature review generation

### Phase 2 (Enhancement)
- [ ] Advanced re-ranking
- [ ] Citation graph analysis
- [ ] Web UI

### Phase 3 (Advanced)
- [ ] Multi-agent collaboration
- [ ] Active learning from feedback
- [ ] Knowledge graph construction
- [ ] Integration with note-taking tools
