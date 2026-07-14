#!/usr/bin/env python3
"""Direct full-text LLM coding baseline.

This baseline intentionally skips the MetaAgent Stage-A evidence localization.
For each PMID, it sends the PDF-derived full-text markdown plus the target
output fields to the LLM and asks for extraction records directly. The outputs
are pooled with the same profile-specific pooling code used by the E2E tracker.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e2e.update_screen_to_coding_tracking import (  # noqa: E402
    PARAM_GROUP_TOPIC,
    _fmt_num,
    _pool,
    _read_gt_pmids,
)
from metaagent.coding.export.exporters import export_records  # noqa: E402
from metaagent.coding.fulltext_processor import process_fulltext  # noqa: E402
from metaagent.coding.llm import init_llm  # noqa: E402
from metaagent.coding.parsing import parse_json_records  # noqa: E402
from metaagent.coding.pipeline.extraction import (  # noqa: E402
    _effective_max_input_chars,
    _invoke_model_content,
    _iter_inputs,
    _load_markdown_from_pdf,
)
from metaagent.coding.schema.config_loader import load_config  # noqa: E402
from metaagent.coding.shared.io import infer_pmid_from_path, read_text  # noqa: E402


SOURCE_DATA = ROOT / "docs" / "paper" / "source_data" / "coding_estimate_intervals.csv"
RUN_ROOT = ROOT / "e2e" / "runs" / "direct_fulltext_coding_baseline"
OFFICIAL_SELECTED_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding" / "official_qwen36_recall_selected"
PAPER_POOL_PDFS = ROOT / "paper_pool" / "pdfs"


def _project_num(project: object) -> str:
    return str(project).strip().lower().removeprefix("mp").removeprefix("p")


def _profile(disease: str, project: object) -> str:
    prefix = "MP" if disease == "mpox" else "P"
    return f"{prefix}{_project_num(project)}"


def _safe_float(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _topic_from_row(row: pd.Series) -> str:
    return PARAM_GROUP_TOPIC[str(row["parameter_group"]).strip().lower()]


def _codebook_path(disease: str, topic: str) -> Path:
    return ROOT / "configs" / disease / "codebooks" / f"{topic}.yaml"


def _field_schema_text(config) -> str:
    lines = []
    for field in config.fields:
        lines.append(f"- {field.name} ({field.type})")
    return "\n".join(lines)


def _direct_system_prompt() -> str:
    return (
        "You extract structured data from biomedical full-text articles. "
        "Return JSON only."
    )


def _direct_user_prompt(
    *,
    disease: str,
    topic: str,
    article: str,
    pmid: str,
    config,
    fulltext: str,
    was_truncated: bool,
    exclude_cited_estimates: bool,
) -> str:
    parameter_label = {
        "serial_interval": "serial interval",
        "reproduction_number": "basic/effective reproduction number",
        "fatality": "fatality rate",
    }.get(topic, topic)
    cited_instruction = ""
    if exclude_cited_estimates:
        cited_instruction = (
            "\n- Do not extract estimates that are only cited from other studies, "
            "background text, or literature-summary tables; extract estimates generated "
            "or analysed by this article itself.\n"
        )

    return f"""Task: Directly extract {parameter_label} coding records for a systematic review.

Disease: {disease}
Source review: {article}
PMID: {pmid}

Return a JSON array using these fields:
{_field_schema_text(config)}

Instructions:
- Read the full text and extract the main relevant estimate(s) for this target parameter.
- Use the field names exactly as listed.
- If no relevant estimate is reported, return [].
- Use null for missing numeric values and "NR" for missing text values.
{cited_instruction}

Document was truncated: {was_truncated}

PDF-derived full text:
{fulltext}
"""


def _source_rows() -> pd.DataFrame:
    df = pd.read_csv(SOURCE_DATA)
    df["topic"] = df.apply(_topic_from_row, axis=1)
    df["profile"] = df.apply(lambda r: _profile(str(r["disease"]), r["project"]), axis=1)
    return df


def _selected_pmids(profile: str) -> list[str]:
    path = OFFICIAL_SELECTED_ROOT / profile / "screening_selected_records.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, dtype=str, low_memory=False)
    if "PMID" not in df.columns:
        return []
    return df["PMID"].dropna().astype(str).str.extract(r"(\d+)")[0].dropna().drop_duplicates().tolist()


def _input_pmids(row: pd.Series, input_mode: str) -> list[str]:
    disease = str(row["disease"])
    topic = str(row["topic"])
    profile = str(row["profile"])
    project_num = _project_num(row["project"])
    if input_mode == "e2e":
        return _selected_pmids(profile)
    gt = _read_gt_pmids(disease, topic, project_num)
    return sorted(gt, key=lambda x: int(x) if str(x).isdigit() else str(x))


def _paper_pool_pdf(pmid: str) -> Path:
    return PAPER_POOL_PDFS / f"PMID_{pmid}.pdf"


def _extract_pdf_text(pdf_path: Path) -> str:
    import fitz  # PyMuPDF

    chunks: list[str] = []
    with fitz.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            chunks.append(f"\n\n[Page {idx}]\n{text.strip()}")
    return "\n".join(chunks).strip()


def _load_fulltext(path: Path, pmid: str, text_source: str) -> tuple[str, str, str]:
    pdf_path = path if path.suffix.lower() == ".pdf" else _paper_pool_pdf(pmid)
    if text_source == "pdf_text" and pdf_path.exists():
        return _extract_pdf_text(pdf_path), "pdf_text", str(pdf_path)
    if text_source == "pdf_markdown" and pdf_path.exists():
        return _load_markdown_from_pdf(pdf_path, pmid), "pdf_markdown", str(pdf_path)
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_text(path), "pdf_text", str(path)
    return read_text(path), "markdown_fallback", str(path)


def _chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        if end < len(text):
            split_at = max(text.rfind("\n\n", start, end), text.rfind("\n", start, end))
            if split_at > start + int(chunk_chars * 0.65):
                end = split_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _invoke_direct_extract(
    *,
    model,
    llm_overrides: dict[str, object],
    pmid: str,
    messages: list[dict[str, str]],
) -> str:
    return _invoke_model_content(
        model=model,
        messages=messages,
        llm_overrides=llm_overrides,
        pmid=pmid,
        stage_name="direct_fulltext_extract",
    )


def _run_one_pmid(
    *,
    pmid: str,
    path: Path,
    disease: str,
    topic: str,
    article: str,
    config,
    model,
    llm_overrides: dict[str, object],
    out_dir: Path,
    max_input_chars: int,
    text_source: str,
    llm_call_timeout_s: int | None,
    chunked_pdf: bool,
    chunk_chars: int,
    chunk_overlap_chars: int,
    exclude_cited_estimates: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_dir = out_dir / "direct_records"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"PMID_{pmid}.{text_source}.direct.json"
    if cache_path.exists():
        envelope = json.loads(cache_path.read_text(encoding="utf-8"))
        return list(envelope.get("records") or []), envelope

    fulltext_raw, source_type, source_path = _load_fulltext(path, pmid, text_source)
    if model is None:
        model = init_llm(llm_overrides)
    if llm_call_timeout_s:
        # init_llm reloads .env.local, so apply CLI timeout after model init.
        os.environ["CODING_LLM_SUBPROCESS_TIMEOUT_S"] = str(llm_call_timeout_s)
        os.environ["CODING_LLM_CALL_TIMEOUT_S"] = str(llm_call_timeout_s)

    chunk_errors: list[dict[str, object]] = []
    was_truncated = False
    prompt_fulltext_chars = 0
    if chunked_pdf and text_source == "pdf_text" and source_type == "pdf_text":
        chunks = _chunk_text(
            fulltext_raw,
            chunk_chars=chunk_chars,
            overlap_chars=chunk_overlap_chars,
        )
        responses: list[str] = []
        records = []
        for chunk_idx, chunk in enumerate(chunks, start=1):
            processed = process_fulltext(
                chunk,
                max_chars=chunk_chars,
                truncation_marker=config.extraction.truncation_marker,
            )
            was_truncated = was_truncated or processed.was_truncated
            prompt_fulltext_chars += len(processed.content)
            user_prompt = _direct_user_prompt(
                disease=disease,
                topic=topic,
                article=article,
                pmid=pmid,
                config=config,
                fulltext=f"[Chunk {chunk_idx}/{len(chunks)}]\n{processed.content}",
                was_truncated=processed.was_truncated,
                exclude_cited_estimates=exclude_cited_estimates,
            )
            messages = [
                {"role": "system", "content": _direct_system_prompt()},
                {"role": "user", "content": user_prompt},
            ]
            try:
                content = _invoke_direct_extract(
                    model=model,
                    messages=messages,
                    llm_overrides=llm_overrides,
                    pmid=pmid,
                )
            except Exception as exc:
                chunk_errors.append(
                    {"chunk": chunk_idx, "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            responses.append(content)
            records.extend(parse_json_records(content))
        content = "\n\n".join(responses)
    else:
        processed = process_fulltext(
            fulltext_raw,
            max_chars=max_input_chars,
            truncation_marker=config.extraction.truncation_marker,
        )
        was_truncated = processed.was_truncated
        prompt_fulltext_chars = len(processed.content)
        user_prompt = _direct_user_prompt(
            disease=disease,
            topic=topic,
            article=article,
            pmid=pmid,
            config=config,
            fulltext=processed.content,
            was_truncated=processed.was_truncated,
            exclude_cited_estimates=exclude_cited_estimates,
        )
        messages = [
            {"role": "system", "content": _direct_system_prompt()},
            {"role": "user", "content": user_prompt},
        ]
        content = _invoke_direct_extract(
            model=model,
            messages=messages,
            llm_overrides=llm_overrides,
            pmid=pmid,
        )
        records = parse_json_records(content)

    seen: set[str] = set()
    deduped_records: list[dict[str, Any]] = []
    for record in records:
        pmid_value = str(record.get("pmid", "")).strip().upper()
        if "pmid" not in record or pmid_value in {"", "NR", "NA", "N/A", "NONE", "NULL"}:
            record["pmid"] = pmid
        key = json.dumps(record, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped_records.append(record)
    records = deduped_records
    envelope = {
        "pmid": pmid,
        "path": source_path,
        "source_type": "pdf_text_chunked" if chunked_pdf and source_type == "pdf_text" else source_type,
        "records": records,
        "raw_response": content,
        "fulltext_chars": len(fulltext_raw),
        "prompt_fulltext_chars": prompt_fulltext_chars,
        "was_truncated": was_truncated,
        "chunked_pdf": bool(chunked_pdf and source_type == "pdf_text"),
        "exclude_cited_estimates": exclude_cited_estimates,
        "chunk_errors": chunk_errors,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    cache_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return records, envelope


def _pool_records(records: list[dict[str, Any]], topic: str, disease: str, project_num: str) -> dict[str, Any]:
    if not records:
        return {}
    return _pool(pd.DataFrame(records), topic, disease, project_num)


def _normalize_direct_record(record: dict[str, Any], topic: str) -> dict[str, Any]:
    """Normalize direct-baseline free-form labels to the existing pooling schema."""
    out = dict(record)
    parameter_type = str(out.get("parameter_type", "")).strip().lower().replace("-", " ").replace("_", " ")
    estimate_measure = str(out.get("estimate_measure", "")).strip().lower().replace("-", "_").replace(" ", "_")
    unit = str(out.get("unit", "")).strip().lower()

    if topic == "serial_interval":
        if parameter_type in {"serial interval", "serial"}:
            out["parameter_type"] = "serial_interval"
        elif parameter_type in {"generation interval", "generation time"}:
            out["parameter_type"] = parameter_type.replace(" ", "_")
        if unit in {"day", "days"}:
            out["unit"] = "d"
    elif topic == "reproduction_number":
        if parameter_type in {"r0", "basic reproduction number", "basic reproductive number"}:
            out["parameter_type"] = "R0"
        elif parameter_type in {"rt", "effective reproduction number", "effective reproductive number"}:
            out["parameter_type"] = "Rt"
        if unit in {"dimensionless", "none", "nr", "n/a"}:
            out["unit"] = ""
    elif topic == "fatality":
        mapping = {
            "case fatality rate": "CFR",
            "case fatality ratio": "CFR",
            "cfr": "CFR",
            "infection fatality rate": "IFR",
            "infection fatality ratio": "IFR",
            "ifr": "IFR",
            "hospital fatality rate": "HFR",
            "hospitalized fatality rate": "HFR",
            "hfr": "HFR",
        }
        if parameter_type in mapping:
            out["fatality_type"] = mapping[parameter_type]
        if unit in {"percent", "percentage", "%"}:
            out["unit"] = "%"

    if estimate_measure in {"point_estimate", "point", "estimate"}:
        out["estimate_measure"] = "point_estimate" if topic == "reproduction_number" else "mean"
    elif estimate_measure:
        out["estimate_measure"] = estimate_measure
    return out


def _profile_out_dir(row: pd.Series, input_mode: str, out_root: Path) -> Path:
    disease = str(row["disease"])
    topic = str(row["topic"])
    project_num = _project_num(row["project"])
    return out_root / f"{disease}_{topic}_p{project_num}_{input_mode}_direct"


def run_profile(
    row: pd.Series,
    *,
    input_mode: str,
    out_root: Path,
    fetch_strategy: str,
    llm_overrides: dict[str, object],
    limit: int | None,
    fresh: bool,
    llm_call_timeout_s: int | None,
    text_source: str,
    concurrency: int,
    chunked_pdf: bool,
    chunk_chars: int,
    chunk_overlap_chars: int,
    exclude_cited_estimates: bool,
) -> dict[str, Any]:
    disease = str(row["disease"])
    topic = str(row["topic"])
    profile = str(row["profile"])
    project_num = _project_num(row["project"])
    article = str(row["article"])
    out_dir = _profile_out_dir(row, input_mode, out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    if fresh:
        for path in (out_dir / "direct_records").glob("PMID_*.direct.json"):
            path.unlink()
        for path in (out_dir / "direct_records").glob(f"PMID_*.{text_source}.direct.json"):
            path.unlink()

    pmids = _input_pmids(row, input_mode)
    if limit is not None:
        pmids = pmids[:limit]
    input_txt = out_dir / "input_pmids.txt"
    input_txt.write_text("\n".join(pmids) + ("\n" if pmids else ""), encoding="utf-8")

    codebook = _codebook_path(disease, topic)
    config = load_config(codebook)
    max_input_chars = _effective_max_input_chars(config.extraction.max_input_chars)
    inputs = list(_iter_inputs(input_txt, fetch_strategy=fetch_strategy))
    input_by_pmid = {infer_pmid_from_path(path) or path.stem: path for path in inputs}
    model = init_llm(llm_overrides) if concurrency <= 1 else None
    if llm_call_timeout_s:
        # init_llm reloads .env.local, so apply CLI timeout after model init.
        os.environ["CODING_LLM_SUBPROCESS_TIMEOUT_S"] = str(llm_call_timeout_s)
        os.environ["CODING_LLM_CALL_TIMEOUT_S"] = str(llm_call_timeout_s)

    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    envelopes: list[dict[str, Any]] = []
    tasks: list[tuple[int, str, Path]] = []
    for idx, pmid in enumerate(pmids, start=1):
        path = input_by_pmid.get(pmid)
        pdf_path = _paper_pool_pdf(pmid)
        if pdf_path.exists():
            path = pdf_path
        if not path:
            errors.append({"pmid": pmid, "stage": "load_fulltext", "error": "full text not available"})
            print(f"[{profile}] {idx}/{len(pmids)} PMID {pmid}: full text not available")
            continue
        tasks.append((idx, pmid, path))

    def _task(idx: int, pmid: str, path: Path) -> tuple[int, str, list[dict[str, Any]], dict[str, Any]]:
        recs, envelope = _run_one_pmid(
                pmid=pmid,
                path=path,
                disease=disease,
                topic=topic,
                article=article,
                config=config,
                model=model,
                llm_overrides=llm_overrides,
                out_dir=out_dir,
                max_input_chars=max_input_chars,
                text_source=text_source,
                llm_call_timeout_s=llm_call_timeout_s,
                chunked_pdf=chunked_pdf,
                chunk_chars=chunk_chars,
                chunk_overlap_chars=chunk_overlap_chars,
                exclude_cited_estimates=exclude_cited_estimates,
            )
        recs = [_normalize_direct_record(record, topic) for record in recs]
        return idx, pmid, recs, envelope

    if concurrency <= 1:
        for idx, pmid, path in tasks:
            try:
                _, _, recs, envelope = _task(idx, pmid, path)
            except Exception as exc:  # keep the run resumable
                errors.append({"pmid": pmid, "stage": "direct_extract", "error": f"{type(exc).__name__}: {exc}"})
                print(f"[{profile}] {idx}/{len(pmids)} PMID {pmid}: ERROR {type(exc).__name__}: {exc}")
                continue
            print(f"[{profile}] {idx}/{len(pmids)} PMID {pmid}: records={len(recs)}")
            records.extend(recs)
            envelopes.append(envelope)
    else:
        pool = ThreadPoolExecutor(max_workers=concurrency)
        try:
            future_map = {pool.submit(_task, idx, pmid, path): (idx, pmid) for idx, pmid, path in tasks}
            for future in as_completed(future_map):
                idx, pmid = future_map[future]
                try:
                    _, _, recs, envelope = future.result()
                except Exception as exc:
                    errors.append({"pmid": pmid, "stage": "direct_extract", "error": f"{type(exc).__name__}: {exc}"})
                    print(f"[{profile}] {idx}/{len(pmids)} PMID {pmid}: ERROR {type(exc).__name__}: {exc}")
                    continue
                print(f"[{profile}] {idx}/{len(pmids)} PMID {pmid}: records={len(recs)}")
                records.extend(recs)
                envelopes.append(envelope)
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

    xlsx_path = ""
    if records:
        xlsx, _ = export_records(
            records,
            out_dir,
            basename="direct_coding_sheet",
            column_order=[field.name for field in config.fields] if config.fields else None,
        )
        xlsx_path = str(xlsx)
        pd.DataFrame(records).to_csv(out_dir / "direct_coding_records.csv", index=False)

    pool = _pool_records(records, topic, disease, project_num)
    sr = _safe_float(row.get("sr"))
    module = _safe_float(row.get("llm"))
    direct = _safe_float(pool.get("pooled_mean"))
    chunk_error_count = sum(len(envelope.get("chunk_errors") or []) for envelope in envelopes)
    summary = {
        "status": "completed" if records else "completed_no_records",
        "input_mode": input_mode,
        "disease": disease,
        "topic": topic,
        "profile": profile,
        "article": article,
        "input_pmids": len(pmids),
        "fulltext_available": len(inputs),
        "record_count": len(records),
        "error_count": len(errors),
        "chunk_error_count": chunk_error_count,
        "text_source": text_source,
        "concurrency": concurrency,
        "chunked_pdf": chunked_pdf,
        "exclude_cited_estimates": exclude_cited_estimates,
        "parameter_type": pool.get("parameter_type"),
        "estimate_measure": pool.get("estimate_measure"),
        "pool_method": pool.get("pool_method"),
        "n_studies": _fmt_num(pool.get("n_studies"), 0),
        "n_excluded": _fmt_num(pool.get("n_excluded"), 0),
        "pooled_input_rows": pool.get("pooled_input_rows"),
        "pooled_input_pmids": pool.get("pooled_input_pmids"),
        "direct_pooled_mean": _fmt_num(pool.get("pooled_mean")),
        "direct_ci_lower": _fmt_num(pool.get("ci_lower")),
        "direct_ci_upper": _fmt_num(pool.get("ci_upper")),
        "sr_point": _fmt_num(sr),
        "sr_ci_lower": _fmt_num(row.get("sr_lo")),
        "sr_ci_upper": _fmt_num(row.get("sr_hi")),
        "module_point": _fmt_num(module),
        "module_ci_lower": _fmt_num(row.get("llm_lo")),
        "module_ci_upper": _fmt_num(row.get("llm_hi")),
        "delta_direct_vs_sr": _fmt_num((direct - sr) if direct is not None and sr is not None else None),
        "delta_direct_vs_module": _fmt_num((direct - module) if direct is not None and module is not None else None),
        "unit": row.get("unit"),
        "xlsx": xlsx_path,
        "out_dir": str(out_dir),
        "pooling_warnings": pool.get("pooling_warnings", ""),
    }
    (out_dir / "direct_baseline_summary.json").write_text(
        json.dumps({"summary": summary, "errors": errors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _write_markdown(summary: pd.DataFrame, output: Path) -> None:
    cols = [
        "profile",
        "article",
        "input_pmids",
        "fulltext_available",
        "record_count",
        "error_count",
        "chunk_error_count",
        "direct_pooled_mean",
        "direct_ci_lower",
        "direct_ci_upper",
        "sr_point",
        "module_point",
        "delta_direct_vs_sr",
        "delta_direct_vs_module",
        "unit",
    ]
    text = [
        "# Direct Full-Text Coding Baseline",
        "",
        f"Last updated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "This baseline sends PDF-derived full text and output fields directly to the LLM, without Stage-A evidence localization.",
        "",
        summary[cols].to_markdown(index=False),
        "",
    ]
    output.write_text("\n".join(text), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", nargs="*", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--input-mode", choices=["gt", "e2e"], default="gt")
    parser.add_argument("--out-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--fetch-strategy", default="pmc_only", choices=["pmc_only", "pmc_scihub", "pmc_scihub_manual"])
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=int, default=None)
    parser.add_argument("--llm-call-timeout-s", type=int, default=240)
    parser.add_argument("--text-source", choices=["pdf_text", "pdf_markdown", "markdown"], default="pdf_text")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--chunked-pdf", action="store_true")
    parser.add_argument("--chunk-chars", type=int, default=14000)
    parser.add_argument("--chunk-overlap-chars", type=int, default=800)
    parser.add_argument("--exclude-cited-estimates", action="store_true")
    parser.add_argument("--limit-per-profile", type=int, default=None)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    source = _source_rows()
    if args.all:
        rows = source.copy()
    else:
        wanted = {p.upper() for p in (args.profiles or ["P12"])}
        rows = source[source["profile"].astype(str).str.upper().isin(wanted)].copy()
    if rows.empty:
        raise SystemExit("No profiles matched.")

    llm_overrides: dict[str, object] = {"temperature": args.temperature}
    if args.provider:
        llm_overrides["provider"] = args.provider
    if args.model:
        llm_overrides["model"] = args.model
    if args.timeout_s:
        llm_overrides["timeout_s"] = args.timeout_s

    args.out_root.mkdir(parents=True, exist_ok=True)
    summaries = [
        run_profile(
            row,
            input_mode=args.input_mode,
            out_root=args.out_root,
            fetch_strategy=args.fetch_strategy,
            llm_overrides=llm_overrides,
            limit=args.limit_per_profile,
            fresh=args.fresh,
            llm_call_timeout_s=args.llm_call_timeout_s,
            text_source=args.text_source,
            concurrency=max(1, args.concurrency),
            chunked_pdf=args.chunked_pdf,
            chunk_chars=args.chunk_chars,
            chunk_overlap_chars=args.chunk_overlap_chars,
            exclude_cited_estimates=args.exclude_cited_estimates,
        )
        for _, row in rows.iterrows()
    ]
    summary = pd.DataFrame(summaries)
    suffix = f"{args.input_mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    csv_path = args.out_root / f"direct_baseline_summary_{suffix}.csv"
    latest_path = args.out_root / f"direct_baseline_summary_{args.input_mode}_latest.csv"
    md_path = args.out_root / f"direct_baseline_summary_{args.input_mode}_latest.md"
    summary.to_csv(csv_path, index=False)
    summary.to_csv(latest_path, index=False)
    _write_markdown(summary, md_path)
    print(summary.to_string(index=False))
    print(f"Wrote {csv_path}")
    print(f"Wrote {latest_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
