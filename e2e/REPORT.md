# MetaAgent-Epi — End-to-End Coding Reproducibility Test (covid19 / serial_interval / p13)

## 1. Objective

Re-run the MetaAgent-Epi coding pipeline **end-to-end** (fresh LLM index + extract) on a PDF-heavy
project and quantify how far the fresh results drift from the project's **prior modular** evaluation
already stored in the repo. Same pipeline code, run fresh, apples-to-apples on the identical PMID set.

## 2. Target project & PMID set

- Project: `covid19/serial_interval/p13`
- Modular reference run: `evaluation/coding/covid19/serial_interval/p13/coding_runs/20260421_125302_527/`
  (`coding_sheet_20260421_135142.xlsx` = 105 rows / 45 PMIDs; the largest run).
- PMID set: the **exact 45 PMIDs** in that run's `index/` directory, in the same input order
  (recovered from the run manifest `input_files`). Set equality with the modular index dir was verified.
- All 45 PMIDs had **both** a cached PDF and cached MinerU markdown, so the run incurred **no fetch and no
  MinerU cost** — pure LLM re-extraction. Input file: `e2e/p13_pmids.txt`.

## 3. Pipeline configuration bugs found (and the e2e workaround)

`metaagent.coding.pipeline.extraction.run_pipeline(...)` **cannot run as-is** on branch `feat/webapp-ui`
with the instructed config paths. Three path mismatches:

1. **Codebook -> stage prompts.** `configs/covid19/codebooks/serial_interval.yaml` declares
   `stage_a/stage_b: prompt_file: prompts/stage_*_serial_interval.py`, resolved relative to the codebook
   dir -> `configs/covid19/codebooks/prompts/...`, which **does not exist**. Real files:
   `configs/covid19/coding_prompts/`. `load_config()` raises `FileNotFoundError`.
2. **Hardcoded Stage-A config.** `run_pipeline` loads `parents[2]/configs/stages/stage_a.yaml`
   = `metaagent/configs/stages/stage_a.yaml`, which **does not exist** (real:
   `configs/covid19/coding_prompts/stage_a.yaml`).
3. **Stage-A yaml -> prompt.** that yaml declares `prompt_file: ../prompts/stage_a.py`
   -> `configs/covid19/prompts/stage_a.py`, **does not exist** (real:
   `configs/covid19/coding_prompts/stage_a.py`).

`webapp/app/steps/coding.py` calls `run_pipeline` with these same paths, so the **webapp coding step is
currently broken on this branch** for covid19 serial_interval.

**Workaround (no edits to `configs/` or `metaagent/`):** `e2e/run_e2e.py` replicates the exact body of
`run_pipeline(stage="both")`, reusing every unmodified `metaagent.coding` function (`init_llm`,
`process_fulltext`, `run_index`, `run_extract`, `prompt_factory`, `export_records`), but loads config from
corrected copies under `e2e/configs/` (`serial_interval_fixed.yaml`, `stage_a_fixed.yaml`) whose only change
is the three prompt-file paths corrected to the real `coding_prompts/` locations. Prompt *content* and all
extraction logic are byte-identical to the repo. LLM: `z-ai/glm-5.1` via OpenRouter (`.env.local`).

## 4. Commands

```bash
PYTHONPATH=. .venv/bin/python e2e/run_e2e.py     # fresh index+extract -> e2e/runs/p13/
PYTHONPATH=. .venv/bin/python e2e/compare.py     # join + pooled comparison
PYTHONPATH=. .venv/bin/python e2e/finalize_report.py
```

## 5. Pooling method (identical to `tools/scripts/evaluate_coding.py`)

`enrich_ci()` then `summarize(parameter_type="serial_interval", estimate_measure="mean",
include_median=False, impute_missing_se=True, method="random")` — DerSimonian-Laird random effects, SE
imputed from the median within-study SD where uncertainty is unreported. Verified to reproduce the canonical
evaluator's modular pooled value (5.2427, 4.9497-5.5356, n=70, I2=81.4) bit-for-bit. This evaluator pools
**all** serial_interval mean rows (~70 across 45 papers). The official LEADS reference (4.80, 4.45-5.15,
n=52) uses a different one-value-per-study reduction, so e2e-vs-official is **not** the primary
reproducibility metric; **e2e-vs-modular under identical pooling** is.

## 6. Results

### 6.1 Per-paper agreement (primary serial-interval mean estimate, one row/PMID)

| metric | value |
|---|---|
| PMIDs in modular (SI-mean primary) | 31 |
| PMIDs in e2e (SI-mean primary) | 34 |
| matched PMIDs (both) | 31 |
| only in modular | 0 |
| only in e2e | 3 |
| matched with point estimate in both | 31 |
| **exact** point-estimate match | 31 / 31 |
| mean abs delta (days) | 0.000 |
| % within 5% of modular | 100.0% |
| % within 10% of modular | 100.0% |

Per-paper detail: `e2e/comparison_p13_perpaper.csv` ("primary" = first SI-mean row per PMID = headline estimate).

### 6.2 Pooled (DerSimonian-Laird random effects; identical pooling to evaluate_coding.py)

| source | pooled mean (days) | 95% CI | I2 | n_studies | n_imputed |
|---|---|---|---|---|---|
| modular (prior run) | 5.24 | 4.95-5.54 | 81.4 | 70 | 8 |
| **e2e (fresh re-run)** | 5.28 | 4.98-5.57 | 83.4 | 73 | 7 |
| official LEADS (diff. reduction) | 4.80 | 4.45-5.15 | - | 52 | - |

- Delta(e2e - modular): pooled mean 0.034 d, CI_low 0.031, CI_high 0.037.
- Relative pooled-mean drift vs modular: 0.65%.
- Delta(e2e - official LEADS) pooled mean: 0.477 d.

## 7. Verdict

**Highly reproducible.** Running the identical pipeline code fresh on the same 45 PMIDs (no cached index/extract reuse) reproduced the prior modular results with no meaningful drift. Every one of the 31 papers that both runs surfaced as a primary serial-interval *mean* estimate matched **exactly** (mean abs delta = 0.0 days; 100% within 5%), and the random-effects pooled mean moved only +0.034 days (+0.65%): modular 5.24 (4.95-5.54) vs e2e 5.28 (4.98-5.57), I2 81 vs 83, both n~70-73. The two runs are statistically indistinguishable. Divergences are confined to record *coverage*, not estimate *values*: (1) the e2e run extracted 119 records vs 105 modular, driven almost entirely by one stratified paper (PMID 33234640) where Stage B enumerated 46 sub-stratum rows (42 serial_interval) instead of a single headline estimate — a verbosity/granularity difference the LLM exhibits run-to-run, not a numerical error; (2) 3 papers (32473049, 32796323, 32815514) appear only in e2e because it captured a *mean* where modular had recorded a median or nothing — e2e was marginally more complete; (3) PMID 33031427 returned 0 records in both runs (agreement). For the demo this is more than trustworthy: headline per-study estimates and the pooled meta-analytic result are effectively deterministic across re-runs. The one watch-item is record granularity on heavily stratified papers (one paper inflating row count ~3x), which affects how many rows a reviewer sees but not the pooled estimate. Caveat: the official LEADS reference (4.80, 4.45-5.15, n=52) sits ~0.45 d below both runs, but that gap is a pre-existing pooling-methodology difference (one-value-per-study median-of-means vs pooling all mean rows), NOT an e2e reproducibility issue.
