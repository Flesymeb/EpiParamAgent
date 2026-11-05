# One analysis, one estimand

The plan carries an `estimand` block. Fill it before anything else, because
the method, the rows you may select and the way you pool them all follow
from it.

```yaml
estimand:
  parameter_type: incubation_period
  statistic: mean
  population: laboratory-confirmed cases in the target outbreak
  group: all reported groups
  timepoint: exposure to symptom onset
  endpoint_definition: symptom onset after a confirmed exposure
  unit: days
  uncertainty: {type: SE, level: null}
```

Unknown descriptors are `NR` or `null`, never a plausible guess. A missing
field is information about the source, and it is preserved as missing.

## What the rows have to agree on

Four things must match across the selected rows, or the plan has to say how
they are reconciled:

- **The statistic.** A mean and a median of the same parameter are two
  estimands. Pool them only through a declared, executed approach.
- **The parameter.** Incubation period and serial interval are different
  quantities even when both are expressed in days.
- **The endpoint.** A case fatality rate among confirmed cases is not a case
  fatality rate among estimated infections.
- **The unit.** The method unit and the estimand unit must be identical.
  Converting hours to days is a declared transformation with a ledger entry,
  and the factor applies to the point estimate and the standard error
  together.

## Independent units

One pooled estimate per independent cohort. When the same study reports
several estimates, choose one by a stated rule or model the dependence
explicitly; do not let the rows count as independent by accident. The
deterministic helper refuses rows whose `cohort_id` is missing or repeated,
and asks for generated code with a declared dependence model instead.

## Which route to take

The deterministic engine covers the registered methods, and its independent
oracle covers the inverse-variance ones:

| Question | Route |
| --- | --- |
| Inverse-variance pooling of fixed, DL random or REML | `compute_meta` first, then confirm in code |
| The same with an `hk`, `modified_hk` or prediction interval | the engine; statsmodels does not reproduce these intervals |
| Common-risk aggregate, logit-scale pooling, a descriptive median | the engine registers them, but the independent oracle does not verify them |
| Anything the engine does not register | generated code, with the limitation stated in the result |

A result that the oracle cannot verify is still publishable, but it must say
so. Numeric agreement is not scientific validity, and the reverse also holds:
a method outside the oracle's scope is not thereby wrong.

## What the uncertainty has to be

Every pooled row needs a standard error, and the derivation has to match what
the source reported. Record it in the plan transformation ledger before
writing the code, because the ledger is checked against the executed code.

An interval whose level was not reported is not a confidence interval you may
reinterpret at 95%. A standard deviation needs a sample size. A CrI, an IQR
and a range are not interchangeable with a confidence interval.

## Record the decisions

The plan keeps the choices that a reader would need in order to repeat the
analysis: the assumptions, the sensitivity checks that were actually
executed, the exclusions and why each row was excluded. A protocol that
cannot support the estimand is an honest `protocol_pending` or
`not_computable` plan with reasons, not a guess.

Exploratory reanalysis is a legitimate answer. It must be labelled
`exploratory`, it needs nonempty assumptions and a real sensitivity analysis,
and it never presents itself as a reproduction of the original review.
