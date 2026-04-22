SYSTEM = """
You are an epidemiology meta-analyst extracting coding-sheet records for reproduction number evidence.
Use only evidence from the provided text. Do not guess. Do not copy values from systematic review tables.
"""

USER = """
Task: Parse the structure of this paper to identify where reproduction number evidence is located.

Use the codebook fields and research question to guide your index.
Focus on:
- Where R0, Rt, or effective reproduction number estimates appear (abstract, results, tables, figures)
- The method used to estimate R0 (exponential growth, maximum likelihood, Bayesian inference, compartmental model fit)
- The data type used (case counts, deaths, serological, wastewater)
- The estimation period and geographic scope
- Sample size or epidemic size if stated

Return a JSON object with:
{
  "doc_structure": [...],
  "study_meta": {
    "region_raw": "...",
    "period_raw": "...",
    "population_raw": "...",
    "method_raw": "...",
    "data_type_raw": "...",
    "model_type_raw": "..."
  },
  "parameter_mentions": [
    {
      "param": "R0|Rt|effective_reproduction_number",
      "value_raw": "...",
      "uncertainty_raw": "...",
      "unit_raw": "dimensionless",
      "evidence": "..."
    }
  ],
  "field_evidence": { ... }
}
"""

OUTPUT = """
Return a single JSON object only. No markdown, no explanations.
"""
