"""Cascade screening orchestrator for Tier 1 → Tier 2 → Tier 3 triage.

Tier 1: LLM screens all papers using metadata only (title + abstract + keywords).
        High-confidence decisions are final.
Tier 2: Uncertain papers get enriched content via retrieval agent, then re-screened.
Tier 3: Still-uncertain papers are flagged for human review.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from .retrieval_agent import (
    RetrievalResult,
    batch_retrieve,
    retrieve_enriched_content,
    summarize_retrieval_stats,
)

# Confidence thresholds for cascade triage
DEFAULT_CONFIDENCE_HIGH = 0.7  # Above this: accept LLM decision
DEFAULT_CONFIDENCE_LOW = 0.3   # Below this: even after Tier 2, flag for human


def partition_by_confidence(
    papers: list[dict[str, Any]],
    *,
    threshold_high: float = DEFAULT_CONFIDENCE_HIGH,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split papers into confident and uncertain groups based on confidence score.

    Papers without a confidence field are assumed uncertain (conservative).
    Papers with llm_suggest='error' are excluded from both groups.
    """
    confident: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []

    for paper in papers:
        if paper.get("llm_suggest") == "error":
            continue
        conf = paper.get("confidence")
        if conf is None:
            uncertain.append(paper)
        elif isinstance(conf, (int, float)) and conf >= threshold_high:
            confident.append(paper)
        else:
            uncertain.append(paper)

    return confident, uncertain


def build_enriched_prompt_text(
    paper: dict[str, Any],
    retrieval: RetrievalResult,
) -> str:
    """Build enriched content text for re-screening from retrieval result.

    Prioritizes: full_text_snippet > enriched_abstract > original abstract.
    """
    parts: list[str] = []

    if retrieval.full_text_snippet:
        parts.append(f"[Retrieved full-text snippet from {retrieval.source}]")
        parts.append(retrieval.full_text_snippet)
    elif retrieval.enriched_abstract:
        parts.append(f"[Enriched abstract from {retrieval.source}]")
        parts.append(retrieval.enriched_abstract)
    else:
        # Fall back to original abstract
        abstract = (paper.get("Abstract") or "").strip()
        if abstract:
            parts.append("[Original abstract — no enriched content retrieved]")
            parts.append(abstract)

    if retrieval.pdf_url:
        parts.append(f"\n[Full-text available at: {retrieval.pdf_url}]")

    return "\n".join(parts)


def merge_cascade_results(
    confident: list[dict[str, Any]],
    re_screened: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge Tier 1 confident decisions with Tier 2 re-screened decisions."""
    merged: list[dict[str, Any]] = list(confident)

    for paper in re_screened:
        paper["cascade_tier"] = "2"
        merged.append(paper)

    for paper in confident:
        paper["cascade_tier"] = "1"

    return merged


def summarize_cascade(
    papers: list[dict[str, Any]],
    retrieval_results: Optional[list[tuple[dict[str, Any], RetrievalResult]]] = None,
) -> dict[str, Any]:
    """Generate cascade summary statistics."""
    total = len(papers)
    tier1 = sum(1 for p in papers if p.get("cascade_tier") == "1")
    tier2 = sum(1 for p in papers if p.get("cascade_tier") == "2")
    tier3 = sum(1 for p in papers if p.get("cascade_tier") == "3")
    errors = sum(1 for p in papers if p.get("llm_suggest") == "error")

    stats: dict[str, Any] = {
        "total_papers": total,
        "tier1_resolved": tier1,
        "tier2_resolved": tier2,
        "tier3_human_review": tier3,
        "errors": errors,
        "tier1_rate": tier1 / total if total else 0,
        "escalation_rate": (tier2 + tier3) / total if total else 0,
    }

    if retrieval_results:
        retrieval_stats = summarize_retrieval_stats(retrieval_results)
        stats["retrieval"] = retrieval_stats

    return stats


async def run_cascade_screening(
    papers: list[dict[str, Any]],
    *,
    screen_fn,  # async function(papers, **kwargs) for LLM screening
    screen_kwargs: dict[str, Any],
    confidence_threshold: float = DEFAULT_CONFIDENCE_HIGH,
    human_review_threshold: float = DEFAULT_CONFIDENCE_LOW,
    retrieval_concurrency: int = 5,
    unpaywall_email: str = "",
) -> dict[str, Any]:
    """Run the full cascade screening pipeline.

    Args:
        papers: List of paper dicts to screen.
        screen_fn: Async function that screens a list of papers in-place.
        screen_kwargs: Arguments forwarded to screen_fn.
        confidence_threshold: Papers with confidence >= this go directly to Tier 1 final.
        human_review_threshold: After Tier 2, papers below this go to Tier 3 (human).
        retrieval_concurrency: Max concurrent retrieval requests.
        unpaywall_email: Email for Unpaywall API.

    Returns:
        Cascade summary dict.
    """
    started_at = time.perf_counter()

    # ── Tier 1: Screen all papers ──
    print(f"\n{'='*60}")
    print("CASCADE Tier 1: Screening {len(papers)} papers with metadata only")
    print(f"{'='*60}")
    await screen_fn(papers, **screen_kwargs)

    confident, uncertain = partition_by_confidence(
        papers, threshold_high=confidence_threshold
    )
    print(f"\nTier 1 results: {len(confident)} confident, {len(uncertain)} uncertain "
          f"(threshold={confidence_threshold})")

    if not uncertain:
        elapsed = time.perf_counter() - started_at
        print(f"Cascade complete in {elapsed:.1f}s — all decisions confident at Tier 1.")
        return summarize_cascade(papers)

    # ── Tier 2: Retrieve enriched content for uncertain papers ──
    print(f"\n{'='*60}")
    print(f"CASCADE Tier 2: Retrieving enriched content for {len(uncertain)} uncertain papers")
    print(f"{'='*60}")

    retrieval_results = await batch_retrieve(
        uncertain,
        concurrency=retrieval_concurrency,
        unpaywall_email=unpaywall_email,
    )
    retrieval_stats = summarize_retrieval_stats(retrieval_results)
    print(f"Retrieval: {retrieval_stats['successful']}/{retrieval_stats['total']} "
          f"successful ({retrieval_stats['success_rate']:.0%}) "
          f"via {retrieval_stats['by_source']}")

    # Build enriched prompts and re-screen
    re_screen_papers: list[dict[str, Any]] = []
    for paper, retrieval in retrieval_results:
        if retrieval.success:
            enriched_text = build_enriched_prompt_text(paper, retrieval)
            paper["_enriched_content"] = enriched_text
            paper["_retrieval_source"] = retrieval.source
            re_screen_papers.append(paper)
        else:
            # No enriched content found — keep original decision, mark for human if low confidence
            conf = paper.get("confidence", 0.0)
            if isinstance(conf, (int, float)) and conf < human_review_threshold:
                paper["cascade_tier"] = "3"
                paper["llm_suggest"] = paper.get("llm_suggest", "possible_candidate")
            else:
                paper["cascade_tier"] = "2"

    if re_screen_papers:
        print(f"\n{'='*60}")
        print(f"CASCADE Tier 2: Re-screening {len(re_screen_papers)} papers with enriched content")
        print(f"{'='*60}")

        # Re-screen with enriched content — use full text as the content source
        tier2_kwargs = dict(screen_kwargs)
        tier2_kwargs["content_key"] = "_enriched_content"
        tier2_kwargs["content_label"] = "Enriched content (retrieved full-text/methods)"
        tier2_kwargs["content_fallback"] = "(No enriched content available)"

        await screen_fn(re_screen_papers, **tier2_kwargs)

        # After re-screening, check confidence again for Tier 3 escalation
        for paper in re_screen_papers:
            conf = paper.get("confidence", 0.0)
            if isinstance(conf, (int, float)) and conf < human_review_threshold:
                paper["cascade_tier"] = "3"

    # ── Merge and summarize ──
    elapsed = time.perf_counter() - started_at
    stats = summarize_cascade(papers, retrieval_results)
    stats["total_elapsed_s"] = elapsed

    tier3_count = sum(1 for p in papers if p.get("cascade_tier") == "3")
    print(f"\nCascade complete in {elapsed:.1f}s.")
    print(f"  Tier 1 (confident):   {stats['tier1_resolved']}")
    print(f"  Tier 2 (re-screened):  {stats['tier2_resolved']}")
    print(f"  Tier 3 (human review): {tier3_count}")
    if "retrieval" in stats:
        r = stats["retrieval"]
        print(f"  Retrieval: {r['successful']}/{r['total']} sources found "
              f"({r['avg_elapsed_ms']:.0f}ms avg)")

    return stats
