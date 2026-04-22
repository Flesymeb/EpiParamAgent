"""Meta-analysis pooling utilities — shared across all parameter types.

Handles SE derivation from various uncertainty reporting styles
(CI, CrI, SD, SE, IQR, Range) and implements DerSimonian-Laird
random-effects pooling (inverse-variance weighting).

Typical workflow
---------------
>>> import pandas as pd
>>> from meta_analysis.pooling import summarize
>>> df = pd.read_excel("coding_sheet_output.xlsx")
>>> summary = summarize(df, parameter_type="serial_interval", group_by="disease_name")
>>> print(summary[["disease_name", "pooled_mean", "ci_lower", "ci_upper", "i2", "n_studies"]])

Or low-level:
>>> from meta_analysis.pooling import se_from_record, pool_means
>>> records = [{"point_estimate": 6.3, "se": se_from_record(row)} for row in rows]
>>> result = pool_means(records)  # DL random effects
"""

from __future__ import annotations

import math
import re
import warnings
from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy.stats import chi2, norm

__all__ = ["se_from_record", "pool_means", "summarize"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _f(value: Any) -> float | None:
    """Coerce to finite float, return None if not possible."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v or v.upper() in {"NR", "NA", "N/A", "NONE", "NULL", "—", "-"}:
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _norm(value: Any) -> str:
    """Lowercase, strip whitespace/punctuation for type-string comparison."""
    return re.sub(r"[\s_/\-]", "", str(value or "")).lower()


def _extract_n(value: Any) -> float | None:
    """Parse sample size from strings like '48 pairs', '339', '1407 cases'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    m = re.search(r"(\d+(?:\.\d+)?)", str(value))
    if not m:
        return None
    n = float(m.group(1))
    return n if n > 0 else None


def _ci_z(level: Any) -> float | None:
    """Return two-tailed z for a stated confidence/credible level."""
    t = _norm(level)
    if t in {"95", "95%", "0.95"}:
        return 1.96
    if t in {"90", "90%", "0.90"}:
        return 1.645
    if t in {"99", "99%", "0.99"}:
        return 2.576
    if t in {"80", "80%", "0.80"}:
        return 1.282
    # Try to parse e.g. "97.5" → z = norm.ppf(0.975 + (1-0.975)/2)... fallback
    m = re.match(r"^(\d+(?:\.\d+)?)%?$", t)
    if m:
        pct = float(m.group(1))
        if 50 < pct < 100:
            alpha = 1 - pct / 100
            return float(norm.ppf(1 - alpha / 2))
    return None


def _single(low: Any, high: Any) -> float | None:
    """Return the single non-None value from (low, high), or None if both/neither."""
    lo, hi = _f(low), _f(high)
    if lo is not None and hi is not None:
        return None  # ambiguous — caller decides
    return hi if hi is not None else lo


# ---------------------------------------------------------------------------
# Public: SE derivation
# ---------------------------------------------------------------------------

def se_from_record(row: dict) -> float | None:
    """Derive standard error from a coding_sheet row.

    Reads: uncertainty_type, uncertainty_level, uncertainty_low,
           uncertainty_high, sample_size.

    Returns SE (float > 0) or None if SE cannot be derived.

    Supported types
    ---------------
    CI / CrI  :  SE = (upper − lower) / (2 × z)
                 level defaults to 95% if not stated
    SE        :  SE = single provided value (low or high, whichever is set)
    SD        :  SE = SD / √n   (SD = single value in low or high field)
    IQR       :  SD ≈ IQR / 1.35,  SE = SD / √n
    Range     :  SD via Wan et al. 2014 range-only estimator, SE = SD / √n
    """
    utype = _norm(row.get("uncertainty_type"))
    low = row.get("uncertainty_low")
    high = row.get("uncertainty_high")
    n = _extract_n(row.get("sample_size"))

    if utype in ("", "nr", "other", "missing", "nan"):
        return None

    # ── CI / CrI ────────────────────────────────────────────────────────────
    if utype in ("ci", "cri", "confidenceinterval", "credibleinterval",
                 "credibleintervals", "confidenceintervals"):
        lo, hi = _f(low), _f(high)
        if lo is None or hi is None:
            return None
        if hi <= lo:
            warnings.warn(f"CI bounds inverted (low={lo}, high={hi}); skipping.")
            return None
        z = _ci_z(row.get("uncertainty_level")) or 1.96  # default 95%
        return (hi - lo) / (2 * z)

    # ── SE ──────────────────────────────────────────────────────────────────
    if utype == "se":
        # SE may be in low OR high; if both differ, use mean (rare edge case)
        lo, hi = _f(low), _f(high)
        if lo is not None and hi is not None:
            se_val = (lo + hi) / 2.0  # unusual; warn
            warnings.warn("SE type with two values; using mean of both.")
        else:
            se_val = hi if hi is not None else lo
        return se_val if (se_val is not None and se_val > 0) else None

    # ── SD ──────────────────────────────────────────────────────────────────
    if utype == "sd":
        # SD is a single value; don't average low and high — take whichever is set.
        # Convention in coding_sheet: SD stored in uncertainty_high when only one
        # value is present; fall back to uncertainty_low.
        sd = _single(low, high)
        if sd is None:
            # Both set: ambiguous encoding — take high as SD (common convention)
            hi_v = _f(high)
            sd = hi_v
        if sd is None or sd <= 0:
            return None
        if n is None:
            warnings.warn("SD reported but sample_size missing; cannot compute SE.")
            return None
        return sd / math.sqrt(n)

    # ── IQR ─────────────────────────────────────────────────────────────────
    if utype == "iqr":
        lo, hi = _f(low), _f(high)
        if lo is None or hi is None or hi <= lo:
            return None
        if n is None:
            warnings.warn("IQR reported but sample_size missing; cannot compute SE.")
            return None
        sd_approx = (hi - lo) / 1.35
        return sd_approx / math.sqrt(n)

    # ── Range ────────────────────────────────────────────────────────────────
    if utype == "range":
        lo, hi = _f(low), _f(high)
        if lo is None or hi is None or hi <= lo:
            return None
        if n is None or n <= 1:
            warnings.warn("Range reported but sample_size missing/invalid.")
            return None
        # Wan et al. 2014 (BMC Med Res Methodol) — range-only estimator
        denom = 2.0 * norm.ppf((n - 0.375) / (n + 0.25))
        if denom <= 0:
            return None
        sd_approx = (hi - lo) / denom
        return sd_approx / math.sqrt(n)

    warnings.warn(f"Unrecognised uncertainty_type={row.get('uncertainty_type')!r}; returning None.")
    return None


# ---------------------------------------------------------------------------
# Public: pooling
# ---------------------------------------------------------------------------

def pool_means(
    records: Sequence[dict],
    method: str = "random",
) -> dict:
    """Inverse-variance weighted pooling (fixed or DerSimonian-Laird random effects).

    Parameters
    ----------
    records : sequence of dicts, each must have 'point_estimate' (float) and
              'se' (float > 0).  Rows with missing/invalid values are excluded.
    method  : 'random' (default, DL estimator) or 'fixed'.

    Returns
    -------
    dict with keys:
        pooled_mean, se_pooled, ci_lower, ci_upper,
        i2 (%), tau2, Q, df, p_het,
        n_studies (used), n_excluded (dropped due to missing SE/estimate)
    """
    method = method.lower()
    if method not in ("fixed", "random"):
        raise ValueError("method must be 'fixed' or 'random'")

    valid: list[tuple[float, float]] = []
    n_excluded = 0
    for rec in records:
        est = _f(rec.get("point_estimate"))
        se = _f(rec.get("se"))
        if est is None or se is None or se <= 0:
            n_excluded += 1
        else:
            valid.append((est, se))

    if not valid:
        return {
            "pooled_mean": float("nan"), "se_pooled": float("nan"),
            "ci_lower": float("nan"), "ci_upper": float("nan"),
            "i2": float("nan"), "tau2": float("nan"),
            "Q": float("nan"), "df": 0,
            "p_het": float("nan"), "n_studies": 0, "n_excluded": n_excluded,
        }

    y = np.array([v[0] for v in valid])
    se_arr = np.array([v[1] for v in valid])
    var = se_arr ** 2
    k = len(y)

    # Fixed-effects quantities (used for Q and I²)
    w_fe = 1.0 / var
    mu_fe = float(np.dot(w_fe, y) / w_fe.sum())
    Q = float(np.dot(w_fe, (y - mu_fe) ** 2))
    df = k - 1
    p_het = float(chi2.sf(Q, df)) if df > 0 else float("nan")
    i2 = float(max(0.0, (Q - df) / Q * 100.0)) if (Q > 0 and df > 0) else 0.0

    # Tau² (DerSimonian-Laird)
    tau2 = 0.0
    if method == "random" and k > 1:
        c = float(w_fe.sum() - (w_fe ** 2).sum() / w_fe.sum())
        tau2 = max(0.0, (Q - df) / c) if c > 0 else 0.0

    w = 1.0 / (var + tau2)
    pooled = float(np.dot(w, y) / w.sum())
    se_pooled = float(math.sqrt(1.0 / w.sum()))

    return {
        "pooled_mean": pooled,
        "se_pooled": se_pooled,
        "ci_lower": pooled - 1.96 * se_pooled,
        "ci_upper": pooled + 1.96 * se_pooled,
        "i2": i2,
        "tau2": tau2,
        "Q": Q,
        "df": df,
        "p_het": p_het,
        "n_studies": k,
        "n_excluded": n_excluded,
    }


# ---------------------------------------------------------------------------
# Public: high-level summarize
# ---------------------------------------------------------------------------

def summarize(
    df: pd.DataFrame,
    *,
    parameter_type: str | None = None,
    estimate_measure: str | None = "mean",
    group_by: str | list[str] | None = None,
    method: str = "random",
) -> pd.DataFrame:
    """Derive SEs and compute pooled mean (± I²) from a coding_sheet DataFrame.

    Parameters
    ----------
    df              : coding_sheet extraction output (must contain standard columns).
    parameter_type  : filter to this parameter_type (e.g. 'serial_interval'). None = all.
    estimate_measure: filter to 'mean', 'median', or None (all). Default 'mean'.
                      Pass None to include medians (treated as means — use with caution).
    group_by        : column name(s) to group by before pooling (e.g. 'disease_name',
                      ['disease_name', 'country']).  None = pool everything.
    method          : 'random' (default) or 'fixed'.

    Returns
    -------
    pd.DataFrame with one row per group (or one row if group_by is None), columns:
        [group columns..., pooled_mean, se_pooled, ci_lower, ci_upper,
         i2, tau2, Q, df, p_het, n_studies, n_excluded]
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    work = df.copy()

    # Filter by parameter type
    if parameter_type and "parameter_type" in work.columns:
        work = work[work["parameter_type"].astype(str).str.strip().str.lower()
                    == parameter_type.strip().lower()]

    # Filter by estimate measure
    if estimate_measure and "estimate_measure" in work.columns:
        work = work[work["estimate_measure"].astype(str).str.strip().str.lower()
                    == estimate_measure.strip().lower()]

    if work.empty:
        warnings.warn("No rows remain after filtering; returning empty summary.")
        return pd.DataFrame()

    # Derive SE for every row
    work = work.copy()
    work["se"] = [se_from_record(row) for row in work.to_dict("records")]

    def _pool_group(g: pd.DataFrame) -> dict:
        recs = g[["point_estimate", "se"]].to_dict("records")
        return pool_means(recs, method=method)

    if group_by is None:
        result = _pool_group(work)
        return pd.DataFrame([result])

    group_cols = [group_by] if isinstance(group_by, str) else list(group_by)
    missing = [c for c in group_cols if c not in work.columns]
    if missing:
        raise KeyError(f"group_by columns not in DataFrame: {missing}")

    rows = []
    for keys, group in work.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update(_pool_group(group))
        rows.append(row)

    out = pd.DataFrame(rows)
    # Round for readability
    for col in ("pooled_mean", "se_pooled", "ci_lower", "ci_upper", "tau2", "Q"):
        if col in out.columns:
            out[col] = out[col].round(4)
    for col in ("i2",):
        if col in out.columns:
            out[col] = out[col].round(1)
    return out
