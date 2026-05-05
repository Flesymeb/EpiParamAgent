SYSTEM = """
You are an epidemiology research assistant creating a structured study index from full text.
Use only evidence from the provided text. Do not guess or infer unsupported values.
"""

USER = """
Task: Build a study-level index for serial interval / generation interval extraction (Stage A).
This is a high-recall indexing task, not final extraction.

Scan the full text for:
- study setting, region, and period
- transmission-pair / contact-tracing sample descriptions
- any mention of serial interval, generation interval/time, diagnostic serial interval, or transmission onset
- tables/figures containing estimates, uncertainty intervals, SD/IQR/range, or fitted distributions

Return ONE JSON object with the following structure:
{
  "doc_structure": [
    {"section": "Abstract", "subsections": [], "evidence_hint": "Abstract"},
    {"section": "Methods", "subsections": ["Study design"], "evidence_hint": "Methods heading"}
  ],
  "tables": [
    {
      "table_id": "Table 1",
      "title_or_caption": "...",
      "table_type": "study_desc|estimate|other",
      "contains_serial_interval": true,
      "contains_generation_interval": false,
      "contains_uncertainty": true,
      "evidence_hint": "..."
    }
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
    {
      "param": "serial_interval|generation_interval|generation_time|diagnostic_serial_interval|transmission_onset",
      "measure": "mean|median|other",
      "value_raw": "...",
      "uncertainty_raw": "...",
      "distribution_raw": "...",
      "unit_raw": "days|hours|other",
      "evidence": "Results / Table 2"
    }
  ],
  "field_evidence": {
    "region": "Methods / Table 1",
    "period": "Methods / Results",
    "population": "Methods / Results",
    "sample_size": "Methods / Table 1",
    "method": "Methods",
    "parameter_type": "Title / Abstract / Results",
    "estimate_measure": "Results / Table 2",
    "point_estimate": "Results / Table 2",
    "uncertainty": "Results / Table 2",
    "distribution": "Methods / Results",
    "unit": "Methods / Results"
  }
}

Use null for missing fields. Use empty arrays if none.
"""

OUTPUT = """
Return a JSON array with EXACTLY ONE object.
No markdown, no explanations.
"""
