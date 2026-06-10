from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class PipelineRun(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class PipelineStep(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="pipelinerun.id", index=True)
    step_no: int = Field(index=True)
    name: str
    status: str = Field(default="pending", index=True)
    artifact_path: str | None = None
    edited_artifact_path: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="pipelinerun.id", index=True)
    step_no: int | None = Field(default=None, index=True)
    ts: datetime = Field(default_factory=utc_now, index=True)
    level: str = Field(default="info", index=True)
    message: str

