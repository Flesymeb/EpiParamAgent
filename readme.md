# MetaAgent-Epi

LLM-powered epidemiological systematic review automation with three active modules:

- `metaagent/screening/`: literature search, screening, evaluation
- `metaagent/coding/`: PDF-to-coding-sheet extraction
- `workbench/`: local analysis and visualization console

## Quick Start

```bash
# Run the CLI
python -m metaagent.cli

# Or use the shell entry point
./metaagent.sh
```

## Project Structure

```
MetaAgent-Epi/
├── metaagent/              # Python package
│   ├── cli/                # Click CLI commands (screening, coding, pubmed, pdf)
│   ├── screening/          # LLM screening engine + cascade retrieval
│   ├── coding/             # Coding sheet extraction pipeline
│   ├── pubmed/             # PubMed + data source API clients
│   ├── analysis/           # Meta-analysis pooling statistics
│   ├── prompts/            # LLM prompt templates (5d, binary, peco, etc.)
│   └── epidemiology/       # Epidemiological utilities
├── tools/                  # Standalone scripts and utilities
│   └── scripts/
│       ├── screening_prepare.py    # Build screening-ready datasets
│       ├── screening_llm_batch.py  # Run screening for profiles or explicit CSVs
│       ├── screening_evaluation.py # Evaluate screening against ground truth
│       ├── screening_report.py     # Generate academic reports
│       ├── pubmed_manager.py       # PubMed batch operations
│       ├── evaluate_coding.py      # Coding evaluation and pooling
│       └── extract_coding.py       # Coding sheet extraction CLI
├── configs/                # YAML configuration files
│   ├── screening_profiles/     # Experiment profiles (per disease/parameter)
│   ├── codebooks/              # Coding codebook definitions
│   └── coding_prompts/         # Stage A/B coding prompts
├── workbench/              # Web UI dashboard (FastAPI + React)
├── evaluation/             # Ground truth + experiment results
├── dataset/                # Raw datasets
├── docs/                   # Documentation
├── tests/                  # Integration tests
└── paper_pool/             # Cached PDFs and markdown (gitignored)
```

## Module Map

### `metaagent/screening/`

Purpose:
- Run title/abstract and optional full-text screening
- Cascade retrieval for uncertain papers (Tier 1→2→3)
- Multi-strategy comparison (5d, binary, binary_baseline, binary_noguidance, peco)
- Cost tracking (tokens, time, USD)

CLI commands:
```bash
python -m metaagent.cli screening run --input papers.csv --output screened.csv --research-question "..." --strategy peco
python -m metaagent.cli screening run -p P4 --strategy 5d --provider lab --model deepseek-3.2
```

### `metaagent/coding/`

Purpose:
- Stage A (indexing) + Stage B (extraction) from full-text PDFs
- Codebook-driven configurable extraction
- Export to XLSX with quality scoring

### `workbench/`

Purpose:
- Inspect screening runs and failure cases
- Visualize metrics and manifests

## Runtime Config

Runtime env is loaded from:
1. `.env` -- shared defaults
2. `.env.local` -- machine-local secrets
3. `configs/` -- YAML profiles and codebooks

Module-specific LLM settings live in the root env file:
`SCREENING_LLM_PROVIDER`, `SCREENING_LLM_MODEL`, `CODING_LLM_PROVIDER`, and
`CODING_LLM_MODEL`. Provider profiles use variables such as
`LAB_BASE_URL`, `LAB_API_KEY`, `LAB_MODEL`, `OPENROUTER_BASE_URL`, and
`OPENROUTER_API_KEY`.

## Shared Infrastructure

- `tools/common/`: runtime config and provenance helpers
- `tools/paper_fetch/`: PDF download tooling (Sci-Hub)
- `tools/mineru/`: PDF-to-Markdown parsing (MinerU API)

## Canonical Workflow

For screening experiments:
1. Prepare raw dataset: `python tools/scripts/screening_prepare.py`
2. Run screening: `python -m metaagent.cli screening run --input ... --output ... --research-question "..."`
3. Evaluate: `python tools/scripts/screening_evaluation.py`
4. Analyze: open `workbench/`

## Legacy

The `dev/` directory contains the previous workspace structure and will be removed
once the migration is fully validated. All functionality has been migrated to the
new package layout.
