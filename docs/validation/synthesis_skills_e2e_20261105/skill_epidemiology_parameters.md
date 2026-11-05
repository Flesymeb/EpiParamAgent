# Pooling by parameter

The coding tables carry `parameter_type` values `incubation_period`,
`serial_interval`, `fatality_rate`, `positivity_rate`,
`reproduction_number` and `dispersion_k`. Each one needs a different
treatment, and each one has a way to be silently mis-pooled.

## incubation_period

The estimand is the time from a person's exposure or infection to symptom
onset, for one population, on one time scale.

- Pool `estimate_measure = mean` rows by inverse variance.
- A reported **median** is a different estimand. Pool the medians only
  through a declared, executed approach, or keep them descriptive.
- A reported **distribution** (a fitted lognormal, say) is not a mean. When
  the source reports distribution parameters instead of a summary, the
  estimand is that distribution, and deriving a mean from it is an
  exploratory assumption that needs a sensitivity check.
- Right skew is the norm. A pooled mean on the raw scale is the standard
  answer, but say so and show the medians alongside it.

## serial_interval

The time between successive cases in a transmission chain.

- Forward and backward serial intervals are **different estimands**. Do not
  pool them; select one by a stated rule.
- A generation interval is not a serial interval. Keep them apart even when
  the source mixes the terms.
- Pool the declared statistic by inverse variance, on one time scale.

## fatality_rate

A proportion with a denominator that must be named: deaths among confirmed
cases, deaths among estimated infections, deaths among hospitalizations,
deaths among ICU admissions.

- The **common-risk aggregate** pools the raw counts, not the proportions.
  Use it when the studies report cases and deaths that can be summed. The
  assumption is a common risk and independent observations, and it belongs
  in the assumptions.
- The **logit-scale** route pools the logit of each proportion with its
  standard error. It needs the proportion and its standard error, so a
  proportion reported only as a range cannot enter.
- A CFR and an IFR never share a pool. A study reporting a CFR, an ICU CFR
  and an IFR contributes one of them, chosen by the plan.
- The independent oracle covers inverse-variance pooling only. Both
  proportion routes run and publish, and the result records that the numbers
  were not independently verified.

## positivity_rate

The share of tests that are positive.

- The denominator matters: tests performed, people tested, or a surveillance
  population. Pool only rows with the same denominator.
- A study that reports positivity at several time points contributes rows
  that are not independent. Either select one by a stated rule or declare a
  dependence model.

## reproduction_number

R0, Rt and Re are different estimands, and R is not usually reported with a
standard error that can be pooled.

- The usual route is to pool the **inputs** — a growth rate, a serial or
  generation interval, or a transmission rate — by inverse variance, and then
  derive R in code. The derivation formula belongs in the plan and is
  executed, for example `R = exp(gamma * D)` for a growth rate `gamma` and an
  interval `D`.
- Pooling reported R values directly is only defensible when every study
  derived them from the same model with the same inputs, and the plan says
  which.
- Rt is time-varying, so a single pooled Rt needs a declared time window.

## dispersion_k

A dispersion parameter is not an effect, so inverse-variance pooling does not
apply to it. Fitting a meta-model that estimates the dispersion directly is
outside what the sandbox can verify, and the honest answers are a descriptive
summary or a `not_computable` plan with the reasons.

## What every parameter shares

- The unit must be one target for the whole analysis.
- One estimate per independent cohort.
- Every pooled row needs a standard error with a recorded derivation.
- Rows that differ in statistic, parameter, endpoint, group, timepoint or
  population need an explicit compatibility decision in the plan and an
  executed sensitivity analysis, not a silent merge.
