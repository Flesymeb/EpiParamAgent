from __future__ import annotations

import json
import hashlib
import dataclasses
import multiprocessing as mp
import queue
import threading
import os
import re
import signal
import sys
import shutil
import traceback
import time
import uuid
import math
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from contextlib import contextmanager
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
    configured = os.environ.get("METAAGENT_PAPER_POOL", "").strip()
    base = Path(configured).expanduser().resolve() if configured else _repo_root() / "paper_pool"
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
EXTRACTION_BACKENDS = ("llm", "langextract")


class LLMCallTimeoutError(TimeoutError):
    """Raised when a single LLM call exceeds the configured wall-clock budget."""


class EmptyModelContentError(RuntimeError):
    """The API returned no extractable text, even if reasoning tokens were billed."""


class LLMSubprocessError(RuntimeError):
    """Safe process error retaining HTTP classification for audited retry policy."""
    def __init__(self,message,*,status_code=None,retry_after_s=None,error_type=None):
        super().__init__(message)
        self.status_code=status_code
        self.retry_after_s=retry_after_s
        self.provider_error_type=error_type


def _retry_after_seconds(exc):
    """Read only a provider's delay field, never persist its opaque body/headers."""
    direct=getattr(exc,"retry_after_s",None)
    response=getattr(exc,"response",None)
    headers=getattr(response,"headers",{}) or {}
    raw=direct if direct is not None else headers.get("retry-after")
    if raw is None:
        body=getattr(exc,"body",None)
        if isinstance(body,dict):
            body=body.get("error",body)
            if isinstance(body,dict) and isinstance(body.get("details"),dict):
                raw=body["details"].get("retry_after")
    if raw is None:return None
    try:
        delay=float(raw)
    except (TypeError,ValueError):
        try:
            when=parsedate_to_datetime(str(raw))
            if when.tzinfo is None:when=when.replace(tzinfo=UTC)
            delay=(when-datetime.now(UTC)).total_seconds()
        except (TypeError,ValueError,OverflowError):return None
    return max(0.,delay) if math.isfinite(delay) else None


def _env_positive_int(*names: str) -> int | None:
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        try:
            parsed = int(value)
        except ValueError:
            continue
        if parsed > 0:
            return parsed
    return None


def _effective_max_input_chars(config_value: int | None) -> int:
    override = _env_positive_int("CODING_MAX_INPUT_CHARS", "CODING_FULLTEXT_MAX_CHARS")
    if override:
        return override
    return int(config_value or 500000)


def _llm_call_timeout_s() -> int | None:
    return _env_positive_int(
        "CODING_LLM_SUBPROCESS_TIMEOUT_S",
        "CODING_LLM_CALL_TIMEOUT_S",
        "CODING_LLM_TIMEOUT_S",
        "LLM_TIMEOUT_S",
    )


def _invoke_messages_worker(messages, llm_overrides, connection) -> None:
    """Spawn-safe worker: no inherited HTTP clients, locks or Queue feeder thread."""
    worker_model=None
    try:
        worker_model=init_llm(llm_overrides)
        response=worker_model.invoke(messages)
        connection.send({"ok":True,"content":response.content,
                         "usage":getattr(response,"usage_metadata",None),
                         "response_metadata":getattr(response,"response_metadata",None)})
    except BaseException as exc:
        configured_key=getattr(worker_model,"openai_api_key",None)
        if hasattr(configured_key,"get_secret_value"):configured_key=configured_key.get_secret_value()
        secret=str((llm_overrides or {}).get("llm_api_key") or configured_key or "")
        error=_redacted({"ok":False,"error_type":type(exc).__name__,"error":str(exc),
                         "traceback":traceback.format_exc(),
                         "status_code":getattr(exc,"status_code",None),
                         "retry_after_s":_retry_after_seconds(exc)},secret)
        try:connection.send(error)
        except (BrokenPipeError,EOFError,OSError):pass
    finally:
        connection.close()


def _receive_worker(connection, mailbox):
    """Drain large messages while the worker is still alive, under caller timeout."""
    try:mailbox.put(connection.recv())
    except (EOFError,OSError) as exc:
        mailbox.put({"ok":False,"transport_error":type(exc).__name__})
    except Exception as exc:
        mailbox.put({"ok":False,"transport_error":type(exc).__name__})
    finally:connection.close()


def _isolated_model_result(messages, overrides, timeout_s, *, pmid, stage_name):
    # fork from Web workers can inherit thread-owned locks and active HTTP state.
    # spawn imports clean code; only messages/config and one write endpoint cross.
    ctx=mp.get_context("spawn")
    receiving,sending=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_invoke_messages_worker,args=(messages,overrides,sending))
    mailbox=queue.Queue(maxsize=1)
    reader=None
    started=time.monotonic()
    try:
        process.start()
        sending.close()
        # A reader thread makes the deadline cover the complete recv/unpickle,
        # not just the availability of a pipe header for a multi-megabyte payload.
        reader=threading.Thread(target=_receive_worker,args=(receiving,mailbox),daemon=True)
        reader.start()
        try:result=mailbox.get(timeout=max(0.001,timeout_s-(time.monotonic()-started)))
        except queue.Empty:
            raise LLMCallTimeoutError(f"{stage_name} LLM subprocess timed out after {timeout_s}s for PMID {pmid}") from None
        process.join(min(1,max(0,timeout_s-(time.monotonic()-started))))
        if result.get("transport_error"):
            raise RuntimeError(f"{stage_name} LLM subprocess exited without a result for PMID {pmid}")
        return result
    finally:
        sending.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate();process.join(1)
                if process.is_alive():process.kill();process.join(1)
            process.close()
        # The receiver owns its endpoint. Closing it concurrently in this thread
        # can double-close a reused FD and mask the original model timeout.
        if reader is not None:reader.join(1)
        else:receiving.close()


def _invoke_model_content_once(
    *,
    model,
    messages: list[dict[str, str]],
    llm_overrides: dict[str, object] | None,
    pmid: str,
    stage_name: str,
    telemetry: dict | None = None,
) -> str:
    timeout_s = _llm_call_timeout_s()
    isolated_timeout_s=_env_positive_int("CODING_LLM_SUBPROCESS_TIMEOUT_S")
    if isolated_timeout_s is None and threading.current_thread() is not threading.main_thread():
        # SIGALRM is unavailable in Web/background threads. Preserve an explicit
        # configured call cap using the same isolated transport instead.
        isolated_timeout_s=timeout_s
    if isolated_timeout_s:
        result=_isolated_model_result(messages,llm_overrides,isolated_timeout_s,pmid=pmid,stage_name=stage_name)
        if result.get("ok"):
            if telemetry is not None:
                telemetry.update(usage=result.get("usage"),response_metadata=result.get("response_metadata"))
            return str(result.get("content",""))
        raise LLMSubprocessError(f"{stage_name} LLM subprocess failed for PMID {pmid}: "
                           f"{result.get('error_type')}: {result.get('error')}\n{result.get('traceback','')}",
                           status_code=result.get("status_code"),retry_after_s=result.get("retry_after_s"),error_type=result.get("error_type"))

    response_format=(llm_overrides or {}).get('_coding_response_format')
    if response_format:
        model=model.bind(extra_body={**(getattr(model,'extra_body',None) or {}),'response_format':response_format})
    with _llm_call_timeout(timeout_s, pmid=pmid, stage_name=stage_name):
        resp = model.invoke(messages)
    if telemetry is not None:
        telemetry.update(usage=getattr(resp, "usage_metadata", None), response_metadata=getattr(resp, "response_metadata", None))
    return str(resp.content)


def _redacted(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).casefold() in {"api_key", "authorization"} else _redacted(v, secret) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted(v, secret) for v in value]
    return value


def _invoke_model_content(
    *, model, messages, llm_overrides, pmid, stage_name,
) -> str:
    """Call the configured client, retaining raw responses and every retry attempt."""
    from metaagent.coding.llm import _env_int

    overrides = llm_overrides or {}
    audit_path = overrides.get("_coding_call_log")
    configured_key = getattr(model, "openai_api_key", None)
    if hasattr(configured_key, "get_secret_value"):
        configured_key = configured_key.get_secret_value()
    secret = str(overrides.get("llm_api_key") or configured_key or "")
    budget = _env_int("CODING_LLM_MAX_RETRIES", "LLM_MAX_RETRIES", default=3)
    request_hash = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    for attempt in range(budget + 1):
        started = time.perf_counter()
        event = {"pmid": pmid if str(pmid).isdigit() else None, "record_id": overrides.get("_coding_record_id") or ("pmid:" + str(pmid) if str(pmid).isdigit() else None), "stage": stage_name, "attempt": attempt + 1, "retry_index": attempt, "max_retries": budget, "started_at": datetime.now(UTC).isoformat(), "request_sha256": request_hash, "request_chars": sum(len(str(m.get("content", ""))) for m in messages), "model": overrides.get("llm_model"), "api_base": overrides.get("llm_api_base")}
        event.update(configured_http_timeout_s=overrides.get("llm_timeout_s"),
                     call_deadline_s=_llm_call_timeout_s(),
                     explicit_process_deadline_s=_env_positive_int("CODING_LLM_SUBPROCESS_TIMEOUT_S"),
                     isolation_start_method="spawn" if _env_positive_int("CODING_LLM_SUBPROCESS_TIMEOUT_S") or (threading.current_thread() is not threading.main_thread() and _llm_call_timeout_s()) else None)
        if overrides.get('_coding_response_format'):
            contract=overrides['_coding_response_format']
            event['response_format']={'type':contract['type'],'name':contract.get('json_schema',{}).get('name'),'schema_sha256':hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()}
        telemetry = {}
        retry = False
        retry_delay = 0.
        try:
            content = _invoke_model_content_once(model=model, messages=messages, llm_overrides=llm_overrides, pmid=pmid, stage_name=stage_name, telemetry=telemetry)
            if not content.strip():
                event.update(raw_response=content, **telemetry)
                raise EmptyModelContentError("Model returned empty content; inspect finish_reason and reasoning/output token usage, or explicitly configure the endpoint thinking policy/output budget")
            event.update(status="ok", raw_response=content, **telemetry)
            return content
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            deterministic_error=isinstance(exc,(ValueError,TypeError)) or getattr(exc,"provider_error_type",None) in {"ValueError","TypeError","ImportError","ModuleNotFoundError"}
            retry = not isinstance(exc, EmptyModelContentError) and not deterministic_error and attempt < budget and (status_code is None or status_code in {408, 409, 425, 429} or status_code >= 500)
            provider_delay=_retry_after_seconds(exc)
            # Do not sleep indefinitely on an extreme provider delay. A terminal
            # failure is safer than sending another request before its cooldown.
            if provider_delay is not None and provider_delay > (_env_positive_int("CODING_LLM_RETRY_MAX_WAIT_S") or 120):retry=False
            if retry:retry_delay=max(min(0.5 * 2**attempt, 4),provider_delay or 0.)
            event.update(status="retrying" if retry else "error", error_type=type(exc).__name__, error=str(exc), status_code=status_code,
                         provider_retry_after_s=provider_delay,retry_delay_s=retry_delay if retry else None)
            if not retry:
                if secret and secret in str(exc):
                    # Sidecar error payloads and traceback writers downstream
                    # must not receive an exception that contains credentials.
                    raise RuntimeError(str(exc).replace(secret, "[REDACTED]")) from None
                raise
        finally:
            event["wall_time_ms"] = round((time.perf_counter() - started) * 1000, 3)
            if audit_path:
                path = Path(str(audit_path))
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(_redacted(event, secret), ensure_ascii=False, default=str) + "\n")
        if retry:
            time.sleep(retry_delay)
    raise RuntimeError("Unreachable retry state")


@contextmanager
def _llm_call_timeout(timeout_s: int | None, *, pmid: str, stage_name: str):
    if not timeout_s or not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handle_timeout(_signum, _frame):
        raise LLMCallTimeoutError(f"{stage_name} LLM call timed out after {timeout_s}s for PMID {pmid}")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


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
    name = f"PMID_{pmid}" if str(pmid).isdigit() else "document_" + hashlib.sha256(str(pmid).encode()).hexdigest()[:20]
    return md_dir / name / "fulltext.md"


def _load_markdown_from_pdf(pdf_path: Path, pmid: str) -> str:
    from tools.mineru.cache import parse_pdf

    return parse_pdf(pdf_path, pmid if str(pmid).isdigit() else None).text


def _iter_inputs(input_path: Path, fetch_strategy: str = "pmc_only"):
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        yield input_path
        return
    if input_path.is_file() and input_path.suffix.lower() == ".txt":
        pmids = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines()]
        pmids = [p for p in pmids if p and not p.startswith("#")]
        if not pmids:
            return
        if any(not pmid.isdigit() for pmid in pmids):
            raise ValueError("PMID lists must contain numeric IDs, one per line. For plain-text full text use --document-manifest (or a Markdown .md file).")
        from metaagent.acquisition import resolve_document
        from tools.mineru.cache import pool_root
        acquisition_dir = pool_root() / "acquisition_attempts" / uuid.uuid4().hex
        resolved, failed = [], []
        for pmid in pmids:
            outcome = resolve_document({"record_id": "pmid:" + pmid, "pmid": pmid}, acquisition_dir,
                                       parse=False, cache_policy="strict")
            if outcome.get("record_status") != "pdf_ready":
                failed.append((pmid, outcome.get("failure_reason")))
            else:
                alias = pool_root() / "pdfs" / f"PMID_{pmid}.pdf"
                canonical = Path(outcome["pdf_path"])
                if alias.is_file() and hashlib.sha256(alias.read_bytes()).hexdigest() == outcome["pdf_sha256"]:
                    resolved.append(alias)
                else:
                    # Preserve the requested identifier without consuming or
                    # overwriting a rejected legacy PMID alias.
                    local_copy = acquisition_dir / f"PMID_{pmid}.pdf"
                    local_copy.write_bytes(canonical.read_bytes())
                    resolved.append(local_copy)
        if failed:
            raise RuntimeError("Full text unavailable for requested PMID(s): " +
                               "; ".join(pmid + ": " + str(reason) for pmid, reason in failed) +
                               ". Per-record acquisition receipts: " + str(acquisition_dir))
        yield from resolved
        return
    if input_path.is_dir():
        documents=sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in {".pdf",".md"})
        pdf_stems={(p.parent,p.stem.casefold()) for p in documents if p.suffix.lower()==".pdf"}
        for path in documents:
            if path.suffix.lower()==".md" and (path.parent,path.stem.casefold()) in pdf_stems:continue
            yield path
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
    llm_overrides: dict[str, object] | None = None,
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
    content = _invoke_model_content(
        model=model,
        messages=messages,
        llm_overrides=llm_overrides,
        pmid=pmid,
        stage_name="index",
    )
    return _parse_json_object(content)


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
    llm_overrides: dict[str, object] | None = None,
    backend: str = "llm",
    evidence_dir: Path | None = None,
    document_id: str | None = None,
    source_pmid: str | None = None,
) -> list[dict]:
    if backend not in EXTRACTION_BACKENDS:
        raise ValueError(f"Unknown extraction backend: {backend}")
    if backend == "langextract":
        from .langextract_backend import extract_with_langextract

        def invoke(messages):
            return _invoke_model_content(
                model=model, messages=messages, llm_overrides=llm_overrides,
                pmid=title.removeprefix("PMID "), stage_name="extract",
            )

        return extract_with_langextract(
            fulltext=fulltext, tables_summary=tables_summary,
            was_truncated=was_truncated, title=title, abstract=abstract,
            index_json=index_json, config=config, invoke=invoke,
            evidence_dir=evidence_dir,
            document_id=document_id, source_pmid=source_pmid,
        )
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
    pmid = title.removeprefix("PMID ")
    content = _invoke_model_content(
        model=model,
        messages=messages,
        llm_overrides=llm_overrides,
        pmid=pmid,
        stage_name="extract",
    )
    return parse_json_records(content)


def load_document_manifest(path: Path) -> list[dict]:
    """Load explicit document identities; no numeric identifier is fabricated."""
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        data = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Document manifest must be a JSON list or JSONL rows")
    seen = set()
    result = []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("Every document manifest row must be an object")
        identity = str(row.get("record_id") or "").strip()
        pmid = str(row.get("pmid") or "").strip()
        declared_path = row.get("path") or row.get("fulltext_path")
        source = Path(str(declared_path)) if declared_path else None
        if source is not None and not source.is_absolute():
            source = path.parent / source
        if not identity or identity in seen:
            raise ValueError("Document manifest requires unique nonempty record_id")
        if pmid and not pmid.isdigit():
            raise ValueError("Document manifest pmid must be real numeric PMID or null")
        if source is not None and (not source.is_file() or source.suffix.lower() not in {".md", ".txt", ".pdf"}):
            raise ValueError(f"Document is unavailable or unsupported: {source}")
        if source is None and not (pmid or row.get("doi") or row.get("fulltext_url") or row.get("url") or identity.startswith(("pmid:","doi:"))):
            raise ValueError("Identity-only document requires PMID, DOI or an explicit public PDF URL")
        seen.add(identity)
        supplements=[]
        seen_sources={"main"}
        declared_supplements = row.get("supplements") or []
        if not isinstance(declared_supplements, list):
            raise ValueError("Document supplements must be a list of paths or objects")
        for index,item in enumerate(declared_supplements):
            item={"path":item} if isinstance(item,str) else item
            if not isinstance(item, dict):
                raise ValueError("Every supplement must be a path or object")
            supplemental=Path(str(item["path"])) if item.get("path") else None
            if supplemental is not None and not supplemental.is_absolute():supplemental=path.parent/supplemental
            sid=str(item.get("source_id") or f"supplement-{index+1}")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*",sid):
                raise ValueError("Supplement source_id must be a safe stable identifier")
            if sid in seen_sources:raise ValueError("Duplicate document source_id")
            seen_sources.add(sid)
            if supplemental is not None and (not supplemental.is_file() or supplemental.suffix.lower() not in {".pdf",".md",".txt"}):
                raise ValueError(f"Supplement unavailable or unsupported: {supplemental}")
            if supplemental is None and not (item.get("pmid") or item.get("doi") or item.get("fulltext_url") or item.get("url")):
                raise ValueError("Identity-only supplement requires PMID, DOI or a public PDF URL")
            supplements.append({**item,"path":supplemental.resolve() if supplemental is not None else None,"source_id":sid,"role":item.get("role","supplement")})
        result.append({**row,"record_id": identity, "pmid": pmid or None, "path": source.resolve() if source is not None else None, "title": str(row.get("title") or ""), "supplements":supplements})
    return result


def _publish_coding_call_counts(out_dir, file_tag, record_id):
    """Expose actual logged provider attempts separately from logical scan passes."""
    path=out_dir/"documents"/file_tag/"coverage.json"
    log=out_dir/"llm_calls.jsonl"
    if not path.is_file():return
    coverage=json.loads(path.read_text())
    events=[json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.is_file() else []
    for stage in ("stage_a","stage_b"):
        coverage[stage+"_logged_provider_attempts"]=sum(e.get("record_id")==record_id and e.get("stage")==stage for e in events)
    path.write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+"\n")


def resolve_coding_documents(documents: list[dict], directory: Path) -> list[dict]:
    """Acquire identity-only primary/supplement declarations through one resolver.

    All per-source outcomes are published before a missing source raises; no
    subset of an explicitly requested manifest is presented as a complete run.
    Explicit local unlabelled PDFs/text keep the original upload semantics.
    """
    from metaagent.acquisition import resolve_document
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    prepared, outcomes, failures = [], [], []
    for document in documents:
        item = dict(document)
        sources = [("main", item), *((s["source_id"], s) for s in item.get("supplements", []))]
        supplements = []
        for source_id, source in sources:
            path = source.get("path")
            needs_acquisition = path is None or (Path(path).suffix.lower() == ".pdf" and bool(source.get("pmid") or source.get("doi")))
            if needs_acquisition:
                record = {**source, "record_id": item["record_id"] if source_id == "main" else item["record_id"] + ":supplement:" + source_id}
                if path is not None:
                    record["path"] = str(path)
                outcome = resolve_document(record, directory, cache_policy="strict")
                outcomes.append({"parent_record_id": item["record_id"], "source_id": source_id, **outcome})
                if outcome.get("record_status") != "fulltext_ready":
                    failures.append(item["record_id"] + "/" + source_id + ": " + str(outcome.get("failure_reason")))
                    continue
                descriptor = {k: outcome.get(k) for k in ("source_sha256", "pdf_path", "pdf_sha256", "parser_route", "parser_fingerprint", "registry_path", "article_boundary_hint")}
                if source_id == "main":
                    item.update(path=Path(outcome["fulltext_path"]), acquired_source=descriptor,
                                pmid=outcome.get("pmid") or (outcome.get("identity_verification") or {}).get("expected", {}).get("pmid"))
                else:
                    supplements.append({**source, **descriptor, "path": Path(outcome["fulltext_path"])})
            elif source_id != "main":
                supplements.append(source)
        item["supplements"] = supplements
        prepared.append(item)
    (directory / "acquisition_manifest.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in outcomes), encoding="utf-8")
    if failures:
        raise RuntimeError("Declared Coding source(s) unavailable: " + "; ".join(failures) + ". See " + str(directory / "acquisition_manifest.jsonl"))
    return prepared


def read_document_sources(document: dict) -> list[dict]:
    """Read the main report and declared supplements via shared PDF/Markdown input.

    Paths are expected absolute, as returned by load_document_manifest. The helper
    is reusable by full-text screening so it sees the same declared source bundle.
    """
    sources=[]
    entries=[{**(document.get("acquired_source") or {}),"path":document["path"],"source_id":"main","role":"main"},*document.get("supplements",[])]
    for entry in entries:
        path=Path(entry["path"])
        source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix.lower()==".pdf":
            from tools.mineru.cache import parse_pdf
            parsed=parse_pdf(path,document.get("pmid") if entry["source_id"]=="main" else None,cache_policy="strict")
            text=parsed.text;route=parsed.route;fingerprint=parsed.parser_fingerprint
        else:
            text=read_text(path);route=entry.get("parser_route") or "provided_text";fingerprint=entry.get("parser_fingerprint")
            source_hash=entry.get("source_sha256") or source_hash
        sources.append({"source_id":entry["source_id"],"role":entry.get("role","supplement"),"text":text,"path":str(path.resolve()),
                        "source_sha256":source_hash,"markdown_sha256":hashlib.sha256(text.encode()).hexdigest(),
                        "parser_route":route,"parser_fingerprint":fingerprint,
                        **({"article_boundary_hint":entry["article_boundary_hint"]} if entry.get("article_boundary_hint") else {}),
                        **({"pdf_path":entry["pdf_path"],"pdf_sha256":entry.get("pdf_sha256")} if entry.get("pdf_path") else {})})
    return sources


def _claim_extraction_output(out_dir, *, backend, ablation):
    """An extraction directory belongs to one invocation, never two ablations."""
    claim=out_dir/"coding_output_owner.json"
    occupied=claim.exists() or any((out_dir/name).exists() for name in ("coding_estimates.jsonl","llm_calls.jsonl","documents","evidence")) or any(out_dir.glob("run_manifest*.json")) or any(out_dir.glob("coding_sheet*.xlsx"))
    if occupied:
        raise ValueError(f"Coding output directory is already used: {out_dir}. Choose a fresh --out for each invocation/ablation; existing records and call audits were preserved.")
    try:
        with claim.open("x",encoding="utf-8") as handle:
            json.dump({"invocation_id":uuid.uuid4().hex,"created_at":datetime.now(UTC).isoformat(),"backend":backend,"ablation":ablation},handle,indent=2)
    except FileExistsError:
        raise ValueError(f"Coding output directory was claimed concurrently: {out_dir}; use a fresh --out.") from None


def run_pipeline(
    input_path: Path,
    out_dir: Path,
    stage: str,
    codebook_path: Path,
    fetch_strategy: str = "pmc_only",
    llm_overrides: dict[str, object] | None = None,
    skip_stage_a: bool = False,
    extraction_backend: str = "langextract",
    document_manifest: Path | None = None,
    ablation: str = "full",
    chunk_chars: int | None = None,
    extraction_scope: str | None = None,
    stage_a_empty_retries: int = 1,
    review_context: dict | None = None,
) -> None:
    from metaagent.coding.stages import ABLATIONS, DOMAIN_GUIDE_SHA256
    from metaagent.coding.prompt_context import normalize_review_context
    review_context = normalize_review_context(review_context)
    if skip_stage_a:
        if ablation not in {"full", "without_a"}:
            raise ValueError("skip_stage_a conflicts with ablation")
        ablation = "without_a"
    if ablation not in ABLATIONS:
        raise ValueError(f"Unknown coding ablation: {ablation}")
    if extraction_backend not in EXTRACTION_BACKENDS:
        raise ValueError(f"Unknown extraction backend: {extraction_backend}")
    if extraction_backend == "langextract" and ablation != "without_a" and stage in {"extract", "both"}:
        from .langextract_backend import require_langextract

        require_langextract()
    if stage!="fetch":
        effect_config=load_config(codebook_path)
        # Reject invalid local scientific schema/budgets before claiming outputs
        # or constructing a provider client.
        from metaagent.coding.schema.config_loader import create_model_from_config
        create_model_from_config(effect_config)
        if stage_a_empty_retries not in {0,1,2}:
            raise ValueError("stage_a_empty_retries must be between zero and two")
        if chunk_chars is not None and chunk_chars<256:
            raise ValueError("chunk_chars must be at least 256")
        if review_context is not None:
            effect_config.parameters["review_context"] = review_context
        effect_config.parameters["stage_a_empty_retries"] = stage_a_empty_retries
        if extraction_scope:
            effect_config.parameters["extraction_scope"] = extraction_scope
    out_dir.mkdir(parents=True, exist_ok=True)
    if stage in {"extract","both"}:
        _claim_extraction_output(out_dir,backend=extraction_backend,ablation=ablation)
    llm_overrides = {**(llm_overrides or {}), "_coding_call_log": str(out_dir / "llm_calls.jsonl")}

    # ── Phase 0: fetch-only ──────────────────────────────────────────────────
    # Download missing PDFs and warm the MinerU markdown cache.
    # No LLM calls; useful as a pre-flight before a full extraction run.
    if stage == "fetch":
        fetched = []
        if document_manifest:
            fetched = resolve_coding_documents(load_document_manifest(document_manifest), out_dir / "acquisition")
            inputs = [row["path"] for row in fetched]
        else:
            inputs = list(_iter_inputs(input_path, fetch_strategy=fetch_strategy))
        if not inputs:
            raise RuntimeError(
                f"No full-text inputs could be resolved from {input_path}. "
                "Check the PMID list and paper_pool fetch status."
            )
        pdf_dir, md_dir = _paper_pool_dirs()
        cached = warmed = pdf_count = 0
        metadata_by_path = {str(row["path"]): row for row in fetched}
        for path in inputs:
            metadata = metadata_by_path.get(str(path), {})
            pmid = metadata.get("pmid") or infer_pmid_from_path(path)
            label = "PMID_" + pmid if pmid else metadata.get("record_id") or "Document " + path.name
            acquired = metadata.get("acquired_source") or {}
            if path.suffix.lower() in {".md", ".txt"}:
                pdf_count += bool(acquired.get("pdf_path"))
                if acquired.get("parser_route") == "mineru_parsed":
                    warmed += 1
                    print(f"  [MinerU]   {label} — parsed")
                else:
                    cached += 1
                    print(f"  [MD cache] {label} ✓")
                continue
            pdf_count += 1
            from tools.mineru.cache import parse_pdf
            result = parse_pdf(path, pmid if str(pmid).isdigit() else None, cache_policy="strict")
            if result.route != "mineru_parsed":
                cached += 1
                print(f"  [MD cache] {label} ✓")
            else:
                print(f"  [MinerU]   {label} — parsed")
                warmed += 1
        print(f"\n[fetch] Done. Documents={len(inputs)}  Local PDF={pdf_count}  Text/cache={cached}  MinerU parsed={warmed}")
        return

    # ── Phase 1+2: LLM extraction ────────────────────────────────────────────
    index_dir = out_dir / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    model = init_llm(llm_overrides)
    # Legacy index remains explicitly available, but is not the new extraction A.
    prompts_dir = codebook_path.resolve().parents[1] / "coding_prompts"
    stage_a_schema = prompts_dir / "stage_a.yaml"
    if stage == "index":
        if not stage_a_schema.exists():
            raise FileNotFoundError(f"Legacy index schema not found: {stage_a_schema}")
        stage_a_config = load_config(stage_a_schema)
        if not _apply_stage_prompt_from_codebook(effect_config, "stage_a", stage_a_config):
            _apply_prompt_override(stage_a_config, prompts_dir / "stage_a.py")
        _inject_codebook_context(stage_a_config, effect_config)
    else:
        stage_a_config = effect_config
    records: list[dict] = []
    source_records: list[dict] = []
    completeness_reports: list[dict] = []
    index_rows: list[dict] = []
    errors: list[dict] = []
    xlsx_path: Path | None = None
    max_input_chars = _effective_max_input_chars(effect_config.extraction.max_input_chars)
    if max_input_chars != effect_config.extraction.max_input_chars:
        print(
            f"[coding] max_input_chars override: "
            f"{effect_config.extraction.max_input_chars} -> {max_input_chars}"
        )

    documents = load_document_manifest(document_manifest) if document_manifest else [
        {"path": path, "pmid": infer_pmid_from_path(path), "record_id": "pmid:" + infer_pmid_from_path(path) if infer_pmid_from_path(path) else "file:" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20], "title": ""}
        for path in _iter_inputs(input_path, fetch_strategy=fetch_strategy)
    ]
    documents = resolve_coding_documents(documents, out_dir / "acquisition")
    inputs = [row["path"] for row in documents]
    if len({row["record_id"] for row in documents}) != len(documents):
        raise ValueError("Inputs resolve to duplicate report identities. Use --document-manifest with one main document and explicit supplements per record_id.")
    if not inputs:
        raise RuntimeError(
            f"No full-text inputs could be resolved from {input_path}. "
            "Run 'metaagent pdf fetch' and inspect fetch_results.csv."
        )

    for document in documents:
        path = document["path"]
        source_pmid = document["pmid"]
        pmid = source_pmid or "NR"
        record_id = document["record_id"]
        document_llm_overrides = {**llm_overrides, "_coding_record_id": record_id}
        file_tag = "PMID_" + source_pmid if source_pmid else "doc_" + hashlib.sha256(record_id.encode()).hexdigest()[:20]
        try:
            document_sources = read_document_sources(document)
            markdown = document_sources[0]["text"]
            source_records.extend({"record_id":record_id,**{key:value for key,value in source.items() if key!="text"}} for source in document_sources)
        except Exception as exc:
            _write_paper_error(out_dir, file_tag, "load_fulltext", exc)
            errors.append({"record_id": record_id, "pmid": source_pmid, "stage": "load_fulltext", "error": str(exc)})
            print(f"  [WARN] PMID {pmid}: full-text load failed: {exc}")
            continue

        max_chars = max_input_chars
        trunc_marker = effect_config.extraction.truncation_marker
        processed = process_fulltext(markdown, max_chars=max_chars, truncation_marker=trunc_marker)
        fulltext = processed.content
        tables_summary = processed.tables_summary

        title = document["title"] or (f"PMID {pmid}" if source_pmid else f"Document {record_id}")
        abstract = ""

        if stage == "index" and not skip_stage_a:
            index_path = index_dir / f"{file_tag}.index.json"
            source_hash = hashlib.sha256(fulltext.encode()).hexdigest()
            index_config_hash = hashlib.sha256(json.dumps({"codebook": codebook_path.read_text(), "stage_a": dataclasses.asdict(stage_a_config), "model": llm_overrides.get("llm_model"), "api_base": llm_overrides.get("llm_api_base"), "temperature": llm_overrides.get("llm_temperature"), "coding_extra_body": json.loads(os.environ.get("CODING_LLM_EXTRA_BODY_JSON") or "null"), "llm_rate_limit": {key: os.environ.get(key) for key in ("METAAGENT_LLM_REQUESTS_PER_MINUTE", "METAAGENT_LLM_RATE_STATE_PATH")}}, sort_keys=True, default=str).encode()).hexdigest()
            cached_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
            reusable_index = cached_index.get("source_sha256") == source_hash and cached_index.get("index_config_sha256") == index_config_hash and cached_index.get("record_id") == record_id
            if reusable_index:
                index_envelope = cached_index
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
                        llm_overrides=document_llm_overrides,
                    )
                    index_payload = index_obj.get("index") if isinstance(index_obj, dict) else None
                    index_envelope = {"pmid": source_pmid, "record_id": record_id, "source_sha256": source_hash, "index_config_sha256": index_config_hash, "index": index_payload or index_obj}
                    index_path.write_text(
                        json.dumps(index_envelope, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    _write_paper_error(out_dir, file_tag, "index", exc)
                    errors.append({"record_id": record_id, "pmid": source_pmid, "stage": "index", "error": str(exc)})
                    continue
            index_schema = _get_index_schema(effect_config)
            if index_schema:
                index_rows.append(_build_index_row(pmid, index_envelope, index_schema))
        else:
            index_obj = {}

        if stage in ("extract", "both"):
            try:
                from metaagent.coding.stages import run_stages

                def invoke_coding(stage_name, messages):
                    from metaagent.coding.response_contracts import stage_request_overrides
                    request_overrides=stage_request_overrides(document_llm_overrides,stage_name,messages)
                    return _invoke_model_content(
                        model=model, messages=messages,
                        llm_overrides=request_overrides,
                        pmid=pmid, stage_name=stage_name,
                    )

                def extract_candidates(block, candidate_config):
                    # LangExtract is an implementation of A, never a separate arm.
                    from .langextract_backend import extract_with_langextract
                    return extract_with_langextract(
                        fulltext="\n".join(segment["text"] for segment in block.get("segments",[{"text":block["text"]}])), tables_summary="", was_truncated=False,
                        title=title, abstract=abstract, index_json="{}",
                        config=candidate_config,
                        invoke=lambda messages: invoke_coding("stage_a", messages),
                        evidence_dir=out_dir / "evidence" / file_tag / block["block_id"] / f"pass-{block.get('candidate_pass',0)}",
                        document_id=record_id, source_pmid=source_pmid,
                    )

                record_objs = run_stages(
                    text=markdown, config=effect_config, record_id=record_id,
                    pmid=source_pmid, invoke=invoke_coding,
                    output_dir=out_dir / "documents" / file_tag,
                    ablation=ablation, document_sources=document_sources, stage_a_empty_retries=stage_a_empty_retries,
                    chunk_chars=chunk_chars or min(max_input_chars, 24000),
                    extract_a=extract_candidates if extraction_backend == "langextract" else None,
                )
            except Exception as exc:
                _publish_coding_call_counts(out_dir,file_tag,record_id)
                _write_paper_error(out_dir, file_tag, "extract", exc)
                errors.append({"record_id": record_id, "pmid": source_pmid, "stage": "extract", "error": str(exc)})
                continue
            _publish_coding_call_counts(out_dir,file_tag,record_id)
            completeness_path = out_dir / "documents" / file_tag / "completeness.json"
            if completeness_path.is_file():
                completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
                completeness_reports.append({"record_id": record_id, "artifact": str(completeness_path.resolve()),
                    **{key: completeness[key] for key in ("audit_version", "status", "signal_count", "unresolved_signal_count", "source_processing_complete")}})
            if not record_objs:
                print(f"  [WARN] PMID {pmid}: Coding returned 0 records")
            for record_obj in record_objs or []:
                record_obj["pmid"] = pmid
                record_obj["record_id"] = record_id
                records.append(record_obj)

    # Lossless structured data is authoritative; Excel is a review/export view.
    structured_path = out_dir / "coding_estimates.jsonl"
    source_manifest_path = out_dir / "source_manifest.jsonl"
    source_manifest_path.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in source_records),encoding="utf-8")
    structured_path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str)+"\n" for r in records), encoding="utf-8")
    completeness_summary_path = out_dir / "coding_completeness.json"
    completeness_summary_path.write_text(json.dumps({"schema_version": "1", "documents": completeness_reports,
        "documents_needing_review": sum(item["status"] == "needs_review" for item in completeness_reports),
        "unresolved_signal_count": sum(item["unresolved_signal_count"] for item in completeness_reports),
        "scope": "supplied_sources_only_not_proof_of_semantic_completeness"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if records:
        xlsx_path, _ = export_records(
            records,
            out_dir,
            basename="coding_sheet",
            column_order=[f.name for f in effect_config.fields] if effect_config.fields else None,
        )
    elif stage in {"extract", "both"}:
        import pandas as pd
        xlsx_path = out_dir / "coding_sheet_empty.xlsx"
        pd.DataFrame(columns=[f.name for f in effect_config.fields]).to_excel(xlsx_path, index=False)

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
            "skip_stage_a": ablation == "without_a",
            "ablation": ablation,
            "chunk_chars": chunk_chars or min(max_input_chars, 24000),
            "extraction_backend": extraction_backend,
            "extraction_scope": extraction_scope,
            "review_context": review_context,
            "stage_a_empty_retries": stage_a_empty_retries,
            "document_manifest": str(document_manifest) if document_manifest else None,
            "coding_llm_extra_body": json.loads(os.environ.get("CODING_LLM_EXTRA_BODY_JSON") or "null"),
            "llm_rate_limit": {key: os.environ.get(key) for key in ("METAAGENT_LLM_REQUESTS_PER_MINUTE", "METAAGENT_LLM_RATE_STATE_PATH")},
            "llm_deadline_environment": {key: os.environ.get(key) for key in ("CODING_LLM_SUBPROCESS_TIMEOUT_S", "CODING_LLM_CALL_TIMEOUT_S", "CODING_LLM_TIMEOUT_S", "LLM_TIMEOUT_S")},
            "codebook": str(codebook_path.resolve()),
            "stage_a_config": str(getattr(stage_a_config, "_config_path", "")),
            "coding_domain_guide": {"version": "1", "sha256": DOMAIN_GUIDE_SHA256},
        },
        inputs=[input_path, codebook_path, getattr(stage_a_config, "_config_path", ""), document_manifest] if document_manifest else [input_path, codebook_path, getattr(stage_a_config, "_config_path", "")],
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
            "coding_estimates_path": str(structured_path.resolve()),
            "coding_completeness_path": str(completeness_summary_path.resolve()),
            "coding_unresolved_source_signals": sum(item["unresolved_signal_count"] for item in completeness_reports),
            "source_manifest_path": str(source_manifest_path.resolve()),
            "max_input_chars": max_input_chars,
            "skip_stage_a": ablation == "without_a",
            "ablation": ablation,
            "chunk_chars": chunk_chars or min(max_input_chars, 24000),
            "llm_call_timeout_s": _llm_call_timeout_s(),
            "extraction_backend": extraction_backend,
            "extraction_scope": extraction_scope,
            "review_context": review_context,
            "stage_a_empty_retries": stage_a_empty_retries,
            "review_record_count": sum(bool(r.get("needs_review")) for r in records),
        },
    )
    print(f"[OK] Manifest written: {manifest_path}")
    if errors:
        raise RuntimeError(
            f"Coding is incomplete: {len(errors)} processing error(s) across "
            f"{len(inputs)} full-text input(s). Partial outputs were retained; "
            f"inspect {out_dir / 'errors'} and rerun before pooling."
        )
