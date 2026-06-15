from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# Webapp run storage lives in its own folder (separate from the repo's shared
# data/ and any pre-refactor runs). Override with METAAGENT_WEBAPP_DATA.
DATA_DIR = Path(os.environ.get("METAAGENT_WEBAPP_DATA", "data/webapp"))
DB_PATH = DATA_DIR / "app.db"
RUNS_DIR = DATA_DIR / "runs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def run_step_dir(run_id: str, step_no: int) -> Path:
    """Canonical artifact directory for a run's step (data/webapp/runs/...)."""
    return RUNS_DIR / run_id / f"step-{step_no}"


def init_db() -> None:
    from app import models  # noqa: F401

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
