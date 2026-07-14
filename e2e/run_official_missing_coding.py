#!/usr/bin/env python3
"""Run coding for PMIDs missing from the official screening-aligned E2E queue."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding"
ALIGNMENT_CSV = RUN_ROOT / "official_qwen36_recall_selected" / "official_screen_to_coding_alignment.csv"


def _project_num(project: object) -> str:
    return str(project).strip().lower().removeprefix("p")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alignment-csv", type=Path, default=ALIGNMENT_CSV)
    parser.add_argument("--profiles", nargs="*", default=[])
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    alignment = pd.read_csv(args.alignment_csv)
    todo = alignment[alignment["official_only"].fillna(0).astype(int).gt(0)].copy()
    if args.profiles:
        wanted = {p.upper() for p in args.profiles}
        todo = todo[todo["profile"].astype(str).str.upper().isin(wanted)].copy()

    for _, row in todo.iterrows():
        profile = str(row["profile"]).upper()
        disease = str(row["disease"])
        topic = str(row["topic"])
        project_num = _project_num(row["project"])
        selected_csv = Path(str(row["selected_csv"]))
        official_only_pmids = Path(str(row["official_only_pmids"]))
        out_dir = RUN_ROOT / f"{disease}_{topic}_p{project_num}_official_dsv4_fix"

        cmd = [
            sys.executable,
            "e2e/run_screen_to_coding.py",
            "--disease",
            disease,
            "--topic",
            topic,
            "--project",
            f"p{project_num}",
            "--screening-csv",
            str(selected_csv),
            "--input-pmids-file",
            str(official_only_pmids),
            "--out-dir",
            str(out_dir),
            "--stage",
            "both",
            "--fetch-strategy",
            "pmc_only",
            "--run-coding",
            "--disable-proxy",
        ]
        if args.fresh:
            cmd.append("--fresh")

        print(
            f"\n[{profile}] official_only={int(row['official_only'])} "
            f"tp={int(row['official_only_tp'])} fp={int(row['official_only_fp'])} "
            f"out={out_dir}"
        )
        print(" ".join(cmd))
        if args.dry_run:
            continue
        subprocess.run(cmd, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
