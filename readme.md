# MetaAgent-Epi

MetaAgent-Epi is a CLI-first research codebase for LLM-assisted screening,
full-text coding, extraction, and pooling in infectious-disease systematic
reviews.

This repository contains core runtime source code, configuration examples, and
empty workspace documentation. Manuscripts, datasets, cached papers,
credentials, test workspaces, baseline experiments, and generated outputs are
kept locally and are not versioned.

## Requirements

- Python 3.11 or newer
- Git
- [uv](https://docs.astral.sh/uv/)
- Access to an OpenAI-compatible LLM endpoint
- Optional: NCBI API credentials for PubMed retrieval
- Optional: MinerU credentials for PDF parsing

## Installation

```bash
# Install uv on Linux or macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone git@github.com:Flesymeb/MetaAgent-Epi.git
cd MetaAgent-Epi

uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .

cp .env.example .env.local
metaagent --help
```

On Windows PowerShell, install uv and activate the environment with:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
uv venv --python 3.11
.venv\Scripts\Activate.ps1
uv pip install -e .
```

Set the provider, model, API base URL, and API key in `.env.local`. Never
commit `.env.local` or place credentials in scripts.

Query generation, screening, and coding can use separate models through
`QUERY_LLM_*`, `SCREENING_LLM_*`, and `CODING_LLM_*`. The recommended student
defaults are Qwen3.7 Plus for query generation and screening, and GLM-5.2 for
coding.

## Screening Quick Start

Start the guided PubMed query wizard:

```bash
metaagent pubmed query
```

The wizard collects the research question, disease, epidemiological parameter,
publication dates in `YYYY-MM-DD` format, and project ID. It always saves the
generated query before asking whether PubMed should be searched. Answering
`yes` creates `raw.csv`; answering `no` leaves only the reusable query files.

```text
dataset/avian_influenza/screening/positivity_rate/p1/
├── query.json
├── query.txt
├── raw.csv
└── ground_truth.csv
```

The same operation can run non-interactively:

```bash
metaagent pubmed query \
  --no-interactive \
  --question "What is the positivity rate of avian influenza infection in humans?" \
  --disease "Avian influenza" \
  --parameter "Positivity rate" \
  --start-date 2000-01-01 \
  --end-date 2026-07-14 \
  --project-id p1 \
  --no-search
```

The candidate CSV must contain `PMID`, `Title`, and `Abstract` columns. A small
evaluation set is optional and needs only a `PMID` column.

Run title-and-abstract screening:

```bash
metaagent screening run \
  --input dataset/avian_influenza/screening/positivity_rate/p1/raw.csv \
  --output evaluation/avian_influenza/screening/positivity_rate/p1/screened.csv \
  --ground-truth dataset/avian_influenza/screening/positivity_rate/p1/ground_truth.csv \
  --research-question "Studies of avian influenza reporting positivity rates" \
  --strategy 5d \
  --batch-mode multi \
  --batch-size 20 \
  --batch-concurrency 5
```

Evaluate the run against the small ground-truth set:

```bash
metaagent screening evaluate performance \
  --ground-truth dataset/avian_influenza/screening/positivity_rate/p1/ground_truth.csv \
  --screened-results evaluation/avian_influenza/screening/positivity_rate/p1/screened.csv
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
- `dataset/`: local review inputs; only its README is tracked.
- `evaluation/`: generated run outputs; only its README is tracked.
- `paper_pool/`: local full-text cache; only its README is tracked.

The following local paths are intentionally ignored by Git:

- all contents under `dataset/`, `evaluation/`, and `paper_pool/`
- `data/` and `external/`
- `baselines/` and `e2e/`
- `tests/`, `scripts/`, and `webapp/`
- `output/`
- `docs/`
- `archive/`

Do not force-add files from these paths. Share approved datasets and experiment
artifacts through the project storage agreed by the research team.
