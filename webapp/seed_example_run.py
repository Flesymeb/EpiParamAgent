"""Seed a fully-populated example pipeline run into the webapp DB.

Creates ONE run with all five backend steps marked done and real artifacts on
disk, so the dashboard is not empty and every per-stage result panel (query,
candidates, screened, code index, extraction sheet, pooled/forest) has
something genuine to render.

Data provenance — nothing here is fabricated:
  * query.json     <- dataset/.../p13 project query_text (the real PubMed query)
  * candidates.csv <- dataset/covid19/screening/serial_interval/p13/raw.csv
                      (the real 111-paper retrieval pool)
  * screened.csv   <- the 45 papers from that pool that proceeded to coding
                      (the exact PMID set the e2e reproducibility run coded),
                      with their real metadata + a screening_decision=include col
  * coding_sheet.csv + index/*.index.json
                   <- e2e/runs/p13 (the fresh LLM re-extraction, 119 rows /
                      45 papers, validated in e2e/REPORT.md)
  * pooled.csv + forest.csv
                   <- recomputed live from that coding sheet via
                      tools.analysis.pooling (same code the pooling step uses)

Run from repo root:
    PYTHONPATH=. .venv/bin/python webapp/seed_example_run.py
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "webapp"))

import openpyxl  # noqa: E402

from app.db import RUNS_DIR, engine, init_db, run_step_dir  # noqa: E402
from app.models import PipelineRun, PipelineStep, RunEvent  # noqa: E402
from sqlmodel import Session, delete, select  # noqa: E402

RUN_ID = "demo-si"

P13_DIR = REPO_ROOT / "dataset/covid19/screening/serial_interval/p13"
E2E_DIR = REPO_ROOT / "e2e/runs/p13"
PMIDS_FILE = REPO_ROOT / "e2e/p13_pmids.txt"


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        cols = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return cols, rows


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def seed_step1_query(project: dict) -> Path:
    out = run_step_dir(RUN_ID, 1)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "query": project.get("query_text", ""),
        "research_question": project.get("research_question", ""),
        "disease": "covid19",
        "parameter": "serial_interval",
        "terms": [
            {
                "concept": "serial interval",
                "synonyms": [
                    "generation interval",
                    "generation time",
                    "serial distribution",
                ],
            },
            {
                "concept": "COVID-19",
                "synonyms": [
                    "SARS-CoV-2",
                    "coronavirus",
                    "2019-nCoV",
                    "SARS-CoV",
                ],
            },
        ],
    }
    path = out / "query.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return path


def seed_step2_candidates() -> tuple[Path, list[str], list[dict[str, str]]]:
    cols, rows = _read_csv(P13_DIR / "raw.csv")
    out = run_step_dir(RUN_ID, 2)
    path = out / "candidates.csv"
    _write_csv(path, cols, rows)
    return path, cols, rows


def seed_step3_screened(
    cand_cols: list[str], cand_rows: list[dict[str, str]]
) -> Path:
    coded = {p.strip() for p in PMIDS_FILE.read_text().split() if p.strip()}

    def pmid_of(row: dict[str, str]) -> str:
        return (row.get("PMID") or row.get("pmid") or "").strip()

    columns = [*cand_cols, "screening_decision"]
    rows: list[dict[str, str]] = []
    for row in cand_rows:
        decision = "include" if pmid_of(row) in coded else "exclude"
        rows.append({**row, "screening_decision": decision})
    # Surface included papers first so the table opens on the meaningful rows.
    rows.sort(key=lambda r: 0 if r["screening_decision"] == "include" else 1)

    out = run_step_dir(RUN_ID, 3)
    path = out / "screened.csv"
    _write_csv(path, columns, rows)
    return path


def seed_step4_coding() -> Path:
    out = run_step_dir(RUN_ID, 4)
    out.mkdir(parents=True, exist_ok=True)

    # index/*.index.json  -> drives the Code stage's index endpoint
    dst_index = out / "index"
    if dst_index.exists():
        shutil.rmtree(dst_index)
    shutil.copytree(E2E_DIR / "index", dst_index)

    # coding_sheet.csv  -> drives the Extraction stage table
    xlsx = next(E2E_DIR.glob("coding_sheet_*.xlsx"))
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    ws = wb.active
    data = list(ws.iter_rows(values_only=True))
    columns = [str(c) for c in data[0]]
    rows = [
        {col: ("" if v is None else str(v)) for col, v in zip(columns, r)}
        for r in data[1:]
    ]
    csv_path = out / "coding_sheet.csv"
    _write_csv(csv_path, columns, rows)
    return csv_path


def seed_step5_pooling(coding_csv: Path) -> Path:
    import pandas as pd

    from tools.analysis.pooling import enrich_ci, summarize

    out = run_step_dir(RUN_ID, 5)
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(coding_csv)
    df = enrich_ci(df)
    pooled = summarize(
        df,
        parameter_type="serial_interval",
        estimate_measure="mean",
        include_median=False,
        impute_missing_se=True,
        method="random",
    )
    pooled_path = out / "pooled.csv"
    pooled.to_csv(pooled_path, index=False)

    # forest.csv: one primary mean row per study (first SI-mean per pmid)
    si = df[
        (df["parameter_type"].astype(str).str.lower() == "serial_interval")
        & (df["estimate_measure"].astype(str).str.lower() == "mean")
    ].copy()
    si["point_estimate"] = pd.to_numeric(si["point_estimate"], errors="coerce")
    si = si.dropna(subset=["point_estimate"])
    primary = si.groupby("pmid", as_index=False).first()
    forest = pd.DataFrame(
        {
            "study_label": primary.get("study", primary["pmid"]).astype(str),
            "estimate": primary["point_estimate"],
            "ci_lower": pd.to_numeric(primary.get("uncertainty_low"), errors="coerce"),
            "ci_upper": pd.to_numeric(primary.get("uncertainty_high"), errors="coerce"),
        }
    )
    forest.to_csv(out / "forest.csv", index=False)
    return pooled_path


def main() -> None:
    if not P13_DIR.exists() or not E2E_DIR.exists():
        raise SystemExit(
            f"Missing source data. Expected {P13_DIR} and {E2E_DIR} to exist."
        )

    init_db()
    project = json.loads((P13_DIR / "project.json").read_text("utf-8"))

    # Clean any prior seed of this run (DB rows + artifacts) for idempotency.
    with Session(engine) as session:
        session.exec(delete(RunEvent).where(RunEvent.run_id == RUN_ID))
        session.exec(delete(PipelineStep).where(PipelineStep.run_id == RUN_ID))
        existing = session.get(PipelineRun, RUN_ID)
        if existing is not None:
            session.delete(existing)
        session.commit()
    seeded_dir = RUNS_DIR / RUN_ID
    if seeded_dir.exists():
        shutil.rmtree(seeded_dir)

    p1 = seed_step1_query(project)
    p2, cand_cols, cand_rows = seed_step2_candidates()
    p3 = seed_step3_screened(cand_cols, cand_rows)
    p4 = seed_step4_coding()
    p5 = seed_step5_pooling(p4)

    artifacts = {1: p1, 2: p2, 3: p3, 4: p4, 5: p5}
    names = {1: "query_gen", 2: "retrieval", 3: "screening", 4: "coding", 5: "pooling"}

    base = datetime.now(UTC) - timedelta(minutes=30)
    with Session(engine) as session:
        run = PipelineRun(
            id=RUN_ID,
            status="done",
            created_at=base,
            params={
                "disease": "covid19",
                "parameter": "serial_interval",
                "research_question": project.get("research_question", ""),
                "codebook_path": "configs/covid19/codebooks/serial_interval.yaml",
                "estimate_measure": "mean",
                "method": "random",
            },
        )
        session.add(run)
        for step_no in range(1, 6):
            started = base + timedelta(minutes=step_no * 4)
            session.add(
                PipelineStep(
                    run_id=RUN_ID,
                    step_no=step_no,
                    name=names[step_no],
                    status="done",
                    artifact_path=str(artifacts[step_no]),
                    started_at=started,
                    finished_at=started + timedelta(minutes=3),
                )
            )
        session.add(
            RunEvent(
                run_id=RUN_ID,
                step_no=None,
                level="info",
                message="Seeded example run (covid19 / serial_interval / p13).",
            )
        )
        session.commit()

    print(f"Seeded run {RUN_ID!r} with 5 done steps.")
    for step_no in range(1, 6):
        print(f"  step {step_no} ({names[step_no]}): {artifacts[step_no]}")
    idx = run_step_dir(RUN_ID, 4) / "index"
    print(f"  index files: {len(list(idx.glob('*.index.json')))}")


if __name__ == "__main__":
    main()
