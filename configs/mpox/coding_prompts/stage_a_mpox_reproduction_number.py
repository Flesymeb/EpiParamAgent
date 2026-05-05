SYSTEM = """
You are an epidemiology meta-analyst indexing a primary mpox (monkeypox) paper to guide reproduction number extraction.
Use only evidence from the provided text. Do not guess.
"""

USER = """
Task: Parse the structure of this paper to identify where reproduction number evidence is located.

Focus specifically on:
1. Basic reproduction number (R0) — transmission potential in naive population
2. Effective/time-varying reproduction number (Rt) — under control measures
3. Net reproduction number — context-dependent

These may appear as:
- Explicit labels: "R0", "Rt", "reproduction number", "reproductive number", "R naught"
- Estimates like "R0 = 1.5", "Rt declined to 0.8"
- Model outputs with confidence/credible intervals

CRITICAL for mpox: note the outbreak context (2022 global outbreak vs endemic in Africa),
as R0/Rt values differ substantially between settings and clades.

Return a JSON object:
{
  "doc_structure": [{"section": "...", "evidence_hint": "..."}],

  "study_meta": {
    "region_raw": "country/region as stated",
    "period_raw": "study period",
    "population_raw": "population studied",
    "sample_size_raw": "number of cases",
    "method_raw": "estimation method as stated",
    "data_type_raw": "case_counts|deaths|hospitalizations|other"
  },

  "method_index": {
    "method_category": "exponential_growth | maximum_likelihood | bayesian | seir_fit | branching_process | next_generation_matrix | other",
    "ci_derivation": "mcmc_posterior | bootstrap | profile_likelihood | analytical | delta_method | simulation | not_reported",
    "generation_interval_assumed": "SI/GI value used as input if stated",
    "is_pre_intervention": true or false,
    "data_weeks": "number of weeks of epidemic data used",
    "transformation": "log | log10 | none | other",
    "processing_hint": "standard_ci | treat_cri_as_ci | log_normal_se | wide_ci_flag | no_interval",
    "method_notes": "free-text methodological notes"
  },

  "analysis_summary": {
    "summary_statistic": "mean | median | pooled_mean | other",
    "pooling_method": "DL | REML | HKSJ | fixed | none | other",
    "is_single_study": true or false
  },

  "parameter_mentions": [
    {
      "param": "R0|Rt|net_reproduction_number",
      "value_raw": "e.g. '1.5' or 'R0=2.3'",
      "uncertainty_raw": "CI/SE if stated",
      "evidence": "section/table reference"
    }
  ],

  "field_evidence": {
    "parameter_type": "where R0/Rt type is defined",
    "point_estimate": "where the main value appears",
    "method": "where estimation method is described"
  }
}
"""

OUTPUT = """
Return a single JSON object only. No markdown, no explanations.
"""