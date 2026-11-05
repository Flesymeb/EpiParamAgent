"""Protocol-driven estimate selection and deterministic statistical execution.

This boundary intentionally does not read full text, repair coding semantics, infer
cohort independence or impute uncertainty. Unsupported protocols stay visible.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from scipy.stats import norm

from .methods import METHOD_REGISTRY, calculate


class UncertaintyRules(BaseModel):
    """Opt-in normal approximations; no source interval level is assumed."""
    model_config = ConfigDict(extra="forbid")
    allowed_types: list[Literal["SE", "CI", "SD"]]


class IndependenceRules(BaseModel):
    """The protocol declares which existing identity constitutes independence."""
    model_config = ConfigDict(extra="forbid")
    unit: Literal["cohort_id", "study_family_id", "record_id"]
    multiple_estimates: Literal["review", "select_ids"] = "review"
    selected_estimate_ids: list[str] = Field(default_factory=list)
    assert_independent_reports: bool = False


class BinomialRules(BaseModel):
    """Counts, zero-event handling and interval choice are protocol decisions."""
    model_config = ConfigDict(extra="forbid")
    interval_method: Literal["wilson", "clopper_pearson"]
    zero_event_policy: Literal["none", "continuity"]
    continuity_correction: float | None = Field(default=None, gt=0)
    numerator_field: str = "deaths"
    denominator_field: str = "denominator_count"


class SensitivitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    exclude_estimate_ids: list[str] = Field(default_factory=list)
    method: str | None = None


class AnalysisProtocol(BaseModel):
    """Versioned supported methods; unknown options never silently disappear."""
    model_config = ConfigDict(extra="forbid")
    analysis_id: str = Field(min_length=1)
    parameter_type: str = Field(min_length=1)
    estimate_measure: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    method: str
    uncertainty_rules: UncertaintyRules | None = None
    independence: IndependenceRules
    allow_unit_conversion: bool = False
    log_transform: bool = False
    ci_level: float = Field(default=0.95, gt=0, lt=1)
    minimum_estimates: int = Field(default=1, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    exclude_flagged_ineligible: bool = True
    input_measures: list[str] | None = None
    binomial_rules: BinomialRules | None = None
    median_interval_method: Literal["none", "order_statistic"] = "none"
    interval_method: Literal["normal", "hk", "modified_hk"] = "normal"
    prediction_interval: bool = False
    influence_diagnostics: bool = False
    publication_bias: bool = False
    leave_one_out: bool = False
    sensitivity: list[SensitivitySpec] = Field(default_factory=list)
    llm_selection: bool = False
    llm_report: bool = False


_MISSING = {"", "nr", "na", "n/a", "none", "null", "nan", "unknown"}
_UNITS = {
    "days": ("time", 1.0), "day": ("time", 1.0), "d": ("time", 1.0),
    "hours": ("time", 1 / 24), "hour": ("time", 1 / 24), "h": ("time", 1 / 24),
    "weeks": ("time", 7.0), "week": ("time", 7.0),
    "%": ("proportion", .01), "percentage": ("proportion", .01), "percent": ("proportion", .01),
    "proportion": ("proportion", 1.0), "fraction": ("proportion", 1.0),
    "dimensionless": ("ratio", 1.0), "unitless": ("ratio", 1.0), "ratio": ("ratio", 1.0),
}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _missing(value):
    return value is None or str(value).strip().casefold() in _MISSING


def _false(value):
    return value is False or (isinstance(value, str) and value.strip().lower() == "false")


def _review_issues(row):
    """Honor actual unresolved coding/evidence issues, independently of variant."""
    harmless = {"stage_b_not_run", "semantic_review_not_run", "not_semantically_finalized"}
    issues = []
    for key in ("review_flags", "review_notes", "unresolved_fields"):
        value = row.get(key)
        if _missing(value) or value in ([], {}):
            continue
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, (list, dict)) else value
            except ValueError:
                pass
        entries = value if isinstance(value, list) else list(value) if isinstance(value, dict) else str(value).split(";")
        issues.extend(str(x).strip() for x in entries if str(x).strip() and str(x).strip() not in harmless)
    if row.get("needs_review") is True or str(row.get("needs_review", "")).lower() == "true":
        if not issues:
            issues.append("coding_requires_review")
    if str(row.get("semantic_review", "")).lower() in {"pending", "unresolved", "rejected"}:
        issues.append("unresolved_semantic_review")
    return issues


def _safe(value):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(_safe(value), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _se(row, rules):
    """Return original-unit SE plus an auditable derivation or a review reason."""
    kind = str(row.get("uncertainty_type") or "").strip().upper()
    if not kind and not _missing(row.get("se")):
        kind = "SE"
    if kind not in rules.allowed_types:
        return None, None, "uncertainty_type_not_authorized_or_missing"
    for field in ("uncertainty_low", "uncertainty_high", "se", "sd"):
        if not _missing(row.get(field)) and _number(row.get(field)) is None:
            return None, None, "nonfinite_or_invalid_uncertainty:" + field
    low, high = _number(row.get("uncertainty_low")), _number(row.get("uncertainty_high"))
    if kind in {"SE", "SD"}:
        direct = _number(row.get("se" if kind == "SE" else "sd"))
        values = [v for v in (low, high) if v is not None]
        if direct is not None:
            values.append(direct)
        if not values or min(values) <= 0 or any(not math.isclose(v, values[0]) for v in values):
            return None, None, "missing_or_ambiguous_dispersion"
        if kind == "SE":
            return values[0], {"method": "reported_se", "input": values[0]}, None
        n = _number(row.get("sample_size"))
        if n is None or n <= 0:
            return None, None, "missing_numeric_sample_size_for_sd"
        return values[0] / math.sqrt(n), {"method": "sd_div_sqrt_n", "sd": values[0], "n": n}, None
    raw_level = row.get("uncertainty_level")
    percent = isinstance(raw_level,str) and raw_level.strip().endswith("%")
    level = _number(raw_level.strip().removesuffix("%").strip() if isinstance(raw_level,str) else raw_level)
    if level is not None and (percent or 1 < level < 100):
        level /= 100
    point = _number(row.get("point_estimate"))
    if level is None or not 0 < level < 1 or low is None or high is None or low >= high:
        return None, None, "missing_or_invalid_ci_bounds_or_level"
    if point is None or not low <= point <= high:
        return None, None, "point_outside_reported_ci"
    z = float(norm.ppf((1 + level) / 2))
    if not math.isfinite(z) or z <= 0:
        return None, None, "unrepresentable_ci_quantile"
    se = (high - low) / (2 * z)
    return se, {"method": "normal_ci_width", "low": low, "high": high, "level": level, "z": z}, None


def run_synthesis(records: list[dict], protocol: dict, *, llm_invoke=None) -> dict:
    """Select estimates and calculate from an explicit, immutable protocol.

    Status is complete/single_estimate, partial (some eligible inputs need review),
    not_computable, or protocol_pending. All are JSON-safe; no NaNs signal success.
    """
    output = dict(schema_version="1", analysis_id=protocol.get("analysis_id") if isinstance(protocol, dict) else None,
                  status="protocol_pending", protocol_sha256=_digest(protocol), input_sha256=_digest(records),
                  protocol_gaps=[], selection=[], selected_estimates=[], result=None,
                  forest_data=[], sensitivity_results=[],
                  counts={"input": len(records), "selected": 0, "excluded": 0, "review": 0,
                          "independent_units": 0})
    try:
        p = AnalysisProtocol.model_validate(protocol)
    except ValidationError as exc:
        output["protocol_gaps"] = [".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors()]
        return output
    gaps = output["protocol_gaps"]
    unit = _UNITS.get(p.unit.strip().lower())
    if unit is None:
        gaps.append("Unsupported canonical unit")
    count_method = p.method in {"binomial","ft_dl_miller_harmonic"} or p.method.startswith("logit_")
    if p.method not in METHOD_REGISTRY:
        gaps.append("Unsupported method: " + p.method)
    if p.method in {"fixed", "random", "reml"}:
        if p.uncertainty_rules is None:
            gaps.append("Inverse-variance methods require explicit uncertainty_rules")
        if p.estimate_measure.casefold() in {"count_only", "median"}:
            gaps.append("Median/count-only input requires an explicit median/binomial/logit method")
    if count_method:
        if p.binomial_rules is None:
            gaps.append("Counts-based synthesis requires binomial_rules")
        elif p.method in {"binomial","ft_dl_miller_harmonic"} and p.binomial_rules.zero_event_policy != "none":
            gaps.append("Aggregate binomial intervals use uncorrected counts; continuity is a logit-method option")
        elif p.binomial_rules.zero_event_policy == "continuity" and p.binomial_rules.continuity_correction is None:
            gaps.append("Continuity policy requires an explicit positive correction")
        if unit and unit[0] != "proportion":
            gaps.append("Counts-based synthesis requires proportion or percentage unit")
    if (p.interval_method != "normal" or p.prediction_interval) and p.method not in {"random", "reml", "logit_random", "logit_reml"}:
        gaps.append("HK/prediction intervals require an explicitly supported random-effects method")
    if p.log_transform and p.method not in {"fixed", "random", "reml"}:
        gaps.append("log_transform is only applicable to inverse-variance methods")
    for field, rule in p.filters.items():
        error = _filter_error(rule)
        if error:
            gaps.append(f"Invalid filter for {field}: {error}")
    sensitivity_names = [v.name for v in p.sensitivity]
    if len(sensitivity_names) != len(set(sensitivity_names)):
        gaps.append("Sensitivity names must be unique")
    if p.independence.unit == "record_id" and not p.independence.assert_independent_reports:
        gaps.append("record_id independence requires assert_independent_reports=true; report IDs alone do not prove independence")
    if p.independence.multiple_estimates == "select_ids" and not p.independence.selected_estimate_ids:
        gaps.append("select_ids requires a nonempty selected_estimate_ids list")
    ids = [str(r.get("estimate_id") or f"input:{i+1}") for i, r in enumerate(records)]
    unknown_ids = set(p.independence.selected_estimate_ids) - set(ids)
    if unknown_ids:
        gaps.append("Selection IDs are absent from input: " + ", ".join(sorted(unknown_ids)))
    if gaps:
        return output
    duplicate_ids = {k for k, n in Counter(ids).items() if n > 1}
    selected = []
    groups = defaultdict(list)
    for i, source in enumerate(records):
        estimate_id = ids[i]
        decision = dict(estimate_id=estimate_id, input_index=i, decision="review", reasons=[], transformations=[])
        output["selection"].append(decision)
        def stop(reason, status="review"):
            decision.update(decision=status, reasons=[reason])
        if estimate_id in duplicate_ids:
            stop("duplicate_estimate_id")
            continue
        if p.exclude_flagged_ineligible and _false(source.get("eligible_for_target")):
            stop("explicitly_ineligible_for_target", "exclude")
            continue
        if str(source.get("parameter_type", "")).strip().casefold() != p.parameter_type.casefold():
            stop("parameter_type_out_of_scope", "exclude")
            continue
        if str(source.get("estimate_measure", "")).strip().casefold() not in {m.casefold() for m in (p.input_measures or [p.estimate_measure])}:
            stop("estimate_measure_out_of_scope", "exclude")
            continue
        mismatch = False
        for key, expected in p.filters.items():
            if _missing(source.get(key)):
                stop("missing_protocol_filter_field:" + key)
                mismatch = True
                break
            match = _matches_filter(source.get(key), expected)
            if match is None:
                stop("uninterpretable_protocol_filter_field:" + key)
                mismatch = True
                break
            if not match:
                stop("protocol_filter_mismatch:" + key, "exclude")
                mismatch = True
                break
        if mismatch:
            continue
        if p.independence.multiple_estimates == "select_ids" and estimate_id not in p.independence.selected_estimate_ids:
            stop("not_in_explicit_selection", "exclude")
            continue
        issues = _review_issues(source)
        if issues:
            stop("unresolved_coding_evidence:" + ";".join(issues))
            continue
        identity = source.get(p.independence.unit)
        if _missing(identity):
            stop("missing_independence_identity:" + p.independence.unit)
            continue
        raw = {k: source.get(k) for k in ("point_estimate", "unit", "uncertainty_type", "uncertainty_level", "uncertainty_low", "uncertainty_high", "sd", "se")}
        row = dict(source, estimate_id=estimate_id, raw_values=raw, source_raw=_safe(dict(source)), source_record_sha256=_digest(source))
        if count_method:
            br = p.binomial_rules
            events, denominator = _number(source.get(br.numerator_field)), _number(source.get(br.denominator_field))
            if events is None or denominator is None or denominator <= 0 or not 0 <= events <= denominator or not events.is_integer() or not denominator.is_integer():
                stop("missing_or_invalid_matched_binomial_counts")
                continue
            events, denominator = int(events), int(denominator)
            row.update(_events=events, _denominator=denominator, point_estimate=events / denominator / unit[1], unit=p.unit)
            decision["transformations"].append({"method": "reported_matched_counts_to_proportion", "events": events, "denominator": denominator,
                                                "formula": "events / denominator / canonical_unit_factor", "canonical_unit_factor": unit[1]})
            if p.method.startswith("logit_"):
                failures = denominator - events
                correction = br.continuity_correction if (events == 0 or failures == 0) and br.zero_event_policy == "continuity" else 0.0
                if events == 0 or failures == 0:
                    if not correction:
                        stop("zero_event_logit_requires_explicit_continuity_policy")
                        continue
                    decision["transformations"].append({"method": "boundary_cell_continuity_correction", "events": events, "non_events": failures, "added_to_each_cell": correction})
                row.update(_logit=math.log((events + correction) / (failures + correction)),
                           _logit_se=math.sqrt(1 / (events + correction) + 1 / (failures + correction)))
                decision["transformations"].append({"method": "log_odds_with_binomial_delta_se", "logit": row["_logit"], "se": row["_logit_se"]})
        else:
            value = _number(source.get("point_estimate"))
            if value is None or (p.log_transform and value <= 0):
                stop("missing_nonfinite_or_nonpositive_log_estimate")
                continue
            source_unit = _UNITS.get(str(source.get("unit", "")).strip().lower())
            if source_unit is None or source_unit[0] != unit[0]:
                stop("unknown_or_incompatible_unit")
                continue
            factor = source_unit[1] / unit[1]
            if factor != 1 and not p.allow_unit_conversion:
                stop("unit_conversion_not_authorized")
                continue
            if source_unit[0] == "proportion" and not 0 <= value * source_unit[1] <= 1:
                stop("proportion_outside_valid_range")
                continue
            row.update(point_estimate=value * factor, unit=p.unit)
            for field in ("uncertainty_low", "uncertainty_high", "sd"):
                if _number(source.get(field)) is not None:
                    row[field] = _number(source[field]) * factor
            if p.method != "median":
                if source_unit[0] == "proportion" and str(source.get("uncertainty_type", "")).upper() == "CI":
                    bounds = [_number(source.get(k)) for k in ("uncertainty_low", "uncertainty_high")]
                    if any(v is not None and not 0 <= v * source_unit[1] <= 1 for v in bounds):
                        stop("proportion_ci_outside_valid_range")
                        continue
                se, derivation, reason = _se(source, p.uncertainty_rules)
                if reason or se is None or not math.isfinite(se) or se <= 0:
                    stop(reason or "invalid_se")
                    from .diagnostics import se_derivation_candidates
                    decision["derivation_candidates"] = se_derivation_candidates(source)
                    continue
                row["se"] = se * factor
                decision["transformations"].append({"field": "se", "derivation": derivation})
            if factor != 1:
                decision["transformations"].append({"method": "linear_unit_conversion", "from": source.get("unit"), "to": p.unit, "factor": factor,
                                                    "point_before": value, "point_after": value * factor})
        decision.update(decision="select", reasons=["protocol_requirements_met"])
        groups[str(identity)].append((row, decision))
    for identity, members in groups.items():
        if len(members) > 1:
            for row, decision in members:
                decision.update(decision="review", reasons=["multiple_estimates_for_independent_unit:" + identity])
        else:
            selected.append(members[0][0])
    counts = output["counts"]
    counts.update(selected=len(selected), excluded=sum(d["decision"] == "exclude" for d in output["selection"]),
                  review=sum(d["decision"] == "review" for d in output["selection"]), independent_units=len(selected))
    output["selected_estimates"] = _safe(selected)
    if len(selected) < p.minimum_estimates:
        output.update(status="not_computable", reason="insufficient_eligible_independent_estimates")
        return output
    try:
        result, forest = calculate(selected, p, unit[1])
    except (ArithmeticError, ValueError) as exc:
        output.update(status="not_computable", reason="statistical_backend_error:" + type(exc).__name__)
        return output
    valid = _number(result.get("pooled_mean")) is not None
    if p.method != "median":
        valid = valid and all(_number(result.get(k)) is not None for k in ("ci_lower", "ci_upper"))
    if not valid or result.get("n_studies") != len(selected):
        output.update(status="not_computable", reason="statistical_backend_produced_invalid_result")
        return output
    if unit[0] == "proportion" and not all(0 <= result[k] * unit[1] <= 1 for k in ("pooled_mean", "ci_lower", "ci_upper") if result.get(k) is not None):
        output.update(status="not_computable", reason="normal_interval_outside_proportion_bounds")
        return output
    source_map = {r["estimate_id"]: r for r in selected}
    for row in forest:
        row["source_record_sha256"] = source_map[row["estimate_id"]]["source_record_sha256"]
        row["protocol_sha256"] = output["protocol_sha256"]
    output.update(status="partial" if counts["review"] else "single_estimate" if len(selected) == 1 else "complete", result=_safe(result), forest_data=_safe(forest))
    specifications = list(p.sensitivity)
    if p.leave_one_out:
        specifications.extend(SensitivitySpec(name="leave_one_out:" + r["estimate_id"], exclude_estimate_ids=[r["estimate_id"]]) for r in selected)
    available = {r["estimate_id"] for r in selected}
    for spec in specifications:
        subset = [r for r in selected if r["estimate_id"] not in spec.exclude_estimate_ids]
        item = dict(name=spec.name, excluded_estimate_ids=spec.exclude_estimate_ids, input_estimate_ids=[r["estimate_id"] for r in subset], status="not_computable", result=None)
        method = spec.method or p.method
        same_family = method in {"fixed", "random", "reml"} and p.method in {"fixed", "random", "reml"} or method in {"logit_fixed", "logit_random", "logit_reml"} and p.method.startswith("logit_") or method == p.method
        if set(spec.exclude_estimate_ids) - available:
            item["reason"] = "unknown_or_unselected_sensitivity_exclusion"
        elif not same_family or method not in METHOD_REGISTRY:
            item["reason"] = "incompatible_sensitivity_method"
        elif len(subset) < p.minimum_estimates:
            item["reason"] = "insufficient_eligible_independent_estimates"
        else:
            try:
                calculated, _ = calculate(subset, p.model_copy(update={"method": method}), unit[1])
                if _number(calculated.get("pooled_mean")) is None:
                    raise ValueError("Non-finite result")
                item.update(status="single_estimate" if len(subset) == 1 else "complete", result=_safe(calculated))
            except (ArithmeticError, ValueError) as exc:
                item["reason"] = "statistical_backend_error:" + type(exc).__name__
        output["sensitivity_results"].append(item)
    if p.influence_diagnostics:
        from .diagnostics import influence_diagnostics
        output["influence_diagnostics"] = _safe(influence_diagnostics(selected,p,unit[1],result))
    if p.publication_bias:
        from .diagnostics import publication_bias_diagnostics
        output["publication_bias"] = _safe(publication_bias_diagnostics(selected,p))
    if p.llm_selection or p.llm_report:
        from .assistance import assist_synthesis
        assist_synthesis(output, p.model_dump(), invoke=llm_invoke)
    return output


def _filter_scalar(value):
    return isinstance(value, (str, bool, int, float)) and (not isinstance(value, float) or math.isfinite(value))


def _filter_bound(value):
    """Return typed finite numeric or ISO-date bound, rejecting boolean coercion."""
    if isinstance(value, bool):
        return None
    number = _number(value)
    if number is not None:
        return "number", number
    if isinstance(value, str):
        from datetime import date
        try:
            return "date", date.fromisoformat(value)
        except ValueError:
            pass
    return None


def _filter_error(rule):
    if not isinstance(rule, dict):
        values = rule if isinstance(rule, list) else [rule]
        return None if values and all(_filter_scalar(v) for v in values) else "exact filters require a scalar or nonempty scalar list"
    if not rule or set(rule) - {"eq", "in", "not_in", "gte", "lte"}:
        return "unsupported or empty filter operators"
    for operator, operand in rule.items():
        if operator == "eq" and not _filter_scalar(operand):
            return "eq requires a scalar operand"
        if operator in {"in", "not_in"} and (not isinstance(operand, list) or not operand or any(not _filter_scalar(v) for v in operand)):
            return "in/not_in require nonempty scalar lists"
        if operator in {"gte", "lte"} and _filter_bound(operand) is None:
            return "bounds require a finite number or ISO date"
    if "gte" in rule and "lte" in rule:
        low, high = _filter_bound(rule["gte"]), _filter_bound(rule["lte"])
        if low[0] != high[0] or low[1] > high[1]:
            return "bounds have incompatible types or reversed order"
    return None


def _matches_filter(value, rule):
    """Explicit field matches and numeric/ISO date bounds; never infer a stratum."""
    error = _filter_error(rule)
    if error:
        raise ValueError(error)
    if not isinstance(rule, dict):
        return value in (rule if isinstance(rule, list) else [rule])
    for operator, expected in rule.items():
        if operator == "eq" and value != expected:
            return False
        if operator == "in" and value not in expected:
            return False
        if operator == "not_in" and value in expected:
            return False
        if operator in {"gte", "lte"}:
            left, right = _filter_bound(value), _filter_bound(expected)
            if left is None or right is None or left[0] != right[0]:
                return None
            left, right = left[1], right[1]
            if operator == "gte" and left < right or operator == "lte" and left > right:
                return False
    return True


def run_analyses(records: list[dict], protocols: list[dict], output_dir=None, *, llm_invoke=None):
    """Run independent analyses; optional directory returns (summary, artifact_paths)."""
    ids = [p.get("analysis_id") for p in protocols]
    if len(ids) != len(set(ids)):
        raise ValueError("analysis_id must be unique across protocols")
    results = [run_synthesis(records, p, llm_invoke=llm_invoke) for p in protocols]
    selection = [dict(row, analysis_id=result["analysis_id"]) for result in results for row in result["selection"]]
    summary = {"schema_version": "1", "analysis_id": "multiple_analyses", "status": "complete" if results and all(r["status"] in {"complete", "single_estimate"} for r in results) else "partial",
               "analyses": results, "n_analyses": len(results), "n_computable": sum(r["result"] is not None for r in results),
               "selection": selection, "selected_estimates": [], "result": None, "protocol_gaps": [],
               "counts": {"input": len(records), "analyses": len(results), "computable_analyses": sum(r["result"] is not None for r in results)},
               "input_sha256": _digest(records), "protocol_sha256": _digest(protocols)}
    return (summary, write_synthesis_artifacts(summary, output_dir)) if output_dir is not None else summary


def write_synthesis_artifacts(result: dict, output_dir: Path | str) -> dict[str, str]:
    """Write the result, decision ledger and an artifact-grounded short report."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    if "analyses" in result:
        artifacts = {}
        lines = ["# Multiple analyses", "", "Status: " + result["status"], ""]
        for index, analysis in enumerate(result["analyses"]):
            # Numeric directory avoids path traversal through protocol identifiers.
            relative = f"analysis_{index + 1:03d}"
            child = write_synthesis_artifacts(analysis, root / relative)
            artifacts.update({relative + "/" + k: v for k, v in child.items()})
            lines.append(f"- {analysis['analysis_id']}: {analysis['status']} ([report]({relative}/report.md))")
        (root / "synthesis_result.json").write_text(json.dumps(_safe(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        (root / "analysis_selection.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in result["selection"]))
        (root / "report.md").write_text("\n".join(lines) + "\n")
        return {**artifacts, "synthesis_result": str(root / "synthesis_result.json"), "analysis_selection": str(root / "analysis_selection.jsonl"), "synthesis_report": str(root / "report.md")}
    # Remove only this writer's stale derived artifacts when a rerun cannot
    # regenerate them; old plots must not masquerade as the new result.
    if not result.get("forest_data"):
        for name in ("study_weights.jsonl", "forest.png", "forest.pdf"):
            (root / name).unlink(missing_ok=True)
    if not result.get("sensitivity_results"):
        (root / "sensitivity_results.json").unlink(missing_ok=True)
    paths = {"synthesis_result": root / "synthesis_result.json", "analysis_selection": root / "analysis_selection.jsonl", "synthesis_report": root / "report.md"}
    paths["synthesis_result"].write_text(json.dumps(_safe(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    paths["analysis_selection"].write_text("".join(json.dumps(_safe(row), ensure_ascii=False, allow_nan=False) + "\n" for row in result["selection"]), encoding="utf-8")
    text = [f"# Analysis {result.get('analysis_id') or '(protocol pending)'}", "", f"Status: {result['status']}", "", "Counts: " + json.dumps(result["counts"], ensure_ascii=False), ""]
    if result.get("result"):
        r = result["result"]
        if "tau2" in r:
            text.extend([f"Heterogeneity: Q={r.get('Q')}; df={r.get('df')}; I²={r.get('i2')}%; τ²={r.get('tau2')} (analysis scale: {r.get('analysis_scale','original')}).", ""])
        if r.get("prediction_interval"):
            text.extend(["Prediction interval: " + json.dumps(r["prediction_interval"],ensure_ascii=False), ""])
        text.extend([f"Estimate: {r['pooled_mean']} {r['unit']}", f"Interval: {r.get('ci_level')} {r.get('ci_type')} [{r.get('ci_lower')}, {r.get('ci_upper')}]", f"Method: {r['method_detail']}; independent units: {r['n_independent_units']}", "", "Numeric source: synthesis_result.json#/result", ""])
    else:
        text.extend(["No synthesis value is available. This does not establish absence of an effect.", result.get("reason", ""), ""])
    if result["protocol_gaps"]:
        text.extend(["Protocol gaps:", *["- " + g for g in result["protocol_gaps"]], ""])
    candidates=[{"estimate_id":row["estimate_id"],"reasons":row["reasons"],"options":row["derivation_candidates"]}
                for row in result["selection"] if row.get("derivation_candidates")]
    if candidates:
        candidate_path=root/"se_derivation_candidates.json"
        candidate_path.write_text(json.dumps(candidates,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
        paths["se_derivation_candidates"]=candidate_path
        text.extend(["Uncertainty derivation candidates (not applied; require explicit protocol approval):",json.dumps(candidates,ensure_ascii=False,indent=2),""])
    else:
        (root/"se_derivation_candidates.json").unlink(missing_ok=True)
    if result.get("forest_data"):
        weights = root / "study_weights.jsonl"
        weights.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in result["forest_data"]))
        paths["study_weights"] = weights
        from .plots import write_forest_plot
        paths.update(write_forest_plot(result, root))
    if result.get("sensitivity_results"):
        sensitivity = root / "sensitivity_results.json"
        sensitivity.write_text(json.dumps(_safe(result["sensitivity_results"]), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        paths["sensitivity_results"] = sensitivity
    for name in ("influence_diagnostics", "publication_bias"):
        if result.get(name):
            path = root / (name + ".json")
            path.write_text(json.dumps(_safe(result[name]),ensure_ascii=False,indent=2,allow_nan=False)+"\n")
            paths[name]=path
            text.extend([name + ": " + result[name]["status"], ""])
        else:
            (root/(name+".json")).unlink(missing_ok=True)
    from .plots import write_diagnostic_plots
    paths.update(write_diagnostic_plots(result,root))
    if result.get("llm_report", {}).get("status") == "accepted":
        text.extend(["", "Validated model explanation:", *[c["text"] for c in result["llm_report"]["claims"]]])
    if result["counts"]["review"]:
        text.append("Some inputs require review and were not included; the result has incomplete eligible-input coverage.")
    paths["synthesis_report"].write_text("\n".join(text), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}
