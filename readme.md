# MetaAgent-Epi

MetaAgent-Epi is a CLI-first research codebase for LLM-assisted screening,
full-text coding, extraction, and pooling in infectious-disease systematic
reviews.

This repository contains core runtime source code and configuration examples
only. Manuscripts, datasets, cached papers, credentials, test workspaces,
baseline experiments, and generated outputs are kept locally and are not
versioned.

## Requirements

- Python 3.11 or newer
- Git
- Access to an OpenAI-compatible LLM endpoint
- Optional: NCBI API credentials for PubMed retrieval
- Optional: MinerU credentials for PDF parsing

## Installation

```bash
git clone git@github.com:Flesymeb/MetaAgent-Epi.git
cd MetaAgent-Epi

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

cp .env.example .env.local
metaagent --help
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Set the provider, model, API base URL, and API key in `.env.local`. Never
commit `.env.local` or place credentials in scripts.

## Screening Quick Start

For a new review, start with explicit CSV inputs. The candidate file must
contain `PMID`, `Title`, and `Abstract` columns. A small evaluation set is
optional and needs only a `PMID` column.

```text
project_data/
├── raw.csv
└── ground_truth.csv
```

Run title-and-abstract screening:

```bash
metaagent screening run \
  --input project_data/raw.csv \
  --output project_output/screened.csv \
  --ground-truth project_data/ground_truth.csv \
  --research-question "Studies of avian influenza reporting positivity rates" \
  --strategy 5d \
  --batch-mode multi \
  --batch-size 20 \
  --batch-concurrency 5
```

Evaluate the run against the small ground-truth set:

```bash
metaagent screening evaluate performance \
  --ground-truth project_data/ground_truth.csv \
  --screened-results project_output/screened.csv
```

Repeat the workflow with a separate research question and output directory for
the avian-influenza reproduction-number review. Keep the ground-truth labels
for evaluation; do not insert them into prompts or decision rules.

Profile-based `prepare`, `run`, and `pipeline` commands are also available.
Existing YAML files under `configs/*/screening_profiles/` show the expected
profile structure. New disease profiles should define their own review
question, PubMed query, eligibility criteria, date range, and local data paths.

## Coding and Extraction

The coding CLI operates on locally available full text and disease-specific
codebooks:

```bash
metaagent coding --help
metaagent coding extract --help
```

The repository currently includes COVID-19 and mpox coding examples. A new
avian-influenza study must add and validate parameter-specific codebooks and
prompts before its coding results are used in an experiment.

## Repository Layout

- `metaagent/`: reusable screening, coding, extraction, and analysis package.
- `configs/`: tracked screening profiles, codebooks, and prompt templates.
- `tools/`: PubMed, PDF, MinerU, pooling, and evaluation utilities.

The following local paths are intentionally ignored by Git:

- `dataset/` and `data/`
- `paper_pool/` and `external/`
- `baselines/`, `e2e/`, and `evaluation/`
- `tests/`, `scripts/`, and `webapp/`
- `output/`
- `docs/`
- `archive/`

Do not force-add files from these paths. Share approved datasets and experiment
artifacts through the project storage agreed by the research team.
