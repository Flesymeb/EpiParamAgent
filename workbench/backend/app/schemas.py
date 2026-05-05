from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunSummary(BaseModel):
    id: str
    label: str
    module: str
    topic: str | None = None
    config: str | None = None
    timestamp_utc: str | None = None
    status: str = "ready"
    screened_csv: str | None = None
    manifest_path: str | None = None


class MetricSummary(BaseModel):
    label: str
    value: int


class CountItem(BaseModel):
    label: str
    count: int


class ConfusionMatrix(BaseModel):
    tp: int
    fp: int
    fn: int
    tn: int
    recall: float
    precision: float
    specificity: float
    accuracy: float


class ScreeningRunDetail(BaseModel):
    run: dict[str, Any]
    metrics: list[MetricSummary]
    decision_counts: list[CountItem]
    stage_counts: list[CountItem]
    fulltext_counts: list[CountItem]
    confusion_matrix: ConfusionMatrix
    papers: list[dict[str, Any]] = Field(default_factory=list)
    report_preview: str = ""


class ExtractionRunDetail(BaseModel):
    run: dict[str, Any]
    metrics: list[MetricSummary]
    outputs: list[dict[str, Any]] = Field(default_factory=list)


class WorkbenchSummary(BaseModel):
    screening_runs: int
    extraction_runs: int
