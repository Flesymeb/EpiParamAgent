# Literature Search (Epidemiology)

Epidemiology-focused literature search and screening pipeline.

## What It Does

- Generate search terms and Boolean queries
- Retrieve records (PubMed primary; ERIC/Embase optional placeholders)
- Normalize and deduplicate
- LLM screening (abstract-first with full-text fallback)

## Quick Start

```bash
cd dev/literature_search
uv sync
cp .env.example .env
.venv/Scripts/activate
```

Run LangGraph dev server (optional):

```bash
langgraph dev --allow-blocking
```

Run batch screening:

```bash
python scripts/screening_llm_batch.py --input ..\\langgraph_runs\\ground_truth\\search_v2\\search_v2_raw.csv --output ..\\langgraph_runs\\ground_truth\\search_v2\\test_screen\\search_v2_screened.csv --config V2 --auto-fulltext --batch-size 3
```

Or use the helper script:

```bash
scripts\\run_llm_screening.ps1 V2
```

## Key Scripts

- `scripts/screening_llm_batch.py`: LLM screening (abstract + full-text)
- `scripts/screening_evaluation.py`: evaluate screened results vs ground truth
- `scripts/run_llm_screening.ps1`: run V1/V2/V3 configs with standard paths

## Data Sources

- PubMed (primary)
- ERIC (optional)
- Embase (placeholder; requires institutional access)

## Notes

- Full-text cache: `dev/paper_pool/` (PDFs + Markdown).
- Prompts: `src/epidemiology/prompts/`.
