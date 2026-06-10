from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "app.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    from app import models  # noqa: F401

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session

