#!/usr/bin/env python3
"""Aggregate all Direct-LLM baseline runs vs the canonical 5D Qwen3.6-plus run.

Reads per-profile summary.csv files written by tools/scripts/leads_mistral_screening_eval.py
and the canonical 5D comparison summary, then prints overall + per-disease + per-profile
recall/NNS with dominance flags.

Usage:
  python tools/scripts/aggregate_directllm_baselines.py
"""
from __future__ import annotations
import csv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

# canonical 5D Qwen3.6-plus per-profile reference
REF = ROOT / "evaluation/experiments/qwen36_plus_openrouter_direct_single_b1c8_j2_repeat1_20260510/screening_model_comparison_summary.csv"

BASELINES = {
    "Direct-LLM minimal (Qwen3.6-plus)": [
        ("covid19", ROOT/"evaluation/experiments/baseline_directllm_minimal_qwen36_covid19/screening/covid19/summary.csv"),
        ("mpox", ROOT/"evaluation/experiments/baseline_directllm_minimal_qwen36_mpox/screening/mpox/summary.csv"),
    ],
    "Direct-LLM minimal (DeepSeek V3)": [
        ("covid19", ROOT/"evaluation/experiments/baseline_directllm_minimal_dsv3_covid19/screening/covid19/summary.csv"),
        ("mpox", ROOT/"evaluation/experiments/baseline_directllm_minimal_dsv3_mpox/screening/mpox/summary.csv"),
    ],
    "Direct-LLM minimal (DeepSeek V3.2)": [
        ("covid19", ROOT/"evaluation/experiments/baseline_directllm_minimal_dsk32_covid19/screening/covid19/summary.csv"),
        ("mpox", ROOT/"evaluation/experiments/baseline_directllm_minimal_dsk32_mpox/screening/mpox/summary.csv"),
    ],
    "Direct-LLM minimal (DeepSeek V4 Pro)": [
        ("covid19", ROOT/"evaluation/experiments/baseline_directllm_minimal_dsv4pro_mt512_covid19/screening/covid19/summary.csv"),
        ("mpox", ROOT/"evaluation/experiments/baseline_directllm_minimal_dsv4pro_mt512_mpox/screening/mpox/summary.csv"),
    ],
    "Direct-LLM screenprompt_lite (Qwen3.6-plus)": [
        ("covid19", ROOT/"evaluation/experiments/baseline_screenpromptlite_qwen36_covid19/screening/covid19/summary.csv"),
        ("mpox", ROOT/"evaluation/experiments/baseline_screenpromptlite_qwen36_mpox/screening/mpox/summary.csv"),
    ],
}

def load_5d():
    out={}
    for r in csv.DictReader(open(REF)):
        gt=int(r['TP'])+int(r['FN'])
        out[(r['disease'].lower(), r['profile'].upper())]=dict(
            gt=gt,tp=int(r['TP']),fp=int(r['FP']),fn=int(r['FN']),
            recall=int(r['TP'])/gt, nns=(int(r['TP'])+int(r['FP']))/int(r['TP']) if int(r['TP']) else 99)
    return out

def load_baseline(files):
    # files: list of (disease, path)
    out={}
    for disease,p in files:
        if not p.exists(): continue
        for r in csv.DictReader(open(p)):
            if r.get('status')!='ok': continue
            prof=r.get('profile','').strip().upper()
            tp,fp,fn,tn=int(float(r['tp'])),int(float(r['fp'])),int(float(r['fn'])),int(float(r['tn']))
            gt=tp+fn
            out[(disease,prof)]=dict(gt=gt,tp=tp,fp=fp,fn=fn,recall=tp/gt if gt else 0,
                nns=(tp+fp)/tp if tp else 99)
    return out

def agg(rows):
    g=sum(r['gt'] for r in rows); t=sum(r['tp'] for r in rows); f=sum(r['fp'] for r in rows)
    return dict(recall=t/g if g else 0, nns=(t+f)/t if t else 99, tp=t, fp=f, gt=g)

def main():
    five=load_5d()
    # 5D overall + per-disease
    print("="*78)
    print("OVERALL (22 profiles)")
    print("="*78)
    f_all=agg(list(five.values()))
    f_cov=agg([v for k,v in five.items() if k[0]=='covid19'])
    f_mp=agg([v for k,v in five.items() if k[0]=='mpox'])
    hdr=f"{'method':<45}{'recall':>8}{'NNS':>8}  |  {'cov_rec':>8}{'cov_nns':>9}{'mp_rec':>8}{'mp_nns':>8}"
    print(hdr); print("-"*len(hdr))
    print(f"{'5D Qwen3.6-plus (ours)':<45}{f_all['recall']:>8.3f}{f_all['nns']:>8.2f}  |  {f_cov['recall']:>8.3f}{f_cov['nns']:>9.2f}{f_mp['recall']:>8.3f}{f_mp['nns']:>8.2f}")
    for name,paths in BASELINES.items():
        b=load_baseline(paths)
        if not b: print(f"{name:<45}  (no results)"); continue
        b_all=agg(list(b.values()))
        b_cov=agg([v for k,v in b.items() if k[0]=='covid19'])
        b_mp=agg([v for k,v in b.items() if k[0]=='mpox'])
        # dominance vs 5D overall
        dom = "DOMINATED (worse both)" if (b_all['recall']<f_all['recall'] and b_all['nns']>f_all['nns']) else \
              ("recall-dominated" if b_all['recall']<f_all['recall'] else "NNS-dominated" if b_all['nns']>f_all['nns'] else "??")
        print(f"{name:<45}{b_all['recall']:>8.3f}{b_all['nns']:>8.2f}  |  {b_cov['recall']:>8.3f}{b_cov['nns']:>9.2f}{b_mp['recall']:>8.3f}{b_mp['nns']:>8.2f}  [{dom}]")

    # per-profile minimal
    print("\n"+"="*78); print("PER-PROFILE: minimal vs 5D"); print("="*78)
    print(f"{'disease':<8}{'prof':<6}{'5D_rec':>8}{'5D_nns':>9}{'b_rec':>8}{'b_nns':>8}  flag")
    b=load_baseline(BASELINES["Direct-LLM minimal (Qwen3.6-plus)"])
    for k in sorted(b):
        if k not in five: continue
        v5=five[k]; vb=b[k]
        flag="WORSE-BOTH" if (vb['recall']<v5['recall'] and vb['nns']>v5['nns']) else \
             ("rec_only" if vb['recall']<v5['recall'] else ("nns_only" if vb['nns']>v5['nns'] else "BETTER/equal"))
        print(f"{k[0]:<8}{k[1]:<6}{v5['recall']:>8.3f}{v5['nns']:>9.2f}{vb['recall']:>8.3f}{vb['nns']:>8.2f}  [{flag}]")

if __name__=="__main__":
    main()
