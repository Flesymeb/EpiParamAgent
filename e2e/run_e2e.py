"""End-to-end coding pipeline re-run for reproducibility testing.

WHY THIS WRAPPER (not a direct run_pipeline call):
  metaagent.coding.pipeline.extraction.run_pipeline() crashes with the documented
  config paths on this branch (feat/webapp-ui) for TWO reasons:
    1. The codebook configs/covid19/codebooks/serial_interval.yaml references its
       stage prompts as "prompts/stage_a_serial_interval.py" (relative to the
       codebook dir), but the real files live in configs/covid19/coding_prompts/.
       -> load_config() raises FileNotFoundError.
    2. run_pipeline() hardcodes the Stage-A index config at
       metaagent/configs/stages/stage_a.yaml, which does not exist on this branch
       (the real file is configs/covid19/coding_prompts/stage_a.yaml).

  Since e2e/ must not modify metaagent/ or configs/, this driver replicates the
  EXACT body of run_pipeline() (stage="both") but:
    - loads the codebook from e2e/configs/serial_interval_fixed.yaml (a verbatim
      copy of the repo codebook with the two prompt_file paths corrected to absolute
      coding_prompts/ locations), and
    - loads the Stage-A config from the real configs/covid19/coding_prompts/stage_a.yaml.
  ALL extraction logic (init_llm, process_fulltext, run_index, run_extract,
  prompt_factory, export_records) is the unmodified metaagent code, so the
  LLM-facing behaviour is identical to the production pipeline.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metaagent.coding.llm import init_llm
from metaagent.coding.shared.io import infer_pmid_from_path, read_text
from metaagent.coding.export.exporters import export_records
from metaagent.coding.fulltext_processor import process_fulltext
from metaagent.coding.schema.config_loader import load_config
from metaagent.coding.pipeline.extraction import (
    _iter_inputs,
    _load_markdown_from_pdf,
    _apply_stage_prompt_from_codebook,
    _inject_codebook_context,
    _get_index_schema,
    _build_index_row,
    _write_paper_error,
    run_index,
    run_extract,
)

INPUT_TXT = ROOT / "e2e" / "p13_pmids.txt"
OUT_DIR = ROOT / "e2e" / "runs" / "p13"
CODEBOOK = ROOT / "e2e" / "configs" / "serial_interval_fixed.yaml"
STAGE_A_YAML = ROOT / "e2e" / "configs" / "stage_a_fixed.yaml"
FETCH_STRATEGY = "pmc_only"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_dir = OUT_DIR / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    model = init_llm()
    stage_a_config = load_config(STAGE_A_YAML)
    effect_config = load_config(CODEBOOK)

    # Apply stage prompts exactly as run_pipeline does
    applied_b = _apply_stage_prompt_from_codebook(effect_config, "stage_b", effect_config)
    print(f"[cfg] stage_b prompt applied from codebook: {applied_b}")
    applied_a = _apply_stage_prompt_from_codebook(effect_config, "stage_a", stage_a_config)
    print(f"[cfg] stage_a prompt applied from codebook: {applied_a}")
    _inject_codebook_context(stage_a_config, effect_config)

    records: list[dict] = []
    index_rows: list[dict] = []
    errors: list[dict] = []

    inputs = list(_iter_inputs(INPUT_TXT, fetch_strategy=FETCH_STRATEGY))
    print(f"[input] {len(inputs)} input files resolved")
    if not inputs:
        print("[WARN] No inputs.")
        return

    t0 = time.time()
    for i, path in enumerate(inputs, 1):
        pmid = infer_pmid_from_path(path) or path.stem
        ts = time.time()
        if path.suffix.lower() == ".pdf":
            markdown = _load_markdown_from_pdf(path, pmid)
        else:
            markdown = read_text(path)

        max_chars = effect_config.extraction.max_input_chars
        trunc_marker = effect_config.extraction.truncation_marker
        processed = process_fulltext(markdown, max_chars=max_chars, truncation_marker=trunc_marker)
        fulltext = processed.content
        tables_summary = processed.tables_summary
        title = f"PMID {pmid}"
        abstract = ""

        # Stage A: index (fresh — out_dir is empty, no reuse)
        index_path = index_dir / f"PMID_{pmid}.index.json"
        try:
            index_obj = run_index(
                fulltext=fulltext, tables_summary=tables_summary,
                was_truncated=processed.was_truncated, pmid=pmid,
                title=title, abstract=abstract, config=stage_a_config, model=model,
            )
            index_payload = index_obj.get("index") if isinstance(index_obj, dict) else None
            index_envelope = {"pmid": pmid, "index": index_payload or index_obj}
            index_path.write_text(json.dumps(index_envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            _write_paper_error(OUT_DIR, pmid, "index", exc)
            errors.append({"pmid": pmid, "stage": "index", "error": str(exc)})
            print(f"[{i}/{len(inputs)}] PMID {pmid}: INDEX FAILED ({type(exc).__name__})")
            continue
        index_schema = _get_index_schema(effect_config)
        if index_schema:
            index_rows.append(_build_index_row(pmid, index_envelope, index_schema))

        # Stage B: extract
        index_json = json.dumps(index_obj, ensure_ascii=False)
        try:
            record_objs = run_extract(
                fulltext=fulltext, tables_summary=tables_summary,
                was_truncated=processed.was_truncated, title=title, abstract=abstract,
                index_json=index_json, config=effect_config, model=model,
            )
        except Exception as exc:
            _write_paper_error(OUT_DIR, pmid, "extract", exc)
            errors.append({"pmid": pmid, "stage": "extract", "error": str(exc)})
            print(f"[{i}/{len(inputs)}] PMID {pmid}: EXTRACT FAILED ({type(exc).__name__})")
            continue
        n_rec = len(record_objs or [])
        for record_obj in record_objs or []:
            pmid_value = str(record_obj.get("pmid", "")).strip().upper()
            if "pmid" not in record_obj or pmid_value in {"", "NR", "NA", "N/A", "NONE", "NULL"}:
                record_obj["pmid"] = pmid
            records.append(record_obj)
        print(f"[{i}/{len(inputs)}] PMID {pmid}: {n_rec} records ({time.time()-ts:.0f}s)", flush=True)

    xlsx_path = None
    if records:
        xlsx_path, _ = export_records(
            records, OUT_DIR, basename="coding_sheet",
            column_order=[f.name for f in effect_config.fields] if effect_config.fields else None,
        )

    summary = {
        "input_count": len(inputs),
        "record_count": len(records),
        "index_row_count": len(index_rows),
        "error_count": len(errors),
        "errors": errors,
        "xlsx_path": str(xlsx_path) if xlsx_path else None,
        "elapsed_s": round(time.time() - t0, 1),
        "codebook": str(CODEBOOK),
        "stage_a_yaml": str(STAGE_A_YAML),
        "pmids_input": str(INPUT_TXT),
    }
    (OUT_DIR / "e2e_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n[DONE] records={len(records)} index_rows={len(index_rows)} errors={len(errors)} "
          f"xlsx={xlsx_path} elapsed={summary['elapsed_s']}s")


if __name__ == "__main__":
    main()
