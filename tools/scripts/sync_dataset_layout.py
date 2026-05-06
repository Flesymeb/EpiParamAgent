#!/usr/bin/env python3
"""Synchronize fixed task inputs into the disease-first dataset layout.

Canonical layout:
  dataset/{covid19|mpox}/screening/{topic}/pN/{project.json,ground_truth.csv,raw.csv}
  dataset/{covid19|mpox}/coding/{topic}/pN/{project.json,ground_truth.csv,pmids.txt}

Evaluation outputs stay under:
  evaluation/screening/{covid19|mpox}/{topic}/pN/experiments/{experiment}/
  evaluation/coding/{covid19|mpox}/{topic}/pN/coding_runs/{run}/
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DISEASE_DIRS = {
    "covid19": "covid19",
    "mpox": "mpox",
}


def _copy_file(src: Path, dst: Path, *, hardlink: bool = False, dry_run: bool = False) -> str:
    if not src.exists():
        return "missing"
    if dst.exists():
        return "exists"
    if dry_run:
        return "would_copy"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if hardlink:
        try:
            os.link(src, dst)
            return "linked"
        except OSError:
            pass
    shutil.copy2(src, dst)
    return "copied"


def _move_dir(src: Path, dst: Path, *, dry_run: bool = False) -> str:
    if not src.exists():
        return "missing"
    if dst.exists():
        return "exists"
    if dry_run:
        return "would_move"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return "moved"


def sync_screening_inputs(*, dry_run: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    legacy_root = REPO_ROOT / "dataset" / "_legacy_imports" / "evaluation_legacy" / "screening"
    for disease_key, disease_dir in DISEASE_DIRS.items():
        source_root = legacy_root / disease_key / "GT_1" / "GT_export"
        if not source_root.exists():
            continue
        for project_json in sorted(source_root.glob("*/p*/project.json")):
            src_project_dir = project_json.parent
            topic = src_project_dir.parent.name
            project = src_project_dir.name
            project_number = project.removeprefix("p")
            dst_project_dir = REPO_ROOT / "dataset" / disease_dir / "screening" / topic / project

            operations = [
                (project_json, dst_project_dir / "project.json", False),
                (
                    src_project_dir / f"project_{project_number}_groundtruth.csv",
                    dst_project_dir / "ground_truth.csv",
                    False,
                ),
                (
                    src_project_dir / f"project_{project_number}_raw.csv",
                    dst_project_dir / "raw.csv",
                    True,
                ),
            ]
            for src, dst, hardlink in operations:
                result = _copy_file(src, dst, hardlink=hardlink, dry_run=dry_run)
                stats[result] = stats.get(result, 0) + 1
    return stats


def sync_coding_inputs(*, dry_run: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    source_roots = [
        REPO_ROOT / "dataset" / "_legacy_imports" / "evaluation_legacy" / "coding",
        REPO_ROOT / "evaluation" / "coding",
        REPO_ROOT / "evaluation",
    ]
    for disease_key, disease_dir in DISEASE_DIRS.items():
        for root in source_roots:
            if root.name == "evaluation":
                disease_root = root / disease_key
                pattern = "*/coding/p*"
            else:
                disease_root = root / disease_key
                pattern = "*/p*"
            if not disease_root.exists():
                continue
            for src_project_dir in sorted(disease_root.glob(pattern)):
                if not src_project_dir.is_dir():
                    continue
                topic = src_project_dir.parent.parent.name if src_project_dir.parent.name == "coding" else src_project_dir.parent.name
                project = src_project_dir.name
                dst_project_dir = REPO_ROOT / "dataset" / disease_dir / "coding" / topic / project
                for src in sorted(src_project_dir.iterdir()):
                    if src.is_dir():
                        continue
                    if src.name not in {
                        "project.json",
                        "ground_truth.csv",
                        "pmids.txt",
                        "pmids_corrected_20260424.txt",
                        "doi_only_corrected_20260424.txt",
                        "reported_truth_20260424.csv",
                        "reported_truth_comparison_20260424.csv",
                        "sr_table1.csv",
                        "coverage_report.json",
                    }:
                        continue
                    result = _copy_file(src, dst_project_dir / src.name, dry_run=dry_run)
                    stats[result] = stats.get(result, 0) + 1
    return stats


def move_existing_outputs(*, dry_run: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    for disease_key, disease_dir in DISEASE_DIRS.items():
        disease_root = REPO_ROOT / "evaluation" / disease_key
        if not disease_root.exists():
            continue
        for experiments_dir in sorted(disease_root.glob("*/ground_truth/p*/experiments")):
            topic = experiments_dir.parents[2].name
            project = experiments_dir.parent.name
            dst = REPO_ROOT / "evaluation" / "screening" / disease_dir / topic / project / "experiments"
            result = _move_dir(experiments_dir, dst, dry_run=dry_run)
            stats[f"screening_{result}"] = stats.get(f"screening_{result}", 0) + 1
        for coding_runs_dir in sorted(disease_root.glob("*/coding/p*/coding_runs")):
            topic = coding_runs_dir.parents[2].name
            project = coding_runs_dir.parent.name
            dst = REPO_ROOT / "evaluation" / "coding" / disease_dir / topic / project / "coding_runs"
            result = _move_dir(coding_runs_dir, dst, dry_run=dry_run)
            stats[f"coding_{result}"] = stats.get(f"coding_{result}", 0) + 1
    return stats


def remove_empty_dirs(*, dry_run: bool = False) -> int:
    removed = 0
    for base in [
        REPO_ROOT / "evaluation" / "covid19",
        REPO_ROOT / "evaluation" / "mpox",
        REPO_ROOT / "evaluation" / "ground_truth",
    ]:
        if not base.exists():
            continue
        for path in sorted([p for p in base.rglob("*") if p.is_dir()], reverse=True):
            try:
                if dry_run:
                    if not any(path.iterdir()):
                        removed += 1
                else:
                    path.rmdir()
                    removed += 1
            except OSError:
                continue
        try:
            if dry_run:
                if not any(base.iterdir()):
                    removed += 1
            else:
                base.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def remove_evaluation_input_duplicates(*, dry_run: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    names = {
        "project.json",
        "ground_truth.csv",
        "pmids.txt",
        "pmids_corrected_20260424.txt",
        "doi_only_corrected_20260424.txt",
        "reported_truth_20260424.csv",
        "reported_truth_comparison_20260424.csv",
        "sr_table1.csv",
        "coverage_report.json",
    }
    patterns = [
        "evaluation/coding/*/*/p*/*",
        "evaluation/covid19/*/coding/p*/*",
        "evaluation/mpox/*/coding/p*/*",
        "evaluation/covid19/*/ground_truth/p*/*",
        "evaluation/mpox/*/ground_truth/p*/*",
    ]
    for pattern in patterns:
        for path in REPO_ROOT.glob(pattern):
            if path.is_dir() or path.name not in names:
                continue
            if dry_run:
                result = "would_remove"
            else:
                path.unlink()
                result = "removed"
            stats[result] = stats.get(result, 0) + 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize dataset/evaluation layout.")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without changing files")
    parser.add_argument(
        "--skip-output-move",
        action="store_true",
        help="Only sync dataset inputs; do not move existing evaluation outputs",
    )
    args = parser.parse_args()

    print("screening_inputs", sync_screening_inputs(dry_run=args.dry_run))
    print("coding_inputs", sync_coding_inputs(dry_run=args.dry_run))
    if not args.skip_output_move:
        print("output_moves", move_existing_outputs(dry_run=args.dry_run))
        print("input_duplicates_removed", remove_evaluation_input_duplicates(dry_run=args.dry_run))
        print("empty_dirs_removed", remove_empty_dirs(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
