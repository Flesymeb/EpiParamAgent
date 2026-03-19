# Coding Sheet Extraction

LLM-based extraction pipeline for meta-analysis coding sheets.

## Quick Start

```powershell
cd dev/coding_sheet
uv sync
.venv/Scripts/activate
```

Runtime config:

- shared defaults: `dev/.env`
- shared local overrides: `dev/.env.local`
- coding_sheet-only overrides: `dev/coding_sheet/.env.local`

### 1) Download PDFs (tools)

```powershell
python ../tools/paper_fetch/pdf_fetcher.py --input pmid.txt --input-type pmid --download
```

### 2) Stage A/B Extract (new)

```powershell
python cli/extract_epi.py --input papers/pdfs_all --out output/epi_extract --stage both
```

Outputs:
- `output/epi_extract/index/PMID_*.index.json`
- `output/epi_extract/coding_sheet_*.xlsx`

Input can be:
- a PDF file
- a directory of PDFs/Markdown
- a `.txt` file of PMIDs (will map to `dev/paper_pool/pdfs/PMID_<pmid>.pdf`)

## Key Scripts

- `cli/extract_epi.py`: Stage A/B extraction (new pipeline)
- `old/scripts/*`: legacy scripts (preserved)

## Templates

Prompts and codebook live in `configs/`:

- `configs/prompts/stage_a.py`
- `configs/prompts/stage_b.py`
- `configs/codebook_epi.yaml`

`codebook_epi.yaml` supports:
- `fields`: extraction fields (Stage B)
- `index_schema`: columns to export from Stage A index (dot paths)
- `stage_a` / `stage_b`: prompt overrides

## Notes

- MinerU client is shared in `dev/tools/mineru/`.
- Runtime env is loaded via `dev/tools/common/config.py`.
- Extraction runs emit `run_manifest_*.json` in the output directory.
- Legacy implementation preserved under `old/`.
