# MetaAgent-Epi

Modular workflows for epidemiology-oriented meta-analysis. Active development lives under `dev/`.

## Modules

- **Literature Search** (`dev/literature_search`)
  - LangGraph pipeline for scoping, query generation, retrieval, deduplication, and screening.
  - Primary source: PubMed. Optional clients exist (ERIC/Embase placeholders).
  - Screening supports abstract-first with full-text fallback.

- **Coding Sheet Extraction** (`dev/coding_sheet`)
  - PDF acquisition → MinerU → LLM extraction → coding sheet output.
  - Templates are YAML-based (no code changes to add fields).

- **Shared Tools** (`dev/tools`)
  - `paper_fetch`: PDF download tooling (Sci‑Hub + PMC).
  - `mineru`: MinerU client and PDF→Markdown helpers.

## Quick Start

### Literature Search

```bash
cd dev/literature_search
uv sync
cp .env.example .env
.venv/Scripts/activate

# Run LangGraph dev server (optional)
langgraph dev --allow-blocking
```

### Coding Sheet Extraction

```bash
cd dev/coding_sheet
uv sync
cp .env.example .env
.venv/Scripts/activate

# Download PDFs
python scripts/pdf_fetcher.py --download

# Run extraction
python scripts/run_extraction.py --input papers/pdfs/ --out output/extraction --method mineru --template v2
```

## Key Entrypoints

- Literature search + screening:
  - `dev/literature_search/scripts/screening_llm_batch.py`
  - `dev/literature_search/scripts/run_llm_screening.ps1` (V1/V2/V3)
- PDF fetcher:
  - `dev/tools/paper_fetch/pdf_fetcher.py`

## Project Layout (high-level)

```
dev/
  literature_search/
  coding_sheet/
  tools/
docs/
misc/
```

For details, see:
- `dev/literature_search/README.md`
- `dev/coding_sheet/README.md`
