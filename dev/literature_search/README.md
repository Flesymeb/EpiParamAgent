# MetaAgent-Epi: Literature Search & Screening for Epidemiology

Systematic literature search and screening pipeline optimized for **epidemiology and infectious disease research**.

## Features

- **Epidemiology-focused**: Keyword generation, screening criteria, and study design filters tailored for epidemiology research
- **Query generation**: LLM-based generation of comprehensive search terms (exposures, outcomes, risk factors, study designs)
- **Multi-source retrieval**: PubMed (primary) + ERIC (optional) + Embase (placeholder for institutional access)
- **LLM-based screening**: Automated abstract screening with epidemiologic study design evaluation
- **De-duplication**: Cross-database duplicate detection
- **Export formats**: CSV, JSON, PRISMA flowcharts

## Quick Start

### Installation

```bash
# Minimal installation (core search & screening only)
pip install -r requirements-minimal.txt

# OR full installation (includes PDF processing, embeddings)
pip install -r requirements-full.txt
```

### Configuration

Create your `.env` file:

```bash
cp .env.example .env
# Edit .env and add your API keys:
# - LLM_PROVIDER and ANTHROPIC_API_KEY or OPENAI_API_KEY (required)
# - NCBI_API_KEY and NCBI_EMAIL (highly recommended for PubMed)
# - EMBASE_API_KEY (optional, requires institutional subscription)
```

Customize pipeline behavior (optional):

```bash
# Edit configs/pipeline_config.yaml to control:
# - Data sources (default: PubMed only)
# - Query generation (LLM vs rule-based)
# - Result limits and filters
# - Screening criteria
# See docs/CONFIGURATION.md for details
```

### Run Literature Search

```python
from langgraph_pipeline.graph import build_graph, run_once

graph = build_graph()
result = run_once(
   graph,
   research_question='What is the association between air pollution exposure and cardiovascular disease incidence?',
   domain='environmental_epi',  # or 'infectious_disease', 'chronic_disease', etc.
   workdir='outputs/air_pollution_cvd'
)

print(f'Papers found: {len(result.deduped_records)}')
print(f'Included after screening: {len(result.included)}')
print(f'Results exported to: {result.workdir}')
```

## Architecture

The LangGraph pipeline (`langgraph_pipeline/graph.py`) executes:

```
scoping_search (optional)
  → generate_terms
  → build_queries
  → retrieve_pubmed / retrieve_eric (parallel)
  → normalize_and_dedupe
  → autoscreen_and_export
```

### Epidemiology-Specific Adaptations

1. **Domain configuration** ([configs/agent_config.yaml](configs/agent_config.yaml)):

   - Subdomains: infectious_disease, chronic_disease, environmental_epi, cancer_epi, etc.
   - Study designs: cohort, case-control, RCT, meta-analysis
   - Keyword categories: exposures, outcomes, risk factors, biomarkers

2. **Keyword generation** ([src/epidemiology/keyword_generator.py](src/epidemiology/keyword_generator.py)):

   - Generates terms for exposures, disease outcomes, study designs, populations
   - Optimized for PubMed MeSH terms and epidemiologic terminology

3. **Screening criteria** ([langgraph_pipeline/prompts/autoscreen.md](langgraph_pipeline/prompts/autoscreen.md)):
   - Evaluates study design appropriateness
   - Assesses exposure-outcome relationships
   - Considers temporality and population representativeness

## Data Sources

### Primary: PubMed/MEDLINE (FREE)

- **Coverage**: ~36 million citations in biomedicine and life sciences
- **API**: Free NCBI E-utilities API
- **Setup**: Get free API key at https://www.ncbi.nlm.nih.gov/account/
- **Rate limits**: 3/sec without key, 10/sec with key

### Optional: Embase (PAID - Requires Institutional Access)

- **Coverage**: ~40 million citations, strong in pharmacology and European literature
- **API**: Elsevier API (requires subscription)
- **Setup**: Contact your institution's library for API credentials
- **Status**: Placeholder implementation included (see [src/data_sources/embase_client.py](src/data_sources/embase_client.py))
- **Alternative**: Export Embase results manually and import alongside PubMed

### Optional: ERIC (FREE - Education Database)

- **Coverage**: Education research (NOT recommended for epidemiology)
- **Status**: Removed from default pipeline (configure in `configs/pipeline_config.yaml` if needed)

## Configuration

The system uses YAML configuration files for fine-grained control. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for complete documentation.

**Key settings** in `configs/pipeline_config.yaml`:

```yaml
# Data sources (default: PubMed only)
default_providers:
  - pubmed

# Query generation (LLM vs rule-based)
query_generation:
  use_llm_queries: true
  fallback_to_rules: true

# Result limits
pubmed:
  max_results: 500
  year_filter: null  # or "2020-2024"
```

**Quick configurations**:

- **Production** (default): `configs/pipeline_config.yaml`
- **Testing/debugging**: `configs/test_config.yaml` (fewer queries, smaller results)

## Examples

See [examples/](examples/) directory:

- [keyword_generator_test.py](examples/keyword_generator_test.py) - Generate search terms
- [boolean_search_test.py](examples/boolean_search_test.py) - Build PubMed queries

## Project Structure

```
literature_search/
├── langgraph_pipeline/      # LangGraph workflow definition
│   ├── graph.py             # Pipeline wiring
│   ├── nodes.py             # Node functions
│   ├── state.py             # State dataclass
│   └── prompts/             # LLM prompts
├── src/
│   ├── data_sources/        # PubMed, ERIC, Embase clients
│   │   ├── pubmed_client.py
│   │   ├── eric_client.py
│   │   ├── embase_client.py  # Placeholder
│   │   └── models.py         # Paper dataclass
│   └── epidemiology/        # Domain-specific modules
│       ├── keyword_generator.py
│       ├── boolean_search_agent.py
│       └── utils.py
├── examples/                # Usage examples
├── tests/                   # Integration tests
├── configs/                 # Configuration files
├── requirements-minimal.txt # Core dependencies only
└── requirements-full.txt    # All dependencies (PDF, embeddings)
```

## Development

LLM/provider configuration is read from `.env` / environment variables. See [.env.example](.env.example) for all configuration options.

For detailed setup instructions, see [START.md](START.md).
