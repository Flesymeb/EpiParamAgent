# Literature Search (Epidemiology)

Epidemiology-focused literature search and screening pipeline.

## What It Does

- Generate search terms and Boolean queries
- Retrieve records (PubMed primary; ERIC/Embase optional placeholders)
- Normalize and deduplicate
- LLM screening (abstract-first with full-text fallback)

## Quick Start

```powershell
cd dev/literature_search
uv sync
.venv/Scripts/activate
```

Runtime config:

- shared defaults: `dev/.env`
- shared local overrides: `dev/.env.local`
- literature_search-only overrides: `dev/literature_search/.env.local`

Run LangGraph dev server (optional):

```powershell
langgraph dev --allow-blocking
```

Run batch screening:

```powershell
python scripts/cli/screening_llm_batch.py --input ..\\langgraph_runs\\ground_truth\\search_v2\\search_v2_raw.csv --output ..\\langgraph_runs\\ground_truth\\search_v2\\test_screen\\search_v2_screened.csv --config V2 --auto-fulltext --batch-size 3
```

Or use the helper script:

```powershell
scripts\\ops\\run_llm_screening.ps1 V2
```

Run the local screening dashboard:

```powershell
scripts\\ops\\run_screening_dashboard.ps1
```

## Key Scripts

- `scripts/cli/`: 主入口（screening / prepare raw / evaluation）
- `scripts/ops/`: PowerShell 运行脚本
- `scripts/tools/`: 功能性工具（PubMed 修复、配置等）
- `scripts/tests/`: 测试/实验脚本

常用入口：
- `scripts/cli/screening_llm_batch.py`: LLM screening (abstract + full-text)
- `scripts/cli/screening_prepare_raw.py`: merge GT + fix missing
- `scripts/cli/screening_evaluation.py`: evaluate screened results vs ground truth
- `scripts/ops/run_llm_screening.ps1`: run V1/V2/V3 configs with standard paths
- `apps/screening_dashboard.py`: Streamlit dashboard for manifests + screened CSVs
- `scripts/ops/run_screening_dashboard.ps1`: launch the local dashboard

## Data Sources

- PubMed (primary)
- ERIC (optional)
- Embase (placeholder; requires institutional access)

## Notes

- Full-text cache: `dev/paper_pool/` (PDFs + Markdown).
- Prompts: `src/epidemiology/prompts/`.
- Runtime env is loaded via `dev/tools/common/config.py`.
- Main workflows emit `run_manifest_*.json` next to outputs for provenance.
