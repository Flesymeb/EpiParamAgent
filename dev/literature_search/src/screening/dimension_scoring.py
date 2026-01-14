"""Multi-dimensional relevance scoring for epidemiological literature screening.

This module provides a structured approach to evaluate papers across multiple
dimensions rather than binary include/exclude decisions, enabling flexible
threshold strategies and prioritization for manual review.
"""

from __future__ import annotations

from typing import Literal, Dict, Optional
from pydantic import BaseModel, Field, field_validator


# Type alias for dimension scores
DimensionScore = Literal["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]


class EpiDimensionScores(BaseModel):
    """Multi-dimensional screening scores for epidemiological parameter studies.

    Evaluates papers across 7 dimensions critical for COVID-19 epidemiology
    meta-analysis, particularly for time-interval parameters (serial interval,
    isolation delay, etc.).
    """

    # Individual dimension scores
    disease_relevance: DimensionScore = Field(
        description="Relevance to COVID-19 epidemiology and human transmission"
    )
    original_data: DimensionScore = Field(
        description="Contains original empirical data (not modeling/simulation)"
    )
    population_level: DimensionScore = Field(
        description="Population-level study vs individual case report"
    )
    parameter_availability: DimensionScore = Field(
        description="Target epidemiological parameters are reported"
    )
    statistical_usability: DimensionScore = Field(
        description="Statistical data quality and completeness (CI/SD/uncertainty)"
    )
    design_relevance: DimensionScore = Field(
        description="Study design appropriate for parameter estimation"
    )
    parameter_alignment: DimensionScore = Field(
        description="Study explicitly aims to estimate target parameters"
    )

    # Rationales (brief explanations for each dimension)
    rationales: Optional[Dict[str, str]] = Field(
        default=None,
        description="Brief explanations for each dimension score (<50 tokens each)",
    )

    # Aggregated outputs
    overall_score: Optional[float] = Field(
        default=None,
        description="Weighted overall relevance score (0-1)",
        ge=0.0,
        le=1.0,
    )
    recommendation: Optional[Literal["INCLUDE", "MAYBE", "EXCLUDE"]] = Field(
        default=None,
        description="Final screening recommendation based on dimension scores",
    )
    confidence: Optional[float] = Field(
        default=None,
        description="LLM's confidence in the assessment (0-1)",
        ge=0.0,
        le=1.0,
    )

    def calculate_overall_score(
        self, weights: Optional[Dict[str, float]] = None
    ) -> float:
        """Calculate weighted overall score from dimension scores.

        Args:
            weights: Custom weights for each dimension. If None, uses default
                weights that prioritize disease relevance and data originality.

        Returns:
            Weighted score between 0 and 1.
        """
        # Default weights: disease relevance and original data are critical
        if weights is None:
            weights = {
                "disease_relevance": 0.20,  # Critical
                "original_data": 0.20,  # Critical
                "population_level": 0.15,  # Important
                "parameter_availability": 0.15,  # Important
                "statistical_usability": 0.10,  # Moderate
                "design_relevance": 0.10,  # Moderate
                "parameter_alignment": 0.10,  # Moderate
            }

        # Score mapping
        score_map = {
            "HIGH": 1.0,
            "MEDIUM": 0.5,
            "LOW": 0.0,
            "UNCERTAIN": 0.0,  # Treat uncertain as low for scoring
        }

        weighted_sum = 0.0
        for dimension, weight in weights.items():
            dimension_value = getattr(self, dimension)
            score = score_map.get(dimension_value, 0.0)
            weighted_sum += score * weight

        self.overall_score = weighted_sum
        return weighted_sum

    def calculate_recommendation(
        self, high_threshold: float = 0.70, maybe_threshold: float = 0.40
    ) -> Literal["INCLUDE", "MAYBE", "EXCLUDE"]:
        """Calculate recommendation based on overall score and critical dimensions.

        Args:
            high_threshold: Score threshold for INCLUDE (default 0.70)
            maybe_threshold: Score threshold for MAYBE vs EXCLUDE (default 0.40)

        Returns:
            Recommendation: INCLUDE, MAYBE, or EXCLUDE
        """
        # Ensure overall_score is calculated
        if self.overall_score is None:
            self.calculate_overall_score()

        # Critical exclusion criteria
        if self.disease_relevance == "LOW":
            self.recommendation = "EXCLUDE"
            return "EXCLUDE"

        if self.original_data == "LOW":
            self.recommendation = "EXCLUDE"
            return "EXCLUDE"

        # Score-based recommendation
        if self.overall_score >= high_threshold:
            self.recommendation = "INCLUDE"
        elif self.overall_score >= maybe_threshold:
            self.recommendation = "MAYBE"
        else:
            self.recommendation = "EXCLUDE"

        return self.recommendation

    def get_dimension_summary(self) -> Dict[str, any]:
        """Get a summary dict of all dimension scores for export.

        Returns:
            Dict with dimension names as keys and scores as values.
        """
        return {
            "disease_relevance": self.disease_relevance,
            "original_data": self.original_data,
            "population_level": self.population_level,
            "parameter_availability": self.parameter_availability,
            "statistical_usability": self.statistical_usability,
            "design_relevance": self.design_relevance,
            "parameter_alignment": self.parameter_alignment,
            "overall_score": self.overall_score,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
        }

    def get_failed_dimensions(self) -> list[str]:
        """Get list of dimensions that scored LOW.

        Returns:
            List of dimension names with LOW scores.
        """
        failed = []
        for dim in [
            "disease_relevance",
            "original_data",
            "population_level",
            "parameter_availability",
            "statistical_usability",
            "design_relevance",
            "parameter_alignment",
        ]:
            if getattr(self, dim) == "LOW":
                failed.append(dim)
        return failed

    def get_high_dimensions(self) -> list[str]:
        """Get list of dimensions that scored HIGH.

        Returns:
            List of dimension names with HIGH scores.
        """
        high = []
        for dim in [
            "disease_relevance",
            "original_data",
            "population_level",
            "parameter_availability",
            "statistical_usability",
            "design_relevance",
            "parameter_alignment",
        ]:
            if getattr(self, dim) == "HIGH":
                high.append(dim)
        return high
