# Literature Search

Search, screening, and evaluation workflow for epidemiology-oriented literature review.

## What This Module Owns

- screening-ready raw dataset construction
- LLM screening on title/abstract
- optional full-text rescue for no-abstract papers
- evaluation against ground truth

## Quick Start

```powershell
cd dev/literature_search
uv sync
.venv\Scripts\Activate.ps1
```

Runtime config:
- shared defaults: `dev/.env`
- shared machine overrides: `dev/.env.local`
- module-only overrides: `dev/literature_search/.env.local`

## Canonical Workflow

### 1. Prepare raw dataset

Use when raw or ground truth changed.

```powershell
scripts\ops\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -IncludeGt -FixMissing
```

### 2. Run formal screening + evaluation

```powershell
scripts\ops\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -BatchSize 10 -BatchConcurrency 3 -AutoFulltext
```

### 3. Run the one-command wrapper

```powershell
scripts\ops\run_pipeline.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -IncludeGt -FixMissing -BatchSize 10 -BatchConcurrency 3 -AutoFulltext
```

### 4. Inspect results

```powershell
..\workbench\scripts\ops\run_workbench.ps1
```

## Directory Roles

- `scripts/cli/`: workflow entrypoints
- `scripts/ops/`: PowerShell wrappers for supported runs
- `scripts/tools/`: supporting utilities
- `src/screening/`: screening domain modules
- `archive/`: deprecated dashboards, tests, and scratch assets

## Core Entrypoints

- [`screening_prepare_raw.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/cli/screening_prepare_raw.py)
- [`screening_llm_batch.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/cli/screening_llm_batch.py)
- [`screening_evaluation.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/cli/screening_evaluation.py)
- [`run_prepare_raw.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/ops/run_prepare_raw.ps1)
- [`run_screening_eval.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/ops/run_screening_eval.ps1)
- [`run_pipeline.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/ops/run_pipeline.ps1)

## Outputs

- screening outputs: `evaluation/screening/GT_1/GT_export/{topic}/pXX/`
- full-text cache: `dev/paper_pool/`
- manifests: next to outputs or under `screening_logs/`

## Notes

- Primary source is PubMed.
- Full-text fallback uses shared tooling under `dev/tools/paper_fetch/` and `dev/tools/mineru/`.
- Legacy Streamlit dashboard and one-off tests were moved to `archive/`.
