"""Generate e2e/REPORT.md from comparison_p13_summary.json (self-contained).

Kept as a Python script so the required e2e/REPORT.md deliverable can be produced
(the methodology text is embedded below). Run AFTER e2e/compare.py.
Verdict text is passed via --verdict or defaults to an auto-generated line.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

METHODOLOGY = r"""# MetaAgent-Epi — End-to-End Coding Reproducibility Test (covid19 / serial_interval / p13)

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

"""


def f(x, n=2):
    try:
        return f"{float(x):.{n}f}"
    except Exception:
        return str(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdict", default="(verdict in e2e/comparison_p13_summary.json)")
    args = ap.parse_args()
    S = json.loads((ROOT / "e2e/comparison_p13_summary.json").read_text())
    pm, pe, po = S["pooled_modular"], S["pooled_e2e"], S["pooled_official_leads"]
    dmod = S["pooled_delta_e2e_vs_modular"]

    results = f"""## 6. Results

### 6.1 Per-paper agreement (primary serial-interval mean estimate, one row/PMID)

| metric | value |
|---|---|
| PMIDs in modular (SI-mean primary) | {S['n_modular_pmids']} |
| PMIDs in e2e (SI-mean primary) | {S['n_e2e_pmids']} |
| matched PMIDs (both) | {S['n_matched_pmids']} |
| only in modular | {S['n_only_modular']} |
| only in e2e | {S['n_only_e2e']} |
| matched with point estimate in both | {S['n_matched_both_pt']} |
| **exact** point-estimate match | {S['n_exact_match_pt']} / {S['n_matched_both_pt']} |
| mean abs delta (days) | {f(S['mean_abs_delta_days'],3)} |
| % within 5% of modular | {f(S['pct_within_5pct'],1)}% |
| % within 10% of modular | {f(S['pct_within_10pct'],1)}% |

Per-paper detail: `e2e/comparison_p13_perpaper.csv` ("primary" = first SI-mean row per PMID = headline estimate).

### 6.2 Pooled (DerSimonian-Laird random effects; identical pooling to evaluate_coding.py)

| source | pooled mean (days) | 95% CI | I2 | n_studies | n_imputed |
|---|---|---|---|---|---|
| modular (prior run) | {f(pm['pooled_mean'])} | {f(pm['ci_lower'])}-{f(pm['ci_upper'])} | {f(pm['i2'],1)} | {int(pm['n_studies'])} | {int(pm['n_imputed'])} |
| **e2e (fresh re-run)** | {f(pe['pooled_mean'])} | {f(pe['ci_lower'])}-{f(pe['ci_upper'])} | {f(pe['i2'],1)} | {int(pe['n_studies'])} | {int(pe['n_imputed'])} |
| official LEADS (diff. reduction) | {f(po['pooled_mean'])} | {f(po['ci_lower'])}-{f(po['ci_upper'])} | - | {int(po['n_studies'])} | - |

- Delta(e2e - modular): pooled mean {f(dmod['pooled_mean'],3)} d, CI_low {f(dmod['ci_lower'],3)}, CI_high {f(dmod['ci_upper'],3)}.
- Relative pooled-mean drift vs modular: {f(100*abs(dmod['pooled_mean'])/pm['pooled_mean'],2)}%.
- Delta(e2e - official LEADS) pooled mean: {f(S['pooled_delta_e2e_vs_official']['pooled_mean'],3)} d.
"""

    verdict = f"## 7. Verdict\n\n{args.verdict}\n"
    (ROOT / "e2e/REPORT.md").write_text(METHODOLOGY + results + "\n" + verdict, encoding="utf-8")
    print("wrote e2e/REPORT.md")


if __name__ == "__main__":
    main()
