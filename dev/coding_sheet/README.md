# Coding Sheet Extraction

LLM-based extraction workflow for meta-analysis coding sheets.

## Quick Start

```powershell
cd dev/coding_sheet
uv sync
.venv\Scripts\activate
```

Runtime config:
- shared defaults: `dev/.env`
- shared machine overrides: `dev/.env.local`
- module-only overrides: `dev/coding_sheet/.env.local`

## Supported Workflow

### 1. Download PDFs when needed

```powershell
python ../tools/paper_fetch/pdf_fetcher.py --input pmid.txt --input-type pmid --download
```

### 2. Run Stage A / Stage B extraction

```powershell
python cli/extract_epi.py --input papers/pdfs_all --out output/epi_extract --stage both
```

## Inputs

Supported input forms:
- a single PDF
- a directory of PDFs or Markdown files
- a `.txt` file of PMIDs mapped to `dev/paper_pool/pdfs/PMID_<pmid>.pdf`

## Outputs

- `output/epi_extract/index/PMID_*.index.json`
- `output/epi_extract/coding_sheet_*.xlsx`
- `run_manifest_*.json`

## Core Files

- [`extract_epi.py`](D:/AILab/MAS/Meta-Analysis/MetaAgent-Epi/dev/coding_sheet/cli/extract_epi.py)
- `configs/prompts/stage_a.py`
- `configs/prompts/stage_b.py`
- `configs/codebook_epi.yaml`

## Notes

- MinerU client is shared via `dev/tools/mineru/`.
- Runtime env is loaded via `dev/tools/common/config.py`.
- Legacy implementation is preserved under `old/`.
