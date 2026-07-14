"""Run the current production coding pipeline for covid19/serial_interval/p13."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_INPUT = ROOT / "e2e" / "p13_pmids.txt"
DEFAULT_OUT_DIR = ROOT / "e2e" / "runs" / "p13_current"
DEFAULT_CODEBOOK = ROOT / "configs" / "covid19" / "codebooks" / "serial_interval.yaml"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--codebook", type=Path, default=DEFAULT_CODEBOOK)
    parser.add_argument("--stage", default="both", choices=("fetch", "index", "extract", "both"))
    parser.add_argument("--fetch-strategy", default="pmc_only")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove the output directory before running so indexes are not reused.",
    )
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    if args.fresh and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from metaagent.coding.pipeline.extraction import run_pipeline

    t0 = time.time()
    run_pipeline(
        input_path=args.input.resolve(),
        out_dir=out_dir,
        stage=args.stage,
        codebook_path=args.codebook.resolve(),
        fetch_strategy=args.fetch_strategy,
    )
    summary = _summarize_run(
        input_path=args.input.resolve(),
        out_dir=out_dir,
        codebook_path=args.codebook.resolve(),
        stage=args.stage,
        fetch_strategy=args.fetch_strategy,
        elapsed_s=round(time.time() - t0, 1),
    )
    summary_path = out_dir / "e2e_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[done] wrote {summary_path}")


def _summarize_run(
    *,
    input_path: Path,
    out_dir: Path,
    codebook_path: Path,
    stage: str,
    fetch_strategy: str,
    elapsed_s: float,
) -> dict[str, object]:
    input_pmids = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    xlsx_files = sorted(
        out_dir.glob("coding_sheet*.xlsx"),
        key=lambda path: path.stat().st_mtime,
    )
    latest_xlsx = xlsx_files[-1] if xlsx_files else None
    record_count = 0
    if latest_xlsx is not None:
        record_count = int(len(pd.read_excel(latest_xlsx)))

    index_count = len(list((out_dir / "index").glob("*.index.json")))
    errors = []
    for path in sorted((out_dir / "errors").glob("*.error.json")):
        try:
            errors.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            errors.append({"path": str(path), "error": "invalid error json"})

    return {
        "input_count": len(input_pmids),
        "record_count": record_count,
        "index_row_count": index_count,
        "error_count": len(errors),
        "errors": errors,
        "xlsx_path": str(latest_xlsx) if latest_xlsx is not None else None,
        "elapsed_s": elapsed_s,
        "codebook": str(codebook_path),
        "stage": stage,
        "fetch_strategy": fetch_strategy,
        "pmids_input": str(input_path),
    }


if __name__ == "__main__":
    main()
