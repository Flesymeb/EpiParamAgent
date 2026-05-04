from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.schemas import WorkbenchSummary
from app.services import extraction_service, screening_service

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/summary", response_model=WorkbenchSummary)
def summary(root: str = Query(default="")) -> WorkbenchSummary:
    repo_root = _resolve_root(root)
    return WorkbenchSummary(
        screening_runs=len(screening_service.list_runs(repo_root)),
        extraction_runs=len(extraction_service.list_runs(repo_root)),
    )


@router.get("/screening/runs")
def list_screening_runs(root: str = Query(default="")) -> dict[str, object]:
    repo_root = _resolve_root(root)
    return {"items": screening_service.list_runs(repo_root)}


@router.get("/screening/runs/{run_id}")
def get_screening_run(run_id: str, root: str = Query(default="")) -> dict[str, object]:
    repo_root = _resolve_root(root)
    detail = screening_service.get_run(repo_root, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Screening run not found")
    return detail


@router.get("/screening/runs/{run_id}/papers")
def get_screening_run_papers(run_id: str, root: str = Query(default="")) -> dict[str, object]:
    repo_root = _resolve_root(root)
    detail = screening_service.get_run_papers(repo_root, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Screening run not found")
    return detail


@router.get("/extraction/runs")
def list_extraction_runs(root: str = Query(default="")) -> dict[str, object]:
    repo_root = _resolve_root(root)
    return {"items": extraction_service.list_runs(repo_root)}


@router.get("/extraction/runs/{run_id}")
def get_extraction_run(run_id: str, root: str = Query(default="")) -> dict[str, object]:
    repo_root = _resolve_root(root)
    detail = extraction_service.get_run(repo_root, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    return detail


def _resolve_root(root: str) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parents[5]
