# MetaAgent-Epi

Epidemiology-oriented meta-analysis workspace with three active modules under `dev/`:

- `literature_search`: search, screening, evaluation
- `coding_sheet`: PDF-to-coding-sheet extraction
- `workbench`: local analysis and visualization console

## Start Here

For the current developer workflow, read:

- [`dev/START.md`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/START.md)

## Module Map

### `dev/literature_search`

Purpose:
- build screening-ready raw datasets
- run title/abstract and optional full-text screening
- evaluate results against ground truth

Primary entrypoints:
- [`run_prepare_raw.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/ops/run_prepare_raw.ps1)
- [`run_screening_eval.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/ops/run_screening_eval.ps1)
- [`run_pipeline.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/scripts/ops/run_pipeline.ps1)

Reference:
- [`dev/literature_search/README.md`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/literature_search/README.md)

### `dev/coding_sheet`

Purpose:
- acquire PDFs / markdown inputs
- run Stage A / Stage B extraction
- export coding sheet outputs

Primary entrypoints:
- [`extract_epi.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/coding_sheet/cli/extract_epi.py)
- [`run_codebook_extract.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/coding_sheet/run_codebook_extract.ps1)

Reference:
- [`dev/coding_sheet/README.md`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/coding_sheet/README.md)

### `dev/workbench`

Purpose:
- inspect screening runs
- inspect failure cases and metrics
- visualize manifests and outputs from active modules

Primary entrypoint:
- [`run_workbench.ps1`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/workbench/scripts/ops/run_workbench.ps1)

Reference:
- [`dev/workbench/README.md`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/workbench/README.md)

## Runtime Config

Runtime env is loaded in this order:

1. `dev/.env`
2. `dev/.env.local`
3. `dev/<module>/.env`
4. `dev/<module>/.env.local`

Rules:
- shared defaults go in `dev/.env`
- machine-local secrets go in `dev/.env.local`
- module-only overrides go in module-local `.env.local`

## Shared Infrastructure

Shared code lives under `dev/tools`:

- `common`: runtime config and provenance helpers
- `paper_fetch`: PDF download tooling
- `mineru`: PDF-to-Markdown helpers

## Canonical Workflow

For screening experiments, the supported path is:

1. raw / GT changed -> `run_prepare_raw.ps1`
2. formal experiment -> `run_screening_eval.ps1`
3. optional one-command wrapper -> `run_pipeline.ps1`
4. analysis / failure cases -> `run_workbench.ps1`

## Design Notes

Key workflow and documentation decisions are tracked in:

- [`docs/DECISIONS.md`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/docs/DECISIONS.md)
