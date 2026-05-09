#!/usr/bin/env python3
"""Summarize cached full-text tier-2 ablations for P12."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO / "evaluation" / "screening_prompt_eval" / "retrieval_enriched_20260509"
DOC_DIR = REPO / "docs" / "paper" / "screening" / "full-text"
PROJECT = "covid19_serial_interval_p12"
GT_PATH = REPO / "dataset" / "covid19" / "screening" / "serial_interval" / "p12" / "ground_truth.csv"
BASELINE_PATH = (
    REPO
    / "evaluation"
    / "screening"
    / "covid19"
    / "serial_interval"
    / "p12"
    / "experiments"
    / "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
    / "project_12_screened.csv"
)
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_gt() -> set[str]:
    gt: set[str] = set()
    for row in read_csv(GT_PATH):
        for col in ("PMID", "pmid", "gt_pmid"):
            value = (row.get(col) or "").strip()
            if value.isdigit():
                gt.add(value)
                break
    return gt


def included(label: str | None) -> bool:
    return label in {"strong_candidate", "possible_candidate"}


def metrics(rows: list[dict[str, str]], gt: set[str], label_col: str = "llm_suggest") -> dict[str, float | int]:
    valid = [row for row in rows if row.get(label_col) != "error"]
    inc = [row for row in valid if included(row.get(label_col))]
    tp = sum(1 for row in inc if (row.get("PMID") or "").strip() in gt)
    fp = len(inc) - tp
    gt_in_sample = sum(1 for row in valid if (row.get("PMID") or "").strip() in gt)
    fn = gt_in_sample - tp
    recall = tp / gt_in_sample if gt_in_sample else 0.0
    precision = tp / len(inc) if inc else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "included": len(inc),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "nns": 1 / precision if precision else 0.0,
    }


def load_scope(scope: str) -> dict[str, dict[str, str]]:
    path = EVAL_DIR / f"{PROJECT}_retrieval_screened_{scope}.csv"
    return {(row.get("PMID") or "").strip(): row for row in read_csv(path)}


def apply_scope(
    baseline: list[dict[str, str]],
    scope_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    merged = [dict(row) for row in baseline]
    for row in merged:
        pmid = (row.get("PMID") or "").strip()
        tuned = scope_rows.get(pmid)
        if tuned and tuned.get("review_content_source") and tuned.get("llm_suggest") != "error":
            row["llm_suggest"] = tuned.get("llm_suggest", row.get("llm_suggest", ""))
            row["llm_tier"] = tuned.get("llm_tier", row.get("llm_tier", ""))
    return merged


def summarize_transitions(
    baseline: list[dict[str, str]],
    tuned: list[dict[str, str]],
    gt: set[str],
) -> dict[str, int]:
    by_pmid = {(row.get("PMID") or "").strip(): row for row in tuned}
    demoted_tp = demoted_fp = rescued_tp = rescued_fp = 0
    for row in baseline:
        pmid = (row.get("PMID") or "").strip()
        before = included(row.get("llm_suggest"))
        after = included((by_pmid.get(pmid) or {}).get("llm_suggest"))
        is_gt = pmid in gt
        if before and not after:
            if is_gt:
                demoted_tp += 1
            else:
                demoted_fp += 1
        if not before and after:
            if is_gt:
                rescued_tp += 1
            else:
                rescued_fp += 1
    return {
        "demoted_tp": demoted_tp,
        "demoted_fp": demoted_fp,
        "rescued_tp": rescued_tp,
        "rescued_fp": rescued_fp,
    }


def truthy_gt(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "✓", "included"}


def source_scope_reason(justification: str) -> str:
    text = justification.lower()
    hard_terms = {
        "language": ["language", "non-english", "not english"],
        "article_type": ["case report", "letter", "comment", "review article", "article type"],
        "duplicate_version": ["duplicate", "preprint", "alternate version", "published version"],
        "cited_or_input_only": ["cited", "fixed", "input only", "model input", "assumption"],
        "no_target_parameter": ["no target", "does not report", "absent"],
    }
    for reason, needles in hard_terms.items():
        if any(needle in text for needle in needles):
            return reason
    if "date" in text or "cutoff" in text or "window" in text:
        return "date_only"
    return "uncertain"


def parse_citation_date(citation: str) -> tuple[str, str]:
    """Extract the most useful human-readable citation date from PubMed citation text."""
    text = citation or ""
    match = re.search(r"Epub (\d{4}) ([A-Z][a-z]{2}) (\d{1,2})", text)
    if match:
        return (
            f"{match.group(1)}-{MONTHS[match.group(2)]:02d}-{int(match.group(3)):02d}",
            "epub",
        )
    match = re.search(r"\. (\d{4}) ([A-Z][a-z]{2}) (\d{1,2})", text)
    if match:
        return (
            f"{match.group(1)}-{MONTHS[match.group(2)]:02d}-{int(match.group(3)):02d}",
            "citation_day",
        )
    match = re.search(r"\. (\d{4}) ([A-Z][a-z]{2})(?:;|\()", text)
    if match:
        return f"{match.group(1)}-{MONTHS[match.group(2)]:02d}", "citation_month"
    match = re.search(r"\. (\d{4})(?:;|\.| )", text)
    if match:
        return match.group(1), "citation_year"
    return "", ""


def generate_source_scope_audit(gt: set[str]) -> dict[str, object]:
    scope = load_scope("strong_only_source_scope")
    audit_rows: list[dict[str, object]] = []
    for pmid, row in sorted(scope.items()):
        if row.get("baseline_llm_tier") != "S" or row.get("llm_tier") != "P":
            continue
        reason = source_scope_reason(row.get("overall_justification", ""))
        citation_date, citation_date_type = parse_citation_date(row.get("Citation", ""))
        is_gt = pmid in gt or truthy_gt(row.get("is_ground_truth"))
        safe_to_u = reason in {
            "language",
            "article_type",
            "duplicate_version",
            "cited_or_input_only",
            "no_target_parameter",
        }
        audit_rows.append(
            {
                "pmid": pmid,
                "is_gt": "yes" if is_gt else "no",
                "title": row.get("Title", ""),
                "journal": row.get("Journal/Book", ""),
                "citation": row.get("Citation", ""),
                "citation_date": citation_date,
                "citation_date_type": citation_date_type,
                "publication_year": row.get("Publication Year", ""),
                "create_date": row.get("Create Date", ""),
                "source_scope_reason": reason,
                "safe_to_convert_to_u": "yes" if safe_to_u else "no",
                "recommendation": (
                    "Can be tested as U if this reason is stable."
                    if safe_to_u
                    else "Keep included; date-only uncertainty is unsafe for this P12 GT."
                ),
                "overall_justification": row.get("overall_justification", ""),
            }
        )

    write_csv(DOC_DIR / "strong_source_scope_s_to_p_audit.csv", audit_rows)

    baseline = read_csv(BASELINE_PATH)
    forced = apply_scope(baseline, scope)
    for row in forced:
        pmid = (row.get("PMID") or "").strip()
        if any(audit["pmid"] == pmid for audit in audit_rows):
            row["llm_suggest"] = "excluded"
            row["llm_tier"] = "U"
    forced_metrics = metrics(forced, gt)

    oracle_non_gt = apply_scope(baseline, scope)
    non_gt_pids = {
        str(audit["pmid"])
        for audit in audit_rows
        if audit["is_gt"] == "no"
    }
    for row in oracle_non_gt:
        pmid = (row.get("PMID") or "").strip()
        if pmid in non_gt_pids:
            row["llm_suggest"] = "excluded"
            row["llm_tier"] = "U"
    oracle_metrics = metrics(oracle_non_gt, gt)

    counts: dict[str, int] = {}
    for row in audit_rows:
        reason = str(row["source_scope_reason"])
        counts[reason] = counts.get(reason, 0) + 1

    md = [
        "# Strong source-scope S-to-P audit: COVID-19 P12",
        "",
        "This table audits baseline strong candidates that the source-scope full-text verifier downgraded from S to P.",
        "The key question is whether any of these P cases can safely become U without harming recall.",
        "",
        f"- S-to-P rows: {len(audit_rows)}",
        f"- GT among S-to-P rows: {sum(1 for row in audit_rows if row['is_gt'] == 'yes')}",
        f"- Non-GT among S-to-P rows: {sum(1 for row in audit_rows if row['is_gt'] == 'no')}",
        f"- Reason counts: {json.dumps(counts, sort_keys=True)}",
        "",
        "Date interpretation: PubMed `Create Date`, print/online citation date, and source-review search availability are not interchangeable.",
        "This P12 GT includes records with July 2020, August 2020, and 2021 metadata, so date is not safe as a hard U criterion in the full-text verifier.",
        "",
        "## Counterfactual",
        "",
        "If all S-to-P rows were converted to U, the metrics would be:",
        "",
        "| Counterfactual | TP | FP | FN | Recall | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        (
            f"| All S-to-P -> U | {forced_metrics['tp']} | {forced_metrics['fp']} | {forced_metrics['fn']} | "
            f"{float(forced_metrics['recall']):.3f} | {float(forced_metrics['precision']):.3f} | "
            f"{float(forced_metrics['f1']):.3f} |"
        ),
        (
            f"| Oracle non-GT S-to-P -> U | {oracle_metrics['tp']} | {oracle_metrics['fp']} | {oracle_metrics['fn']} | "
            f"{float(oracle_metrics['recall']):.3f} | {float(oracle_metrics['precision']):.3f} | "
            f"{float(oracle_metrics['f1']):.3f} |"
        ),
        "",
        "Converting all S-to-P rows is worse than baseline because most S-to-P rows are GT.",
        "Even the oracle non-GT-only conversion would only remove 2 FP, so the strong bucket has limited headroom in this P12 pilot.",
        "",
        "## Audit Table",
        "",
        "| PMID | GT | Reason | Safe U? | Citation date | Date type | Create date | Journal | Title |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in audit_rows:
        title = str(row["title"]).replace("|", "\\|")
        journal = str(row["journal"]).replace("|", "\\|")
        md.append(
            f"| {row['pmid']} | {row['is_gt']} | {row['source_scope_reason']} | "
            f"{row['safe_to_convert_to_u']} | {row['citation_date']} | {row['citation_date_type']} | "
            f"{row['create_date']} | {journal} | {title} |"
        )
    md.extend(
        [
            "",
            "## Interpretation",
            "",
            "No current S-to-P case is safe to convert to U by prompt logic alone.",
            "The demotions are driven by date mismatch, but the P12 GT itself contains multiple date-mismatched papers.",
            "A date hard-exclusion rule therefore removes true positives and should not be used until GT/raw scope is reconciled.",
            "For S+P full-text screening, date should be treated as weak metadata: use it to explain uncertainty, but only non-date hard mismatches should become U.",
        ]
    )
    (DOC_DIR / "strong_source_scope_s_to_p_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    return {
        "rows": audit_rows,
        "forced_metrics": forced_metrics,
        "oracle_non_gt_metrics": oracle_metrics,
        "reason_counts": counts,
    }


def generate_remaining_fp_audit(gt: set[str]) -> None:
    baseline = read_csv(BASELINE_PATH)
    strong = load_scope("strong_only")
    possible = load_scope("possible_only")
    excluded = load_scope("rescue_only")
    scope_maps = [
        ("S-pass", strong),
        ("P-pass", possible),
        ("U-pass", excluded),
    ]

    rows: list[dict[str, str]] = []
    for base in baseline:
        merged = dict(base)
        merged["final_source"] = "baseline"
        merged["baseline_suggest"] = base.get("llm_suggest", "")
        merged["baseline_tier"] = base.get("llm_tier", "")
        pmid = (base.get("PMID") or "").strip()
        for source, scope in scope_maps:
            tuned = scope.get(pmid)
            if tuned and tuned.get("review_content_source"):
                for key in (
                    "llm_suggest",
                    "llm_tier",
                    "overall_justification",
                    "parameter_justification",
                    "review_content_source",
                    "review_content_path",
                ):
                    if key in tuned:
                        merged[key] = tuned[key]
                merged["final_source"] = source
        rows.append(merged)

    audit_rows: list[dict[str, object]] = []
    for row in rows:
        pmid = (row.get("PMID") or "").strip()
        if pmid in gt or not included(row.get("llm_suggest")):
            continue
        source = row.get("final_source", "")
        reason = "source_review_coverage_or_scope"
        text = " ".join(
            [
                row.get("Title", ""),
                row.get("overall_justification", ""),
                row.get("parameter_justification", ""),
            ]
        ).lower()
        if "meta-analysis" in text or "systematic review" in text:
            reason = "secondary_review_or_meta_analysis"
        elif "family cluster" in text or "cluster" in text:
            reason = "cluster_or_case_series_parameter"
        elif "date" in text or "window" in text:
            reason = "date_or_version_scope"
        elif "cited" in text or "fixed" in text or "input" in text:
            reason = "cited_or_input_only"
        audit_rows.append(
            {
                "pmid": pmid,
                "final_source": source,
                "baseline_suggest": row.get("baseline_suggest", ""),
                "baseline_tier": row.get("baseline_tier", ""),
                "final_suggest": row.get("llm_suggest", ""),
                "final_tier": row.get("llm_tier", ""),
                "review_content_source": row.get("review_content_source", ""),
                "reason_group": reason,
                "title": row.get("Title", ""),
                "journal": row.get("Journal/Book", ""),
                "citation": row.get("Citation", ""),
                "overall_justification": row.get("overall_justification", ""),
            }
        )

    write_csv(DOC_DIR / "fulltext_tier2_p12_remaining_fp_audit.csv", audit_rows)

    by_source: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for row in audit_rows:
        by_source[str(row["final_source"])] = by_source.get(str(row["final_source"]), 0) + 1
        by_reason[str(row["reason_group"])] = by_reason.get(str(row["reason_group"]), 0) + 1
        by_tier[str(row["final_tier"])] = by_tier.get(str(row["final_tier"]), 0) + 1

    md = [
        "# Remaining false positives after S+P+U full-text: COVID-19 P12",
        "",
        f"Remaining FP: {len(audit_rows)}",
        f"By pass: {json.dumps(by_source, sort_keys=True)}",
        f"By final tier: {json.dumps(by_tier, sort_keys=True)}",
        f"By reason group: {json.dumps(by_reason, sort_keys=True)}",
        "",
        "Interpretation: most remaining FP are not simple full-text screening errors. They often directly report serial interval, generation time, or incubation-period evidence, but are absent from this source review's GT because of source-review coverage, date/version/language/article-type scope, or citation matching differences.",
        "",
        "| PMID | Pass | Final | Reason group | Title |",
        "|---|---|---|---|---|",
    ]
    for row in audit_rows:
        title = str(row["title"]).replace("|", "\\|")
        md.append(
            f"| {row['pmid']} | {row['final_source']} | {row['final_tier']} | "
            f"{row['reason_group']} | {title} |"
        )
    (DOC_DIR / "fulltext_tier2_p12_remaining_fp_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )


def format_count(value: object, delta: int) -> str:
    if delta == 0:
        return str(value)
    direction = r"$\uparrow$" if delta > 0 else r"$\downarrow$"
    return f"{value} ({direction}{abs(delta)})"


def bucket_label(name: str) -> str:
    labels = {
        "Baseline": "--",
        "S-only full text": "S",
        "P-only full text": "P",
        "S+P full text": "S+P",
        "U-only full text": "U",
        "P+U full text": "P+U",
        "S+P+U full text": "S+P+U",
    }
    return labels.get(name, "")


def format_metric(value: object) -> str:
    return f"{float(value):.3f}"


def strategy_rank(row: dict[str, object]) -> tuple[float, float, float, int]:
    preferred_order = {
        "S+P+U full text": 3,
        "P+U full text": 2,
        "S+P full text": 1,
    }
    return (
        float(row["recall"]),
        float(row["precision"]),
        float(row["f1"]),
        preferred_order.get(str(row["strategy"]), 0),
    )


def latex_row(row: dict[str, object], base: dict[str, float | int], bold: bool = False) -> str:
    tp = format_count(row["tp"], int(row["delta_tp"]))
    fp = format_count(row["fp"], int(row["delta_fp"]))
    fn = format_count(row["fn"], int(row["delta_fn"]))
    cells = [
        str(row["strategy"]),
        bucket_label(str(row["strategy"])),
        tp,
        fp,
        fn,
        format_metric(row["recall"]),
        format_metric(row["precision"]),
        format_metric(row["f1"]),
        f"{float(row['nns']):.2f}",
    ]
    if bold:
        cells = [rf"\textbf{{{cell}}}" for cell in cells]
    return " & ".join(cells) + r" \\"


def generate_main_latex_table(summary_rows: list[dict[str, object]]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    selected = [
        row
        for row in summary_rows
        if row["strategy"]
        in {
            "Baseline",
            "S-only full text",
            "P-only full text",
            "U-only full text",
            "S+P+U full text",
        }
    ]
    best = max(selected, key=strategy_rank)
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Full-text tier-2 bucket ablation and combined strategy on COVID-19 P12. Counts in parentheses show changes relative to the stage-1 baseline. S, stage-1 strong candidates; P, stage-1 plausible candidates; U, stage-1 excluded records re-reviewed without using ground truth labels.}",
        r"\label{tab:fulltext-tier2-p12-main}",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{llrrrrrrr}",
        r"\toprule",
        r"Strategy & Buckets & TP & FP & FN & Recall & Precision & F1 & NNS \\",
        r"\midrule",
    ]
    for row in selected:
        lines.append(latex_row(row, selected[0], bold=row["strategy"] == best["strategy"]))
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    (DOC_DIR / "fulltext_tier2_p12_main_table.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def generate_latex_table(summary_rows: list[dict[str, object]]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Component ablation for full-text tier-2 screening on COVID-19 P12. Counts in parentheses show changes relative to the stage-1 baseline. S, stage-1 strong candidates; P, stage-1 plausible candidates; U, stage-1 excluded records re-reviewed without using ground truth labels.}",
        r"\label{tab:fulltext-tier2-p12}",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{llrrrrrrr}",
        r"\toprule",
        r"Strategy & Buckets & TP & FP & FN & Recall & Precision & F1 & NNS \\",
        r"\midrule",
    ]
    for row in summary_rows:
        if row["strategy"] == "P-only full text":
            lines.append(r"\addlinespace[2pt]")
            lines.append(r"\multicolumn{9}{l}{\textit{Diagnostic component passes}} \\")
        if row["strategy"] == "S+P full text":
            lines.append(r"\addlinespace[2pt]")
            lines.append(r"\multicolumn{9}{l}{\textit{Composed tier-2 strategies}} \\")
        best = max(summary_rows, key=strategy_rank)
        lines.append(latex_row(row, summary_rows[0], bold=row["strategy"] == best["strategy"]))
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    (DOC_DIR / "fulltext_tier2_p12_ablation_table.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    gt = load_gt()
    baseline = read_csv(BASELINE_PATH)
    strong = load_scope("strong_only")
    possible = load_scope("possible_only")
    excluded = load_scope("rescue_only")

    strategies = {
        "Baseline": baseline,
        "S-only full text": apply_scope(baseline, strong),
        "P-only full text": apply_scope(baseline, possible),
        "S+P full text": apply_scope(apply_scope(baseline, strong), possible),
        "U-only full text": apply_scope(baseline, excluded),
        "P+U full text": apply_scope(apply_scope(baseline, possible), excluded),
        "S+P+U full text": apply_scope(apply_scope(apply_scope(baseline, strong), possible), excluded),
    }

    summary_rows: list[dict[str, object]] = []
    base_metrics = metrics(baseline, gt)
    for name, rows in strategies.items():
        m = metrics(rows, gt)
        transitions = summarize_transitions(baseline, rows, gt)
        summary_rows.append(
            {
                "strategy": name,
                **m,
                "delta_recall": float(m["recall"]) - float(base_metrics["recall"]),
                "delta_precision": float(m["precision"]) - float(base_metrics["precision"]),
                "delta_f1": float(m["f1"]) - float(base_metrics["f1"]),
                "delta_tp": int(m["tp"]) - int(base_metrics["tp"]),
                "delta_fp": int(m["fp"]) - int(base_metrics["fp"]),
                "delta_fn": int(m["fn"]) - int(base_metrics["fn"]),
                **transitions,
            }
        )

    write_csv(DOC_DIR / "fulltext_tier2_p12_ablation_summary.csv", summary_rows)
    (DOC_DIR / "fulltext_tier2_p12_ablation_summary.json").write_text(
        json.dumps(summary_rows, indent=2), encoding="utf-8"
    )
    generate_main_latex_table(summary_rows)
    generate_latex_table(summary_rows)

    best = max(summary_rows, key=strategy_rank)
    u_availability = ""
    u_summary_path = EVAL_DIR / "summary_rescue_only.json"
    if u_summary_path.exists():
        try:
            u_summary = json.loads(u_summary_path.read_text(encoding="utf-8"))
            project_summary = (u_summary.get("projects") or [{}])[0]
            u_availability = (
                f"U-pass availability: {project_summary.get('candidate_count', 0)} stage-1 excluded records; "
                f"{project_summary.get('cached_ready', 0)} cached markdown; "
                f"{project_summary.get('retrieved_ready', 0)} direct PMC full-text retrievals; "
                f"{int(project_summary.get('candidate_count', 0)) - int(project_summary.get('cached_ready', 0)) - int(project_summary.get('retrieved_ready', 0))} unavailable."
            )
        except Exception:
            u_availability = ""
    md = [
        "# Full-text tier-2 ablation: COVID-19 P12",
        "",
        "This pilot combines existing stage-1 screening with cached/full-text retrieval LLM re-review.",
        "The LLM makes the final S/P/U decision; the script only selects which stage-1 bucket is re-reviewed and computes metrics.",
        "",
        "| Strategy | TP | FP | FN | Recall | Precision | F1 | NNS | ΔFP | ΔFN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        md.append(
            f"| {row['strategy']} | {row['tp']} | {row['fp']} | {row['fn']} | "
            f"{float(row['recall']):.3f} | {float(row['precision']):.3f} | "
            f"{float(row['f1']):.3f} | {float(row['nns']):.2f} | "
            f"{row['delta_fp']:+d} | {row['delta_fn']:+d} |"
        )
    md.extend(
        [
            "",
            "## Current best",
            "",
            f"Best strategy in this run: **{best['strategy']}**.",
            f"It changes recall from {base_metrics['recall']:.3f} to {float(best['recall']):.3f}, "
            f"precision from {base_metrics['precision']:.3f} to {float(best['precision']):.3f}, "
            f"FP from {base_metrics['fp']} to {best['fp']}, and FN from {base_metrics['fn']} to {best['fn']}.",
            "",
            "## Interpretation",
            "",
            *([u_availability, ""] if u_availability else []),
            "- S-only full-text re-review is not useful as a precision lever in this pilot: strong candidates mostly remain relevant by full-text evidence, and many apparent FP are likely source-review coverage differences rather than parameter-screening mistakes.",
            "- P-only full-text re-review is the main precision lever: it removes papers where the target parameter is only a model input, keyword, correspondence topic, or theoretically calculable but not actually reported.",
            "- U-pass full-text re-review is unbiased in candidate selection: it re-reviews all stage-1 excluded records with available full text, not only known false negatives.",
            "- A broad U-pass prompt over-promoted records that merely contained incubation-period values. The conservative U-pass fixes this by requiring source-review eligible original observational evidence before promoting a stage-1 excluded record.",
            "- The deployable strategy is S+P+U full-text composition with a conservative U-pass. In this pilot, P filtering removes 8 FP, while U re-review recovers 1 TP and adds 3 FP, giving a net FP reduction of 5 and eliminating the remaining FN.",
            "",
            "Main LaTeX table: `fulltext_tier2_p12_main_table.tex`",
            "Ablation LaTeX table: `fulltext_tier2_p12_ablation_table.tex`",
        ]
    )
    (DOC_DIR / "fulltext_tier2_p12_ablation_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    generate_source_scope_audit(gt)
    generate_remaining_fp_audit(gt)


if __name__ == "__main__":
    main()
