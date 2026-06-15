from __future__ import annotations

import json
import re
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlmodel import Session

from app.db import engine, run_step_dir
from app.events import StreamToEvents

DATASET_DISEASE_DIRS = {
    "covid19": "covid19",
    "mpox": "mpox",
}


def run_coding_step(run_id: str, params: dict[str, Any]) -> str:
    disease = str(params.get("disease") or "covid19").strip()
    parameter = str(params.get("parameter") or "").strip()
    profile = str(params.get("profile") or params.get("topic") or "").strip()
    stage = str(params.get("stage") or "extract").strip()
    fetch_strategy = str(params.get("fetch_strategy") or "pmc_only").strip()
    supplement = str(
        params.get("code_prompt_supplement")
        or params.get("prompt_supplement")
        or ""
    ).strip()

    if not parameter:
        raise ValueError("params['parameter'] is required")
    if not profile:
        raise ValueError("params['profile'] or params['topic'] is required")

    project_root = _resolve_project_root()
    disease_dir = DATASET_DISEASE_DIRS.get(disease, disease)
    profile_id = profile.lower()
    project_dir = project_root / "dataset" / disease_dir / "coding" / parameter / profile_id
    project_path = project_dir / "project.json"
    pmids_path = project_dir / "pmids.txt"
    codebook_path = Path(
        params.get("codebook_path")
        or project_root / "configs" / disease / "codebooks" / f"{parameter}.yaml"
    )
    out_dir = run_step_dir(run_id, 4)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not project_path.exists():
        raise FileNotFoundError(f"project.json not found: {project_path}")
    if not pmids_path.exists():
        raise FileNotFoundError(f"pmids.txt not found: {pmids_path}")
    if not codebook_path.exists():
        raise FileNotFoundError(f"Codebook not found: {codebook_path}")

    with Session(engine) as session:
        stream = StreamToEvents(session=session, run_id=run_id, step_no=4)
        with redirect_stdout(stream), redirect_stderr(stream):
            print(f"coding step: disease={disease} parameter={parameter} profile={profile_id}")
            print(f"coding step: stage={stage} fetch_strategy={fetch_strategy}")
            print(f"coding step: project={project_path}")
            print(f"coding step: pmids={pmids_path}")
            print(f"coding step: codebook={codebook_path}")
            print(f"coding step: out_dir={out_dir}")

            temp_codebook: Path | None = None
            if supplement:
                temp_codebook = _materialize_codebook_supplement(
                    codebook_path, supplement, run_id
                )
                codebook_path = temp_codebook
                print(f"coding step: applied reviewer supplement → {codebook_path}")

            from metaagent.coding.pipeline.extraction import run_pipeline

            try:
                run_pipeline(
                    input_path=pmids_path,
                    out_dir=out_dir,
                    stage=stage,
                    codebook_path=codebook_path,
                    fetch_strategy=fetch_strategy,
                    llm_overrides=params,
                )
            finally:
                if temp_codebook is not None:
                    temp_codebook.unlink(missing_ok=True)

            coding_csv = _write_coding_sheet_csv(out_dir)
            if coding_csv is not None:
                print(f"coding step: wrote CSV artifact {coding_csv}")
                return str(coding_csv)

            fetch_result = out_dir / "fetch_result.json"
            payload = {
                "run_id": run_id,
                "stage": stage,
                "disease": disease,
                "parameter": parameter,
                "profile": profile_id,
                "project_path": str(project_path),
                "pmids_path": str(pmids_path),
                "codebook_path": str(codebook_path),
                "output_dir": str(out_dir),
                "coding_sheet_csv": None,
            }
            fetch_result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"coding step: no coding sheet produced; wrote {fetch_result}")
            return str(fetch_result)


def _write_coding_sheet_csv(out_dir: Path) -> Path | None:
    candidates = sorted(
        out_dir.glob("coding_sheet*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None

    source_xlsx = candidates[0]
    stable_xlsx = out_dir / "coding_sheet.xlsx"
    if source_xlsx.resolve() != stable_xlsx.resolve():
        shutil.copy2(source_xlsx, stable_xlsx)

    df = pd.read_excel(stable_xlsx)
    csv_path = out_dir / "coding_sheet.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


def _resolve_project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "evaluation").exists():
        return cwd
    # webapp/app/steps/coding.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _materialize_codebook_supplement(
    codebook_path: Path, supplement: str, run_id: str
) -> Path:
    """Write a per-run codebook copy NEXT TO the original (same directory) with
    the reviewer supplement appended to `notes`. Keeping it in the original dir
    means run_pipeline's relative `../coding_prompts/` + sibling derivation still
    resolve. The caller deletes it after the run."""
    data = yaml.safe_load(codebook_path.read_text(encoding="utf-8")) or {}
    notes = str(data.get("notes") or "").rstrip()
    block = "[Reviewer supplement]\n" + supplement
    data["notes"] = f"{notes}\n\n{block}" if notes else block

    safe_run = re.sub(r"[^A-Za-z0-9_-]", "", run_id)[:24] or "run"
    target = codebook_path.parent / f".run_{safe_run}.codebook.yaml"
    target.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target
