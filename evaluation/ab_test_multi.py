#!/usr/bin/env python3
"""Multi-project A/B test: code-threshold vs LLM self-tier (S/P/U)."""

import asyncio, csv, sys, time, math
from pathlib import Path
from collections import defaultdict

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
sys.path.insert(0, str(REPO))

from metaagent.screening.engine import init_llm_model, screen_papers_batch_async

# Projects: (disease, topic, pnum, research_question, disease_focus, parameter_focus)
PROJECTS = [
    ("covid19", "serial_interval", 14,
     "What is the serial interval of COVID-19?",
     "(COVID-19 OR 2019-nCoV OR coronavirus)",
     "(serial interval)"),
    ("covid19", "serial_interval", 12,
     "What is the serial interval and generation time of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus OR COVID19)",
     "(serial interval OR generation time OR incubation period OR latent period)"),
    ("covid19", "fatality", 4,
     "What are the fatality and severity outcomes of SARS-CoV-2 infection?",
     "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus OR coronavirus disease 2019)",
     "(mortality OR fatality OR case fatality rate OR case fatality ratio OR CFR OR infection fatality rate OR infection fatality ratio OR IFR OR death rate OR died OR ICU admission OR intensive care OR intensive care unit OR invasive mechanical ventilation OR mechanical ventilation OR ventilation OR clinical characteristic*)"),
    ("covid19", "reproduction_number", 17,
     "What is the basic reproduction number (R0) and effective reproduction number (Rt) of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
     "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number OR transmission rate OR epidemic growth rate OR doubling time)"),
]

BATCH_SIZE = 20
CONCURRENCY = 3
BATCH_MODE = "single"
MODEL_NAME = "deepseek/deepseek-v4-pro"
PROVIDER = "openrouter"
STRATEGY = "5d"
OUT_BASE = REPO / "evaluation" / "screening"


def load_papers(disease, topic, pnum):
    path = REPO / "dataset" / disease / "screening" / topic / f"p{pnum}" / "raw.csv"
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_gt(disease, topic, pnum):
    path = REPO / "dataset" / disease / "screening" / topic / f"p{pnum}" / "ground_truth.csv"
    pmids = set()
    if not path.exists():
        return pmids
    with open(path, encoding="utf-8-sig") as f:
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

    recall = tp / len(gt_pmids) if gt_pmids else 0
    prec = tp / len(inc) if inc else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) else 0
    wr = (len(valid) - len(inc)) / len(valid) if valid else 0

    strong_tp = sum(1 for p in strong if p["PMID"].strip() in gt_pmids)
    poss_tp = sum(1 for p in possible if p["PMID"].strip() in gt_pmids)

    return {
        "total": len(valid), "errors": len(papers) - len(valid),
        "gt": len(gt_pmids), "tp": tp, "fp": fp, "fn": fn,
        "included": len(inc), "excluded": len(unlikely),
        "S": len(strong), "S_tp": strong_tp,
        "P": len(possible), "P_tp": poss_tp,
        "U": len(unlikely),
        "recall": recall, "precision": prec, "f1": f1, "wr": wr,
    }


async def run_one(disease, topic, pnum, rq, disease_focus, param_focus, prefer_llm_tier):
    label = f"{disease}/{topic}/p{pnum}"
    papers = load_papers(disease, topic, pnum)
    gt = load_gt(disease, topic, pnum)
    print(f"\n  [{label}] {len(papers)} papers, {len(gt)} GT, tier={'LLM' if prefer_llm_tier else 'Code'}")

    llm = init_llm_model(model_override=MODEL_NAME, provider_override=PROVIDER)

    screening_config = {
        "research_question": rq,
        "disease_focus": disease_focus,
        "disease_exclude": "none",
        "parameter_focus": param_focus,
        "parameter_exclude": "studies that do not report the target parameter",
        "parameter_scoring_note": "Score based on whether the paper explicitly reports the target parameter.",
    }

    t0 = time.perf_counter()
    await screen_papers_batch_async(
        papers, research_question=rq, llm_model=llm,
        batch_size=BATCH_SIZE, batch_concurrency=CONCURRENCY,
        batch_mode=BATCH_MODE,
        screening_stage="title_abstract", content_label="Abstract",
        content_key="Abstract", content_fallback="(NO ABSTRACT AVAILABLE — cannot assess evidence or parameter from title alone. Score conservatively.)",
        strategy=STRATEGY, screening_config=screening_config,
        prefer_llm_tier=prefer_llm_tier,
    )
    elapsed = time.perf_counter() - t0

    metrics = compute_metrics(papers, gt)
    metrics["elapsed_s"] = elapsed
    metrics["label"] = label
    metrics["prefer_llm_tier"] = prefer_llm_tier

    # Save
    out_dir = OUT_BASE / disease / topic / f"p{pnum}" / "experiments" / "ab_tier_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "llm_tier" if prefer_llm_tier else "code_threshold"
    out_file = out_dir / f"project_{pnum}_screened_{suffix}.csv"
    fieldnames = list(papers[0].keys())
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(papers)

    return metrics


def fmt_pct(v): return f"{v*100:.1f}%"


async def main():
    all_results = []

    for disease, topic, pnum, rq, df, pf in PROJECTS:
        for prefer in [False, True]:
            metrics = await run_one(disease, topic, pnum, rq, df, pf, prefer)
            all_results.append(metrics)

    # Aggregate comparison
    print("\n" + "=" * 90)
    print("MULTI-PROJECT A/B COMPARISON: Code-threshold vs LLM self-tier (S/P/U)")
    print("=" * 90)

    # Per-project
    for disease, topic, pnum, _, _, _ in PROJECTS:
        code_m = next(m for m in all_results if m["label"] == f"{disease}/{topic}/p{pnum}" and not m["prefer_llm_tier"])
        llm_m = next(m for m in all_results if m["label"] == f"{disease}/{topic}/p{pnum}" and m["prefer_llm_tier"])
        print(f"\n[{code_m['label']}] GT={code_m['gt']}, pool={code_m['total']}")
        print(f"  {'':<12} {'Recall':>8} {'Prec':>8} {'F1':>8} {'Incl':>6} {'S':>5} {'P':>5} {'U':>5} {'Err':>5} {'Time':>6}")
        for name, m in [("Code-thr", code_m), ("LLM-tier", llm_m)]:
            print(f"  {name:<12} {fmt_pct(m['recall']):>8} {fmt_pct(m['precision']):>8} {m['f1']:>8.3f} "
                  f"{m['included']:>6} {m['S']:>5} {m['P']:>5} {m['U']:>5} {m['errors']:>5} {m['elapsed_s']:>6.0f}s")

    # Pooled
    print(f"\n--- Pooled ---")
    code_tp = sum(m["tp"] for m in all_results if not m["prefer_llm_tier"])
    code_inc = sum(m["included"] for m in all_results if not m["prefer_llm_tier"])
    code_gt = sum(m["gt"] for m in all_results if not m["prefer_llm_tier"])
    code_err = sum(m["errors"] for m in all_results if not m["prefer_llm_tier"])
    code_total = sum(m["total"] for m in all_results if not m["prefer_llm_tier"])
    llm_tp = sum(m["tp"] for m in all_results if m["prefer_llm_tier"])
    llm_inc = sum(m["included"] for m in all_results if m["prefer_llm_tier"])
    llm_err = sum(m["errors"] for m in all_results if m["prefer_llm_tier"])
    llm_total = sum(m["total"] for m in all_results if m["prefer_llm_tier"])

    cr, cp = code_tp / code_gt if code_gt else 0, code_tp / code_inc if code_inc else 0
    cf1 = 2 * cr * cp / (cr + cp) if (cr + cp) else 0
    lr, lp = llm_tp / code_gt if code_gt else 0, llm_tp / llm_inc if llm_inc else 0
    lf1 = 2 * lr * lp / (lr + lp) if (lr + lp) else 0

    # S/P distribution
    code_s = sum(m["S"] for m in all_results if not m["prefer_llm_tier"])
    code_p = sum(m["P"] for m in all_results if not m["prefer_llm_tier"])
    code_u = sum(m["U"] for m in all_results if not m["prefer_llm_tier"])
    llm_s = sum(m["S"] for m in all_results if m["prefer_llm_tier"])
    llm_p = sum(m["P"] for m in all_results if m["prefer_llm_tier"])
    llm_u = sum(m["U"] for m in all_results if m["prefer_llm_tier"])

    print(f"  {'':<12} {'Recall':>8} {'Prec':>8} {'F1':>8} {'Incl':>6} {'S':>5} {'P':>5} {'U':>5} {'Err':>5}")
    print(f"  {'Code-thr':<12} {fmt_pct(cr):>8} {fmt_pct(cp):>8} {cf1:>8.3f} "
          f"{code_inc:>6} {code_s:>5} {code_p:>5} {code_u:>5} {code_err:>5}")
    print(f"  {'LLM-tier':<12} {fmt_pct(lr):>8} {fmt_pct(lp):>8} {lf1:>8.3f} "
          f"{llm_inc:>6} {llm_s:>5} {llm_p:>5} {llm_u:>5} {llm_err:>5}")
    print(f"  {'Δ':<12} {fmt_pct(lr-cr):>8} {fmt_pct(lp-cp):>8} {lf1-cf1:>+8.3f} "
          f"{llm_inc-code_inc:>+6} {llm_s-code_s:>+5} {llm_p-code_p:>+5} {llm_u-code_u:>+5} {llm_err-code_err:>+5}")

    # Disagreement analysis
    print(f"\n--- Tier Disagreement Analysis ---")
    total_disagree = 0
    for disease, topic, pnum, _, _, _ in PROJECTS:
        out_dir = OUT_BASE / disease / topic / f"p{pnum}" / "experiments" / "ab_tier_test"
        code_f = out_dir / f"project_{pnum}_screened_code_threshold.csv"
        llm_f = out_dir / f"project_{pnum}_screened_llm_tier.csv"
        if not code_f.exists() or not llm_f.exists():
            continue
        code_rows = {r["PMID"]: r for r in csv.DictReader(open(code_f, encoding="utf-8-sig"))}
        llm_rows = {r["PMID"]: r for r in csv.DictReader(open(llm_f, encoding="utf-8-sig"))}
        gt = load_gt(disease, topic, pnum)

        disagree = []
        for pmid in code_rows:
            cs = code_rows[pmid]["llm_suggest"]
            ls = llm_rows[pmid]["llm_suggest"]
            if cs != ls:
                disagree.append((pmid, cs, ls, pmid in gt))

        total_disagree += len(disagree)
        total_papers = len(code_rows)

        # Summarize disagreement patterns
        from collections import Counter
        patterns = Counter()
        for _, cs, ls, is_gt in disagree:
            gt_flag = "[GT]" if is_gt else ""
            patterns[f"{cs}→{ls} {gt_flag}"] += 1

        if disagree:
            print(f"\n  [{disease}/{topic}/p{pnum}] {len(disagree)}/{total_papers} disagree:")
            for pat, cnt in patterns.most_common():
                print(f"    {pat}: {cnt}")

    print(f"\n  Total disagreements: {total_disagree}")

    # Recommendation
    print(f"\n--- Final Recommendation ---")
    if lf1 > cf1:
        print(f"✅ LLM-tier improves pooled F1 ({cf1:.3f}→{lf1:.3f}, Δ=+{lf1-cf1:.3f})")
        print(f"   Recommend: ENABLE by default for title/abstract screening")
    elif abs(lf1 - cf1) < 0.01:
        print(f"≈ LLM-tier F1 change is negligible ({cf1:.3f}→{lf1:.3f}, Δ={lf1-cf1:+.3f})")
        print(f"   Recommend: KEEP as experimental option, more data needed")
    else:
        print(f"❌ LLM-tier degrades pooled F1 ({cf1:.3f}→{lf1:.3f}, Δ={lf1-cf1:.3f})")
        print(f"   Recommend: KEEP as experimental option only")

    if code_err > 0 or llm_err > 0:
        print(f"\n⚠️  Code errors: {code_err}, LLM errors: {llm_err}")


if __name__ == "__main__":
    asyncio.run(main())
