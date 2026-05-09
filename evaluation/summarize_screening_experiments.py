#!/usr/bin/env python3
"""Summarize frozen screening experiment metrics across COVID-19 and mpox."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASET_ROOT = REPO / "dataset"
EVAL_ROOT = REPO / "evaluation" / "screening"
OUT_DIR = REPO / "evaluation" / "results"

PROJECTS: tuple[tuple[str, str, int], ...] = (
    ("covid19", "fatality", 4),
    ("covid19", "fatality", 5),
    ("covid19", "fatality", 6),
    ("covid19", "reproduction_number", 7),
    ("covid19", "reproduction_number", 8),
    ("covid19", "reproduction_number", 15),
    ("covid19", "reproduction_number", 16),
    ("covid19", "reproduction_number", 17),
    ("covid19", "serial_interval", 10),
    ("covid19", "serial_interval", 11),
    ("covid19", "serial_interval", 12),
    ("covid19", "serial_interval", 13),
    ("covid19", "serial_interval", 14),
    ("mpox", "fatality", 4),
    ("mpox", "fatality", 7),
    ("mpox", "fatality", 8),
    ("mpox", "fatality", 12),
    ("mpox", "reproduction_number", 9),
    ("mpox", "serial_interval", 5),
    ("mpox", "serial_interval", 6),
    ("mpox", "serial_interval", 10),
    ("mpox", "serial_interval", 11),
)

INCLUDE_LABELS = {"strong_candidate", "possible_candidate"}


@dataclass(frozen=True)
class Metrics:
    disease: str
    topic: str
    project: int
    experiment: str
    gt: int
    total: int
    tp: int
    fp: int
    fn: int
    tn: int
    strong: int
    possible: int
    unlikely: int
    errors: int
    missing_gt: int

    @property
    def recall(self) -> float:
        return self.tp / self.gt if self.gt else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        r, p = self.recall, self.precision
        return 2 * r * p / (r + p) if r + p else 0.0

    @property
    def workload_reduction(self) -> float:
        return self.tn / self.total if self.total else 0.0

    @property
    def nns(self) -> float:
        return 1 / self.precision if self.precision else 0.0

    @property
    def fdr(self) -> float:
        return 1 - self.precision if self.tp + self.fp else 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_gt(disease: str, topic: str, project: int) -> set[str]:
    path = DATASET_ROOT / disease / "screening" / topic / f"p{project}" / "ground_truth.csv"
    gt: set[str] = set()
    for row in read_csv(path):
        for col in ("PMID", "pmid", "gt_pmid"):
            value = (row.get(col) or "").strip()
            if value.isdigit():
                exclude = (row.get("exclude_flag") or "").strip().lower()
                if exclude not in {"review_low_evidence", "review", "low_evidence"}:
                    gt.add(value)
                break
    return gt


def row_pmid(row: dict[str, str]) -> str:
    for col in ("PMID", "pmid", "gt_pmid"):
        value = (row.get(col) or "").strip()
        if value:
            return value
    return ""


def row_label(row: dict[str, str]) -> str:
    label = (row.get("llm_suggest") or row.get("prediction") or "").strip()
    if label:
        return label
    predicted = (row.get("predicted_include") or "").strip().lower()
    if predicted in {"1", "true", "yes", "include"}:
        return "possible_candidate"
    if predicted in {"0", "false", "no", "exclude"}:
        return "unlikely_candidate"
    return ""


def evaluate_file(path: Path, disease: str, topic: str, project: int, experiment: str) -> Metrics:
    rows = read_csv(path)
    gt = load_gt(disease, topic, project)
    valid: list[dict[str, str]] = []
    errors = 0
    for row in rows:
        label = row_label(row)
        if label == "error":
            errors += 1
            continue
        if row_pmid(row):
            valid.append(row)

    included = [row for row in valid if row_label(row) in INCLUDE_LABELS]
    included_pmids = {row_pmid(row) for row in included}
    valid_pmids = {row_pmid(row) for row in valid}

    tp = len(included_pmids & gt)
    fp = len([row for row in included if row_pmid(row) not in gt])
    fn = len(gt - included_pmids)
    tn = len([row for row in valid if row_label(row) not in INCLUDE_LABELS and row_pmid(row) not in gt])
    strong = sum(1 for row in valid if row_label(row) == "strong_candidate")
    possible = sum(1 for row in valid if row_label(row) == "possible_candidate")
    unlikely = sum(1 for row in valid if row_label(row) == "unlikely_candidate")
    return Metrics(
        disease=disease,
        topic=topic,
        project=project,
        experiment=experiment,
        gt=len(gt),
        total=len(valid),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        strong=strong,
        possible=possible,
        unlikely=unlikely,
        errors=errors,
        missing_gt=len(gt - valid_pmids),
    )


def experiment_files() -> list[tuple[str, str, int, str, Path]]:
    files: list[tuple[str, str, int, str, Path]] = []
    for disease, topic, project in PROJECTS:
        exp_root = EVAL_ROOT / disease / topic / f"p{project}" / "experiments"
        if not exp_root.exists():
            continue
        for exp_dir in sorted(path for path in exp_root.iterdir() if path.is_dir()):
            path = exp_dir / f"project_{project}_screened.csv"
            if path.exists():
                files.append((disease, topic, project, exp_dir.name, path))
    return files


def aggregate(metrics: list[Metrics]) -> dict[str, float | int | str]:
    totals = {
        "profiles": len(metrics),
        "gt": sum(item.gt for item in metrics),
        "total": sum(item.total for item in metrics),
        "tp": sum(item.tp for item in metrics),
        "fp": sum(item.fp for item in metrics),
        "fn": sum(item.fn for item in metrics),
        "tn": sum(item.tn for item in metrics),
        "strong": sum(item.strong for item in metrics),
        "possible": sum(item.possible for item in metrics),
        "unlikely": sum(item.unlikely for item in metrics),
        "errors": sum(item.errors for item in metrics),
        "missing_gt": sum(item.missing_gt for item in metrics),
    }
    recall = totals["tp"] / totals["gt"] if totals["gt"] else 0.0
    precision = totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    totals.update(
        {
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "fdr": 1 - precision if totals["tp"] + totals["fp"] else 0.0,
            "nns": 1 / precision if precision else 0.0,
            "workload_reduction": totals["tn"] / totals["total"] if totals["total"] else 0.0,
        }
    )
    return totals


def wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    per_file = [
        evaluate_file(path, disease, topic, project, experiment)
        for disease, topic, project, experiment, path in experiment_files()
    ]
    by_exp: dict[str, list[Metrics]] = defaultdict(list)
    by_scope: dict[tuple[str, str, str], list[Metrics]] = defaultdict(list)
    for item in per_file:
        by_exp[item.experiment].append(item)
        by_scope[(item.experiment, item.disease, item.topic)].append(item)

    complete = {
        exp: items
        for exp, items in by_exp.items()
        if len({(item.disease, item.topic, item.project) for item in items}) == len(PROJECTS)
    }
    partial = {
        exp: items
        for exp, items in by_exp.items()
        if exp not in complete and len(items) >= 3
    }

    def summary_rows(grouped: dict[str, list[Metrics]]) -> list[dict[str, object]]:
        rows = []
        for exp, items in sorted(grouped.items()):
            totals = aggregate(items)
            r_ci = wilson_ci(float(totals["recall"]), int(totals["gt"]))
            p_ci = wilson_ci(float(totals["precision"]), int(totals["tp"]) + int(totals["fp"]))
            rows.append(
                {
                    "experiment": exp,
                    **totals,
                    "recall_ci_low": r_ci[0],
                    "recall_ci_high": r_ci[1],
                    "precision_ci_low": p_ci[0],
                    "precision_ci_high": p_ci[1],
                }
            )
        rows.sort(key=lambda row: (-int(row["profiles"]), -float(row["f1"]), -float(row["precision"])))
        return rows

    complete_rows = summary_rows(complete)
    partial_rows = summary_rows(partial)
    per_profile_rows = [
        {
            "experiment": item.experiment,
            "disease": item.disease,
            "topic": item.topic,
            "project": item.project,
            "gt": item.gt,
            "total": item.total,
            "tp": item.tp,
            "fp": item.fp,
            "fn": item.fn,
            "tn": item.tn,
            "strong": item.strong,
            "possible": item.possible,
            "unlikely": item.unlikely,
            "errors": item.errors,
            "missing_gt": item.missing_gt,
            "recall": item.recall,
            "precision": item.precision,
            "f1": item.f1,
            "fdr": item.fdr,
            "nns": item.nns,
            "workload_reduction": item.workload_reduction,
        }
        for item in sorted(per_file, key=lambda x: (x.experiment, x.disease, x.topic, x.project))
    ]
    scope_rows = []
    for (exp, disease, topic), items in sorted(by_scope.items()):
        totals = aggregate(items)
        scope_rows.append({"experiment": exp, "disease": disease, "topic": topic, **totals})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "screening_experiment_summary_complete.csv", complete_rows)
    write_csv(OUT_DIR / "screening_experiment_summary_partial.csv", partial_rows)
    write_csv(OUT_DIR / "screening_experiment_by_scope.csv", scope_rows)
    write_csv(OUT_DIR / "screening_experiment_by_profile.csv", per_profile_rows)
    (OUT_DIR / "screening_experiment_summary_complete.json").write_text(
        json.dumps(complete_rows, indent=2), encoding="utf-8"
    )

    top = complete_rows[:12]
    lines = ["# Frozen Screening Experiment Summary", ""]
    lines.append("Complete experiments cover all 22 frozen profiles.")
    lines.append("")
    lines.append("| Experiment | Profiles | TP/FP/FN | Recall | Precision | F1 | NNS | WR |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in top:
        lines.append(
            "| {experiment} | {profiles} | {tp}/{fp}/{fn} | {recall} | {precision} | {f1:.3f} | {nns:.2f} | {wr} |".format(
                experiment=row["experiment"],
                profiles=row["profiles"],
                tp=row["tp"],
                fp=row["fp"],
                fn=row["fn"],
                recall=pct(float(row["recall"])),
                precision=pct(float(row["precision"])),
                f1=float(row["f1"]),
                nns=float(row["nns"]),
                wr=pct(float(row["workload_reduction"])),
            )
        )
    lines.append("")
    lines.append(f"Complete experiments: {len(complete_rows)}")
    lines.append(f"Partial experiments with >=3 profiles: {len(partial_rows)}")
    (OUT_DIR / "SCREENING_EXPERIMENT_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Complete experiments: {len(complete_rows)}")
    for row in top[:8]:
        print(
            f"{row['experiment']}: profiles={row['profiles']} "
            f"R={float(row['recall']):.3f} P={float(row['precision']):.3f} "
            f"F1={float(row['f1']):.3f} TP/FP/FN={row['tp']}/{row['fp']}/{row['fn']}"
        )


if __name__ == "__main__":
    main()
