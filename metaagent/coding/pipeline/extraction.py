from __future__ import annotations

import json
import re
import sys
import shutil
import traceback
from pathlib import Path

from metaagent.coding.llm import init_llm
from metaagent.coding.shared.io import infer_pmid_from_path, iter_markdown_files, read_text
from metaagent.coding.export.exporters import export_records
from metaagent.coding.parsing import parse_json_records
from metaagent.coding.fulltext_processor import process_fulltext
from metaagent.coding.schema.config_loader import load_config, ProjectConfig
from metaagent.coding.schema.prompt_factory import (
    build_full_context_system_prompt,
    build_full_context_user_prompt,
)


def _parse_json_object(text: str) -> dict:
    records = parse_json_records(text)
    if records:
        return records[0]
    return {}


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "metaagent").is_dir():
            return parent
    return current.parents[3]


def _paper_pool_dirs() -> tuple[Path, Path]:
    base = _repo_root() / "paper_pool"
    pdf_dir = base / "pdfs"
    md_dir = base / "markdown"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)
    return pdf_dir, md_dir


def _ensure_tools_on_path() -> None:
    tools_dir = _repo_root() / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))


FETCH_STRATEGIES = ("pmc_only", "pmc_scihub", "pmc_scihub_manual")


def _fetch_missing_pmids(
    pmids: list[str],
    pdf_dir: Path,
    fetch_strategy: str = "pmc_only",
) -> list[str]:
    """Download PDFs for PMIDs not already in pdf_dir.

    fetch_strategy:
      pmc_only          — PMC OA only; skip if no PMCID (default, safe)
      pmc_scihub        — PMC first, then Sci-Hub via DOI fallback
      pmc_scihub_manual — as above, plus interactive prompt when automated fails
    """
    if not pmids:
        return []
    _ensure_tools_on_path()
    try:
        from paper_fetch.pdf_fetcher import SciHubUrlExtractor  # type: ignore
    except Exception as exc:
        print(f"[WARN] Unable to import pdf_fetcher: {exc}")
        return pmids

    extractor = SciHubUrlExtractor()
    if fetch_strategy != "pmc_only":
        extractor.get_mirrors()

    allow_interactive = fetch_strategy == "pmc_scihub_manual"
    still_missing = []

    for pmid in pmids:
        target = pdf_dir / f"PMID_{pmid}.pdf"
        if target.exists():
            continue

        try:
            if fetch_strategy == "pmc_only":
                _, resolved_pmcid = extractor._resolve_pmid(pmid)
                if not resolved_pmcid:
                    print(f"  [SKIP] PMID {pmid}: no PMCID (pmc_only mode)")
                    still_missing.append(pmid)
                    continue
                url_results = extractor._process_pmcid(resolved_pmcid, pdf_dir)
            else:
                url_results, _, _ = extractor.process_pmid(
                    pmid,
                    download_dir=pdf_dir,
                    prefer_pmc=True,
                    allow_interactive=allow_interactive,
                )
        except Exception as exc:
            print(f"[WARN] PMID {pmid} fetch failed: {exc}")
            still_missing.append(pmid)
            continue

        downloaded = next((u for u in url_results if u.get("status") == "downloaded"), None)
        if downloaded:
            local_path = Path(downloaded.get("local_path", downloaded.get("url", "")))
            if local_path.exists() and local_path != target:
                try:
                    local_path.replace(target)
                except Exception:
                    shutil.copy2(local_path, target)
        if not target.exists():
            still_missing.append(pmid)

    return still_missing


def _markdown_cache_path(md_dir: Path, pmid: str) -> Path:
    return md_dir / f"PMID_{pmid}" / "fulltext.md"


def _load_markdown_from_pdf(pdf_path: Path, pmid: str) -> str:
    _ensure_tools_on_path()
    from tools.mineru.pdf_reader import extract_pdf_markdown_mineru  # type: ignore
    from metaagent.config import load_mineru_config  # type: ignore

    _, md_dir = _paper_pool_dirs()
    cache_path = _markdown_cache_path(md_dir, pmid)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")

    mineru_cfg = load_mineru_config(module_hint="coding")
    # Allow up to 10× the per-request timeout for the full parse cycle (default 600s)
    max_poll_s = max(600, mineru_cfg.timeout_s * 10)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    extract = extract_pdf_markdown_mineru(pdf_path, output_dir=cache_path.parent, max_poll_s=max_poll_s)
    cache_path.write_text(extract.markdown or "", encoding="utf-8")
    return extract.markdown or ""


def _iter_inputs(input_path: Path, fetch_strategy: str = "pmc_only"):
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        yield input_path
        return
    if input_path.is_file() and input_path.suffix.lower() == ".txt":
        pmids = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines()]
        pmids = [p for p in pmids if p and not p.startswith("#")]
        if not pmids:
            return
        pdf_dir, md_dir = _paper_pool_dirs()
        missing = []
        for pmid in pmids:
            pdf_path = pdf_dir / f"PMID_{pmid}.pdf"
            if pdf_path.exists():
                yield pdf_path
            elif _markdown_cache_path(md_dir, pmid).exists():
                yield _markdown_cache_path(md_dir, pmid)
            else:
                legacy_md = md_dir / f"PMID_{pmid}" / f"PMID_{pmid}.md"
                if legacy_md.exists():
                    yield legacy_md
                else:
                    missing.append(pmid)
        if missing:
            print(f"[INFO] {len(missing)} PDF(s) not cached — fetching (strategy: {fetch_strategy})")
            still_missing = _fetch_missing_pmids(missing, pdf_dir, fetch_strategy=fetch_strategy)
            if still_missing:
                print(f"[WARN] Still missing PDFs for {len(still_missing)} PMID(s) after fetch")
            # yield only the newly downloaded PDFs (avoid re-yielding those from first pass)
            newly_fetched = set(missing) - set(still_missing)
            for pmid in newly_fetched:
                pdf_path = pdf_dir / f"PMID_{pmid}.pdf"
                if pdf_path.exists():
                    yield pdf_path
        return
    if input_path.is_dir():
        pdfs = list(input_path.rglob("*.pdf"))
        if pdfs:
            for p in sorted(pdfs):
                yield p
            return
    # fallback to markdown
    for p in iter_markdown_files(input_path):
        yield p


def _load_prompt_sections(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    sections = {}
    for key in ("SYSTEM", "USER", "OUTPUT"):
        pattern = rf"{key}\s*=\s*\"\"\"(.*?)\"\"\""
        match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            sections[key.lower()] = match.group(1).strip()
    return sections


def _apply_prompt_override(config: ProjectConfig, prompt_path: Path) -> None:
    sections = _load_prompt_sections(prompt_path)
    if "system" in sections:
        config.prompt.system = sections["system"]
    if "user" in sections:
        config.prompt.user_preamble = sections["user"]
    if "output" in sections:
        config.prompt.output_rules = sections["output"]


def _apply_stage_prompt_from_codebook(
    effect_config: ProjectConfig, stage: str, target_config: ProjectConfig
) -> bool:
    raw = getattr(effect_config, "_raw_config", None)
    if not isinstance(raw, dict):
        return False
    stage_cfg = raw.get(stage)
    if not isinstance(stage_cfg, dict):
        return False

    base_path = getattr(effect_config, "_config_path", None)
    base_dir = Path(base_path).resolve().parent if base_path else Path.cwd()

    prompt_file = stage_cfg.get("prompt_file")
    if prompt_file:
        p = Path(str(prompt_file))
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        _apply_prompt_override(target_config, p)
        return True

    updated = False
    if stage_cfg.get("system"):
        target_config.prompt.system = stage_cfg["system"]
        updated = True
    if stage_cfg.get("user_preamble"):
        target_config.prompt.user_preamble = stage_cfg["user_preamble"]
        updated = True
    if stage_cfg.get("output_rules"):
        target_config.prompt.output_rules = stage_cfg["output_rules"]
        updated = True

    return updated


def _inject_codebook_context(index_config: ProjectConfig, effect_config: ProjectConfig) -> None:
    params = dict(getattr(index_config, "parameters", {}) or {})
    params.update(getattr(effect_config, "parameters", {}) or {})
    index_config.parameters = params

    codebook_notes = (getattr(effect_config, "notes", "") or "").strip()
    if codebook_notes:
        if index_config.notes:
            index_config.notes = (
                index_config.notes.rstrip()
                + "\n\n[Codebook Notes]\n"
                + codebook_notes
            )
        else:
            index_config.notes = codebook_notes


def _get_index_schema(effect_config: ProjectConfig) -> list[dict]:
    raw = getattr(effect_config, "_raw_config", None)
    if isinstance(raw, dict):
        schema = raw.get("index_schema")
        if isinstance(schema, list):
            return [s for s in schema if isinstance(s, dict)]
    return []


def _extract_by_path(data: dict, path: str):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _build_index_row(pmid: str, index_obj: dict, index_schema: list[dict]) -> dict:
    row = {"pmid": pmid}
    source = index_obj.get("index") if isinstance(index_obj.get("index"), dict) else index_obj
    for field in index_schema:
        name = field.get("name")
        path = field.get("path") or name
        if not name:
            continue
        if isinstance(path, str) and path.startswith("index."):
            path = path[len("index.") :]
        value = _extract_by_path(source, str(path))
        row[name] = value
    return row


def _write_paper_error(out_dir: Path, pmid: str, stage_name: str, exc: Exception) -> None:
    errors_dir = out_dir / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "pmid": pmid,
        "stage": stage_name,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(),
    }
    error_path = errors_dir / f"PMID_{pmid}.{stage_name}.error.json"
    error_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [ERROR] PMID {pmid}: {stage_name} failed ({type(exc).__name__}); wrote {error_path}")


def run_index(
    *,
    fulltext: str,
    tables_summary: str,
    was_truncated: bool,
    pmid: str,
    title: str,
    abstract: str,
    config: ProjectConfig,
    model,
) -> dict:
    system_text = build_full_context_system_prompt(config)
    user_text = build_full_context_user_prompt(
        config,
        title=title,
        abstract=abstract,
        full_text=fulltext,
        tables_summary=tables_summary,
        was_truncated=was_truncated,
        context_section=None,
    )
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    resp = model.invoke(messages)
    return _parse_json_object(resp.content)


def run_extract(
    *,
    fulltext: str,
    tables_summary: str,
    was_truncated: bool,
    title: str,
    abstract: str,
    index_json: str,
    config: ProjectConfig,
    model,
) -> list[dict]:
    system_text = build_full_context_system_prompt(config)
    context_section = "## Study Index (Stage A)\n" + index_json
    user_text = build_full_context_user_prompt(
        config,
        title=title,
        abstract=abstract,
        full_text=fulltext,
        tables_summary=tables_summary,
        was_truncated=was_truncated,
        context_section=context_section,
    )
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    resp = model.invoke(messages)
    return parse_json_records(resp.content)


def run_pipeline(
    input_path: Path,
    out_dir: Path,
    stage: str,
    codebook_path: Path,
    fetch_strategy: str = "pmc_only",
    llm_overrides: dict[str, object] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 0: fetch-only ──────────────────────────────────────────────────
    # Download missing PDFs and warm the MinerU markdown cache.
    # No LLM calls; useful as a pre-flight before a full extraction run.
    if stage == "fetch":
        inputs = list(_iter_inputs(input_path, fetch_strategy=fetch_strategy))
        pdf_dir, md_dir = _paper_pool_dirs()
        cached = warmed = 0
        for path in inputs:
            pmid = infer_pmid_from_path(path) or path.stem
            cache = _markdown_cache_path(md_dir, pmid)
            if cache.exists():
                cached += 1
                print(f"  [MD cache] PMID_{pmid} ✓")
            else:
                print(f"  [MinerU]   PMID_{pmid} — parsing…")
                _load_markdown_from_pdf(path, pmid)
                warmed += 1
        print(f"\n[fetch] Done. PDF={len(inputs)}  MD cached={cached}  MinerU parsed={warmed}")
        return

    # ── Phase 1+2: LLM extraction ────────────────────────────────────────────
    index_dir = out_dir / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    model = init_llm(llm_overrides)
    # Stage-A schema and prompt fallbacks live in the disease's coding_prompts/
    # dir, derived from the codebook path (configs/{disease}/codebooks/*.yaml ->
    # configs/{disease}/coding_prompts/). Avoids hardcoding a path that breaks
    # whenever this module is relocated.
    prompts_dir = codebook_path.resolve().parents[1] / "coding_prompts"
    stage_a_schema = prompts_dir / "stage_a.yaml"
    if not stage_a_schema.exists():
        raise FileNotFoundError(
            f"Stage-A schema not found at {stage_a_schema}. Expected the codebook "
            f"at configs/<disease>/codebooks/<param>.yaml so its sibling "
            f"coding_prompts/ dir can be derived; got codebook_path={codebook_path}."
        )
    stage_a_config = load_config(stage_a_schema)
    effect_config = load_config(codebook_path)
    applied_b = _apply_stage_prompt_from_codebook(effect_config, "stage_b", effect_config)
    if not applied_b:
        _apply_prompt_override(effect_config, prompts_dir / "stage_b.py")
    applied_a = _apply_stage_prompt_from_codebook(effect_config, "stage_a", stage_a_config)
    if not applied_a:
        _apply_prompt_override(stage_a_config, prompts_dir / "stage_a.py")
    _inject_codebook_context(stage_a_config, effect_config)
    records: list[dict] = []
    index_rows: list[dict] = []
    errors: list[dict] = []
    xlsx_path: Path | None = None

    inputs = list(_iter_inputs(input_path, fetch_strategy=fetch_strategy))
    if not inputs:
        print(f"[WARN] No input files found for: {input_path}")
        return

    for path in inputs:
        if path.suffix.lower() == ".pdf":
            pmid = infer_pmid_from_path(path) or path.stem
            markdown = _load_markdown_from_pdf(path, pmid)
        else:
            pmid = infer_pmid_from_path(path) or path.stem
            markdown = read_text(path)

        max_chars = effect_config.extraction.max_input_chars
        trunc_marker = effect_config.extraction.truncation_marker
        processed = process_fulltext(markdown, max_chars=max_chars, truncation_marker=trunc_marker)
        fulltext = processed.content
        tables_summary = processed.tables_summary

        title = f"PMID {pmid}"
        abstract = ""

        if stage in ("index", "extract", "both"):
            index_path = index_dir / f"PMID_{pmid}.index.json"
            if index_path.exists():
                index_envelope = json.loads(index_path.read_text(encoding="utf-8"))
                index_obj = index_envelope.get("index", index_envelope)
                print(f"  [Index] PMID {pmid}: reusing existing index")
            else:
                try:
                    index_obj = run_index(
                        fulltext=fulltext,
                        tables_summary=tables_summary,
                        was_truncated=processed.was_truncated,
                        pmid=pmid,
                        title=title,
                        abstract=abstract,
                        config=stage_a_config,
                        model=model,
                    )
                    index_payload = index_obj.get("index") if isinstance(index_obj, dict) else None
                    index_envelope = {"pmid": pmid, "index": index_payload or index_obj}
                    index_path.write_text(
                        json.dumps(index_envelope, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    _write_paper_error(out_dir, pmid, "index", exc)
                    errors.append({"pmid": pmid, "stage": "index", "error": str(exc)})
                    continue
            index_schema = _get_index_schema(effect_config)
            if index_schema:
                index_rows.append(_build_index_row(pmid, index_envelope, index_schema))
        else:
            index_obj = {}

        if stage in ("extract", "both"):
            index_json = json.dumps(index_obj, ensure_ascii=False)
            try:
                record_objs = run_extract(
                    fulltext=fulltext,
                    tables_summary=tables_summary,
                    was_truncated=processed.was_truncated,
                    title=title,
                    abstract=abstract,
                    index_json=index_json,
                    config=effect_config,
                    model=model,
                )
            except Exception as exc:
                _write_paper_error(out_dir, pmid, "extract", exc)
                errors.append({"pmid": pmid, "stage": "extract", "error": str(exc)})
                continue
            if not record_objs:
                print(f"  [WARN] PMID {pmid}: Stage B returned 0 records")
            for record_obj in record_objs or []:
                pmid_value = str(record_obj.get("pmid", "")).strip().upper()
                if "pmid" not in record_obj or pmid_value in {"", "NR", "NA", "N/A", "NONE", "NULL"}:
                    record_obj["pmid"] = pmid
                records.append(record_obj)

    if records:
        xlsx_path, _ = export_records(
            records,
            out_dir,
            basename="coding_sheet",
            column_order=[f.name for f in effect_config.fields] if effect_config.fields else None,
        )

    _ensure_tools_on_path()
    from metaagent.config import load_llm_config, load_mineru_config  # type: ignore
    from tools.provenance import write_run_manifest  # type: ignore

    llm_cfg = load_llm_config(llm_overrides, module_hint="coding")
    mineru_cfg = load_mineru_config(module_hint="coding")
    manifest_path = write_run_manifest(
        output_dir=out_dir,
        workflow="coding_sheet_extraction",
        module="coding_sheet",
        params={
            "stage": stage,
            "codebook": str(codebook_path.resolve()),
            "stage_a_config": str(getattr(stage_a_config, "_config_path", "")),
        },
        inputs=[input_path, codebook_path, getattr(stage_a_config, "_config_path", "")],
        outputs=[out_dir, index_dir, xlsx_path] if xlsx_path else [out_dir, index_dir],
        runtime={
            "llm": {
                "provider": llm_cfg.provider,
                "model": llm_cfg.model,
                "api_base": llm_cfg.api_base,
                "timeout_s": llm_cfg.timeout_s,
                "verify_ssl": llm_cfg.verify_ssl,
                "has_api_key": bool(llm_cfg.api_key),
            },
            "mineru": {
                "base_url": mineru_cfg.base_url,
                "endpoint": mineru_cfg.endpoint,
                "timeout_s": mineru_cfg.timeout_s,
                "has_api_key": bool(mineru_cfg.api_key),
            },
        },
        extra={
            "input_count": len(inputs),
            "record_count": len(records),
            "index_row_count": len(index_rows),
            "error_count": len(errors),
            "errors": errors,
            "input_files": [str(p) for p in inputs],
            "xlsx_path": str(xlsx_path) if xlsx_path else None,
        },
    )
    print(f"[OK] Manifest written: {manifest_path}")
