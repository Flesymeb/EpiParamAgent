#!/usr/bin/env python3
"""Smoke-test retrieval/full-text enriched stage-2 screening on hard profiles.

This script does not replace the formal profile runner. It starts from an
existing stage-1 screened CSV, routes selected included papers through:

1. Local cached full-text markdown, if available.
2. PubMed/PMC enrichment fallback.
3. OA/web retrieval fallback.

Then it re-screens those candidates with the stricter stage-2 prompts and
reports whether precision/F1 improve without large recall loss.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from metaagent.screening.enrichment import batch_enrich, build_enriched_prompt
from metaagent.screening.engine import init_llm_model, screen_papers_batch_async
from metaagent.screening.fulltext_pipeline import MD_CACHE_DIR
from metaagent.screening.retrieval import batch_retrieve


EXP = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
MODEL = os.getenv("RETRIEVAL_TEST_MODEL", "qwen3.6-plus")
PROVIDER = os.getenv("RETRIEVAL_TEST_PROVIDER", "boyue")
OUT = REPO / "evaluation" / "screening_prompt_eval" / "retrieval_enriched_20260509"

BATCH_SIZE = int(os.getenv("RETRIEVAL_TEST_BATCH_SIZE", "8"))
CONCURRENCY = int(os.getenv("RETRIEVAL_TEST_CONCURRENCY", "4"))
BATCH_MODE = os.getenv("RETRIEVAL_TEST_BATCH_MODE", "multi")
RETRIEVAL_CONCURRENCY = int(os.getenv("RETRIEVAL_TEST_RETRIEVAL_CONCURRENCY", "5"))
CANDIDATE_SCOPE = os.getenv("RETRIEVAL_TEST_SCOPE", "all_included").strip().lower()
MAX_CONTENT_CHARS = int(os.getenv("RETRIEVAL_TEST_MAX_CONTENT_CHARS", "9000"))
SNIPPET_WINDOW_CHARS = int(os.getenv("RETRIEVAL_TEST_SNIPPET_WINDOW_CHARS", "900"))
USE_PMC = os.getenv("RETRIEVAL_TEST_USE_PMC", "1") != "0"
USE_WEB = os.getenv("RETRIEVAL_TEST_USE_WEB", "1") != "0"
USE_DIRECT_PMC = os.getenv("RETRIEVAL_TEST_USE_DIRECT_PMC", "1") != "0"
STRONG_STAGE = os.getenv("RETRIEVAL_TEST_STRONG_STAGE", "strong_full_text_llm").strip()
POSSIBLE_STAGE = os.getenv("RETRIEVAL_TEST_POSSIBLE_STAGE", "possible_full_text_llm").strip()
RESCUE_STAGE = os.getenv("RETRIEVAL_TEST_RESCUE_STAGE", "rescue_full_text_llm").strip()
USE_SCOPE_NOTE = os.getenv("RETRIEVAL_TEST_USE_SCOPE_NOTE", "0") == "1"
RUN_SCOPE = f"{CANDIDATE_SCOPE}{'_date_scope' if USE_SCOPE_NOTE else ''}"
PROJECT_FILTER = {
    item.strip()
    for item in os.getenv("RETRIEVAL_TEST_PROJECTS", "").split(",")
    if item.strip()
}
CANDIDATE_LIMIT = int(os.getenv("RETRIEVAL_TEST_CANDIDATE_LIMIT", "0") or "0")
CANDIDATE_OFFSET = int(os.getenv("RETRIEVAL_TEST_CANDIDATE_OFFSET", "0") or "0")


@dataclass(frozen=True)
class Project:
    disease: str
    topic: str
    project: int
    research_question: str
    disease_focus: str
    parameter_focus: str
    parameter_note: str


MPOX_DISEASE = "(mpox OR monkeypox OR monkeypox virus OR MPXV)"
COVID_DISEASE = "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus)"

PROJECTS = [
    Project(
        "covid19",
        "serial_interval",
        12,
        "What are the serial interval, generation time, and incubation period of COVID-19?",
        COVID_DISEASE,
        "(serial interval OR generation time OR generation interval OR incubation period)",
        "Source review: Alene et al. 2021, 'Serial interval and incubation period of COVID-19: a systematic review and meta-analysis'. "
        "Review-specific eligibility: include observational studies, published or unpublished, written in English, that report either serial interval/generation time/generation interval or incubation period for people diagnosed with COVID-19. "
        "Publication-date eligibility in the source review is 2020-01-01 to 2020-06-30. The review searched databases between 2020-06-01 and 2020-07-31; use publication date/article date when available rather than PubMed Create Date. "
        "Exclude inaccessible full text, case reports, letters/comments/responses, review articles, wrong disease, and papers that only cite the target parameter or use it as a fixed input assumption for another endpoint. "
        "For this P12 source review, incubation period is in scope together with serial interval and generation time.",
    ),
    Project(
        "covid19",
        "serial_interval",
        13,
        "What are the serial interval and generation time of COVID-19?",
        COVID_DISEASE,
        "(serial interval OR generation time OR generation interval OR serial distribution)",
        "Source review: 'Serial intervals and case isolation delays for Coronavirus disease 2019: A systematic review and meta-analysis'. "
        "Review-specific eligibility: include human COVID-19 studies that report or estimate serial interval, generation time, generation interval, or serial distribution from original outbreak, contact-tracing, surveillance, or modelling/reanalysis data. "
        "Do not rescue incubation-period-only papers for this project. Exclude papers that only cite serial interval/generation time from another paper, use it only as a fixed input assumption for R0/Rt/Re, or discuss transmission without reporting an extractable target-parameter estimate. "
        "Treat reviews, narrative summaries, comments, letters, protocols, and non-human/laboratory studies as out of scope unless the source review explicitly counted them as included primary evidence.",
    ),
    Project(
        "mpox",
        "fatality",
        8,
        "What is the case fatality rate of mpox, restricted to records created on or before 2023-03-20?",
        MPOX_DISEASE,
        "(case fatality rate OR CFR OR fatality rate OR mortality OR deaths OR death rate OR fatal outcomes)",
        "For fatality/severity, retain original human mpox case, outbreak, cohort, or surveillance studies only when patient outcomes are plausibly extractable. Demote reviews, policy, diagnostics-only, and papers with no explicit patient outcome reporting path.",
    ),
    Project(
        "mpox",
        "fatality",
        12,
        "What is the CFR of mpox?",
        MPOX_DISEASE,
        "(case fatality rate OR CFR OR mortality)",
        "For fatality/severity, retain original human mpox case, outbreak, cohort, or surveillance studies only when patient outcomes are plausibly extractable. Demote reviews, policy, diagnostics-only, and papers with no explicit patient outcome reporting path.",
    ),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
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


def baseline_path(project: Project) -> Path:
    return (
        REPO
        / "evaluation"
        / "screening"
        / project.disease
        / project.topic
        / f"p{project.project}"
        / "experiments"
        / EXP
        / f"project_{project.project}_screened.csv"
    )


def raw_path(project: Project) -> Path:
    return REPO / "dataset" / project.disease / "screening" / project.topic / f"p{project.project}" / "raw.csv"


def gt_path(project: Project) -> Path:
    return REPO / "dataset" / project.disease / "screening" / project.topic / f"p{project.project}" / "ground_truth.csv"


def project_meta_path(project: Project) -> Path:
    return REPO / "dataset" / project.disease / "screening" / project.topic / f"p{project.project}" / "project.json"


def load_screening_config(project: Project) -> dict[str, Any]:
    """Load the same profile thresholds/policies used by the formal runner."""
    path = REPO / "configs" / project.disease / "screening_profiles" / f"{project.topic}.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults", {}) or {}
    profile = (data.get("profiles", {}) or {}).get(f"P{project.project}", {}) or {}
    return {
        "thresholds": {
            **(defaults.get("thresholds", {}) or {}),
            **(profile.get("thresholds", {}) or {}),
        },
        "policies": {
            **(defaults.get("policies", {}) or {}),
            **(profile.get("policies", {}) or {}),
        },
    }


def scope_note(project: Project) -> str:
    path = project_meta_path(project)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    start = str(data.get("query_date_from") or "").strip()
    end = str(data.get("query_date_to") or "").strip()
    if start and end:
        return f"In-scope records must have Create Date between {start} and {end}, inclusive."
    if end:
        return f"In-scope records must have Create Date on or before {end}."
    if start:
        return f"In-scope records must have Create Date on or after {start}."
    return ""


def load_gt_pmids(project: Project) -> set[str]:
    pmids: set[str] = set()
    for row in read_csv(gt_path(project)):
        for col in ("PMID", "pmid", "gt_pmid"):
            value = (row.get(col) or "").strip()
            if value.isdigit():
                exclude = (row.get("exclude_flag") or "").strip().lower()
                if exclude not in {"review_low_evidence", "review", "low_evidence"}:
                    pmids.add(value)
                break
    return pmids


def is_include(row: dict[str, str], prefix: str = "") -> bool:
    return row.get(f"{prefix}llm_suggest", row.get("llm_suggest", "")) in {
        "strong_candidate",
        "possible_candidate",
    }


def compute_metrics(rows: list[dict[str, str]], gt_pmids: set[str], prefix: str = "") -> dict[str, float | int]:
    valid = [row for row in rows if row.get(f"{prefix}llm_suggest", row.get("llm_suggest", "")) != "error"]
    included = [row for row in valid if is_include(row, prefix=prefix)]
    tp = sum(1 for row in included if (row.get("PMID") or "").strip() in gt_pmids)
    fp = len(included) - tp
    gt_in_sample = sum(1 for row in valid if (row.get("PMID") or "").strip() in gt_pmids)
    fn = gt_in_sample - tp
    precision = tp / len(included) if included else 0.0
    recall = tp / gt_in_sample if gt_in_sample else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "n": len(valid),
        "gt": gt_in_sample,
        "included": len(included),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "nns": 1 / precision if precision else 0.0,
    }


def _safe_int(value: str) -> int:
    text = (value or "").strip()
    return int(text) if text.isdigit() else -1


def _safe_float(value: str) -> float:
    text = (value or "").strip()
    try:
        return float(text)
    except Exception:
        return -1.0


def select_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    included = [row for row in rows if is_include(row)]
    if CANDIDATE_SCOPE in {"strong_only", "strong_only_source_scope"}:
        return [row for row in included if row.get("llm_suggest") == "strong_candidate"]
    if CANDIDATE_SCOPE == "possible_only":
        return [row for row in included if row.get("llm_suggest") == "possible_candidate"]
    if CANDIDATE_SCOPE in {"nonincluded_only", "excluded_only", "rescue_only"}:
        return [row for row in rows if not is_include(row)]
    if CANDIDATE_SCOPE == "weak_includes":
        return [
            row
            for row in included
            if (
                row.get("llm_tier") == "P"
                or _safe_int(row.get("parameter_score", "")) <= 2
                or _safe_int(row.get("evidence_score", "")) <= 2
                or _safe_float(row.get("confidence", "")) < 0.7
            )
        ]
    if CANDIDATE_SCOPE in {"all", "all_candidates"}:
        return rows
    return included


def _markdown_path(pmid: str) -> Path:
    paper_dir = MD_CACHE_DIR / f"PMID_{pmid}"
    for name in (f"PMID_{pmid}.md", "full.md", "fulltext.md"):
        path = paper_dir / name
        if path.exists():
            return path
    return paper_dir / f"PMID_{pmid}.md"


def _snippet_terms(project: Project) -> list[str]:
    base = [
        "serial interval",
        "generation time",
        "generation interval",
        "incubation period",
        "case fatality",
        "fatality rate",
        "mortality",
        "death",
        "deaths",
        "reproduction number",
        "basic reproduction",
        "effective reproduction",
        "R0",
        "Rt",
        "Re",
    ]
    extra = re.findall(r"[A-Za-z][A-Za-z0-9 -]{2,}", f"{project.parameter_focus} {project.parameter_note}")
    return list(dict.fromkeys([*base, *extra]))


def build_review_snippet(text: str, row: dict[str, str], project: Project) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text or len(text) <= MAX_CONTENT_CHARS:
        return text

    chunks: list[str] = []
    used_chars = 0
    header = "\n\n".join(
        part
        for part in [
            f"Title: {(row.get('Title') or '').strip()}",
            f"Abstract: {(row.get('Abstract') or '').strip()}",
        ]
        if part.strip()
    )
    if header:
        header_budget = min(1200, max(500, MAX_CONTENT_CHARS // 3))
        chunks.append(header[:header_budget])
        used_chars += len(chunks[-1])

    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    for term in _snippet_terms(project):
        needle = term.lower().strip()
        if not needle:
            continue
        start = 0
        while True:
            idx = lowered.find(needle, start)
            if idx < 0:
                break
            spans.append((max(0, idx - SNIPPET_WINDOW_CHARS), min(len(text), idx + len(needle) + SNIPPET_WINDOW_CHARS)))
            start = idx + len(needle)
            if len(spans) >= 12:
                break
        if len(spans) >= 12:
            break

    if not spans:
        chunks.append(text[: max(0, MAX_CONTENT_CHARS - used_chars)])
        return "\n\n---\n\n".join(chunks)[:MAX_CONTENT_CHARS]

    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1] + 300:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    for idx, (start, end) in enumerate(merged, start=1):
        remaining = MAX_CONTENT_CHARS - used_chars - 10
        if remaining <= 0:
            break
        chunk = f"[Full-text evidence window {idx}]\n{text[start:end].strip()}"
        chunks.append(chunk[:remaining])
        used_chars += len(chunks[-1])
        if used_chars >= MAX_CONTENT_CHARS:
            break
    return "\n\n---\n\n".join(chunks)[:MAX_CONTENT_CHARS]


def normalize_pmcid(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.upper().replace("PMCID:", "").strip()
    if text.isdigit():
        return f"PMC{text}"
    if text.startswith("PMC") and text[3:].isdigit():
        return text
    return ""


def html_to_text(html: str) -> str:
    text = re.sub(r"<(script|style|nav|header|footer|aside)\b[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return re.sub(r"\s+", " ", text).strip()


async def fetch_direct_pmc_fulltext(
    candidates: list[dict[str, str]],
    project: Project,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not USE_DIRECT_PMC or not candidates:
        return [], candidates

    ready: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    semaphore = asyncio.Semaphore(max(1, RETRIEVAL_CONCURRENCY))

    headers = {
        "User-Agent": "MetaAgent-Epi/0.1 (mailto:yanhaoyang@example.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25.0),
        follow_redirects=True,
        headers=headers,
    ) as client:
        async def fetch_one(row: dict[str, str]) -> None:
            pmcid = normalize_pmcid(row.get("PMCID", ""))
            if not pmcid:
                missing.append(row)
                return
            url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            async with semaphore:
                try:
                    resp = await client.get(url)
                except Exception:
                    row["review_content_source"] = "pmc_missing"
                    row["review_content_path"] = url
                    missing.append(row)
                    return
            content_type = resp.headers.get("content-type", "")
            has_article = "pmc-article" in resp.text or "article-container" in resp.text
            text = html_to_text(resp.text) if resp.status_code == 200 and "text/html" in content_type and has_article else ""
            if len(text) >= 1000:
                row["review_content"] = build_review_snippet(text, row, project)
                row["review_content_source"] = "pmc_html"
                row["review_content_path"] = url
                ready.append(row)
            else:
                row["review_content_source"] = "pmc_missing"
                row["review_content_path"] = url
                missing.append(row)

        await asyncio.gather(*(fetch_one(row) for row in candidates))

    return ready, missing


def attach_cached_fulltext(
    candidates: list[dict[str, str]],
    project: Project,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ready: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for row in candidates:
        pmid = (row.get("PMID") or "").strip()
        md_path = _markdown_path(pmid)
        if md_path.exists() and md_path.stat().st_size > 0:
            enriched = build_review_snippet(md_path.read_text(encoding="utf-8"), row, project)
            row["review_content"] = enriched
            row["review_content_source"] = "cached_markdown"
            row["review_content_path"] = str(md_path.relative_to(REPO))
            ready.append(row)
        else:
            missing.append(row)
    return ready, missing


async def enrich_missing(candidates: list[dict[str, str]], project: Project) -> list[dict[str, str]]:
    ready: list[dict[str, str]] = []

    remaining = candidates
    direct_pmc_ready, remaining = await fetch_direct_pmc_fulltext(remaining, project)
    ready.extend(direct_pmc_ready)

    if USE_PMC and remaining:
        enriched_results = await batch_enrich(
            remaining,
            concurrency=RETRIEVAL_CONCURRENCY,
            try_pmc=True,
        )
        next_remaining: list[dict[str, str]] = []
        for row, enriched in enriched_results:
            if enriched.success and enriched.enriched_text.strip():
                row["review_content"] = build_enriched_prompt(row, enriched)
                row["review_content_source"] = f"pubmed_pmc:{enriched.source or 'pubmed'}"
                row["review_content_path"] = ""
                ready.append(row)
            else:
                next_remaining.append(row)
        remaining = next_remaining

    if USE_WEB and remaining:
        retrieval_results = await batch_retrieve(
            remaining,
            concurrency=RETRIEVAL_CONCURRENCY,
        )
        still_missing: list[dict[str, str]] = []
        for row, retrieval in retrieval_results:
            text = ""
            if retrieval.full_text_snippet:
                text = retrieval.full_text_snippet
            elif retrieval.enriched_abstract:
                text = retrieval.enriched_abstract
            if retrieval.success and text.strip():
                base = [
                    f"Title: {(row.get('Title') or '').strip()}",
                    f"Original Abstract: {(row.get('Abstract') or '').strip()[:2000]}",
                    f"[Retrieved evidence from {retrieval.source}]",
                    text[:3000],
                ]
                row["review_content"] = "\n\n".join(part for part in base if part.strip())
                row["review_content_source"] = f"web:{retrieval.source}"
                row["review_content_path"] = retrieval.pdf_url or retrieval.html_url or ""
                ready.append(row)
            else:
                still_missing.append(row)
        remaining = still_missing

    for row in remaining:
        row["review_content"] = ""
        row["review_content_source"] = "missing"
        row["review_content_path"] = ""

    return ready


async def rerank_candidates(
    llm: Any,
    project: Project,
    candidates: list[dict[str, str]],
) -> None:
    scoped_question = project.research_question
    note = scope_note(project)
    if USE_SCOPE_NOTE and note:
        scoped_question = f"{scoped_question} Scope note: {note}"

    def initial_label(row: dict[str, str]) -> str:
        return row.get("baseline_llm_suggest") or row.get("llm_suggest") or ""

    strong_rows = [row for row in candidates if initial_label(row) == "strong_candidate"]
    possible_rows = [row for row in candidates if initial_label(row) == "possible_candidate"]
    rescue_rows = [
        row
        for row in candidates
        if initial_label(row) not in {"strong_candidate", "possible_candidate"}
    ]

    config = {
        "research_question": scoped_question,
        "disease_focus": project.disease_focus,
        "disease_exclude": "other diseases or pathogens not matching the target disease",
        "parameter_focus": project.parameter_focus,
        "parameter_exclude": "studies that do not report, estimate, or directly measure the target parameter",
        "parameter_scoring_note": project.parameter_note,
    }
    config.update(load_screening_config(project))
    policies = config.setdefault("policies", {})
    profile_note = str(policies.get("parameter_scoring_note") or "").strip()
    if project.parameter_note and project.parameter_note not in profile_note:
        policies["parameter_scoring_note"] = "\n".join(
            part for part in (profile_note, project.parameter_note) if part
        )

    if strong_rows:
        await screen_papers_batch_async(
            strong_rows,
            research_question=scoped_question,
            llm_model=llm,
            batch_size=BATCH_SIZE,
            batch_concurrency=CONCURRENCY,
            batch_mode=BATCH_MODE,
            screening_stage=STRONG_STAGE,
            content_label="Retrieved evidence / full text",
            content_key="review_content",
            content_fallback="(No retrieved evidence available.)",
            strategy="5d",
            screening_config=config,
            prefer_llm_tier=True,
        )
    if possible_rows:
        await screen_papers_batch_async(
            possible_rows,
            research_question=scoped_question,
            llm_model=llm,
            batch_size=BATCH_SIZE,
            batch_concurrency=CONCURRENCY,
            batch_mode=BATCH_MODE,
            screening_stage=POSSIBLE_STAGE,
            content_label="Retrieved evidence / full text",
            content_key="review_content",
            content_fallback="(No retrieved evidence available.)",
            strategy="5d",
            screening_config=config,
            prefer_llm_tier=True,
        )
    if rescue_rows:
        await screen_papers_batch_async(
            rescue_rows,
            research_question=scoped_question,
            llm_model=llm,
            batch_size=BATCH_SIZE,
            batch_concurrency=CONCURRENCY,
            batch_mode=BATCH_MODE,
            screening_stage=RESCUE_STAGE,
            content_label="Retrieved evidence / full text",
            content_key="review_content",
            content_fallback="(No retrieved evidence available.)",
            strategy="5d",
            screening_config=config,
            prefer_llm_tier=True,
        )


async def run_project(llm: Any, project: Project) -> dict[str, Any]:
    print(f"\n[{project.disease}/{project.topic}/p{project.project}]")
    stage1_rows = read_csv(baseline_path(project))
    gt_pmids = load_gt_pmids(project)
    raw_rows = {(row.get("PMID") or "").strip(): row for row in read_csv(raw_path(project))}

    rows: list[dict[str, str]] = []
    for stage1 in stage1_rows:
        pmid = (stage1.get("PMID") or "").strip()
        merged = dict(raw_rows.get(pmid, {}))
        merged.update(stage1)
        for key, value in list(stage1.items()):
            merged[f"baseline_{key}"] = value
        rows.append(merged)

    baseline = compute_metrics(rows, gt_pmids, prefix="baseline_")
    candidates = select_candidates(rows)
    total_candidates = len(candidates)
    if CANDIDATE_OFFSET or CANDIDATE_LIMIT:
        end = None if CANDIDATE_LIMIT <= 0 else CANDIDATE_OFFSET + CANDIDATE_LIMIT
        candidates = candidates[CANDIDATE_OFFSET:end]
    cached_ready, missing = attach_cached_fulltext(candidates, project)
    retrieved_ready = await enrich_missing(missing, project)
    rerank_ready = cached_ready + retrieved_ready

    print(
        f"  included={baseline['included']} candidates={len(candidates)} "
        f"(selected from {total_candidates}) "
        f"cached={len(cached_ready)} enriched={len(retrieved_ready)} missing={len(missing) - len(retrieved_ready)}"
        f" strong_stage={STRONG_STAGE} possible_stage={POSSIBLE_STAGE} rescue_stage={RESCUE_STAGE}",
        flush=True,
    )

    if rerank_ready:
        await rerank_candidates(llm, project, rerank_ready)

    tuned = compute_metrics(rows, gt_pmids)
    demoted = sum(1 for row in candidates if is_include(row, prefix="baseline_") and not is_include(row))
    rescued = sum(
        1
        for row in rows
        if (row.get("PMID") or "").strip() in gt_pmids
        and not is_include(row, prefix="baseline_")
        and is_include(row)
    )

    out_file = OUT / f"{project.disease}_{project.topic}_p{project.project}_retrieval_screened_{RUN_SCOPE}.csv"
    write_csv(out_file, rows)

    print(
        "  baseline "
        f"R={baseline['recall']:.3f} P={baseline['precision']:.3f} F1={baseline['f1']:.3f} "
        f"FP={baseline['fp']} incl={baseline['included']}"
    )
    print(
        "  enriched "
        f"R={tuned['recall']:.3f} P={tuned['precision']:.3f} F1={tuned['f1']:.3f} "
        f"FP={tuned['fp']} incl={tuned['included']} demoted={demoted} rescued_fn={rescued}"
    )

    return {
        "label": f"{project.disease}/{project.topic}/p{project.project}",
        "baseline": baseline,
        "tuned": tuned,
        "candidate_scope": CANDIDATE_SCOPE,
        "strong_stage": STRONG_STAGE,
        "possible_stage": POSSIBLE_STAGE,
        "rescue_stage": RESCUE_STAGE,
        "max_content_chars": MAX_CONTENT_CHARS,
        "use_scope_note": USE_SCOPE_NOTE,
        "candidate_count": len(candidates),
        "total_candidate_count": total_candidates,
        "candidate_offset": CANDIDATE_OFFSET,
        "candidate_limit": CANDIDATE_LIMIT,
        "cached_ready": len(cached_ready),
        "retrieved_ready": len(retrieved_ready),
        "demoted_candidates": demoted,
        "rescued_fn": rescued,
        "output": str(out_file.relative_to(REPO)),
    }


def pooled_summary(project_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    def add_counts(section: str) -> dict[str, float | int]:
        tp = sum(int(item[section]["tp"]) for item in project_summaries)
        fp = sum(int(item[section]["fp"]) for item in project_summaries)
        fn = sum(int(item[section]["fn"]) for item in project_summaries)
        gt = sum(int(item[section]["gt"]) for item in project_summaries)
        included = sum(int(item[section]["included"]) for item in project_summaries)
        recall = tp / gt if gt else 0.0
        precision = tp / included if included else 0.0
        f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
        return {
            "gt": gt,
            "included": included,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "nns": 1 / precision if precision else 0.0,
        }

    return {
        "baseline": add_counts("baseline"),
        "tuned": add_counts("tuned"),
        "candidate_count": sum(int(item["candidate_count"]) for item in project_summaries),
        "cached_ready": sum(int(item["cached_ready"]) for item in project_summaries),
        "retrieved_ready": sum(int(item["retrieved_ready"]) for item in project_summaries),
        "demoted_candidates": sum(int(item["demoted_candidates"]) for item in project_summaries),
        "rescued_fn": sum(int(item["rescued_fn"]) for item in project_summaries),
    }


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    llm = init_llm_model(model_override=MODEL, provider_override=PROVIDER)
    projects = PROJECTS
    if PROJECT_FILTER:
        projects = [
            project for project in projects
            if (
                f"{project.disease}/{project.topic}/p{project.project}" in PROJECT_FILTER
                or f"{project.disease}_{project.topic}_p{project.project}" in PROJECT_FILTER
            )
        ]
    print(
        f"Running {len(projects)} project(s); model={MODEL}; provider={PROVIDER}; "
        f"batch={BATCH_SIZE}; concurrency={CONCURRENCY}; retrieval_concurrency={RETRIEVAL_CONCURRENCY}; "
        f"scope={CANDIDATE_SCOPE}; pmc={USE_PMC}; web={USE_WEB}",
        flush=True,
    )

    summaries = []
    for project in projects:
        summaries.append(await run_project(llm, project))

    pooled = pooled_summary(summaries)
    report = {
        "model": MODEL,
        "provider": PROVIDER,
        "baseline_experiment": EXP,
        "candidate_scope": CANDIDATE_SCOPE,
        "projects": summaries,
        "pooled": pooled,
    }
    summary_path = OUT / f"summary_{RUN_SCOPE}.json"
    summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== POOLED RETRIEVAL-ENRICHED SAMPLE ===")
    for name in ("baseline", "tuned"):
        metrics = pooled[name]
        print(
            f"{name:<8} R={metrics['recall']:.3f} P={metrics['precision']:.3f} "
            f"F1={metrics['f1']:.3f} NNS={metrics['nns']:.2f} "
            f"TP/FP/FN={metrics['tp']}/{metrics['fp']}/{metrics['fn']} "
            f"included={metrics['included']}"
        )
    print(
        f"candidates={pooled['candidate_count']} cached={pooled['cached_ready']} "
        f"retrieved={pooled['retrieved_ready']} demoted={pooled['demoted_candidates']} "
        f"rescued_fn={pooled['rescued_fn']}"
    )
    print(f"wrote {summary_path.relative_to(REPO)}")


if __name__ == "__main__":
    asyncio.run(main())
