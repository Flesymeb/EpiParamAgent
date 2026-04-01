"""Structured output models and code-side classification for screening."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

DEFAULT_THRESHOLDS: dict[str, dict[str, int]] = {
    "strong": {
        "disease_min": 4,
        "parameter_min": 4,
        "evidence_min": 3,
        "population_min": 2,
        "location_min": 2,
    },
    "possible": {
        "disease_min": 3,
        "parameter_min": 3,
        "evidence_min": 2,
        "population_min": 2,
        "location_min": 2,
    },
}

DIMENSION_KEY_MAP = {
    "disease_min": "disease_relevance",
    "parameter_min": "parameter_relevance",
    "evidence_min": "original_evidence",
    "population_min": "population_relevance",
    "location_min": "location_relevance",
}


class DimensionAssessment(BaseModel):
    """Assessment for a single screening dimension."""

    score: int = Field(
        description="相关性评分 0-4 (0=不相关, 1=基本不相关, 2=不确定/可能相关, 3=比较相关, 4=高度相关)"
    )
    justification: str = Field(description="简要理由，1-2句话")


class ScreeningDecision(BaseModel):
    """Structured multi-dimension output returned by the screening model."""

    disease_relevance: DimensionAssessment = Field(
        description="疾病相关性: 是否研究目标疾病(COVID-19/SARS-CoV-2)"
    )
    population_relevance: DimensionAssessment = Field(
        description="人群相关性: 是否关注人类（非纯动物或体外研究）"
    )
    location_relevance: DimensionAssessment = Field(
        description="地理相关性: 是否在真实地理环境中进行"
    )
    original_evidence: DimensionAssessment = Field(
        description="原始数据: 是否报告原始经验数据（非综述等）"
    )
    parameter_relevance: DimensionAssessment = Field(
        description="目标参数相关性: 是否报告研究问题所关注的参数"
    )

    overall_score: Optional[int] = Field(
        default=None,
        description="整体相关性评分 0-4，由系统自动计算加权平均（Disease 30% + Parameter 30% + Evidence 25% + Population 10% + Location 5%）",
    )
    overall_justification: str = Field(description="整体评估理由，2-3句话")

    @model_validator(mode="after")
    def calculate_overall_score(self):
        weighted_score = (
            0.30 * self.disease_relevance.score
            + 0.30 * self.parameter_relevance.score
            + 0.25 * self.original_evidence.score
            + 0.10 * self.population_relevance.score
            + 0.05 * self.location_relevance.score
        )
        self.overall_score = round(weighted_score)
        return self


def normalize_thresholds(raw_thresholds: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    """Merge partial YAML thresholds with canonical defaults."""
    merged = deepcopy(DEFAULT_THRESHOLDS)
    for bucket_name, default_values in DEFAULT_THRESHOLDS.items():
        overrides = (raw_thresholds or {}).get(bucket_name, {}) or {}
        for key, default_value in default_values.items():
            merged[bucket_name][key] = int(overrides.get(key, default_value))
    return merged


def resolve_stage_mode(stage: str, policies: dict[str, Any] | None) -> str:
    """Resolve stage-specific scoring mode from YAML policies."""
    policy_map = {
        "title_abstract": "title_abstract_mode",
        "title_only": "title_only_mode",
        "full_text": "full_text_mode",
        "possible_full_text": "possible_full_text_mode",
    }
    default_map = {
        "title_abstract": "strict",
        "title_only": "lenient",
        "full_text": "standard",
        "possible_full_text": "confirm_parameter",
        "strong_full_text": "confirm_parameter",
    }
    key = policy_map.get(stage, "title_abstract_mode")
    return str((policies or {}).get(key, default_map.get(stage, "strict"))).strip().lower()


def classify_screening_decision(
    decision: ScreeningDecision,
    *,
    thresholds: dict[str, Any] | None = None,
    stage_mode: str = "strict",
) -> str:
    """Map five-dimension scores to strong/possible/unlikely in code."""
    normalized = normalize_thresholds(thresholds)

    if _meets_threshold_block(decision, normalized["strong"]):
        return "strong_candidate"

    possible_block = _apply_stage_mode(normalized["possible"], stage_mode=stage_mode)
    if stage_mode == "confirm_parameter":
        return _classify_confirm_parameter(decision, possible_block)

    if _meets_threshold_block(decision, possible_block):
        return "possible_candidate"

    return "unlikely_candidate"


def _classify_confirm_parameter(
    decision: ScreeningDecision,
    threshold_block: dict[str, int],
) -> str:
    """Second-stage rule: demote a stage-1 possible paper only when full text shows parameter is clearly absent.

    Stage-1 already screened against profile-specific thresholds.  Stage-2 is a
    rescue/confirmation pass, so we only demote when the full text provides clear
    evidence that the target parameter or original empirical data is missing
    entirely (score <= 1).  A weak-but-present parameter (score == 2) is kept as
    possible_candidate — the doubt was already factored in by stage-1.
    """
    # Hard floor: demote only when full text clearly shows the parameter is absent.
    # Do NOT re-apply the profile-specific possible_min here; that is stage-1's job.
    DEMOTE_FLOOR = 1

    if decision.parameter_relevance.score <= DEMOTE_FLOOR:
        return "unlikely_candidate"
    if decision.original_evidence.score <= DEMOTE_FLOOR:
        return "unlikely_candidate"

    return "possible_candidate"


def _meets_threshold_block(
    decision: ScreeningDecision, threshold_block: dict[str, int]
) -> bool:
    for threshold_key, min_score in threshold_block.items():
        attr_name = DIMENSION_KEY_MAP[threshold_key]
        score = getattr(decision, attr_name).score
        if score < min_score:
            return False
    return True


def _apply_stage_mode(
    threshold_block: dict[str, int], *, stage_mode: str
) -> dict[str, int]:
    adjusted = dict(threshold_block)
    if stage_mode != "lenient":
        return adjusted

    relaxed_by_one = {
        "disease_min": 2,
        "parameter_min": 2,
        "evidence_min": 1,
        "population_min": 1,
        "location_min": 1,
    }
    for key, floor in relaxed_by_one.items():
        adjusted[key] = max(floor, adjusted[key] - 1)
    return adjusted
