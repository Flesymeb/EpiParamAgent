# Experimental Design: Validating LLMs for Epidemiological Systematic Review Automation

## Research Question

Can LLMs match human expert performance in large-scale epidemiological literature screening and effect-size data coding, and under what prompt strategies and model choices is performance maximized?

**Target venue**: PNAS (methodological validation study)  
**Status**: Pre-registration / experimental design phase

---

## 1. Experimental Factors

### 1.1 Screening Prompt Strategies (5 levels)

| Strategy | Description | Decision Logic | Guidance Level |
|----------|-------------|----------------|----------------|
| `5d` | Five-dimensional weighted scoring: disease (30%) + parameter (30%) + evidence (25%) + population (10%) + location (5%) | Weighted sum → threshold classification | Full (research question + disease/parameter focus + scoring rubric) |
| `peco` | PECO framework: Population, Exposure, Comparison, Outcome | Boolean AND (P ∧ E ∧ O → include; C optional) | Standard (PECO elements with definitions) |
| `binary` | Simple include/exclude with full research question | Binary decision | Full research question in system prompt |
| `binary_baseline` | Include/exclude with only disease + parameter names | Binary decision | Disease name + parameter name only |
| `binary_noguidance` | Include/exclude with zero task-specific guidance | Binary decision | None (LLM uses only general epidemiological knowledge) |

**Why PECO instead of PICO**: The parameters studied (R0, CFR, serial interval) are derived from observational studies where the pathogen is an *exposure*, not an *intervention*. PECO is the technically correct framework per Cochrane and WHO guidelines for etiological/observational research. We note in the paper that PECO is equivalent to what many researchers informally call "PICO for observational studies."

**Why test both 5D and PECO**: They represent fundamentally different decision architectures:
- 5D: Weighted-compensatory (low score on one dimension can be offset by another)
- PECO: Boolean-conjunctive (must satisfy ALL of P, E, O; failing any one → exclude)

This tests whether domain-tailored granularity (5D) outperforms the standard systematic review framework (PECO), which is the most theoretically interesting comparison in the design.

### 1.2 Coding Prompt Strategies (3 levels)

| Strategy | Description | Expected Trade-off |
|----------|-------------|-------------------|
| `indexed` | Stage A: Create structured document index → Stage B: Extract coding records using index as guide | Most robust for long documents; higher token cost |
| `direct` | Single-stage extraction directly from full-text without indexing | Fastest/cheapest; may miss data in long or complex papers |
| `peco_structured` | PECO framework-driven segmented extraction (extract P-relevant fields first, then E, then O) | May leverage structured reasoning; untested hypothesis |

### 1.3 Models (4 levels)

- GPT-4.1
- Claude Sonnet 4.6
- DeepSeek V4 Pro
- GLM-5.1

Selection rationale: Covers both Western and Chinese LLM ecosystems; includes both proprietary API and alternative providers; spans different architectural families.

### 1.4 Diseases and Parameters (Fixed)

| Disease | Serial Interval | Fatality Rate | Reproduction Number |
|---------|-----------------|---------------|---------------------|
| COVID-19 | ✓ | ✓ | ✓ |
| mpox | ✓ | ✓ | ✓ |

All parameters are continuous effect sizes. Binary outcomes (OR, RR, HR) are noted as a limitation and deferred to future work.

### 1.5 Stages

- **Stage 1 — Screening**: Title/abstract → Full-text screening
- **Stage 2 — Coding**: Effect-size data extraction from included full-text PDFs

---

## 2. Experimental Matrix

```
5 screening strategies × 3 coding strategies × 4 models × 2 diseases × 3 parameters × 2 stages
```

However, not all combinations are independent:
- Coding strategies are only tested on papers that pass screening
- The screening-coding pipeline is sequential (coding depends on screening output)
- Full factorial at screening stage: 5 strategies × 4 models × 2 diseases × 3 params = 120 screening experiments
- Full factorial at coding stage: 3 strategies × 4 models × 2 diseases × 3 params = 72 coding experiments
- **Total: up to 192 experiment runs** (each run processes a batch of papers)

### Practical Simplification

The `binary_noguidance` condition is primarily an ablation for screening (it makes less sense for coding, where the codebook defines the extraction schema). Similarly, `binary` and `binary_baseline` are screening-only strategies. Coding strategies are `indexed`, `direct`, and `peco_structured`.

---

## 3. Evaluation Metrics

### 3.1 Screening Stage

| Metric | Definition | Priority |
|--------|------------|----------|
| Sensitivity (Recall) | TP / (TP + FN) | Critical — must not miss relevant studies |
| Specificity | TN / (TN + FP) | Important — determines workload reduction |
| Precision (PPV) | TP / (TP + FP) | Important |
| F1 Score | Harmonic mean of precision and recall | Standard summary |
| **Cohen's κ** | Human-LLM agreement beyond chance | **Critical — primary metric** |
| NNS | Number Needed to Screen to find one relevant paper | Practical efficiency metric |
| MCC | Matthews Correlation Coefficient | Robust to class imbalance |
| ROC-AUC | Across decision thresholds | For threshold sensitivity analysis |

### 3.2 Coding Stage

| Metric | Definition | Priority |
|--------|------------|----------|
| **ICC (Intraclass Correlation)** | Human-LLM agreement on continuous effect sizes | **Critical — primary metric** |
| **Bland-Altman Analysis** | Mean difference ± limits of agreement; systematic bias visualization | **Critical** |
| **TOST Equivalence Test** | Two one-sided tests proving LLM-human difference < equivalence bound | **Critical for clinical validity claim** |
| Per-field Accuracy | Exact match / within-tolerance rate per codebook field | Important for error diagnosis |
| Pooled Estimate Comparison | LLM-pooled vs Human-pooled mean and CI overlap | Secondary |
| Coverage | % of human-extracted records found by LLM | Important |
| Hallucination Rate | % of LLM-extracted records with no corresponding human record (by field) | Critical |

### 3.3 Cost-Effectiveness

| Metric | Definition |
|--------|------------|
| Token Consumption | Prompt tokens + completion tokens per paper |
| Wall Time | Seconds per paper (screening and coding separately) |
| USD Cost | Based on API pricing per model |
| Time Saved vs Human | Human annotation time (estimated) − LLM processing time |
| Accuracy-Cost Ratio | κ or ICC per USD |
| Pareto Frontier | Optimal accuracy-efficiency trade-off configurations |

### 3.4 Statistical Analysis of Experiment Results

- **Factorial ANOVA**: Main effects and interactions of strategy × model × disease × parameter on κ/ICC
- **Post-hoc pairwise comparisons**: Which strategies/models differ significantly (with Bonferroni correction)
- **Sensitivity analysis**: Leave-one-disease-out, leave-one-parameter-out to assess robustness
- **Cascade error analysis**: How screening errors propagate to coding stage

---

## 4. Human Baseline (Ground Truth)

### 4.1 Human-Human Reliability Baseline (Deferred)

Single-annotator ground truth is a limitation at PNAS level. The core problem:

> Without human-human reliability data, an LLM-human κ of 0.85 is uninterpretable. If human-human κ is 0.80, then LLM is *better than* human agreement. If human-human κ is 0.95, then LLM has substantial room for improvement.

**Status: Deferred to future work.** Dual annotation requires a second independent expert annotator, which is not currently available.

**Mitigation strategies for the current paper:**
1. Acknowledge this explicitly as a limitation in the Discussion
2. Use published inter-rater reliability values from the systematic review methodology literature as a reference range (typically κ = 0.65–0.85 for title/abstract screening, ICC = 0.70–0.90 for data extraction)
3. Frame LLM performance relative to these published human benchmarks, while noting this is an indirect comparison
4. Argue that demonstrating LLM performance *within or above* the published human reliability range is informative even without a study-specific baseline

### 4.2 Ground Truth Pipeline

1. **MetaTagger**: Human annotator uploads systematic review PDF → manually extracts included study references
2. **Export**: Structured CSV/JSON with PMID, study metadata, inclusion status
3. **Dual annotation subset**: 20% of papers independently annotated by a second expert
4. **Adjudication**: Discrepancies resolved by third expert or consensus discussion (documented)

---

## 5. Hallucination Measurement

Define and measure three categories:

| Category | Definition | Detection Method |
|----------|------------|-----------------|
| **Fabrication** | LLM invents a value not present in source | Compare extracted value against source PDF (spot-check or automated) |
| **Misattribution** | Correct value, wrong study/PMID | Cross-reference with human GT at record level |
| **Hallucinated record** | Entire extracted record has no corresponding human GT record | Precision analysis (FP records are hallucinations) |

Report hallucination rate per model, per strategy, per field type.

---

## 6. Claims Matrix

| Claim | Strength | Required Evidence | Risk |
|-------|----------|-------------------|------|
| LLM screening achieves sensitivity >0.95 across all models | Strong | All model-strategy combinations show sensitivity ≥0.95 | One model-strategy combo failing weakens the claim |
| Prompt strategy significantly affects screening performance | Strong | ANOVA main effect of strategy, p<0.01 | If strategies don't differ, the contribution is diminished |
| PECO framework matches or exceeds 5D for LLM screening | Strong (surprising) | PECO κ ≥ 5D κ across models | Only true if PECO outperforms; if 5D > PECO, the claim is the reverse |
| LLM coding produces pooled estimates clinically equivalent to human | Moderate | TOST passes with clinically defined equivalence bounds | Equivalence bound must be pre-registered and justified |
| LLM cost-effectiveness justifies real-world deployment | Moderate | Clear Pareto frontier with acceptable accuracy loss at substantial cost savings | Requires careful framing — not "LLM replaces humans" but "LLM triages, humans verify" |
| LLMs can fully replace human screeners/coders | **DO NOT CLAIM** | N/A | Overclaiming; reviewers will reject |
| Results generalize beyond infectious diseases | **DO NOT CLAIM** | N/A | Only 2 infectious diseases tested |

---

## 7. Known Limitations (To Be Explicitly Acknowledged in Paper)

1. **Disease scope**: Only 2 infectious diseases (COVID-19, mpox); results may not generalize to non-communicable diseases
2. **Parameter types**: Only continuous effect sizes; binary/time-to-event outcomes (OR, RR, HR) not tested
3. **Language**: Only English-language literature; performance on Chinese, Spanish, etc. unknown
4. **Human-human baseline unavailable**: Only single-annotator ground truth; human-human reliability not directly measured. Mitigated by comparing against published inter-rater reliability benchmarks from the systematic review methodology literature.
5. **Single annotation for majority of GT**: Only subset is dual-annotated
6. **PDF quality dependency**: Coding extraction depends on MinerU parsing quality; poorly formatted PDFs may degrade performance
7. **Model version drift**: API models change over time; results are time-stamped snapshots

---

## 8. Recommended Analysis Pipeline

```
For each experiment run (strategy × model × disease × param × stage):
  1. Run LLM screening/coding
  2. Save: decisions CSV + token counts + wall time + cost
  3. Compute: all metrics vs GT

Aggregate analysis:
  4. Factorial ANOVA: κ ~ strategy + model + disease + param + strategy:model
  5. Post-hoc pairwise tests (Bonferroni-corrected)
  6. Bland-Altman plots for coding (per strategy × model)
  7. TOST equivalence tests (with pre-registered equivalence bounds)
  8. Cost-accuracy Pareto frontier
  9. Sensitivity: leave-one-disease-out, leave-one-parameter-out
  10. Cascade error: screening FN impact on coding recall
```

---

## 9. Pre-registration Items

Before running the full experiment:

- [ ] Register on OSF or AsPredicted
- [ ] Define and justify equivalence bounds for TOST
- [ ] Define primary vs secondary metrics (recommend: κ for screening, ICC for coding as co-primary)
- [ ] Define sample size (total papers per disease × parameter combination)
- [ ] Define stopping rules / exclusion criteria for individual papers
- [ ] Document model API versions and dates
- [ ] Commit all prompt templates to version control

---

## 10. Paper Outline (Target: PNAS)

**Title pattern**: "Large-language models achieve expert-level performance in epidemiological systematic review screening and data extraction"

### Sections

1. **Significance Statement** (PNAS requirement, 120 words max)
2. **Abstract**
3. **Introduction**
   - Systematic reviews are bottlenecked by manual screening and coding
   - LLMs show promise but lack rigorous validation in epidemiology
   - We present the first systematic multi-model, multi-strategy validation
4. **Results**
   - Screening performance (Table 1: κ, sensitivity, specificity per strategy × model)
   - Coding performance (Table 2: ICC, mean difference, TOST per strategy × model)
   - Cost-effectiveness (Table 3: cost-accuracy trade-off; Figure: Pareto frontier)
   - Strategy comparison (Figure: forest plot of κ differences between strategies)
   - Hallucination analysis (Table 4: hallucination rates by category)
5. **Discussion**
   - PECO vs 5D: domain-tailored frameworks [do/do not] outperform standard frameworks
   - Binary strategies are [surprisingly competitive / significantly worse]
   - Coding with indexing vs direct: the cost-accuracy trade-off
   - Model choice matters [more/less] than prompt strategy
   - Limitations and future work
6. **Methods**
   - Experimental design (factorial)
   - Ground truth construction (MetaTagger + dual annotation)
   - Prompt templates
   - Evaluation metrics
   - Statistical analysis plan
7. **Data and Code Availability** (PNAS requires)

### Key Figures

| Figure | Content |
|--------|---------|
| Fig 1 | PRISMA flow diagram (total retrieved → screened → included) |
| Fig 2 | Screening κ heatmap (strategies × models) |
| Fig 3 | Bland-Altman plots for coding (LLM vs Human per-study effect sizes) |
| Fig 4 | Cost-accuracy Pareto frontier (κ vs USD/paper, annotated by strategy+model) |
| Fig 5 | Hallucination rate breakdown by category and model |
| Fig S1-S4 | Per-disease, per-parameter subgroup analyses (supplementary) |
