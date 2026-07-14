"""Raw-start webapp e2e smoke test over current covid19 projects.

This verifies that the webapp can skip Query/Retrieval and start Screening from
existing dataset/*/raw.csv files. By default it patches the screening LLM with a
deterministic local fake so the check is repeatable and cheap. Pass --real-llm
to exercise the configured screening model.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "e2e" / "runs" / "raw_start_smoke"
WEBAPP_DATA = OUT_DIR / "webapp_data"

os.environ["METAAGENT_WEBAPP_DATA"] = str(WEBAPP_DATA)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))

PROJECTS = [
    {
        "disease": "covid19",
        "parameter": "serial_interval",
        "profile": "p13",
        "raw_path": ROOT / "dataset/covid19/screening/serial_interval/p13/raw.csv",
        "research_question": "What are the serial interval and generation time of COVID-19?",
    },
    {
        "disease": "covid19",
        "parameter": "reproduction_number",
        "profile": "p7",
        "raw_path": ROOT / "dataset/covid19/screening/reproduction_number/p7/raw.csv",
        "research_question": "What are the reproduction number estimates for COVID-19?",
    },
    {
        "disease": "covid19",
        "parameter": "fatality",
        "profile": "p4",
        "raw_path": ROOT / "dataset/covid19/screening/fatality/p4/raw.csv",
        "research_question": "What are the case fatality estimates for COVID-19?",
    },
]


async def fake_screen_papers_batch_async(
    papers: list[dict[str, Any]],
    research_question: str,
    llm_model: Any,
    **_: Any,
) -> list[dict[str, Any]]:
    del research_question, llm_model

    labels = ("strong_candidate", "possible_candidate", "unlikely_candidate")
    tiers = {
        "strong_candidate": "S",
        "possible_candidate": "P",
        "unlikely_candidate": "U",
    }
    for index, paper in enumerate(papers):
        label = labels[index % len(labels)]
        score = {"strong_candidate": 4, "possible_candidate": 3}.get(label, 1)
        paper["llm_suggest"] = label
        paper["llm_tier"] = tiers[label]
        paper["overall_score"] = str(score)
        paper["overall_justification"] = (
            "Deterministic raw-start smoke decision; not a model judgment."
        )
        paper["confidence"] = "1.0"
        paper["prompt_tokens"] = "0"
        paper["completion_tokens"] = "0"
        paper["total_tokens"] = "0"
        paper["wall_time_ms"] = "0"
    return papers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument(
        "--real-llm",
        action="store_true",
        help="Use the configured screening LLM instead of the deterministic fake.",
    )
    args = parser.parse_args()

    if args.rows < 1:
        raise SystemExit("--rows must be >= 1")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "inputs").mkdir(parents=True, exist_ok=True)

    from sqlmodel import Session

    from app.db import engine, init_db
    from app.models import PipelineRun, PipelineStep
    from app.runs import run_step_background

    if not args.real_llm:
        import metaagent.screening.engine as screening_engine

        screening_engine.init_llm_model = lambda *_, **__: object()
        screening_engine.screen_papers_batch_async = fake_screen_papers_batch_async

    init_db()
    results: list[dict[str, Any]] = []

    for project in PROJECTS:
        input_path = _write_subset(project["raw_path"], project, args.rows)
        run_id = f"raw-smoke-{project['parameter']}-{project['profile']}"
        params = {
            "input_path": str(input_path),
            "research_question": project["research_question"],
            "disease": project["disease"],
            "parameter": project["parameter"],
            "profile": project["profile"],
            "batch_size": args.rows,
            "strategy": "5d",
        }

        with Session(engine) as session:
            run = PipelineRun(id=run_id, params=params)
            step = PipelineStep(run_id=run_id, step_no=3, name="screening")
            session.add(run)
            session.add(step)
            session.commit()
            step_id = step.id

        run_step_background(run_id, 3, params)

        with Session(engine) as session:
            run = session.get(PipelineRun, run_id)
            step = session.get(PipelineStep, step_id) if step_id is not None else None
            if run is None or step is None:
                raise RuntimeError(f"Missing persisted run/step for {run_id}")
            if run.status != "done" or step.status != "done":
                raise RuntimeError(
                    f"{run_id} did not finish: run={run.status} step={step.status}"
                )
            artifact_path = Path(step.artifact_path or "")

        rows = _read_rows(artifact_path)
        counts = Counter(row.get("llm_suggest", "") for row in rows)
        result = {
            "run_id": run_id,
            "project": f"{project['disease']}/{project['parameter']}/{project['profile']}",
            "input_path": str(input_path),
            "artifact_path": str(artifact_path),
            "rows": len(rows),
            "decision_counts": dict(sorted(counts.items())),
            "real_llm": args.real_llm,
        }
        results.append(result)
        print(
            f"[ok] {result['project']}: rows={result['rows']} "
            f"decisions={result['decision_counts']}"
        )

    summary = {
        "projects": len(results),
        "rows_per_project": args.rows,
        "real_llm": args.real_llm,
        "results": results,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[done] wrote {OUT_DIR / 'summary.json'}")


def _write_subset(raw_path: Path, project: dict[str, Any], rows: int) -> Path:
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)

    target = (
        OUT_DIR
        / "inputs"
        / f"{project['disease']}_{project['parameter']}_{project['profile']}_raw_first{rows}.csv"
    )
    with raw_path.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        subset = []
        for index, row in enumerate(reader):
            if index >= rows:
                break
            subset.append(row)

    if not subset:
        raise RuntimeError(f"No rows found in {raw_path}")

    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(subset)
    return target


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    main()
