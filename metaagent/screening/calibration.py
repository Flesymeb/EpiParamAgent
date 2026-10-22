"""Portable, explicitly trained screening routers; no training at inference."""

from __future__ import annotations

import math

DIMENSIONS = (
    "disease_relevance",
    "population_relevance",
    "location_relevance",
    "original_evidence",
    "parameter_relevance",
)


def screening_features(
    five_dim: dict, criteria: dict | None = None
) -> dict[str, float]:
    """Encode evidence states without paper identifiers or reference labels."""
    features = {}
    for name in DIMENSIONS:
        score = five_dim[name]["score"]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= score <= 4
        ):
            raise ValueError(f"Invalid screening score: {name}={score!r}")
        features[name] = float(score) / 4
    confidence = five_dim.get("confidence")
    features["confidence_missing"] = float(confidence is None)
    features["confidence"] = float(confidence) if confidence is not None else 0.5
    for tier in ("S", "P", "U"):
        features[f"tier:{tier}"] = float(five_dim.get("tier") == tier)
    if criteria is not None:
        categories = {
            "target_support": ("direct", "plausible", "none", "unknown"),
            "evidence_role": (
                "primary_empirical",
                "primary_model",
                "secondary",
                "other",
                "unknown",
            ),
            "decision": ("include", "exclude", "uncertain"),
        }
        for key in (
            "disease",
            "population",
            "target",
            "original_evidence",
            "restrictions",
        ):
            for status in ("met", "not_met", "unknown"):
                features[f"criterion:{key}:{status}"] = float(
                    criteria[key]["status"] == status
                )
        for key, values in categories.items():
            for value in values:
                features[f"{key}:{value}"] = float(criteria.get(key) == value)
    return features


def apply_router(features: dict[str, float], artifact: dict) -> tuple[float, int]:
    """Apply frozen logistic coefficients and an independently selected threshold.

    A returned score is a fitted model score, not a guaranteed correctness
    probability. Missing inputs fail explicitly instead of becoming negatives.
    """
    names = artifact["feature_names"]
    weights = [float(w) for w in artifact["coefficients"]]
    if len(names) != len(weights):
        raise ValueError("Router feature/coefficient lengths differ")
    threshold = float(artifact["threshold"])
    intercept = float(artifact["intercept"])
    if not names or len(set(names)) != len(names):
        raise ValueError("Router feature names must be nonempty and unique")
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Router threshold must be between zero and one")
    if not all(math.isfinite(v) for v in [intercept, *weights]):
        raise ValueError("Router coefficients must be finite")
    if any(name not in features for name in names):
        raise ValueError("Required router features are missing")
    values = [features[name] for name in names]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Router features must be finite")
    logit = intercept + sum(w * v for w, v in zip(weights, values))
    probability = (
        1 / (1 + math.exp(-logit))
        if logit >= 0
        else math.exp(logit) / (1 + math.exp(logit))
    )
    return probability, int(probability >= threshold)


def route_screened_record(record: dict, artifact: dict) -> dict:
    """Apply a 5D-only artifact to an existing CSV row, preserving raw decisions."""
    result = dict(record)
    result["llm_suggest_before_router"] = record.get("llm_suggest", "")
    result["router_method"] = artifact.get("method", "")
    if record.get("llm_suggest") == "error":
        result["router_status"] = "upstream_error"
        return result
    aliases = {
        "disease_relevance": "disease_score",
        "population_relevance": "population_score",
        "location_relevance": "location_score",
        "original_evidence": "evidence_score",
        "parameter_relevance": "parameter_score",
    }
    try:
        values = {key: {"score": float(record[name])} for key, name in aliases.items()}
        conf = record.get("confidence")
        values["confidence"] = (
            None
            if conf is None or str(conf).strip().lower() in {"", "none", "nan"}
            else float(conf)
        )
        values["tier"] = record.get("llm_tier")
        score, included = apply_router(screening_features(values), artifact)
    except (KeyError, ValueError, TypeError) as exc:
        result.update(
            llm_suggest="error", router_status="unresolved", router_error=str(exc)
        )
        return result
    result.update(
        llm_suggest="possible_candidate" if included else "unlikely_candidate",
        router_score=score,
        router_status="applied",
    )
    return result
