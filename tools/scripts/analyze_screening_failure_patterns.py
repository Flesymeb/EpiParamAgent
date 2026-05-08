#!/usr/bin/env python3
"""Generate deeper screening failure-pattern analysis.

This script complements ``analyze_screening_failure_modes.py``. It reads the
same per-PMID screened CSV files, preserves the current 5D prediction rule as
the baseline, and estimates which conservative post-processing rules would
remove false positives at what recall cost.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Callable

from analyze_screening_failure_modes import (
    DEFAULT_MODEL_DISPLAY,
    DEFAULT_MODEL_SLUG,
    GT_MARKERS,
    PREDICTED_INCLUDE,
    TOPIC_LABELS,
    classify_fn,
    classify_fp,
    load_gt_pmids,
    parse_path,
    row_is_gt,
    score_dict,
)


REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ScreeningRow:
    disease: str
    topic: str
    profile: str
    project: str
    pmid: str
    title: str
    abstract_len: int
    prediction: str
    llm_tier: str
    is_gt: bool
    base_include: bool
    scores: dict[str, int]
    primary_type: str
    flags: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO))
    parser.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    parser.add_argument("--model-display", default=DEFAULT_MODEL_DISPLAY)
    parser.add_argument("--out-dir", default="")
    return parser.parse_args()


def norm(text: str | None) -> str:
    return str(text or "").strip()


def low(text: str | None) -> str:
    return norm(text).lower()


def is_ground_truth(row: dict[str, str]) -> bool:
    return low(row.get("is_ground_truth")) in GT_MARKERS or norm(row.get("is_ground_truth")) == "✓"


def is_predicted_include(row: dict[str, str]) -> bool:
    return norm(row.get("llm_suggest")) in PREDICTED_INCLUDE


def collect_rows(repo: Path, model_slug: str) -> list[ScreeningRow]:
    root = repo / "evaluation" / "screening"
    paths = sorted(root.glob(f"**/experiments/{model_slug}/project_*_screened.csv"))
    if not paths:
        raise FileNotFoundError(f"No screened CSVs found for model slug: {model_slug}")

    rows: list[ScreeningRow] = []
    for path in paths:
        disease, topic, profile, project = parse_path(path)
        gt_pmids = load_gt_pmids(repo, disease, topic, profile, project)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for raw in csv.DictReader(fh):
                prediction = norm(raw.get("llm_suggest"))
                if prediction == "error":
                    continue
                gt = row_is_gt(raw, gt_pmids)
                pred = is_predicted_include(raw)
                scores = score_dict(raw)
                if pred and not gt:
                    primary_type, flags = classify_fp(raw, topic, scores)
                elif gt and not pred:
                    primary_type, flags = classify_fn(raw, topic, scores)
                else:
                    primary_type, flags = "", ()
                rows.append(
                    ScreeningRow(
                        disease=disease,
                        topic=topic,
                        profile=profile,
                        project=project,
                        pmid=norm(raw.get("PMID")),
                        title=norm(raw.get("Title")),
                        abstract_len=len(norm(raw.get("Abstract"))),
                        prediction=prediction,
                        llm_tier=norm(raw.get("llm_tier")),
                        is_gt=gt,
                        base_include=pred,
                        scores=scores,
                        primary_type=primary_type,
                        flags=flags,
                    )
                )
    return rows


def confusion(rows: list[ScreeningRow], include_fn: Callable[[ScreeningRow], bool]) -> Counter:
    out: Counter = Counter()
    for row in rows:
        pred = include_fn(row)
        if pred and row.is_gt:
            out["TP"] += 1
        elif pred and not row.is_gt:
            out["FP"] += 1
        elif not pred and row.is_gt:
            out["FN"] += 1
        else:
            out["TN"] += 1
    return out


def metric_dict(counter: Counter) -> dict[str, float]:
    tp = counter["TP"]
    fp = counter["FP"]
    fn = counter["FN"]
    tn = counter["TN"]
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    fdr = fp / (tp + fp) if tp + fp else 0.0
    nns = (tp + fp) / tp if tp else math.inf
    wr = tn / (tn + fp) if tn + fp else 0.0
    return {
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "fdr": fdr,
        "nns": nns,
        "wr": wr,
    }


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def fmt_num(value: float) -> str:
    return "inf" if value == math.inf else f"{value:.2f}"


def rule_table(rows: list[ScreeningRow]) -> list[dict[str, object]]:
    has_5d_scores = any(row.scores["disease"] >= 0 and row.scores["evidence"] >= 0 and row.scores["parameter"] >= 0 for row in rows)
    rules: list[tuple[str, Callable[[ScreeningRow], bool], str]] = [
        (
            "Baseline: strong + possible",
            lambda row: row.base_include,
            "Current paper setting.",
        ),
        (
            "Strong only",
            lambda row: row.prediction == "strong_candidate",
            "Drops all possible-candidate papers.",
        ),
        (
            "Drop sparse possible",
            lambda row: row.base_include and not (row.prediction == "possible_candidate" and row.abstract_len < 160),
            "Keeps strong sparse records, but drops sparse possible candidates.",
        ),
    ]
    if has_5d_scores:
        rules.extend(
            [
                (
                    "Parameter score >= 3",
                    lambda row: row.base_include and row.scores["parameter"] >= 3,
                    "Removes direct weak-parameter includes.",
                ),
                (
                    "Evidence score >= 3",
                    lambda row: row.base_include and row.scores["evidence"] >= 3,
                    "Removes weak original-evidence includes.",
                ),
                (
                    "Parameter and evidence >= 3",
                    lambda row: row.base_include
                    and row.scores["parameter"] >= 3
                    and row.scores["evidence"] >= 3,
                    "Requires both parameter and empirical evidence support.",
                ),
                (
                    "Drop possible with parameter <= 2",
                    lambda row: row.base_include
                    and not (row.prediction == "possible_candidate" and row.scores["parameter"] <= 2),
                    "Targets the largest mpox FP bucket while preserving strong decisions.",
                ),
            ]
        )
    baseline = metric_dict(confusion(rows, rules[0][1]))
    table = []
    for name, include_fn, note in rules:
        metrics = metric_dict(confusion(rows, include_fn))
        table.append(
            {
                "rule": name,
                "note": note,
                **metrics,
                "delta_recall": metrics["recall"] - baseline["recall"],
                "delta_precision": metrics["precision"] - baseline["precision"],
                "delta_f1": metrics["f1"] - baseline["f1"],
                "fp_removed": baseline["FP"] - metrics["FP"],
                "tp_lost": baseline["TP"] - metrics["TP"],
            }
        )
    return table


def scope_groups(rows: list[ScreeningRow]) -> dict[tuple[str, str], list[ScreeningRow]]:
    groups: dict[tuple[str, str], list[ScreeningRow]] = defaultdict(list)
    for row in rows:
        groups[(row.disease, "all")].append(row)
        groups[(row.disease, row.topic)].append(row)
        groups[("overall", "all")].append(row)
    return groups


def profile_metrics(rows: list[ScreeningRow]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[ScreeningRow]] = defaultdict(list)
    for row in rows:
        groups[(row.disease, row.topic, row.profile)].append(row)
    out = []
    for (disease, topic, profile), subset in groups.items():
        metrics = metric_dict(confusion(subset, lambda row: row.base_include))
        out.append({"disease": disease, "topic": topic, "profile": profile, **metrics})
    return sorted(out, key=lambda item: (item["recall"], -item["fdr"], -item["FP"]))


def score_summary(rows: list[ScreeningRow]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str, str], list[ScreeningRow]] = defaultdict(list)
    for row in rows:
        pred = row.base_include
        if pred and row.is_gt:
            kind = "TP"
        elif pred and not row.is_gt:
            kind = "FP"
        elif not pred and row.is_gt:
            kind = "FN"
        else:
            kind = "TN"
        buckets[(row.disease, row.topic, kind, "all")].append(row)
        buckets[(row.disease, "all", kind, "all")].append(row)
        buckets[("overall", "all", kind, "all")].append(row)

    out = []
    for (disease, topic, kind, _), subset in sorted(buckets.items()):
        if kind not in {"TP", "FP", "FN"}:
            continue
        record: dict[str, object] = {
            "disease": disease,
            "topic": topic,
            "kind": kind,
            "n": len(subset),
        }
        for score_name in ["disease", "population", "location", "evidence", "parameter", "overall"]:
            vals = [row.scores[score_name] for row in subset if row.scores[score_name] >= 0]
            record[f"{score_name}_mean"] = mean(vals) if vals else math.nan
            record[f"{score_name}_median"] = median(vals) if vals else math.nan
        out.append(record)
    return out


def top_error_types(rows: list[ScreeningRow], disease: str, topic: str, kind: str, limit: int = 5) -> list[tuple[str, int, float]]:
    subset = [
        row
        for row in rows
        if row.disease == disease
        and (topic == "all" or row.topic == topic)
        and ((kind == "FP" and row.base_include and not row.is_gt) or (kind == "FN" and row.is_gt and not row.base_include))
    ]
    counts = Counter(row.primary_type for row in subset)
    total = len(subset)
    return [(name, count, count / total if total else 0.0) for name, count in counts.most_common(limit)]


def write_rule_csv(rows: list[dict[str, object]], out: Path) -> None:
    fields = [
        "rule",
        "TP",
        "FP",
        "FN",
        "TN",
        "recall",
        "precision",
        "f1",
        "fdr",
        "nns",
        "wr",
        "delta_recall",
        "delta_precision",
        "delta_f1",
        "fp_removed",
        "tp_lost",
        "note",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})


def write_profile_csv(rows: list[dict[str, object]], out: Path) -> None:
    fields = ["disease", "topic", "profile", "TP", "FP", "FN", "TN", "recall", "precision", "f1", "fdr", "nns", "wr"]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})


def write_score_csv(rows: list[dict[str, object]], out: Path) -> None:
    fields = list(rows[0]) if rows else []
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(
    *,
    rows: list[ScreeningRow],
    rules: list[dict[str, object]],
    profiles: list[dict[str, object]],
    out: Path,
    model_display: str,
    model_slug: str,
) -> None:
    groups = scope_groups(rows)
    lines: list[str] = []
    lines.append(f"# Screening Failure Pattern Deep Dive - {model_display}")
    lines.append("")
    lines.append(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CST")
    lines.append("")
    lines.append(f"Model slug: `{model_slug}`")
    lines.append("")
    lines.append("## Core Finding")
    lines.append("")
    lines.append(
        "The main failure pattern is not disease confusion. The model recognizes the target disease well, "
        "but its inclusion boundary is broader than the SR ground truth. False positives are mainly nearby "
        "epidemiology papers with plausible disease and evidence signals, while false negatives are mostly "
        "papers where the target parameter evidence is weak or hidden in the title/abstract."
    )
    lines.append("")
    lines.append("## Metrics By Disease And Topic")
    lines.append("")
    lines.append("| Scope | TP/FP/FN/TN | Recall | Precision | F1 | FDR | NNS | WR |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    ordered_scopes = [
        ("covid19", "all"),
        ("covid19", "fatality"),
        ("covid19", "reproduction_number"),
        ("covid19", "serial_interval"),
        ("mpox", "all"),
        ("mpox", "fatality"),
        ("mpox", "reproduction_number"),
        ("mpox", "serial_interval"),
        ("overall", "all"),
    ]
    for disease, topic in ordered_scopes:
        subset = groups.get((disease, topic), [])
        if not subset:
            continue
        metrics = metric_dict(confusion(subset, lambda row: row.base_include))
        label = "Overall" if disease == "overall" else disease if topic == "all" else f"{disease} / {TOPIC_LABELS.get(topic, topic)}"
        lines.append(
            f"| {label} | {metrics['TP']}/{metrics['FP']}/{metrics['FN']}/{metrics['TN']} | "
            f"{fmt_pct(metrics['recall'])} | {fmt_pct(metrics['precision'])} | {fmt_pct(metrics['f1'])} | "
            f"{fmt_pct(metrics['fdr'])} | {fmt_num(metrics['nns'])} | {fmt_pct(metrics['wr'])} |"
        )

    lines.append("")
    lines.append("## Dominant Error Types")
    lines.append("")
    lines.append("| Scope | FP dominant types | FN dominant types |")
    lines.append("| --- | --- | --- |")
    for disease, topic in ordered_scopes[:-1]:
        if disease == "overall":
            continue
        fp = ", ".join(f"`{name}` {fmt_pct(share)}" for name, _, share in top_error_types(rows, disease, topic, "FP", 3))
        fn = ", ".join(f"`{name}` {fmt_pct(share)}" for name, _, share in top_error_types(rows, disease, topic, "FN", 3))
        label = disease if topic == "all" else f"{disease} / {TOPIC_LABELS.get(topic, topic)}"
        lines.append(f"| {label} | {fp or 'None'} | {fn or 'None'} |")

    lines.append("")
    lines.append("## Post-Processing Rule Simulation")
    lines.append("")
    lines.append("These are post-hoc simulations over the same model outputs, not new model runs.")
    lines.append("")
    lines.append("| Rule | Recall | Precision | F1 | FDR | NNS | FP removed | TP lost | Note |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in rules:
        lines.append(
            f"| {row['rule']} | {fmt_pct(row['recall'])} | {fmt_pct(row['precision'])} | "
            f"{fmt_pct(row['f1'])} | {fmt_pct(row['fdr'])} | {fmt_num(row['nns'])} | "
            f"{row['fp_removed']} | {row['tp_lost']} | {row['note']} |"
        )

    lines.append("")
    lines.append("## Weakest Profiles")
    lines.append("")
    lines.append("Profiles are sorted by recall first, then FDR. These are the profiles to inspect before tuning.")
    lines.append("")
    lines.append("| Disease | Topic | Profile | Recall | Precision | F1 | FDR | NNS | TP/FP/FN/TN |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in profiles[:10]:
        topic_label = TOPIC_LABELS.get(str(row["topic"]), str(row["topic"]))
        lines.append(
            f"| {row['disease']} | {topic_label} | {row['profile']} | {fmt_pct(row['recall'])} | "
            f"{fmt_pct(row['precision'])} | {fmt_pct(row['f1'])} | {fmt_pct(row['fdr'])} | "
            f"{fmt_num(row['nns'])} | {row['TP']}/{row['FP']}/{row['FN']}/{row['TN']} |"
        )

    lines.append("")
    lines.append("## Failure Laws")
    lines.append("")
    lines.append("1. High recall is driven by a permissive `possible_candidate` boundary. This protects recall, but it also admits weak parameter-evidence papers.")
    lines.append("2. COVID-19 false positives are often plausible epidemiology studies outside the narrower SR GT, so many are boundary errors rather than obviously irrelevant papers.")
    lines.append("3. mpox false positives are more often metadata-limited or weakly parameter-specific, reflecting shorter abstracts and less standardized reporting.")
    lines.append("4. False negatives cluster where the target parameter is implicit, downstream of another analysis, or only visible in full text.")
    lines.append("5. A simple parameter/evidence gate can reduce FP, but the post-hoc table should be used to decide whether the recall loss is acceptable.")
    lines.append("")
    lines.append("## Practical Tuning Direction")
    lines.append("")
    lines.append("For the next 5D iteration, tune the boundary rather than the disease detector. The most defensible changes are:")
    lines.append("")
    lines.append("1. Require explicit target-parameter evidence for `strong_candidate`; keep weaker evidence as `possible_candidate` only.")
    lines.append("2. For sparse abstracts, avoid automatic inclusion unless title contains the exact target parameter or full-text rescue confirms it.")
    lines.append("3. Add full-text rescue for FN-heavy profiles before tightening too much, especially mpox fatality and COVID serial interval.")
    lines.append("4. Report FDR/NNS alongside recall so LEADS and keyword baselines cannot look strong solely because they over-include.")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    repo = Path(args.project_root).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (
        repo / "evaluation" / "results" / f"failure_patterns_{args.model_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = collect_rows(repo, args.model_slug)
    rules = rule_table(rows)
    profiles = profile_metrics(rows)
    scores = score_summary(rows)

    write_rule_csv(rules, out_dir / "postprocessing_rule_simulation.csv")
    write_profile_csv(profiles, out_dir / "profile_metric_risk_ranking.csv")
    write_score_csv(scores, out_dir / "score_distribution_by_outcome.csv")
    write_markdown(
        rows=rows,
        rules=rules,
        profiles=profiles,
        out=out_dir / "FAILURE_PATTERN_DEEP_DIVE.md",
        model_display=args.model_display,
        model_slug=args.model_slug,
    )
    print(f"Rows: {len(rows)}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
