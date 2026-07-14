from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime
    params: dict[str, Any]


class StepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    step_no: int
    name: str
    status: str
    artifact_path: str | None
    edited_artifact_path: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(BaseModel):
    run: RunRead
    steps: list[StepRead]


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    step_no: int | None
    ts: datetime
    level: str
    message: str


class StartStepResponse(BaseModel):
    run: RunRead
    step: StepRead


class StepTableRows(BaseModel):
    kind: Literal["table"]
    columns: list[str]
    rows: list[dict[str, str]]


class StepJsonRows(BaseModel):
    kind: Literal["json"]
    data: dict[str, Any]


StepRowsResponse = StepTableRows | StepJsonRows


class SaveEditedStepRequest(BaseModel):
    rows: list[dict[str, Any]] | None = None
    columns: list[str] | None = None
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_edit_payload(self) -> Self:
        has_rows = self.rows is not None
        has_data = self.data is not None
        if has_rows == has_data:
            raise ValueError("Provide exactly one of 'rows' or 'data'")
        if self.columns is not None and not has_rows:
            raise ValueError("'columns' can only be provided with 'rows'")
        return self
