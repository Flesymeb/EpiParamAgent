"""Automated prompt optimizer for LLM-based systematic review screening.

Iteratively compresses the 5D system prompt (title+abstract stage) while keeping
recall above a minimum threshold, validated on a small sample of GT + random negatives.

Usage:
    python scripts/cli/prompt_optimizer.py \\
        --project-root /path/to/MetaAgent-Epi \\
        --profile P12 \\
        --experiment 5d_gpt54 \\
        --min-recall 0.80 \\
        --max-iterations 5 \\
        --target-reduction 25

Algorithm:
    1. Load existing screened CSV → compute baseline recall vs GT.
    2. If baseline recall >= --min-recall, begin compression loop.
    3. Each iteration: call LLM to compress current prompt by ~--target-reduction %.
    4. Validate new prompt on mini-sample (all GT papers + equal-sized random negatives).
    5. If mini-recall >= min_recall - 0.05: commit new prompt; otherwise stop.
    6. Repeat until max iterations or compression < 5 %.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import random
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

import httpx

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR.parent / "tools"))
sys.path.insert(0, str(BASE_DIR / "src"))

from metaagent.config import load_llm_config
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from metaagent.screening.engine import (
    init_llm_model,
    load_ground_truth_pmids,
    screen_papers_batch_async,
)
from metaagent.screening.profile_registry import resolve_profile_paths

PROMPT_DIR = BASE_DIR / "src" / "epidemiology" / "prompts"
SYSTEM_PROMPT_PATH = PROMPT_DIR / "5d" / "screening_system_title_abstract.md"
VARIANTS_DIR = PROMPT_DIR / "5d" / "variants"

# ── LLM prompt compressor instruction ─────────────────────────────────────────

_COMPRESS_SYSTEM = (
    "You are a technical writer specialising in concise scientific instructions.\n"
    "Rewrite the system prompt below to be approximately {pct}% shorter (by word count) "
    "while strictly preserving:\n"
    "  - All {{placeholder}} variables (e.g. {{research_question}}, {{disease_focus}})\n"
    "  - The 0–4 scoring rubric\n"
    "  - Every screening criterion and exclusion rule\n"
    "  - The Output requirements section\n"
    "Remove redundancy and tighten phrasing only. "
    "Output ONLY the rewritten prompt — no commentary, no markdown fences."
)


# ── metric helpers ─────────────────────────────────────────────────────────────

def _load_screened_map(path: Path) -> dict[str, str]:
    """Return {PMID: llm_suggest} from a screened CSV."""
    result: dict[str, str] = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pmid = (row.get("PMID") or "").strip()
            if pmid:
                result[pmid] = (row.get("llm_suggest") or "").strip()
    return result


def _compute_recall(screened: dict[str, str], gt_pmids: set[str]) -> float:
    if not gt_pmids:
        return 0.0
    retrieved = {k for k, v in screened.items() if v in ("strong_candidate", "possible_candidate")}
    return len(gt_pmids & retrieved) / len(gt_pmids)


def _compute_precision(screened: dict[str, str], gt_pmids: set[str]) -> float:
    retrieved = {k for k, v in screened.items() if v in ("strong_candidate", "possible_candidate")}
    if not retrieved:
        return 0.0
    return len(gt_pmids & retrieved) / len(retrieved)


# ── prompt compression via LLM ────────────────────────────────────────────────

def _compress_prompt(prompt_text: str, target_pct: int) -> str:
    """Ask the configured LLM to rewrite prompt_text ~target_pct% shorter."""
    cfg = load_llm_config(module_hint="screening")
    http_client = httpx.Client(verify=cfg.verify_ssl, timeout=cfg.timeout_s)
    http_async_client = httpx.AsyncClient(verify=cfg.verify_ssl)
    llm = ChatOpenAI(
        model=cfg.model or "gpt-4o-mini",
        temperature=0.3,
        api_key=cfg.api_key,
        base_url=cfg.api_base or "https://api.openai.com/v1",
        http_client=http_client,
        http_async_client=http_async_client,
        request_timeout=cfg.timeout_s,
    )
    response = llm.invoke([
        SystemMessage(content=_COMPRESS_SYSTEM.format(pct=target_pct)),
        HumanMessage(content=prompt_text),
    ])
    return response.content.strip()


# ── mini-sample construction ──────────────────────────────────────────────────

def _load_raw_papers(raw_file: Path) -> list[dict[str, Any]]:
    with open(raw_file, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _build_mini_sample(
    raw_papers: list[dict[str, Any]],
    gt_pmids: set[str],
    seed: int,
) -> list[dict[str, Any]]:
    """All GT papers from the pool + an equal-sized random negative sample."""
    gt_papers = [p for p in raw_papers if (p.get("PMID") or "").strip() in gt_pmids]
    non_gt = [p for p in raw_papers if (p.get("PMID") or "").strip() not in gt_pmids]
    rng = random.Random(seed)
    neg_sample = rng.sample(non_gt, min(len(gt_papers), len(non_gt)))
    combined = gt_papers + neg_sample
    rng.shuffle(combined)
    return combined


# ── temporary prompt swap ─────────────────────────────────────────────────────

@contextmanager
def _swap_prompt(path: Path, new_text: str) -> Generator[None, None, None]:
    """Temporarily write new_text to path; restore original on exit."""
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(new_text, encoding="utf-8")
        yield
    finally:
        path.write_text(original, encoding="utf-8")


# ── mini validation ───────────────────────────────────────────────────────────

async def _screen_sample_async(
    papers: list[dict[str, Any]],
    screening_config: dict[str, Any],
    llm_model: Any,
) -> list[dict[str, Any]]:
    return await screen_papers_batch_async(
        papers=copy.deepcopy(papers),
        research_question=screening_config["research_question"],
        llm_model=llm_model,
        batch_size=10,
        batch_concurrency=2,
        screening_config=screening_config,
        screening_stage="title_abstract",
        content_label="Abstract",
        content_key="Abstract",
        strategy="5d",
    )


def _validate_prompt(
    new_prompt: str,
    sample: list[dict[str, Any]],
    gt_pmids: set[str],
    screening_config: dict[str, Any],
    llm_model: Any,
    prompt_path: Path,
) -> float:
    """Screen mini-sample with new_prompt; return recall on GT papers in sample."""
    sample_gt = {(p.get("PMID") or "").strip() for p in sample} & gt_pmids
    with _swap_prompt(prompt_path, new_prompt):
        screened = asyncio.run(_screen_sample_async(sample, screening_config, llm_model))
    screened_map = {(p.get("PMID") or "").strip(): p.get("llm_suggest", "") for p in screened}
    return _compute_recall(screened_map, sample_gt)


# ── main optimization loop ────────────────────────────────────────────────────

def run_optimizer(
    *,
    screened_file: Path,
    gt_file: Path,
    raw_file: Path,
    screening_config: dict[str, Any],
    prompt_path: Path,
    min_recall: float,
    max_iterations: int,
    target_reduction_pct: int,
    seed: int,
) -> list[dict[str, Any]]:
    gt_pmids = load_ground_truth_pmids(gt_file)
    screened_map = _load_screened_map(screened_file)

    baseline_recall = _compute_recall(screened_map, gt_pmids)
    baseline_precision = _compute_precision(screened_map, gt_pmids)
    gt_in_screened = sum(1 for p in gt_pmids if p in screened_map)

    print(f"\n{'='*60}")
    print("Prompt Optimizer")
    print(f"{'='*60}")
    print(f"GT papers: {len(gt_pmids)} total, {gt_in_screened} in pool")
    print(f"Baseline recall:    {baseline_recall:.3f}")
    print(f"Baseline precision: {baseline_precision:.3f}")
    print(f"Min recall threshold: {min_recall}")
    print(f"Max iterations: {max_iterations}  |  Target reduction/iter: {target_reduction_pct}%")

    if baseline_recall < min_recall:
        print(f"\nBaseline recall {baseline_recall:.3f} < threshold {min_recall}. Skipping.")
        return []

    raw_papers = _load_raw_papers(raw_file)
    mini_sample = _build_mini_sample(raw_papers, gt_pmids, seed=seed)
    print(f"\nMini-sample: {len(mini_sample)} papers "
          f"({sum(1 for p in mini_sample if (p.get('PMID') or '').strip() in gt_pmids)} GT + "
          f"{sum(1 for p in mini_sample if (p.get('PMID') or '').strip() not in gt_pmids)} neg)")

    llm_model = init_llm_model()
    current_prompt = prompt_path.read_text(encoding="utf-8")
    log: list[dict[str, Any]] = []
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)

    for iteration in range(1, max_iterations + 1):
        print(f"\n{'─'*60}")
        print(f"Iteration {iteration}/{max_iterations}")
        orig_words = len(current_prompt.split())
        print(f"Current: {orig_words} words — compressing by ~{target_reduction_pct}%...")

        new_prompt = _compress_prompt(current_prompt, target_reduction_pct)
        new_words = len(new_prompt.split())
        actual_reduction = round((1 - new_words / orig_words) * 100, 1)
        print(f"Compressed: {new_words} words  ({actual_reduction:+.1f}% change)")

        if actual_reduction < 3:
            print("Compression < 3% — no meaningful reduction. Stopping.")
            log.append({
                "iteration": iteration,
                "outcome": "stopped_no_compression",
                "orig_words": orig_words,
                "new_words": new_words,
                "reduction_pct": actual_reduction,
                "timestamp": datetime.now().isoformat(),
            })
            break

        print("Running mini-sample validation...")
        mini_recall = _validate_prompt(
            new_prompt=new_prompt,
            sample=mini_sample,
            gt_pmids=gt_pmids,
            screening_config=screening_config,
            llm_model=llm_model,
            prompt_path=prompt_path,
        )
        tolerance = 0.05
        threshold = min_recall - tolerance
        print(f"Mini-recall: {mini_recall:.3f}  (need >= {threshold:.3f})")

        accepted = mini_recall >= threshold
        entry: dict[str, Any] = {
            "iteration": iteration,
            "outcome": "accepted" if accepted else "rejected",
            "orig_words": orig_words,
            "new_words": new_words,
            "reduction_pct": actual_reduction,
            "mini_recall": round(mini_recall, 4),
            "recall_threshold": threshold,
            "timestamp": datetime.now().isoformat(),
        }
        log.append(entry)

        if accepted:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = VARIANTS_DIR / f"iter{iteration}_{orig_words}w_{ts}.md"
            backup_path.write_text(current_prompt, encoding="utf-8")
            prompt_path.write_text(new_prompt, encoding="utf-8")
            print(f"Accepted. Backup saved: variants/{backup_path.name}")
            current_prompt = new_prompt
        else:
            print("Rejected — recall dropped below threshold. Stopping.")
            break

    return log


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iteratively compress the screening system prompt while preserving recall."
    )
    parser.add_argument("--project-root", required=True, help="MetaAgent-Epi root directory")
    parser.add_argument("--profile", required=True, help="Screening profile name (e.g. P12)")
    parser.add_argument("--experiment", default="", help="Experiment subdirectory for screened output")
    parser.add_argument("--topic", default="", help="Override topic key")
    parser.add_argument(
        "--min-recall", type=float, default=0.80,
        help="Minimum acceptable recall on full screened results (default: 0.80)"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=5,
        help="Maximum number of compression iterations (default: 5)"
    )
    parser.add_argument(
        "--target-reduction", type=int, default=25,
        help="Target word-count reduction per iteration in %% (default: 25)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for negative sample selection")
    args = parser.parse_args()

    profile, paths = resolve_profile_paths(
        project_root=args.project_root,
        profile_name=args.profile,
        topic=args.topic or None,
        experiment=args.experiment or None,
    )
    screening_config = profile.to_screening_config()

    log = run_optimizer(
        screened_file=paths.screened_file,
        gt_file=paths.ground_truth_file,
        raw_file=paths.raw_file,
        screening_config=screening_config,
        prompt_path=SYSTEM_PROMPT_PATH,
        min_recall=args.min_recall,
        max_iterations=args.max_iterations,
        target_reduction_pct=args.target_reduction,
        seed=args.seed,
    )

    if not log:
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = VARIANTS_DIR / f"opt_log_{ts}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nLog saved: {log_path}")

    accepted = [e for e in log if e.get("outcome") == "accepted"]
    if accepted:
        last = accepted[-1]
        total_reduction = round((1 - last["new_words"] / log[0]["orig_words"]) * 100, 1)
        print(
            f"\nFinal: {log[0]['orig_words']} → {last['new_words']} words "
            f"({total_reduction}% total reduction), "
            f"mini-recall={last['mini_recall']:.3f}"
        )
    else:
        print("\nNo iterations accepted — original prompt retained.")


if __name__ == "__main__":
    main()
