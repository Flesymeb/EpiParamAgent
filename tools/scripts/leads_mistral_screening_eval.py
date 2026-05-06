#!/usr/bin/env python3
"""Run a deliberately rough LEADS-Mistral screening evaluation.

This script is intentionally independent from the main screening engine: it uses
one short binary prompt and the OpenAI-compatible /chat/completions API exposed
by vLLM. It reads disease screening profile YAML files and the canonical/legacy
evaluation CSV layouts used by this repository.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILES_BY_DISEASE = {
    "covid19": [
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
        "P10",
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
        "P16",
        "P17",
    ],
    "mpox": [
        "MP4",
        "MP5",
        "MP6",
        "MP7",
        "MP8",
        "MP9",
        "MP10",
        "MP11",
        "MP12",
    ],
}

RESULT_FIELDS = [
    "llm_suggest",
    "overall_score",
    "overall_justification",
    "include",
    "confidence",
    "screening_stage",
    "screening_mode",
    "screening_strategy",
    "screening_profile",
    "screening_topic",
    "screening_disease",
    "model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "wall_time_ms",
    "parse_error",
    "api_error",
    "disease_score",
    "disease_justification",
    "population_score",
    "population_justification",
    "location_score",
    "location_justification",
    "evidence_score",
    "evidence_justification",
    "parameter_score",
    "parameter_justification",
]


@dataclass(frozen=True)
class ScreeningProfile:
    id: str
    topic: str
    disease: str
    project_number: int
    research_question: str
    disease_focus: str
    disease_exclude: str
    parameter_focus: str
    parameter_exclude: str
    thresholds: dict[str, Any]
    policies: dict[str, Any]

    @property
    def project_dir_name(self) -> str:
        return f"p{self.project_number}"

    @property
    def project_file_stem(self) -> str:
        return f"project_{self.project_number}"


def normalize_key(value: str) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_profiles(project_root: Path, disease: str) -> dict[str, ScreeningProfile]:
    profile_dir = project_root / "configs" / normalize_key(disease) / "screening_profiles"
    if not profile_dir.exists():
        raise FileNotFoundError(f"Missing profile directory: {profile_dir}")

    registry: dict[str, ScreeningProfile] = {}
    for yaml_file in sorted(profile_dir.glob("*.yaml")):
        if yaml_file.stem.startswith("_"):
            continue
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        topic = normalize_key(data.get("topic") or yaml_file.stem)
        disease_key = normalize_key(data.get("disease") or disease)
        defaults = data.get("defaults", {}) or {}
        default_thresholds = defaults.get("thresholds", {}) or {}
        default_policies = defaults.get("policies", {}) or {}

        for profile_id, raw_profile in (data.get("profiles", {}) or {}).items():
            raw_profile = raw_profile or {}
            profile_key = str(profile_id).strip().upper()
            thresholds = merge_dict(default_thresholds, raw_profile.get("thresholds", {}) or {})
            policies = merge_dict(default_policies, raw_profile.get("policies", {}) or {})
            registry[profile_key] = ScreeningProfile(
                id=profile_key,
                topic=topic,
                disease=disease_key,
                project_number=int(raw_profile["project_number"]),
                research_question=str(raw_profile["research_question"]),
                disease_focus=str(raw_profile.get("disease_focus", "COVID-19 OR SARS-CoV-2")),
                disease_exclude=str(raw_profile.get("disease_exclude", "none")),
                parameter_focus=str(raw_profile.get("parameter_focus", "target parameter")),
                parameter_exclude=str(raw_profile.get("parameter_exclude", "none")),
                thresholds=thresholds,
                policies=policies,
            )
    return registry


def resolve_profile_paths(project_root: Path, profile: ScreeningProfile, experiment: str) -> dict[str, Path]:
    canonical_base_dir = (
        project_root
        / "evaluation"
        / "screening"
        / profile.disease
        / "GT_1"
        / "GT_export"
        / profile.topic
    )
    legacy_base_dir = project_root / "evaluation" / profile.disease / profile.topic / "ground_truth"
    base_dir = canonical_base_dir
    legacy_project_dir = legacy_base_dir / profile.project_dir_name
    canonical_project_dir = canonical_base_dir / profile.project_dir_name
    if legacy_project_dir.exists() and not canonical_project_dir.exists():
        base_dir = legacy_base_dir

    project_dir = base_dir / profile.project_dir_name
    output_dir = project_dir / "experiments" / experiment if experiment else project_dir
    stem = profile.project_file_stem
    return {
        "project_dir": project_dir,
        "raw_file": project_dir / f"{stem}_raw.csv",
        "ground_truth_file": project_dir / f"{stem}_groundtruth.csv",
        "screened_file": output_dir / f"{stem}_screened.csv",
        "checkpoint_file": output_dir / f"{stem}_predictions.jsonl",
        "metrics_file": output_dir / "metrics.json",
    }


def set_csv_field_limit() -> None:
    try:
        csv.field_size_limit(sys.maxsize)
    except (AttributeError, ValueError, OverflowError):
        try:
            csv.field_size_limit(2**31 - 1)
        except (AttributeError, ValueError, OverflowError):
            pass


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    set_csv_field_limit()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    for key in RESULT_FIELDS:
        if key not in fieldnames:
            fieldnames.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def get_field(row: dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        if name in row and row[name] is not None:
            return str(row[name])
    lower_map = {str(k).lower(): k for k in row.keys()}
    for name in names:
        key = lower_map.get(name.lower())
        if key is not None and row.get(key) is not None:
            return str(row[key])
    return default


def get_pmid(row: dict[str, Any], fallback: str) -> str:
    pmid = get_field(row, "PMID", "pmid", "gt_pmid").strip()
    return pmid or fallback


def truncate_text(text: str, max_chars: int) -> str:
    text = " ".join(str(text or "").split())
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " ... [truncated]"


def load_ground_truth_pmids(path: Path) -> set[str]:
    pmids: set[str] = set()
    if not path.exists():
        return pmids
    for idx, row in enumerate(read_csv_rows(path), start=1):
        pmid = get_pmid(row, fallback=f"GTROW{idx}")
        if pmid.isdigit():
            pmids.add(pmid)
    return pmids


def normalize_base_url(base_url: str) -> str:
    value = str(base_url).strip().rstrip("/")
    suffix = "/chat/completions"
    if value.endswith(suffix):
        value = value[: -len(suffix)].rstrip("/")
    return value


def build_messages(profile: ScreeningProfile, row: dict[str, Any], *, abstract_max_chars: int) -> list[dict[str, str]]:
    title = truncate_text(get_field(row, "Title", "title"), 1200)
    abstract = truncate_text(get_field(row, "Abstract", "abstract"), abstract_max_chars)
    if not abstract:
        abstract = "(No abstract.)"

    # Keep this deliberately rough: the goal is a simple LEADS-Mistral baseline,
    # not the stronger hand-engineered prompts used by the main screening engine.
    user = f"""
Task: quick screen for a {profile.disease} review.
Question: {profile.research_question}
Title: {title}
Abstract: {abstract}

Be strict. Include only if the title/abstract clearly looks directly useful for the question.
If it is vague, off-topic, review/editorial/protocol, or only mentions the topic, exclude it.
JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    return [{"role": "user", "content": user}]


def extract_json_object(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty response")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(text[start : idx + 1])
                if isinstance(parsed, dict):
                    return parsed
                break
    raise ValueError("could not parse JSON object")


def normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "include", "included", "eligible", "relevant", "1"}:
        return True
    if text in {"false", "no", "n", "exclude", "excluded", "ineligible", "irrelevant", "0"}:
        return False
    if (
        "exclude" in text
        or "ineligible" in text
        or "irrelevant" in text
        or "not include" in text
        or "not relevant" in text
    ):
        return False
    if "include" in text or "eligible" in text or "relevant" in text:
        return True
    return None


def parse_prediction(content: str, *, possible_confidence_threshold: float) -> dict[str, Any]:
    parse_error = ""
    try:
        data = extract_json_object(content)
    except Exception as exc:
        data = {}
        parse_error = str(exc)

    include_value = None
    for key in ("include", "included", "eligible", "relevant", "decision", "answer"):
        if key in data:
            include_value = data.get(key)
            break
    include = normalize_bool(include_value)
    if include is None:
        include = False
        parse_error = parse_error or f"could not normalize include value: {include_value!r}"

    raw_confidence = data.get("confidence", data.get("certainty", None))
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))

    reason = str(
        data.get("reason")
        or data.get("justification")
        or data.get("rationale")
        or data.get("explanation")
        or ""
    ).strip()
    if not reason and parse_error:
        reason = f"Parse error: {parse_error}"

    if include:
        label = "possible_candidate" if confidence < possible_confidence_threshold else "strong_candidate"
    else:
        label = "unlikely_candidate"

    return {
        "include": include,
        "confidence": confidence,
        "reason": reason[:1000],
        "llm_suggest": label,
        "parse_error": parse_error,
        "parsed_json": data,
    }


def error_prediction(error: str) -> dict[str, Any]:
    return {
        "include": False,
        "confidence": 0.0,
        "reason": f"API error: {error[:500]}",
        "llm_suggest": "error",
        "parse_error": "",
        "api_error": error[:1000],
        "parsed_json": {},
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "wall_time_ms": 0,
        "raw_response": "",
    }


async def check_server(client: Any, base_url: str, api_key: str, model: str) -> None:
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Could not reach vLLM server at {url}: {exc}") from exc

    try:
        payload = response.json()
        served_ids = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    except Exception:
        served_ids = []
    if served_ids and model not in served_ids:
        print(f"WARN: requested model {model!r} not found in /models: {served_ids}")


async def call_chat_completion(
    client: Any,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    response_format_json: bool,
    retries: int,
) -> tuple[str, dict[str, Any]]:
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        started = time.perf_counter()
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            wall_ms = round((time.perf_counter() - started) * 1000, 1)
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {}) or {}
            usage["wall_time_ms"] = wall_ms
            return str(content), usage
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(min(8.0, 0.8 * (2 ** (attempt - 1))))
    raise RuntimeError(str(last_error) if last_error else "unknown chat completion error")


def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return predictions
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            pmid = str(item.get("pmid") or "").strip()
            if pmid:
                predictions[pmid] = item
    return predictions


def apply_prediction(
    row: dict[str, Any],
    prediction: dict[str, Any],
    *,
    profile: ScreeningProfile,
    model: str,
    save_raw_response: bool,
) -> dict[str, Any]:
    updated = dict(row)
    include = bool(prediction.get("include", False))
    confidence = prediction.get("confidence", 0.0)
    llm_suggest = str(prediction.get("llm_suggest") or ("strong_candidate" if include else "unlikely_candidate"))
    if llm_suggest == "strong_candidate":
        overall_score = 4
    elif llm_suggest == "possible_candidate":
        overall_score = 2
    else:
        overall_score = 0

    updated.update(
        {
            "llm_suggest": llm_suggest,
            "overall_score": overall_score,
            "overall_justification": str(prediction.get("reason") or ""),
            "include": str(include).lower(),
            "confidence": confidence,
            "screening_stage": "title_abstract",
            "screening_mode": "simple_prompt",
            "screening_strategy": "leads_mistral_simple",
            "screening_profile": profile.id,
            "screening_topic": profile.topic,
            "screening_disease": profile.disease,
            "model": model,
            "prompt_tokens": int(prediction.get("prompt_tokens") or 0),
            "completion_tokens": int(prediction.get("completion_tokens") or 0),
            "total_tokens": int(prediction.get("total_tokens") or 0),
            "wall_time_ms": prediction.get("wall_time_ms") or 0,
            "parse_error": str(prediction.get("parse_error") or ""),
            "api_error": str(prediction.get("api_error") or ""),
            # Empty dimension scores make it explicit that this is binary screening.
            "disease_score": "",
            "disease_justification": "",
            "population_score": "",
            "population_justification": "",
            "location_score": "",
            "location_justification": "",
            "evidence_score": "",
            "evidence_justification": "",
            "parameter_score": "",
            "parameter_justification": "",
        }
    )
    if save_raw_response:
        updated["raw_response"] = str(prediction.get("raw_response") or "")
    return updated


def is_relevant_label(label: str) -> bool:
    return str(label).strip() in {"strong_candidate", "possible_candidate"}


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def matthews_corrcoef(tp: int, fp: int, fn: int, tn: int) -> float:
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denom == 0:
        return 0.0
    return ((tp * tn) - (fp * fn)) / denom


def compute_metrics(ground_truth_pmids: set[str], screened_rows: list[dict[str, Any]]) -> dict[str, Any]:
    screened_by_pmid: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(screened_rows, start=1):
        pmid = get_pmid(row, fallback=f"ROW{idx}")
        screened_by_pmid[pmid] = row

    tp = fp = fn = tn = 0
    strong = possible = unlikely = error_count = missing = 0

    for pmid in ground_truth_pmids:
        row = screened_by_pmid.get(pmid)
        if row is None:
            fn += 1
            missing += 1
            continue
        label = str(row.get("llm_suggest") or "")
        if label == "strong_candidate":
            tp += 1
            strong += 1
        elif label == "possible_candidate":
            tp += 1
            possible += 1
        else:
            fn += 1
            if label == "error":
                error_count += 1
            else:
                unlikely += 1

    for pmid, row in screened_by_pmid.items():
        if pmid in ground_truth_pmids:
            continue
        label = str(row.get("llm_suggest") or "")
        if is_relevant_label(label):
            fp += 1
        else:
            tn += 1
            if label == "error":
                error_count += 1

    pool = len(screened_by_pmid)
    recall = safe_div(tp, tp + fn)
    precision = safe_div(tp, tp + fp)
    specificity = safe_div(tn, tn + fp)
    npv = safe_div(tn, tn + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    accuracy = safe_div(tp + tn, tp + fp + fn + tn)
    workload_reduction = safe_div(tn + fn, pool)
    nns = safe_div(tp + fp, tp) if tp else math.inf
    return {
        "ground_truth_count": len(ground_truth_pmids),
        "screened_count": pool,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "strong_count": strong,
        "possible_count": possible,
        "unlikely_count": unlikely,
        "missing_count": missing,
        "error_count": error_count,
        "recall": round(recall, 6),
        "precision": round(precision, 6),
        "specificity": round(specificity, 6),
        "npv": round(npv, 6),
        "f1": round(f1, 6),
        "accuracy": round(accuracy, 6),
        "workload_reduction": round(workload_reduction, 6),
        "nns": None if math.isinf(nns) else round(nns, 6),
        "mcc": round(matthews_corrcoef(tp, fp, fn, tn), 6),
        "wss95": round(workload_reduction - 0.05, 6),
    }


async def screen_one(
    client: Any,
    row: dict[str, Any],
    *,
    profile: ScreeningProfile,
    args: argparse.Namespace,
) -> dict[str, Any]:
    pmid = get_pmid(row, fallback="")
    messages = build_messages(profile, row, abstract_max_chars=args.abstract_max_chars)
    try:
        content, usage = await call_chat_completion(
            client,
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            response_format_json=args.response_format_json,
            retries=args.retries,
        )
        prediction = parse_prediction(
            content,
            possible_confidence_threshold=args.possible_confidence_threshold,
        )
        prediction.update(
            {
                "pmid": pmid,
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "wall_time_ms": usage.get("wall_time_ms") or 0,
                "api_error": "",
                "raw_response": content,
            }
        )
        return prediction
    except Exception as exc:
        prediction = error_prediction(str(exc))
        prediction["pmid"] = pmid
        return prediction


async def run_profile(
    client: Any,
    profile: ScreeningProfile,
    paths: dict[str, Path],
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not paths["raw_file"].exists():
        return {
            "profile": profile.id,
            "topic": profile.topic,
            "project": profile.project_number,
            "status": "missing_raw",
            "raw_file": str(paths["raw_file"]),
            "screened_file": str(paths["screened_file"]),
        }

    raw_rows = read_csv_rows(paths["raw_file"])
    if args.limit and args.limit > 0:
        raw_rows = raw_rows[: args.limit]
    normalized_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(raw_rows, start=1):
        if get_field(row, "PMID", "pmid", "gt_pmid").strip():
            normalized_rows.append(row)
        else:
            row_with_id = dict(row)
            row_with_id["PMID"] = f"ROW{idx}"
            normalized_rows.append(row_with_id)
    raw_rows = normalized_rows

    paths["screened_file"].parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path = paths["checkpoint_file"]
    predictions = load_checkpoint(checkpoint_path) if args.resume else {}

    pending: list[dict[str, Any]] = []
    for idx, row in enumerate(raw_rows, start=1):
        pmid = get_pmid(row, fallback=f"ROW{idx}")
        existing = predictions.get(pmid)
        if existing and existing.get("llm_suggest") != "error":
            continue
        pending.append(row)

    print(
        f"[{profile.id}] {profile.topic} | raw={len(raw_rows)} "
        f"resume={len(predictions)} pending={len(pending)}"
    )

    checkpoint_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    completed = 0
    started = time.perf_counter()

    async def worker(row: dict[str, Any]) -> None:
        nonlocal completed
        async with args.semaphore:
            prediction = await screen_one(client, row, profile=profile, args=args)
        pmid = get_pmid(row, fallback="")
        predictions[pmid] = prediction
        async with checkpoint_lock:
            with checkpoint_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(prediction, ensure_ascii=False) + "\n")
        async with progress_lock:
            completed += 1
            if completed == len(pending) or completed % max(1, args.log_every) == 0:
                elapsed = max(0.001, time.perf_counter() - started)
                print(f"[{profile.id}] {completed}/{len(pending)} done ({completed / elapsed:.2f}/s)")

    if pending and not args.dry_run:
        await asyncio.gather(*(worker(row) for row in pending))

    screened_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(raw_rows, start=1):
        pmid = get_pmid(row, fallback=f"ROW{idx}")
        prediction = predictions.get(pmid)
        if prediction is None:
            prediction = error_prediction("not run")
            prediction["pmid"] = pmid
        screened_rows.append(
            apply_prediction(
                row,
                prediction,
                profile=profile,
                model=args.model,
                save_raw_response=args.save_raw_response,
            )
        )

    if not args.dry_run:
        write_csv_rows(paths["screened_file"], screened_rows)

    gt_pmids = load_ground_truth_pmids(paths["ground_truth_file"])
    if gt_pmids:
        metrics = compute_metrics(gt_pmids, screened_rows)
        metrics.update(
            {
                "profile": profile.id,
                "topic": profile.topic,
                "project": profile.project_number,
                "model": args.model,
                "experiment": args.experiment,
                "raw_file": str(paths["raw_file"]),
                "ground_truth_file": str(paths["ground_truth_file"]),
                "screened_file": str(paths["screened_file"]),
            }
        )
        if not args.dry_run:
            paths["metrics_file"].write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        status = "ok"
    else:
        metrics = {
            "profile": profile.id,
            "topic": profile.topic,
            "project": profile.project_number,
            "status": "missing_ground_truth",
            "raw_file": str(paths["raw_file"]),
            "ground_truth_file": str(paths["ground_truth_file"]),
            "screened_file": str(paths["screened_file"]),
        }
        status = "missing_ground_truth"

    summary = {"status": status, **metrics}
    print_profile_summary(summary)
    return summary


def print_profile_summary(summary: dict[str, Any]) -> None:
    status = summary.get("status", "ok")
    profile = summary.get("profile")
    topic = summary.get("topic")
    if status != "ok":
        print(f"[{profile}] {topic} | {status}")
        return
    print(
        f"[{profile}] recall={summary.get('recall'):.3f} "
        f"precision={summary.get('precision'):.3f} "
        f"f1={summary.get('f1'):.3f} "
        f"TP/FP/FN/TN={summary.get('tp')}/{summary.get('fp')}/{summary.get('fn')}/{summary.get('tn')}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate LEADS-Mistral-7B-v1 with a deliberately rough screening prompt."
    )
    parser.add_argument("--project-root", default=".", help="Repository root")
    parser.add_argument("--disease", default="covid19", help="Disease profile namespace")
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=None,
        help="Profile IDs to run. Defaults: COVID-19 13 tasks; mpox 9 tasks. Use 'all' for all configured profiles.",
    )
    parser.add_argument(
        "--experiment",
        default="",
        help="Experiment name. Defaults to leads_mistral_simple_<timestamp>.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LEADS_ENDPOINT")
        or os.getenv("LLM_API_BASE")
        or os.getenv("OPENAI_API_BASE")
        or "http://127.0.0.1:8000/v1",
        help="OpenAI-compatible API base URL, e.g. http://127.0.0.1:8000/v1",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LEADS_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "testtoken",
        help="API key for the OpenAI-compatible endpoint; vLLM accepts any non-empty value.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_MODEL") or "zifeng-ai/leads-mistral-7b-v1",
        help="Served model name configured in vLLM.",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--log-every", type=int, default=25)
    parser.add_argument("--abstract-max-chars", type=int, default=5000)
    parser.add_argument("--limit", type=int, default=0, help="Smoke-test limit per profile; 0 means no limit")
    parser.add_argument("--possible-confidence-threshold", type=float, default=0.7)
    parser.add_argument("--response-format-json", action="store_true", help="Send response_format=json_object to vLLM")
    parser.add_argument("--save-raw-response", action="store_true", help="Also store raw model output in the screened CSV")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--check-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verify-ssl", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fail-on-missing", action="store_true", help="Exit non-zero if any raw/GT file is missing")
    parser.add_argument("--dry-run", action="store_true", help="Resolve profiles and paths without calling the model")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    args.base_url = normalize_base_url(args.base_url)
    if not args.experiment:
        args.experiment = "leads_mistral_simple_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    profiles = load_profiles(project_root, args.disease)
    disease_key = normalize_key(args.disease)
    requested_profiles = args.profiles or DEFAULT_PROFILES_BY_DISEASE.get(disease_key) or ["all"]
    requested = [p.upper() for p in requested_profiles]
    if requested == ["ALL"]:
        selected = sorted(profiles.values(), key=lambda p: p.project_number)
    else:
        missing = [p for p in requested if p not in profiles]
        if missing:
            raise KeyError(f"Unknown profiles: {missing}. Available: {sorted(profiles)}")
        selected = [profiles[p] for p in requested]

    aggregate_dir = project_root / "evaluation" / "experiments" / args.experiment / "screening" / normalize_key(args.disease)
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    run_config = {
        "experiment": args.experiment,
        "model": args.model,
        "base_url": args.base_url,
        "profiles": [p.id for p in selected],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "concurrency": args.concurrency,
        "limit": args.limit,
        "response_format_json": args.response_format_json,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (aggregate_dir / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

    if args.dry_run:
        summaries: list[dict[str, Any]] = []
        for profile in selected:
            paths = resolve_profile_paths(project_root, profile, args.experiment)
            print(
                f"[{profile.id}] raw={paths['raw_file']} gt={paths['ground_truth_file']} "
                f"out={paths['screened_file']}"
            )
            summaries.append(
                {
                    "profile": profile.id,
                    "topic": profile.topic,
                    "project": profile.project_number,
                    "status": "dry_run",
                    "raw_file": str(paths["raw_file"]),
                    "ground_truth_file": str(paths["ground_truth_file"]),
                    "screened_file": str(paths["screened_file"]),
                }
            )
        write_summary_csv(aggregate_dir / "summary.csv", summaries)
        (aggregate_dir / "summary.json").write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSummary: {aggregate_dir / 'summary.csv'}")
        return 0

    try:
        import httpx
    except ImportError:
        print("ERROR: httpx is not installed. Run `pip install -e .` in the project environment.", file=sys.stderr)
        return 1

    timeout = httpx.Timeout(args.timeout_s)
    limits = httpx.Limits(max_keepalive_connections=max(1, args.concurrency), max_connections=max(1, args.concurrency * 2))
    args.semaphore = asyncio.Semaphore(max(1, args.concurrency))

    summaries: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout, verify=args.verify_ssl, limits=limits) as client:
        if args.check_server:
            await check_server(client, args.base_url, args.api_key, args.model)
        for profile in selected:
            paths = resolve_profile_paths(project_root, profile, args.experiment)
            summaries.append(await run_profile(client, profile, paths, args=args))

    write_summary_csv(aggregate_dir / "summary.csv", summaries)
    (aggregate_dir / "summary.json").write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSummary: {aggregate_dir / 'summary.csv'}")

    if args.fail_on_missing and any(str(s.get("status")) in {"missing_raw", "missing_ground_truth"} for s in summaries):
        return 2
    return 0


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        raise_code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise_code = 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise_code = 1
    raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
