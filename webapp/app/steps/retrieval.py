from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import engine
from app.events import StreamToEvents
from app.models import PipelineStep

REQUIRED_COLUMNS = ["PMID", "Title", "Abstract", "Keywords"]


def run_retrieval_step(run_id: str, params: dict[str, Any]) -> str:
    query, query_source = _resolve_query(run_id, params)

    retmax = _parse_retmax(params.get("retmax", "200"))
    date_range = str(params.get("date_range") or "").strip()
    out_dir = Path("data") / "runs" / run_id / "step-2"
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = out_dir / "candidates.csv"

    with Session(engine) as session:
        stream = StreamToEvents(session=session, run_id=run_id, step_no=2)
        with redirect_stdout(stream), redirect_stderr(stream):
            from metaagent.config import load_runtime_env
            from tools.pubmed.client import PubMedClient
            from tools.scripts.pubmed_manager import fetch_paper_details

            load_runtime_env()
            print(f"retrieval step: query={query}")
            if query_source:
                print(f"retrieval step: query_source={query_source}")
            print(f"retrieval step: retmax={retmax if retmax is not None else 'all'}")
            if date_range:
                print(f"retrieval step: date_range={date_range}")

            client = PubMedClient()
            papers = client.search(query, retmax=retmax, year=date_range or None)
            pmids = [paper.id.replace("pubmed:", "") for paper in papers if paper.id]
            print(f"retrieval step: PubMed search hits={len(pmids)}")

            rows: list[dict[str, Any]] = []
            for chunk in _chunk(pmids, 50):
                rows.extend(fetch_paper_details(list(chunk), client))

            rows = _dedupe_rows(rows)
            for row in rows:
                for column in REQUIRED_COLUMNS:
                    row.setdefault(column, "")

            _write_csv(rows, candidates_path, required_columns=REQUIRED_COLUMNS)
            print(f"retrieval step: wrote rows={len(rows)} to {candidates_path}")

    return str(candidates_path)


def _resolve_query(run_id: str, params: dict[str, Any]) -> tuple[str, str | None]:
    query = str(params.get("query") or "").strip()
    if query:
        return query, None

    query_path = _resolve_step1_query_path(run_id)
    try:
        payload = json.loads(query_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Step-1 query artifact is not valid JSON: {query_path}") from exc

    query = str(payload.get("query") or "").strip() if isinstance(payload, dict) else ""
    if not query:
        raise ValueError(f"Step-1 query artifact has empty 'query': {query_path}")
    return query, str(query_path)


def _resolve_step1_query_path(run_id: str) -> Path:
    candidates: list[Path] = []

    with Session(engine) as session:
        step = session.exec(
            select(PipelineStep).where(
                PipelineStep.run_id == run_id,
                PipelineStep.step_no == 1,
            )
        ).one_or_none()

    if step is not None:
        for artifact in (step.edited_artifact_path, step.artifact_path):
            if artifact:
                candidates.append(Path(artifact))

    candidates.append(Path("data") / "runs" / run_id / "step-1" / "query.json")

    seen: set[Path] = set()
    checked: list[str] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        checked.append(str(path))
        if path.is_file():
            return path

    raise FileNotFoundError(
        "No step-1 query artifact found for this run. "
        f"Checked: {', '.join(checked)}"
    )


def _parse_retmax(value: Any) -> int | None:
    if value is None:
        return 200
    text = str(value).strip()
    if not text:
        return 200
    if text.lower() == "all":
        return None
    retmax = int(text)
    if retmax < 1:
        raise ValueError("params['retmax'] must be a positive integer or 'all'")
    return retmax


def _chunk(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        pmid = str(row.get("PMID") or "").strip()
        if pmid:
            if pmid in seen:
                continue
            seen.add(pmid)
        deduped.append(row)
    return deduped


def _write_csv(
    rows: list[dict[str, Any]],
    output_path: Path,
    *,
    required_columns: list[str],
) -> None:
    fieldnames = list(required_columns)
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
