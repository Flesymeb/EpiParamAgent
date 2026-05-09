#!/usr/bin/env python3
"""Root cause classification for TP/FP/FN/TN in 5D screening.

Classifies each paper into failure/success modes to answer:
- WHY are FPs included?
- WHY are FNs missed?
- WHAT distinguishes TP from FP?
"""

import csv, json
from collections import defaultdict, Counter
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
DATASET = REPO / "dataset"
EVAL = REPO / "evaluation" / "screening"

TOPICS_COVID = {
    "fatality": [4, 5, 6],
    "reproduction_number": [7, 8, 15, 16, 17],
    "serial_interval": [10, 11, 12, 13, 14],
}
TOPICS_MPOX = {
    "fatality": [4, 7, 8, 12],
    "serial_interval": [5, 6, 10, 11],
    "reproduction_number": [9],
}


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


def safe_int(v):
    try: return int(float(v))
    except: return -1


def classify_fp(paper, topic):
    """Classify WHY this paper is a false positive."""
    reasons = []
    pts = (paper.get("pub_types") or "").lower()
    p = safe_int(paper.get("parameter_score"))
    e = safe_int(paper.get("evidence_score"))
    d = safe_int(paper.get("disease_score"))

    # 1. Non-original publication type
    non_orig = {"editorial", "letter", "comment", "news", "video-audio media",
                "review", "systematic review", "meta-analysis", "retracted publication"}
    matched = [t for t in non_orig if t in pts]
    if matched:
        reasons.append(f"non_original_pubtype:{matched[0]}")

    # 2. Parameter mismatch: paper reports a different parameter
    if p >= 3 and e >= 3 and d >= 4:
        # Looks like a real paper but for wrong topic — check justification
        just = (paper.get("parameter_justification") or "").lower()
        if topic == "serial_interval" and any(kw in just for kw in ["r0", "reproduction", "attack rate"]):
            reasons.append("parameter_mismatch:reports_R0_not_SI")
        elif topic == "reproduction_number" and any(kw in just for kw in ["serial interval", "incubation", "generation time"]):
            reasons.append("parameter_mismatch:reports_SI_not_R0")
        elif topic == "fatality" and any(kw in just for kw in ["transmission", "serial interval", "r0", "reproduction"]):
            reasons.append("parameter_mismatch:reports_transmission_not_fatality")

    # 3. Evidence overestimation: model gives E>=3 to non-original research
    if e >= 3 and not reasons:
        # Check if abstract mentions "data" or "patients" vs just discussion
        abstract = (paper.get("Abstract") or "").lower()
        if len(abstract) < 100:
            reasons.append("evidence_overestimate:short_or_no_abstract")
        elif not any(kw in abstract for kw in ["patient", "case", "data", "we observed", "we measured",
                                                  "we collected", "surveillance", "cohort"]):
            reasons.append("evidence_overestimate:no_primary_data_language")

    # 4. Weak evidence but still included (possible candidate with E<=2)
    if e <= 2 and "possible_candidate" in paper.get("llm_suggest", ""):
        reasons.append("weak_evidence_still_possible")

    # 5. Generic COVID mention, not specific to parameter
    if not reasons:
        reasons.append("overly_generous_scoring")

    return reasons


def classify_fn(paper, topic):
    """Classify WHY this GT paper was missed."""
    reasons = []
    p = safe_int(paper.get("parameter_score"))
    e = safe_int(paper.get("evidence_score"))
    d = safe_int(paper.get("disease_score"))
    pts = (paper.get("pub_types") or "").lower()

    # 1. Review / non-original — correctly excluded, GT error
    if "review" in pts or "meta-analysis" in pts:
        reasons.append("gt_error:review_in_gt")
        return reasons

    # 2. Low evidence — modeling or aggregate data
    if e <= 1:
        reasons.append("low_evidence:modeling_or_review")
        if p >= 3:
            reasons.append("parameter_ok_but_evidence_failed")

    # 3. Parameter mismatch: model says paper doesn't report target
    if p <= 1:
        reasons.append("parameter_not_detected")
        if topic == "reproduction_number":
            reasons.append("likely_R0_paper_misclassified_as_non_R0")
        elif topic == "serial_interval":
            reasons.append("likely_SI_paper_misclassified_as_non_SI")

    # 4. Disease score too low
    if d <= 1:
        reasons.append("disease_score_too_low")

    # 5. Evidence OK but parameter flagged — paper really doesn't report it
    if e >= 3 and p <= 2:
        just = (paper.get("parameter_justification") or "").lower()
        reasons.append(f"correctly_excluded:wrong_parameter_for_topic:{topic}")

    # 6. All scores OK but still excluded — likely edge case
    if not reasons:
        if e >= 3 and p >= 3 and d >= 3:
            reasons.append("all_scores_good_but_excluded:threshold_boundary")
        else:
            reasons.append("mixed_weak_signals")

    return reasons


def classify_tp(paper, topic):
    """Classify WHY this paper was correctly included."""
    p = safe_int(paper.get("parameter_score"))
    e = safe_int(paper.get("evidence_score"))
    d = safe_int(paper.get("disease_score"))
    sugg = paper.get("llm_suggest", "")

    if p >= 4 and e >= 4:
        return ["strong_match:clear_parameter_and_evidence"]
    elif p >= 4 and e >= 3:
        return ["good_match:parameter_clear_evidence_adequate"]
    elif e >= 3 and p >= 3:
        return ["moderate_match:both_adequate"]
    elif sugg == "strong_candidate":
        return ["threshold_pass:in_strong_bucket"]
    else:
        return ["possible_bucket:lucky"]


def classify_tn(paper, topic):
    """Classify WHY this paper was correctly excluded."""
    p = safe_int(paper.get("parameter_score"))
    e = safe_int(paper.get("evidence_score"))
    d = safe_int(paper.get("disease_score"))

    reasons = []
    if p <= 1:
        reasons.append("parameter_absent_or_weak")
    if e <= 1:
        reasons.append("no_original_evidence")
    if d <= 2:
        reasons.append("disease_mismatch")
    if not reasons:
        if p <= 2:
            reasons.append("parameter_weak")
        if e <= 2:
            reasons.append("evidence_weak")
    if not reasons:
        reasons.append("below_threshold:mixed_moderate_scores")
    return reasons


def main():
    all_papers = []

    for disease, topics_dict, covid_exp, mpox_exp in [
        ("COVID", TOPICS_COVID,
         "cmp_covid13_deepseek_deepseek-v4-flash_5d_nofulltext_c16",
         None),
        ("MPOX", TOPICS_MPOX, None, "5d_dsv4pro_v5"),
    ]:
        exp_dir = covid_exp or mpox_exp
        data_dir = DATASET / ("covid19" if disease == "COVID" else "mpox") / "screening"
        eval_dir = EVAL / ("covid19" if disease == "COVID" else "mpox")

        for topic, pnums in topics_dict.items():
            for pnum in pnums:
                gt_f = data_dir / topic / f"p{pnum}" / "ground_truth.csv"
                scr_f = eval_dir / topic / f"p{pnum}" / "experiments" / exp_dir / f"project_{pnum}_screened.csv"
                if not scr_f.exists() or not gt_f.exists():
                    continue
                gt = load_gt(gt_f)
                with open(scr_f, encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        if row.get("llm_suggest") == "error":
                            continue
                        pmid = row["PMID"].strip()
                        is_gt = pmid in gt
                        sugg = row["llm_suggest"]
                        is_inc = sugg in ("strong_candidate", "possible_candidate")

                        # Determine category
                        if is_inc and is_gt:
                            cat = "TP"
                            root_cause = classify_tp(row, topic)
                        elif is_inc and not is_gt:
                            cat = "FP"
                            root_cause = classify_fp(row, topic)
                        elif not is_inc and is_gt:
                            cat = "FN"
                            root_cause = classify_fn(row, topic)
                        else:
                            cat = "TN"
                            root_cause = classify_tn(row, topic)

                        all_papers.append({
                            "disease": disease, "topic": topic, "project": pnum,
                            "pmid": pmid, "category": cat,
                            "suggest": sugg, "is_gt": is_gt,
                            "D": safe_int(row.get("disease_score")),
                            "P": safe_int(row.get("population_score")),
                            "L": safe_int(row.get("location_score")),
                            "E": safe_int(row.get("evidence_score")),
                            "Par": safe_int(row.get("parameter_score")),
                            "root_cause": root_cause,
                            "pub_types": row.get("pub_types", ""),
                            "title": (row.get("Title") or "")[:120],
                            "justification": (row.get("overall_justification") or "")[:200],
                        })

    # === FP Root Cause Analysis ===
    print("=" * 100)
    print("FALSE POSITIVE ROOT CAUSE ANALYSIS")
    print("=" * 100)

    fp_papers = [p for p in all_papers if p["category"] == "FP"]
    fp_causes = Counter()
    fp_cause_examples = defaultdict(list)
    for p in fp_papers:
        for cause in p["root_cause"]:
            fp_causes[cause] += 1
            if len(fp_cause_examples[cause]) < 3:
                fp_cause_examples[cause].append(p)

    print(f"\nTotal FPs: {len(fp_papers)}")
    print(f"\n{'Root Cause':<55} {'Count':>6} {'%':>6}")
    print("-" * 70)
    for cause, count in fp_causes.most_common():
        pct = count / len(fp_papers) * 100
        print(f"  {cause:<55} {count:>6} {pct:>5.1f}%")

    print(f"\n--- FP Examples ---")
    for cause in fp_causes.most_common(8):
        print(f"\n[{cause[0]}] (n={cause[1]}):")
        for ex in fp_cause_examples[cause[0]][:3]:
            print(f"  PMID={ex['pmid']} | D={ex['D']} E={ex['E']} Par={ex['Par']} | {ex['pub_types'][:60]}")
            print(f"    {ex['title'][:100]}")

    # === FN Root Cause Analysis ===
    print("\n" + "=" * 100)
    print("FALSE NEGATIVE ROOT CAUSE ANALYSIS")
    print("=" * 100)

    fn_papers = [p for p in all_papers if p["category"] == "FN"]
    fn_causes = Counter()
    fn_cause_examples = defaultdict(list)
    for p in fn_papers:
        for cause in p["root_cause"]:
            fn_causes[cause] += 1
            if len(fn_cause_examples[cause]) < 3:
                fn_cause_examples[cause].append(p)

    print(f"\nTotal FNs: {len(fn_papers)}")
    print(f"\n{'Root Cause':<55} {'Count':>6} {'%':>6}")
    print("-" * 70)
    for cause, count in fn_causes.most_common():
        pct = count / len(fn_papers) * 100
        print(f"  {cause:<55} {count:>6} {pct:>5.1f}%")

    print(f"\n--- FN Examples ---")
    for cause in fn_causes.most_common(8):
        print(f"\n[{cause[0]}] (n={cause[1]}):")
        for ex in fn_cause_examples[cause[0]][:3]:
            print(f"  PMID={ex['pmid']} | D={ex['D']} E={ex['E']} Par={ex['Par']} | sugg={ex['suggest']}")
            print(f"    {ex['title'][:100]}")
            print(f"    just: {ex['justification'][:150]}")

    # === TP Analysis ===
    print("\n" + "=" * 100)
    print("TRUE POSITIVE: HOW WERE THEY FOUND?")
    print("=" * 100)
    tp_papers = [p for p in all_papers if p["category"] == "TP"]
    tp_causes = Counter()
    for p in tp_papers:
        for cause in p["root_cause"]:
            tp_causes[cause] += 1
    print(f"\nTotal TPs: {len(tp_papers)}")
    for cause, count in tp_causes.most_common():
        pct = count / len(tp_papers) * 100
        print(f"  {cause:<55} {count:>6} {pct:>5.1f}%")
    # Dimension profile
    print(f"\n  Avg D={sum(p['D'] for p in tp_papers)/len(tp_papers):.1f} "
          f"P={sum(p['P'] for p in tp_papers)/len(tp_papers):.1f} "
          f"L={sum(p['L'] for p in tp_papers)/len(tp_papers):.1f} "
          f"E={sum(p['E'] for p in tp_papers)/len(tp_papers):.1f} "
          f"Par={sum(p['Par'] for p in tp_papers)/len(tp_papers):.1f}")

    # === TN Analysis ===
    print("\n" + "=" * 100)
    print("TRUE NEGATIVE: WHY WERE THEY CORRECTLY EXCLUDED?")
    print("=" * 100)
    tn_papers = [p for p in all_papers if p["category"] == "TN"]
    tn_causes = Counter()
    for p in tn_papers:
        for cause in p["root_cause"]:
            tn_causes[cause] += 1
    print(f"\nTotal TNs: {len(tn_papers)}")
    for cause, count in tn_causes.most_common():
        pct = count / len(tn_papers) * 100
        print(f"  {cause:<55} {count:>6} {pct:>5.1f}%")
    print(f"\n  Avg D={sum(p['D'] for p in tn_papers)/len(tn_papers):.1f} "
          f"P={sum(p['P'] for p in tn_papers)/len(tn_papers):.1f} "
          f"L={sum(p['L'] for p in tn_papers)/len(tn_papers):.1f} "
          f"E={sum(p['E'] for p in tn_papers)/len(tn_papers):.1f} "
          f"Par={sum(p['Par'] for p in tn_papers)/len(tn_papers):.1f}")

    # === Dimension discriminability ===
    print("\n" + "=" * 100)
    print("DIMENSION DISCRIMINABILITY: TP vs FP Score Distributions")
    print("=" * 100)
    for dim, label in [("D", "Disease"), ("E", "Evidence"), ("Par", "Parameter"), ("L", "Location"), ("P", "Population")]:
        tp_dist = Counter(p[dim] for p in tp_papers)
        fp_dist = Counter(p[dim] for p in fp_papers)
        print(f"\n  {label}:")
        print(f"    TP: " + " | ".join(f"score={k}:{v}" for k, v in sorted(tp_dist.items())))
        print(f"    FP: " + " | ".join(f"score={k}:{v}" for k, v in sorted(fp_dist.items())))
        # Separation metric: how different are the distributions?
        tp_vals = [p[dim] for p in tp_papers]
        fp_vals = [p[dim] for p in fp_papers]
        tp_avg = sum(tp_vals) / len(tp_vals)
        fp_avg = sum(fp_vals) / len(fp_vals)
        print(f"    Δ(TP-FP) = {tp_avg - fp_avg:+.2f}")

    # === Summary for PNAS ===
    print("\n" + "=" * 100)
    print("PNAS PAPER: KEY NUMBERS FOR RESULTS SECTION")
    print("=" * 100)
    print(f"""
    Total papers screened: {len(all_papers)}
    GT papers: {sum(1 for p in all_papers if p['is_gt'])}

    TP: {len(tp_papers)} — correctly included
    FP: {len(fp_papers)} — incorrectly included
    FN: {len(fn_papers)} — incorrectly excluded
    TN: {len(tn_papers)} — correctly excluded

    FP root causes (top 5):
    {chr(10).join(f'      {i+1}. {c[0]} ({c[1]}, {c[1]/len(fp_papers)*100:.0f}%)' for i, c in enumerate(fp_causes.most_common(5)))}

    FN root causes (top 5):
    {chr(10).join(f'      {i+1}. {c[0]} ({c[1]}, {c[1]/len(fn_papers)*100:.0f}%)' for i, c in enumerate(fn_causes.most_common(5)))}

    TP discovery mode:
    {chr(10).join(f'      {c[0]} ({c[1]}, {c[1]/len(tp_papers)*100:.0f}%)' for c in tp_causes.most_common(3))}

    TN exclusion mode:
    {chr(10).join(f'      {c[0]} ({c[1]}, {c[1]/len(tn_papers)*100:.0f}%)' for c in tn_causes.most_common(3))}
    """)

    # Export detailed data
    out_path = REPO / "evaluation" / "results" / "root_cause_analysis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    export = []
    for p in all_papers:
        export.append({k: str(v) if isinstance(v, list) else v for k, v in p.items()})
    out_path.write_text(json.dumps(export, indent=2))
    print(f"Detailed data exported to {out_path}")


if __name__ == "__main__":
    main()
