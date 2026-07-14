# Screening Related Work and Baseline Choice

Date: 2026-06-18

## Scope

This note covers first-pass title/abstract screening only. It does not evaluate
full-text screening, OCR, extraction, report generation, or source-review-level
meta-analytic estimate agreement.

## Selected Baselines

### LEADS-Minimal

LEADS-Mistral is a direct model baseline because it is a fine-tuned systematic
review literature-mining model. Its model card describes support for search
query generation, study eligibility prediction, and structured extraction from
biomedical literature.

Repository implementation:

- `baselines/screening/leads_minimal/`
- Canonical frozen outputs: `evaluation/leads_mistral_freeze_leads_minimal_summary.csv`

Reporting label:

- `LEADS-Minimal`

Why this prompt is acceptable:

- It gives only disease and parameter labels.
- It uses title/abstract only.
- It does not expose MetaAgent's five dimensions or source-review-specific
  inclusion logic.

Source:

- https://huggingface.co/zifeng-ai/leads-mistral-7b-v1

### AgentSLR-Style ScreenPrompt Lite

AgentSLR is important related work because it is an open-source epidemiological
SLR harness covering retrieval, title/abstract screening, OCR, full-text
screening, extraction, and report generation. Its official benchmark uses WHO
priority pathogens and PERG labels, so official AgentSLR metrics are not directly
comparable to this COVID-19/mpox source-review benchmark.

The implemented baseline is therefore an adaptation of its abstract-screening
style, not an official AgentSLR reproduction. The prompt is intentionally
shorter than the AgentSLR prompt template and omits the broad multi-parameter
criteria and step-by-step reasoning instructions.

Repository implementation:

- `baselines/screening/agent_slr_screenprompt_lite/`
- Runner prompt style: `screenprompt_lite`

Reporting label:

- `AgentSLR-style ScreenPrompt Lite`

Source:

- https://github.com/OxRML/AgentSLR
- https://oxrml.com/agent-slr/

### Keyword Rules

Keyword rules are retained as a non-LLM retrieval-style baseline. They are useful
because they are deterministic, cheap, and easy to audit, while setting a lower
bound for disease-plus-parameter lexical matching.

Repository implementation:

- `baselines/screening/keyword_rules/`
- Canonical rule source: `tools/scripts/rule_based_screening_baselines.py`

Reporting label:

- `Keyword disease+parameter rule`

## Not Implemented as Primary Screening Baselines

### Generic GPT/LLM Title-Abstract Screening

Several recent studies evaluate GPT-style APIs or general LLM prompts for
title/abstract screening in clinical or biomedical systematic reviews. These are
important background because they show that prompt-only screening is feasible,
but they are not added as another primary baseline here for two reasons: the
paper-facing model table already includes general LLMs such as GPT-4.1, and the
implemented LEADS-Minimal plus AgentSLR-style ScreenPrompt Lite baselines already
cover simple prompt-only include/exclude screening on our benchmark.

Sources:

- Guo et al., 2024, *Automated Paper Screening for Clinical Reviews Using Large Language Models: Data Analysis Study*, JMIR. https://www.jmir.org/2024/1/e48996/
- Dennstadt et al., 2024, *Title and abstract screening for literature reviews using large language models: an exploratory study in the biomedical domain*, Systematic Reviews. https://pubmed.ncbi.nlm.nih.gov/38879534/

### ASReview

ASReview is highly relevant as open-source active-learning software for
systematic-review screening. It is not a direct zero-shot baseline for this first
pass because its core workflow is reviewer-in-the-loop prioritization: users
provide labels, the model ranks records, and performance depends on a stopping
criterion. That is a different operating setting from classifying every raw-pool
record from title/abstract metadata alone.

Source:

- https://www.nature.com/articles/s42256-020-00287-7
- https://asreview.readthedocs.io/en/stable/lab/about.html

### Full AgentSLR Official Reproduction

A full official AgentSLR reproduction is not recommended for the main screening
table because its pathogens, labels, and metrics differ from this benchmark.
Use it as related work and, if needed, run only the ScreenPrompt Lite adaptation
on our frozen profiles.

## Suggested Reporting

Main screening comparison:

1. MetaAgent 5D screening.
2. LEADS-Minimal.
3. Keyword disease+parameter rule.

Optional appendix/sensitivity:

1. AgentSLR-style ScreenPrompt Lite.
2. Stricter LEADS prompt variants from `tools/scripts/leads_mistral_screening_eval.py`.
