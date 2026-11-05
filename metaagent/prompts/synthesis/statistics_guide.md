# Project synthesis statistics guide v1

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
