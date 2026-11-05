"""Executable review stages with content-addressed, label-free provenance.

The runner never reads ground_truth, source_inventory or coding_reference. Imported
candidate sets must be selected explicitly; natural retrieval is the default.
"""
from __future__ import annotations

import asyncio
import contextlib
import csv
import hashlib
import json
import os
import re
import shutil
import uuid
from time import perf_counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from metaagent.config import normalize_api_base
from tools.mineru.cache import pool_root

STAGES = ("retrieval", "screening", "fulltext_fetch", "fulltext_screening", "coding", "pooling")
VERSION = "2"


class WorkflowRunError(RuntimeError):
    def __init__(self, message: str, manifest: dict):
        super().__init__(message)
        self.manifest = manifest


@dataclass
class WorkflowOptions:
    profile: str
    dataset_root: Path
    output_dir: Path
    project_root: Path | None = None
    start_at: str = "retrieval"
    stop_after: str = "pooling"
    input_mode: str = "search"
    raw_input: Path | None = None
    query: str | None = None
    model: str | None = None
    api_base: str | None = None
    api_key_env: str = "WORKFLOW_LLM_API_KEY"
    limit: int | None = None
    resume: bool = True
    batch_size: int = 20
    batch_concurrency: int = 1
    batch_mode: str = "single"
    strategy: str = "5d"
    fetch_mode: str = "pmc_only"
    codebook: Path | None = None
    parameter_type: str | None = None
    estimate_measure: str = "mean"
    pooling_method: str = "random"
    temperature: float | None = None
    extraction_backend: str | None = None
    skip_fulltext_screening: bool = False
    start_date: str | None = None
    end_date: str | None = None
    task_config: Path | None = None
    analysis_protocol: Path | None = None
    ablation: str = "full"
    document_manifest: Path | None = None
    estimates_input: Path | None = None
    chunk_chars: int | None = None
    stage_a_empty_retries: int | None = None
    synthesis_backend: str | None = None
    research_question: str | None = None
    method_sources: tuple[Path, ...] = ()
    synthesis_max_executions: int | None = None
    synthesis_max_turns: int | None = None
    synthesis_max_tokens: int | None = None
    synthesis_total_timeout_s: int | None = None
    synthesis_exec_timeout_s: int | None = None
    pi_command: str | None = None


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def read_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").split("\n") if line.strip()]
    elif path.suffix.lower() == ".json":
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = obj if isinstance(obj, list) else obj.get("records", [])
    else:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    normalized = normalize_records(rows)
    for row in normalized:
        if row.get("fulltext_path") and not Path(row["fulltext_path"]).is_absolute():
            row["fulltext_path"] = str((path.resolve().parent / row["fulltext_path"]).resolve())
        for source in row.get("supplements") or []:
            if source.get("path") and not Path(source["path"]).is_absolute():
                source["path"] = str((path.resolve().parent / source["path"]).resolve())
    return normalized


def normalize_records(rows: list[dict]) -> list[dict]:
    """Normalize bibliographic exports without sending provenance/labels to LLMs."""
    normalized = []
    seen = set()
    for original in rows:
        # Whitelist bibliographic inputs: reference values and eligibility labels
        # cannot enter prompts through an imported coding benchmark file.
        lower = {str(k).lower(): v for k, v in original.items()}
        row = {key: lower.get(key, "") for key in (
            "record_id", "pmid", "doi", "pmcid", "title", "official_title", "abstract", "keywords",
            "authors", "citation", "journal/book", "publication year", "pub_types",
            "mesh_terms", "fulltext_url", "fulltext_path", "fulltext_source_url", "fulltext_access", "url",
            "pdf_path", "pdf_url", "download_url", "preprint_version", "source_version", "version", "version_date", "preprint_server")}
        aliases = {
            "language": ("language", "languages"), "publication_date": ("publication_date", "publication date", "date"),
            "year": ("year", "publication year", "publication_year"), "journal": ("journal", "journal/book"),
            "mesh_terms": ("mesh_terms", "mesh_headings", "mesh", "mesh headings"),
            "pub_types": ("pub_types", "publication_types", "publication types"),
            "report_version_id": ("report_version_id",),
        }
        for target, names in aliases.items():
            row[target] = next((lower[name] for name in names if lower.get(name) not in (None, "")), "")
        for key in row:
            value = row[key]
            row[key] = value.strip() if isinstance(value, str) else value if isinstance(value, (list, dict)) else str(value or "").strip()
        for key in ("record_id", "pmid", "doi", "pmcid", "fulltext_path", "pdf_path", "url", "fulltext_url", "pdf_url", "download_url", "source_version", "preprint_version", "version", "version_date"):
            if isinstance(row[key], (list, dict)):
                raise ValueError(f"Bibliographic identity/path must be scalar: {key}")
        row["publication year"] = row["year"]
        row["journal/book"] = row["journal"]
        for key in ("source", "sources", "source_records", "origin_route", "origin_routes", "search_run_ids", "retrieved_by_search", "is_public_fulltext", "public_fulltext", "native_database", "native_export_sha256", "supplements", "fulltext_coverage"):
            if key in lower:
                row[key] = lower[key]
        row["pmid"] = row["pmid"].removeprefix("pubmed:")
        if not row["pmid"].isdigit():
            row["pmid"] = ""
        row["record_id"] = row["record_id"] or ("pmid:" + row["pmid"] if row["pmid"] else "doi:" + row["doi"] if row["doi"] else "record:" + _hash(row)[:20])
        if row["record_id"] in seen:
            raise ValueError(f"Duplicate record_id in input: {row['record_id']}")
        seen.add(row["record_id"])
        for source, target in (("pmid", "PMID"), ("doi", "DOI"), ("pmcid", "PMCID"), ("title", "Title"), ("abstract", "Abstract"), ("keywords", "Keywords"), ("authors", "Authors"), ("citation", "Citation"), ("journal/book", "Journal/Book")):
            row[target] = row[source]
        normalized.append(row)
    return normalized


def _jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows), encoding="utf-8")


def _load_jsonl(path: str | Path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").split("\n") if line.strip()]


def _context(o: WorkflowOptions) -> dict:
    from metaagent.screening.profile_registry import resolve_profile_context
    root = Path(o.project_root or Path(__file__).resolve().parents[1]).resolve()
    dataset = Path(o.dataset_root).expanduser().resolve()
    if o.task_config:
        from metaagent.workflow_task import read_task, resolve_synthesis
        path = Path(o.task_config).resolve()
        task = read_task(path)
        cb = Path(o.codebook) if o.codebook else path.parent / task.codebook
        analysis = task.analysis_protocols or task.analysis_protocol
        if o.analysis_protocol:
            import yaml
            analysis = yaml.safe_load(Path(o.analysis_protocol).read_text())
        return dict(root=root, dataset=dataset, task_dir=path.parent, profile=task.task_id,
                    disease=task.disease, topic=task.topic, codebook=cb.resolve(),
                    parameter_type=o.parameter_type or (analysis[0] if isinstance(analysis, list) and analysis else analysis or {}).get("parameter_type") or task.topic,
                    screening_config={"research_question": task.research_question,
                                      "review_protocol": task.review_protocol},
                    start_date=o.start_date or task.start_date, end_date=o.end_date or task.end_date,
                    source_queries=task.search, analysis_protocol=analysis,
                    synthesis_settings=resolve_synthesis(o, task=task, task_dir=path.parent))
    with (dataset / "profiles.csv").open(encoding="utf-8-sig", newline="") as handle:
        matches = [r for r in csv.DictReader(handle) if r["profile"].upper() == o.profile.upper()]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {o.profile} in {dataset / 'profiles.csv'}")
    row = matches[0]
    # Resolve the known profile only for domain policies, never its legacy data paths.
    profile = resolve_profile_context(o.profile)
    relative = Path(row["path"])
    if relative.is_absolute():
        task_dir = relative
    elif (dataset / relative).exists():
        task_dir = dataset / relative
    elif (root / relative).exists():
        task_dir = root / relative
    else:
        task_dir = dataset / "profiles" / o.profile.upper()
    task = {}
    for name in ("project.json", "task.json"):
        if (task_dir / name).exists():
            task.update(json.loads((task_dir / name).read_text()))
    disease = row.get("disease") or profile.disease_key
    topic = row.get("topic") or task.get("topic") or profile.topic_key
    config = profile.to_screening_config()
    config.update({"disease": disease, "topic": topic})
    for key in ("research_question", "disease_focus", "disease_exclude", "parameter_focus", "parameter_exclude", "policies", "thresholds"):
        if task.get(key) is not None:
            config[key] = task[key]
    if topic != profile.topic_key:
        # Corrected v2 endpoints must not inherit the old parameter prompt.
        config["research_question"] = task.get("research_question") or f"What is the {topic.replace('_', ' ')} of {disease}?"
        config["parameter_focus"] = task.get("parameter_focus") or topic.replace("_", " ")
        config["parameter_exclude"] = task.get("parameter_exclude") or "studies reporting only other parameters"
    cb = Path(o.codebook).resolve() if o.codebook else root / "configs" / disease / "codebooks" / f"{topic}.yaml"
    param = o.parameter_type or task.get("parameter_type") or {"reproduction_number": "R0", "serial_interval": "serial_interval", "incubation_period": "incubation_period", "fatality": "CFR"}.get(topic, topic)
    param = {"basic_reproduction_number": "R0", "case_fatality_rate": "CFR", "infection_fatality_rate": "IFR"}.get(param, param)
    scope = task.get("endpoint_constraints")
    if scope:
        config["research_question"] += f" Review-specific scope: {scope}."
    analysis = task.get("analysis_protocol")
    if o.analysis_protocol:
        import yaml
        analysis = yaml.safe_load(Path(o.analysis_protocol).read_text())
    if task.get("review_protocol"):
        config["review_protocol"] = task["review_protocol"]
    legacy = task.get("v1_project") or {}
    from metaagent.workflow_task import resolve_synthesis
    return dict(root=root, dataset=dataset, task_dir=task_dir, profile=row["profile"], disease=disease, topic=topic,
                screening_config=config, codebook=cb, parameter_type=param, analysis_protocol=analysis, source_queries={},
                synthesis_source_review={"pmid": task.get("source_review_pmid"), "title": task.get("source_review_title")},
                synthesis_settings=resolve_synthesis(o, task=task, task_dir=task_dir,
                                                     research_question=config.get("research_question")),
                start_date=o.start_date or row.get("query_date_from") or task.get("query_date_from") or legacy.get("query_date_from"),
                end_date=o.end_date or row.get("query_date_to") or task.get("query_date_to") or legacy.get("query_date_to"))


def _input_path(o, ctx):
    if o.raw_input:
        return Path(o.raw_input).expanduser().resolve()
    if o.input_mode == "search":
        return None
    stem = o.input_mode
    for name in (stem + ".jsonl", stem + ".csv", "raw.csv" if stem == "raw_pool" else stem + ".json"):
        path = ctx["task_dir"] / name
        if path.exists():
            return path
    raise ValueError(f"No {stem} file found; pass --raw-input explicitly")


def plan_workflow(o: WorkflowOptions) -> dict:
    if o.estimates_input and o.document_manifest:
        raise ValueError("--estimates-input and --document-manifest are mutually exclusive")
    if o.estimates_input and o.start_at != "pooling":
        raise ValueError("--estimates-input requires --start-at pooling")
    if o.document_manifest and o.start_at not in {"coding","fulltext_screening"}:
        raise ValueError("--document-manifest starts at coding or fulltext_screening")
    if o.start_at not in STAGES or o.stop_after not in STAGES or STAGES.index(o.start_at) > STAGES.index(o.stop_after):
        raise ValueError("Invalid workflow stage range")
    if o.input_mode not in {"search", "raw_search", "raw_pool"}:
        raise ValueError("input_mode must be search, raw_search or raw_pool")
    if o.raw_input and o.input_mode == "search":
        raise ValueError("--raw-input requires explicit --input-mode raw_search or raw_pool")
    if o.fetch_mode != "pmc_only":
        raise ValueError("Only lawful public PMC retrieval (pmc_only) is supported")
    if o.extraction_backend not in {None, "llm", "langextract"}:
        raise ValueError("extraction_backend must be llm or langextract")
    if o.limit is not None and o.limit < 1:
        raise ValueError("limit must be positive")
    if o.batch_size < 1 or o.batch_concurrency < 1:
        raise ValueError("Batch size and concurrency must be positive")
    if o.batch_mode not in {"single", "multi"}:
        raise ValueError("batch_mode must be single or multi")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", o.api_key_env):
        raise ValueError("api_key_env must be an environment variable name")
    if o.ablation not in {"full", "without_a", "without_b"}:
        raise ValueError("Unknown coding ablation")
    ctx = _context(o)
    if not o.task_config and Path(o.output_dir).expanduser().resolve().is_relative_to(ctx["dataset"]):
        raise ValueError("output_dir must be outside the input dataset root")
    path = _input_path(o, ctx)
    if path and not path.is_file():
        raise ValueError(f"Input file not found: {path}")
    selected = list(STAGES[STAGES.index(o.start_at):STAGES.index(o.stop_after)+1])
    synthesis_settings = ctx["synthesis_settings"]
    synthesis_inspection = None
    if "pooling" in selected and synthesis_settings["backend"] == "pi":
        from metaagent.workflow_task import inspect_synthesis_settings
        synthesis_inspection = inspect_synthesis_settings(synthesis_settings)
        if isinstance(ctx.get("analysis_protocol"), list) and len(ctx["analysis_protocol"]) != 1:
            raise ValueError("Pi synthesis accepts one optional protocol; describe multiple analyses in the research question")
        from metaagent.synthesis.pi_agent import pi_synthesis_fingerprint
        from metaagent.workflow_task import resolve_runtime
        configured = ctx.get("analysis_protocol")
        synthesis_inspection["agent"] = pi_synthesis_fingerprint(
            **({"input_path": Path(o.estimates_input)} if o.estimates_input else {"records": []}),
            research_question=synthesis_settings["research_question"],
            review_context=ctx["screening_config"].get("review_protocol"),
            method_sources=[Path(value) for value in synthesis_settings["method_sources"]],
            protocol=configured[0] if isinstance(configured, list) else configured,
            settings=synthesis_settings,
            runtime_overrides=resolve_runtime(o, "synthesis")[0])
        synthesis_inspection["input_pending"] = o.estimates_input is None
    # Fingerprint all prompts/schemas and implementation dependencies; no mtimes.
    files = [Path(o.task_config).resolve()] if o.task_config else [ctx["dataset"] / "profiles.csv"]
    for additional in (o.analysis_protocol, o.document_manifest, o.estimates_input):
        if additional:
            files.append(Path(additional).resolve())
    if synthesis_inspection:
        files.extend(Path(value) for value in synthesis_settings["method_sources"])
    if o.document_manifest:
        from metaagent.coding.pipeline.extraction import load_document_manifest
        for record in load_document_manifest(Path(o.document_manifest)):
            sources = [{"path": record.get("path") or record.get("fulltext_path")}, *(record.get("supplements") or [])]
            for source in sources:
                if source.get("path"):
                    local = Path(source["path"])
                    if not local.is_absolute():
                        local = Path(o.document_manifest).resolve().parent / local
                    if local.is_file():
                        files.append(local.resolve())
    if path:
        for record in read_records(path):
            local_text = record.get("fulltext_path")
            if local_text and Path(local_text).expanduser().is_file():
                files.append(Path(local_text).expanduser().resolve())
    files.extend(ctx["task_dir"] / n for n in ("project.json", "task.json", "search_runs.jsonl") if (ctx["task_dir"] / n).is_file())
    for folder in (ctx["root"] / "configs" / ctx["disease"], ctx["root"] / "metaagent/prompts", ctx["root"] / "metaagent/screening", ctx["root"] / "metaagent/coding", ctx["root"] / "tools/analysis", ctx["root"] / "tools/mineru", ctx["root"] / "tools/literature", ctx["root"] / "metaagent/synthesis"):
        if folder.exists():
            files.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix in {".py", ".yaml", ".md", ".json"})
    files.extend([Path(__file__), Path(__file__).with_name("config.py"), Path(__file__).with_name("workflow_task.py"), Path(__file__).with_name("retrieval.py"), Path(__file__).with_name("documents.py"), Path(__file__).with_name("acquisition.py"), Path(__file__).with_name("evidence_search.py")])
    if Path(__file__).with_name("pmc_cloud.py").is_file():
        files.append(Path(__file__).with_name("pmc_cloud.py"))
    if Path(__file__).with_name("llm_rate_limit.py").is_file():
        files.append(Path(__file__).with_name("llm_rate_limit.py"))
    files.extend(p for p in (ctx["root"] / "tools/pubmed/client.py", ctx["root"] / "tools/pubmed/query_generator.py", ctx["root"] / "tools/pubmed/query_validation.py", ctx["root"] / "tools/pubmed/query_guide.md",
                             ctx["root"] / "tools/benchmark_v2/retrieve_public.py") if p.is_file())
    if ctx["codebook"].is_file():
        files.append(ctx["codebook"])
    runtime = {}
    from metaagent.workflow_task import resolve_runtime
    for module in ("query", "screening", "coding", "synthesis"):
        _, runtime[module] = resolve_runtime(o, module)
    extra_body_hashes = {module.upper() + "_LLM_EXTRA_BODY_JSON": public["extra_body_sha256"]
                         for module, public in runtime.items() if public.get("extra_body_sha256")}
    from metaagent.workflow_task import resolve_coding
    from tools.mineru.cache import parser_identity
    _,document_parser_fingerprint=parser_identity()
    coding_settings = resolve_coding(o)
    config = {"document_parser":{"fingerprint":document_parser_fingerprint,"cache_policy":os.environ.get("MINERU_CACHE_POLICY","compatible")},"coding_settings": coding_settings, "version": VERSION, "profile": ctx["profile"], "dataset_root": str(ctx["dataset"]),
              "disease": ctx["disease"], "topic": ctx["topic"], "screening_config": ctx["screening_config"],
              "coding_review_context": {"research_question": ctx["screening_config"].get("research_question"), "review_protocol": ctx["screening_config"].get("review_protocol")},
              "analysis_protocol": ctx.get("analysis_protocol"), "source_queries": ctx.get("source_queries", {}),
              "synthesis_settings": synthesis_settings, "synthesis_inspection": synthesis_inspection,
              "synthesis_source_review": ctx.get("synthesis_source_review"),
              "document_acquisition": {"require_pdf": True, "cache_policy": "strict"},
              "ablation": o.ablation, "chunk_chars": o.chunk_chars, "input_mode": o.input_mode, "model": o.model, "api_base": normalize_api_base(o.api_base, append_version=True),
              "api_key_env": o.api_key_env, "limit": o.limit, "query": o.query,
              "start_date": ctx["start_date"], "end_date": ctx["end_date"], "batch_size": o.batch_size,
              "batch_concurrency": o.batch_concurrency, "batch_mode": o.batch_mode, "strategy": o.strategy, "fetch_mode": o.fetch_mode,
              "codebook": str(ctx["codebook"]), "parameter_type": ctx["parameter_type"],
              "estimate_measure": o.estimate_measure, "pooling_method": o.pooling_method, "temperature": o.temperature,
              "extraction_backend": o.extraction_backend, "skip_fulltext_screening": o.skip_fulltext_screening,
              "paper_pool": str(pool_root()),
              "effective_llm_runtime": runtime,
              "extra_body_sha256": extra_body_hashes,
              "runtime_environment": {key: os.environ.get(key) for key in (
                  "CODING_LLM_MAX_RETRIES", "CODING_LLM_SUBPROCESS_TIMEOUT_S", "CODING_LLM_CALL_TIMEOUT_S",
                  "CODING_MAX_INPUT_CHARS", "CODING_LLM_MAX_INPUT_CHARS", "LLM_MAX_RETRIES",
                  "METAAGENT_LLM_REQUESTS_PER_MINUTE", "METAAGENT_LLM_RATE_STATE_PATH")},
              "dependency_hashes": {str(p): file_hash(p) for p in sorted(set(files))}}
    return {"schema_version": VERSION, "profile": ctx["profile"], "stages": selected,
            "config": config, "config_sha256": _hash(config), "input": str(path) if path else None,
            "input_sha256": file_hash(path) if path else None, "output_dir": str(Path(o.output_dir).resolve()),
            "pool_kind": {"search": "natural_search", "raw_search": "frozen_natural_search", "raw_pool": "explicit_augmented_pool"}[o.input_mode],
            "retrieval_scope": "task source-specific queries (bounded outside PubMed)" if ctx.get("source_queries") else "PubMed adapter only; other sources not executed",
            "search_runs_provenance": str(ctx["task_dir"] / "search_runs.jsonl") if (ctx["task_dir"] / "search_runs.jsonl").is_file() else None,
            "codebook_exists": ctx["codebook"].is_file(), "dry_run": True}


def _llm_params(o, module="screening"):
    from metaagent.workflow_task import resolve_runtime
    return resolve_runtime(o, module, require_credentials=True)[0]


def _screen_rows(rows, o, ctx, *, fulltext=False, directory=None):
    if not rows:
        return rows
    from metaagent.screening.engine import init_llm_model, screen_papers_batch_async
    to_screen = rows
    rescue = ctx["screening_config"].get("policies", {}).get("fulltext_rescue", {})
    if not fulltext and rescue.get("enabled") and rescue.get("when_no_abstract"):
        to_screen = []
        for row in rows:
            if str(row.get("Abstract") or "").strip():
                to_screen.append(row)
            else:
                row.update(record_status="awaiting_fulltext", llm_suggest="needs_full_text", screening_stage="pending_fulltext")
    if not to_screen:
        return rows
    model = init_llm_model(config_overrides=_llm_params(o))
    asyncio.run(screen_papers_batch_async(to_screen, ctx["screening_config"]["research_question"], model,
        batch_size=o.batch_size, batch_concurrency=o.batch_concurrency, batch_mode=o.batch_mode, screening_config={**ctx["screening_config"], **({"call_log":str(directory / "llm_calls.jsonl")} if directory else {})},
        screening_stage="full_text" if fulltext else "title_abstract", content_key="fulltext" if fulltext else "Abstract",
        content_label="Full text" if fulltext else "Abstract", strategy=o.strategy))
    for row in to_screen:
        from metaagent.screening.cli import _screening_row_tier
        row["record_status"] = "screened" if _screening_row_tier(row) in {"S", "P", "U"} else "error"
        if fulltext and (row.get("protocol_decision", {}).get("route") == "review"
                         or row.get("screening_requires_review")
                         or row.get("screening_budget", {}).get("status") == "pending_source_budget"):
            row["record_status"] = "eligibility_pending"
            row["fulltext_eligible"] = None
    return rows


def _retained(row):
    from metaagent.screening.cli import _screening_row_tier
    return _screening_row_tier(row) in {"S", "P"} or row.get("llm_suggest") == "needs_full_text"


def _inline_xml(element) -> str:
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def jats_to_markdown(root) -> str:
    """Render JATS paragraphs and table grids, including merged header cells."""
    def tag(node):
        return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""

    def table(node):
        rows, pending = [], {}
        for tr in (x for x in node.iter() if tag(x) == "tr"):
            cells = {}
            for column, (value, remaining) in list(pending.items()):
                cells[column] = value
                if remaining <= 1:
                    del pending[column]
                else:
                    pending[column] = (value, remaining - 1)
            column = 0
            for cell in tr:
                if tag(cell) not in {"td", "th"}:
                    continue
                while column in cells:
                    column += 1
                value = _inline_xml(cell).replace("|", "\\|")
                span = max(1, int(cell.get("colspan", "1")))
                rowspan = max(1, int(cell.get("rowspan", "1")))
                for offset in range(span):
                    cells[column + offset] = value
                    if rowspan > 1:
                        pending[column + offset] = (value, rowspan - 1)
                column += span
            rows.append(cells)
        if not rows:
            return _inline_xml(node)
        width = max(max(row, default=-1) for row in rows) + 1
        grid = [[row.get(i, "") for i in range(width)] for row in rows]
        lines = ["| " + " | ".join(row) + " |" for row in grid]
        lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
        return "\n".join(lines)

    def render(node, level=2):
        name = tag(node)
        if name == "table":
            return table(node)
        if name == "table-wrap":
            blocks = []
            for child in node:
                if tag(child) in {"label", "caption"}:
                    blocks.append("**" + _inline_xml(child) + "**")
                elif tag(child) == "table":
                    blocks.append(table(child))
                else:
                    blocks.append(render(child, level))
            return "\n\n".join(x for x in blocks if x)
        if name == "title":
            return "#" * min(level, 6) + " " + _inline_xml(node)
        if name in {"p", "list-item", "disp-formula", "fn", "label"}:
            text = _inline_xml(node)
            return ("- " if name == "list-item" else "") + text
        return "\n\n".join(text for child in node if (text := render(child, level + (name == "sec"))))

    body = next((node for node in root.iter() if tag(node) == "body"), None)
    if body is None:
        raise ValueError("PMC XML has no article body")
    return render(body).strip()


def _provided_public_fulltext(row, directory):
    """Use explicitly supplied public primary documents, never review evidence URLs."""
    import requests
    record = dict(row)
    local = row.get("fulltext_path")
    public = row.get("fulltext_access") == "public" or row.get("is_public_fulltext") is True or row.get("public_fulltext") is True
    url = row.get("fulltext_url")
    content, source = None, None
    if local and public:
        source = Path(local).expanduser().resolve()
        if not source.is_file():
            return {**record, "record_status": "fulltext_unavailable", "failure_reason": "provided_local_document_missing"}
        content = source.read_bytes()
        suffix = source.suffix.lower()
    elif url:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return {**record, "record_status": "fulltext_unavailable", "failure_reason": "invalid_public_fulltext_url"}
        response = requests.get(url, timeout=60)
        if response.status_code != 200:
            return {**record, "record_status": "fulltext_unavailable", "failure_reason": f"provided_public_url_http_{response.status_code}"}
        content, source = response.content, url
        suffix = Path(parsed.path).suffix.lower()
        if content.startswith(b"%PDF"):
            suffix = ".pdf"
    else:
        return None
    token = _hash(record["record_id"])[:20]
    original = directory / f"{token}.source{suffix}"
    original.write_bytes(content)
    parse_route = "provided_structured_text"
    if suffix == ".pdf":
        from tools.mineru.cache import parse_pdf
        parsed = parse_pdf(original, str(row.get("pmid") or ""))
        text = parsed.text
        parse_route = parsed.route
    elif suffix == ".xml" or content.lstrip().startswith(b"<?xml"):
        text = jats_to_markdown(ET.fromstring(content))
    elif suffix in {".md", ".txt"}:
        text = content.decode("utf-8-sig")
    else:
        return {**record, "record_status": "fulltext_unavailable", "failure_reason": "public_url_not_supported_fulltext_format"}
    if not text.strip():
        return {**record, "record_status": "fulltext_unavailable", "failure_reason": "empty_public_fulltext"}
    output = directory / f"{token}.md"
    output.write_text(text, encoding="utf-8")
    return {**record, "record_status": "fulltext_ready", "fulltext_path": str(output),
            "source_url": str(source), "primary_document_source": str(source),
            "source_sha256": hashlib.sha256(content).hexdigest(), "fulltext_sha256": file_hash(output),
            "access_route": "provided_public_primary_document", "parser_route": parse_route,
            "failure_reason": None}


def _fetch_pmc(row, directory: Path) -> dict:
    """Compatibility adapter to the shared identity-bound PDF/MinerU route.

    A missing PDF remains an explicit acquisition failure. User-provided text is
    accepted by the shared resolver with pdf_status=not_provided, never as a PDF.
    """
    from metaagent.acquisition import resolve_document
    return resolve_document(row, directory, require_pdf=True, cache_policy="strict")


def _import_documents(path: Path, directory: Path) -> list[dict]:
    """Resolve declared identities without treating an empty path as a file."""
    from metaagent.coding.pipeline.extraction import load_document_manifest
    from metaagent.acquisition import resolve_document
    declared = load_document_manifest(path)
    directory.mkdir(parents=True, exist_ok=True)
    rows = normalize_records(declared)
    outcomes = []
    for row, document in zip(rows, declared):
        sources = [("main", document), *((s["source_id"], s) for s in document.get("supplements", []))]
        supplements, missing = [], []
        for source_id, source in sources:
            local = source.get("path")
            identity = {key: source[key] for key in (
                "pmid", "doi", "title", "fulltext_url", "url", "pdf_url", "download_url",
                "preprint_version", "source_version", "version", "version_date", "preprint_server") if source.get(key)}
            identity["record_id"] = row["record_id"] if source_id == "main" else row["record_id"] + ":supplement:" + source_id
            if source_id != "main":
                identity["role"] = source.get("role", "supplement")
            # An anonymous local upload has no external identity to verify. Keep
            # its explicit-user provenance; the ordinary shared parser handles it.
            anonymous_pdf = local and Path(local).suffix.lower() == ".pdf" and not (
                identity.get("pmid") or identity.get("doi") or identity.get("title")
                or identity["record_id"].startswith(("pmid:", "doi:")))
            if anonymous_pdf:
                frozen_pdf = directory / (_hash(identity["record_id"])[:20] + ".source.pdf")
                shutil.copyfile(local, frozen_pdf)
                outcome = {**identity, "record_status": "fulltext_ready", "fulltext_path": str(frozen_pdf),
                           "pdf_path": str(frozen_pdf), "primary_document_source": str(local), "pdf_status": "user_provided_unlabelled",
                           "source_sha256": file_hash(Path(local)), "pdf_sha256": file_hash(Path(local)),
                           "access_route": "explicit_user_pdf", "identity_verification": {"status": "not_asserted"}}
            else:
                if local:
                    identity["path"] = str(local)
                outcome = resolve_document(identity, directory, require_pdf=True, cache_policy="strict")
            outcomes.append({"parent_record_id": row["record_id"], "source_id": source_id, **outcome})
            if outcome.get("record_status") != "fulltext_ready":
                missing.append(source_id)
            if source_id == "main":
                row.update(outcome)
            else:
                supplements.append({**outcome, "path": outcome.get("fulltext_path"), "source_id": source_id,
                                    "role": source.get("role", "supplement")})
        row["supplements"] = supplements
        if missing:
            row.update(record_status="fulltext_unavailable", failure_reason="declared_source_unavailable")
            row["fulltext_coverage"] = {**(row.get("fulltext_coverage") or {}), "complete": False,
                                       "missing_materials": missing}
    _jsonl(directory / "acquisition_manifest.jsonl", outcomes)
    return rows


def _coding_records(artifacts: dict) -> list[dict]:
    if artifacts.get("coding_estimates"):
        return _load_jsonl(artifacts["coding_estimates"])
    from metaagent.synthesis.cli import read_estimates
    return read_estimates(Path(artifacts["coding_predictions"]))


def _bibliographic_identity(row: dict) -> dict:
    """Whitelist identities only; no scientific value, label or host file path."""
    identity = {key: row[key] for key in ("record_id", "pmid", "doi", "title", "preprint_version", "source_version", "version")
                if row.get(key) is not None and str(row[key]).strip()}
    for key in ("pmid", "doi", "title"):
        if key not in identity and row.get(key.upper() if key != "title" else "Title"):
            identity[key] = row[key.upper() if key != "title" else "Title"]
    return identity


def _identity_aliases(row: dict) -> set[str]:
    identity = _bibliographic_identity(row)
    aliases = {str(identity["record_id"])} if identity.get("record_id") else set()
    pmid = str(identity.get("pmid") or "").removeprefix("pubmed:").strip()
    if pmid.isdigit():
        aliases.add("pmid:" + pmid)
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", str(identity.get("doi") or ""), flags=re.I).strip().lower()
    if doi:
        version = str(identity.get("preprint_version") or identity.get("source_version") or identity.get("version") or "").lower()
        if not version:
            match = re.search(r":(v\d+)$", str(identity.get("record_id") or ""), re.I)
            version = match.group(1).lower() if match else ""
        if version.isdigit():
            version = "v" + version
        aliases.add("doi:" + doi + (":" + version if version else ""))
    return aliases


_PI_SOURCE_IDENTITY_POLICY = "explicit-bibliography-v2"


def _source_claims(row: dict, *, coding: bool) -> tuple[dict, list[str]]:
    """Normalize declarations for comparison, never repair conflicting identities."""
    values = {key: set() for key in ("pmid", "doi", "version", "title")}
    def doi(value):
        return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value).strip(), flags=re.I).lower().rstrip(".,;")
    def version(value):
        value = str(value).strip().lower()
        return "v" + value if value.isdigit() else value
    entries = [_bibliographic_identity(row)]
    if not coding:
        entries.append((row.get("identity_verification") or {}).get("expected") or {})
    for entry in entries:
        for field in ("pmid", "doi", "title"):
            if entry.get(field) is not None and str(entry[field]).strip():
                value = str(entry[field]).strip()
                value = doi(value) if field == "doi" else re.sub(r"^(?:pubmed:|pmid:)", "", value, flags=re.I) if field == "pmid" else re.sub(r"[\W_]+", "", value.casefold())
                values[field].add(value)
        for field in ("preprint_version", "source_version", "version"):
            if entry.get(field) is not None and str(entry[field]).strip():
                values["version"].add(version(entry[field]))
    record_id = str(row.get("record_id") or "")
    alias = re.match(r"^(?:doi|medrxiv|biorxiv):(10\..+)$", record_id, re.I)
    if alias:
        identifier = alias.group(1)
        tail = re.search(r":(v\d+)$", identifier, re.I)
        if tail:
            alias_version = version(tail.group(1))
            # A source's filename/record ID alone does not prove its version.
            if coding or values["version"]:
                values["version"].add(alias_version)
            identifier = identifier[:tail.start()]
        values["doi"].add(doi(identifier))
    pmid = re.fullmatch(r"(?:pmid|pubmed):(\d+)", record_id, re.I)
    if pmid:
        values["pmid"].add(pmid.group(1))
    conflicts = [field for field, declarations in values.items() if len(declarations) > 1]
    return {field: next(iter(declarations)) for field, declarations in values.items() if len(declarations) == 1}, conflicts


def _source_identity_issues(claims: dict, row: dict) -> tuple[list[str], list[str]]:
    observed, inconsistent = _source_claims(row, coding=False)
    conflicting = sorted(set(inconsistent) | {field for field, value in claims.items()
                                              if field in observed and observed[field] != value})
    return conflicting, sorted(field for field in claims if field not in observed)


def _prepare_pi_sources(ctx: dict, artifacts: dict, root: Path) -> dict:
    """Freeze explicit methods plus acquired primary evidence before Pi starts.

    Plan never enters this function. Only exact bibliographic identities link
    coding rows to source rows. Failed acquisitions remain in the source manifest;
    no reference values, arbitrary evidence_file paths or gold tables are read.
    """
    from metaagent.acquisition import resolve_document
    records = _coding_records(artifacts)
    settings = ctx["synthesis_settings"]
    declared = [Path(p).resolve() for p in settings["method_sources"]]
    upstream = artifacts.get("fulltext_records") or artifacts.get("fulltext_predictions") or artifacts.get("coding_input_manifest")
    signature = _hash({"identity_policy": _PI_SOURCE_IDENTITY_POLICY,
                       "coding": records, "upstream": file_hash(Path(upstream)) if upstream else None,
                       "methods": {str(p): file_hash(p) for p in declared},
                       "source_review": ctx.get("synthesis_source_review")})
    directory = root / signature[:24]
    manifest_path = directory / "source_manifest.json"
    if manifest_path.is_file():
        cached = json.loads(manifest_path.read_text())
        if cached.get("identity_policy") == _PI_SOURCE_IDENTITY_POLICY and all(
                Path(source["path"]).is_file() and file_hash(Path(source["path"])) == source["sha256"]
                for source in cached["sources"]):
            return {**cached, "manifest_path": str(manifest_path)}
        # Preserve an old source snapshot and claim when source bytes changed.
        directory = directory.with_name(directory.name + "_" + uuid.uuid4().hex[:12])
        manifest_path = directory / "source_manifest.json"
    directory.mkdir(parents=True, exist_ok=True)
    sources, gaps, outcomes = [], [], []
    seen = set()
    def add(path, role, record_id=None, kind=None):
        if not path:
            return
        candidate = Path(path).resolve()
        if not candidate.is_file():
            gaps.append({"record_id": record_id, "reason": "source_file_missing", "path": str(candidate)})
            return
        if role == "primary_study" and any(source["path"] == str(candidate) and source["role"] == "original_methods" for source in sources):
            gaps.append({"record_id": record_id, "reason": "primary_source_already_declared_as_original_methods", "path": str(candidate)})
            return
        key = (str(candidate), role, record_id)
        if key not in seen:
            seen.add(key)
            sources.append({"path": str(candidate), "sha256": file_hash(candidate), "role": role,
                            "record_id": record_id, "kind": kind})
    for path in declared:
        add(path, "original_methods", kind="explicit_methods")
    identities = {}
    for record in records:
        identity = _bibliographic_identity(record)
        aliases = _identity_aliases(identity)
        if not aliases:
            gaps.append({"record_id": None, "reason": "coding_row_without_bibliographic_identity"})
            continue
        key = str(identity.get("record_id") or sorted(aliases)[0])
        claims, conflicts = _source_claims(identity, coding=True)
        if key in identities:
            item = identities[key]
            conflicts.extend(field for field, value in claims.items() if field in item["claims"] and item["claims"][field] != value)
            item["conflicts"].update(conflicts)
            item["claims"].update(claims)
            item["aliases"].update(aliases)
            for field, value in identity.items():
                item["identity"].setdefault(field, value)
        else:
            identities[key] = {"identity": identity, "aliases": aliases, "claims": claims, "conflicts": set(conflicts)}
    upstream_rows = _load_jsonl(upstream) if upstream else []
    for record_id, item in identities.items():
        if item["conflicts"]:
            gaps.append({"record_id": record_id, "reason": "coding_bibliographic_identity_conflict", "fields": sorted(item["conflicts"])})
            continue
        exact = [row for row in upstream_rows if str(row.get("record_id") or "") == str(item["identity"].get("record_id") or "")]
        matches = exact or [row for row in upstream_rows if item["aliases"] & _identity_aliases(row)]
        if len(matches) > 1:
            gaps.append({"record_id": record_id, "reason": "ambiguous_primary_source_identity"})
            continue
        if matches:
            row = matches[0]
            conflicting, missing = _source_identity_issues(item["claims"], row)
            if conflicting or missing:
                gaps.append({"record_id": record_id,
                             "reason": "primary_source_identity_conflict" if conflicting else "primary_source_identity_pending",
                             "conflicting_fields": conflicting, "missing_fields": missing})
                continue
            available = len(sources)
            for source in [row, *(row.get("supplements") or [])]:
                add(source.get("pdf_path"), "primary_study", record_id, "primary_pdf")
                add(source.get("fulltext_path") or source.get("path"), "primary_study", record_id, "primary_text")
                for original in source.get("source_documents") or []:
                    add(original.get("original_path"), "primary_study", record_id, "primary_original")
            if len(sources) == available:
                gaps.append({"record_id": record_id, "reason": "upstream_primary_source_unavailable"})
        else:
            identity = item["identity"]
            if not (identity.get("pmid") or identity.get("doi") or str(identity.get("record_id") or "").startswith(("pmid:", "doi:"))):
                gaps.append({"record_id": record_id, "reason": "no_resolvable_bibliographic_identifier"})
                continue
            outcome = resolve_document(identity, directory / "acquisition", require_pdf=True, parse=False, cache_policy="strict")
            outcomes.append({"role": "primary_study", **outcome})
            if outcome.get("pdf_path") and outcome.get("record_status") == "pdf_ready":
                conflicting, missing = _source_identity_issues(item["claims"], outcome)
                if conflicting or missing:
                    gaps.append({"record_id": record_id,
                                 "reason": "primary_source_identity_conflict" if conflicting else "primary_source_identity_pending",
                                 "conflicting_fields": conflicting, "missing_fields": missing})
                    continue
                add(outcome["pdf_path"], "primary_study", record_id, "primary_pdf")
            else:
                gaps.append({"record_id": record_id, "reason": outcome.get("failure_reason") or "primary_pdf_unavailable"})
    review = ctx.get("synthesis_source_review") or {}
    if not declared and review.get("pmid"):
        outcome = resolve_document({**review, "record_id": "pmid:" + str(review["pmid"])},
                                   directory / "acquisition", require_pdf=True, parse=False, cache_policy="strict")
        outcomes.append({"role": "original_methods", **outcome})
        if outcome.get("record_status") == "pdf_ready" and outcome.get("pdf_path"):
            add(outcome["pdf_path"], "original_methods", "pmid:" + str(review["pmid"]), "original_review_pdf")
        else:
            gaps.append({"record_id": "pmid:" + str(review["pmid"]), "reason": outcome.get("failure_reason") or "original_methods_unavailable"})
    # Identity metadata only: it is labelled as a lookup map, not scientific
    # evidence, and contains no target estimates or evaluation annotations.
    mapping = directory / "primary_source_map.md"
    mapping.write_text("# Workflow source identity map (metadata only)\n\n"
        "Use the actual source text/PDF for scientific claims. This map supplies no verified estimates.\n\n"
        + json.dumps({"sources": sources, "unavailable": gaps}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if sources or gaps:
        add(mapping, "primary_study", kind="identity_metadata_only")
    payload = {"schema_version": "2", "identity_policy": _PI_SOURCE_IDENTITY_POLICY, "sources": sources, "gaps": gaps,
               "acquisition_receipt": str(directory / "acquisition_outcomes.jsonl")}
    _jsonl(directory / "acquisition_outcomes.jsonl", outcomes)
    _write_json(manifest_path, payload)
    return {**payload, "manifest_path": str(manifest_path)}


def _complete_pubmed_search(query: str, directory: Path, *, start: date, end: date) -> tuple[list[dict], dict]:
    """Export the complete root ESearch set or fail, never truncate at 9,999."""
    from tools.benchmark_v2.retrieve_public import METADATA_PARSER_VERSION, PubMed

    client = PubMed(directory / "ncbi_cache")
    stats = {"status": "running", "requested_limit": None, "retrieval_complete": False,
             "retrieval_scope": "all_matches_in_current_PubMed_index", "executed_query": query,
             "executed_at": datetime.now(UTC).isoformat(), "historical_index_reproduction": False,
             "adapter": "date_partitioned_public_pubmed", "metadata_parser_version": METADATA_PARSER_VERSION,
             "partition_window": {"from": start.isoformat(), "to": end.isoformat(),
                                  "purpose": "partition coverage only; root query is unmodified; union must equal root count"}}
    try:
        ids = {str(value) for value in client.search(query, start=start, end=end)}
        if not client.calls:
            raise ValueError("Complete PubMed retrieval has no ESearch count provenance")
        total = int(client.calls[0]["count"])
        stats.update(total_matches=total, partition_union_ids=len(ids),
                     count_validation={"root_esearch_count": total, "partition_union_ids": len(ids), "all_equal": False})
        if len(ids) != total:
            raise ValueError(f"Complete PubMed ESearch union has {len(ids)} IDs but root count is {total}")
        rows = client.records(ids)
        exported_ids = [str(row.get("pmid") or "") for row in rows]
        stats.update(retrieved=len(rows), unique_metadata_ids=len(set(exported_ids)))
        if len(rows) != total or len(set(exported_ids)) != total or set(exported_ids) != ids:
            raise ValueError("Complete PubMed EFetch rows do not match verified ESearch IDs")
        _jsonl(directory / "raw_search_export.jsonl", rows)
        (directory / "pubmed_ids.txt").write_text("".join(value + "\n" for value in sorted(ids)), encoding="utf-8")
        stats.update(status="all_matches_retrieved", retrieved=len(rows), total_matches=total,
                     retrieval_complete=True, subset=False,
                     count_validation={"root_esearch_count": total, "partition_union_ids": len(ids),
                                       "metadata_records": len(rows), "unique_metadata_ids": len(set(exported_ids)),
                                       "all_equal": True})
        return normalize_records(rows), stats
    except Exception as exc:
        stats.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        stats["ncbi_search_calls"] = client.calls
        stats["query_warnings"] = [{"query": call["query"], "warnings": call["warninglist"]}
                                   for call in client.calls if call.get("warninglist")]
        _write_json(directory / "retrieval_stats.json", stats)


def _coding_outputs(extraction: Path) -> tuple[Path | None, Path | None]:
    """Use the current attempt's declared sheet, never newest-file selection."""
    manifests = list(extraction.glob("run_manifest*.json"))
    if len(manifests) > 1:
        raise ValueError("Current coding attempt has multiple run manifests")
    manifest = manifests[0] if manifests else None
    if manifest:
        extra = json.loads(manifest.read_text(encoding="utf-8")).get("extra", {})
        if "xlsx_path" in extra:
            declared = extra["xlsx_path"]
            if not declared:
                return manifest, None
            path = Path(declared)
            candidates = {p.resolve() for p in (path, extraction / path) if p.is_file()}
            candidates = {p for p in candidates if p.is_relative_to(extraction.resolve())}
            if len(candidates) != 1:
                raise ValueError("Coding manifest does not identify one existing sheet within this attempt")
            return manifest, candidates.pop()
    # Compatibility with injected adapters/older manifests that have no xlsx
    # declaration: uniqueness within a fresh attempt is required, without mtime.
    sheets = list(extraction.glob("coding_sheet*.xlsx"))
    if len(sheets) > 1:
        raise ValueError("Coding attempt has multiple sheets and no explicit manifest selection")
    return manifest, sheets[0] if sheets else None


def execute_stage(stage, o, ctx, directory, artifacts):
    """Shared stage adapter used by both complete and stage-range runs."""
    directory.mkdir(parents=True, exist_ok=True)
    unresolved = 0
    # Commit normal artifacts only after this executor returns successfully.
    # A failed attempt publishes its paths through the diagnostic index instead.
    result = {}
    required = {"screening": ("records_source",), "fulltext_fetch": ("screening_predictions", "records_source"),
                "fulltext_screening": ("fulltext_records",), "coding": ("fulltext_predictions", "fulltext_records"),
                "pooling": ("coding_predictions", "coding_estimates")}.get(stage, ())
    if required and not any(artifacts.get(key) for key in required):
        raise ValueError(f"Stage {stage} requires a verified prior artifact ({' or '.join(required)}); run preceding stages with the same configuration, or supply an explicit input for screening/fulltext_fetch")
    if stage == "retrieval":
        source = _input_path(o, ctx)
        if source:
            rows = read_records(source)
            if o.limit:
                rows = rows[:o.limit]
        elif ctx.get("source_queries") and not o.query:
            from metaagent.retrieval import search_sources
            def complete_pubmed(query, target):
                return _complete_pubmed_search(query, target, start=date(1800, 1, 1), end=date(3000, 12, 31))
            rows, stats = search_sources(ctx["source_queries"], directory, limit=o.limit, complete_pubmed=complete_pubmed, page_cache=Path(o.output_dir) / "input_cache" / "search" if o.resume else None)
            rows = normalize_records(rows)
            unresolved = stats["failed_sources"] + stats.get("incomplete_sources", 0)
            result["retrieval_stats"] = str(directory / "retrieval_stats.json")
        else:
            from tools.pubmed.query_generator import PubMedQueryGenerator, PubMedQueryRequest, search_pubmed_to_csv
            if o.query:
                query = o.query
                provenance = {"query": query, "mode": "explicit_final_query", "date_policy": "dates must be present in the supplied query; no hidden date filters added"}
            else:
                if not ctx["start_date"] or not ctx["end_date"]:
                    raise ValueError("Generated retrieval requires --start-date and --end-date or task date metadata")
                from metaagent.screening.engine import init_llm_model
                model = init_llm_model(config_overrides=_llm_params(o, "query"), module_hint="query")
                request = PubMedQueryRequest(question=ctx["screening_config"]["research_question"], disease=ctx["disease"],
                    parameter=ctx["topic"], start_date=ctx["start_date"], end_date=ctx["end_date"], project_id="p1")
                artifact = PubMedQueryGenerator(llm=model, provider=_llm_params(o, "query")["llm_provider"], model=_llm_params(o, "query")["llm_model"]).generate(request)
                query = artifact.query
                provenance = artifact.model_dump(mode="json")
            _write_json(directory / "query.json", provenance)
            result["query"] = str(directory / "query.json")
            result["retrieval_stats"] = str(directory / "retrieval_stats.json")
            if o.limit is None:
                # Generated queries contain their validated window. Explicit
                # queries get a wide partition cover, including future-dated
                # records; no profile date filter is silently added to them.
                start = date.fromisoformat(ctx["start_date"]) if not o.query else date(1800, 1, 1)
                end = date.fromisoformat(ctx["end_date"]) if not o.query else date(3000, 12, 31)
                rows, stats = _complete_pubmed_search(query, directory, start=start, end=end)
                result["retrieval_export"] = str(directory / "raw_search_export.jsonl")
                result["retrieval_identifiers"] = str(directory / "pubmed_ids.txt")
            else:
                stats = search_pubmed_to_csv(query, directory / "raw_search.csv", retmax=o.limit, medline_only=False)
                rows = read_records(directory / "raw_search.csv")
                if stats.get("retrieved") != len(rows) or len(rows) > o.limit:
                    raise ValueError("Limited PubMed export row count differs from its requested subset")
                stats.update(status="limited_subset_retrieved", requested_limit=o.limit, retrieved=len(rows),
                             retrieval_complete=False, subset=True, retrieval_scope="explicit_limited_subset",
                             executed_query=query, executed_at=datetime.now(UTC).isoformat(),
                             historical_index_reproduction=False, adapter="limited_pubmed_client",
                             query_warnings=None, query_warnings_status="see_query_retrieval_receipt_when_available",
                             all_matches_fit_in_subset=(len(rows) == stats.get("total_matches")))
                receipt_path = (directory / "raw_search.csv").with_suffix(".csv.retrieval.json")
                if receipt_path.is_file():
                    receipt = json.loads(receipt_path.read_text())
                    stats.update(ncbi_search_calls=receipt.get("ncbi_search_calls"), remote_validation=receipt.get("remote_validation"),
                                 local_validation=receipt.get("local_validation"), query_warnings_status="preserved_in_ncbi_search_calls")
                    result["query_retrieval_receipt"] = str(receipt_path)
                _write_json(directory / "retrieval_stats.json", stats)
                result["retrieval_export"] = str(directory / "raw_search.csv")
        for row in rows:
            row["record_status"] = "retrieved" if not source else "imported"
            row["pool_kind"] = {"search": "natural_search", "raw_search": "frozen_natural_search", "raw_pool": "explicit_augmented_pool"}[o.input_mode]
        path = directory / ("raw_pool.jsonl" if o.input_mode == "raw_pool" else "raw_search.jsonl")
        _jsonl(path, rows)
        result["records_source"] = str(path)
    elif stage == "screening":
        rows = _screen_rows(_load_jsonl(artifacts["records_source"]), o, ctx, directory=directory)
        _jsonl(directory / "screening_predictions.jsonl", rows)
        result["screening_predictions"] = str(directory / "screening_predictions.jsonl")
        from metaagent.screening.guards import screening_audit
        _write_json(directory / "screening_audit.json", screening_audit(rows))
        result["screening_audit"] = str(directory / "screening_audit.json")
        unresolved = sum(row["record_status"] == "error" for row in rows)
    elif stage == "fulltext_fetch":
        if artifacts.get("screening_predictions"):
            rows = [r for r in _load_jsonl(artifacts["screening_predictions"]) if _retained(r)]
        else:
            rows = _load_jsonl(artifacts["records_source"])
        fetched = []
        for row in rows:
            try:
                fetched.append(_fetch_pmc(row, directory))
            except Exception as exc:
                fetched.append({**row, "record_status": "fulltext_unavailable", "failure_reason": type(exc).__name__})
        _jsonl(directory / "fulltext_records.jsonl", fetched)
        result["fulltext_records"] = str(directory / "fulltext_records.jsonl")
        unresolved = sum(r["record_status"] != "fulltext_ready" for r in fetched)
    elif stage == "fulltext_screening":
        rows = _load_jsonl(artifacts["fulltext_records"])
        ready = []
        for row in rows:
            if row["record_status"] == "fulltext_ready":
                from metaagent.documents import document_bundle
                row["fulltext"], row["fulltext_coverage"] = document_bundle(row)
                ready.append(row)
        if ready and not o.skip_fulltext_screening:
            _screen_rows(ready, o, ctx, fulltext=True, directory=directory)
        for row in rows:
            row.pop("fulltext", None)
        unresolved = sum(r["record_status"] not in ({"fulltext_ready"} if o.skip_fulltext_screening else {"screened"}) for r in rows)
        _jsonl(directory / "fulltext_predictions.jsonl", rows)
        result["fulltext_predictions"] = str(directory / "fulltext_predictions.jsonl")
        from metaagent.screening.guards import screening_audit
        _write_json(directory / "screening_audit.json", screening_audit(rows))
        result["fulltext_screening_audit"] = str(directory / "screening_audit.json")
    elif stage == "coding":
        from metaagent.coding.pipeline.extraction import run_pipeline
        rows = _load_jsonl(artifacts.get("fulltext_predictions") or artifacts["fulltext_records"])
        attempt = directory / "attempts" / uuid.uuid4().hex
        attempt.mkdir(parents=True)
        inputs = attempt / "inputs"
        inputs.mkdir()
        extraction = attempt / "extraction"
        coding_status = []
        documents = []
        for row in rows:
            expected_statuses = {"fulltext_ready"} if not artifacts.get("fulltext_predictions") or o.skip_fulltext_screening else {"screened"}
            if row.get("record_status") not in expected_statuses:
                coding_status.append({"record_id": row["record_id"], "status": "unresolved", "reason": row.get("failure_reason") or "fulltext_screening_error"})
            elif artifacts.get("fulltext_predictions") and row.get("record_status") == "screened" and not _retained(row):
                coding_status.append({"record_id": row["record_id"], "status": "excluded_by_fulltext_screening"})
            elif not row.get("fulltext_path"):
                coding_status.append({"record_id": row["record_id"], "status": "unresolved", "reason": row.get("failure_reason", "no_fulltext")})
            else:
                from metaagent.documents import materialize_coding_document
                try:
                    document=materialize_coding_document(row,inputs)
                except Exception as exc:
                    coding_status.append({"record_id":row["record_id"],"status":"unresolved",
                                          "reason":"document_parse_error","error_type":type(exc).__name__})
                    continue
                pmid=document["pmid"]
                documents.append(document)
                coding_status.append({"record_id":row["record_id"],"pmid":pmid,"status":"submitted"})
        _jsonl(attempt / "coding_input_manifest.jsonl", documents)
        result["coding_input_manifest"] = str(attempt / "coding_input_manifest.jsonl")
        _jsonl(attempt / "coding_status.jsonl", coding_status)
        result["coding_record_status"] = str(attempt / "coding_status.jsonl")
        result["coding_attempt_manifest"] = str(attempt / "attempt_manifest.json")
        attempt_info = {"attempt_id": attempt.name, "started_at": datetime.now(UTC).isoformat(),
                        "status": "running", "extraction_dir": str(extraction),
                        "input_manifest": result["coding_input_manifest"], "record_status": result["coding_record_status"]}
        _write_json(attempt / "attempt_manifest.json", attempt_info)
        _write_json(directory / "stage_artifacts.json", {"attempt_id":attempt.name,"artifacts":dict(result)})
        unresolved = sum(r["status"] == "unresolved" for r in coding_status)
        if not documents:
            import pandas as pd
            sheet = directory / "coding_sheet_empty.xlsx"
            pd.DataFrame(columns=["record_id", "parameter_type"]).to_excel(sheet, index=False)
            structured = directory / "coding_estimates.jsonl"
            _jsonl(structured, [])
            result.update(coding_predictions=str(sheet), coding_estimates=str(structured))
            attempt_info.update(status="not_run", reason="no_eligible_fulltext_documents")
            _write_json(attempt / "attempt_manifest.json", attempt_info)
            _write_json(directory / "stage_artifacts.json", {"attempt_id":attempt.name,"artifacts":dict(result)})
            return {"artifacts": result, "unresolved": unresolved}
        completed = False
        lookup_error = None
        try:
            from metaagent.workflow_task import resolve_coding
            coding_cfg = resolve_coding(o)
            run_pipeline(inputs, extraction, "both", ctx["codebook"], fetch_strategy="pmc_only", llm_overrides=_llm_params(o, "coding"), extraction_backend=coding_cfg["backend"], ablation=o.ablation, chunk_chars=coding_cfg["chunk_chars"], extraction_scope=coding_cfg["extraction_scope"], review_context={"research_question":ctx["screening_config"].get("research_question"),"review_protocol":ctx["screening_config"].get("review_protocol")}, stage_a_empty_retries=coding_cfg["stage_a_empty_retries"], document_manifest=attempt / "coding_input_manifest.jsonl")
            completed = True
        finally:
            try:
                execution_manifest, sheet = _coding_outputs(extraction)
            except (OSError, ValueError, TypeError) as exc:
                lookup_error = exc
                execution_manifest, sheet = None, None
            if sheet:
                result["coding_predictions"] = str(sheet)
            extra = {}
            if execution_manifest:
                result["coding_execution_manifest"] = str(execution_manifest)
                extra = json.loads(execution_manifest.read_text()).get("extra", {})
            errors = {str(x.get("record_id") or x.get("pmid")): x for x in extra.get("errors", [])}
            processed_ids = set()
            if sheet:
                import pandas as pd
                try:
                    frame = pd.read_excel(sheet, dtype=str)
                    column = "record_id" if "record_id" in frame else "pmid" if "pmid" in frame else None
                    if column:
                        processed_ids = set(frame[column].astype(str))
                except Exception as exc:
                    lookup_error = exc
            for row in coding_status:
                if row["status"] == "submitted":
                    error = errors.get(row["record_id"]) or errors.get(str(row["pmid"]))
                    processed = row["record_id"] in processed_ids or (row["pmid"] and row["pmid"] in processed_ids)
                    row["status"] = "error" if error else "processed" if processed else "no_records" if execution_manifest else "error"
                    if error:
                        row["reason"] = error.get("stage", "extraction_error")
                    elif row["status"] == "error":
                        row["reason"] = "coding_did_not_complete"
            _jsonl(attempt / "coding_status.jsonl", coding_status)
            attempt_info.update(status="complete" if completed and sheet and lookup_error is None else "failed",
                                pipeline_returned=completed, finished_at=datetime.now(UTC).isoformat(), artifacts=dict(result))
            if lookup_error:
                attempt_info["artifact_error_type"] = type(lookup_error).__name__
            _write_json(attempt / "attempt_manifest.json", attempt_info)
            _write_json(directory / "stage_artifacts.json", {"attempt_id":attempt.name,"artifacts":dict(result)})
        if lookup_error:
            raise ValueError(f"Coding output validation failed: {type(lookup_error).__name__}") from lookup_error
        if sheet is None:
            raise ValueError("Coding attempt produced no manifest-selected coding sheet")
        result["coding_predictions"] = str(sheet)
        structured = extraction / "coding_estimates.jsonl"
        if structured.is_file():
            result["coding_estimates"] = str(structured)
        if (extraction / "coding_completeness.json").is_file():
            result["coding_completeness"] = str(extraction / "coding_completeness.json")
    elif stage == "pooling":
        import pandas as pd
        from metaagent.synthesis import run_synthesis, run_analyses, write_synthesis_artifacts
        records = _coding_records(artifacts)
        protocol = ctx.get("analysis_protocol")
        synthesis_settings = ctx.get("synthesis_settings")
        if synthesis_settings is None:
            from metaagent.workflow_task import resolve_synthesis
            synthesis_settings = resolve_synthesis(o)
        llm_invoke = None
        protocols = protocol if isinstance(protocol, list) else [protocol or {}]
        if synthesis_settings["backend"] == "pi":
            from metaagent.synthesis.pi_agent import run_pi_synthesis
            prepared = ctx.get("pi_sources")
            source_paths = [Path(source["path"]) for source in prepared["sources"]] if prepared else [Path(value) for value in synthesis_settings["method_sources"]]
            roles = {source["path"]: source["role"] for source in prepared["sources"]} if prepared else None
            synthesis = run_pi_synthesis(records=records,
                research_question=synthesis_settings["research_question"],
                review_context=ctx["screening_config"].get("review_protocol"),
                method_sources=list(dict.fromkeys(source_paths)), source_roles=roles,
                output_dir=directory, protocol=protocol[0] if isinstance(protocol, list) and protocol else protocol,
                settings=synthesis_settings, runtime_overrides=_llm_params(o, "synthesis"), resume=o.resume)
            published = dict(synthesis.get("artifacts") or {})
            if prepared:
                # Copy only our metadata manifest into the stage; Pi's published
                # scientific artifacts remain byte-identical to its receipts.
                _write_json(directory / "workflow_sources.json", prepared)
                published["workflow_sources"] = str(directory / "workflow_sources.json")
            # Publish failures as inspectable failures; never manufacture an
            # analysis result or require an old deterministic protocol to run Pi.
            if "synthesis_result" not in published:
                _write_json(directory / "synthesis_result.json", synthesis)
                published["synthesis_result"] = str(directory / "synthesis_result.json")
            if "synthesis_report" not in published:
                report = directory / "synthesis_report.md"
                report.write_text("# Pi synthesis\n\nStatus: " + str(synthesis.get("status", "failed")) + "\n", encoding="utf-8")
                published["synthesis_report"] = str(report)
            for value in published.values():
                path = Path(value).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file():
                    raise ValueError("Pi synthesis declared an artifact outside its stage or a missing file")
        elif any(p.get("llm_report") or p.get("llm_selection") for p in protocols):
            llm_invoke = _synthesis_invoke(o, directory)
        if synthesis_settings["backend"] == "pi":
            pass
        elif isinstance(protocol, list):
            synthesis, published = run_analyses(records, protocol, directory, llm_invoke=llm_invoke)
        else:
            synthesis = run_synthesis(records, protocol, llm_invoke=llm_invoke)
            published = None
        coverage = {}
        if artifacts.get("retrieval_stats"):
            retrieval = json.loads(Path(artifacts["retrieval_stats"]).read_text())
            coverage["retrieval_complete"] = retrieval.get("retrieval_complete", False)
            coverage["failed_sources"] = retrieval.get("failed_sources", 0)
        for name in ("screening_predictions", "fulltext_records", "fulltext_predictions", "coding_record_status"):
            if artifacts.get(name):
                rows = _load_jsonl(artifacts[name])
                counts = {}
                for row in rows:
                    status = row.get("record_status") or row.get("status") or "unknown"
                    counts[status] = counts.get(status, 0) + 1
                coverage[name] = {"total": len(rows), "statuses": counts}
        synthesis["workflow_coverage"] = coverage
        if synthesis_settings["backend"] == "pi":
            # Executed-code receipts may bind the agent's result/report bytes.
            # Keep those artifacts immutable after validation; attach workflow
            # coverage as a separate artifact rather than rewriting them.
            _write_json(directory / "workflow_coverage.json", coverage)
            published["workflow_coverage"] = str(directory / "workflow_coverage.json")
        elif published is None:
            published = write_synthesis_artifacts(synthesis, directory)
        else:
            _write_json(Path(published["synthesis_result"]), synthesis)
        if synthesis_settings["backend"] != "pi":
            report = Path(published["synthesis_report"])
            with report.open("a", encoding="utf-8") as handle:
                handle.write("\n\nWorkflow coverage (from execution artifacts):\n\n```json\n" + json.dumps(coverage, ensure_ascii=False, indent=2) + "\n```\n")
        result.update(published)
        if synthesis["status"] not in {"complete", "single_estimate"}:
            unresolved = max(1, synthesis.get("counts", {}).get("review", 0))
    return {"artifacts": result, "unresolved": unresolved}


def _synthesis_invoke(o, directory):
    from time import perf_counter
    from metaagent.screening.engine import init_llm_model
    model = None
    def invoke(messages):
        nonlocal model
        start = perf_counter()
        event = {"module": "synthesis", "status": "running"}
        try:
            if model is None:
                model = init_llm_model(config_overrides=_llm_params(o, "synthesis"), module_hint="synthesis")
            response = model.invoke(messages)
            content = response.content
            event.update(status="complete", response=content, usage=getattr(response, "usage_metadata", None), response_metadata=getattr(response, "response_metadata", None), model=getattr(model, "model_name", None))
            return content
        except Exception as exc:
            event.update(status="failed", error_type=type(exc).__name__)
            raise
        finally:
            event["walltime_s"] = perf_counter() - start
            with (directory / "llm_calls.jsonl").open("a") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    return invoke


def _stage_config_hash(plan: dict, stage: str) -> str:
    """Hash semantic stage inputs, so analysis edits do not rerun retrieval."""
    config = plan["config"]
    keys = {
        "retrieval": ("input_mode", "query", "start_date", "end_date", "limit", "source_queries", "screening_config"),
        "screening": ("screening_config", "strategy", "batch_size", "batch_concurrency", "batch_mode"),
        "fulltext_fetch": ("fetch_mode", "paper_pool", "document_parser", "document_acquisition"),
        "fulltext_screening": ("screening_config", "strategy", "batch_size", "batch_concurrency", "batch_mode", "skip_fulltext_screening", "document_parser", "document_acquisition"),
        "coding": ("coding_review_context", "codebook", "extraction_backend", "ablation", "coding_settings", "chunk_chars", "runtime_environment", "document_parser", "document_acquisition"),
        "pooling": ("analysis_protocol", "synthesis_settings", "synthesis_inspection", "synthesis_source_review", "document_acquisition"),
    }[stage]
    semantic = {k: config.get(k) for k in keys}
    if stage == "retrieval" and (config.get("query") or config.get("source_queries")):
        semantic.pop("screening_config", None)
    modules = {"retrieval": "query", "screening": "screening", "fulltext_screening": "screening", "coding": "coding", "pooling": "synthesis"}
    if stage in modules:
        semantic["runtime"] = config["effective_llm_runtime"][modules[stage]]
    def relevant(path):
        path = Path(path)
        if path.name in {"workflow_runner.py", "workflow_task.py", "config.py"}:
            return True
        name = str(path)
        if path.name in {"acquisition.py", "pmc_cloud.py"}:
            return stage in {"fulltext_fetch", "fulltext_screening", "coding", "pooling"}
        if path.name == "evidence_search.py":
            return stage in {"coding", "pooling"}
        if stage == "retrieval":
            return any(v in name for v in ("tools/literature/", "tools/pubmed/", "metaagent/retrieval.py", "metaagent/prompts/query/"))
        if stage in {"screening", "fulltext_screening"}:
            if stage=="fulltext_screening" and ("metaagent/documents.py" in name or "tools/mineru/" in name):return True
            return any(folder in name for folder in ("metaagent/screening/", "metaagent/prompts/screening/", "metaagent/prompts/5d/", "metaagent/prompts/binary/", "metaagent/prompts/peco/"))
        if stage == "fulltext_fetch":
            return "tools/mineru/" in name or "metaagent/documents.py" in name or "tools/benchmark_v2/retrieve_public.py" in name
        if stage == "coding":
            return any(v in name for v in ("metaagent/coding/", "metaagent/prompts/coding/", "metaagent/documents.py", "tools/mineru/", "/codebooks/", "/coding_prompts/")) or path == Path(config["codebook"])
        return (str(path) in (config.get("synthesis_inspection") or {}).get("method_source_sha256", {})
                or "metaagent/synthesis/" in name or "metaagent/prompts/synthesis/" in name or "tools/analysis/" in name)
    semantic["dependencies"] = {p: h for p, h in config["dependency_hashes"].items() if relevant(p)}
    return _hash(semantic)


def _publish_quality_audit(manifest, output):
    """Publish bounded operational diagnostics without making them a run gate."""
    try:
        from metaagent.evaluation.diagnostics import diagnose_workflow
        audit = diagnose_workflow(manifest, run_root=output)
        _write_json(output / "quality_audit.json", audit)
        _write_json(output / "flow_counts.json", audit["flow_counts"])
        manifest.setdefault("artifacts", {}).update(quality_audit=str(output / "quality_audit.json"), flow_counts=str(output / "flow_counts.json"))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        manifest.setdefault("warnings", []).append("quality_audit_unavailable:" + type(exc).__name__)


def run_workflow(o: WorkflowOptions) -> dict:
    plan = plan_workflow(o)
    ctx = _context(o)
    output = Path(o.output_dir).expanduser().resolve()
    manifest_path = output / "workflow_manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest = {**plan, "dry_run": False, "started_at": datetime.now(UTC).isoformat(), "status": "running", "stage_results": {}, "artifacts": {}, "artifact_overrides": previous.get("artifact_overrides", {})}
    artifacts = manifest["artifacts"]
    output.mkdir(parents=True, exist_ok=True)
    # Typed modular imports share the same stage executors as end-to-end runs.
    if o.estimates_input:
        from metaagent.synthesis.cli import read_estimates
        imported = output / "imports" / (file_hash(Path(o.estimates_input))[:20] + ".estimates.jsonl")
        _jsonl(imported, read_estimates(Path(o.estimates_input)))
        artifacts["coding_estimates"] = str(imported)
    elif o.document_manifest:
        from metaagent.coding.pipeline.extraction import load_document_manifest
        declared = load_document_manifest(Path(o.document_manifest))
        source_hashes = {str(source["path"]): file_hash(Path(source["path"]))
                         for row in declared for source in [row, *(row.get("supplements") or [])] if source.get("path")}
        import_key = _hash({"manifest": file_hash(Path(o.document_manifest)), "sources": source_hashes,
                            "parser": plan["config"]["document_parser"],
                            "acquisition_implementation": file_hash(Path(__file__).with_name("acquisition.py"))})[:20]
        imported = output / "imports" / (import_key + ".documents.jsonl")
        cached_rows = _load_jsonl(imported) if imported.is_file() else []
        def valid_snapshot(row):
            if row.get("record_status") != "fulltext_ready":
                return False
            for source in [row, *(row.get("supplements") or [])]:
                for field, hash_field in (("fulltext_path", "fulltext_sha256"), ("pdf_path", "pdf_sha256")):
                    value = source.get(field)
                    if value and (not Path(value).is_file() or (source.get(hash_field) and file_hash(Path(value)) != source[hash_field])):
                        return False
                if not source.get("fulltext_path"):
                    return False
            return True
        if cached_rows and all(valid_snapshot(row) for row in cached_rows):
            rows = cached_rows
        else:
            # A failed or changed source is a new acquisition attempt. Retain
            # the old input/receipt, including the denominator of failures.
            if imported.exists():
                import_key += "_" + uuid.uuid4().hex[:12]
                imported = output / "imports" / (import_key + ".documents.jsonl")
            rows = _import_documents(Path(o.document_manifest), output / "imports" / "acquisition" / import_key)
            _jsonl(imported, rows)
        artifacts["fulltext_records"] = str(imported)
    elif o.start_at != "retrieval" and plan["input"]:
        rows = read_records(Path(plan["input"]))
        if o.limit:
            rows = rows[:o.limit]
        imported = output / "imports" / f"{plan['input_sha256'][:20]}.jsonl"
        _jsonl(imported, rows)
        artifacts["records_source"] = str(imported)
    elif o.start_at != "retrieval":
        # Reuse dependencies only when the whole configuration and their content
        # hashes match. No mtime-based freshness and no implicit legacy fallback.
        for stage in STAGES[:STAGES.index(o.start_at)]:
            item = previous.get("stage_results", {}).get(stage, {})
            if item.get("config_stage_sha256") != _stage_config_hash(plan, stage) or not _reusable(item):
                break
            artifacts.update(item.get("artifacts", {}))
            manifest["stage_results"][stage] = {**item, "reused": True}
            _apply_overrides(manifest, item.get("artifacts", {}))
    _apply_overrides(manifest, dict(artifacts))
    _write_json(manifest_path, manifest)
    try:
        for stage in plan["stages"]:
            if stage == "pooling" and ctx["synthesis_settings"]["backend"] == "pi":
                ctx["pi_sources"] = _prepare_pi_sources(ctx, artifacts, output / "synthesis_sources")
            inputs = {key: file_hash(Path(path)) for key, path in artifacts.items() if Path(path).is_file()}
            if stage == "pooling" and ctx.get("pi_sources"):
                inputs["pi_source_manifest"] = file_hash(Path(ctx["pi_sources"]["manifest_path"]))
                for source in ctx["pi_sources"]["sources"]:
                    inputs["pi_source:" + source["path"]] = source["sha256"]
            if stage == "fulltext_fetch":
                source_artifact = artifacts.get("screening_predictions") or artifacts.get("records_source")
                if source_artifact:
                    for row in _load_jsonl(source_artifact):
                        local = Path(row["fulltext_path"]).expanduser() if row.get("fulltext_path") else None
                        if local and local.is_file():
                            inputs["local_document:" + str(local.resolve())] = file_hash(local)
            for key in ("fulltext_records", "fulltext_predictions", "records_source"):
                if artifacts.get(key) and stage in {"fulltext_fetch", "fulltext_screening", "coding"}:
                    for row in _load_jsonl(artifacts[key]):
                        local = Path(row["fulltext_path"]) if row.get("fulltext_path") else None
                        if local and local.is_file():
                            inputs["primary_document:" + str(local.resolve())] = file_hash(local)
                        for source in row.get("supplements") or []:
                            path = Path(source["path"]) if source.get("path") else None
                            if path and path.is_file():
                                inputs["supplement:" + str(path.resolve())] = file_hash(path)
            stage_hash = _stage_config_hash(plan, stage)
            fingerprint = _hash({"stage": stage, "config": stage_hash, "input": plan["input_sha256"], "dependencies": inputs})
            old = previous.get("stage_results", {}).get(stage, {})
            if o.resume and old.get("fingerprint") == fingerprint and _reusable(old):
                item = {**old, "reused": True}
            else:
                directory = output / "stages" / stage / fingerprint[:20]
                resume_pi = (stage == "pooling" and ctx["synthesis_settings"]["backend"] == "pi"
                             and o.resume and old.get("fingerprint") == fingerprint
                             and old.get("status") in {"partial", "failed"}
                             and old.get("attempt_directory"))
                if resume_pi:
                    candidate = Path(old["attempt_directory"]).resolve()
                    if not candidate.is_relative_to((output / "stages" / "pooling").resolve()) or not candidate.is_dir():
                        raise ValueError("Pi resume attempt must be an existing managed pooling directory")
                    directory = candidate
                # Failed attempts never reuse partial model indexes accidentally.
                # Pi owns an explicit hash-bound continuation contract; only
                # that backend may resume the same incomplete analysis workspace.
                if directory.exists() and not resume_pi:
                    directory = directory.with_name(directory.name + "_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S%f"))
                log_name = f"{stage}_{directory.name}" + ("_resume_" + uuid.uuid4().hex[:12] if resume_pi else "")
                log = output / "logs" / (log_name + ".log")
                log.parent.mkdir(exist_ok=True)
                item = {"fingerprint": fingerprint, "config_stage_sha256": stage_hash, "status": "running", "reused": False, "log": str(log), "input_hashes": inputs,"attempt_directory":str(directory)}
                manifest["stage_results"][stage] = item
                _write_json(manifest_path, manifest)
                stage_started = perf_counter()
                try:
                    with log.open("w", encoding="utf-8") as handle, contextlib.redirect_stdout(_RedactingLog(handle, _runtime_secrets(o))), contextlib.redirect_stderr(_RedactingLog(handle, _runtime_secrets(o))):
                        result = execute_stage(stage, o, ctx, directory, artifacts)
                except Exception:
                    item["status"]="failed"
                    index=directory/"stage_artifacts.json"
                    diagnostic={}
                    if index.is_file():
                        try:
                            declared=json.loads(index.read_text()).get("artifacts",{})
                            for key,value in declared.items():
                                path=Path(value).resolve()
                                if path.is_relative_to(directory.resolve()) and path.is_file():diagnostic[key]=str(path)
                        except (ValueError,TypeError,OSError):pass
                    item["diagnostic_artifacts"]={"attempt_artifact_index":str(index),**diagnostic} if index.is_file() else diagnostic
                    manifest.setdefault("diagnostic_artifacts",{})[stage]=item["diagnostic_artifacts"]
                    raise
                finally:
                    item["walltime_s"] = perf_counter() - stage_started
                    item["output_hashes"] = {str(p): file_hash(p) for p in directory.rglob("*") if p.is_file()}
                item.update(result)
                item["status"] = "partial" if result["unresolved"] else "complete"
            artifacts.update(item.get("artifacts", {}))
            _apply_overrides(manifest, item.get("artifacts", {}))
            manifest["stage_results"][stage] = item
            _write_json(manifest_path, manifest)
            if stage == "screening" and item.get("unresolved"):
                raise ValueError("Screening has model errors; resolve them before proceeding")
        manifest["status"] = "partial" if any(r.get("unresolved") for r in manifest["stage_results"].values()) else "complete"
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        from metaagent.telemetry import summarize_run
        manifest['metrics'] = summarize_run(manifest)
        _write_json(output / 'run_metrics.json', manifest['metrics'])
        _publish_quality_audit(manifest, output)
        _write_json(manifest_path, manifest)
        if manifest["status"] == "partial":
            raise WorkflowRunError("Workflow has unresolved records; inspect per-record failures", manifest)
        return manifest
    except WorkflowRunError:
        raise
    except Exception as exc:
        # Do not serialize API exception bodies or credentials into provenance.
        message = str(exc)
        for secret in _runtime_secrets(o):
            message = message.replace(secret, "[REDACTED]")
        manifest.update(status="failed", error={"type": type(exc).__name__, "message": message}, finished_at=datetime.now(UTC).isoformat())
        for item in manifest["stage_results"].values():
            if item.get("status") == "running":
                item["status"] = "failed"
        from metaagent.telemetry import summarize_run
        manifest["metrics"]=summarize_run(manifest)
        _write_json(output/'run_metrics.json',manifest["metrics"])
        _publish_quality_audit(manifest, output)
        _write_json(manifest_path, manifest)
        raise WorkflowRunError(message, manifest) from exc


def _apply_overrides(manifest, machine_artifacts):
    for name, original in machine_artifacts.items():
        reviewed = manifest.get("artifact_overrides", {}).get(name)
        if not reviewed:
            continue
        path = Path(reviewed["path"])
        if file_hash(Path(original)) == reviewed["machine_sha256"] and path.is_file() and file_hash(path) == reviewed["sha256"]:
            manifest["artifacts"][name] = str(path)
            reviewed["status"] = "applied"
        else:
            reviewed["status"] = "stale_requires_rebase"


def _reusable(item):
    return bool(not item.get("stale") and item.get("status") == "complete" and item.get("output_hashes") and
                all(Path(p).is_file() and file_hash(Path(p)) == digest for p, digest in item["output_hashes"].items()))


def _runtime_secrets(o):
    from metaagent.workflow_task import resolve_runtime
    values = [os.environ.get(o.api_key_env, "")]
    for module in ("query", "screening", "coding", "synthesis"):
        values.append(resolve_runtime(o, module)[0].get("llm_api_key") or "")
    return list({v for v in values if v})


class _RedactingLog:
    def __init__(self, stream, secret):
        self.stream, self.secret = stream, secret

    def write(self, value):
        text = value
        for secret in ([self.secret] if isinstance(self.secret, str) else self.secret):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        if self.closed:
            # absl can retain the redirected stream until interpreter shutdown.
            # The original context owns its file and may already have closed it.
            return len(value)
        return self.stream.write(text)

    def flush(self):
        if not self.closed:
            self.stream.flush()

    def close(self):
        """Do not close caller-owned files or an original sys.stdout/stderr."""
        self.flush()

    @property
    def closed(self):
        return bool(getattr(self.stream, "closed", False))

    @property
    def encoding(self):
        return getattr(self.stream, "encoding", None) or "utf-8"

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self.stream, name)


