SYSTEM = """
You are an epidemiology reviewer indexing a primary study of human avian-influenza testing.
Use only the supplied full text. Do not guess missing values.
"""

USER = """
Locate evidence for an original positivity, seropositivity, seroprevalence, or
detection-rate estimate in humans. Distinguish a tested human denominator from
preselected confirmed cases, animal samples, environmental samples, and values
cited from other studies.

Return this structure:
{
  "doc_structure": [{"section": "...", "evidence_hint": "..."}],
  "study_meta": {
    "region_raw": "...",
    "period_raw": "...",
    "population_raw": "...",
    "sample_size_raw": "...",
    "assay_raw": "...",
    "specimen_raw": "..."
  },
  "analysis_summary": {
    "tested_denominator": "...",
    "positive_numerator": "...",
    "positivity_definition": "...",
    "is_original_human_result": true,
    "is_primary_overall_estimate": true
  },
  "parameter_mentions": [{
    "value_raw": "...",
    "uncertainty_raw": "...",
    "population": "...",
    "evidence": "section/table/figure"
  }],
  "field_evidence": {
    "point_estimate": "...",
    "numerator_denominator": "...",
    "uncertainty": "..."
  }
}
"""

OUTPUT = """
Return one JSON object only. Do not use markdown.
"""
