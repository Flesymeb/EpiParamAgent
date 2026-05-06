#!/usr/bin/env python3
"""Strategy comparison: keyword baseline vs binary (strict) vs 5D.
Run per-project, evaluate recall/precision/F1.
"""
from __future__ import annotations
import csv, re, json, subprocess, sys, time, os
from pathlib import Path

ROOT = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
EVAL_DIR = ROOT / "evaluation" / "covid19"

STRATEGIES = {
    "keyword": {
        "type": "rule",
        "rules": {
            "serial_interval": {
                "disease": [r'COVID', r'SARS.CoV.2', r'coronavirus', r'2019.nCoV'],
                "parameter": [r'serial.interval', r'incubation.period', r'generation.time', r'transmission.pair', r'symptom.onset.interval', r'serial.interval.estimate'],
            },
            "reproduction_number": {
                "disease": [r'COVID', r'SARS.CoV.2', r'coronavirus', r'2019.nCoV'],
                "parameter": [r'R0', r'R.t', r'reproduction.number', r'reproductive.number', r'basic.reproduction', r'effective.reproduction'],
            },
            "fatality": {
                "disease": [r'COVID', r'SARS.CoV.2', r'coronavirus', r'2019.nCoV'],
                "parameter": [r'CFR', r'IFR', r'case.fatality', r'infection.fatality', r'mortality.rate', r'death.rate', r'fatality.rate'],
            },
        },
    },
    "binary_strict": {
        "type": "llm",
        "command": "screening run --strategy binary --experiment strategy_binary_strict",
    },
    "5d": {
        "type": "llm_existing",
        "experiment_dir": "strategy_5d",
    },
}

PROJECTS = [
    ("p10", "serial_interval", "P10"), ("p11", "serial_interval", "P11"),
    ("p12", "serial_interval", "P12"), ("p13", "serial_interval", "P13"),
    ("p14", "serial_interval", "P14"),
    ("p4", "fatality", "P4"), ("p5", "fatality", "P5"),
    ("p6", "fatality", "P6"),
    ("p7", "reproduction_number", "P7"), ("p8", "reproduction_number", "P8"),
    ("p15", "reproduction_number", "P15"), ("p16", "reproduction_number", "P16"),
    ("p17", "reproduction_number", "P17"),
]


def evaluate_keyword(proj, topic):
    """Run keyword screening and evaluate."""
    rules = STRATEGIES["keyword"]["rules"][topic]

    raw_file = EVAL_DIR / topic / "ground_truth" / proj / f"project_{proj[1:]}_raw.csv"
    if not raw_file.exists():
        return None

    with open(raw_file) as f:
        rows = list(csv.DictReader(f))
    pmid_col = [c for c in rows[0].keys() if 'PMID' in c.replace('﻿','')][0]

    gt_file = EVAL_DIR / topic / "ground_truth" / proj / f"project_{proj[1:]}_groundtruth.csv"
    with open(gt_file) as f:
        gt_pmids = {r["gt_pmid"].strip() for r in csv.DictReader(f)}

    included = set()
    for row in rows:
        # Title-only keyword matching (simulates rapid title screening)
        text = (row.get("Title") or "").lower()
        if any(re.search(p, text) for p in rules["disease"]) and any(re.search(p, text) for p in rules["parameter"]):
            included.add(row[pmid_col].strip())

    tp = len(gt_pmids & included)
    fn = len(gt_pmids - included)
    fp = len(included - gt_pmids)
    recall = tp / (tp + fn) if (tp + fn) else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) else 0

    return {"proj": proj, "strategy": "keyword", "included": len(included),
            "total": len(rows), "tp": tp, "fn": fn, "fp": fp,
            "recall": recall, "precision": precision, "f1": f1}


def evaluate_screened_csv(proj, topic, csv_path, strategy_name):
    """Evaluate an existing screened CSV."""
    if not csv_path or not Path(csv_path).exists():
        return None

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    pmid_col = [c for c in rows[0].keys() if 'PMID' in c.replace('﻿','')][0]

    # Find decision column
    decision_cols = [c for c in rows[0].keys() if 'decision' in c.lower() or 'suggest' in c.lower()]
    if not decision_cols:
        # Try 5D-style columns
        for col in rows[0].keys():
            vals = [str(r[col]).strip().lower() for r in rows[:5]]
            if all(v in ('strong_candidate', 'unlikely_candidate', 'include', 'exclude', 'strong', 'possible', '') for v in vals if v):
                decision_cols = [col]
                break

    if not decision_cols:
        # Try score-based
        score_cols = [c for c in rows[0].keys() if 'overall_score' in c.lower().replace(' ','_').replace('-','_')]
        if score_cols:
            col = score_cols[0]
            included = set()
            for r in rows:
                try:
                    if float(r.get(col, 0) or 0) >= 3:
                        included.add(r[pmid_col].strip())
                except: pass
            if included:
                # Compute metrics
                gt_file = EVAL_DIR / topic / "ground_truth" / proj / f"project_{proj[1:]}_groundtruth.csv"
                with open(gt_file) as f: gt_pmids = {r["gt_pmid"].strip() for r in csv.DictReader(f)}
                tp = len(gt_pmids & included); fn = len(gt_pmids - included); fp = len(included - gt_pmids)
                recall = tp/(tp+fn) if (tp+fn) else 0; precision = tp/(tp+fp) if (tp+fp) else 0
                f1 = 2*recall*precision/(recall+precision) if (recall+precision) else 0
                return {"proj": proj, "strategy": strategy_name, "included": len(included),
                        "total": len(rows), "tp": tp, "fn": fn, "fp": fp,
                        "recall": recall, "precision": precision, "f1": f1}
            return None
        print(f"    cols={list(rows[0].keys())[:10]}")
        return None

    col = decision_cols[0]
    included = set()
    for r in rows:
        v = str(r.get(col, "")).strip().lower()
        if v in ("include", "strong_candidate", "strong", "possible", "yes", "1", "true"):
            included.add(r[pmid_col].strip())

    if not included:
        return None

    gt_file = EVAL_DIR / topic / "ground_truth" / proj / f"project_{proj[1:]}_groundtruth.csv"
    with open(gt_file) as f:
        gt_pmids = {r["gt_pmid"].strip() for r in csv.DictReader(f)}

    tp = len(gt_pmids & included)
    fn = len(gt_pmids - included)
    fp = len(included - gt_pmids)
    recall = tp / (tp + fn) if (tp + fn) else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) else 0

    return {"proj": proj, "strategy": strategy_name, "included": len(included),
            "total": len(rows), "tp": tp, "fn": fn, "fp": fp,
            "recall": recall, "precision": precision, "f1": f1}


def find_latest_screened(proj, topic, experiment_name):
    """Find latest screened CSV for a given experiment name (supports wildcards)."""
    exp_dir = EVAL_DIR / topic / "ground_truth" / proj / "experiments"

    # If exact match
    exact = exp_dir / experiment_name
    if exact.exists():
        csvs = sorted(exact.rglob(f"project_{proj[1:]}_screened*.csv"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
        if csvs:
            return csvs[0]

    # Try glob pattern
    if '*' in experiment_name or '?' in experiment_name:
        for d in sorted(exp_dir.glob(experiment_name), reverse=True):
            if d.is_dir():
                csvs = sorted(d.rglob(f"project_{proj[1:]}_screened*.csv"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
                if csvs:
                    return csvs[0]

    return None


def run_llm_screening(proj, topic, profile, strategy, experiment):
    """Spawn LLM screening as background process, return immediately."""
    cmd = [
        str(ROOT / ".venv/bin/metaagent"),
        "screening", "run",
        "-p", profile,
        "--strategy", strategy,
        "--experiment", experiment,
        "--batch-size", "20",
        "--batch-concurrency", "3",
    ]
    env = {**__import__('os').environ, "LANGCHAIN_OPENAI_TCP_KEEPALIVE": "0"}
    log_file = ROOT / "evaluation" / f"screening_{proj}_{experiment}.log"
    print(f"  Spawning: {' '.join(cmd)} > {log_file}")
    # Check if already running
    import subprocess as sp
    pid_file = ROOT / "evaluation" / f"screening_{proj}_{experiment}.pid"
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)  # Check if alive
            print(f"  Already running (PID {old_pid})")
            return True
        except (OSError, ValueError):
            pid_file.unlink()

    proc = sp.Popen(cmd, cwd=str(ROOT), env=env, stdout=open(log_file, 'w'), stderr=subprocess.STDOUT)
    pid_file.write_text(str(proc.pid))
    print(f"  Spawned PID {proc.pid}")
    return True


def main():
    results = []

    for proj, topic, profile in PROJECTS:
        print(f"\n{'='*60}")
        print(f"Processing {proj} ({topic})")
        print(f"{'='*60}")

        # 1. Keyword baseline
        kw = evaluate_keyword(proj, topic)
        if kw:
            results.append(kw)
            print(f"  keyword: Recall={kw['recall']:.0%} Prec={kw['precision']:.0%} F1={kw['f1']:.2f} "
                  f"incl={kw['included']}/{kw['total']} TP={kw['tp']} FN={kw['fn']}")

        # 2. Binary strict - run LLM if needed
        csv_path = find_latest_screened(proj, topic, "strategy_binary_strict")
        if csv_path:
            bin_result = evaluate_screened_csv(proj, topic, csv_path, "binary_strict")
        else:
            ok = run_llm_screening(proj, topic, profile, "binary", "strategy_binary_strict")
            if ok:
                time.sleep(2)
                csv_path = find_latest_screened(proj, topic, "strategy_binary_strict")
            bin_result = evaluate_screened_csv(proj, topic, csv_path, "binary_strict") if csv_path else None

        if bin_result:
            results.append(bin_result)
            print(f"  binary_strict: Recall={bin_result['recall']:.0%} Prec={bin_result['precision']:.0%} "
                  f"F1={bin_result['f1']:.2f} incl={bin_result['included']}/{bin_result['total']} TP={bin_result['tp']} FN={bin_result['fn']}")
        else:
            print(f"  binary_strict: FAILED")

        # 3. 5D - prefer gpt-4.1 (deepseek-level), fall back to others
        csv_5d = None
        exp_dir = EVAL_DIR / topic / "ground_truth" / proj / "experiments"
        for pattern in ["*gpt*5d*", "*gemini*5d*", "*5d*"]:
            for d in sorted(exp_dir.glob(pattern), reverse=True):
                if d.is_dir():
                    csvs = sorted(d.rglob(f"project_{proj[1:]}_screened*.csv"),
                                 key=lambda p: p.stat().st_mtime, reverse=True)
                    if csvs:
                        csv_5d = csvs[0]
                        print(f"  5d: using {d.name}/{csvs[0].name}")
                        break
            if csv_5d:
                break
        if csv_5d:
            d5_result = evaluate_screened_csv(proj, topic, csv_5d, "5d")
            if d5_result:
                results.append(d5_result)
                print(f"  5d: Recall={d5_result['recall']:.0%} Prec={d5_result['precision']:.0%} "
                      f"F1={d5_result['f1']:.2f} incl={d5_result['included']}/{d5_result['total']} TP={d5_result['tp']} FN={d5_result['fn']}")
        else:
            print(f"  5d: NO EXISTING DATA (need to run)")

    # Summary
    print(f"\n{'='*70}")
    print(f"{'Strategy':<15} {'Project':<8} {'Recall':>7} {'Precision':>9} {'F1':>7} {'TP/FN':>10} {'Incl':>6}")
    print(f"{'-'*70}")
    for r in sorted(results, key=lambda x: (x['proj'], x['strategy'])):
        print(f"{r['strategy']:<15} {r['proj']:<8} {r['recall']:>6.0%} {r['precision']:>8.0%} {r['f1']:>6.2f} "
              f"{r['tp']:>3}/{r['fn']:<3} {r['included']:>5}/{r['total']}")

    # Save
    out = ROOT / "evaluation" / "strategy_comparison.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
