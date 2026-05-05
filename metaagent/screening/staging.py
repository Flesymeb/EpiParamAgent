"""Paper staging helpers for screening workflows."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from metaagent.screening.fulltext_pipeline import find_markdown_cache


def print_ground_truth_warning(gt_file: Path) -> None:
    """Emit a helpful warning when GT PMIDs cannot be loaded."""
    if gt_file.exists():
        header = ""
        try:
            with open(gt_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                header = ",".join(reader.fieldnames or [])
        except Exception:
            header = ""
        print(
            f"⚠️  Ground Truth file exists but no PMID column recognized: {gt_file}\n"
            f"   Header: {header}\n"
        )
    else:
        print(f"⚠️  Ground truth file not found: {gt_file}\n")


def annotate_ground_truth(
    papers: list[dict[str, Any]], gt_pmids: set[str]
) -> int | None:
    """Mark papers that belong to the provided GT PMID set."""
    if not gt_pmids:
        return None

    for paper in papers:
        pmid = (paper.get("PMID") or "").strip()
        paper["is_ground_truth"] = "✓" if pmid in gt_pmids else ""
    gt_count = sum(1 for p in papers if p.get("is_ground_truth") == "✓")
    print(f"Containing {gt_count}/{len(gt_pmids)} ground truth papers\n")
    return gt_count


def partition_papers(
    *,
    papers: list[dict[str, Any]],
    screening_config: dict[str, Any] | None,
    auto_fulltext: bool,
    fulltext_only: bool,
) -> dict[str, Any]:
    """Split papers into title/abstract screening and full-text rescue buckets."""
    papers_title_abstract: list[dict[str, Any]] = []
    papers_title_only: list[dict[str, Any]] = []
    papers_without_abstract: list[dict[str, Any]] = []
    fulltext_errors: list[dict[str, str]] = []
    fulltext_cached: list[dict[str, Any]] = []
    policies = (screening_config or {}).get("policies", {}) or {}
    rescue_policy = policies.get("fulltext_rescue", {}) or {}
    effective_fulltext_only = bool(fulltext_only)
    effective_auto_fulltext = bool(
        effective_fulltext_only
        or auto_fulltext
        or (
            bool(rescue_policy.get("enabled"))
            and bool(rescue_policy.get("when_no_abstract"))
        )
    )
    title_abstract_mode = str(policies.get("title_abstract_mode", "strict")).strip().lower()
    title_only_mode = str(policies.get("title_only_mode", "lenient")).strip().lower()
    full_text_mode = str(policies.get("full_text_mode", "standard")).strip().lower()

    for paper in papers:
        pmid = (paper.get("PMID") or "").strip()
        abstract = (paper.get("Abstract") or "").strip()
        fulltext_markdown = (paper.get("fulltext_markdown") or "").strip()
        fulltext_path = (paper.get("fulltext_path") or "").strip()

        if effective_fulltext_only:
            papers_without_abstract.append(paper)
            paper["screening_stage"] = "pending_fulltext"
            paper["screening_mode"] = full_text_mode
            paper["fulltext_status"] = "pending"
            paper.setdefault("fulltext_path", "")
            paper["llm_suggest"] = "needs_full_text"
        elif abstract:
            papers_title_abstract.append(paper)
            paper["screening_stage"] = "title_abstract"
            paper["screening_mode"] = title_abstract_mode
            continue
        elif not effective_auto_fulltext:
            papers_title_only.append(paper)
            paper["screening_stage"] = "title_only"
            paper["screening_mode"] = title_only_mode
        else:
            papers_without_abstract.append(paper)
            paper["screening_stage"] = "pending_fulltext"
            paper["screening_mode"] = full_text_mode
            paper["fulltext_status"] = "pending"
            paper.setdefault("fulltext_path", "")
            paper["llm_suggest"] = "needs_full_text"

        if not (effective_auto_fulltext or effective_fulltext_only):
            continue

        if not fulltext_markdown and fulltext_path:
            try:
                fulltext_markdown = Path(fulltext_path).read_text(encoding="utf-8")
                paper["fulltext_markdown"] = fulltext_markdown
            except Exception:
                fulltext_errors.append(
                    {
                        "pmid": pmid,
                        "title": paper.get("Title", ""),
                        "status": "read_failed",
                        "detail": f"failed to read fulltext_path: {fulltext_path}",
                    }
                )

        if not fulltext_markdown and pmid:
            cached_md = find_markdown_cache(pmid)
            if cached_md:
                try:
                    fulltext_markdown = cached_md.read_text(encoding="utf-8")
                    paper["fulltext_markdown"] = fulltext_markdown
                    paper["fulltext_path"] = str(cached_md)
                except Exception:
                    fulltext_errors.append(
                        {
                            "pmid": pmid,
                            "title": paper.get("Title", ""),
                            "status": "read_failed",
                            "detail": f"failed to read cached md: {cached_md}",
                        }
                    )

        if fulltext_markdown:
            fulltext_cached.append(paper)

    return {
        "papers_title_abstract": papers_title_abstract,
        "papers_title_only": papers_title_only,
        "papers_without_abstract": papers_without_abstract,
        "fulltext_errors": fulltext_errors,
        "fulltext_cached": fulltext_cached,
        "effective_auto_fulltext": effective_auto_fulltext,
        "effective_fulltext_only": effective_fulltext_only,
    }


def print_stage_split(
    *,
    papers_title_abstract: list[dict[str, Any]],
    papers_title_only: list[dict[str, Any]],
    papers_without_abstract: list[dict[str, Any]],
    auto_fulltext: bool,
    fulltext_only: bool,
) -> None:
    """Print the routing summary of the current screening run."""
    print("=" * 80)
    if auto_fulltext or fulltext_only:
        print(
            f"Stage split: title+abstract={len(papers_title_abstract)} | full-text={len(papers_without_abstract)}"
        )
    else:
        print(
            f"Stage split: title+abstract={len(papers_title_abstract)} | title-only={len(papers_title_only)}"
        )
    print("=" * 80)
