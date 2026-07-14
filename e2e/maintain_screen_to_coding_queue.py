"""Maintain up to N concurrent screening-to-coding E2E jobs.

This is intentionally conservative: it launches only profiles listed in the
paper source-data table, skips completed/running/prepared profiles, and writes
per disease/topic skip lists so already coded or in-flight PMIDs are not run
again.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path

import pandas as pd

from update_screen_to_coding_tracking import (
    PARAM_GROUP_TOPIC,
    ROOT,
    RUN_ROOT,
    SOURCE_DATA,
    _latest_xlsx,
    _norm_pmid,
    _project_num,
    _run_context,
    build_tracking,
)


DEFAULT_PROVIDER = None
DEFAULT_MODEL = None
DEFAULT_MODEL_TAG = "coding_env"
DEFAULT_SCREENING_EXPERIMENT = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
DISEASE_ORDER = {"covid19": 0, "mpox": 1}
TOPIC_ORDER = {"serial_interval": 0, "reproduction_number": 1, "fatality": 2}
TIER_TO_INCLUDE = {"S", "P"}


def _running_commands() -> list[str]:
    proc = subprocess.run(["ps", "-eww", "-o", "cmd"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return []
    return [
        line
        for line in proc.stdout.splitlines()
        if "run_screen_to_coding.py" in line and "python" in line
    ]


def _running_keys_and_dirs() -> tuple[set[tuple[str, str, str]], list[Path]]:
    keys: set[tuple[str, str, str]] = set()
    dirs: list[Path] = []
    for line in _running_commands():
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        disease = topic = project = out_dir = None
        for idx, part in enumerate(parts):
            if idx + 1 >= len(parts):
                continue
            if part == "--disease":
                disease = parts[idx + 1]
            elif part == "--topic":
                topic = parts[idx + 1]
            elif part == "--project":
                project = _project_num(parts[idx + 1])
            elif part == "--out-dir":
                out_dir = parts[idx + 1]
        if disease and topic and project:
            keys.add((disease, topic, project))
        if out_dir:
            dirs.append(Path(out_dir).resolve())
    return keys, dirs


def _screening_csv(disease: str, topic: str, project_num: str) -> Path | None:
    base = (
        ROOT
        / "evaluation"
        / "screening"
        / disease
        / topic
        / f"p{project_num}"
        / "experiments"
        / DEFAULT_SCREENING_EXPERIMENT
    )
    direct = base / f"project_{project_num}_screened.csv"
    if direct.exists():
        return direct
    matches = sorted(base.glob(f"screening_runs/*/project_{project_num}_screened.csv"))
    return matches[-1] if matches else None


def _screening_csv_exists(disease: str, topic: str, project_num: str) -> bool:
    return _screening_csv(disease, topic, project_num) is not None


def _selected_pmids_from_screening(disease: str, topic: str, project_num: str) -> list[str]:
    path = _screening_csv(disease, topic, project_num)
    if path is None:
        return []
    df = pd.read_csv(path)
    if "PMID" not in df.columns:
        return []
    if "llm_tier" in df.columns:
        mask = df["llm_tier"].astype(str).str.strip().str.upper().isin(TIER_TO_INCLUDE)
    elif "llm_suggest" in df.columns:
        mapped = df["llm_suggest"].astype(str).str.strip().str.lower().map(
            {"strong_candidate": "S", "possible_candidate": "P", "unlikely_candidate": "U"}
        )
        mask = mapped.isin(TIER_TO_INCLUDE)
    else:
        return []
    pmids = df.loc[mask, "PMID"].dropna().astype(str).str.strip()
    pmids = pmids[pmids.ne("") & pmids.str.lower().ne("nan")]
    return pmids.drop_duplicates().tolist()


def _cache_counts(pmids: list[str]) -> tuple[int, int]:
    pdf_dir = ROOT / "paper_pool" / "pdfs"
    md_dir = ROOT / "paper_pool" / "markdown"
    cached = 0
    for pmid in pmids:
        pdf = pdf_dir / f"PMID_{pmid}.pdf"
        md = md_dir / f"PMID_{pmid}.md"
        legacy_md = md_dir / f"PMID_{pmid}" / f"PMID_{pmid}.md"
        if pdf.exists() or md.exists() or legacy_md.exists():
            cached += 1
    return cached, len(pmids) - cached


def _completed_pmids(disease: str, topic: str) -> set[str]:
    pmids: set[str] = set()
    for run_dir in sorted(RUN_ROOT.iterdir() if RUN_ROOT.exists() else []):
        if not run_dir.is_dir() or any(part in run_dir.name for part in ("dryrun", "debug", "preflight", "limit")):
            continue
        ctx = _run_context(run_dir)
        if not ctx or ctx["disease"] != disease or ctx["topic"] != topic:
            continue
        xlsx = _latest_xlsx(run_dir)
        if xlsx:
            try:
                df = pd.read_excel(xlsx, usecols=["pmid"])
            except Exception:
                df = pd.DataFrame()
            if not df.empty:
                pmids.update(p for p in df["pmid"].map(_norm_pmid).dropna().astype(str).tolist())
        if ctx["summary"].get("coding_ran"):
            path = run_dir / "coding_input_pmids.txt"
            if path.exists():
                pmids.update(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return pmids


def _inflight_pmids(disease: str, topic: str, running_dirs: list[Path]) -> set[str]:
    pmids: set[str] = set()
    for run_dir in running_dirs:
        ctx = _run_context(run_dir)
        if not ctx or ctx["disease"] != disease or ctx["topic"] != topic:
            continue
        for name in ("coding_input_pmids.txt", "screened_sp_pmids.txt"):
            path = run_dir / name
            if path.exists():
                pmids.update(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
                break
    return pmids


def _write_skip_files(
    disease: str,
    topic: str,
    running_dirs: list[Path],
    extra_inflight_pmids: set[str] | None = None,
    file_prefix: str | None = None,
) -> tuple[Path, Path]:
    state_dir = RUN_ROOT / "queue_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    completed = _completed_pmids(disease, topic)
    inflight = _inflight_pmids(disease, topic, running_dirs)
    if extra_inflight_pmids:
        inflight.update(extra_inflight_pmids)
    prefix = file_prefix or f"{disease}_{topic}"
    completed_path = state_dir / f"{prefix}_completed_pmids.txt"
    inflight_path = state_dir / f"{prefix}_inflight_pmids.txt"
    completed_path.write_text("\n".join(sorted(completed, key=lambda x: int(x) if x.isdigit() else x)) + ("\n" if completed else ""), encoding="utf-8")
    inflight_path.write_text("\n".join(sorted(inflight, key=lambda x: int(x) if x.isdigit() else x)) + ("\n" if inflight else ""), encoding="utf-8")
    return completed_path, inflight_path


def _launch(
    disease: str,
    topic: str,
    project_num: str,
    running_dirs: list[Path],
    extra_inflight_pmids: set[str] | None = None,
) -> str:
    skip_prefix = f"{disease}_{topic}_p{project_num}"
    completed_skip, inflight_skip = _write_skip_files(
        disease,
        topic,
        running_dirs,
        extra_inflight_pmids,
        file_prefix=skip_prefix,
    )
    out_dir = RUN_ROOT / f"{disease}_{topic}_p{project_num}_{DEFAULT_MODEL_TAG}_dedup_noproxy"
    log_dir = ROOT / "e2e" / "logs" / "screen_to_coding"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{disease}_{topic}_p{project_num}_{DEFAULT_MODEL_TAG}_dedup_noproxy.log"
    session = f"e2e_{DEFAULT_MODEL_TAG}_{disease}_{topic}_p{project_num}"
    llm_args = ""
    if DEFAULT_PROVIDER:
        llm_args += f"--provider {shlex.quote(DEFAULT_PROVIDER)} "
    if DEFAULT_MODEL:
        llm_args += f"--model {shlex.quote(DEFAULT_MODEL)} "
    cmd = (
        f"cd {shlex.quote(str(ROOT))} && "
        "export PYTHONUNBUFFERED=1 && "
        "PYTHONPATH=. LANGCHAIN_OPENAI_TCP_KEEPALIVE=0 "
        ".venv/bin/python e2e/run_screen_to_coding.py "
        f"--disease {shlex.quote(disease)} "
        f"--topic {shlex.quote(topic)} "
        f"--project p{project_num} "
        f"--out-dir {shlex.quote(str(out_dir))} "
        f"--skip-pmids-file {shlex.quote(str(completed_skip.relative_to(ROOT)))} "
        f"--skip-pmids-file {shlex.quote(str(inflight_skip.relative_to(ROOT)))} "
        "--run-coding --stage both --fetch-strategy pmc_only "
        f"{llm_args}"
        "--disable-proxy "
        f"2>&1 | tee -a {shlex.quote(str(log))}"
    )
    subprocess.run(["tmux", "kill-session", "-t", session], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["tmux", "new-session", "-d", "-s", session, cmd], check=True)
    return session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-parallel", type=int, default=3)
    parser.add_argument(
        "--priority",
        choices=("paper", "fastest"),
        default="fastest",
        help="Queue order: paper source-data order, or estimated fastest pending profile first.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tracking = build_tracking()
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    tracking_path = RUN_ROOT / "e2e_pooled_mean_tracking.csv"
    tracking.to_csv(tracking_path, index=False)

    running_keys, running_dirs = _running_keys_and_dirs()
    running_count = len(running_keys)
    launched: list[str] = []

    if running_count >= args.max_parallel:
        print(json.dumps({"running_count": running_count, "launched": launched, "tracking": str(tracking_path)}, indent=2))
        return

    source = pd.read_csv(SOURCE_DATA).copy()
    source["_topic"] = source["parameter_group"].astype(str).str.strip().str.lower().map(PARAM_GROUP_TOPIC)
    source["_disease_order"] = source["disease"].map(DISEASE_ORDER).fillna(99)
    source["_topic_order"] = source["_topic"].map(TOPIC_ORDER).fillna(99)
    source["_project_num"] = source["project"].map(_project_num).astype(int)
    candidates = []
    for _, src in source.iterrows():
        disease = str(src["disease"]).strip()
        topic = PARAM_GROUP_TOPIC[str(src["parameter_group"]).strip().lower()]
        project_num = _project_num(src["project"])
        status_row = tracking[
            (tracking["disease"] == disease)
            & (tracking["topic"] == topic)
            & (tracking["profile"] == (f"{'MP' if disease == 'mpox' else 'P'}{project_num}"))
        ]
        status = status_row.iloc[0]["status"] if not status_row.empty else "pending"
        if status not in {"pending", "prepared"}:
            continue
        if (disease, topic, project_num) in running_keys:
            continue
        if not _screening_csv_exists(disease, topic, project_num):
            print(f"[skip] missing screening csv: {disease}/{topic}/p{project_num}")
            continue
        selected_pmids = _selected_pmids_from_screening(disease, topic, project_num)
        completed = _completed_pmids(disease, topic)
        inflight = _inflight_pmids(disease, topic, running_dirs)
        coding_pmids = [pmid for pmid in selected_pmids if pmid not in completed and pmid not in inflight]
        cached, missing = _cache_counts(coding_pmids)
        candidates.append(
            {
                "disease": disease,
                "topic": topic,
                "project_num": project_num,
                "selected_pmids": selected_pmids,
                "coding_pmids": coding_pmids,
                "cached": cached,
                "missing": missing,
                "paper_order": (
                    DISEASE_ORDER.get(disease, 99),
                    TOPIC_ORDER.get(topic, 99),
                    int(project_num),
                ),
            }
        )

    if args.priority == "fastest":
        candidates.sort(
            key=lambda item: (
                len(item["coding_pmids"]),
                item["missing"],
                -item["cached"],
                item["paper_order"],
            )
        )
    else:
        candidates.sort(key=lambda item: item["paper_order"])

    reserved_pmids_by_topic: dict[tuple[str, str], set[str]] = {}
    for candidate in candidates:
        disease = candidate["disease"]
        topic = candidate["topic"]
        project_num = candidate["project_num"]
        reserved = reserved_pmids_by_topic.setdefault((disease, topic), set())
        if args.dry_run:
            session = f"DRY:{disease}/{topic}/p{project_num}"
        else:
            session = _launch(disease, topic, project_num, running_dirs, reserved)
        launched.append(session)
        running_keys.add((disease, topic, project_num))
        reserved.update(candidate["selected_pmids"])
        running_count += 1
        if running_count >= args.max_parallel:
            break

    print(json.dumps({"running_count": running_count, "launched": launched, "tracking": str(tracking_path)}, indent=2))


if __name__ == "__main__":
    main()
