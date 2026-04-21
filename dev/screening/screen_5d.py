"""5-Dimension title+abstract screener with groundtruth evaluation.

Usage
-----
    python screen_5d.py --raw project_5_raw.csv --gt project_5_groundtruth.csv

Outputs
-------
    screening_results.csv   — per-record scores + decision
    STDOUT                  — markdown confusion matrix + metrics
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from langchain_openai import ChatOpenAI

# ── project config ────────────────────────────────────────────────────────────
_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from common.config import load_llm_config  # noqa: E402

# ── screening config — edit for your review ──────────────────────────────────
RESEARCH_QUESTION = (
    "What is the infection fatality rate (IFR) of SARS-CoV-2 / COVID-19 "
    "in different populations, settings, and time periods?"
)
DISEASE_FOCUS = "SARS-CoV-2 / COVID-19"
DISEASE_EXCLUDE = "other respiratory viruses (influenza, RSV) or non-COVID diseases"
PARAMETER_FOCUS = (
    "infection fatality rate (IFR), seroprevalence combined with death counts, "
    "or case fatality rate (CFR) used to derive IFR"
)
PARAMETER_EXCLUDE = (
    "vaccine efficacy, treatment outcomes, or studies that only report "
    "transmission parameters without mortality estimates"
)

CONCURRENCY = 10          # parallel API calls
MODEL = None              # None = use LLM_MODEL from .env; or e.g. "gpt-4.1-mini"
OUTPUT_FILE = "screening_results.csv"

# Label thresholds
INCLUDE_D1_MIN = 3        # disease_score
INCLUDE_D5_MIN = 3        # parameter_score
INCLUDE_TOTAL_MIN = 12    # sum of all 5 scores

# ── prompts ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are an expert systematic review screener in epidemiology.
Score the study on five relevance dimensions. Do NOT output include/exclude language.
Return ONLY a valid JSON object — no markdown, no commentary."""

def _build_user_prompt(title: str, abstract: str, keywords: str) -> str:
    has_abstract = bool(abstract and abstract.strip())
    stage = "title and abstract" if has_abstract else "title-only"
    evidence = (
        f"Title: {title}\nAbstract: {abstract}\nKeywords: {keywords}"
        if has_abstract
        else f"Title: {title}\nKeywords: {keywords}"
    )
    conservative = (
        "Be conservative: scores 3–4 require explicit textual evidence. "
        "If only implied, use 2."
        if has_abstract
        else
        "Be conservative: scores 3–4 should be rare. Use 2 when hinted but not explicit."
    )

    return f"""\
Research question: {RESEARCH_QUESTION}
Stage: {stage} screening.

Score on these five dimensions (integer 0–4 each):
1. disease_score    — Must explicitly investigate {DISEASE_FOCUS}. Other diseases / {DISEASE_EXCLUDE} → low.
2. population_score — Human populations preferred. Animal / in vitro → low.
3. location_score   — Real-world geographic or field context preferred.
4. evidence_score   — Original empirical data preferred. Reviews, editorials, letters → low.
5. parameter_score  — Must explicitly report {PARAMETER_FOCUS}. {PARAMETER_EXCLUDE} → low.

Rubric: 4=explicit & central | 3=clearly present | 2=uncertain/indirect | 1=tangential | 0=absent
{conservative}

{evidence}

Reply with ONLY this JSON (no extra keys, no markdown):
{{
  "disease_score": <0-4>,
  "disease_justification": "<one sentence>",
  "population_score": <0-4>,
  "population_justification": "<one sentence>",
  "location_score": <0-4>,
  "location_justification": "<one sentence>",
  "evidence_score": <0-4>,
  "evidence_justification": "<one sentence>",
  "parameter_score": <0-4>,
  "parameter_justification": "<one sentence>",
  "overall_justification": "<one sentence summarising relevance>"
}}"""


# ── label rule ────────────────────────────────────────────────────────────────
def _compute_label(d1: int, d5: int, total: int) -> str:
    if d1 == 0 or d5 == 0:
        return "exclude"
    if d1 >= INCLUDE_D1_MIN and d5 >= INCLUDE_D5_MIN and total >= INCLUDE_TOTAL_MIN:
        return "include"
    return "uncertain"


# ── LLM call ──────────────────────────────────────────────────────────────────
async def _score_record(
    llm: ChatOpenAI,
    sem: asyncio.Semaphore,
    record: dict,
) -> dict:
    title    = record.get("Title", "")
    abstract = record.get("Abstract", "")
    keywords = record.get("Keywords", "")

    prompt = _build_user_prompt(title, abstract, keywords)
    mode = "title+abstract" if (abstract and abstract.strip()) else "title-only"

    for attempt in range(3):
        try:
            async with sem:
                from langchain_core.messages import HumanMessage, SystemMessage
                response = await llm.ainvoke(
                    [SystemMessage(content=SYSTEM_PROMPT),
                     HumanMessage(content=prompt)]
                )
            raw = response.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            scores = json.loads(raw)
            break
        except (json.JSONDecodeError, Exception) as exc:
            if attempt == 2:
                scores = {
                    "disease_score": 0, "disease_justification": f"parse_error: {exc}",
                    "population_score": 0, "population_justification": "",
                    "location_score": 0, "location_justification": "",
                    "evidence_score": 0, "evidence_justification": "",
                    "parameter_score": 0, "parameter_justification": "",
                    "overall_justification": f"error after 3 attempts: {exc}",
                }
            else:
                await asyncio.sleep(2 ** attempt)

    d1    = int(scores.get("disease_score", 0))
    d5    = int(scores.get("parameter_score", 0))
    total = sum(int(scores.get(k, 0)) for k in
                ["disease_score", "population_score", "location_score",
                 "evidence_score", "parameter_score"])

    return {
        **record,
        "screening_mode":            mode,
        "d1_disease":                d1,
        "disease_justification":     scores.get("disease_justification", ""),
        "d2_population":             int(scores.get("population_score", 0)),
        "population_justification":  scores.get("population_justification", ""),
        "d3_location":               int(scores.get("location_score", 0)),
        "location_justification":    scores.get("location_justification", ""),
        "d4_evidence":               int(scores.get("evidence_score", 0)),
        "evidence_justification":    scores.get("evidence_justification", ""),
        "d5_parameter":              d5,
        "parameter_justification":   scores.get("parameter_justification", ""),
        "total_score":               total,
        "decision":                  _compute_label(d1, d5, total),
        "overall_justification":     scores.get("overall_justification", ""),
    }


# ── screening runner ──────────────────────────────────────────────────────────
async def screen_all(records: list[dict], llm: ChatOpenAI) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []
    total = len(records)

    tasks = [_score_record(llm, sem, r) for r in records]
    for i, coro in enumerate(asyncio.as_completed(tasks)):
        result = await coro
        results.append(result)
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"  Screened {i + 1} / {total}", flush=True)

    # Preserve original order
    pmid_order = {str(r.get("PMID", i)): i for i, r in enumerate(records)}
    results.sort(key=lambda r: pmid_order.get(str(r.get("PMID", "")), 9999))
    return results


# ── CSV I/O ───────────────────────────────────────────────────────────────────
def load_raw(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_groundtruth_pmids(path: str) -> set[str]:
    """Return set of PMIDs that are verified/included in the groundtruth."""
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # Support gt_pmid (MetaAgent-Epi format) or PMID column
    pmid_col = "gt_pmid" if "gt_pmid" in rows[0] else "PMID"
    return {str(r[pmid_col]).strip() for r in rows
            if r.get("review_status", "").strip().lower() in {"verified", "include", "1"}}


def save_results(results: list[dict], path: str) -> None:
    if not results:
        return
    score_cols = [
        "screening_mode",
        "d1_disease", "disease_justification",
        "d2_population", "population_justification",
        "d3_location", "location_justification",
        "d4_evidence", "evidence_justification",
        "d5_parameter", "parameter_justification",
        "total_score", "decision", "overall_justification",
    ]
    base_cols = [c for c in results[0].keys() if c not in score_cols]
    fieldnames = base_cols + score_cols
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"\nSaved {len(results)} records → {path}")


# ── evaluation ────────────────────────────────────────────────────────────────
def _map_binary(decision: str) -> int:
    """include=1, uncertain treated as 0 (conservative), exclude=0."""
    return 1 if decision == "include" else 0


def evaluate_and_print(results: list[dict], gt_pmids: set[str]) -> None:
    tp = fp = fn = tn = 0
    uncertain_in_gt = 0

    for r in results:
        pmid = str(r.get("PMID", "")).strip()
        pred = r["decision"]
        truth = 1 if pmid in gt_pmids else 0
        pred_b = _map_binary(pred)

        if truth == 1 and pred_b == 1:
            tp += 1
        elif truth == 0 and pred_b == 1:
            fp += 1
        elif truth == 1 and pred_b == 0:
            fn += 1
            if pred == "uncertain":
                uncertain_in_gt += 1
        else:
            tn += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    # Work saved = fraction of records correctly excluded
    wss95 = (tn + fn) / total - (1 - recall) if total > 0 else 0.0

    # Counts per decision
    n_include   = sum(1 for r in results if r["decision"] == "include")
    n_uncertain = sum(1 for r in results if r["decision"] == "uncertain")
    n_exclude   = sum(1 for r in results if r["decision"] == "exclude")

    print("\n## Screening Results\n")
    print(f"Total screened: {total}  |  GT positives: {len(gt_pmids)}\n")

    print("### Decision Distribution\n")
    print(f"| Decision   | N      | % |")
    print(f"|------------|--------|-----|")
    print(f"| include    | {n_include:<6} | {n_include/total*100:.1f}% |")
    print(f"| uncertain  | {n_uncertain:<6} | {n_uncertain/total*100:.1f}% |")
    print(f"| exclude    | {n_exclude:<6} | {n_exclude/total*100:.1f}% |")

    print("\n### Confusion Matrix (include=positive, exclude+uncertain=negative)\n")
    print(f"|                    | **GT: include** | **GT: exclude** |")
    print(f"|--------------------|-----------------|-----------------|")
    print(f"| **Pred: include**  | TP = {tp:<10} | FP = {fp:<10} |")
    print(f"| **Pred: excl/unc** | FN = {fn:<10} | TN = {tn:<10} |")

    print("\n### Performance Metrics\n")
    print(f"| Metric      | Value  |")
    print(f"|-------------|--------|")
    print(f"| Precision   | {precision:.3f}  |")
    print(f"| Recall      | {recall:.3f}  |")
    print(f"| F1          | {f1:.3f}  |")
    print(f"| Specificity | {specificity:.3f}  |")
    print(f"| WSS@95      | {wss95:.3f}  |")

    if uncertain_in_gt > 0:
        print(f"\n> ⚠️  {uncertain_in_gt} GT-positive records classified as 'uncertain' "
              f"(counted as FN above)")


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="5D abstract screener")
    parser.add_argument("--raw", required=True, help="Raw pool CSV path")
    parser.add_argument("--gt",  default=None,  help="Groundtruth CSV path (optional)")
    parser.add_argument("--out", default=OUTPUT_FILE, help="Output CSV path")
    parser.add_argument("--model", default=MODEL, help="Override LLM model name")
    args = parser.parse_args()

    # Load config
    cfg = load_llm_config(module_hint="coding_sheet")
    model_name = args.model or cfg.model or "gpt-4.1-mini"
    http_client = httpx.Client(verify=cfg.verify_ssl, timeout=cfg.timeout_s)
    llm = ChatOpenAI(
        model=model_name,
        api_key=cfg.api_key,
        base_url=cfg.api_base or None,
        temperature=0.0,
        max_retries=3,
        request_timeout=cfg.timeout_s,
        http_client=http_client,
    )

    print(f"Model: {model_name}")
    print(f"Raw pool: {args.raw}")

    records = load_raw(args.raw)
    print(f"Loaded {len(records)} records\n")

    start = time.time()
    results = asyncio.run(screen_all(records, llm))
    elapsed = time.time() - start
    print(f"Screening complete in {elapsed:.0f}s")

    save_results(results, args.out)

    if args.gt:
        gt_pmids = load_groundtruth_pmids(args.gt)
        print(f"Groundtruth: {len(gt_pmids)} verified PMIDs")
        evaluate_and_print(results, gt_pmids)
    else:
        counts = {"include": 0, "exclude": 0, "uncertain": 0}
        for r in results:
            counts[r["decision"]] += 1
        n = len(results)
        print(f"\nInclude: {counts['include']} ({counts['include']/n*100:.1f}%)")
        print(f"Uncertain: {counts['uncertain']} ({counts['uncertain']/n*100:.1f}%)")
        print(f"Exclude: {counts['exclude']} ({counts['exclude']/n*100:.1f}%)")


if __name__ == "__main__":
    main()
