"""Structured output models for epidemiology screening decisions."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


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
    transmission_metric: DimensionAssessment = Field(
        description="传播指标: 是否报告传播强度或再生数相关指标"
    )

    llm_suggest: str = Field(
        description="strong_candidate / possible_candidate / unlikely_candidate"
    )
    overall_score: Optional[int] = Field(
        default=None,
        description="整体相关性评分 0-4，由系统自动计算加权平均（Disease 30% + Transmission 30% + Evidence 25% + Population 10% + Location 5%）",
    )
    overall_justification: str = Field(description="整体评估理由，2-3句话")

    @model_validator(mode="after")
    def calculate_overall_score(self):
        weighted_score = (
            0.30 * self.disease_relevance.score
            + 0.30 * self.transmission_metric.score
            + 0.25 * self.original_evidence.score
            + 0.10 * self.population_relevance.score
            + 0.05 * self.location_relevance.score
        )
        self.overall_score = round(weighted_score)
        return self
