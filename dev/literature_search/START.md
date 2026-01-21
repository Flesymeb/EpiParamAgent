# Literature Search - Start Here

## Setup

```bash
cd dev/literature_search
uv sync
cp .env.example .env
.venv/Scripts/activate
```

## Run Screening (V1/V2/V3)

```bash
scripts\\run_llm_screening.ps1 V2
```

## Run LangGraph Dev Server (optional)

```bash
langgraph dev --allow-blocking
```

## Outputs

- Screening outputs: `dev/literature_search/langgraph_runs/...`
- Full-text cache: `dev/paper_pool/`
