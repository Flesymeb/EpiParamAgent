# Dev Start

This file is the shortest restart path for the active `dev/` workspace.

## Runtime Config

Load order:

1. `dev/.env`
2. `dev/.env.local`
3. `dev/<module>/.env`
4. `dev/<module>/.env.local`

Use:
- `dev/.env` for shared defaults
- `dev/.env.local` for shared machine-local secrets
- module `.env.local` only when a module truly needs a different runtime
- avoid creating new module `.env` files; they are legacy-compatible but not the preferred path

## Canonical Daily Workflow

### Literature Search

```powershell
cd dev/literature_search
uv sync
.venv\Scripts\Activate.ps1
```

Use this order:

1. raw / GT changed
```powershell
scripts\ops\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -IncludeGt -FixMissing
```

2. formal screening experiment
```powershell
scripts\ops\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -BatchSize 10 -BatchConcurrency 3 -AutoFulltext
```

3. one-command wrapper
```powershell
scripts\ops\run_pipeline.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -IncludeGt -FixMissing -BatchSize 10 -BatchConcurrency 3 -AutoFulltext
```

4. analysis / failure cases
```powershell
..\workbench\scripts\ops\run_workbench.ps1
```

### Coding Sheet

```powershell
cd dev/coding_sheet
uv sync
.venv\Scripts\Activate.ps1
```

Main entry:

```powershell
python cli/extract_epi.py --input papers/pdfs_all --out output/epi_extract --stage both
```

## Shared Boundaries

Shared:
- runtime config loading
- provenance manifests
- MinerU client
- PDF fetch tooling

Module-local:
- screening configs and prompts
- extraction prompts and codebooks
- evaluation / reporting logic

## Output Locations

- screening results: `evaluation/screening/GT_1/GT_export/{topic}/pXX/`
- full-text cache: `dev/paper_pool/`
- coding outputs: `dev/coding_sheet/output/`
- manifests: next to workflow outputs
