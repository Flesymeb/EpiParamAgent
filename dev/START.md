# MetaAgent-Epi Restart Guide

## Runtime Config

Runtime env is loaded in this order:

1. `dev/.env`
2. `dev/.env.local`
3. `dev/<module>/.env`
4. `dev/<module>/.env.local`

Current rule:

- shared defaults go in `dev/.env`
- personal secrets or machine-specific overrides go in `dev/.env.local`
- only module-specific overrides go in module-level `.env.local`

Do not duplicate the same LLM base/key in both `coding_sheet/.env` and
`literature_search/.env` unless you intentionally want different runtimes.

## Main Workflows

### Literature Search

Working dir:

```powershell
cd dev/literature_search
uv sync
.venv\Scripts\Activate.ps1
```

Main entrypoints:

- `scripts/cli/screening_llm_batch.py`
- `scripts/cli/screening_prepare_raw.py`
- `scripts/cli/screening_evaluation.py`
- `scripts/ops/run_llm_screening.ps1`
- `scripts/ops/run_prepare_raw.ps1`
- `scripts/ops/run_screening_eval.ps1`

### Coding Sheet

Working dir:

```powershell
cd dev/coding_sheet
uv sync
.venv\Scripts\Activate.ps1
```

Main entrypoints:

- `cli/extract_epi.py`
- `run_codebook_extract.ps1`

Shared dependencies:

- `dev/tools/paper_fetch`
- `dev/tools/mineru`
- `dev/tools/common/config.py`

## Structure

- `dev/tools`: shared runtime/config/fetch/markdown infrastructure
- `dev/literature_search`: search, screening, evaluation workflows
- `dev/coding_sheet`: extraction workflows

## Current Refactor Boundary

What is shared:

- runtime config loading
- MinerU client
- PDF fetch tooling
- run manifest / provenance logging

What stays module-local:

- screening configs and prompts
- codebook and extraction prompts
- evaluation/report scripts

## Provenance

Primary workflows now emit `run_manifest_*.json` files alongside outputs:

- screening: `screening_logs/`
- prepare-raw: output CSV directory
- evaluation: result directory
- coding-sheet extraction: extraction output directory
