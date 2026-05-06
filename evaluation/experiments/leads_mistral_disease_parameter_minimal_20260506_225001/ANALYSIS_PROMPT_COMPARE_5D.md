# Prompt for comparing LEADS-Mistral minimal screening vs MetaAgent 5D

You are analyzing screening performance for epidemiology systematic-review tasks. Compare two methods on the same COVID-19 and mpox title/abstract screening tasks.

## Methods

Method A: `LEADS-Mistral disease_parameter_minimal`
- Model: `zifeng-ai/leads-mistral-7b-v1`, served by vLLM.
- Experiment: `leads_mistral_disease_parameter_minimal_20260506_225001`.
- Prompt intentionally minimal; it only gives disease + parameter labels and the title/abstract:

```text
I am screening papers for a systematic review about {disease} and {parameter}.
Based on the title and abstract, decide include or exclude.

Title: {title}
Abstract: {abstract}

Return JSON only: {"include": true/false, "reason": "short"}
```

Method B: `MetaAgent 5D screening`
- Use the user's 5D method outputs for the matching COVID-19 and mpox profiles.
- If multiple 5D runs exist, use the latest full non-smoke run on the same raw/ground-truth CSVs.

## Files for Method A

Use these files in this repository:

- Combined per-profile summary: `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/screening/combined_summary.csv`
- COVID-19 summary: `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/screening/covid19/summary.csv`
- mpox summary: `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/screening/mpox/summary.csv`
- Run configs:
  - `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/screening/covid19/run_config.json`
  - `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/screening/mpox/run_config.json`

Optional reference only, not the main comparator:

- LEADS strict-simple vs minimal comparison: `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/screening/comparison_strict_simple_vs_disease_parameter_minimal.csv`
- Short strict-simple comparison note: `evaluation/experiments/leads_mistral_disease_parameter_minimal_20260506_225001/COMPARISON_WITH_STRICT_SIMPLE.md`

## Files for Method B

Please locate or receive the matching MetaAgent 5D outputs. Expected input can be one of:

- A combined summary CSV with one row per profile, containing at least `disease`, `profile`, `topic`, `tp`, `fp`, `fn`, `tn`, `recall`, `precision`, `f1`, and `workload_reduction`; or
- Separate COVID-19 and mpox summary CSVs with the same fields.

If the 5D summary lacks `disease`, infer it from the file path or profile prefix (`P*` = COVID-19, `MP*` = mpox). If it lacks metrics but has counts, recompute metrics from TP/FP/FN/TN.

## Matching tasks

Compare only matching profiles:

- COVID-19: `P4`, `P5`, `P6`, `P7`, `P8`, `P10`, `P11`, `P12`, `P13`, `P14`, `P15`, `P16`, `P17`
- mpox: `MP4`, `MP5`, `MP6`, `MP7`, `MP8`, `MP9`, `MP10`, `MP11`, `MP12`

Parameter groups:

- `fatality`
- `reproduction_number`
- `serial_interval`

Before comparing, verify that Method A and Method B have matching `screened_count` and `ground_truth_count` per profile. If any profile differs, flag it and either exclude it from paired comparison or analyze it separately.

## Required analysis

Produce a concise Chinese report with the following sections:

1. `数据和可比性检查`
   - List the Method A and Method B files used.
   - Confirm matched profiles and note any missing/mismatched profiles.
   - State whether raw counts and ground-truth counts match.

2. `总体性能`
   - Report micro-average metrics for COVID-19, mpox, and overall: recall, precision, F1, specificity, workload reduction, TP/FP/FN/TN, predicted include count.
   - Report macro-average metrics across profiles for COVID-19, mpox, and overall.
   - Include delta as `LEADS minimal - 5D`.

3. `按任务类型分析`
   - Aggregate by `disease + topic` and by topic overall.
   - Compare fatality, reproduction number, and serial interval.
   - Identify where 5D is strongest and where the minimal LEADS prompt is competitive or fails.

4. `逐 profile 排名和失败模式`
   - Provide a compact table for each profile: Method A recall/precision/F1/WR, Method B recall/precision/F1/WR, and deltas.
   - Highlight profiles where LEADS minimal has much lower recall than 5D, much lower precision than 5D, or unusually high false positives.

5. `置信区间和显著性`
   - Compute Wilson 95% CI for recall, precision, and specificity from TP/FP/FN/TN.
   - For F1, either bootstrap if per-paper predictions are available, or clearly state that only point estimates are shown from summary counts.
   - If per-paper predictions from both methods are available for the same PMID rows, run paired error analysis: McNemar test for include/exclude decisions and paired comparison of false negatives/false positives. If only summary counts are available, do not claim paired significance.

6. `结论`
   - Answer directly: does MetaAgent 5D outperform the minimal LEADS-Mistral prompt?
   - Separate conclusions for recall, precision, F1, workload reduction, COVID-19 vs mpox, and each topic.
   - Interpret whether the minimal LEADS prompt is a fair weak baseline: it should not look intentionally sabotaged, but it lacks 5D disease/population/location/evidence/parameter criteria.

## Metric definitions

Use these definitions consistently:

- `recall = TP / (TP + FN)`
- `precision = TP / (TP + FP)`
- `specificity = TN / (TN + FP)`
- `F1 = 2 * precision * recall / (precision + recall)`
- `workload_reduction = (TN + FN) / screened_count`
- `predicted_include = TP + FP`

Treat `strong_candidate` and `possible_candidate` as predicted include for Method A. Use the 5D method's own binary include/relevant definition for Method B.

Keep the report factual and concise. Do not over-interpret small differences when confidence intervals overlap or when only summary-level counts are available.
