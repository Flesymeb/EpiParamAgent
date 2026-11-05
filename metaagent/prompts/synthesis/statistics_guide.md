# Project synthesis statistics guide v1

## Choosing the estimand and the method

Read the coding columns before choosing: parameter_type, estimate_measure,
point_estimate, unit, uncertainty_type, uncertainty_level, uncertainty_low,
uncertainty_high, distribution, population, estimation_period, method.

| parameter_type | statistic | method | unit |
| --- | --- | --- | --- |
| incubation_period | mean | fixed or random, normal interval | days |
| serial_interval | mean | fixed or random, normal interval | days |
| fatality_rate | proportion | binomial (common risk) or logit_fixed / logit_random | proportion or % |
| positivity_rate | proportion | binomial or logit | proportion or % |
| reproduction_number | derived from a growth rate or a transmission model | generated code | dimensionless |

A mean and a median of one parameter are two estimands, and so are a case
fatality rate among confirmed cases and one among estimated infections.
Pooling rows that differ in measure, endpoint, population, group or time
origin needs an explicit compatibility decision in the plan and an executed
sensitivity analysis, not a silent merge.

The independent oracle covers fixed, DL random and REML on the declared
analysis scale. The other registered methods run and publish, and the result
records that their numbers were not independently verified.

Before writing code, pull the matching manual with read_skill; the names are
in profile.skills: estimands, epidemiology_parameters, python_meta_analysis,
r_meta_analysis, sandbox_environment.

Use method_capabilities before selecting an inverse-variance method. The supported
independent oracle covers fixed, DL random (aliases random/dl/random_effects) and
REML. Declare method.interval_method as normal, hk or modified_hk, ci_level as an
explicit probability, and tau_estimator as none, DL or REML consistently with the
name. HK requires at least two independent effects; prediction_interval=true uses
t(k-2) and needs at least three. Prediction intervals assume an approximate normal
random-effect distribution; they are not individual-patient reference ranges.

compute_meta {} is a bounded optional calculation helper after save_plan. It uses
the saved selection and reported SE, CI with its stated confidence level, or SD
with numeric sample size. It never imputes missing uncertainty or publishes an
answer. Declare conversions in the plan and execution ledger. Then write_code,
run_code and finalize as usual. Results of recognized random methods MUST include
tau2; provide interval_type=CI, ci_level and interval_method when giving intervals.
The independent verifier compares actual point, tau2, confidence bounds, supplied
weights and supplied heterogeneity metrics. Unsupported custom methods remain
numerically unverified, even if repeated execution succeeds. Never rename a known
method to bypass verification. Scientific selection and cohort independence are
not established by numeric verification.

SE transformation arithmetic alone is insufficient: a derivation from CI or SD
must agree with the original bounds, source level and sample-size definition.
No-match in evidence_search is not evidence of absence. Preserve exact source IDs
and offsets and use evidence pagination when search is inconclusive. Unapproved
CrI/IQR/range approximations remain exploratory with assumptions and executed
sensitivity. Do not select a formula to approach a source SR pooled answer.

Report Q, I2, tau2 on their analysis scale. Influence and Egger diagnostics are
advisory, never automatic deletion or correction. Egger requires at least ten
independent estimates and varying precision; association is not proof of publication
bias. For proportions or strong effect/SE dependence it may be inappropriate.
