SYSTEM = """
You are an epidemiology meta-analyst indexing a primary COVID-19 paper to guide fatality rate extraction.
Use only evidence from the provided text. Do not guess.
"""

USER = """
Task: Parse the structure of this paper to identify where fatality rate evidence is located.

Focus specifically on:
1. Case fatality rate (CFR) = deaths / confirmed cases × 100%
2. Infection fatality rate (IFR) = deaths / estimated infections × 100%
3. Hospital fatality rate (HFR) = deaths among hospitalized / hospitalized × 100%
4. ICU fatality rate = deaths in ICU / ICU admissions × 100%

These may appear as:
- Explicit labels: "CFR", "IFR", "fatality rate", "mortality rate", "case fatality ratio"
- Tables with "deaths", "mortality", "fatal" columns
- Statements like "X% of patients died", "mortality was X%", "X out of Y died"
- Stratified by age, sex, severity, region

Also capture:
- The denominator type: confirmed cases, estimated infections, hospitalized, etc.
- Whether adjustment was applied (e.g., ascertainment correction, age standardization)
- Sample size (number of cases or infections)

Return a JSON object:
{
  "doc_structure": [{"section": "...", "evidence_hint": "..."}],
  "study_meta": {
    "region_raw": "country/region as stated",
    "period_raw": "study period",
    "population_raw": "population studied",
    "sample_size_raw": "number of cases/infections/deaths",
    "fatality_type_raw": "CFR|IFR|HFR|ICU fatality|mortality rate"
  },
  "parameter_mentions": [
    {
      "param": "CFR|IFR|HFR|ICU_fatality_rate",
      "value_raw": "e.g. '2.3%' or '0.023'",
      "numerator_raw": "number of deaths if stated",
      "denominator_raw": "number of cases/infections if stated",
      "uncertainty_raw": "CI/SE if stated",
      "evidence": "section/table reference"
    }
  ],
  "field_evidence": {
    "fatality_type": "where fatality type is defined",
    "point_estimate": "where the main % value appears",
    "denominator_type": "what the denominator represents"
  }
}
"""

OUTPUT = """
Return a single JSON object only. No markdown, no explanations.
"""
