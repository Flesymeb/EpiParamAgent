"""Persistence, reporting, and manifest helpers for screening runs."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from metaagent.config import load_llm_config
from tools.provenance import write_run_manifest
from tools.mineru._config import load_mineru_config


def save_screening_outputs(
    *,
    papers: list[dict[str, Any]],
    output_file: Path,
    research_question: str,
    input_file: Path,
    gt_file: Path | None,
    gt_pmids: set[str],
    gt_count: int | None,
    batch_size: int,
    batch_concurrency: int,
    batch_mode: str = "single",
    profile_name: str | None,
    auto_fulltext: bool,
    fulltext_only: bool,
    fulltext_needed_count: int,
    fulltext_ready_count: int,
    fulltext_errors: list[dict[str, str]],
    strategy: str = "5d",
    experiment: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Persist screened CSV, detailed report, and run manifest."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_file.parent / "screening_runs" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    from .guards import screening_audit
    audit_path = run_dir / "screening_audit.json"
    audit_path.write_text(json.dumps(screening_audit(papers), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Archive previous result before overwriting so multi-run history is preserved.
    # The canonical output_file always holds the latest run; backups accumulate in screening_logs/.
    if output_file.exists():
        log_dir_early = output_file.parent / "screening_logs"
        log_dir_early.mkdir(parents=True, exist_ok=True)
        backup_path = log_dir_early / f"{output_file.stem}_backup_{timestamp}.csv"
        shutil.copy2(output_file, backup_path)

    for paper in papers:
        paper.pop("fulltext_markdown", None)
    fieldnames = _collect_fieldnames(papers)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(papers)

    strong = [p for p in papers if p.get("llm_suggest") == "strong_candidate"]
    possible = [p for p in papers if p.get("llm_suggest") == "possible_candidate"]
    unlikely = [p for p in papers if p.get("llm_suggest") == "unlikely_candidate"]
    errors = [p for p in papers if p.get("llm_suggest") == "error"]

    llm_cfg = load_llm_config(
        {
            "llm_provider": llm_provider,
            "llm_model": llm_model,
        },
        module_hint="screening",
    )

    log_dir = output_file.parent / "screening_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"screening_report_{timestamp}.txt"
    report_lines = _build_report_lines(
        papers=papers,
        research_question=research_question,
        input_file=input_file,
        output_file=output_file,
        batch_size=batch_size,
        batch_concurrency=batch_concurrency,
        batch_mode=batch_mode,
        fulltext_needed_count=fulltext_needed_count,
        fulltext_ready_count=fulltext_ready_count,
        fulltext_errors=fulltext_errors,
        strong=strong,
        possible=possible,
        unlikely=unlikely,
        errors=errors,
        llm_cfg=llm_cfg,
    )
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    mineru_cfg = load_mineru_config(module_hint="screening")
    manifest_path = write_run_manifest(
        output_dir=log_dir,
        workflow="screening",
        module="literature_search",
        params={
            "profile": profile_name,
            "batch_size": batch_size,
            "batch_concurrency": batch_concurrency,
            "batch_mode": batch_mode,
            "auto_fulltext": bool(auto_fulltext),
            "fulltext_only": bool(fulltext_only),
            "research_question": research_question,
            "strategy": strategy,
            "experiment": experiment,
        },
        inputs=[input_file, gt_file] if gt_file else [input_file],
        outputs=[output_file, log_file],
        runtime={
            "llm": {
                "provider": llm_cfg.provider,
                "model": llm_cfg.model,
                "api_base": llm_cfg.api_base,
                "timeout_s": llm_cfg.timeout_s,
                "verify_ssl": llm_cfg.verify_ssl,
                "has_api_key": bool(llm_cfg.api_key),
            },
            "mineru": {
                "base_url": mineru_cfg.base_url,
                "endpoint": mineru_cfg.endpoint,
                "timeout_s": mineru_cfg.timeout_s,
                "has_api_key": bool(mineru_cfg.api_key),
            },
        },
        extra={
            "screening_audit": str(audit_path),
            "paper_count": len(papers),
            "ground_truth_count": len(gt_pmids),
            "ground_truth_in_pool": gt_count if gt_pmids else None,
            "strong_count": len(strong),
            "possible_count": len(possible),
            "unlikely_count": len(unlikely),
            "error_count": len(errors),
            "fulltext_error_count": len(fulltext_errors),
        },
    )
    run_output_file = run_dir / output_file.name
    run_log_file = run_dir / log_file.name
    run_manifest_file = run_dir / manifest_path.name
    shutil.copy2(output_file, run_output_file)
    shutil.copy2(log_file, run_log_file)
    shutil.copy2(manifest_path, run_manifest_file)
    return output_file, log_file, manifest_path, run_dir


def _collect_fieldnames(papers: list[dict[str, Any]]) -> list[str]:
    if not papers:
        return []

    fieldnames: list[str] = []
    seen: set[str] = set()
    for paper in papers:
        for key in paper.keys():
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)
    if "is_ground_truth" in fieldnames:
        fieldnames.remove("is_ground_truth")
        if "PMID" in fieldnames:
            pmid_idx = fieldnames.index("PMID")
            fieldnames.insert(pmid_idx + 1, "is_ground_truth")
        else:
            fieldnames.insert(0, "is_ground_truth")

    for field in ["llm_suggest", "overall_score", "overall_justification"]:
        if field not in fieldnames:
            fieldnames.append(field)
    for field in ["screening_stage", "screening_mode", "fulltext_status", "fulltext_path", "fulltext_eligible"]:
        if field not in fieldnames:
            fieldnames.append(field)
    for dimension in ["disease", "population", "location", "evidence", "parameter"]:
        for suffix in ["score", "justification"]:
            field = f"{dimension}_{suffix}"
            if field not in fieldnames:
                fieldnames.append(field)
    return fieldnames


def _build_report_lines(
    *,
    papers: list[dict[str, Any]],
    research_question: str,
    input_file: Path,
    output_file: Path,
    batch_size: int,
    batch_concurrency: int,
    batch_mode: str,
    fulltext_needed_count: int,
    fulltext_ready_count: int,
    fulltext_errors: list[dict[str, str]],
    strong: list[dict[str, Any]],
    possible: list[dict[str, Any]],
    unlikely: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    llm_cfg: Any,
) -> list[str]:
    denominator = len(papers)
    def share(rows):
        return len(rows) / denominator * 100 if denominator else 0.0

    report_lines: list[str] = []
    report_lines.append("=" * 80)
    report_lines.append("LLM Screening Detailed Report")
    report_lines.append("=" * 80)
    report_lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Research question: {research_question}")
    report_lines.append(f"Input file: {input_file}")
    report_lines.append(f"Output file: {output_file}")
    report_lines.append(f"Model config: {llm_cfg.provider}/{llm_cfg.model}")
    report_lines.append(f"Batch size: {batch_size}")
    report_lines.append(f"Batch concurrency: {batch_concurrency}")
    report_lines.append(f"Batch mode: {batch_mode}")
    report_lines.append(
        "Full-text: "
        f"need_fulltext={fulltext_needed_count} | "
        f"screened={fulltext_ready_count}"
    )

    report_lines.append("\n" + "=" * 80)
    report_lines.append("Screening Result Summary")
    report_lines.append("=" * 80)
    report_lines.append("\n┌─────────────────────────┬──────────┬──────────┐")
    report_lines.append("│ Category                │ Count    │ Share    │")
    report_lines.append("├─────────────────────────┼──────────┼──────────┤")
    report_lines.append(
        f"│ 💪 Strong candidates     │   {len(strong):4d}   │  {share(strong):5.1f}%  │"
    )
    report_lines.append(
        f"│ 🤔 Possible candidates   │   {len(possible):4d}   │  {share(possible):5.1f}%  │"
    )
    report_lines.append(
        f"│ 😐 Unlikely candidates   │   {len(unlikely):4d}   │  {share(unlikely):5.1f}%  │"
    )
    report_lines.append(
        f"│ ⚠️  Errors               │   {len(errors):4d}   │  {share(errors):5.1f}%  │"
    )
    report_lines.append("├─────────────────────────┼──────────┼──────────┤")
    report_lines.append(f"│ Total records           │   {len(papers):4d}   │  {100.0 if papers else 0.0:5.1f}%  │")
    report_lines.append("└─────────────────────────┴──────────┴──────────┘")

    if fulltext_errors:
        report_lines.append("\n" + "=" * 80)
        report_lines.append("Full-text failures")
        report_lines.append("=" * 80)
        for idx, item in enumerate(fulltext_errors, 1):
            report_lines.append(
                f"[{idx:02d}] PMID={item.get('pmid') or 'N/A'} | {item.get('status')} | {item.get('title')}"
            )
            detail = (item.get("detail") or "").strip()
            if detail:
                report_lines.append(f"     detail: {detail}")

    report_lines.append("\n" + "=" * 80)
    report_lines.append("Dimension Score Summary (0-4)")
    report_lines.append("=" * 80)
    dimensions = [
        ("disease", "Disease (Variant)"),
        ("population", "Population"),
        ("location", "Location"),
        ("evidence", "Evidence"),
        ("parameter", "Parameter"),
    ]
    report_lines.append(
        "\n┌─────────────────┬─────────┬──────────┬────────────────────────────────┐"
    )
    report_lines.append(
        "│ Dimension        │ Average │ Missing   │ Score distribution (0/1/2/3/4)  │"
    )
    report_lines.append(
        "├─────────────────┼─────────┼──────────┼────────────────────────────────┤"
    )

    for dim, label in dimensions:
        score_field = f"{dim}_score"
        scores = [_dimension_score(p.get(score_field)) for p in papers]
        valid_scores = [score for score in scores if score is not None]
        score_counts = [valid_scores.count(i) for i in range(5)]
        average = f"{sum(valid_scores) / len(valid_scores):4.2f}" if valid_scores else " N/A"
        missing = len(scores) - len(valid_scores)
        report_lines.append(
            f"│ {label:15s} │  {average}  │  {missing:5d}   │ {score_counts[0]:2d}/{score_counts[1]:2d}/{score_counts[2]:2d}/{score_counts[3]:2d}/{score_counts[4]:2d}                 │"
        )

    report_lines.append(
        "└─────────────────┴─────────┴──────────┴────────────────────────────────┘"
    )

    if strong:
        report_lines.append("\n" + "=" * 80)
        report_lines.append(f"Strong Candidates ({len(strong)} papers, input order)")
        report_lines.append("=" * 80)
        for i, paper in enumerate(strong, 1):
            record_id = paper.get("record_id") or paper.get("PMID") or paper.get("pmid") or "N/A"
            report_lines.append(
                f"\n{i}. Record: {record_id} | Tier: {paper.get('llm_tier') or 'N/A'} | Label: {paper.get('llm_suggest') or 'N/A'}"
            )
            report_lines.append(f"   Title: {paper.get('Title') or paper.get('title') or 'N/A'}")
            report_lines.append(
                f"   Rationale: {paper.get('overall_justification') or 'N/A'}"
            )
            values = [_dimension_score(paper.get(f"{dimension}_score")) for dimension, _ in dimensions]
            scores = " ".join(f"{label}={value if value is not None else 'N/A'}" for label, value in zip(("D", "P", "L", "E", "Param"), values))
            report_lines.append(f"   Dimension scores: {scores}")
            if paper.get("screening_requires_review") or paper.get("screening_review_flags"):
                report_lines.append(f"   Review: {paper.get('screening_review_flags') or 'required'}")
    return report_lines


def _dimension_score(value: Any) -> int | None:
    """Read an ordinal dimension score; missing/malformed values stay missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return int(number) if number in (0, 1, 2, 3, 4) else None
