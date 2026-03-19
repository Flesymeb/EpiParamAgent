# Literature Search - Start Here

## Setup

```powershell
cd dev/literature_search
uv sync
.venv/Scripts/activate
```

Config rule:

- shared defaults: `dev/.env`
- local machine overrides: `dev/.env.local`
- literature_search-only overrides: `dev/literature_search/.env.local`

## Run Screening (V1/V2/V3)

```powershell
scripts\\ops\\run_llm_screening.ps1 -ConfigName P10 -Topic serial_interval
```

## Run Dashboard

```powershell
scripts\\ops\\run_screening_dashboard.ps1
```

## Run LangGraph Dev Server (optional)

```bash
langgraph dev --allow-blocking
```

## Outputs

- Screening outputs: `dev/literature_search/langgraph_runs/...`
- Full-text cache: `dev/paper_pool/`
- Screening manifests: next to outputs / `screening_logs/run_manifest_*.json`
