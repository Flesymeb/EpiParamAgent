# Screening with task context

The default five-dimension screen retains each 0–4 score and its reason. The LLM combines this evidence with the research question and review criteria to assign S/P/U. No weighted total or score threshold replaces its tag. `screening run --no-prefer-llm-tier` explicitly selects the legacy threshold path; `--prefer-llm-tier` is the default. Reports list strong candidates in input order and show their five dimensions, tag and review flags separately; the CSV retains every record. Missing source material or an invalid response may require review even when a model tag exists.

The recommended standalone module uses the same executor as the end-to-end workflow:

```bash
.venv/bin/metaagent screening task \
  --task-config configs/templates/review_task.yaml \
  --input path/to/bibliography.jsonl --input-mode raw_search \
  --output-dir runs/screening_task --dry-run --json
```

Remove `--dry-run` to execute only Screening. CSV and JSONL inputs may use PMID, DOI or a traceable source record ID. The task supplies the research question, original eligibility protocol and independent SCREENING model configuration. No Coding or Synthesis executes. Planning does not write output or call a service. `screening protocol-run` also accepts `--research-question` when a separate protocol is preferred; the older profile-based `screening run` remains compatible.

The research question gives context; review criteria determine eligibility. A downstream parameter or pooling target cannot narrow a complete review protocol. Missing abstracts/indexing do not establish exclusion. Keywords and MeSH are indexing context, not proof that a primary method or estimate was reported. Scientific decisions still require exact source evidence and ordinary protocol reduction. Original source-roster IDs are replaced with opaque transport IDs in model requests and mapped back after strict response-ID validation.

# Bibliographic completion

```bash
.venv/bin/metaagent literature enrich \
  --dataset-root dataset/benchmark_releases/20261104_experiment_ready_v1 \
  --out runs/metadata_completion \
  --xml-root dataset/benchmark_sources/original_alignment_retrieval_20261103
```

The default is offline. Add `--online --max-requests 500` for bounded public PubMed/Europe PMC requests. Add `--resume` for the same derived workspace: completed requests are reused and changed source inputs are rejected. One writer holds the workspace lease. The script `tools/scripts/enrich_benchmark_metadata.py` additionally exposes batch size, minimum request interval and explicit retry of failed lookups.

Existing nonempty fields, identities and versions remain unchanged. Author keywords and MeSH stay separate. An ID-bound official full title is added as `official_title` alongside a differing nonempty input title. A version-specific preprint is not silently enriched with an unversioned latest result. Unknown data remains missing.

The derived workspace contains:

- `enriched/profiles/*/raw_search.jsonl` and `raw_pool.jsonl`: original fields plus available metadata, per-field sources, unresolved fields and metadata conflicts. These preserve historical audit fields and are not the blind model view.
- `model_inputs/profiles/*/raw_search.jsonl` and `raw_pool.jsonl`: strict bibliographic allowlist with opaque record IDs, without eligibility labels, reference numbers, manual-rescue hints or metadata provenance.
- `MODEL_IDENTITY_MAP.jsonl`: score-only mapping from opaque IDs to original records. Do not feed this sidecar to a model.
- `COVERAGE_REPORT.json`: every input denominator, before/after field availability and remaining gaps.
- `metadata.sqlite3`, `REQUESTS.jsonl`, `responses/`: resumable metadata ledger and actual response/hash receipts. A completed batch does not mean every article has an abstract or every optional field is available.

Use the blind `model_inputs` view for new model runs. Keep retrieval coverage and source-assisted pool evaluation separate, and use the identity map only when scoring. Bibliographic enrichment does not create scientific gold labels or establish document/PDF identity; shared acquisition performs its own identity/version checks.
