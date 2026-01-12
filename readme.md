# MetaAgent

> A modular agentic workflow for scientific meta-analysis.

---

## 🔍 Modules

All modules are under `dev/` for active development.

### 1. Literature Search (`dev/literature_search/`)

- **LangGraph pipeline**: Scoping → Query Generation → Multi-DB Retrieval → Deduplication → Auto-screening
- **Data sources**: PubMed, ERIC, etc.
- **Output**: Screened papers with inclusion decisions + screening reports

### 2. Coding Sheet Extraction (`dev/coding_sheet/`)

Now, we only support the correlation template extraction.

`dois` => `get_scihub_urls` => `pdf→markdown` (MinerU) => `LLM extraction` => `coding sheet`

- **Multi-timepoint extraction**: Longitudinal studies → ALL timepoints (no filtering during extraction)
- **Dependency tracking**: `sample_id`, `is_dependent` for multilevel meta-analysis
- **Smart calculation**: Sample sizes from missing rates, n from (T1+T2)/2
- **Templates**: `early_numeracy`, `correlation`, `intervention` (YAML-based schemas)

---

## 🚀 Quick Start

### Literature Search

```bash
cd dev/literature_search
uv sync
cp .env.example .env  # Add API keys

# Run the search pipeline
.venv\Scripts\activate

langgraph dev --allow-blocking
```

### Coding Sheet Extraction

```bash
cd dev/coding_sheet
uv sync
cp .env.example .env  # Add API keys
.venv\Scripts\activate
```

```
# 1) get Sci-Hub URLs from DOIs
python scripts/get_scihub_urls.py --input dois.txt --out scihub_urls.txt
# 2) run extraction
python scripts/run_extraction.py --input papers/scihub_urls.txt --out output/extraction_fixed --method mineru --mode debug --template early_numeracy --continue-on-error
```

---

## 📚 Documentation

- Literature Search: [START.md](dev/literature_search/START.md)
- Coding Sheet: [FEATURES.md](dev/coding_sheet/docs/FEATURES.md)
- Template Config: [early_numeracy.yaml](dev/coding_sheet/src/coding_sheet/configs/templates/early_numeracy.yaml)

---

## 🗂️ Database Support

**Literature Search Module**:

- [x] PubMed (NCBI Entrez API)
- [x] ERIC (IES API)
- [ ] PsycINFO
- [ ] ProQuest

**Coding Sheet Module**:

- PDF → Markdown: MinerU VLM
- Paper access: Sci-Hub integration
