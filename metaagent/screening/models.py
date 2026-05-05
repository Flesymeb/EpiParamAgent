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
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="置信度 0-1。反映各维度评分的信息充分程度。1.0=摘要直接覆盖所有维度，0.0=完全无法判断",
    )

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


class BinaryDecision(BaseModel):
    """Structured binary output for simple include/exclude screening."""

    include: bool = Field(
        description="Should this paper be included in the review? True=Include, False=Exclude"
    )
    justification: str = Field(description="Brief justification for the decision, 1-2 sentences")
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence in the decision. 1.0=highly confident, 0.0=complete guess.",
    )


class PECOElement(BaseModel):
    """Assessment for a single PECO element."""

    present: bool = Field(description="Whether evidence for this element was found in the text")
    justification: str = Field(description="Brief justification, 1-2 sentences")


class PECODecision(BaseModel):
    """Structured PECO framework output for epidemiological screening."""

    population: PECOElement = Field(description="P — Population: human subjects or human-derived data?")
    exposure: PECOElement = Field(description="E — Exposure: target disease/pathogen/risk factor?")
    comparison: PECOElement = Field(
        description="C — Comparison: comparison group or context? (Optional for descriptive epi)"
    )
    outcome: PECOElement = Field(description="O — Outcome: target epidemiological parameter reported?")

    include: bool = Field(
        description="Include decision: P AND E AND O must all be present (C optional). True=Include, False=Exclude."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the overall decision. 0.0-0.3=very uncertain, 0.7+=high confidence.",
    )
    justification: str = Field(description="Overall justification, 2-3 sentences summarizing key evidence")


def classify_binary_decision(decision: BinaryDecision) -> str:
    """Map binary include/exclude to the canonical candidate label."""
    return "strong_candidate" if decision.include else "unlikely_candidate"


def classify_peco_decision(decision: PECODecision) -> str:
    """Map PECO include/exclude to the canonical candidate label.

    Low-confidence includes are downgraded to possible_candidate.
    Low-confidence excludes are kept as unlikely_candidate.
    """
    if not decision.include:
        return "unlikely_candidate"
    if decision.confidence < 0.7:
        return "possible_candidate"
    return "strong_candidate"


def peco_confidence_from_elements(decision: PECODecision) -> float:
    """Derive confidence from per-element certainty.

    If the LLM didn't provide an overall confidence, estimate it from
    the number of elements that are definitively present vs uncertain.
    """
    elements = [decision.population, decision.exposure, decision.outcome]
    n_clear = sum(1 for e in elements if e.present)
    total = len(elements)
    # More elements present = higher confidence that inclusion is correct
    return round(n_clear / total, 2)


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
        "strong_full_text": "strong_full_text_mode",
    }
    default_map = {
        "title_abstract": "strict",
        "title_only": "lenient",
        "full_text": "standard",
        "possible_full_text": "filter_possible",
        "strong_full_text": "confirm_parameter",
    }
    key = policy_map.get(stage, "title_abstract_mode")
    return str((policies or {}).get(key, default_map.get(stage, "strict"))).strip().lower()


def resolve_stage2_evidence_floor(policies: dict[str, Any] | None) -> int:
    """Read stage2_evidence_floor from profile policies, defaulting to 1.

    SI profiles set this to 2 (require directly observed contact-pair data).
    R0/Rt profiles leave it at the default 1 (model-fitted aggregate data accepted).
    """
    return int((policies or {}).get("stage2_evidence_floor", 1))


def classify_screening_decision(
    decision: ScreeningDecision,
    *,
    thresholds: dict[str, Any] | None = None,
    stage_mode: str = "strict",
    evidence_floor: int = 1,
) -> str:
    """Map five-dimension scores to strong/possible/unlikely in code."""
    normalized = normalize_thresholds(thresholds)

    if _meets_threshold_block(decision, normalized["strong"]):
        return "strong_candidate"

    possible_block = _apply_stage_mode(normalized["possible"], stage_mode=stage_mode)
    if stage_mode == "confirm_parameter":
        return _classify_confirm_parameter(decision, possible_block, evidence_floor=evidence_floor)
    if stage_mode == "filter_possible":
        return _classify_possible_fulltext(decision, possible_block, evidence_floor=evidence_floor)

    if _meets_threshold_block(decision, possible_block):
        return "possible_candidate"

    return "unlikely_candidate"


def _classify_confirm_parameter(
    decision: ScreeningDecision,
    threshold_block: dict[str, int],
    *,
    evidence_floor: int = 1,
) -> str:
    """Stage-2 rule for STRONG candidates: conservative confirmation pass.

    Demote only when the full text provides clear evidence that:
    - the target parameter is entirely absent or cited-only (score <= 1), OR
    - evidence quality is below the profile-specific floor:
        SI profiles: floor=2 → demote model-fitted (evidence=2) papers
        R0 profiles: floor=1 → only demote purely theoretical papers (evidence≤1)
    """
    if decision.parameter_relevance.score <= 1:
        return "unlikely_candidate"
    if decision.original_evidence.score <= evidence_floor:
        return "unlikely_candidate"

    return "possible_candidate"


def _classify_possible_fulltext(
    decision: ScreeningDecision,
    threshold_block: dict[str, int],
    *,
    evidence_floor: int = 1,
) -> str:
    """Stage-2 rule for POSSIBLE candidates: active FP reduction pass.

    Demotion rules (any one is sufficient):
    - parameter_relevance <= 2  (weakly/not supported; or cited-only estimate)
    - original_evidence   <= evidence_floor  (below profile-specific threshold)
    - disease_relevance   <= 1  (clearly off-topic disease)
    """
    if decision.parameter_relevance.score <= 2:
        return "unlikely_candidate"
    if decision.original_evidence.score <= evidence_floor:
        return "unlikely_candidate"
    if decision.disease_relevance.score <= 1:
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
