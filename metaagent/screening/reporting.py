"""Persistence, reporting, and manifest helpers for screening runs."""

from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from metaagent.config import load_llm_config
from metaagent.provenance import write_run_manifest
from metaagent.mineru_config import load_mineru_config


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
    profile_name: str | None,
    auto_fulltext: bool,
    fulltext_only: bool,
    fulltext_needed_count: int,
    fulltext_ready_count: int,
    fulltext_errors: list[dict[str, str]],
    strategy: str = "5d",
    experiment: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Persist screened CSV, detailed report, and run manifest."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_file.parent / "screening_runs" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Archive previous result before overwriting so multi-run history is preserved.
    # The canonical output_file always holds the latest run; backups accumulate in screening_logs/.
    if output_file.exists():
        log_dir_early = output_file.parent / "screening_logs"
        log_dir_early.mkdir(parents=True, exist_ok=True)
        backup_path = log_dir_early / f"{output_file.stem}_backup_{timestamp}.csv"
        shutil.copy2(output_file, backup_path)

    fieldnames = _collect_fieldnames(papers)
    for paper in papers:
        paper.pop("fulltext_markdown", None)

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(papers)

    strong = [p for p in papers if p.get("llm_suggest") == "strong_candidate"]
    possible = [p for p in papers if p.get("llm_suggest") == "possible_candidate"]
    unlikely = [p for p in papers if p.get("llm_suggest") == "unlikely_candidate"]
    errors = [p for p in papers if p.get("llm_suggest") == "error"]

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
        fulltext_needed_count=fulltext_needed_count,
        fulltext_ready_count=fulltext_ready_count,
        fulltext_errors=fulltext_errors,
        strong=strong,
        possible=possible,
        unlikely=unlikely,
        errors=errors,
    )
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    llm_cfg = load_llm_config(module_hint="literature_search")
    mineru_cfg = load_mineru_config(module_hint="literature_search")
    manifest_path = write_run_manifest(
        output_dir=log_dir,
        workflow="screening",
        module="literature_search",
        params={
            "profile": profile_name,
            "batch_size": batch_size,
            "batch_concurrency": batch_concurrency,
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

    fieldnames = list(papers[0].keys())
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
    fulltext_needed_count: int,
    fulltext_ready_count: int,
    fulltext_errors: list[dict[str, str]],
    strong: list[dict[str, Any]],
    possible: list[dict[str, Any]],
    unlikely: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[str]:
    report_lines: list[str] = []
    report_lines.append("=" * 80)
    report_lines.append("LLM Screening Detailed Report")
    report_lines.append("=" * 80)
    report_lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Research question: {research_question}")
    report_lines.append(f"输入文件: {input_file}")
    report_lines.append(f"输出文件: {output_file}")
    llm_cfg = load_llm_config(module_hint="literature_search")
    report_lines.append(f"模型配置: {llm_cfg.provider}/{llm_cfg.model}")
    report_lines.append(f"批处理大小: {batch_size}")
    report_lines.append(f"批次并发: {batch_concurrency}")
    report_lines.append(
        "Full-text: "
        f"need_fulltext={fulltext_needed_count} | "
        f"screened={fulltext_ready_count}"
    )

    report_lines.append("\n" + "=" * 80)
    report_lines.append("📊 筛选结果统计")
    report_lines.append("=" * 80)
    report_lines.append("\n┌─────────────────────────┬──────────┬──────────┐")
    report_lines.append("│ 类别                     │   数量    │   占比    │")
    report_lines.append("├─────────────────────────┼──────────┼──────────┤")
    report_lines.append(
        f"│ 💪 Strong candidates     │   {len(strong):4d}   │  {len(strong)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append(
        f"│ 🤔 Possible candidates   │   {len(possible):4d}   │  {len(possible)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append(
        f"│ 😐 Unlikely candidates   │   {len(unlikely):4d}   │  {len(unlikely)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append(
        f"│ ⚠️  Errors               │   {len(errors):4d}   │  {len(errors)/len(papers)*100:5.1f}%  │"
    )
    report_lines.append("├─────────────────────────┼──────────┼──────────┤")
    report_lines.append(f"│ 📝 总记录数              │   {len(papers):4d}   │ 100.0%   │")
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
    report_lines.append("📊 各维度相关性评分统计 (0-4分制)")
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
        "│ 维度             │ 平均分  │ 高相关率  │ 评分分布 (0/1/2/3/4)            │"
    )
    report_lines.append(
        "├─────────────────┼─────────┼──────────┼────────────────────────────────┤"
    )

    for dim, label in dimensions:
        score_field = f"{dim}_score"
        score_counts = [
            sum(1 for p in papers if str(p.get(score_field, "")).strip() == str(i))
            for i in range(5)
        ]
        valid_scores = [
            int(p.get(score_field, 0))
            for p in papers
            if p.get(score_field) not in ["", None]
        ]
        avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0
        high_relevance = sum(1 for s in valid_scores if s >= 3)
        high_pct = (high_relevance / len(valid_scores) * 100) if valid_scores else 0
        report_lines.append(
            f"│ {label:15s} │  {avg_score:4.2f}  │  {high_pct:5.1f}%  │ {score_counts[0]:2d}/{score_counts[1]:2d}/{score_counts[2]:2d}/{score_counts[3]:2d}/{score_counts[4]:2d}                 │"
        )

    report_lines.append(
        "└─────────────────┴─────────┴──────────┴────────────────────────────────┘"
    )

    if strong:
        report_lines.append("\n" + "=" * 80)
        report_lines.append(f"💪 Strong Candidates ({len(strong)} 篇)")
        report_lines.append("=" * 80)
        high_relevance = sorted(
            strong, key=lambda x: int(x.get("overall_score", 0)), reverse=True
        )
        for i, paper in enumerate(high_relevance, 1):
            report_lines.append(
                f"\n{i}. PMID: {paper.get('PMID', 'N/A')} [Score: {paper.get('overall_score')}/4]"
            )
            report_lines.append(f"   Title: {paper.get('Title', 'N/A')}")
            report_lines.append(
                f"   Overall: {paper.get('overall_justification', 'N/A')}"
            )
            report_lines.append(
                f"   维度评分: D={paper.get('disease_score')} P={paper.get('population_score')} L={paper.get('location_score')} E={paper.get('evidence_score')} Param={paper.get('parameter_score')}"
            )
    return report_lines
