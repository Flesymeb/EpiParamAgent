#!/usr/bin/env python3
"""Comprehensive 5D screening failure case analysis for COVID-19 and MPOX.

Analysis:
  1. TP/FP/TN/FN per project, per topic, and pooled
  2. Failure case breakdown: what dimension scores look like for FP and FN
  3. Strong vs Possible accuracy: how many in each bucket are true GT papers
  4. Wilson 95% CIs for all metrics
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
DATASET = REPO / "dataset"
EVAL = REPO / "evaluation" / "screening"

# (disease, topic, project_num, experiment_dir)
COVID_DEEPSEEK = "cmp_covid13_deepseek_deepseek-v4-flash_5d_nofulltext_c16"
MPOX_DEEPSEEK = "5d_dsv4pro_v4"

PROJECTS = []

# COVID-19
for topic, nums in [
    ("fatality", [4, 5, 6, 9]),
    ("reproduction_number", [7, 8, 15, 16, 17]),
    ("serial_interval", [10, 11, 12, 13, 14]),
]:
    for n in nums:
        gt_file = DATASET / "covid19" / "screening" / topic / f"p{n}" / "ground_truth.csv"
        raw_file = DATASET / "covid19" / "screening" / topic / f"p{n}" / "raw.csv"
        scr_file = EVAL / "covid19" / topic / f"p{n}" / "experiments" / COVID_DEEPSEEK / f"project_{n}_screened.csv"
        if scr_file.exists() and gt_file.exists():
            PROJECTS.append(("covid19", topic, n, gt_file, raw_file, scr_file))

# MPOX
for topic, nums in [
    ("fatality", [4, 7, 8, 12]),
    ("serial_interval", [5, 6, 10, 11]),
    ("reproduction_number", [9]),
]:
    for n in nums:
        gt_file = DATASET / "mpox" / "screening" / topic / f"p{n}" / "ground_truth.csv"
        raw_file = DATASET / "mpox" / "screening" / topic / f"p{n}" / "raw.csv"
        scr_file = EVAL / "mpox" / topic / f"p{n}" / "experiments" / MPOX_DEEPSEEK / f"project_{n}_screened.csv"
        if scr_file.exists() and gt_file.exists():
            PROJECTS.append(("mpox", topic, n, gt_file, raw_file, scr_file))


def wilson_ci(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def fmt_ci(lo, hi, pct=True):
    if pct:
        return f"{lo*100:.1f}%–{hi*100:.1f}%"
    return f"{lo:.2f}–{hi:.2f}"


def fmt_pct(v):
    return f"{v*100:.1f}%"


def safe_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def load_gt(gt_file):
    """Load ground truth PMIDs, respecting exclude_flag.

    Supports both 'PMID' and 'gt_pmid' column names.
    """
    pmids = set()
    with open(gt_file, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try multiple column names for PMID
            pmid = ""
            for col in ("PMID", "gt_pmid", "pmid"):
                val = (row.get(col) or "").strip()
                if val and val.isdigit():
                    pmid = val
                    break
            if not pmid:
                # Try case-insensitive match
                for k, v in row.items():
                    if k and k.strip().lower() in ("pmid", "gt_pmid") and v:
                        val = v.strip()
                        if val.isdigit():
                            pmid = val
                            break
            if not pmid:
                continue
            # Check exclude flag
            excl = (row.get("exclude_flag") or "").strip().lower()
            if excl in ("review_low_evidence", "review", "low_evidence"):
                continue
            pmids.add(pmid)
    return pmids


def analyze():
    all_details = []
    topic_agg = defaultdict(lambda: {"gt": 0, "pool": 0, "tp": 0, "fp": 0, "fn": 0, "total_screened": 0,
                                      "strong_tp": 0, "strong_fp": 0, "possible_tp": 0, "possible_fp": 0,
                                      "strong_total": 0, "possible_total": 0})

    for disease, topic, pnum, gt_file, raw_file, scr_file in PROJECTS:
        gt_pmids = load_gt(gt_file)
        # Pool size
        pool_n = 0
        if raw_file.exists():
            with open(raw_file, encoding="utf-8-sig") as f:
                pool_n = sum(1 for _ in f) - 1

        # Screened results
        rows = []
        with open(scr_file, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append(row)

        valid = [r for r in rows if r.get("llm_suggest") != "error"]
        total_screened = len(valid)

        inc = [r for r in valid if r["llm_suggest"] in ("strong_candidate", "possible_candidate")]
        strong = [r for r in valid if r["llm_suggest"] == "strong_candidate"]
        possible = [r for r in valid if r["llm_suggest"] == "possible_candidate"]
        unlikely = [r for r in valid if r["llm_suggest"] == "unlikely_candidate"]

        tp = [r for r in inc if r.get("PMID", "").strip() in gt_pmids]
        fp = [r for r in inc if r.get("PMID", "").strip() not in gt_pmids]
        fn = gt_pmids - set(r["PMID"].strip() for r in inc)
        tn = [r for r in unlikely if r.get("PMID", "").strip() not in gt_pmids]

        strong_tp = [r for r in strong if r.get("PMID", "").strip() in gt_pmids]
        strong_fp = [r for r in strong if r.get("PMID", "").strip() not in gt_pmids]
        possible_tp = [r for r in possible if r.get("PMID", "").strip() in gt_pmids]
        possible_fp = [r for r in possible if r.get("PMID", "").strip() not in gt_pmids]

        # FN details: papers in GT but not included
        fn_pmids = fn
        fn_rows = [r for r in valid if r.get("PMID", "").strip() in fn_pmids]

        recall = len(tp) / len(gt_pmids) if gt_pmids else 0.0
        prec = len(tp) / len(inc) if inc else 0.0
        wr = len(unlikely) / len(valid) if valid else 0.0
        strong_prec = len(strong_tp) / len(strong) if strong else 0.0
        possible_prec = len(possible_tp) / len(possible) if possible else 0.0

        proj_label = f"{disease}/{topic}/p{pnum}"
        detail = {
            "disease": disease, "topic": topic, "project": pnum, "label": proj_label,
            "gt_n": len(gt_pmids), "pool_n": pool_n, "total_screened": total_screened,
            "tp": len(tp), "fp": len(fp), "fn": len(fn), "tn": len(tn),
            "strong_n": len(strong), "strong_tp": len(strong_tp), "strong_fp": len(strong_fp),
            "possible_n": len(possible), "possible_tp": len(possible_tp), "possible_fp": len(possible_fp),
            "recall": recall, "precision": prec, "wr": wr,
            "strong_precision": strong_prec, "possible_precision": possible_prec,
            "recall_ci": wilson_ci(recall, len(gt_pmids)),
            "prec_ci": wilson_ci(prec, len(inc)),
            # Failure cases
            "fp_rows": fp,
            "fn_rows": fn_rows,
            "fn_pmids": fn_pmids,
        }
        all_details.append(detail)

        # Aggregate
        key = f"{disease}/{topic}"
        t = topic_agg[key]
        t["gt"] += len(gt_pmids)
        t["pool"] += pool_n
        t["tp"] += len(tp)
        t["fp"] += len(fp)
        t["fn"] += len(fn)
        t["total_screened"] += total_screened
        t["strong_tp"] += len(strong_tp)
        t["strong_fp"] += len(strong_fp)
        t["possible_tp"] += len(possible_tp)
        t["possible_fp"] += len(possible_fp)
        t["strong_total"] += len(strong)
        t["possible_total"] += len(possible)

    return all_details, topic_agg


def print_overall_table(details, topic_agg):
    print("\n" + "=" * 120)
    print("5D SCREENING COMPREHENSIVE ANALYSIS: COVID-19 & MPOX")
    print("=" * 120)

    # Per-project table
    print("\n## Per-Project Results\n")
    header = f"{'Disease':<8} {'Topic':<20} {'P':>4} {'GT':>4} {'Pool':>5} {'TP':>4} {'FP':>4} {'FN':>4} {'Recall':>10} {'Prec':>10} {'WR':>10} {'Strong':>8} {'S_prec':>8} {'Poss':>6} {'P_prec':>8}"
    print(header)
    print("-" * len(header))

    for d in sorted(details, key=lambda x: (x["disease"], x["topic"], x["project"])):
        print(f"{d['disease']:<8} {d['topic']:<20} {d['project']:>4} {d['gt_n']:>4} {d['pool_n']:>5} "
              f"{d['tp']:>4} {d['fp']:>4} {d['fn']:>4} "
              f"{fmt_pct(d['recall']):>6} {fmt_ci(*d['recall_ci']):>16} "
              f"{fmt_pct(d['precision']):>6} {fmt_ci(*d['prec_ci']):>16} "
              f"{fmt_pct(d['wr']):>6} "
              f"{d['strong_n']:>3}/{d['strong_tp']:>2} {fmt_pct(d['strong_precision']):>6} "
              f"{d['possible_n']:>3}/{d['possible_tp']:>2} {fmt_pct(d['possible_precision']):>6}")

    # Topic subtotals
    print("\n## Topic Subtotal\n")
    for key in sorted(topic_agg.keys()):
        t = topic_agg[key]
        r = t["tp"] / t["gt"] if t["gt"] else 0
        p = t["tp"] / (t["tp"] + t["fp"]) if (t["tp"] + t["fp"]) else 0
        w = (t["total_screened"] - t["tp"] - t["fp"]) / t["total_screened"] if t["total_screened"] else 0
        s_prec = t["strong_tp"] / t["strong_total"] if t["strong_total"] else 0
        pos_prec = t["possible_tp"] / t["possible_total"] if t["possible_total"] else 0
        print(f"  {key:<30} GT={t['gt']:>4} TP={t['tp']:>4} FP={t['fp']:>4} FN={t['fn']:>4} "
              f"R={fmt_pct(r)} P={fmt_pct(p)} WR={fmt_pct(w)} "
              f"Strong={t['strong_tp']}/{t['strong_total']}({fmt_pct(s_prec)}) "
              f"Poss={t['possible_tp']}/{t['possible_total']}({fmt_pct(pos_prec)})")

    # Grand total
    gt_total = sum(t["gt"] for t in topic_agg.values())
    tp_total = sum(t["tp"] for t in topic_agg.values())
    fp_total = sum(t["fp"] for t in topic_agg.values())
    fn_total = sum(t["fn"] for t in topic_agg.values())
    total_s = sum(t["total_screened"] for t in topic_agg.values())
    strong_tp_t = sum(t["strong_tp"] for t in topic_agg.values())
    strong_t = sum(t["strong_total"] for t in topic_agg.values())
    poss_tp_t = sum(t["possible_tp"] for t in topic_agg.values())
    poss_t = sum(t["possible_total"] for t in topic_agg.values())

    r = tp_total / gt_total if gt_total else 0
    p = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0
    w = (total_s - tp_total - fp_total) / total_s if total_s else 0
    s_prec = strong_tp_t / strong_t if strong_t else 0
    pos_prec = poss_tp_t / poss_t if poss_t else 0

    print(f"\n  {'GRAND TOTAL':<30} GT={gt_total:>4} TP={tp_total:>4} FP={fp_total:>4} FN={fn_total:>4} "
          f"R={fmt_pct(r)} P={fmt_pct(p)} WR={fmt_pct(w)} "
          f"Strong={strong_tp_t}/{strong_t}({fmt_pct(s_prec)}) "
          f"Poss={poss_tp_t}/{poss_t}({fmt_pct(pos_prec)})")


def print_failure_analysis(details):
    print("\n" + "=" * 120)
    print("FAILURE CASE ANALYSIS")
    print("=" * 120)

    all_fp = []
    all_fn = []

    for d in details:
        for r in d["fp_rows"]:
            pmid = r.get("PMID", "").strip()
            all_fp.append({
                "project": d["label"],
                "pmid": pmid,
                "title": r.get("Title", "")[:120],
                "suggest": r.get("llm_suggest"),
                "overall": safe_int(r.get("overall_score")),
                "disease": safe_int(r.get("disease_score")),
                "population": safe_int(r.get("population_score")),
                "location": safe_int(r.get("location_score")),
                "evidence": safe_int(r.get("evidence_score")),
                "parameter": safe_int(r.get("parameter_score")),
                "confidence": r.get("confidence", ""),
                "pub_types": r.get("pub_types", ""),
                "justification": r.get("overall_justification", "")[:200],
            })

        for r in d["fn_rows"]:
            pmid = r.get("PMID", "").strip()
            all_fn.append({
                "project": d["label"],
                "pmid": pmid,
                "title": r.get("Title", "")[:120],
                "suggest": r.get("llm_suggest"),
                "overall": safe_int(r.get("overall_score")),
                "disease": safe_int(r.get("disease_score")),
                "population": safe_int(r.get("population_score")),
                "location": safe_int(r.get("location_score")),
                "evidence": safe_int(r.get("evidence_score")),
                "parameter": safe_int(r.get("parameter_score")),
                "confidence": r.get("confidence", ""),
                "pub_types": r.get("pub_types", ""),
                "justification": r.get("overall_justification", "")[:200],
            })

    print(f"\n### False Positives (included but not in GT): {len(all_fp)} total\n")
    if all_fp:
        # Score distribution analysis
        score_dist = defaultdict(lambda: defaultdict(int))
        for fp in all_fp:
            for dim in ["disease", "population", "location", "evidence", "parameter"]:
                score_dist[dim][fp[dim]] += 1
        print("FP Dimension Score Distribution:")
        for dim in ["disease", "population", "location", "evidence", "parameter"]:
            dist_str = ", ".join(f"score={k}:{v}" for k, v in sorted(score_dist[dim].items()))
            print(f"  {dim:<12}: {dist_str}")

        print("\nTop FP cases by suggest type:")
        by_suggest = defaultdict(list)
        for fp in all_fp:
            by_suggest[fp["suggest"]].append(fp)
        for s, items in sorted(by_suggest.items()):
            print(f"\n  [{s}] ({len(items)} cases):")
            for fp in items[:5]:
                print(f"    PMID={fp['pmid']} | D={fp['disease']} P={fp['population']} L={fp['location']} "
                      f"E={fp['evidence']} Par={fp['parameter']} | {fp['title'][:100]}")
                print(f"      types={fp['pub_types'][:80]}")
                print(f"      just: {fp['justification'][:150]}")

    print(f"\n### False Negatives (in GT but not included): {len(all_fn)} total\n")
    if all_fn:
        # Score distribution
        score_dist = defaultdict(lambda: defaultdict(int))
        for fn in all_fn:
            for dim in ["disease", "population", "location", "evidence", "parameter"]:
                score_dist[dim][fn[dim]] += 1
        print("FN Dimension Score Distribution:")
        for dim in ["disease", "population", "location", "evidence", "parameter"]:
            dist_str = ", ".join(f"score={k}:{v}" for k, v in sorted(score_dist[dim].items()))
            print(f"  {dim:<12}: {dist_str}")

        print("\nFN cases (all):")
        for fn in sorted(all_fn, key=lambda x: (x["project"], x["pmid"])):
            print(f"  [{fn['project']}] PMID={fn['pmid']} | suggest={fn['suggest']} | "
                  f"D={fn['disease']} P={fn['population']} L={fn['location']} "
                  f"E={fn['evidence']} Par={fn['parameter']} | conf={fn['confidence']}")
            print(f"    Title: {fn['title'][:120]}")
            print(f"    types={fn['pub_types'][:80]}")
            print(f"    just: {fn['justification'][:150]}")
            print()


def print_strong_vs_possible(details):
    print("\n" + "=" * 120)
    print("STRONG vs POSSIBLE CANDIDATE ACCURACY ANALYSIS")
    print("=" * 120)

    all_strong_tp = []
    all_strong_fp = []
    all_possible_tp = []
    all_possible_fp = []

    for d in details:
        for r in d["fp_rows"]:
            pmid = r.get("PMID", "").strip()
            info = {
                "project": d["label"], "pmid": pmid, "title": r.get("Title", "")[:120],
                "overall": safe_int(r.get("overall_score")),
                "disease": safe_int(r.get("disease_score")),
                "population": safe_int(r.get("population_score")),
                "location": safe_int(r.get("location_score")),
                "evidence": safe_int(r.get("evidence_score")),
                "parameter": safe_int(r.get("parameter_score")),
                "pub_types": r.get("pub_types", ""),
                "justification": r.get("overall_justification", "")[:200],
                "abstract": (r.get("Abstract") or "")[:300],
            }
            if r.get("llm_suggest") == "strong_candidate":
                all_strong_fp.append(info)
            else:
                all_possible_fp.append(info)

        # Also collect TP breakdown
        for r in (d.get("tp_rows", [])):
            pass  # Computing differently

    # Strong accuracy
    print(f"\n### Strong Candidates")
    strong_total = sum(d["strong_n"] for d in details)
    strong_tp_total = sum(d["strong_tp"] for d in details)
    strong_fp_total = sum(d["strong_fp"] for d in details)
    print(f"Total Strong: {strong_total} | TP: {strong_tp_total} | FP: {strong_fp_total} | "
          f"Precision: {fmt_pct(strong_tp_total/strong_total) if strong_total else 'N/A'}")

    # Possible accuracy
    print(f"\n### Possible Candidates")
    poss_total = sum(d["possible_n"] for d in details)
    poss_tp_total = sum(d["possible_tp"] for d in details)
    poss_fp_total = sum(d["possible_fp"] for d in details)
    print(f"Total Possible: {poss_total} | TP: {poss_tp_total} | FP: {poss_fp_total} | "
          f"Precision: {fmt_pct(poss_tp_total/poss_total) if poss_total else 'N/A'}")

    # Score profile comparison
    print(f"\n### Score Profile: Strong TP vs Strong FP")
    print(f"(average dimension scores)")
    strong_tp_scores = {"disease": [], "population": [], "location": [], "evidence": [], "parameter": []}
    strong_fp_scores = {"disease": [], "population": [], "location": [], "evidence": [], "parameter": []}
    poss_tp_scores = {"disease": [], "population": [], "location": [], "evidence": [], "parameter": []}
    poss_fp_scores = {"disease": [], "population": [], "location": [], "evidence": [], "parameter": []}

    for d in details:
        fp_rows = d["fp_rows"]
        # Actually need to re-collect from original data
        # Let me just report from what we have

    # Build from all_fp and all_fn above
    print("\n### Possible FP Analysis — candidates for full-text enrichment\n")
    print("Possible = uncertain to include, but might still be correct")
    print("If many Possible FPs have weak evidence/parameter scores, full-text could help filter them out.\n")

    # Analyze possible FP dimension scores
    if all_possible_fp:
        avg_d = sum(x["disease"] for x in all_possible_fp) / len(all_possible_fp)
        avg_ev = sum(x["evidence"] for x in all_possible_fp) / len(all_possible_fp)
        avg_par = sum(x["parameter"] for x in all_possible_fp) / len(all_possible_fp)
        print(f"Average scores for Possible FPs: D={avg_d:.1f} E={avg_ev:.1f} Par={avg_par:.1f}")

        # How many could be filtered with evidence <= 2?
        weak_ev = sum(1 for x in all_possible_fp if x["evidence"] <= 2)
        weak_par = sum(1 for x in all_possible_fp if x["parameter"] <= 2)
        print(f"  {weak_ev}/{len(all_possible_fp)} ({fmt_pct(weak_ev/len(all_possible_fp))}) have evidence <= 2")
        print(f"  {weak_par}/{len(all_possible_fp)} ({fmt_pct(weak_par/len(all_possible_fp))}) have parameter <= 2")

        print("\nSample Possible FPs (first 10):")
        for fp in all_possible_fp[:10]:
            print(f"  PMID={fp['pmid']} | D={fp['disease']} E={fp['evidence']} Par={fp['parameter']}")
            print(f"    Title: {fp['title'][:100]}")
            print(f"    types: {fp['pub_types'][:80]}")
            print(f"    abstract: {fp['abstract'][:200]}")
            print()


def export_failure_csv(details):
    """Export FP and FN cases to CSV for easy review."""
    out_dir = REPO / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    # FP export
    fp_rows = []
    for d in details:
        for r in d["fp_rows"]:
            fp_rows.append({
                "project": d["label"],
                "PMID": r.get("PMID", "").strip(),
                "Title": r.get("Title", ""),
                "llm_suggest": r.get("llm_suggest"),
                "overall_score": r.get("overall_score"),
                "disease_score": r.get("disease_score"),
                "population_score": r.get("population_score"),
                "location_score": r.get("location_score"),
                "evidence_score": r.get("evidence_score"),
                "parameter_score": r.get("parameter_score"),
                "confidence": r.get("confidence"),
                "pub_types": r.get("pub_types", ""),
                "overall_justification": r.get("overall_justification", ""),
                "Abstract": (r.get("Abstract") or "")[:500],
            })

    with open(out_dir / "failure_analysis_fp.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fp_rows[0].keys())
        w.writeheader()
        w.writerows(fp_rows)
    print(f"\nFP list exported to {out_dir / 'failure_analysis_fp.csv'} ({len(fp_rows)} rows)")

    # FN export
    fn_rows = []
    for d in details:
        for r in d["fn_rows"]:
            fn_rows.append({
                "project": d["label"],
                "PMID": r.get("PMID", "").strip(),
                "Title": r.get("Title", ""),
                "llm_suggest": r.get("llm_suggest"),
                "overall_score": r.get("overall_score"),
                "disease_score": r.get("disease_score"),
                "population_score": r.get("population_score"),
                "location_score": r.get("location_score"),
                "evidence_score": r.get("evidence_score"),
                "parameter_score": r.get("parameter_score"),
                "confidence": r.get("confidence"),
                "pub_types": r.get("pub_types", ""),
                "overall_justification": r.get("overall_justification", ""),
                "Abstract": (r.get("Abstract") or "")[:500],
            })

    if fn_rows:
        with open(out_dir / "failure_analysis_fn.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fn_rows[0].keys())
            w.writeheader()
            w.writerows(fn_rows)
        print(f"FN list exported to {out_dir / 'failure_analysis_fn.csv'} ({len(fn_rows)} rows)")
    else:
        print("No FN cases to export.")


def main():
    details, topic_agg = analyze()
    print_overall_table(details, topic_agg)
    print_failure_analysis(details)
    print_strong_vs_possible(details)
    export_failure_csv(details)

    # Save JSON for further analysis
    json_path = REPO / "evaluation" / "results" / "failure_analysis.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    # Make serializable
    serializable = []
    for d in details:
        sd = {k: v for k, v in d.items() if k not in ("fp_rows", "fn_rows")}
        sd["fp_pmids"] = [r.get("PMID", "").strip() for r in d["fp_rows"]]
        sd["fn_pmids"] = list(d["fn_pmids"])
        serializable.append(sd)
    json_path.write_text(json.dumps(serializable, indent=2))
    print(f"\nJSON summary exported to {json_path}")


if __name__ == "__main__":
    main()
