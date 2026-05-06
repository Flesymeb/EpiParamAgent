# Analysis prompt for another machine

You are analyzing a strict/simple LEADS-Mistral screening baseline for epidemiology literature review tasks.

Experiment ID: `leads_mistral_strict_simple_20260506_185524`

Input files:
- `evaluation/experiments/leads_mistral_strict_simple_20260506_185524/screening/combined_summary.csv`
- `evaluation/experiments/leads_mistral_strict_simple_20260506_185524/screening/covid19/summary.csv`
- `evaluation/experiments/leads_mistral_strict_simple_20260506_185524/screening/mpox/summary.csv`
- Optional per-profile details live under:
  - `evaluation/covid19/*/ground_truth/p*/experiments/leads_mistral_strict_simple_20260506_185524/`
  - `evaluation/mpox/*/ground_truth/p*/experiments/leads_mistral_strict_simple_20260506_185524/`

Context:
- Model: `zifeng-ai/leads-mistral-7b-v1` served by vLLM.
- Prompt intentionally simple and strict: include only if title/abstract clearly looks directly useful; exclude vague/off-topic/review/editorial/protocol/mention-only citations.
- This is a baseline run, not the main optimized MetaAgent screening workflow.

Please produce a concise analysis with:
1. Overall performance by disease (macro average across profiles; optionally micro aggregate from TP/FP/FN/TN).
2. A ranked table of profiles by recall, precision, F1, and workload reduction.
3. Identify profiles with high recall but very low precision, and profiles with possible recall failures.
4. Compare COVID-19 vs mpox behavior and discuss likely reasons from task/topic composition.
5. Give 3-5 actionable next steps for improving the prompt or thresholding while keeping the prompt simple.

Use the metric definitions already in the CSV. Treat `strong_candidate` and `possible_candidate` as predicted relevant. Keep the write-up factual and short.
