# MetaAgent-Epi

MetaAgent-Epi is a CLI-first workflow for LLM-assisted literature screening,
full-text coding, parameter extraction, and pooling in infectious-disease
systematic reviews.

The tracked repository contains reusable source code and configuration
templates. Datasets, downloaded papers, credentials, experiment outputs,
manuscripts, and local tests remain outside Git.

## Workflow

| Step | Command | Main output |
| --- | --- | --- |
| 1. Build a query and retrieve records | `metaagent pubmed query` | `query.json`, `query.txt`, `raw.csv` |
| 2. Screen titles and abstracts | `metaagent screening run` | screened CSV and run manifest |
| 3. Inspect S/P/U decisions | `metaagent screening summary` | Strong, Possible, Unlikely, and retained counts |
| 4. Fetch selected full text | `metaagent pdf fetch` | shared PDFs and a project fetch manifest |
| 5. Code and extract parameters | `metaagent coding extract` | evidence index and coding sheet |
| 6. Pool coded estimates | `metaagent coding evaluate` | pooled summary CSV |

Run `metaagent <group> --help` or
`metaagent <group> <command> --help` for the complete option list.

## Requirements

- Python 3.11 or newer
- Git
- [uv](https://docs.astral.sh/uv/)
- An OpenAI-compatible LLM endpoint
- NCBI credentials for sustained PubMed retrieval (recommended)
- A MinerU API key when PDFs need to be converted to Markdown

## Installation

```bash
# Install uv on Linux or macOS.
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone https://github.com/Flesymeb/MetaAgent-Epi.git
cd MetaAgent-Epi

uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

cp .env.example .env.local
metaagent --help
```

On Windows PowerShell:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
uv venv --python 3.11
.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

## Configuration

Edit `.env.local`; never commit it. Query generation, screening, and coding
can use separate models. A minimal Bailian configuration is:

```dotenv
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_API_KEY=replace_with_your_key

QUERY_LLM_PROVIDER=bailian
QUERY_LLM_MODEL=qwen3.7-plus
SCREENING_LLM_PROVIDER=bailian
SCREENING_LLM_MODEL=qwen3.7-plus
CODING_LLM_PROVIDER=bailian
CODING_LLM_MODEL=glm-5.2

NCBI_EMAIL=your_email@example.com
NCBI_API_KEY=replace_with_your_ncbi_key
MINERU_API_KEY=replace_with_your_mineru_key
```

Provider-specific model IDs can differ. Confirm the IDs exposed by your
endpoint before starting a large run.

## Screening Workflow and Coding Hand-off

The examples below use the included avian-influenza positivity-rate screening
profile, `AI1`. The reproduction-number profile is `AIR1`. Steps 1-4 are the
configured screening workflow. Steps 5-6 show the coding hand-off and become
executable after a validated avian-influenza codebook and coding prompts have
been added; the CLI fails clearly while those files are absent.

### 1. Generate a PubMed query and retrieve records

Start the guided wizard:

```bash
metaagent pubmed query
```

The wizard asks for the research question, disease, parameter, publication
dates in `YYYY-MM-DD` format, and a project ID beginning with `p` (for example,
`p1`). It saves the query first, then asks whether PubMed should be searched.
Choose `yes` to create `raw.csv`.
Selecting `all` retrieves all matching PubMed records through paginated
requests; it is not limited to 1,000 records.

Equivalent non-interactive command:

```bash
metaagent pubmed query \
  --no-interactive \
  --question "What is the positivity rate of avian influenza infection in humans?" \
  --disease "Avian influenza" \
  --parameter "Positivity rate" \
  --start-date 2000-01-01 \
  --end-date 2026-07-14 \
  --project-id p1 \
  --search \
  --retmax all
```

To use a query you wrote or edited yourself, bypass LLM query generation while
keeping the same metadata and retrieval workflow:

```bash
metaagent pubmed query \
  --no-interactive \
  --manual-query \
  --query-file /path/to/pubmed_query.txt \
  --question "What is the positivity rate of avian influenza infection in humans?" \
  --disease "Avian influenza" \
  --parameter "Positivity rate" \
  --start-date 2000-01-01 \
  --end-date 2026-07-14 \
  --project-id p1 \
  --search \
  --retmax all
```

Use `--query "..."` instead of `--query-file` for a short query. Use
`--no-search` when only the reproducible query files should be saved.

The resulting project directory is:

```text
dataset/avian_influenza/screening/positivity_rate/p1/
├── query.json
├── query.txt
├── raw.csv                 # present after PubMed retrieval
└── ground_truth.csv        # optional, supplied by the researcher
```

### 2. Run title-and-abstract screening

Profile mode is recommended because it loads the review question and
parameter-specific eligibility guidance from `configs/`:

```bash
metaagent screening run \
  --profile AI1 \
  --strategy 5d \
  --batch-mode multi \
  --batch-size 20 \
  --batch-concurrency 5
```

Before the first LLM request, the CLI inspects `PMID`, `Title`, `Abstract`, and
`Keywords`. In an interactive terminal it offers to retrieve missing PubMed
metadata. Before an in-place update it creates `raw.before_enrichment.csv`.
Records without a recoverable abstract remain available for title-only
screening; they are not silently discarded.

For unattended runs, make the metadata behavior explicit:

```bash
# Retrieve available missing metadata, then screen.
metaagent screening run --profile AI1 --no-interactive --fix-missing \
  --batch-mode multi --batch-size 20 --batch-concurrency 5

# Screen the available text without modifying raw.csv.
metaagent screening run --profile AI1 --no-interactive --no-fix-missing \
  --batch-mode multi --batch-size 20 --batch-concurrency 5
```

The latest profile output is written to:

```text
evaluation/screening/avian_influenza/positivity_rate/p1/project_1_screened.csv
```

For a review without a YAML profile, pass `--input`, `--output`, and
`--research-question` explicitly. Parameter-specific profile mode should be
preferred for a formal experiment.

### 3. Inspect screening decisions

```bash
metaagent screening summary --profile AI1
```

Or inspect any compatible screened CSV:

```bash
metaagent screening summary \
  --input evaluation/screening/avian_influenza/positivity_rate/p1/project_1_screened.csv
```

The command reports:

- `S` (Strong): clear evidence of eligibility;
- `P` (Possible): potentially eligible but requires full-text verification;
- `U` (Unlikely): unlikely to meet the review criteria;
- retained records: `S + P`, used as the default input to full-text retrieval.

Use `--json` for machine-readable counts. If a small ground-truth set is
available, evaluate it separately:

```bash
metaagent screening evaluate performance \
  --ground-truth dataset/avian_influenza/screening/positivity_rate/p1/ground_truth.csv \
  --screened-results evaluation/screening/avian_influenza/positivity_rate/p1/project_1_screened.csv
```

Ground-truth labels are for evaluation only and must not be inserted into the
screening prompt or decision rules.

### 4. Fetch full text for S+P records

The guided command is:

```bash
metaagent pdf fetch
```

For a reproducible unattended run:

```bash
metaagent pdf fetch \
  --no-interactive \
  --disease avian_influenza \
  --parameter positivity_rate \
  --project-id p1 \
  --source screened \
  --input evaluation/screening/avian_influenza/positivity_rate/p1/project_1_screened.csv \
  --tiers S,P \
  --strategy pmc-only \
  --download
```

PDFs are deduplicated in a shared cache. The project directory records exactly
which PMIDs were selected and what happened during retrieval:

```text
paper_pool/
├── pdfs/PMID_<id>.pdf
└── projects/avian_influenza/positivity_rate/p1/
    ├── pmids.txt
    ├── fetch_plan.json
    └── fetch_results.csv
```

`pmc-only` is the safe default. A PMID without accessible PMC full text remains
in `fetch_results.csv` with its failure status; it is not treated as an
ineligible study.

### 5. Run full-text coding and extraction

After a validated coding configuration has been added, `coding extract`
automatically reads the project PMID list created in Step 4:

```bash
metaagent coding extract \
  --disease avian_influenza \
  --parameter positivity_rate \
  --project-id p1 \
  --stage both \
  --fetch-mode pmc_only
```

The command also resolves the codebook at:

```text
configs/avian_influenza/codebooks/positivity_rate.yaml
```

Before running a new disease/parameter formally, that codebook and its sibling
`configs/avian_influenza/coding_prompts/` files must be created and validated.
The repository currently includes complete coding examples for COVID-19 and
mpox; the avian-influenza repository profiles currently configure screening,
not a validated coding protocol. If the codebook is absent, the CLI stops with
an actionable error instead of silently using a different disease's schema.

An explicit input/codebook mode is also available:

```bash
metaagent coding extract \
  --input paper_pool/projects/avian_influenza/positivity_rate/p1/pmids.txt \
  --codebook configs/avian_influenza/codebooks/positivity_rate.yaml \
  --out evaluation/coding/avian_influenza/positivity_rate/p1/coding_runs/manual \
  --stage both \
  --fetch-mode pmc_only
```

The coding pipeline derives Stage A/B prompts from the codebook's sibling
`coding_prompts/` directory. Moving a codebook to an arbitrary standalone path
without that directory layout is therefore unsupported.

Coding stages are:

- `fetch`: retrieve/cache available PDFs and convert them to Markdown; no LLM call;
- `index`: run high-recall evidence localization (Stage A);
- `extract`: reuse or create the evidence index and run structured extraction (Stage B);
- `both`: run Stage A and Stage B; recommended for a fresh coding run.

Generated runs are stored under:

```text
evaluation/coding/<disease>/<parameter>/<project>/coding_runs/<timestamp>/
```

### 6. Pool extracted estimates

After a coding sheet has been generated:

```bash
metaagent coding evaluate \
  --disease avian_influenza \
  --parameter positivity_rate \
  --project p1 \
  --parameter-type positivity_rate \
  --method random
```

By default, evaluation uses the latest coding run that contains a coding sheet.
For a frozen or published experiment, pin it with `--run <run-directory-name>`.
If the requested `parameter_type` is absent, evaluation stops and lists the
available values instead of pooling unlike estimands. Use
`--all-parameter-types` only when pooling every type is scientifically
intentional.

Pooling is parameter-specific. Confirm units, denominator definitions,
estimate type, transformations, and inclusion rules before interpreting the
summary as a meta-analytic result.

## Adding a New Review

1. Add a screening profile under
   `configs/<disease>/screening_profiles/<parameter>.yaml`.
2. Give every review task a unique profile ID and `project_number`.
3. Run query generation/retrieval and verify `raw.csv` before screening.
4. Keep any GT file small and separate from prompts.
5. Before coding, add a parameter-specific codebook and Stage A/B prompt files
   under `configs/<disease>/`.
6. Pilot each stage on a few known papers before launching the full review.

The included `AI1` and `AIR1` files demonstrate screening profiles for avian
influenza positivity rate and human reproduction number, respectively. The
`_template.yaml` files under existing disease directories show the general
profile structure.

## Troubleshooting

**`metaagent` cannot be imported after installation**

Activate the same environment in which `uv pip install -e .` was run, then
check `which metaagent` (Linux/macOS) or `Get-Command metaagent` (PowerShell).

**PubMed reports a self-signed certificate**

Install the correct institutional CA certificate when possible. Only behind a
trusted institutional proxy, set `NCBI_VERIFY_SSL=false` in `.env.local`.
This disables certificate verification and should not be the general default.

**Only 1,000 PubMed records were retrieved**

Use `--retmax all`. The CLI paginates through all PubMed matches. A numeric
`--retmax` intentionally caps the result.

**Coding input was not found**

Run `metaagent pdf fetch` first, or pass `--input` explicitly. The default input
is `paper_pool/projects/<disease>/<parameter>/<project>/pmids.txt`.

**A codebook or Stage A schema was not found**

Add `configs/<disease>/codebooks/<parameter>.yaml` and the corresponding
`configs/<disease>/coding_prompts/` files, or pass a validated `--codebook`.
Do not substitute a codebook from another disease without review.

**Some S+P records have no PDF**

Inspect `fetch_results.csv`. Lack of open full text is a retrieval limitation,
not an exclusion decision, and should be reported separately.

## Repository Layout

- `metaagent/`: reusable screening, coding, extraction, and analysis package.
- `configs/`: tracked screening profiles, codebooks, and prompt templates.
- `tools/`: PubMed, PDF, MinerU, pooling, and evaluation utilities.
- `dataset/`: local review inputs; only its README is tracked.
- `evaluation/`: generated run outputs; only its README is tracked.
- `paper_pool/`: local full-text cache; only its README is tracked.

The following local workspaces are intentionally ignored by Git: `dataset/`,
`evaluation/`, `paper_pool/`, `docs/`, `tests/`, `scripts/`, `baselines/`,
`e2e/`, `webapp/`, `output/`, and `archive/` (except tracked placeholder
READMEs). Do not force-add local datasets, credentials, downloaded papers, or
experiment artifacts. Share approved research data through the storage agreed
by the project team.
