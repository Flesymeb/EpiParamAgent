"""Deterministic, advisory numeric checks shared by all coding variants.

No extracted values are repaired or inferred. Normal-CI/SE and crude-rate checks
are consistency diagnostics, not replacements for the source's statistical model.
"""
from __future__ import annotations

import math
from statistics import NormalDist

_MISSING = {"", "nr", "na", "n/a", "none", "null", "unknown"}
_TIME = {"days": 1.0, "day": 1.0, "d": 1.0,
         "hours": 1 / 24, "hour": 1 / 24, "h": 1 / 24,
         "weeks": 7.0, "week": 7.0}
_PROBABILITY_UNITS = {"proportion": 1.0, "fraction": 1.0,
                      "percentage": 100.0, "percent": 100.0, "%": 100.0}
_INTERVALS = {"ci", "cri", "iqr", "range"}


def _text(value):
    return str(value or "").strip().casefold()


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def parse_uncertainty_level(value):
    """Parse an explicitly declared level, never defaulting to 95 percent."""
    text = str(value).strip()
    percent = text.endswith("%")
    number = _number(text.removesuffix("%").strip())
    if number is None:
        return None
    if percent or 1 < number < 100:
        number /= 100
    return number if 0 < number < 1 else None


def _interval_flags(row, point_field, kind_field, level_field, low_field, high_field):
    kind = _text(row.get(kind_field))
    if kind not in _INTERVALS:
        return []
    flags = []
    point, low, high = (_number(row.get(name)) for name in (point_field, low_field, high_field))
    if low is not None and high is not None and low > high:
        flags.append(f"numeric_interval_reversed:{low_field}:{high_field}")
    if kind != "iqr" and point is not None:
        if low is not None and point < low or high is not None and point > high:
            flags.append(f"numeric_point_outside_interval:{point_field}")
    if kind in {"ci", "cri"}:
        level = parse_uncertainty_level(row.get(level_field))
        if level is None:
            flags.append(f"numeric_invalid_or_missing_level:{level_field}")
        # This is only a normal approximation. Asymmetric/transformed intervals
        # may legitimately disagree; expose the discrepancy for human review.
        se = _number(row.get("se")) if point_field == "point_estimate" else None
        if kind == "ci" and level is not None and low is not None and high is not None and high > low and se is not None:
            quantile = (1 + level) / 2
            z = NormalDist().inv_cdf(quantile) if 0.5 < quantile < 1 else None
            expected = (high - low) / (2 * z) if z else None
            if expected is None or not math.isfinite(expected):
                flags.append("numeric_normal_ci_se_unrepresentable:se")
            elif se <= 0 or not math.isclose(se, expected, rel_tol=0.15, abs_tol=1e-8):
                flags.append("numeric_normal_ci_se_mismatch:se")
    return flags


def numeric_review_flags(row, config):
    """Return stable reason codes without mutating the record or configuration."""
    flags = []
    for field in config.fields:
        value = _number(row.get(field.name))
        if field.review_range is None or value is None:
            continue
        if field.review_range_unit:
            factor = _TIME.get(_text(row.get("unit")))
            if factor is None:
                flags.append(f"numeric_review_range_unknown_unit:{field.name}")
                continue
            value *= factor / _TIME[field.review_range_unit]
        low, high = field.review_range
        if low is not None and value < low or high is not None and value > high:
            flags.append(f"numeric_outside_review_range:{field.name}")
    flags.extend(_interval_flags(row, "point_estimate", "uncertainty_type", "uncertainty_level", "uncertainty_low", "uncertainty_high"))
    flags.extend(_interval_flags(row, "k_value", "k_ci_type", "k_ci_level", "k_ci_low", "k_ci_high"))

    kind = _text(row.get("uncertainty_type"))
    if kind in {"se", "sd"}:
        for field in (kind, "uncertainty_low", "uncertainty_high"):
            value = _number(row.get(field))
            if value is not None and (value < 0 or kind == "se" and value == 0):
                flags.append(f"numeric_nonpositive_se:{field}" if kind == "se" else f"numeric_negative_dispersion:{field}")

    measure = _text(row.get("estimate_measure"))
    parameter = _text(row.get("parameter_type"))
    effect = _text(config.effect_type)
    unit = _text(row.get("unit"))
    scale = _PROBABILITY_UNITS.get(unit)
    probability = measure in {"proportion", "percentage"} or parameter in {
        "cfr", "ifr", "fatality_rate", "positivity_rate"
    } or effect in {"fatality_rate", "positivity_rate"}
    point = _number(row.get("point_estimate"))
    # A count-only record legitimately has no estimate or unit.
    if probability and point is not None and scale is None:
        flags.append("numeric_probability_unit_unresolved:unit")
    if probability and scale is not None:
        names = ["point_estimate"]
        if kind in _INTERVALS:
            names += ["uncertainty_low", "uncertainty_high"]
        for name in names:
            value = _number(row.get(name))
            if value is not None and not 0 <= value <= scale:
                flags.append(f"numeric_probability_out_of_bounds:{name}")

    for numerator, denominator in (("deaths", "denominator_count"), ("positive_count", "tested_count")):
        n, d = _number(row.get(numerator)), _number(row.get(denominator))
        if n is not None and n < 0:
            flags.append(f"numeric_negative_count:{numerator}")
        if d is not None and d < 0:
            flags.append(f"numeric_negative_count:{denominator}")
        if n is not None and d is not None and n > d:
            flags.append(f"numeric_numerator_exceeds_denominator:{numerator}:{denominator}")
        if d == 0 and point is not None:
            flags.append(f"numeric_zero_denominator:{denominator}")
        # Missing adjustment metadata is not proof of a crude estimate. Require
        # at least one explicit crude declaration and no conflicting declaration.
        declarations = [_text(row.get(name)) for name in ("adjustment", "adjustment_status")]
        declarations = [v for v in declarations if v not in (_MISSING - {"none"})]
        crude = bool(declarations) and all(v in {"none", "unadjusted", "crude"} for v in declarations)
        if crude and probability and scale is not None and point is not None and n is not None and d is not None and d > 0:
            # 0.05 percentage points absolute or 5% relative permits rounding
            # while still catching common rare-event percentage scaling errors.
            if not math.isclose(point / scale, n / d, rel_tol=0.05, abs_tol=0.0005):
                flags.append(f"numeric_crude_rate_count_mismatch:{numerator}:{denominator}")
    return sorted(set(flags))
