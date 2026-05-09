#!/usr/bin/env python3
"""Summarize P13 full-text tier-2 pilot."""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO / "evaluation" / "screening_prompt_eval" / "retrieval_enriched_20260509"
DOC_DIR = REPO / "docs" / "paper" / "screening" / "full-text"
EXP = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
BASELINE = (
    REPO
    / "evaluation"
    / "screening"
    / "covid19"
    / "serial_interval"
    / "p13"
    / "experiments"
    / EXP
    / "project_13_screened.csv"
)
GT = REPO / "dataset" / "covid19" / "screening" / "serial_interval" / "p13" / "ground_truth.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def gt_pmids() -> set[str]:
    pmids: set[str] = set()
    for row in read_csv(GT):
        for col in ("PMID", "pmid", "gt_pmid"):
            value = (row.get(col) or "").strip()
            if value.isdigit():
                pmids.add(value)
                break
    return pmids


def include(row: dict[str, str]) -> bool:
    return row.get("llm_suggest") in {"strong_candidate", "possible_candidate"}


def metrics(rows: list[dict[str, str]], gt: set[str]) -> dict[str, float | int]:
    valid = [row for row in rows if row.get("llm_suggest") != "error"]
    included = [row for row in valid if include(row)]
    tp = sum(1 for row in included if (row.get("PMID") or "").strip() in gt)
    fp = len(included) - tp
    gt_n = sum(1 for row in valid if (row.get("PMID") or "").strip() in gt)
    fn = gt_n - tp
    recall = tp / gt_n if gt_n else 0.0
    precision = tp / len(included) if included else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "included": len(included),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "nns": 1 / precision if precision else 0.0,
    }


def scope(name: str) -> dict[str, dict[str, str]]:
    paths = {
        "strong_only": EVAL_DIR / "covid19_serial_interval_p13_retrieval_screened_strong_hard_exclusion_snippet_dsv4pro.csv",
        "possible_only": EVAL_DIR / "covid19_serial_interval_p13_retrieval_screened_possible_only_snippet_dsv4pro.csv",
        "u_conservative": EVAL_DIR / "covid19_serial_interval_p13_retrieval_screened_u_conservative_snippet_dsv4pro.csv",
    }
    path = paths.get(name, EVAL_DIR / f"covid19_serial_interval_p13_retrieval_screened_{name}_dsv4pro.csv")
    return {(row.get("PMID") or "").strip(): row for row in read_csv(path)}


def apply_scope(rows: list[dict[str, str]], scope_rows: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    merged = [dict(row) for row in rows]
    for row in merged:
        tuned = scope_rows.get((row.get("PMID") or "").strip())
        if tuned and tuned.get("review_content_source") and tuned.get("llm_suggest") != "error":
            row["llm_suggest"] = tuned.get("llm_suggest", row.get("llm_suggest", ""))
            row["llm_tier"] = tuned.get("llm_tier", row.get("llm_tier", ""))
    return merged


def format_count(value: object, delta: int) -> str:
    if delta == 0:
        return str(value)
    arrow = r"$\uparrow$" if delta > 0 else r"$\downarrow$"
    return f"{value} ({arrow}{abs(delta)})"


def main() -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    gt = gt_pmids()
    baseline = read_csv(BASELINE)
    s = scope("strong_only")
    p = scope("possible_only")
    u = scope("u_conservative")

    strategies = {
        "Baseline": baseline,
        "S-only hard-exclusion": apply_scope(baseline, s),
        "P-only full text": apply_scope(baseline, p),
        "U-only full text": apply_scope(baseline, u),
        "P+U full text": apply_scope(apply_scope(baseline, p), u),
        "S+P+U full text": apply_scope(apply_scope(apply_scope(baseline, s), p), u),
    }
    base = metrics(baseline, gt)
    rows: list[dict[str, object]] = []
    for strategy, data in strategies.items():
        m = metrics(data, gt)
        rows.append(
            {
                "strategy": strategy,
                **m,
                "delta_tp": int(m["tp"]) - int(base["tp"]),
                "delta_fp": int(m["fp"]) - int(base["fp"]),
                "delta_fn": int(m["fn"]) - int(base["fn"]),
            }
        )

    write_csv(DOC_DIR / "fulltext_tier2_p13_ablation_summary.csv", rows)
    (DOC_DIR / "fulltext_tier2_p13_ablation_summary.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )

    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Full-text tier-2 bucket ablation on COVID-19 P13 using direct PMC/cached full text and DeepSeek-v4-Pro. Counts in parentheses show changes relative to the stage-1 baseline.}",
        r"\label{tab:fulltext-tier2-p13}",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r"Strategy & TP & FP & FN & Recall & Precision & F1 & NNS \\",
        r"\midrule",
    ]
    for row in rows:
        bold = row["strategy"] == "P+U full text"
        cells = [
            str(row["strategy"]),
            format_count(row["tp"], int(row["delta_tp"])),
            format_count(row["fp"], int(row["delta_fp"])),
            format_count(row["fn"], int(row["delta_fn"])),
            f"{float(row['recall']):.3f}",
            f"{float(row['precision']):.3f}",
            f"{float(row['f1']):.3f}",
            f"{float(row['nns']):.2f}",
        ]
        if bold:
            cells = [rf"\textbf{{{cell}}}" for cell in cells]
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (DOC_DIR / "fulltext_tier2_p13_ablation_table.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    report = [
        "# Full-text tier-2 ablation: COVID-19 P13",
        "",
        "| Strategy | TP | FP | FN | Recall | Precision | F1 | NNS |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['strategy']} | {row['tp']} | {row['fp']} | {row['fn']} | "
            f"{float(row['recall']):.3f} | {float(row['precision']):.3f} | "
            f"{float(row['f1']):.3f} | {float(row['nns']):.2f} |"
        )
    report += [
        "",
        "P13 is a stricter test than P12. After target-window snippet extraction from cached/direct-PMC full text, P-only full-text review substantially reduces FP without reducing TP, while conservative U-only rescue recovers three FN without adding FP. A conservative S hard-exclusion audit preserves recall and removes one clear FP, but its incremental gain is small because most strong FP also contain genuine target-parameter evidence. The recommended tier-2 policy is P+U, optionally with S hard-exclusion audit when full recall preservation is confirmed.",
    ]
    (DOC_DIR / "fulltext_tier2_p13_ablation_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
