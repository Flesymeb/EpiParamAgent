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

Shared runtime config:

- put shared defaults in `dev/.env`
- put machine-specific secrets in `dev/.env.local`
- keep module-only overrides in `dev/literature_search/.env.local` or `dev/coding_sheet/.env.local`

### Literature Search

```powershell
cd dev/literature_search
uv sync
.venv/Scripts/activate

# Run LangGraph dev server (optional)
langgraph dev --allow-blocking
```

### Coding Sheet Extraction

```powershell
cd dev/coding_sheet
uv sync
.venv/Scripts/activate

# Run extraction
python cli/extract_epi.py --input pmid.txt --out output/epi_extract --stage both
```

## Key Entrypoints

- Literature search + screening:
  - `dev/literature_search/scripts/cli/screening_llm_batch.py`
  - `dev/literature_search/scripts/ops/run_llm_screening.ps1`
- PDF fetcher:
  - `dev/tools/paper_fetch/pdf_fetcher.py`
- Coding sheet extraction:
  - `dev/coding_sheet/cli/extract_epi.py`

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
- `dev/START.md`
- `dev/literature_search/README.md`
- `dev/coding_sheet/README.md`
