SYSTEM = """
You are an epidemiology meta-analyst indexing a primary COVID-19 paper to guide parameter extraction.
Use only evidence from the provided text. Do not guess.
"""

USER = """
Task: Parse the structure of this paper to identify where reproduction number evidence is located
and capture methodological details needed for downstream processing.

Focus on:
1. WHERE R0/Rt estimates appear (section, table, figure)
2. HOW R0 was estimated (method category, model type, data type)
3. WHAT inputs/assumptions were used (SI, generation interval, susceptible fraction)
4. WHETHER this is pre-intervention R0 or control-phase Rt
5. HOW the CI/CrI was derived (MCMC, bootstrap, profile likelihood, analytical)

Return a JSON object with ALL of the following keys:

{
  "doc_structure": [{"section": "...", "evidence_hint": "..."}],

  "study_meta": {
    "region_raw": "country/city/region as stated",
    "period_raw": "data collection period as stated",
    "population_raw": "population or setting",
    "method_raw": "estimation method verbatim from paper",
    "data_type_raw": "case counts | deaths | hospitalizations | serological | wastewater | other",
    "model_type_raw": "SIR | SEIR | SEIRD | branching_process | next_generation | other | NA"
  },

  "method_index": {
    "method_category": "one of: exponential_growth | maximum_likelihood | bayesian | seir_fit | branching_process | next_generation_matrix | other",
    "ci_derivation": "one of: mcmc_posterior | bootstrap | profile_likelihood | analytical | delta_method | simulation | not_reported",
    "generation_interval_assumed": "SI or GI value used as input, e.g. '5.1 days (SD 3.4)' or null if estimated internally",
    "is_pre_intervention": true or false,
    "data_weeks": estimated number of weeks of data used (integer or null),
    "transformation": "transformation applied IN THE PAPER: log | log10 | none | other",
    "processing_hint": "one of: standard_ci | treat_cri_as_ci | log_normal_se | wide_ci_flag | no_interval",
    "method_notes": "free-text note about critical methodological details, special populations, or processing caveats — e.g. 'log-scale CI; back-transform needed', 'closed cruise ship environment', 'CI is sensitivity range not statistical'"
  },

  "parameter_mentions": [
    {
      "param": "R0 | Rt | net_reproduction_number",
      "value_raw": "...",
      "uncertainty_raw": "...",
      "unit_raw": "dimensionless",
      "evidence": "section/table/figure reference"
    }
  ],

  "field_evidence": {
    "parameter_type": "evidence location for parameter type",
    "point_estimate": "evidence location for numeric estimate",
    "uncertainty": "evidence location for CI/CrI/SE"
  }
}

processing_hint guide:
- standard_ci:      CI reported, treat as normal 95% CI
- treat_cri_as_ci:  Bayesian CrI, treat same as CI for pooling
- log_normal_se:    Only geometric mean / log-scale interval reported
- wide_ci_flag:     CI width > 5x the point estimate — flag for sensitivity analysis
- no_interval:      No uncertainty reported — will need SE imputation
"""

OUTPUT = """
Return a single JSON object only. No markdown, no explanations.
"""
