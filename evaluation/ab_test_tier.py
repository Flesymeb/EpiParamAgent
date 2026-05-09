#!/usr/bin/env python3
"""A/B test: code-side thresholds vs LLM self-tier (S/P/U) on COVID p14.

Minimal standalone script — reuses engine directly, no CLI subprocess.
"""

import asyncio, csv, sys, time, math
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
sys.path.insert(0, str(REPO))

from metaagent.screening.engine import init_llm_model, screen_papers_batch_async
from metaagent.config import load_llm_config

RAW = REPO / "dataset/covid19/screening/serial_interval/p14/raw.csv"
GT  = REPO / "dataset/covid19/screening/serial_interval/p14/ground_truth.csv"
OUT = REPO / "evaluation/screening/covid19/serial_interval/p14/experiments/ab_tier_test"

RESEARCH_QUESTION = "What is the serial interval of COVID-19?"
STRATEGY = "5d"
BATCH_SIZE = 20
CONCURRENCY = 2
BATCH_MODE = "single"
MODEL_NAME = "deepseek/deepseek-v4-pro"
PROVIDER = "openrouter"


def load_papers(csv_path):
    with open(csv_path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_gt(csv_path):
    pmids = set()
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for col in ("PMID", "gt_pmid"):
                v = (row.get(col, "") or "").strip()
                if v.isdigit():
                    excl = (row.get("exclude_flag", "") or "").strip().lower()
                    if excl not in ("review_low_evidence", "review", "low_evidence"):
                        pmids.add(v)
                    break
    return pmids


def compute_metrics(papers, gt_pmids):
    valid = [p for p in papers if p.get("llm_suggest") != "error"]
    inc = [p for p in valid if p["llm_suggest"] in ("strong_candidate", "possible_candidate")]
    strong = [p for p in inc if p["llm_suggest"] == "strong_candidate"]
    possible = [p for p in inc if p["llm_suggest"] == "possible_candidate"]
    unlikely = [p for p in valid if p["llm_suggest"] == "unlikely_candidate"]

    tp = sum(1 for p in inc if p["PMID"].strip() in gt_pmids)
    fp = len(inc) - tp
    fn = len(gt_pmids) - tp
    tn = sum(1 for p in unlikely if p["PMID"].strip() not in gt_pmids)

    recall = tp / len(gt_pmids) if gt_pmids else 0
    prec = tp / len(inc) if inc else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) else 0
    wr = (len(valid) - len(inc)) / len(valid) if valid else 0

    strong_tp = sum(1 for p in strong if p["PMID"].strip() in gt_pmids)
    strong_prec = strong_tp / len(strong) if strong else 0
    poss_tp = sum(1 for p in possible if p["PMID"].strip() in gt_pmids)
    poss_prec = poss_tp / len(possible) if possible else 0

    return {
        "total": len(valid), "errors": len(papers) - len(valid),
        "gt": len(gt_pmids), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "included": len(inc), "excluded": len(unlikely),
        "strong_n": len(strong), "strong_tp": strong_tp, "strong_prec": strong_prec,
        "poss_n": len(possible), "poss_tp": poss_tp, "poss_prec": poss_prec,
        "recall": recall, "precision": prec, "f1": f1, "wr": wr,
    }


async def run_one(label, prefer_llm_tier):
    print(f"\n{'='*60}")
    print(f"Running: {label} (prefer_llm_tier={prefer_llm_tier})")
    print(f"{'='*60}")

    papers = load_papers(RAW)
    gt_pmids = load_gt(GT)
    print(f"Papers: {len(papers)}, GT: {len(gt_pmids)}")

    llm = init_llm_model(model_override=MODEL_NAME, provider_override=PROVIDER)

    t0 = time.perf_counter()
    await screen_papers_batch_async(
        papers,
        research_question=RESEARCH_QUESTION,
        llm_model=llm,
        batch_size=BATCH_SIZE,
        batch_concurrency=CONCURRENCY,
        batch_mode=BATCH_MODE,
        screening_stage="title_abstract",
        content_label="Abstract",
        content_key="Abstract",
        content_fallback="(Abstract unavailable)",
        strategy=STRATEGY,
        prefer_llm_tier=prefer_llm_tier,
    )
    elapsed = time.perf_counter() - t0

    metrics = compute_metrics(papers, gt_pmids)
    metrics["elapsed_s"] = elapsed
    metrics["label"] = label
    metrics["prefer_llm_tier"] = prefer_llm_tier

    # Save output
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "llm_tier" if prefer_llm_tier else "code_threshold"
    out_file = OUT / f"project_14_screened_{suffix}.csv"
    fieldnames = list(papers[0].keys())
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(papers)
    print(f"Saved to {out_file}")

    return metrics


def fmt_pct(v):
    return f"{v*100:.1f}%"


def main():
    gt_pmids = load_gt(GT)

    # Run both
    results = {}
    for prefer in [False, True]:
        label = "LLM-tier (S/P/U)" if prefer else "Code-threshold (default)"
        metrics = asyncio.run(run_one(label, prefer))
        results["llm_tier" if prefer else "code"] = metrics

    # --- Print comparison ---
    print("\n" + "=" * 70)
    print("A/B COMPARISON: Code-threshold vs LLM self-tier (S/P/U)")
    print(f"Project: COVID p14 (serial_interval), GT={len(gt_pmids)}, pool={sum(1 for _ in open(RAW))-1}")
    print("=" * 70)

    r0 = results["code"]
    r1 = results["llm_tier"]

    print(f"\n{'Metric':<25} {'Code-threshold':>18} {'LLM-tier(S/P/U)':>18} {'Δ':>10}")
    print("-" * 73)
    for key, label in [
        ("recall", "Recall"), ("precision", "Precision"), ("f1", "F1"),
        ("wr", "Work Saved"), ("included", "# Included"), ("excluded", "# Excluded"),
        ("strong_n", "# Strong"), ("strong_tp", "Strong TP"), ("strong_prec", "Strong Precision"),
        ("poss_n", "# Possible"), ("poss_tp", "Poss TP"), ("poss_prec", "Poss Precision"),
        ("errors", "# Errors"), ("elapsed_s", "Time (s)"),
    ]:
        v0 = r0[key]
        v1 = r1[key]
        if isinstance(v0, float):
            delta = v1 - v0
            print(f"{label:<25} {v0:>18.4f} {v1:>18.4f} {delta:>+10.4f}")
        else:
            delta = v1 - v0
            print(f"{label:<25} {v0:>18} {v1:>18} {delta:>+10}")

    # Distribution comparison
    print(f"\n--- S/P/U distribution ---")
    print(f"{'Tier':<12} {'Code-threshold':>18} {'LLM-tier':>18}")
    print("-" * 50)
    # Load saved CSVs to compare distributions
    for suffix, label in [("code_threshold", "Code-threshold"), ("llm_tier", "LLM-tier")]:
        f = OUT / f"project_14_screened_{suffix}.csv"
        with open(f, encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        dist = {"S": 0, "P": 0, "U": 0}
        for r in rows:
            if r.get("llm_suggest") == "error":
                continue
            s = r["llm_suggest"]
            if s == "strong_candidate": dist["S"] += 1
            elif s == "possible_candidate": dist["P"] += 1
            else: dist["U"] += 1
        print(f"{label:<12} S={dist['S']:>3}  P={dist['P']:>3}  U={dist['U']:>3}")

    # Also show LLM-tier distribution for the tier run
    print(f"\n--- LLM self-reported tier distribution ---")
    f = OUT / "project_14_screened_llm_tier.csv"
    with open(f, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    tier_dist = {"S": 0, "P": 0, "U": 0, "None": 0}
    for r in rows:
        t = (r.get("llm_tier") or "").strip().upper()
        if t in ("S", "P", "U"):
            tier_dist[t] += 1
        else:
            tier_dist["None"] += 1
    print(f"  S={tier_dist['S']}, P={tier_dist['P']}, U={tier_dist['U']}, None(fallback)={tier_dist['None']}")

    # Conclusion
    print(f"\n--- Conclusion ---")
    r_delta = r1["recall"] - r0["recall"]
    p_delta = r1["precision"] - r0["precision"]
    if r1["f1"] > r0["f1"]:
        print(f"✅ LLM-tier IMPROVES F1 ({r0['f1']:.3f} → {r1['f1']:.3f}, Δ=+{r1['f1']-r0['f1']:.3f})")
    else:
        print(f"❌ LLM-tier DEGRADES F1 ({r0['f1']:.3f} → {r1['f1']:.3f}, Δ={r1['f1']-r0['f1']:.3f})")

    if r_delta > 0:
        print(f"   Recall improved: {fmt_pct(r0['recall'])} → {fmt_pct(r1['recall'])} (Δ=+{fmt_pct(r_delta)})")
    else:
        print(f"   Recall degraded: {fmt_pct(r0['recall'])} → {fmt_pct(r1['recall'])} (Δ={fmt_pct(r_delta)})")

    if p_delta > 0:
        print(f"   Precision improved: {fmt_pct(r0['precision'])} → {fmt_pct(r1['precision'])} (Δ=+{fmt_pct(p_delta)})")
    else:
        print(f"   Precision degraded: {fmt_pct(r0['precision'])} → {fmt_pct(r1['precision'])} (Δ={fmt_pct(p_delta)})")

    verdict = (
        "WORTH ENABLING BY DEFAULT" if r1["f1"] > r0["f1"]
        else "KEEP AS EXPERIMENTAL OPTION"
    )
    print(f"\n   Recommendation: {verdict}")


if __name__ == "__main__":
    main()
