"""Write a compact Markdown report for screening-to-coding E2E runs."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding"
TRACKING = RUN_ROOT / "e2e_pooled_mean_tracking.csv"
SUMMARY = RUN_ROOT / "e2e_pooled_mean_summary.csv"
REPORT = RUN_ROOT / "e2e_results_report.md"
AUDIT = RUN_ROOT / "e2e_sr_deviation_audit.csv"
CI_OVERLAP_TOLERANCE = 0.01
POINT_DELTA_CAVEAT_THRESHOLDS = {
    "serial_interval": {"abs": 1.0, "rel": 0.20},
    "reproduction_number": {"abs": 0.5, "rel": 0.20},
    "fatality": {"abs": 2.0, "rel": 0.20, "rel_min_abs": 0.5},
}
ALIGNMENT_NOTE_PATTERNS = (
    "SR median",
    "general hospitalized",
    "VOC/variant",
    "Create Date <=2023-03-20",
    "clade I CFR",
    "general-population R0 context",
    "COVID-19 R0 mean/point_estimate",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _fmt(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return text if text and text.lower() != "nan" else ""


def _fmt_pct(value: object) -> str:
    text = _fmt(value)
    if not text:
        return ""
    try:
        return f"{float(text) * 100:.1f}%"
    except ValueError:
        return text


def _to_float(value: object) -> float | None:
    text = _fmt(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _alignment_note(note: str) -> str:
    parts = []
    seen = set()
    for raw in note.split("|"):
        part = raw.strip()
        if not part or part in seen:
            continue
        if any(pattern in part for pattern in ALIGNMENT_NOTE_PATTERNS):
            parts.append(part)
            seen.add(part)
    return "; ".join(parts)


def _point_in_sr_ci(row: dict[str, str]) -> bool:
    point = _to_float(row.get("e2e_pooled_mean"))
    lo = _to_float(row.get("sr_ci_lower"))
    hi = _to_float(row.get("sr_ci_upper"))
    return point is not None and lo is not None and hi is not None and lo <= point <= hi


def _interval_overlaps_sr_ci(row: dict[str, str]) -> bool:
    sr_lo = _to_float(row.get("sr_ci_lower"))
    sr_hi = _to_float(row.get("sr_ci_upper"))
    e2e_lo = _to_float(row.get("e2e_ci_lower"))
    e2e_hi = _to_float(row.get("e2e_ci_upper"))
    if None in (sr_lo, sr_hi, e2e_lo, e2e_hi):
        return False
    return max(sr_lo, e2e_lo) <= min(sr_hi, e2e_hi) + CI_OVERLAP_TOLERANCE


def _has_sr_ci(row: dict[str, str]) -> bool:
    return _to_float(row.get("sr_ci_lower")) is not None and _to_float(row.get("sr_ci_upper")) is not None


def _point_delta_exceeds_caveat_threshold(row: dict[str, str]) -> bool:
    topic = _fmt(row.get("topic"))
    thresholds = POINT_DELTA_CAVEAT_THRESHOLDS.get(topic)
    if not thresholds:
        return False
    delta = _to_float(row.get("delta_e2e_vs_sr"))
    sr = _to_float(row.get("sr_point"))
    if delta is None:
        return False
    abs_delta = abs(delta)
    abs_hit = abs_delta >= thresholds["abs"]
    rel_hit = False
    if sr is not None and sr != 0:
        rel_hit = abs_delta / abs(sr) >= thresholds["rel"]
        rel_min_abs = thresholds.get("rel_min_abs")
        if rel_min_abs is not None:
            rel_hit = rel_hit and abs_delta >= rel_min_abs
    return abs_hit or rel_hit


def _audit_status(row: dict[str, str]) -> str:
    if _fmt(row.get("sr_deviation_flag")) == "large":
        return "needs audit"
    if _point_in_sr_ci(row) and _point_delta_exceeds_caveat_threshold(row):
        return "usable-caveat"
    if _point_in_sr_ci(row):
        return "usable"
    if not _has_sr_ci(row):
        return "usable"
    return "usable-caveat"


def _audit_reason(row: dict[str, str]) -> str:
    if _fmt(row.get("sr_deviation_flag")) == "large":
        return "large deviation vs SR"
    if _point_in_sr_ci(row) and _point_delta_exceeds_caveat_threshold(row):
        return "point estimate inside SR CI, but point delta exceeds the large-deviation threshold"
    if _point_in_sr_ci(row):
        return "point estimate inside SR CI"
    if not _has_sr_ci(row):
        return "SR CI unavailable; absolute delta below large-deviation rule"
    if _interval_overlaps_sr_ci(row):
        return "point outside SR CI, but E2E CI overlaps SR CI and delta is below large-deviation rule"
    return "outside SR CI, but below large-deviation rule"


def _build_audit_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    audit_rows = []
    for row in rows:
        audit_rows.append(
            {
                "profile": _fmt(row.get("profile")),
                "disease": _fmt(row.get("disease")),
                "topic": _fmt(row.get("topic")),
                "status": _fmt(row.get("status")),
                "sr_point": _fmt(row.get("sr_point")),
                "sr_ci_lower": _fmt(row.get("sr_ci_lower")),
                "sr_ci_upper": _fmt(row.get("sr_ci_upper")),
                "e2e_pooled_mean": _fmt(row.get("e2e_pooled_mean")),
                "e2e_ci_lower": _fmt(row.get("e2e_ci_lower")),
                "e2e_ci_upper": _fmt(row.get("e2e_ci_upper")),
                "delta_e2e_vs_sr": _fmt(row.get("delta_e2e_vs_sr")),
                "relative_delta_e2e_vs_sr": _fmt(row.get("relative_delta_e2e_vs_sr")),
                "point_in_sr_ci": "yes" if _point_in_sr_ci(row) else "no",
                "interval_overlaps_sr_ci": "yes" if _interval_overlaps_sr_ci(row) else "no",
                "sr_deviation_flag": _fmt(row.get("sr_deviation_flag")),
                "audit_status": _audit_status(row),
                "audit_reason": _audit_reason(row),
                "alignment_note": _alignment_note(
                    " | ".join(
                        part
                        for part in (_fmt(row.get("profile_filter_note")), _fmt(row.get("pooling_warnings")))
                        if part
                    )
                ),
                "pooled_input_rows": _fmt(row.get("pooled_input_rows")),
                "pooled_input_pmids": _fmt(row.get("pooled_input_pmids")),
                "covered_pmid_count": _fmt(row.get("covered_pmid_count")),
                "missing_selected_pmid_count": _fmt(row.get("missing_selected_pmid_count")),
            }
        )
    return audit_rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _fmt_float(value: float | None, digits: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _project_num(profile: str) -> str:
    return str(profile).strip().lower().removeprefix("mp").removeprefix("p")


def _pmid_from_index(path: Path) -> str | None:
    match = re.match(r"PMID_(\d+)\.index\.json$", path.name)
    return match.group(1) if match else None


def _pmid_from_error(path: Path) -> str | None:
    match = re.match(r"PMID_(\d+)\.", path.name)
    return match.group(1) if match else None


def _run_progress(row: dict[str, str]) -> str:
    run_dir = _fmt(row.get("run_dir"))
    if not run_dir:
        return ""
    path = Path(run_dir)
    if not path.exists():
        return ""
    input_path = path / "coding_input_pmids.txt"
    coding_input = 0
    if input_path.exists():
        coding_input = sum(1 for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip())
    disease = _fmt(row.get("disease"))
    topic = _fmt(row.get("topic"))
    project = _project_num(_fmt(row.get("profile")))
    pattern = f"{disease}_{topic}_p{project}*"

    indexed_pmids: set[str] = set()
    error_pmids: set[str] = set()
    missing_pmids: set[str] = set()
    for candidate in RUN_ROOT.glob(pattern):
        if not candidate.is_dir():
            continue
        if (candidate / "index").exists():
            for item in (candidate / "index").glob("PMID_*.index.json"):
                pmid = _pmid_from_index(item)
                if pmid:
                    indexed_pmids.add(pmid)
        if (candidate / "errors").exists():
            for item in (candidate / "errors").glob("PMID_*.json"):
                pmid = _pmid_from_error(item)
                if pmid:
                    error_pmids.add(pmid)
        for summary_path in candidate.glob("screen_to_coding_summary*.json"):
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for pmid in summary.get("coding_missing_fulltext_pmids") or []:
                pmid_s = str(pmid)
                if pmid_s.isdigit():
                    missing_pmids.add(pmid_s)

    covered = indexed_pmids | error_pmids | missing_pmids
    error_only = error_pmids - indexed_pmids
    missing_only = missing_pmids - indexed_pmids - error_pmids
    if coding_input:
        return (
            f"{len(covered)}/{coding_input}; remaining={max(coding_input - len(covered), 0)}; "
            f"index={len(indexed_pmids)}; error-only={len(error_only)}; missing-only={len(missing_only)}"
        )
    if covered:
        return f"index={len(indexed_pmids)}; error-only={len(error_only)}; missing-only={len(missing_only)}"
    return ""


def main() -> None:
    rows = _read_csv(TRACKING)
    summary_rows = _read_csv(SUMMARY)
    audit_rows = _build_audit_rows(rows)
    counts = Counter(_fmt(row.get("status")) for row in rows)
    completed_rows = [row for row in rows if _fmt(row.get("status")) == "completed"]
    rows_with_sr_ci = [row for row in completed_rows if _has_sr_ci(row)]
    point_in_sr_ci = [row for row in rows_with_sr_ci if _point_in_sr_ci(row)]
    interval_overlap = [row for row in rows_with_sr_ci if _interval_overlaps_sr_ci(row)]
    point_delta_caveats = [
        row
        for row in completed_rows
        if _point_in_sr_ci(row) and _point_delta_exceeds_caveat_threshold(row)
    ]
    large_deviations = [
        row
        for row in rows
        if _fmt(row.get("sr_deviation_flag")) == "large"
    ]

    lines: list[str] = []
    lines.append("# E2E Screening-to-Coding Report")
    lines.append("")
    lines.append(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Status")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    for status in ("completed", "completed_no_records", "running", "prepared", "pending"):
        if counts.get(status):
            lines.append(f"| {status} | {counts[status]} |")
    lines.append("")

    topic_stats: dict[str, dict[str, float | None]] = {}
    for topic in sorted({_fmt(row.get("topic")) for row in completed_rows if _fmt(row.get("topic"))}):
        topic_rows = [row for row in completed_rows if _fmt(row.get("topic")) == topic]
        e2e_abs = [abs(v) for row in topic_rows if (v := _to_float(row.get("delta_e2e_vs_sr"))) is not None]
        module_abs = []
        for row in topic_rows:
            sr = _to_float(row.get("sr_point"))
            module = _to_float(row.get("previous_module_point"))
            if sr is not None and module is not None:
                module_abs.append(abs(module - sr))
        topic_stats[topic] = {
            "n": float(len(topic_rows)),
            "e2e_mae": _mean(e2e_abs),
            "e2e_median_ae": _median(e2e_abs),
            "module_mae": _mean(module_abs),
            "module_median_ae": _median(module_abs),
            "e2e_max_ae": max(e2e_abs) if e2e_abs else None,
        }

    lines.append("## Usability Summary")
    lines.append("")
    lines.append(f"- Completed profiles: {len(completed_rows)}/{len(rows)}")
    lines.append(f"- Large deviations after SR-aligned filters: {len(large_deviations)}/{len(rows)}")
    lines.append(f"- Point-delta caveats inside SR CI: {len(point_delta_caveats)}/{len(completed_rows)}")
    lines.append(f"- E2E point estimate inside SR CI: {len(point_in_sr_ci)}/{len(rows_with_sr_ci)} profiles with SR CI")
    lines.append(f"- E2E CI overlaps SR CI: {len(interval_overlap)}/{len(rows_with_sr_ci)} profiles with SR CI")
    lines.append("")
    lines.append("| Topic | n | E2E MAE | E2E median AE | E2E max AE | Module MAE | Module median AE |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for topic, stats in topic_stats.items():
        lines.append(
            "| {topic} | {n:g} | {e2e_mae} | {e2e_median} | {e2e_max} | {module_mae} | {module_median} |".format(
                topic=topic,
                n=stats["n"] or 0,
                e2e_mae=_fmt_float(stats["e2e_mae"]),
                e2e_median=_fmt_float(stats["e2e_median_ae"]),
                e2e_max=_fmt_float(stats["e2e_max_ae"]),
                module_mae=_fmt_float(stats["module_mae"]),
                module_median=_fmt_float(stats["module_median_ae"]),
            )
        )
    lines.append("")

    lines.append("## Pooled Summary")
    lines.append("")
    lines.append("| Project | SR pooled mean | Module pooled mean | E2E pooled mean | Delta vs SR | Deviation note |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for row in summary_rows:
        lines.append(
            "| {project} | {sr} | {module} | {e2e} | {delta} | {note} |".format(
                project=_fmt(row.get("Project")),
                sr=_fmt(row.get("SR pooled mean")),
                module=_fmt(row.get("Module pooled mean")),
                e2e=_fmt(row.get("E2E pooled mean")),
                delta=_fmt(row.get("Delta vs SR") or row.get("\ufeffDelta vs SR") or row.get("Δ vs SR")),
                note=_fmt(row.get("Deviation note")),
            )
        )
    lines.append("")

    if large_deviations:
        lines.append("## Large Deviation vs SR")
        lines.append("")
        lines.append(
            "Flag rule: serial interval >=1 day or >=20%; reproduction number >=0.5 or >=20%; "
            "fatality >=2 percentage points or >=20% with >=0.5 percentage points. "
            "Rows are not flagged when the E2E point estimate lies inside the SR CI or the E2E CI overlaps the SR CI."
        )
        lines.append("")
        lines.append("| Project | Disease | Topic | SR | E2E | Delta | Relative delta | Threshold |")
        lines.append("|---|---|---|---:|---:|---:|---:|---|")
        for row in sorted(
            large_deviations,
            key=lambda item: float(_fmt(item.get("relative_delta_e2e_vs_sr")) or 0),
            reverse=True,
        ):
            lines.append(
                "| {profile} | {disease} | {topic} | {sr} | {e2e} | {delta} | {rel} | {threshold} |".format(
                    profile=_fmt(row.get("profile")),
                    disease=_fmt(row.get("disease")),
                    topic=_fmt(row.get("topic")),
                    sr=_fmt(row.get("sr_point")),
                    e2e=_fmt(row.get("e2e_pooled_mean")),
                    delta=_fmt(row.get("delta_e2e_vs_sr")),
                    rel=_fmt_pct(row.get("relative_delta_e2e_vs_sr")),
                    threshold=_fmt(row.get("sr_deviation_threshold")),
                )
            )
        lines.append("")
    else:
        lines.append("## Large Deviation vs SR")
        lines.append("")
        lines.append("No profile exceeds the configured large-deviation rule after SR-aligned filters.")
        lines.append("")

    if audit_rows:
        lines.append("## SR Deviation Audit")
        lines.append("")
        lines.append("| Project | Topic | SR | E2E | Delta | Status | Reason |")
        lines.append("|---|---|---:|---:|---:|---|---|")
        for row in audit_rows:
            lines.append(
                "| {profile} | {topic} | {sr} | {e2e} | {delta} | {status} | {reason} |".format(
                    profile=_fmt(row.get("profile")),
                    topic=_fmt(row.get("topic")),
                    sr=_fmt(row.get("sr_point")),
                    e2e=_fmt(row.get("e2e_pooled_mean")),
                    delta=_fmt(row.get("delta_e2e_vs_sr")),
                    status=_fmt(row.get("audit_status")),
                    reason=_fmt(row.get("audit_reason")),
                )
            )
        lines.append("")

    alignment_rows = []
    for row in rows:
        note = " | ".join(
            part
            for part in (_fmt(row.get("profile_filter_note")), _fmt(row.get("pooling_warnings")))
            if part
        )
        if note and any(pattern in note for pattern in ALIGNMENT_NOTE_PATTERNS):
            alignment_rows.append((row, _alignment_note(note)))
    if alignment_rows:
        lines.append("## Alignment Filters Applied")
        lines.append("")
        lines.append("| Project | Disease | Topic | E2E | Delta vs SR | Note |")
        lines.append("|---|---|---|---:|---:|---|")
        for row, note in alignment_rows:
            lines.append(
                "| {profile} | {disease} | {topic} | {e2e} | {delta} | {note} |".format(
                    profile=_fmt(row.get("profile")),
                    disease=_fmt(row.get("disease")),
                    topic=_fmt(row.get("topic")),
                    e2e=_fmt(row.get("e2e_pooled_mean")),
                    delta=_fmt(row.get("delta_e2e_vs_sr")),
                    note=note,
                )
            )
        lines.append("")

    running = [row for row in rows if _fmt(row.get("status")) == "running"]
    if running:
        lines.append("## Running")
        lines.append("")
        lines.append("| Project | Disease | Topic | Progress |")
        lines.append("|---|---|---|---:|")
        for row in running:
            lines.append(
                "| {profile} | {disease} | {topic} | {progress} |".format(
                    profile=_fmt(row.get("profile")),
                    disease=_fmt(row.get("disease")),
                    topic=_fmt(row.get("topic")),
                    progress=_run_progress(row),
                )
            )
        lines.append("")

    review = [
        row
        for row in rows
        if _fmt(row.get("status")).startswith("completed")
        and not _fmt(row.get("e2e_pooled_mean"))
    ]
    if review:
        lines.append("## Needs Review")
        lines.append("")
        lines.append("| Project | Status | Disease | Topic | Records | Note |")
        lines.append("|---|---|---|---|---:|---|")
        for row in review:
            note = "no pooled mean under current pooling filter"
            lines.append(
                "| {profile} | {status} | {disease} | {topic} | {records} | {note} |".format(
                    profile=_fmt(row.get("profile")),
                    status=_fmt(row.get("status")),
                    disease=_fmt(row.get("disease")),
                    topic=_fmt(row.get("topic")),
                    records=_fmt(row.get("coding_record_count")),
                    note=note,
                )
            )
        lines.append("")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if audit_rows:
        with AUDIT.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
            writer.writeheader()
            writer.writerows(audit_rows)
        print(f"Wrote {AUDIT}")
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    main()
