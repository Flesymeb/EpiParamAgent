#!/usr/bin/env python3
"""
Batch runner: --resume-sp-fulltext for all evaluation profiles (P4–P17, skip P9).

Runs each profile sequentially, captures stdout, parses the Second-stage summary
block, and writes a consolidated metrics TSV to:
  evaluation/screening/GT_1/sp_fulltext_results.tsv

Usage:
  python dev/literature_search/scripts/cli/run_sp_fulltext_all.py [--project-root .]
  python dev/literature_search/scripts/cli/run_sp_fulltext_all.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Force line-buffered stdout so progress is visible when not a TTY
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# ── 1. Profile list (P9 excluded) ─────────────────────────────────────────────
PROFILES = ["P4", "P5", "P6", "P7", "P8", "P10", "P11", "P12", "P13", "P14",
            "P15", "P16", "P17"]

# ── 2. Output file ────────────────────────────────────────────────────────────
RESULTS_FILENAME = "sp_fulltext_results.tsv"


# ── 3. Metric parsing helpers ─────────────────────────────────────────────────
def _parse_metrics_line(line: str) -> dict[str, str]:
    """Parse a metrics line like: TP/FP/FN/TN = 22 / 19 / 6 / 552 | Recall=..."""
    result: dict[str, str] = {}
    m = re.search(r"TP/FP/FN/TN\s*=\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", line)
    if m:
        result["tp"] = m.group(1)
        result["fp"] = m.group(2)
        result["fn"] = m.group(3)
        result["tn"] = m.group(4)
    for metric in ("Recall", "Precision", "F1", "MCC", "WR"):
        m2 = re.search(rf"{metric}=([0-9.%]+)", line)
        if m2:
            result[metric.lower()] = m2.group(1).rstrip("%")
    return result


def _parse_delta_line(line: str) -> dict[str, str]:
    """Parse delta line: TP 22 -> 21 (-1) | FP ..."""
    result: dict[str, str] = {}
    for key in ("TP", "FP", "FN", "TN"):
        m = re.search(rf"{key}\s+\d+\s+->\s+\d+\s+\(([+-]?\d+)\)", line)
        if m:
            result[f"d_{key.lower()}"] = m.group(1)
    for metric in ("Recall", "Precision", "F1", "MCC"):
        m2 = re.search(rf"{metric}\s+[\d.%]+\s+->\s+[\d.%]+", line)
        # Extract both before/after from delta line is complex; skip here
        # Already captured in stage1/final metric lines
    return result


def parse_summary(stdout: str) -> dict[str, str]:
    """Extract all key metrics from the Second-stage summary block."""
    lines = stdout.splitlines()
    result: dict[str, str] = {}

    in_summary = False
    for i, line in enumerate(lines):
        if "Second-stage summary" in line:
            in_summary = True
        if not in_summary:
            continue

        if re.search(r"Possible candidates input:", line):
            m = re.search(r"Possible candidates input:\s*(\d+)", line)
            if m:
                result["possible_input"] = m.group(1)

        if re.search(r"PMC full-text screened:", line):
            m = re.search(r"PMC full-text screened:\s*(\d+)", line)
            if m:
                result["pmc_screened"] = m.group(1)

        if re.search(r"PMC unavailable", line):
            m = re.search(r"PMC unavailable.*?:\s*(\d+)", line)
            if m:
                result["pmc_unavailable"] = m.group(1)

        if re.search(r"Label changes after merge:", line):
            m = re.search(r"Label changes after merge:\s*(\d+)", line)
            if m:
                result["label_changes"] = m.group(1)
            # Count GT changes in following lines
            gt_changes = []
            for j in range(i + 1, min(i + 30, len(lines))):
                if re.search(r"PMID=\S+\s*\|\s*GT=yes", lines[j]):
                    gt_changes.append(lines[j].strip())
                elif lines[j].strip().startswith("Stage1 metrics:"):
                    break
            result["gt_label_changes"] = str(len(gt_changes))
            result["gt_changes_detail"] = " || ".join(gt_changes[:5])

        if line.strip().startswith("Stage1 metrics:"):
            if i + 1 < len(lines):
                m1 = _parse_metrics_line(lines[i + 1])
                result.update({f"s1_{k}": v for k, v in m1.items()})

        if line.strip().startswith("Final merged metrics:"):
            if i + 1 < len(lines):
                mf = _parse_metrics_line(lines[i + 1])
                result.update({f"final_{k}": v for k, v in mf.items()})

        if line.strip().startswith("Delta:"):
            if i + 1 < len(lines):
                d = _parse_delta_line(lines[i + 1])
                result.update(d)
            if i + 2 < len(lines):
                d2 = _parse_delta_line(lines[i + 2])
                result.update(d2)

    return result


# ── 4. CSV fieldnames ─────────────────────────────────────────────────────────
FIELDS = [
    "profile", "status", "timestamp",
    "possible_input", "pmc_screened", "pmc_unavailable",
    "label_changes", "gt_label_changes",
    "s1_tp", "s1_fp", "s1_fn", "s1_tn",
    "s1_recall", "s1_precision", "s1_f1", "s1_mcc",
    "final_tp", "final_fp", "final_fn", "final_tn",
    "final_recall", "final_precision", "final_f1", "final_mcc",
    "d_tp", "d_fp", "d_fn", "d_tn",
    "gt_changes_detail",
]


# ── 5. Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Batch --resume-sp-fulltext for all profiles")
    parser.add_argument("--project-root", default=".", help="Repository root directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without executing")
    parser.add_argument("--profiles", nargs="+", default=PROFILES,
                        help="Override profile list (default: all except P9)")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    python_exe = project_root / "dev" / "literature_search" / ".venv" / "Scripts" / "python.exe"
    screening_script = project_root / "dev" / "literature_search" / "scripts" / "cli" / "screening_llm_batch.py"
    results_dir = project_root / "evaluation" / "screening" / "GT_1"
    results_file = results_dir / RESULTS_FILENAME
    log_dir = results_dir / "sp_fulltext_logs"

    if not args.dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)

    progress_file = results_dir / "sp_fulltext_progress.txt"

    def _log(msg: str) -> None:
        print(msg, flush=True)
        with open(progress_file, "a", encoding="utf-8") as pf:
            pf.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

    _log(f"=== Batch start: {datetime.now().isoformat()} ===")
    _log(f"Profiles to run: {args.profiles}")
    _log(f"Results → {results_file}")
    _log(f"Logs    → {log_dir}\n")

    rows: list[dict[str, str]] = []

    for i, profile in enumerate(args.profiles, 1):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cmd = [
            str(python_exe),
            str(screening_script),
            "--project-root", str(project_root),
            "--profile", profile,
            "--resume-sp-fulltext",
        ]
        _log(f"[{i}/{len(args.profiles)}] {'[DRY] ' if args.dry_run else ''}▶  {profile}  ({ts})")

        if args.dry_run:
            print(f"      {' '.join(cmd)}\n", flush=True)
            continue

        log_file = log_dir / f"{profile}_{ts}.log"
        row: dict[str, str] = {"profile": profile, "timestamp": ts, "status": "ok"}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                cwd=str(project_root),
            )
            output = result.stdout + ("\n[STDERR]\n" + result.stderr if result.stderr.strip() else "")
            log_file.write_text(output, encoding="utf-8")

            if result.returncode != 0:
                row["status"] = f"error_rc{result.returncode}"
                _log(f"  ✗ exit code {result.returncode} — see {log_file.name}")
            else:
                _log(f"  ✓ done — {log_file.name}")

            metrics = parse_summary(result.stdout)
            row.update(metrics)

            s1r  = metrics.get("s1_recall", "?")
            fnr  = metrics.get("final_recall", "?")
            s1p  = metrics.get("s1_precision", "?")
            fnp  = metrics.get("final_precision", "?")
            dtp  = metrics.get("d_tp", "?")
            dfp  = metrics.get("d_fp", "?")
            chg  = metrics.get("label_changes", "?")
            gtc  = metrics.get("gt_label_changes", "?")
            _log(f"  Recall {s1r}% → {fnr}%   Precision {s1p}% → {fnp}%")
            _log(f"  ΔTP={dtp}  ΔFP={dfp}   label_changes={chg}  gt_affected={gtc}\n")

        except Exception as exc:
            row["status"] = f"exception: {exc}"
            _log(f"  ✗ exception: {exc}\n")

        rows.append(row)

    if args.dry_run or not rows:
        return

    # Write TSV
    with open(results_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore",
                                delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    _log(f"\n{'='*60}")
    _log(f"All done.  Results written to:\n  {results_file}")
    _log(f"{'='*60}")


if __name__ == "__main__":
    main()
