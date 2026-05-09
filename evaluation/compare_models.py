#!/usr/bin/env python3
"""Cross-model comparison for COVID-19 5D screening experiments.

Compares: 5D (deepseek, qwen-35b, qwen-flash) vs binary (strict) vs LEADS-Mistral.
"""

import csv, json, math
from collections import defaultdict
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
DATASET = REPO / "dataset" / "covid19" / "screening"
EVAL = REPO / "evaluation" / "screening" / "covid19"

EXPERIMENTS = {
    "5D-DeepSeek-v4-flash": "cmp_covid13_deepseek_deepseek-v4-flash_5d_nofulltext_c16",
    "5D-Qwen3.6-35B": "cmp_covid13_qwen_qwen3.6-35b-a3b_5d_nofulltext_c16",
    "5D-Qwen3.6-flash": "cmp_covid13_qwen_qwen3.6-flash_5d_nofulltext_c16",
    "Binary-Strict": "strategy_binary_strict",
    "LEADS-Mistral-7B": "leads_mistral_strict_simple_20260506_185524",
}

TOPICS = {
    "fatality": [4, 5, 6],
    "reproduction_number": [7, 8, 15, 16, 17],
    "serial_interval": [10, 11, 12, 13, 14],
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
                    if excl in ("review_low_evidence", "review", "low_evidence"):
                        continue
                    pmids.add(val)
                    break
    return pmids


def wilson_ci(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def evaluate(scr_file, gt_pmids):
    if not scr_file.exists():
        return None
    rows = list(csv.DictReader(open(scr_file, encoding="utf-8-sig")))
    valid = [r for r in rows if r.get("llm_suggest") != "error"]
    inc = [r for r in valid if r["llm_suggest"] in ("strong_candidate", "possible_candidate")]
    strong = [r for r in inc if r["llm_suggest"] == "strong_candidate"]
    possible = [r for r in inc if r["llm_suggest"] == "possible_candidate"]
    unlikely = [r for r in valid if r["llm_suggest"] == "unlikely_candidate"]

    tp = [r for r in inc if r["PMID"].strip() in gt_pmids]
    fp = [r for r in inc if r["PMID"].strip() not in gt_pmids]
    fn = gt_pmids - {r["PMID"].strip() for r in inc}
    strong_tp = sum(1 for r in strong if r["PMID"].strip() in gt_pmids)
    possible_tp = sum(1 for r in possible if r["PMID"].strip() in gt_pmids)

    recall = len(tp) / len(gt_pmids) if gt_pmids else 0.0
    prec = len(tp) / len(inc) if inc else 0.0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) else 0.0
    wr = len(unlikely) / len(valid) if valid else 0.0

    return {
        "gt": len(gt_pmids), "total": len(valid), "errors": len(rows) - len(valid),
        "tp": len(tp), "fp": len(fp), "fn": len(fn),
        "strong_tp": strong_tp, "strong_n": len(strong),
        "possible_tp": possible_tp, "possible_n": len(possible),
        "recall": recall, "precision": prec, "f1": f1, "wr": wr,
        "recall_ci": wilson_ci(recall, len(gt_pmids)),
        "prec_ci": wilson_ci(prec, len(inc)),
    }


def main():
    results = defaultdict(lambda: defaultdict(dict))

    for exp_name, exp_dir in EXPERIMENTS.items():
        for topic, pnums in TOPICS.items():
            for pnum in pnums:
                gt_file = DATASET / topic / f"p{pnum}" / "ground_truth.csv"
                scr_file = EVAL / topic / f"p{pnum}" / "experiments" / exp_dir / f"project_{pnum}_screened.csv"
                gt = load_gt(gt_file)
                r = evaluate(scr_file, gt) if gt else None
                if r:
                    results[exp_name][topic][pnum] = r

    # Print comparison table
    print("=" * 140)
    print("CROSS-MODEL COMPARISON: COVID-19 5D SCREENING")
    print("=" * 140)

    for exp_name in EXPERIMENTS:
        print(f"\n### {exp_name}")
        print(f"{'Topic':<20} {'P':>4} {'GT':>4} {'TP':>4} {'FP':>5} {'FN':>4} {'R':>7} {'P':>7} {'F1':>7} {'WR':>7} {'Strong':>10} {'Poss':>10}")

        agg = {"gt": 0, "tp": 0, "fp": 0, "fn": 0, "total": 0, "strong_tp": 0, "strong_n": 0, "poss_tp": 0, "poss_n": 0}
        for topic in ["fatality", "reproduction_number", "serial_interval"]:
            for pnum in sorted(results[exp_name].get(topic, {})):
                r = results[exp_name][topic][pnum]
                for k in agg:
                    if k in r:
                        agg[k] += r[k]
                print(f"{topic:<20} {pnum:>4} {r['gt']:>4} {r['tp']:>4} {r['fp']:>5} {r['fn']:>4} "
                      f"{r['recall']:.3f} {r['precision']:.3f} {r['f1']:.3f} {r['wr']:.3f} "
                      f"{r['strong_tp']}/{r['strong_n']:<4} {r['possible_tp']}/{r['possible_n']:<4}")

        r_total = agg["tp"] / agg["gt"] if agg["gt"] else 0
        p_total = agg["tp"] / (agg["tp"] + agg["fp"]) if (agg["tp"] + agg["fp"]) else 0
        f1 = 2 * r_total * p_total / (r_total + p_total) if (r_total + p_total) else 0
        wr = (agg["total"] - agg["tp"] - agg["fp"]) / agg["total"] if agg["total"] else 0
        r_ci = wilson_ci(r_total, agg["gt"])
        p_ci = wilson_ci(p_total, agg["tp"] + agg["fp"])

        print(f"{'POOLED':<20} {'':>4} {agg['gt']:>4} {agg['tp']:>4} {agg['fp']:>5} {agg['fn']:>4} "
              f"{r_total:.3f} {p_total:.3f} {f1:.3f} {wr:.3f} "
              f"{agg['strong_tp']}/{agg['strong_n']:<4} {agg['poss_tp']}/{agg['poss_n']:<4}")
        print(f"  Recall {r_total*100:.1f}% [{r_ci[0]*100:.1f}–{r_ci[1]*100:.1f}%] "
              f"Precision {p_total*100:.1f}% [{p_ci[0]*100:.1f}–{p_ci[1]*100:.1f}%] "
              f"F1={f1:.3f} WR={wr*100:.1f}%")

    # Save JSON
    out_path = REPO / "evaluation" / "results" / "cross_model_comparison.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def convert(obj):
        if isinstance(obj, dict):
            return {str(k): convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [convert(x) for x in obj]
        if isinstance(obj, float):
            return round(obj, 6)
        return obj

    out_path.write_text(json.dumps(convert(dict(results)), indent=2))
    print(f"\nJSON saved to {out_path}")


if __name__ == "__main__":
    main()
