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

`/inputs/table.jsonl` is JSON Lines, one object per line, so it has to be read
line by line. The rows do not all carry the same columns — a row that reports
an SE has no CI bounds — so the reader has to union the columns first:

```r
read_table <- function(path) {
  rows <- lapply(readLines(path, warn = FALSE), jsonlite::fromJSON)
  cols <- Reduce(union, lapply(rows, names))
  rows <- lapply(rows, function(r) {
    values <- lapply(cols, function(cn) if (is.null(r[[cn]])) NA else r[[cn]])
    names(values) <- cols
    as.data.frame(values, stringsAsFactors = FALSE)
  })
  do.call(rbind, rows)
}

plan <- jsonlite::fromJSON("/analysis_plan.json")
rows <- read_table("/inputs/table.jsonl")
keep <- rows[rows$input_id %in% plan$selection$selected_input_ids, ]
```

`jsonlite` is the usual way to read JSON in R. If it is missing, write the
result file by hand instead of installing anything: the sandbox has no
network.

## Derive the SE and the unit scale

The table rows carry the reported uncertainty, not the pooled standard error,
so the same derivation the engine uses has to run first:

```r
unit_scale <- list(days = 1, day = 1, d = 1,
                   hours = 1 / 24, hour = 1 / 24, h = 1 / 24,
                   weeks = 7, week = 7)

se_of <- function(r) {
  kind <- toupper(trimws(as.character(r$uncertainty_type)))
  if (identical(kind, "SE")) {
    return(as.numeric(r$se))
  }
  if (identical(kind, "SD")) {
    return(as.numeric(r$sd) / sqrt(as.numeric(r$sample_size)))
  }
  if (identical(kind, "CI")) {
    raw <- trimws(as.character(r$uncertainty_level))
    level <- as.numeric(sub("%$", "", raw))
    if (grepl("%", raw) || (level > 1 && level < 100)) level <- level / 100
    low <- as.numeric(r$uncertainty_low)
    high <- as.numeric(r$uncertainty_high)
    point <- as.numeric(r$point_estimate)
    if (!(level > 0 && level < 1) || low >= high) stop("Invalid CI bounds or level")
    if (!(point >= low && point <= high)) stop("Point estimate lies outside the reported CI")
    return((high - low) / (2 * qnorm((1 + level) / 2)))
  }
  stop(sprintf("Unsupported uncertainty type: %s", kind))
}

keep$se_used <- vapply(seq_len(nrow(keep)), function(i) se_of(keep[i, ]), numeric(1))
factor <- vapply(keep$unit, function(u) {
  source <- unit_scale[[tolower(trimws(as.character(u)))]]
  target <- unit_scale[[tolower(trimws(as.character(plan$method$unit)))]]
  if (is.null(source) || is.null(target)) stop("Unknown or incompatible unit")
  source / target
}, numeric(1))
keep$value_used <- keep$point_estimate * factor
keep$se_used <- keep$se_used * factor
```

The factor applies to the point estimate and the standard error together, and
the `transformations` ledger has to say so for every row it touches.

## Pool with metafor

```r
library(metafor)

m <- rma(yi = keep$value_used, vi = keep$se_used^2,
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
