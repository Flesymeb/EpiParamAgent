#!/usr/bin/env python3
"""Compare a Direct-LLM baseline run (per-profile summary.csv) against the canonical
5D Qwen3.6-plus run, overall and per-profile, on recall and NNS.

Usage:
  python tools/scripts/compare_baseline_vs_5d.py \
      --baseline evaluation/experiments/baseline_directllm_minimal_qwen36_covid19/screening/covid19/summary.csv \
                 evaluation/experiments/baseline_directllm_minimal_qwen36_mpox/screening/mpox/summary.csv \
      --label "Direct-LLM minimal (Qwen3.6-plus)"
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path

REF = Path("evaluation/experiments/qwen36_plus_openrouter_direct_single_b1c8_j2_repeat1_20260510/screening_model_comparison_summary.csv")

def read_5d(ref: Path):
    out = {}
    for r in csv.DictReader(open(ref)):
        key = (r["disease"], r["profile"])  # (covid19/mpox, P4)
        out[key] = dict(gt=int(r["GT"]), pool=int(r["Pool"]), tp=int(r["TP"]),
                        fp=int(r["FP"]), fn=int(r["FN"]),
                        recall=float(r["TP"])/int(r["GT"]),
                        nns=(int(r["TP"])+int(r["FP"]))/max(int(r["TP"]),1))
    return out

def read_baseline(paths):
    out = {}
    for p in paths:
        for r in csv.DictReader(open(p)):
            # eval-script summary uses 'profile','disease','topic','project'
            disease = r.get("disease","").strip().lower()
            prof = r.get("profile","").strip()
            key = (disease, prof.upper().replace("MP",""))  # normalize P/MP -> bare number? keep raw
            # keep both raw and normalized
            out[(disease, prof)] = r
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", nargs="+", required=True)
    ap.add_argument("--label", default="Baseline")
    ap.add_argument("--ref", default=str(REF))
    args = ap.parse_args()

    five_d = read_5d(Path(args.ref))
    # normalize 5D keys: disease lower; profile like 'P4'/'MP4'
    fd_norm = {}
    for (d, prof), v in five_d.items():
        fd_norm[(d.lower(), prof.upper())] = v

    base = read_baseline(args.baseline)

    # aggregate
    agg_5d = dict(gt=0, pool=0, tp=0, fp=0, fn=0)
    agg_b  = dict(gt=0, pool=0, tp=0, fp=0, fn=0)
    perprof = []
    for (d, prof), br in base.items():
        # match to 5D: eval summary disease is e.g. 'covid19'/'mpox', profile 'P4'/'MP4'
        key5 = None
        if (d, prof) in fd_norm: key5=(d,prof)
        elif prof.startswith("MP") and (d, "MP"+prof[2:]) in fd_norm: key5=(d,"MP"+prof[2:])
        else:
            for k in fd_norm:
                if k[0]==d and k[1].lstrip("M").rstrip("P0123456789")=="" :
                    pass
        v5 = fd_norm.get((d,prof))
        if v5 is None:
            # try matching by stripping
            for k in fd_norm:
                if k[0]==d and k[1].upper().replace("MP","")==prof.upper().replace("MP",""):
                    v5=fd_norm[k]; break
        if v5 is None:
            print(f"  [skip] no 5D match for {(d,prof)}")
            continue
        b=dict(gt=int(float(br["ground_truth_count"])), pool=int(float(br["screened_count"])) if br.get("screened_count") else 0,
               tp=int(float(br["tp"])), fp=int(float(br["fp"])), fn=int(float(br["fn"])))
        # pool not stored as pool in eval summary; recompute nns from tp+fp
        b_rec=b["tp"]/b["gt"] if b["gt"] else 0
        b_nns=(b["tp"]+b["fp"])/b["tp"] if b["tp"] else float("inf")
        perprof.append((d,prof,v5["recall"],v5["nns"],b_rec,b_nns))
        for K in agg_5d: agg_5d[K]+=v5[{ 'gt':'gt','pool':'pool','tp':'tp','fp':'fp','fn':'fn'}[K] if False else K]
        agg_b["gt"]+=b["gt"]; agg_b["tp"]+=b["tp"]; agg_b["fp"]+=b["fp"]; agg_b["fn"]+=b["fn"]

    r5=agg_5d["tp"]/agg_5d["gt"]; n5=(agg_5d["tp"]+agg_5d["fp"])/agg_5d["tp"]
    rb=agg_b["tp"]/agg_b["gt"]; nb=(agg_b["tp"]+agg_b["fp"])/agg_b["tp"] if agg_b["tp"] else float("inf")
    print(f"\n=== {args.label} vs 5D (Qwen3.6-plus) — {len(perprof)} profiles ===")
    print(f"{'metric':<10}{'5D':>12}{args.label:>28}")
    print(f"{'recall':<10}{r5:>12.4f}{rb:>28.4f}")
    print(f"{'NNS':<10}{n5:>12.4f}{nb:>28.4f}")
    worse_recall = sum(1 for p in perprof if p[4] < p[2])
    worse_nns    = sum(1 for p in perprof if p[5] > p[3])
    worse_both   = sum(1 for p in perprof if p[4] < p[2] and p[5] > p[3])
    print(f"\nper-profile: baseline worse on recall in {worse_recall}/{len(perprof)}; "
          f"worse on NNS in {worse_nns}/{len(perprof)}; worse on BOTH in {worse_both}/{len(perprof)}")
    print(f"\n{'disease':<10}{'prof':<8}{'5D_rec':>8}{'5D_nns':>9}{'b_rec':>8}{'b_nns':>8}{'Δrec':>8}{'Δnns':>8}")
    for d,p,r5p,n5p,rbp,nbp in perprof:
        print(f"{d:<10}{p:<8}{r5p:>8.3f}{n5p:>9.2f}{rbp:>8.3f}{nbp:>8.2f}{rbp-r5p:>8.3f}{nbp-n5p:>8.2f}")

if __name__ == "__main__":
    main()
