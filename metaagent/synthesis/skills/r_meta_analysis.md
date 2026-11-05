---
name: r_meta_analysis
description: metafor and meta recipes for the R route, with the runtime precondition stated up front.
---

# The R route

**Precondition.** This route needs an R runtime with `metafor` and `meta`
installed on the host that runs the sandbox. When there is none, `run_code`
returns a recoverable error — `Rscript is unavailable; use Python or supply an
R-enabled runtime` — and the agent switches to the Python route.

These recipes were written against the documented `metafor` and `meta`
interfaces. They were **not executed in this environment**, because the host
here has no R runtime. The Python route is the one that was executed and
checked; when both routes are available, compare them before trusting the R
one.

## Read the table and the plan

```r
plan <- jsonlite::fromJSON("/analysis_plan.json")
rows <- readLines("/inputs/table.jsonl")
rows <- lapply(rows, function(x) jsonlite::fromJSON(x))
keep <- rows[rows$input_id %in% plan$selection$selected_input_ids]
```

`jsonlite` is the usual way to read JSON in R. If it is missing, write the
result file by hand instead of installing anything: the sandbox has no
network.

## Pool with metafor

```r
library(metafor)

m <- rma(yi = keep$point_estimate, vi = keep$se_used^2,
         method = "DL", slab = keep$study, data = keep)
```

- `method` selects the estimator: `"DL"` for DerSimonian-Laird, `"REML"` for
  restricted maximum likelihood, `"PM"` for Paule-Mandel, `"HE"` for
  Hartwell, `"HS"` for Hedges-Smith.
- `vi` is the **variance** of each effect, so square the standard error.
- `slab` labels the rows in the forest plot.

For the conservative interval, ask for the Knapp-Hartung adjustment:

```r
m <- rma(yi = keep$point_estimate, vi = keep$se_used^2,
         method = "DL", test = "knha", slab = keep$study, data = keep)
```

`test = "knha"` uses a t quantile with `k-1` degrees of freedom, the same
form the engine uses for its `hk` interval.

The numbers to report:

```r
pooled <- m$b            # pooled estimate
se     <- m$se           # standard error of the pooled estimate
lo     <- m$ci.lb        # lower confidence bound
hi     <- m$ci.ub        # upper confidence bound
tau2   <- m$tau2         # between-study variance
Q      <- m$QE           # Cochran's Q
I2     <- m$I2           # I-squared, in percent
```

`predict(m)` gives the prediction interval for a new study, and
`weights(m)` gives the inverse-variance weights.

## Effect sizes and the proportion routes

```r
library(metafor)

# odds ratio and its variance from two 2x2 tables
es <- escalc("OR", a1, b1, c1, d1, n1 = n1)

# risk ratio and standardised mean difference
es <- escalc("RR", x1, n1, x2, n2)
es <- escalc("SMD", m1, sd1, n1, m2, sd2, n2)
```

The `meta` package covers the proportion and continuous routes:

```r
library(meta)

m <- metabin(event.e, n.e, sm = "RR", method = "MH")
m <- metacont(mean.e, sd.e, n.e, sm = "SMD", method = "REML")
```

`metabin` with `sm = "RR"` aggregates the raw counts, which is the same
common-risk idea as the engine's `binomial` method.

## Write the result

The result must land in `/work/result.json` in the same schema as the Python
route. When `jsonlite` is available:

```r
jsonlite::write_json(result, "/work/result.json", auto_unbox = TRUE, digits = 10)
```

Without it, format the file by hand and keep the numbers unrounded. The
schema is fixed: `status`, `result` with `point_estimate`, `ci_lower`,
`ci_upper`, `ci_level`, `interval_type` and `unit`, `contributions` with
`input_id`, `value_used`, `se_used` and `weight`, `transformations`,
`sensitivity` and `limitations`.

Keep the contributions' `weight` as the normalized share that sums to one,
not the raw inverse variance. Write the forest plot to `/work/forest.png` and
`/work/forest.pdf`.

## Reproducibility

`run_code` executes the code twice and rejects inconsistent output. Fix the
random seed for anything stochastic, and sort the rows by `input_id` before
you compute, so the two runs agree.
