"""Application task configuration and independent module runtime resolution.

Tasks contain protocols, never reference answers. Benchmark profiles are an
optional adapter to the same runner, not a prerequisite for using the application.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from metaagent.config import is_usable_secret, load_llm_config


class ModuleRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str | None = None
    model: str | None = None
    api_base: str | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    timeout_s: int | None = Field(default=None, gt=0)
    force_streaming: bool | None = None
    reasoning_effort: str | None = None
    thinking: Literal["enabled", "disabled"] | None = None
    extra_body: dict | None = None



class CodingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["llm", "langextract"] = "langextract"
    chunk_chars: int = Field(default=24000, ge=256)
    extraction_scope: str | None = None
    stage_a_empty_retries: int = Field(default=1, ge=0, le=2)


class SynthesisSettings(BaseModel):
    """Explicit opt-in keeps historical deterministic tasks reproducible."""
    model_config = ConfigDict(extra="forbid")
    backend: Literal["pi", "deterministic"] = "deterministic"
    research_question: str | None = None
    method_sources: list[str] = Field(default_factory=list)
    max_executions: int = Field(default=3, ge=1, le=8)
    max_turns: int = Field(default=12, ge=1, le=100)
    max_tokens: int = Field(default=64000, ge=1, le=1000000)
    total_timeout_s: int = Field(default=900, ge=1, le=86400)
    exec_timeout_s: int = Field(default=120, ge=1, le=3600)
    pi_command: str | None = None


class ReviewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1"] = "1"
    task_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    disease: str
    topic: str
    research_question: str
    codebook: str
    review_protocol: dict
    analysis_protocol: dict | None = None
    analysis_protocols: list[dict] = Field(default_factory=list)
    coding: CodingSettings = Field(default_factory=CodingSettings)
    synthesis: SynthesisSettings = Field(default_factory=SynthesisSettings)
    search: dict[str, str] = Field(default_factory=dict)
    llm: dict[Literal["query", "screening", "coding", "synthesis"], ModuleRuntime] = Field(default_factory=dict)
    start_date: str | None = None
    end_date: str | None = None


def read_task(path: Path) -> ReviewTask:
    """Validate a declarative YAML/JSON task without contacting any service."""
    task = ReviewTask.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    from metaagent.screening.protocol import validate_protocol
    validate_protocol(task.review_protocol)
    from tools.literature.cli import SOURCES
    if set(task.search) - set(SOURCES):
        raise ValueError("Task search contains an unsupported source")
    if any(not q.strip() for q in task.search.values()):
        raise ValueError("Each source needs a nonempty native query")
    if task.analysis_protocol and task.analysis_protocols:
        raise ValueError("Use analysis_protocol or analysis_protocols, not both")
    ids = [p.get("analysis_id") for p in task.analysis_protocols]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Multiple analyses require unique nonempty analysis_id values")
    return task


def resolve_runtime(options, module: str, *, require_credentials: bool = False) -> tuple[dict, dict]:
    """Resolve explicit task/CLI overrides over the module's environment profile.

    Returns invocation parameters (private) and a credential-free fingerprint.
    """
    task = read_task(Path(options.task_config)) if options.task_config else None
    spec = task.llm.get(module, ModuleRuntime()) if task else ModuleRuntime()
    params = {"llm_" + k: v for k, v in spec.model_dump(exclude_none=True).items() if k != "api_key_env"}
    # Global CLI overrides remain available, but are no longer required.
    for key, value in (("model", options.model), ("api_base", options.api_base), ("temperature", options.temperature)):
        if value is not None:
            params["llm_" + key] = value
    key_env = spec.api_key_env
    if key_env:
        params["llm_api_key"] = os.environ.get(key_env, "")
    elif options.model or options.api_base:
        key_env = options.api_key_env
        if os.environ.get(key_env):
            params["llm_api_key"] = os.environ[key_env]
    cfg = load_llm_config(params, module_hint=module)
    if require_credentials:
        if key_env and not is_usable_secret(os.environ.get(key_env)):
            raise ValueError(f"Missing credential environment variable {key_env}")
        if not cfg.model or not cfg.provider or not cfg.api_base or not is_usable_secret(cfg.api_key):
            raise ValueError(f"Incomplete {module} runtime; configure its module profile or task llm settings")
    invocation = {"llm_" + key: getattr(cfg, key) for key in (
        "provider", "model", "api_key", "api_base", "temperature", "timeout_s",
        "max_tokens", "verify_ssl", "force_streaming", "reasoning_effort", "thinking")}
    from metaagent.config import resolve_extra_body
    import hashlib, json
    body = resolve_extra_body(params, module_hint=module)
    if body is not None:
        invocation["llm_extra_body"] = body
    public = {k: v for k, v in invocation.items() if k not in {"llm_api_key", "llm_extra_body"}}
    # Vendor bodies can contain private extensions; never echo their values.
    # The canonical content hash still binds every effective transport option.
    public["extra_body_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest() if body is not None else None
    public["api_key_env"] = key_env or f"{module.upper()}_LLM_API_KEY (or provider environment)"
    return invocation, public


def resolve_coding(options) -> dict:
    task = read_task(Path(options.task_config)) if options.task_config else None
    cfg = task.coding.model_dump() if task else CodingSettings().model_dump()
    if options.extraction_backend is not None:
        cfg["backend"] = options.extraction_backend
    if options.chunk_chars is not None:
        cfg["chunk_chars"] = options.chunk_chars
    if getattr(options, "stage_a_empty_retries", None) is not None:
        cfg["stage_a_empty_retries"] = options.stage_a_empty_retries
    return cfg


def resolve_synthesis(options, *, task=None, task_dir=None, research_question=None) -> dict:
    """Resolve task/profile settings and explicit CLI overrides without services."""
    task_path = getattr(options, "task_config", None)
    if task is None and task_path:
        task = read_task(Path(task_path))
    if isinstance(task, ReviewTask):
        cfg = task.synthesis.model_dump()
        inherited_question = task.research_question
    else:
        raw = task or {}
        cfg = SynthesisSettings.model_validate(raw.get("synthesis") or {}).model_dump()
        inherited_question = raw.get("research_question") or (raw.get("v1_project") or {}).get("research_question")
    base = Path(task_dir or (Path(task_path).resolve().parent if task_path else Path.cwd()))
    sources = [(base / Path(value)).resolve() for value in cfg["method_sources"]]
    sources.extend(Path(value).resolve() for value in (getattr(options, "method_sources", None) or ()))
    for field, attr in (("backend", "synthesis_backend"), ("max_executions", "synthesis_max_executions"), ("max_turns", "synthesis_max_turns"),
                        ("max_tokens", "synthesis_max_tokens"), ("total_timeout_s", "synthesis_total_timeout_s"),
                        ("exec_timeout_s", "synthesis_exec_timeout_s"), ("pi_command", "pi_command")):
        value = getattr(options, attr, None)
        if value is not None:
            cfg[field] = value
    cfg["research_question"] = (getattr(options, "research_question", None) or cfg["research_question"]
                                or research_question or inherited_question)
    cfg["method_sources"] = list(dict.fromkeys(str(path) for path in sources))
    cfg["pi_command"] = cfg["pi_command"] or os.environ.get("SYNTHESIS_PI_COMMAND") or None
    return SynthesisSettings.model_validate(cfg).model_dump()


def inspect_synthesis_settings(settings: dict, *, require_runtime: bool = True) -> dict:
    """Inspect Pi locally; never run its CLI, models or document converters."""
    settings = SynthesisSettings.model_validate(settings).model_dump()
    if settings["backend"] != "pi":
        return {"backend": "deterministic"}
    if not (settings["research_question"] or "").strip():
        raise ValueError("Pi synthesis needs a research_question in the task or --research-question")
    sources = {}
    import hashlib
    for value in settings["method_sources"]:
        path = Path(value)
        if not path.is_file():
            raise ValueError(f"Method source is missing or not a file: {path}")
        if path.suffix.lower() not in {".pdf", ".md", ".txt", ".html", ".htm", ".docx"}:
            raise ValueError(f"Unsupported method-source format: {path.suffix}; use PDF/MD/TXT/HTML/DOCX")
        sources[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    from metaagent.synthesis.pi_runtime import inspect_pi_runtime
    runtime = inspect_pi_runtime(settings["pi_command"])
    if require_runtime and (not runtime.get("available") or runtime.get("compatible") is False):
        raise ValueError("Pi runtime is unavailable or incompatible: " + str(runtime.get("error") or "install the pinned Pi runtime"))
    return {"backend": "pi", "method_source_sha256": sources, "runtime": runtime,
            "protocol_required": False, "validation_scope": "Local files, runtime metadata and limits only; no model/code execution"}


def validate_task_files(path: Path, *, codebook_override=None, backend_override=None,
                        check_codebook: bool = True, check_analyses: bool = True,
                        check_backend: bool = True, analysis_override=None, synthesis_options=None) -> dict:
    """Validate the files needed by selected CLI stages, without API calls or writes.

    The core synthesis engine supplies protocol guards; empty input-dependent
    selection-ID gaps are deferred until execution, not treated as bad protocols.
    """
    import importlib.util
    from metaagent.coding.schema.config_loader import load_config, create_model_from_config
    from metaagent.synthesis import AnalysisProtocol, run_synthesis
    task = read_task(path)
    backend = backend_override or task.coding.backend
    book = Path(codebook_override).resolve() if codebook_override else (path.resolve().parent / task.codebook).resolve()
    result = {"status": "valid", "task_id": task.task_id, "task_schema": "valid",
              "codebook": "not_checked", "analyses": [], "coding_backend": backend,
              "backend_installed": None,
              "validation_scope": "Local task/protocol/codebook structure and backend discovery only; does not verify gold, original SR methods, credentials or service availability."}
    if check_codebook:
        config = load_config(book)
        if not config.fields:
            raise ValueError(f"Codebook has no extraction fields: {book}")
        if len({field.name for field in config.fields}) != len(config.fields):
            raise ValueError("Codebook field names must be unique")
        create_model_from_config(config)
        result["codebook"] = "valid"
    if check_analyses:
        configured = yaml.safe_load(Path(analysis_override).read_text(encoding="utf-8")) if analysis_override else (task.analysis_protocols or task.analysis_protocol)
        protocols = configured if isinstance(configured, list) else [configured] if isinstance(configured, dict) else []
        settings = resolve_synthesis(synthesis_options or SimpleNamespace(task_config=path))
        result["synthesis"] = inspect_synthesis_settings(settings)
        if settings["backend"] == "pi":
            if len(protocols) > 1:
                raise ValueError("Pi synthesis accepts one optional protocol; describe multiple analyses in the research question")
            result["analyses"] = [{"schema_status": "agent_planned", "protocol_supplied": bool(protocols)}]
        elif not protocols:
            raise ValueError("Synthesis requires analysis_protocol or nonempty analysis_protocols; supply the protocol or plan only the earlier independent stages")
        identities = []
        for protocol in protocols if settings["backend"] == "deterministic" else []:
            validated = AnalysisProtocol.model_validate(protocol)
            # Reuse all method/unit/filter/independence/uncertainty guards from the
            # real dispatcher. Existence of selected IDs requires actual inputs.
            checked = run_synthesis([], protocol)
            gaps = [gap for gap in checked["protocol_gaps"] if not gap.startswith("Selection IDs are absent from input:")]
            if gaps:
                raise ValueError(f"Analysis {validated.analysis_id}: " + "; ".join(gaps))
            identities.append(validated.analysis_id)
            result["analyses"].append({"analysis_id": validated.analysis_id, "schema_status": "valid"})
        if len(set(identities)) != len(identities):
            raise ValueError("Multiple analyses require unique analysis_id values")
    if check_backend:
        installed = backend != "langextract" or importlib.util.find_spec("langextract") is not None
        result["backend_installed"] = installed
        if not installed:
            raise ValueError("LangExtract backend is not installed; install the langextract project extra or explicitly select coding.backend=llm")
    return result
