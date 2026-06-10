from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.steps.coding import run_coding_step
from app.steps.pooling import run_pooling_step
from app.steps.query_gen import run_query_gen_step
from app.steps.retrieval import run_retrieval_step
from app.steps.screening import run_screening_step

StepRunner = Callable[[str, dict[str, Any]], str]


STEP_REGISTRY: dict[int, StepRunner] = {
    1: run_query_gen_step,
    2: run_retrieval_step,
    3: run_screening_step,
    4: run_coding_step,
    5: run_pooling_step,
}

STEP_NAMES: dict[int, str] = {
    1: "query_gen",
    2: "retrieval",
    3: "screening",
    4: "coding",
    5: "pooling",
}


def get_step_runner(step_no: int) -> StepRunner:
    return STEP_REGISTRY[step_no]


def get_step_name(step_no: int) -> str:
    return STEP_NAMES.get(step_no, f"step-{step_no}")
