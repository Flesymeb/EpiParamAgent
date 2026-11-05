# Synthesis execution report

Status: complete
Reproduction status: exploratory

Independent numeric verification: verified
Numbers below come only from the sandbox execution artifact.

{
  "point_estimate": 5.238908179149273,
  "unit": "days",
  "method": "random",
  "ci_lower": 4.788537394208007,
  "ci_upper": 5.689278964090538,
  "ci_level": 0.95,
  "interval_type": "CI",
  "tau2": 0.08370425702542335,
  "Q": 4.988938698503375,
  "I2": 0.3986697008524146
}

Contributions: 4

Assumptions:
[
  "Each selected row is an independent cohort (distinct cohort_id and study).",
  "CI-derived SEs assume a symmetric normal interval at the reported confidence level.",
  "The 90% CI row (r4) is excluded rather than reinterpreted at 95%.",
  "The median/IQR row (r6) is excluded as a different statistic.",
  "Pooling is exploratory on the current data: the original method is followed (DL random effects, 95% normal CI, hours-to-days conversion, one estimate per cohort), but the current table differs from the original review's included set, so this is not a reproduction."
]

Scientific correctness has not been independently verified. Exploratory results do not establish original-SR reproduction.
