"""Independent synthesis using the same deterministic API as the workflow."""
from __future__ import annotations

import json
import contextlib
import csv
import os
import sys
from pathlib import Path

import click
import yaml

from .engine import run_analyses, run_synthesis, write_synthesis_artifacts
from metaagent.workflow import JsonOutputCommand


def read_estimates(path: Path) -> list[dict]:
    """Read structured estimates without bibliographic whitelist normalization."""
    if path.suffix.lower() == ".xlsx":
        import pandas as pd
        frame = pd.read_excel(path)
        return frame.astype(object).where(frame.notna(), None).to_dict("records")
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if path.suffix.lower() not in {".json", ".jsonl"}:
        raise ValueError("Estimate input must be XLSX, CSV, JSONL or JSON")
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    else:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        records = value if isinstance(value, list) else value.get("records", value.get("selected_estimates")) if isinstance(value, dict) else None
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("Estimate input must contain a list of JSON objects")
    return records


def _redact_protocol_diagnostics(result):
    """Redact protocol error text before CLI output/artifact serialization.

    Scientific values, source identities, decisions and protocol hashes remain
    unchanged. Only rejected-protocol diagnostic strings can echo invalid input.
    """
    from metaagent.workflow import _safe_error_message
    result["protocol_gaps"] = [_safe_error_message(ValueError(gap))
                               for gap in result.get("protocol_gaps", [])]
    for analysis in result.get("analyses", []):
        _redact_protocol_diagnostics(analysis)
    return result


@click.group()
def synthesis():
    """Analyze estimates with Pi, or run a deterministic explicit protocol."""


@synthesis.command("run", cls=JsonOutputCommand)
@click.option("--input", "input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--protocol", "protocol_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--llm-report", is_flag=True, help="Add validated artifact-bound explanation using SYNTHESIS runtime.")
@click.option("--llm-selection", is_flag=True, help="Add validated explanations of immutable selection decisions.")
@click.option("--json", "json_output", is_flag=True, help="Emit one JSON result; diagnostics go to stderr.")
@click.option("--output", type=click.Path(file_okay=False, path_type=Path), required=True)
def run(input_path: Path, protocol_path: Path, output: Path, llm_report: bool = False, llm_selection: bool = False, json_output: bool = False):
    """Run one protocol or a YAML/JSON protocol list using the shared engine.

    Example: metaagent synthesis run --input estimates.jsonl --protocol analysis.yaml --output runs/synthesis --json
    """
    from metaagent.workflow import _command_failure
    try:
        with contextlib.redirect_stdout(sys.stderr) if json_output else contextlib.nullcontext():
            configured = yaml.safe_load(protocol_path.read_text(encoding="utf-8-sig"))
            protocols = configured if isinstance(configured, list) else [configured]
            if not protocols or any(not isinstance(p, dict) for p in protocols):
                raise ValueError("Protocol must be an analysis object or a nonempty list of analysis objects")
            for protocol in protocols:
                if llm_report:
                    protocol["llm_report"] = True
                if llm_selection:
                    protocol["llm_selection"] = True
            records = read_estimates(input_path)
            if isinstance(configured, list):
                result = run_analyses(records, protocols)
            else:
                result = run_synthesis(records, protocols[0])
            _redact_protocol_diagnostics(result)
            paths = write_synthesis_artifacts(result, output)
    except Exception as exc:
        _command_failure(exc, json_output, suggestion="Fix the input JSONL or analysis YAML/JSON; then rerun synthesis run with the same explicit protocol.")
    if json_output:
        click.echo(json.dumps({**result, "artifacts": paths}, ensure_ascii=False, allow_nan=False))
    else:
        click.echo(f"{result['status']}: {output / 'synthesis_result.json'}")
    if result["status"] not in {"complete", "single_estimate"}:
        raise click.exceptions.Exit(1)


@synthesis.command("agent", cls=JsonOutputCommand)
@click.option("--input", "input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--research-question", required=True, help="Question the analysis must address; no expected reference values.")
@click.option("--review-context", "review_context_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None,
              help="Shared review/eligibility context as a JSON/YAML object; bound to planning and execution, without reference answers.")
@click.option("--method-source", "method_sources", multiple=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Explicit original methods, repeat for PDF/MD/TXT/HTML/DOCX. Optional; missing methods become declared exploratory assumptions.")
@click.option("--primary-source", "primary_sources", multiple=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Primary study PDF/MD/TXT/HTML/DOCX evidence; repeat per source, distinct from original review methods.")
@click.option("--protocol", "protocol_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None,
              help="Optional protocol as analysis context; Pi can plan without a prefilled AnalysisProtocol.")
@click.option("--output", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--max-executions", type=click.IntRange(1, 8), default=3, show_default=True, help="Maximum generated-code executions, including repairs.")
@click.option("--max-turns", type=click.IntRange(1, 100), default=12, show_default=True)
@click.option("--max-tokens", type=click.IntRange(1, 1000000), default=64000, show_default=True, help="Total bounded agent token budget.")
@click.option("--total-timeout-s", type=click.IntRange(1, 86400), default=900, show_default=True)
@click.option("--exec-timeout-s", type=click.IntRange(1, 3600), default=120, show_default=True)
@click.option("--pi-command", default=None, help="Pinned local Pi executable name/path; otherwise use SYNTHESIS_PI_COMMAND or PATH.")
@click.option("--model", default=None, help="Optional SYNTHESIS model override.")
@click.option("--api-base", default=None, help="Optional SYNTHESIS OpenAI-compatible endpoint override.")
@click.option("--api-key-env", default=None, help="Credential environment variable NAME; secrets are never CLI values.")
@click.option("--resume", is_flag=True, help="Continue a matching incomplete analysis; changed inputs never overwrite an existing result.")
@click.option("--dry-run", is_flag=True, help="Validate local inputs/runtime and show fingerprints; no model, code execution or output writes.")
@click.option("--json", "json_output", is_flag=True, help="Emit exactly one JSON document; diagnostics go to stderr.")
def agent(input_path, research_question, review_context_path, method_sources, primary_sources, protocol_path, output, max_executions, max_turns,
          max_tokens, total_timeout_s, exec_timeout_s, pi_command, model, api_base,
          api_key_env, resume, dry_run, json_output):
    """Plan → write code → execute → validate → repair with bounded Pi turns.

    Example: metaagent synthesis agent --input estimates.xlsx --research-question
    'What is the incubation period?' --method-source methods.pdf --output runs/analysis --json
    """
    from types import SimpleNamespace
    from metaagent.workflow import _command_failure
    from metaagent.workflow_task import resolve_synthesis, inspect_synthesis_settings
    from metaagent.config import load_llm_config, is_usable_secret
    try:
        with contextlib.redirect_stdout(sys.stderr) if json_output else contextlib.nullcontext():
            original_methods = {str(Path(p).resolve()) for p in method_sources}
            primary = {str(Path(p).resolve()) for p in primary_sources}
            if original_methods & primary:
                raise ValueError("A source cannot be declared as both original methods and a primary study")
            roles = {**{path: "original_methods" for path in original_methods},
                     **{path: "primary_study" for path in primary}}
            opts = SimpleNamespace(task_config=None, synthesis_backend="pi", research_question=research_question,
                method_sources=tuple(dict.fromkeys((*method_sources, *primary_sources))), synthesis_max_executions=max_executions, synthesis_max_turns=max_turns, synthesis_max_tokens=max_tokens,
                synthesis_total_timeout_s=total_timeout_s, synthesis_exec_timeout_s=exec_timeout_s, pi_command=pi_command)
            settings = resolve_synthesis(opts)
            inspection = inspect_synthesis_settings(settings)
            protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8-sig")) if protocol_path else None
            if protocol is not None and not isinstance(protocol, dict):
                raise ValueError("Pi accepts one optional protocol object; use the research question to request multiple analyses")
            review_context = yaml.safe_load(review_context_path.read_text(encoding="utf-8-sig")) if review_context_path else None
            if review_context_path and not isinstance(review_context, dict):
                raise ValueError("--review-context must contain a JSON/YAML object")
            # Validate the coding-table format before invoking any model. Keep
            # original input bytes/path available to the analysis workspace.
            read_estimates(input_path)
            from .pi_agent import pi_synthesis_fingerprint, run_pi_synthesis
            overrides = {"llm_" + key: value for key, value in (("model", model), ("api_base", api_base)) if value is not None}
            if api_key_env:
                import re
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
                    raise ValueError("--api-key-env must name an environment variable")
                from metaagent.config import load_runtime_env
                load_runtime_env(module_hint="synthesis")
                if not dry_run and not is_usable_secret(os.environ.get(api_key_env)):
                    raise ValueError(f"Missing credential environment variable {api_key_env}")
                overrides["llm_api_key"] = os.environ.get(api_key_env, "")
            cfg = load_llm_config(overrides, module_hint="synthesis")
            from .pi_runtime import synthesis_generation_binding
            public_runtime = synthesis_generation_binding(overrides, cfg=cfg)
            runtime = {"llm_" + key: getattr(cfg, key) for key in (
                "provider", "model", "api_key", "api_base", "temperature", "timeout_s", "max_tokens",
                "verify_ssl", "force_streaming", "reasoning_effort", "thinking")}
            runtime["llm_extra_body"] = public_runtime["extra_body"]
            fingerprint = pi_synthesis_fingerprint(input_path=input_path, research_question=research_question, review_context=review_context,
                method_sources=[Path(p) for p in settings["method_sources"]], source_roles=roles,
                protocol=protocol, settings=settings, runtime_overrides=runtime)
            if dry_run:
                import hashlib
                result = {"status": "planned", "backend": "pi", "input": str(input_path.resolve()),
                          "output": str(output.resolve()), "inspection": inspection, "fingerprint": fingerprint,
                          "runtime": public_runtime, "source_roles": roles,
                          "plan_sha256": hashlib.sha256(json.dumps({"agent": fingerprint, "runtime": public_runtime},
                              sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
            else:
                if not cfg.model or not cfg.api_base or not is_usable_secret(cfg.api_key):
                    raise ValueError("Incomplete SYNTHESIS runtime; configure its provider/model/endpoint/key")
                result = run_pi_synthesis(input_path=input_path, research_question=research_question, review_context=review_context,
                    method_sources=[Path(p) for p in settings["method_sources"]], source_roles=roles, output_dir=output,
                    protocol=protocol, settings=settings, runtime_overrides=runtime, resume=resume)
    except Exception as exc:
        _command_failure(exc, json_output,
            suggestion="Check the coding-table/method paths, pinned Pi installation and independent SYNTHESIS configuration; inspect existing agent receipts before retrying.")
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, allow_nan=False))
    else:
        click.echo(f"{result['status']}: {output}")
    if result["status"] not in {"planned", "complete", "single_estimate"}:
        raise click.exceptions.Exit(1)
