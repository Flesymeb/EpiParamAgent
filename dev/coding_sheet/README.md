# Coding Sheet Extraction

LLM-based extraction pipeline for meta-analysis coding sheets.

## Quick Start

```bash
cd dev/coding_sheet
uv sync
cp .env.example .env
.venv/Scripts/activate
```

### 1) Download PDFs

```bash
python scripts/pdf_fetcher.py --download
```

### 2) Extract

```bash
python scripts/run_extraction.py --input papers/pdfs/ --out output/extraction --method mineru --template v2
```

## Key Scripts

- `scripts/pdf_fetcher.py`: PDF download (Sci‑Hub + PMC)
- `scripts/run_extraction.py`: extraction → coding sheet

## Templates

Templates live in `src/coding_sheet/configs/templates/`:

- `v2.yaml` / `covid_variants.yaml`: COVID‑19 variants reproduction numbers
- `early_numeracy.yaml`: legacy template

## Notes

- MinerU client is shared in `dev/tools/mineru/`.
