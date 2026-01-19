# Coding Sheet - Meta-Analysis Data Extraction

LLM-based automated coding sheet extraction for systematic literature review and meta-analysis.

**Originally developed for**: Early numeracy → math achievement (psychology)  
**Adapted for**: Epidemiology meta-analysis (COVID-19 variants, reproduction numbers)

## Features

- **PDF Download**: Automated Sci-Hub PDF retrieval with DDoS-Guard bypass (Playwright)
- **Text Extraction**: MinerU VLM (Vision Language Model) for complex tables/layouts
- **LLM Extraction**: Structured data extraction with Pydantic validation + config-based schemas
- **Flexible Templates**: YAML-based field definitions (no code changes needed)
- **Export**: Excel/CSV with formatting and quality checks

## Quick Start

### 1. Setup Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your API keys:
# - OPENAI_API_KEY or ANTHROPIC_API_KEY
# - NCBI_EMAIL (for PubMed)
# - MINERU_BASE_URL (optional, for MinerU service)
```

### 2. Download PDFs from DOI

```bash
# Create DOI list: papers/doi.txt (one DOI per line)
echo "10.1111/cdev.12676" > papers/doi.txt

# Download with automatic DDoS-Guard bypass
python scripts/get_scihub_urls.py --download
# → Saves PDFs to papers/pdfs/
# → Records URLs in papers/scihub_urls.jsonl
```

### 3. Extract Data

```bash
# Extract from local PDFs using custom template
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --out output/extraction \
  --method mineru \
  --template v2

# Example templates:
# - v2: COVID-19 variants reproduction numbers (epidemiology)
# - covid_variants: Same as v2
# - early_numeracy: Early numeracy meta-analysis (legacy, psychology)
```

**Output**: `output/extraction/run_YYYYMMDD_HHMMSS/coding_sheet_*.xlsx`

## Core Scripts

| Script               | Purpose                                             |
| -------------------- | --------------------------------------------------- |
| `get_scihub_urls.py` | Download PDFs from Sci-Hub (with Playwright bypass) |
| `run_extraction.py`  | Extract structured data from PDFs → Excel           |
| `script_utils.py`    | Shared utilities                                    |

## Configuration

### Templates

Located in `src/coding_sheet/configs/templates/`:

- **`v2.yaml` / `covid_variants.yaml`**: COVID-19 variants reproduction numbers (R0/Re/Relative R)
- **`early_numeracy.yaml`**: Early numeracy → math achievement (legacy, psychology domain)
- **Create custom**: Copy existing template and modify fields for your meta-analysis

### Environment Variables

```bash
# LLM Provider (required)
LLM_PROVIDER=openai              # or anthropic
LLM_MODEL=gpt-4o                 # or claude-3-5-sonnet-20241022
OPENAI_API_KEY=sk-...            # or ANTHROPIC_API_KEY

# PubMed (optional, for DOI resolution)
NCBI_EMAIL=your.email@example.com
NCBI_API_KEY=your_api_key        # optional, increases rate limit

# MinerU (optional, for PDF extraction)
MINERU_BASE_URL=https://mineru.example.com
MINERU_TIMEOUT_S=300

# Proxy (optional, for restricted networks)
HTTP_PROXY=http://proxy:port
HTTPS_PROXY=http://proxy:port
```

## Documentation

- **[Sci-Hub Download Guide](docs/SCIHUB_DOWNLOAD_GUIDE.md)**: Proxy setup, Playwright mode, troubleshooting
- **[Input Modes](docs/INPUT_MODES.md)**: Local PDF vs URL mode comparison
- **[Features & Roadmap](docs/FEATURES.md)**: Implemented features and TODO list

## Workflow Comparison

### ✅ Recommended: Two-Step Workflow

```bash
# Step 1: Download PDFs (with Playwright fallback for 403)
python scripts/get_scihub_urls.py --download

# Step 2: Extract from local files (fast, repeatable)
python scripts/run_extraction.py --input papers/pdfs/ --method mineru
```

**Advantages**:

- Playwright handles DDoS-Guard challenges
- PDFs cached locally for repeated runs
- Easy to debug download vs extraction issues

### ⚠️ Not Recommended: One-Step URL Mode

```bash
# Download + extract in one step (no Playwright fallback)
python scripts/run_extraction.py --input papers/scihub_urls.txt --method mineru
```

**Limitations**:

- Uses cloudscraper only (fails on 403)
- No Playwright browser automation
- Downloads not cached

## Troubleshooting

### OpenRouter Credits Error

```
Error code: 402 - You requested up to 100000 tokens, but can only afford 42902
```

**Solution**: Reduce `max_tokens` in your template YAML or add credits to OpenRouter account.

### Sci-Hub 403 Errors

**Solution**: Use two-step workflow. `get_scihub_urls.py --download` has Playwright fallback.

### Proxy Configuration

```bash
# Windows PowerShell
$env:HTTP_PROXY="http://proxy:port"
python scripts/get_scihub_urls.py --download

# Linux/Mac
export HTTP_PROXY="http://proxy:port"
python scripts/get_scihub_urls.py --download
```

## Output Structure

```
output/run_YYYYMMDD_HHMMSS/
├── coding_sheet_early_numeracy.xlsx    # Main results
├── coding_sheet_early_numeracy.csv     # CSV version
├── pdf_meta.json                       # Extraction metadata
├── mineru_assets/                      # MinerU outputs
│   └── [DOI]/auto/*.md                # Markdown + images
└── debug/                              # Debug info
    ├── raw_llm/                        # LLM responses
    └── failed_extractions.json         # Error records
```

## Advanced Usage

### Debug Mode (First 3 Papers Only)

```bash
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --mode debug \
  --method mineru
```

### Custom Template

```bash
# Copy and modify a template
cp src/coding_sheet/configs/templates/early_numeracy.yaml my_template.yaml

# Use custom template
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --config my_template.yaml \
  --method mineru
```

## Project Structure

```
coding_sheet/
├── scripts/                    # Executable scripts
│   ├── get_scihub_urls.py     # PDF download
│   ├── run_extraction.py      # Data extraction
│   └── script_utils.py        # Utilities
├── src/coding_sheet/          # Core library
│   ├── configs/               # Templates
│   ├── extraction/            # Extractors
│   └── utils/                 # Helpers
├── papers/                    # Input data
│   ├── doi.txt               # DOI list
│   ├── pdfs/                 # Downloaded PDFs
│   └── scihub_urls.jsonl     # URL records
├── output/                    # Extraction results
└── docs/                      # Documentation
```

## License

Part of MetaAgent project for automated meta-analysis.
