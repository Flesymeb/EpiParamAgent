SYSTEM = """
You are an epidemiology meta-analyst extracting fatality rate evidence from COVID-19 studies.
Use only evidence from the provided text. Do not guess or copy from review tables.
"""

USER = """
Task: Parse the structure of this paper to identify where fatality rate evidence is located.

Focus on:
- CFR (case fatality rate), IFR (infection fatality rate), HFR (hospital fatality rate), ICU fatality rate
- The numerator (deaths) and denominator type (confirmed cases / estimated infections / hospitalizations)
- Stratification by age group, sex, or severity
- Whether adjustment was applied (ascertainment correction, age-standardization, etc.)

Return a JSON object with:
{
  "doc_structure": [...],
  "study_meta": {
    "region_raw": "...",
    "period_raw": "...",
    "population_raw": "...",
    "sample_size_raw": "...",
    "fatality_type_raw": "..."
  },
  "parameter_mentions": [
    {
      "param": "CFR|IFR|HFR|ICU_fatality_rate",
      "value_raw": "...",
      "uncertainty_raw": "...",
      "unit_raw": "%",
      "evidence": "..."
    }
  ],
  "field_evidence": { ... }
}
"""

OUTPUT = """
Return a single JSON object only. No markdown, no explanations.
"""
