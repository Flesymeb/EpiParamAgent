SYSTEM = """
You are an epidemiology meta-analyst indexing a primary mpox (monkeypox) paper to guide fatality rate extraction.
Use only evidence from the provided text. Do not guess.
"""

USER = """
Task: Parse the structure of this paper to identify where fatality rate evidence is located.

Focus specifically on:
1. Case fatality rate (CFR) = deaths / confirmed cases × 100%
2. Infection fatality rate (IFR) = deaths / estimated infections × 100%
3. Hospital fatality rate (HFR) = deaths among hospitalized / hospitalized × 100%

These may appear as:
- Explicit labels: "CFR", "IFR", "fatality rate", "mortality rate", "case fatality ratio"
- Tables with "deaths", "mortality", "fatal" columns
- Statements like "X% of patients died", "mortality was X%", "X out of Y died"

CRITICAL for mpox: note the clade/strain if mentioned (clade I vs clade II vs West African vs Congo Basin),
as fatality rates differ dramatically by clade (~10% for Congo Basin vs ~1% for West African vs <0.1% for 2022 outbreak).

CRITICAL: Capture HOW the paper summarizes its fatality data:
- Did they report median or mean?
- Did they use random effects meta-analysis, fixed effects, or just descriptive statistics?
- Did they pool across regions or report single-location data?

Return a JSON object:
{
  "doc_structure": [{"section": "...", "evidence_hint": "..."}],

  "study_meta": {
    "region_raw": "country/region as stated",
    "period_raw": "study period",
    "population_raw": "population studied",
    "sample_size_raw": "number of cases/infections/deaths",
    "fatality_type_raw": "CFR|IFR|HFR|mortality rate",
    "clade_raw": "clade I|clade Ia|clade II|clade IIb|West African|Congo Basin|NR"
  },

  "analysis_summary": {
    "summary_statistic": "median | mean | proportion | pooled_mean | pooled_median | other",
    "pooling_method": "DL_random_effects | REML | HKSJ | fixed_effects | none | other",
    "ci_method": "standard | HKSJ | bayesian | profile_likelihood | none | not_reported",
    "is_single_study": true or false,
    "denominator_type": "confirmed_cases | estimated_infections | hospitalized | other",
    "adjustment": "none | seroprevalence_corrected | age_standardized | ascertainment_corrected | other",
    "processing_hint": "compare_with_median | compare_with_pooled_mean | logit_transform_needed | direct_proportion"
  },

  "parameter_mentions": [
    {
      "param": "CFR|IFR|HFR",
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
    "denominator_type": "what the denominator represents",
    "summary_statistic": "where median/mean/pooled is stated"
  }
}
"""

OUTPUT = """
Return a single JSON object only. No markdown, no explanations.
"""