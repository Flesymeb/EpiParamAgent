from __future__ import annotations

import asyncio
import csv
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import engine, run_step_dir
from app.events import StreamToEvents
from app.models import PipelineStep

BASE_COLUMNS = ["PMID", "Title", "Abstract", "Keywords"]


def run_screening_step(run_id: str, params: dict[str, Any]) -> str:
    input_path = _resolve_input_path(run_id, params)
    out_dir = run_step_dir(run_id, 3)
    out_dir.mkdir(parents=True, exist_ok=True)
    screened_path = out_dir / "screened.csv"

    with Session(engine) as session:
        stream = StreamToEvents(session=session, run_id=run_id, step_no=3)
        with redirect_stdout(stream), redirect_stderr(stream):
            from metaagent.screening.engine import init_llm_model, screen_papers_batch_async

            print(f"screening step: input={input_path}")
            papers = _load_papers(input_path)
            print(f"screening step: loaded rows={len(papers)}")

            llm = init_llm_model(
                model_override=params.get("model"),
                provider_override=params.get("provider"),
                temperature_override=params.get("temperature"),
                config_overrides=params,
            )
            # Human-in-the-loop supplement: appended to the eligibility text so
            # it flows into the screening prompt as extra reviewer guidance.
            research_question = str(params.get("research_question") or "")
            supplement = str(
                params.get("screen_prompt_supplement")
                or params.get("prompt_supplement")
                or ""
            ).strip()
            if supplement:
                research_question = (
                    f"{research_question}\n\nAdditional reviewer guidance:\n{supplement}"
                ).strip()
            asyncio.run(
                screen_papers_batch_async(
                    papers=papers,
                    research_question=research_question,
                    llm_model=llm,
                    batch_size=int(params.get("batch_size", 20)),
                    batch_concurrency=1,
                    batch_mode="single",
                    screening_stage="title_abstract",
                    content_label="Abstract",
                    content_key="Abstract",
                    strategy=params.get("strategy", "binary"),
                    prefer_llm_tier=True,
                )
            )

            _write_csv(papers, screened_path)
            print(f"screening step: wrote rows={len(papers)} to {screened_path}")

    return str(screened_path)


def _resolve_input_path(run_id: str, params: dict[str, Any]) -> Path:
    explicit = params.get("input_path")
    if explicit:
        path = Path(str(explicit))
        if not path.exists():
            raise FileNotFoundError(f"Input artifact not found: {path}")
        return path

    with Session(engine) as session:
        step = session.exec(
            select(PipelineStep).where(
                PipelineStep.run_id == run_id,
                PipelineStep.step_no == 2,
            )
        ).one_or_none()

    if step is None:
        raise FileNotFoundError("No step-2 artifact found for this run")

    artifact = step.edited_artifact_path or step.artifact_path
    if not artifact:
        raise FileNotFoundError("Step 2 has no artifact path")

    path = Path(artifact)
    if not path.exists():
        raise FileNotFoundError(f"Step-2 artifact not found: {path}")
    return path


def _load_papers(input_path: Path) -> list[dict[str, Any]]:
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    fieldnames = list(BASE_COLUMNS)
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
