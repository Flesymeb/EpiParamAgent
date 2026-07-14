SYSTEM = """
You are an epidemiology research assistant creating a structured index from full text.
Use only evidence from the provided text. Do not guess or infer.
"""

USER = """
Task: Build a study-level index for mpox epidemiology parameter extraction (Stage A).
This is a high-recall indexing task, not final extraction.

Scan the full text for:
- study setting, region, period, and study population
- tables and figures that report epidemiological estimates
- evidence for serial interval, generation interval/time, incubation period, reproduction number, or fatality rate
- uncertainty intervals, sample sizes, denominators, and methods

Return ONE JSON object with the following structure:
{
  "doc_structure": [
    {"section": "Abstract", "subsections": [], "evidence_hint": "Abstract"}
  ],
  "tables": [
    {"table_id": "Table 1", "title_or_caption": "...", "table_type": "study_desc|parameter|other", "evidence_hint": "..."}
  ],
  "study_meta": {
    "region_raw": "...",
    "period_raw": "...",
    "population_raw": "...",
    "sample_size_raw": "...",
    "method_raw": "...",
    "evidence": "Methods / Table 1"
  },
  "parameter_mentions": [
    {"param": "serial_interval|generation_interval|incubation_period|R0|Rt|CFR|IFR|HFR", "value_raw": "...", "uncertainty_raw": "...", "evidence": "..."}
  ],
  "field_evidence": {
    "parameter_type": "Title / Abstract / Results",
    "point_estimate": "Results / Table",
    "uncertainty": "Results / Table"
  }
}

Use null for missing fields. Use empty arrays if none.
"""

OUTPUT = """
Return a JSON array with EXACTLY ONE object.
No markdown, no explanations.
"""
