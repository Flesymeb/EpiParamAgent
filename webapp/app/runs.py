from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from app.db import engine, get_session, run_step_dir
from app.events import event_hub, log_event, serialize_event
from app.models import PipelineRun, PipelineStep, RunEvent
from app.schemas import (
    RunDetail,
    RunEventRead,
    RunRead,
    SaveEditedStepRequest,
    StartStepResponse,
    StepJsonRows,
    StepRead,
    StepRowsResponse,
    StepTableRows,
)
from app.steps.registry import STEP_REGISTRY, get_step_name, get_step_runner

router = APIRouter()
MAX_STEP_ROWS = 1000


class CreateRunRequest(BaseModel):
    params: dict[str, Any] = PydanticField(default_factory=dict)


class StartStepRequest(BaseModel):
    # Per-step parameter overrides. Merged into the run's params (override wins)
    # so the configured fields persist and downstream steps inherit them.
    params: dict[str, Any] = PydanticField(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC)


def _get_step(session: Session, run_id: str, step_no: int) -> PipelineStep | None:
    return session.exec(
        select(PipelineStep).where(
            PipelineStep.run_id == run_id,
            PipelineStep.step_no == step_no,
        )
    ).one_or_none()


@router.post("/runs", response_model=RunRead)
def create_run(
    body: CreateRunRequest,
    session: Session = Depends(get_session),
) -> RunRead:
    run = PipelineRun(params=body.params)
    session.add(run)
    session.commit()
    session.refresh(run)
    log_event(session, run.id, None, "info", "Run created")
    session.refresh(run)
    return RunRead.model_validate(run)


@router.get("/runs", response_model=list[RunRead])
def list_runs(
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[RunRead]:
    query = select(PipelineRun).order_by(PipelineRun.created_at.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    runs = list(session.exec(query).all())
    return [RunRead.model_validate(run) for run in runs]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: str,
    session: Session = Depends(get_session),
) -> RunDetail:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = session.exec(
        select(PipelineStep)
        .where(PipelineStep.run_id == run_id)
        .order_by(PipelineStep.step_no)
    ).all()
    return RunDetail(
        run=RunRead.model_validate(run),
        steps=[StepRead.model_validate(step) for step in steps],
    )


@router.post(
    "/runs/{run_id}/steps/{step_no}/start",
    response_model=StartStepResponse,
)
def start_step(
    run_id: str,
    step_no: int,
    background_tasks: BackgroundTasks,
    body: StartStepRequest | None = None,
    session: Session = Depends(get_session),
) -> StartStepResponse:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if step_no < 1 or step_no > 5:
        raise HTTPException(status_code=400, detail="step_no must be between 1 and 5")
    if step_no not in STEP_REGISTRY:
        raise HTTPException(status_code=404, detail="Step is not implemented yet")

    step = _get_step(session, run_id, step_no)
    if step is not None and step.status == "running":
        raise HTTPException(status_code=409, detail="Step is already running")

    if step is None:
        step = PipelineStep(
            run_id=run_id,
            step_no=step_no,
            name=get_step_name(step_no),
        )

    # Merge per-step overrides into the run params (override wins) and persist,
    # so configured fields stick and downstream steps inherit them. Empty-string
    # values are dropped so a blank field falls back to the existing/default —
    # EXCEPT prompt-supplement keys, where an empty value must clear a prior
    # supplement rather than keep applying it.
    raw_overrides = (body.params if body else {}) or {}
    overrides: dict[str, Any] = {}
    for key, value in raw_overrides.items():
        is_blank = isinstance(value, str) and value.strip() == ""
        if is_blank and not key.endswith("prompt_supplement"):
            continue
        overrides[key] = value
    if overrides:
        run.params = {**(run.params or {}), **overrides}

    now = _now()
    run.status = "running"
    step.status = "running"
    step.started_at = now
    step.finished_at = None
    step.artifact_path = None
    step.edited_artifact_path = None

    session.add(run)
    session.add(step)
    session.commit()
    session.refresh(run)
    session.refresh(step)

    log_event(session, run_id, step_no, "info", f"Step {step_no} queued")
    session.refresh(run)
    session.refresh(step)
    background_tasks.add_task(run_step_background, run_id, step_no, run.params)

    return StartStepResponse(
        run=RunRead.model_validate(run),
        step=StepRead.model_validate(step),
    )


@router.get("/runs/{run_id}/steps/{step_no}/artifact")
def download_step_artifact(
    run_id: str,
    step_no: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    _, path = _resolve_current_artifact(session, run_id, step_no)
    return FileResponse(path, filename=path.name)


@router.get(
    "/runs/{run_id}/steps/{step_no}/rows",
    response_model=StepRowsResponse,
)
def get_step_rows(
    run_id: str,
    step_no: int,
    name: str | None = None,
    session: Session = Depends(get_session),
) -> StepRowsResponse:
    _, path = _resolve_current_artifact(session, run_id, step_no)
    if name is not None:
        path = _resolve_named_step_artifact(path, name)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_artifact(path)
    if suffix == ".json":
        return _read_json_artifact(path)
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported artifact format for row preview: {path.suffix}",
    )


@router.put(
    "/runs/{run_id}/steps/{step_no}/edited",
    response_model=StepRead,
)
def save_edited_step(
    run_id: str,
    step_no: int,
    body: SaveEditedStepRequest,
    session: Session = Depends(get_session),
) -> StepRead:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    step = _get_step(session, run_id, step_no)
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")

    out_dir = run_step_dir(run_id, step_no)
    out_dir.mkdir(parents=True, exist_ok=True)

    if body.rows is not None:
        edited_path = out_dir / "edited.csv"
        _write_edited_csv(edited_path, body.rows, body.columns)
    elif body.data is not None:
        edited_path = out_dir / "edited.json"
        edited_path.write_text(
            json.dumps(body.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        raise HTTPException(status_code=400, detail="No edited artifact payload provided")

    step.edited_artifact_path = str(edited_path)
    session.add(step)
    session.commit()
    session.refresh(step)
    return StepRead.model_validate(step)


def _resolve_current_artifact(
    session: Session,
    run_id: str,
    step_no: int,
) -> tuple[PipelineStep, Path]:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    step = _get_step(session, run_id, step_no)
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")

    artifact = step.edited_artifact_path or step.artifact_path
    if not artifact:
        raise HTTPException(status_code=404, detail="Step artifact is absent")

    path = Path(artifact)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Step artifact file not found")
    return step, path


def _resolve_named_step_artifact(primary_path: Path, name: str) -> Path:
    if not name or "/" in name or "\\" in name or Path(name).name != name:
        raise HTTPException(
            status_code=400,
            detail="Artifact name must be a file name within the step directory",
        )

    step_dir = primary_path.parent.resolve()
    path = (step_dir / name).resolve()
    try:
        path.relative_to(step_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Artifact name must stay within the step directory",
        ) from exc

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Named step artifact not found")
    return path


def _read_csv_artifact(path: Path) -> StepTableRows:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for index, row in enumerate(reader):
            if index >= MAX_STEP_ROWS:
                break
            rows.append(
                {
                    column: _csv_cell_to_string(row.get(column))
                    for column in columns
                }
            )
    return StepTableRows(kind="table", columns=columns, rows=rows)


def _read_json_artifact(path: Path) -> StepJsonRows:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Step artifact is not valid JSON: {path}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="JSON artifact preview expects an object at the top level",
        )
    return StepJsonRows(kind="json", data=payload)


def _write_edited_csv(
    path: Path,
    rows: list[dict[str, Any]],
    columns: list[str] | None,
) -> None:
    fieldnames = _resolve_csv_fieldnames(rows, columns)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    column: _csv_cell_to_string(row.get(column))
                    for column in fieldnames
                }
            )


def _resolve_csv_fieldnames(
    rows: list[dict[str, Any]],
    columns: list[str] | None,
) -> list[str]:
    fieldnames: list[str] = []
    seen: set[str] = set()

    for column in columns or []:
        column_name = str(column)
        if column_name not in seen:
            fieldnames.append(column_name)
            seen.add(column_name)

    for row in rows:
        for key in row.keys():
            column_name = str(key)
            if column_name not in seen:
                fieldnames.append(column_name)
                seen.add(column_name)

    if not fieldnames:
        raise HTTPException(status_code=400, detail="CSV edit requires at least one column")
    return fieldnames


def _csv_cell_to_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def run_step_background(
    run_id: str,
    step_no: int,
    params: dict[str, Any],
) -> None:
    with Session(engine) as session:
        run = session.get(PipelineRun, run_id)
        step = _get_step(session, run_id, step_no)
        if run is None or step is None:
            return

        try:
            log_event(session, run_id, step_no, "info", f"Step {step_no} started")
            artifact_path = get_step_runner(step_no)(run_id, params)
        except Exception as exc:
            step.status = "error"
            step.finished_at = _now()
            run.status = "error"
            session.add(run)
            session.add(step)
            session.commit()
            log_event(
                session,
                run_id,
                step_no,
                "error",
                f"Step {step_no} failed: {type(exc).__name__}: {exc}",
            )
            return

        step.status = "done"
        step.artifact_path = artifact_path
        step.finished_at = _now()
        run.status = "done"
        session.add(run)
        session.add(step)
        session.commit()
        log_event(
            session,
            run_id,
            step_no,
            "info",
            f"Step {step_no} completed",
        )


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> EventSourceResponse:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def generate_events() -> Any:
        seen_ids: set[int] = set()
        async with event_hub.subscribe(run_id) as queue:
            with Session(engine) as replay_session:
                events = replay_session.exec(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id)
                    .order_by(RunEvent.id)
                ).all()

            for event in events:
                if await request.is_disconnected():
                    return
                payload = serialize_event(event)
                if event.id is not None:
                    seen_ids.add(event.id)
                yield {
                    "event": "run_event",
                    "id": str(event.id),
                    "data": json.dumps(payload),
                }

            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                event_id = payload.get("id")
                if isinstance(event_id, int) and event_id in seen_ids:
                    continue
                if isinstance(event_id, int):
                    seen_ids.add(event_id)

                yield {
                    "event": "run_event",
                    "id": str(event_id),
                    "data": json.dumps(payload),
                }

    return EventSourceResponse(generate_events(), ping=15)


@router.get("/runs/{run_id}/events/history", response_model=list[RunEventRead])
def list_run_events(
    run_id: str,
    limit: int = 500,
    session: Session = Depends(get_session),
) -> list[RunEventRead]:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    bounded_limit = max(1, min(limit, 1000))
    events = list(
        session.exec(
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.id.desc())
            .limit(bounded_limit)
        ).all()
    )
    events.reverse()

    return [RunEventRead.model_validate(event) for event in events]


# ── Codebook introspection (read-only) ───────────────────────────────────────
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class CodebookField(BaseModel):
    name: str | None = None
    label: str | None = None
    type: str | None = None
    required: bool = False
    prompt: str | None = None


class CodebookRead(BaseModel):
    disease: str
    parameter: str
    name: str | None = None
    description: str | None = None
    effect_type: str | None = None
    notes: str | None = None
    fields: list[CodebookField] = PydanticField(default_factory=list)


def _repo_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "configs").is_dir() and (cwd / "evaluation").is_dir():
        return cwd
    # webapp/app/runs.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


@router.get("/codebooks/{disease}/{parameter}", response_model=CodebookRead)
def get_codebook(disease: str, parameter: str) -> CodebookRead:
    # Guard against path traversal — only flat config names are valid.
    if not _NAME_RE.match(disease) or not _NAME_RE.match(parameter):
        raise HTTPException(status_code=400, detail="Invalid disease/parameter")

    path = _repo_root() / "configs" / disease / "codebooks" / f"{parameter}.yaml"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Codebook not found: {disease}/{parameter}",
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    project = data.get("project") if isinstance(data.get("project"), dict) else {}

    fields: list[CodebookField] = []
    for raw in data.get("fields") or []:
        if not isinstance(raw, dict):
            continue
        fields.append(
            CodebookField(
                name=raw.get("name"),
                label=raw.get("label") or raw.get("name"),
                type=raw.get("type"),
                required=bool(raw.get("required", False)),
                prompt=raw.get("prompt"),
            )
        )

    notes = data.get("notes")
    return CodebookRead(
        disease=disease,
        parameter=parameter,
        name=project.get("name"),
        description=project.get("description"),
        effect_type=project.get("effect_type"),
        notes=notes if isinstance(notes, str) else None,
        fields=fields,
    )


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


@router.get("/runs/{run_id}/steps/{step_no}/index", response_model=StepTableRows)
def get_step_index(run_id: str, step_no: int) -> StepTableRows:
    """Aggregate the per-paper structured index JSONs a coding run produces
    (data/runs/{id}/step-{n}/index/*.index.json) into a single review table."""
    # Guard against path traversal — run ids are flat tokens (uuid-like).
    if not _NAME_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")

    index_dir = run_step_dir(run_id, step_no) / "index"
    if not index_dir.is_dir():
        raise HTTPException(status_code=404, detail="No index results for this stage")

    columns: list[str] = ["pmid"]
    rows: list[dict[str, str]] = []
    for path in sorted(index_dir.glob("*.index.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        envelope = data if isinstance(data, dict) else {}
        index_obj = envelope.get("index")
        if not isinstance(index_obj, dict):
            index_obj = envelope
        pmid = envelope.get("pmid") or path.stem.replace(".index", "").replace(
            "PMID_", ""
        )
        row: dict[str, str] = {"pmid": _stringify_cell(pmid)}
        for key, value in index_obj.items():
            col = str(key)
            if col == "pmid":
                continue
            if col not in columns:
                columns.append(col)
            row[col] = _stringify_cell(value)
        rows.append(row)

    if not rows:
        raise HTTPException(status_code=404, detail="No index records found")

    normalized = [{col: row.get(col, "") for col in columns} for row in rows]
    return StepTableRows(kind="table", columns=columns, rows=normalized)


class StagePromptRead(BaseModel):
    stage: str
    has_prompt: bool
    source: str | None = None
    system: str | None = None
    user: str | None = None
    output: str | None = None


@router.get("/prompts/{stage}", response_model=StagePromptRead)
def get_stage_prompt(
    stage: str,
    disease: str | None = None,
    parameter: str | None = None,
    strategy: str | None = None,
) -> StagePromptRead:
    """Resolve the prompt template a stage uses (read-only), for display +
    human-in-the-loop supplementation."""
    for value in (stage, disease, parameter, strategy):
        if value is not None and not _NAME_RE.match(value):
            raise HTTPException(status_code=400, detail="Invalid prompt selector")

    from app.prompt_templates import resolve_stage_prompt

    data = resolve_stage_prompt(
        stage, disease=disease, parameter=parameter, strategy=strategy
    )
    return StagePromptRead(**data)
