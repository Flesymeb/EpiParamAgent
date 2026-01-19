from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator


class CodingSheetRecord(BaseModel):
    """Legacy coding sheet schema for early numeracy meta-analysis.

    NOTE: This is the old hardcoded schema. For new projects, use config-based
    dynamic models via load_config() and get_model().

    This schema is kept for backward compatibility and testing purposes.
    """

    # Core fields (match EN.xlsx semantics - psychology domain)
    study: str
    country: str
    student_type: str

    gender_boy_percent: Optional[float] = Field(default=None, ge=0, le=100)
    age_t1: Optional[float] = Field(default=None, gt=0, le=25)
    age_t2: Optional[float] = Field(default=None, gt=0, le=25)
    interval: Optional[float] = Field(default=None, gt=0, le=20)
    n: Optional[int] = Field(default=None, gt=0)

    early_numeracy_measurements: str
    early_numeracy_skills: str
    later_mathematics_measures: str
    mathematics_domains: str

    correlations: Optional[float] = Field(default=None, ge=-1, le=1)

    # Evidence (optional): link extracted values to sources.
    # For chunked mode: use evidence_chunk_ids
    # For full_context mode: use evidence_locations
    evidence_chunk_ids: Optional[List[int]] = Field(default=None, max_length=5)
    evidence_locations: Optional[List[str]] = Field(default=None, max_length=5)
    evidence_quotes: Optional[List[str]] = Field(default=None, max_length=5)

    # Extraction mode tracking
    extraction_mode: Optional[str] = None  # "chunked" | "full_context"

    # Metadata
    source_id: Optional[str] = None
    source_doi: Optional[str] = None
    source_database: Optional[str] = None

    extractor_model: Optional[str] = None
    extraction_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )

    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    review_notes: Optional[str] = None

    @field_validator(
        "study",
        "country",
        "student_type",
        "early_numeracy_measurements",
        "early_numeracy_skills",
        "later_mathematics_measures",
        "mathematics_domains",
    )
    @classmethod
    def _non_empty_str(cls, v: str):
        v = (v or "").strip()
        if not v:
            raise ValueError("field must be a non-empty string")
        return v

    @model_validator(mode="after")
    def _quality(self):
        confidence = 1.0
        notes: list[str] = []

        # Critical fields
        if self.correlations is None:
            confidence -= 0.25
            notes.append("Missing correlation")
        if self.n is None:
            confidence -= 0.10
            notes.append("Missing sample size")

        if self.age_t1 is not None and self.age_t2 is not None:
            if self.age_t2 <= self.age_t1:
                confidence -= 0.25
                notes.append("Age T2 <= Age T1")
            if self.interval is not None:
                expected = self.age_t2 - self.age_t1
                if abs(expected - self.interval) > 0.5:
                    confidence -= 0.10
                    notes.append("Interval inconsistent with ages")

        if self.correlations is not None and abs(self.correlations) > 0.95:
            confidence -= 0.15
            notes.append("Unusually high |r|")

        # Evidence validation - check based on extraction mode
        has_chunk_ids = (
            self.evidence_chunk_ids is not None and len(self.evidence_chunk_ids) > 0
        )
        has_locations = (
            self.evidence_locations is not None and len(self.evidence_locations) > 0
        )

        if not has_chunk_ids and not has_locations:
            # No evidence provided in either mode
            confidence -= 0.10
            notes.append("Missing evidence references")

        confidence = max(0.0, min(1.0, confidence))
        self.extraction_confidence = confidence

        if confidence < 0.7:
            self.needs_review = True

        if notes:
            existing = (self.review_notes or "").strip()
            merged = "; ".join(notes)
            self.review_notes = (
                (existing + "; " + merged).strip("; ") if existing else merged
            )

        return self


class ExtractionResult(BaseModel):
    paper_id: str
    paper_title: str
    status: str = "success"  # success|failed
    errors: list[str] = Field(default_factory=list)
    raw_llm_output: Optional[str] = None
    records: list[CodingSheetRecord] = Field(default_factory=list)


class ExtractionBatch(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None
    total_papers: int
    successful_papers: int
    failed_papers: int
    total_records: int
    needs_review: int
    results: list[ExtractionResult]


@dataclass
class Paper:
    id: str
    title: str
    abstract: str = ""
    full_text: str = ""
    doi: Optional[str] = None
    year: Optional[int] = None
    source: Optional[str] = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Paper":
        return Paper(
            id=str(d.get("id") or d.get("pmid") or d.get("paper_id") or ""),
            title=str(d.get("title") or ""),
            abstract=str(d.get("abstract") or ""),
            full_text=str(d.get("full_text") or d.get("content") or ""),
            doi=d.get("doi"),
            year=d.get("year"),
            source=d.get("source") or d.get("database"),
        )
