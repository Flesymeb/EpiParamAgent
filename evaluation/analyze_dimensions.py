#!/usr/bin/env python3
"""Dimension-level contribution analysis for 5D screening.

Key analyses for PNAS paper:
1. Per-dimension score distribution by suggest type (Strong/Possible/Unlikely)
2. Which dimensions drive classification decisions
3. Per-dimension precision (how often does dimension score predict GT membership)
4. Dimension score correlation with overall decision
5. Feature importance via logistic regression
"""

import csv, json, math
from collections import defaultdict
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
DATASET = REPO / "dataset" / "covid19" / "screening"
EVAL = REPO / "evaluation" / "screening" / "covid19"
EXP_DIR = "cmp_covid13_deepseek_deepseek-v4-flash_5d_nofulltext_c16"
TOPICS = {
    "fatality": [4, 5, 6],
    "reproduction_number": [7, 8, 15, 16, 17],
    "serial_interval": [10, 11, 12, 13, 14],
}


def safe_int(v):
    try: return int(float(v))
    except: return -1


def load_gt(gt_file):
    pmids = set()
    if not gt_file.exists():
        return pmids
    with open(gt_file, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for col in ("PMID", "gt_pmid"):
                val = (row.get(col) or "").strip()
                if val.isdigit():
                    excl = (row.get("exclude_flag") or "").strip().lower()
                    if excl not in ("review_low_evidence", "review", "low_evidence"):
                        pmids.add(val)
                    break
    return pmids


def main():
    # Collect all screened papers with GT labels
    all_papers = []
    for topic, pnums in TOPICS.items():
        for pnum in pnums:
            gt_file = DATASET / topic / f"p{pnum}" / "ground_truth.csv"
            scr_file = EVAL / topic / f"p{pnum}" / "experiments" / EXP_DIR / f"project_{pnum}_screened.csv"
            if not scr_file.exists():
                continue
            gt = load_gt(gt_file)
            with open(scr_file, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    if row.get("llm_suggest") == "error":
                        continue
                    pmid = row["PMID"].strip()
                    all_papers.append({
                        "pmid": pmid,
                        "is_gt": pmid in gt,
                        "suggest": row["llm_suggest"],
                        "overall": safe_int(row.get("overall_score")),
                        "D": safe_int(row.get("disease_score")),
                        "P": safe_int(row.get("population_score")),
                        "L": safe_int(row.get("location_score")),
                        "E": safe_int(row.get("evidence_score")),
                        "Par": safe_int(row.get("parameter_score")),
                        "conf": float(row.get("confidence") or 0),
                        "topic": topic,
                    })

    n = len(all_papers)
    gt_n = sum(1 for p in all_papers if p["is_gt"])
    print(f"Total papers: {n}, GT: {gt_n} ({gt_n/n*100:.1f}%)")
    print()

    # 1. Score distribution by suggest type
    print("=" * 100)
    print("1. PER-DIMENSION SCORE DISTRIBUTION BY SUGGEST TYPE")
    print("=" * 100)
    for suggest in ["strong_candidate", "possible_candidate", "unlikely_candidate"]:
        papers = [p for p in all_papers if p["suggest"] == suggest]
        if not papers:
            continue
        print(f"\n## {suggest} (n={len(papers)}, GT={sum(1 for p in papers if p['is_gt'])})")
        for dim in ["D", "P", "L", "E", "Par"]:
            dist = defaultdict(int)
            for p in papers:
                dist[p[dim]] += 1
            dist_str = "  ".join(f"{k}:{v}" for k, v in sorted(dist.items()))
            # Among papers with this score, what fraction are GT?
            prec_str = ""
            for score in sorted(dist):
                at_score = [p for p in papers if p[dim] == score]
                gt_at = sum(1 for p in at_score if p["is_gt"])
                prec_str += f"  [{score}→{gt_at}/{len(at_score)}={gt_at/len(at_score)*100:.0f}%]" if at_score else ""
            print(f"  {dim:>4}: {dist_str}")
            if prec_str:
                print(f"       precision:{prec_str}")

    # 2. GT rate by dimension score (pooled)
    print("\n" + "=" * 100)
    print("2. GT RATE BY DIMENSION SCORE (all papers pooled)")
    print("=" * 100)
    for dim in ["D", "P", "L", "E", "Par"]:
        print(f"\n## Dimension: {dim}")
        for score in range(5):
            at = [p for p in all_papers if p[dim] == score]
            gt_at = sum(1 for p in at if p["is_gt"])
            pct = gt_at / len(at) * 100 if at else 0
            bar = "█" * int(pct / 2)
            print(f"  score={score}: {gt_at:>4}/{len(at):>5} ({pct:5.1f}%) {bar}")

    # 3. Score threshold analysis: what if we filtered by each dimension?
    print("\n" + "=" * 100)
    print("3. THRESHOLD SWEEP: Recall/Precision by dimension cutoff")
    print("=" * 100)
    for dim in ["D", "P", "L", "E", "Par"]:
        print(f"\n## Dimension: {dim}")
        print(f"  {'Cut≥':<8} {'Included':>8} {'TP':>6} {'Recall':>8} {'Precision':>10} {'F1':>8}")
        for cutoff in range(5):
            inc = [p for p in all_papers if p[dim] >= cutoff]
            tp = sum(1 for p in inc if p["is_gt"])
            r = tp / gt_n if gt_n else 0
            p = tp / len(inc) if inc else 0
            f1 = 2 * r * p / (r + p) if (r + p) else 0
            print(f"  {cutoff:<8} {len(inc):>8} {tp:>6} {r:>7.1%} {p:>9.1%} {f1:>8.3f}")

    # 4. Logistic regression: feature importance
    print("\n" + "=" * 100)
    print("4. FEATURE IMPORTANCE (logistic regression predicting GT membership)")
    print("=" * 100)
    try:
        from sklearn.linear_model import LogisticRegression
        import numpy as np
        X = np.array([[p["D"], p["P"], p["L"], p["E"], p["Par"]] for p in all_papers])
        y = np.array([1 if p["is_gt"] else 0 for p in all_papers])
        model = LogisticRegression(max_iter=1000, class_weight="balanced")
        model.fit(X, y)
        print(f"  Intercept: {model.intercept_[0]:.4f}")
        for i, dim in enumerate(["Disease", "Population", "Location", "Evidence", "Parameter"]):
            print(f"  {dim:<12}: coef={model.coef_[0][i]:+.4f}")
        print(f"  Train accuracy: {model.score(X, y):.3f}")
    except ImportError:
        print("  sklearn not available, skipping")

    # 5. Strong papers: which dimension fails?
    print("\n" + "=" * 100)
    print("5. STRONG FP: WHICH DIMENSION IS WRONG?")
    print("=" * 100)
    strong_fp = [p for p in all_papers if p["suggest"] == "strong_candidate" and not p["is_gt"]]
    strong_tp = [p for p in all_papers if p["suggest"] == "strong_candidate" and p["is_gt"]]

    print(f"\nStrong TP (n={len(strong_tp)}) avg scores:")
    for dim in ["D", "P", "L", "E", "Par"]:
        avg_tp = sum(p[dim] for p in strong_tp) / len(strong_tp) if strong_tp else 0
        print(f"  {dim}: {avg_tp:.2f}")

    print(f"\nStrong FP (n={len(strong_fp)}) avg scores:")
    for dim in ["D", "P", "L", "E", "Par"]:
        avg_fp = sum(p[dim] for p in strong_fp) / len(strong_fp) if strong_fp else 0
        print(f"  {dim}: {avg_fp:.2f}")

    print(f"\nDelta (TP - FP):")
    for dim in ["D", "P", "L", "E", "Par"]:
        avg_tp = sum(p[dim] for p in strong_tp) / len(strong_tp) if strong_tp else 0
        avg_fp = sum(p[dim] for p in strong_fp) / len(strong_fp) if strong_fp else 0
        print(f"  {dim}: {avg_tp - avg_fp:+.2f}")

    # 6. NNS analysis
    print("\n" + "=" * 100)
    print("6. NUMBER NEEDED TO SCREEN (NNS)")
    print("=" * 100)
    for label, papers_filter in [
        ("All included", lambda p: p["suggest"] in ("strong_candidate", "possible_candidate")),
        ("Strong only", lambda p: p["suggest"] == "strong_candidate"),
        ("Possible only", lambda p: p["suggest"] == "possible_candidate"),
    ]:
        inc = [p for p in all_papers if papers_filter(p)]
        tp = sum(1 for p in inc if p["is_gt"])
        nns = len(inc) / tp if tp else float("inf")
        print(f"  {label:<20}: NNS = {nns:.1f} ({len(inc)} papers to find {tp} GT)")


if __name__ == "__main__":
    main()
