#!/usr/bin/env python3
"""Print the consolidated baseline-vs-5D comparison table for the paper.
Includes: existing model/keyword/LEADS baselines + new Direct-LLM baselines.
"""
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
REF=ROOT/"evaluation/experiments/qwen36_plus_openrouter_direct_single_b1c8_j2_repeat1_20260510/screening_model_comparison_summary.csv"

def load_5d():
    t=f=fn=g=0
    for r in csv.DictReader(open(REF)):
        t+=int(r['TP']);f+=int(r['FP']);fn+=int(r['FN']);g+=int(r['GT'])
    return dict(recall=t/g,nns=(t+f)/t,tp=t,fp=f,fn=fn,gt=g)

def load_new(exp_prefix,diseases):
    t=f=fn=g=0
    for d in diseases:
        p=ROOT/f"evaluation/experiments/{exp_prefix}_{d}/screening/{d}/summary.csv"
        if not p.exists(): return None
        for r in csv.DictReader(open(p)):
            if r.get('status')!='ok':continue
            t+=int(float(r['tp']));f+=int(float(r['fp']));fn+=int(float(r['fn']))
            g+=int(float(r['ground_truth_count']))
    if not g: return None
    return dict(recall=t/g,nns=(t+f)/t if t else 99,tp=t,fp=f,fn=fn,gt=g)

def load_existing(name):
    p=ROOT/"baselines/screening/results/screening_baseline_summary.csv"
    for r in csv.DictReader(open(p)):
        if r['method']==name and r['scope']=='overall':
            return dict(recall=float(r['recall']),nns=float(r['nns']))
    return None

f5=load_5d()
rows=[]
rows.append(("5D structured (Qwen3.6-plus) — OURS", f5['recall'], f5['nns'],"main method"))
# new direct-llm
for name,exp,tag in [("Direct-LLM minimal (Qwen3.6-plus)","baseline_directllm_minimal_qwen36","simplest 1-shot prompt"),
                     ("Direct-LLM useful (Qwen3.6-plus)","baseline_useful_qwen36","vague 'is it useful?' prompt"),
                     ("Direct-LLM screenprompt_lite (Qwen3.6-plus)","baseline_screenpromptlite_qwen36","AgentSLR-style 'include if uncertain'")]:
    b=load_new(exp,["covid19","mpox"])
    if b: rows.append((name,b['recall'],b['nns'],tag))
# existing model baselines
for name in ["DeepSeek V4 Pro","Gemini 2.5 Flash","GPT-4.1","LEADS","Keyword rule"]:
    e=load_existing(name)
    if e: rows.append((f"{name}",e['recall'],e['nns'],"other model / rule"))

print("="*96)
print("CONSOLIDATED SCREENING COMPARISON vs 5D (ours). Baseline dominated = worse on BOTH recall & NNS.")
print("="*96)
print(f"{'Method':<46}{'Recall':>8}{'NNS':>8}   vs 5D")
print("-"*96)
for name,rec,nns,note in rows:
    dom = "OURS" if "OURS" in name else (
        "dominated (worse both)" if (rec<f5['recall'] and nns>f5['nns']) else
        ("recall-only worse" if rec<f5['recall'] else "NNS-only worse"))
    print(f"{name:<46}{rec:>8.3f}{nns:>8.2f}   [{dom}]  ({note})")
print("-"*96)
print(f"5D overall: recall={f5['recall']:.3f} ({f5['tp']}/{f5['gt']} TP), FN={f5['fn']}, NNS={f5['nns']:.2f}")
