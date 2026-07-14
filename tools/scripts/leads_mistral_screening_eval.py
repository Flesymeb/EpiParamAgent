#!/usr/bin/env python3
"""Run a simple LEADS-Mistral screening evaluation.

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
from typing import Any, Iterable

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

PROMPT_STYLES = (
    "strict_simple",
    "reviewcopilot_minimal",
    "reviewcopilot_style",
    "screenprompt_lite",
    "disease_parameter_minimal",
    "disease_parameter_relevance",
    "disease_parameter_useful",
    "disease_parameter_about_topic",
    "disease_parameter_direct_estimate",
    "disease_parameter_numerical_value",
    "disease_parameter_primary_study",
    "disease_parameter_all_conditions",
    "disease_parameter_broad",
    "disease_parameter_keyword_only",
)

SIMPLE_DISEASE_LABELS = {
    "covid19": "COVID-19",
    "covid_19": "COVID-19",
    "sars_cov_2": "COVID-19",
    "mpox": "mpox",
    "monkeypox": "mpox",
}

SIMPLE_PARAMETER_LABELS = {
    "fatality": "fatality",
    "reproduction_number": "reproduction number",
    "serial_interval": "serial interval",
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
    "prompt_style",
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

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_API_KEY = "testtoken"
DEFAULT_MODEL = "zifeng-ai/leads-mistral-7b-v1"
ENDPOINT_ENV_VARS = ("LEADS_ENDPOINT", "LLM_API_BASE", "OPENAI_API_BASE")
API_KEY_ENV_VARS = ("LEADS_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
MODEL_ENV_VARS = ("LEADS_MODEL", "LLM_MODEL", "OPENAI_MODEL")


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


def resolve_profile_paths(
    project_root: Path,
    profile: ScreeningProfile,
    experiment: str,
    *,
    data_root: Path | None = None,
) -> dict[str, Path]:
    if data_root is not None:
        dataset_project_dir = (
            data_root
            / profile.disease
            / "screening"
            / profile.topic
            / profile.project_dir_name
        )
        if dataset_project_dir.exists():
            output_dir = dataset_project_dir / "experiments" / experiment if experiment else dataset_project_dir
            return {
                "data_source": "dataset",
                "project_dir": dataset_project_dir,
                "raw_file": dataset_project_dir / "raw.csv",
                "ground_truth_file": dataset_project_dir / "ground_truth.csv",
                "screened_file": output_dir / "screened.csv",
                "checkpoint_file": output_dir / "predictions.jsonl",
                "metrics_file": output_dir / "metrics.json",
            }

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
        "data_source": "evaluation_legacy",
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


def simple_disease_label(profile: ScreeningProfile) -> str:
    key = normalize_key(profile.disease)
    return SIMPLE_DISEASE_LABELS.get(key, str(profile.disease).replace("_", " "))


def simple_parameter_label(profile: ScreeningProfile) -> str:
    key = normalize_key(profile.topic)
    return SIMPLE_PARAMETER_LABELS.get(key, str(profile.topic).replace("_", " "))


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


def first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def load_project_llm_config(project_root: Path) -> Any | None:
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from metaagent.config import load_llm_config
    except Exception:
        return None
    try:
        return load_llm_config(module_hint="screening")
    except Exception as exc:
        print(f"WARN: could not load project LLM config: {exc}", file=sys.stderr)
        return None


def resolve_llm_runtime_args(args: argparse.Namespace, project_root: Path) -> None:
    # Capture process env before metaagent.config loads .env.local. This keeps
    # explicit shell overrides above project defaults.
    endpoint_env = first_env(ENDPOINT_ENV_VARS)
    api_key_env = first_env(API_KEY_ENV_VARS)
    model_env = first_env(MODEL_ENV_VARS)
    cfg = load_project_llm_config(project_root)

    args.base_url = normalize_base_url(
        first_nonempty(
            args.base_url,
            endpoint_env,
            getattr(cfg, "api_base", None),
            DEFAULT_API_BASE_URL,
        )
        or DEFAULT_API_BASE_URL
    )
    args.api_key = first_nonempty(
        args.api_key,
        api_key_env,
        getattr(cfg, "api_key", None),
        DEFAULT_API_KEY,
    )
    args.model = first_nonempty(
        args.model,
        model_env,
        getattr(cfg, "model", None),
        DEFAULT_MODEL,
    )
    if args.timeout_s is None:
        args.timeout_s = float(getattr(cfg, "timeout_s", 120) or 120)
    if args.verify_ssl is None:
        args.verify_ssl = bool(getattr(cfg, "verify_ssl", True))


def build_messages(
    profile: ScreeningProfile,
    row: dict[str, Any],
    *,
    abstract_max_chars: int,
    prompt_style: str,
    title_only: bool = False,
) -> list[dict[str, str]]:
    title = truncate_text(get_field(row, "Title", "title"), 1200)
    if title_only:
        abstract = "(No abstract — title-only screening.)"
    else:
        abstract = truncate_text(get_field(row, "Abstract", "abstract"), abstract_max_chars)
        if not abstract:
            abstract = "(No abstract.)"

    if prompt_style == "strict_simple":
        user = f"""
Task: quick screen for a {profile.disease} review.
Question: {profile.research_question}
Title: {title}
Abstract: {abstract}

Be strict. Include only if the title/abstract clearly looks directly useful for the question.
If it is vague, off-topic, review/editorial/protocol, or only mentions the topic, exclude it.
JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "reviewcopilot_minimal":
        user = f"""
You are assisting with title and abstract screening for a systematic review.

Review question:
{profile.research_question}

Based only on the title and abstract, decide whether this record should be included.
Include only if it clearly appears to directly address the review question with relevant empirical information.
Exclude if it is unclear, only indirectly related, a background discussion, protocol, editorial, or secondary review.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "reviewcopilot_style":
        user = f"""
You are assisting with title and abstract screening for a systematic review.

Review question:
{profile.research_question}

Inclusion focus:
- Disease/population: {profile.disease_focus}
- Target parameter or outcome: {profile.parameter_focus}

Exclusion focus:
- Disease/population exclusions: {profile.disease_exclude}
- Parameter/outcome exclusions: {profile.parameter_exclude}
- Exclude clearly irrelevant records, non-research items, protocols, editorials, and secondary reviews unless the abstract suggests original usable evidence for this review.

Screening rule:
- "include": likely meets the review question from title/abstract.
- "unclear": insufficient information, but plausibly relevant and should proceed to manual or full-text review.
- "exclude": clearly not relevant.
Prefer "unclear" over "exclude" for borderline records, because title/abstract screening should preserve sensitivity.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"decision": "include/unclear/exclude", "include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "screenprompt_lite":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
You are screening title/abstract records for an epidemiology systematic review.
Review question: {profile.research_question}

Include if the paper appears to study {disease} and may report data, estimates, or analysis relevant to {parameter}.
Exclude if it is clearly unrelated, a review/editorial/protocol, or only mentions the topic without usable evidence.
If uncertain from the title/abstract, include.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_minimal":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am screening papers for a systematic review about {disease} and {parameter}.
Based on the title and abstract, decide include or exclude.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_relevance":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am studying {disease} and {parameter}.
Please read the title and abstract and decide whether this paper is relevant.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_useful":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am studying {disease} and {parameter}.
Please read the title and abstract and decide whether this paper is useful for this topic.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_about_topic":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am studying {disease} and {parameter}.
Is this paper about this topic?

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_direct_estimate":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am screening papers about {disease} and {parameter}.
Include only if the title and abstract clearly suggest that the paper directly reports or estimates {parameter} for {disease}.
If this is not clear, exclude it.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_numerical_value":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am screening papers about {disease} and {parameter}.
Include only if the title and abstract clearly suggest that the paper gives a numerical {parameter} value or estimate for {disease}.
If it only discusses the topic, exclude it.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_primary_study":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am screening papers about {disease} and {parameter}.
Include only if the title and abstract clearly suggest that this is a primary study directly reporting or estimating {parameter} for {disease}.
Exclude reviews, editorials, protocols, background papers, and vague discussions.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_all_conditions":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am screening papers about {disease} and {parameter}.
Include only if the title and abstract clearly suggest all of the following:
1. the paper is about {disease};
2. it directly reports or estimates {parameter};
3. it gives a numerical estimate or value;
4. it looks like a primary study rather than a review, editorial, or protocol.
If any point is unclear, exclude it.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_broad":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
I am collecting papers broadly related to {disease} and {parameter} for a literature review.
Include the paper if it is in any way related to {disease} or to {parameter}, even if it only
mentions, discusses, reviews, models, or indirectly touches on them. Prefer including borderline
or uncertain cases rather than excluding them. Only exclude if the paper is entirely unrelated to
both {disease} and {parameter}.

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    elif prompt_style == "disease_parameter_keyword_only":
        disease = simple_disease_label(profile)
        parameter = simple_parameter_label(profile)
        user = f"""
Does this paper mention {disease} or {parameter} anywhere in the title or abstract?

Title: {title}
Abstract: {abstract}

Return JSON only: {{"include": true/false, "reason": "short"}}
""".strip()
    else:
        raise ValueError(f"Unknown prompt style: {prompt_style!r}")
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
    if text in {
        "unclear",
        "maybe",
        "possible",
        "possibly",
        "possibly_include",
        "needs_review",
        "requires_review",
        "full_text_review",
        "manual_review",
    }:
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
    if (
        "include" in text
        or "eligible" in text
        or "relevant" in text
        or "unclear" in text
        or "manual review" in text
        or "full text" in text
    ):
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
        if parse_error:
            return {
                "include": False,
                "confidence": 0.0,
                "reason": f"Parse error: {parse_error}",
                "llm_suggest": "error",
                "parse_error": parse_error,
                "parsed_json": data,
            }
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

    decision_text = str(data.get("decision") or data.get("label") or include_value or "").strip().lower()
    is_unclear = any(
        marker in decision_text
        for marker in (
            "unclear",
            "maybe",
            "possible",
            "needs_review",
            "requires_review",
            "manual_review",
            "manual review",
            "full_text",
            "full text",
        )
    )
    if is_unclear:
        include = True
        if raw_confidence is None:
            confidence = min(confidence, possible_confidence_threshold - 0.01)
    if include:
        label = "possible_candidate" if is_unclear or confidence < possible_confidence_threshold else "strong_candidate"
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


def build_chat_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    response_format_json: bool,
    stream: bool,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def parse_chat_completion_stream(lines: Iterable[str]) -> tuple[str, dict[str, Any]]:
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        event_usage = event.get("usage")
        if isinstance(event_usage, dict) and event_usage:
            usage = event_usage
        for choice in event.get("choices", []) or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str):
                content_parts.append(text)
    return "".join(content_parts), usage


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
    stream: bool,
    reasoning_effort: str | None,
    retries: int,
) -> tuple[str, dict[str, Any]]:
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = build_chat_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format_json=response_format_json,
        stream=stream,
        reasoning_effort=reasoning_effort,
    )

    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        started = time.perf_counter()
        try:
            if stream:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    lines = [line async for line in response.aiter_lines()]
                content, usage = parse_chat_completion_stream(lines)
            else:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {}) or {}
            wall_ms = round((time.perf_counter() - started) * 1000, 1)
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
    prompt_style: str,
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
            "screening_strategy": f"leads_mistral_{prompt_style}",
            "prompt_style": prompt_style,
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
    messages = build_messages(
        profile,
        row,
        abstract_max_chars=args.abstract_max_chars,
        prompt_style=args.prompt_style,
        title_only=getattr(args, "title_only", False),
    )
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
            stream=args.stream,
            reasoning_effort=args.reasoning_effort,
            retries=args.retries,
        )
        prediction = parse_prediction(
            content,
            possible_confidence_threshold=args.possible_confidence_threshold,
        )
        prediction.update(
            {
                "pmid": pmid,
                "model": args.model,
                "prompt_style": args.prompt_style,
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
        prediction["model"] = args.model
        prediction["prompt_style"] = args.prompt_style
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
            "data_source": paths.get("data_source", ""),
            "prompt_style": args.prompt_style,
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
            existing_style = str(existing.get("prompt_style") or "strict_simple")
            if existing_style == args.prompt_style:
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
                prompt_style=args.prompt_style,
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
                "data_source": paths.get("data_source", ""),
                "prompt_style": args.prompt_style,
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
            "data_source": paths.get("data_source", ""),
            "prompt_style": args.prompt_style,
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
        description="Evaluate LEADS-Mistral-7B-v1 with simple screening prompts."
    )
    parser.add_argument("--project-root", default=".", help="Repository root")
    parser.add_argument(
        "--data-root",
        default="dataset",
        help=(
            "Frozen dataset root. Defaults to dataset/ and expects "
            "dataset/{disease}/screening/{topic}/{project}/raw.csv plus ground_truth.csv. "
            "Set to an empty string to fall back to legacy evaluation paths."
        ),
    )
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
        help="Experiment name. Defaults to leads_mistral_<prompt_style>_<timestamp>.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "OpenAI-compatible API base URL. Resolution order: CLI, "
            "LEADS_ENDPOINT/LLM_API_BASE/OPENAI_API_BASE, project .env.local, "
            f"{DEFAULT_API_BASE_URL}."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "API key for the OpenAI-compatible endpoint. Resolution order: CLI, "
            "LEADS_API_KEY/LLM_API_KEY/OPENAI_API_KEY, project .env.local, "
            "then a local vLLM placeholder."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Served model name. Resolution order: CLI, LEADS_MODEL/LLM_MODEL/"
            f"OPENAI_MODEL, project .env.local, {DEFAULT_MODEL}."
        ),
    )
    parser.add_argument(
        "--prompt-style",
        choices=PROMPT_STYLES,
        default="strict_simple",
        help=(
            "Prompt template to use. strict_simple keeps the previous strict question prompt; "
            "screenprompt_lite is a short AgentSLR/ScreenPrompt-style adaptation; "
            "the disease_parameter_* variants progressively simplify the task into more ambiguous "
            "disease/parameter relevance judgments."
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout-s", type=float, default=None)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--log-every", type=int, default=25)
    parser.add_argument("--abstract-max-chars", type=int, default=5000)
    parser.add_argument(
        "--title-only",
        action="store_true",
        help="Drop the abstract (simulate title-only metadata screening). Increases both FN and FP.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Smoke-test limit per profile; 0 means no limit")
    parser.add_argument("--possible-confidence-threshold", type=float, default=0.7)
    parser.add_argument("--response-format-json", action="store_true", help="Send response_format=json_object to vLLM")
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default=None,
    )
    parser.add_argument("--save-raw-response", action="store_true", help="Also store raw model output in the screened CSV")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--check-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verify-ssl", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--fail-on-missing", action="store_true", help="Exit non-zero if any raw/GT file is missing")
    parser.add_argument("--dry-run", action="store_true", help="Resolve profiles and paths without calling the model")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    resolve_llm_runtime_args(args, project_root)
    args.data_root = str(args.data_root or "").strip()
    data_root = (project_root / args.data_root).resolve() if args.data_root else None
    if not args.experiment:
        args.experiment = f"leads_mistral_{args.prompt_style}_" + datetime.now().strftime("%Y%m%d_%H%M%S")

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
        "data_root": str(data_root) if data_root else "",
        "prompt_style": args.prompt_style,
        "profiles": [p.id for p in selected],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "concurrency": args.concurrency,
        "limit": args.limit,
        "response_format_json": args.response_format_json,
        "stream": args.stream,
        "reasoning_effort": args.reasoning_effort,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (aggregate_dir / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

    if args.dry_run:
        summaries: list[dict[str, Any]] = []
        for profile in selected:
            paths = resolve_profile_paths(project_root, profile, args.experiment, data_root=data_root)
            print(
                f"[{profile.id}] source={paths.get('data_source')} raw={paths['raw_file']} "
                f"gt={paths['ground_truth_file']} out={paths['screened_file']}"
            )
            summaries.append(
                {
                    "profile": profile.id,
                    "topic": profile.topic,
                    "project": profile.project_number,
                    "status": "dry_run",
                    "data_source": paths.get("data_source", ""),
                    "prompt_style": args.prompt_style,
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
            paths = resolve_profile_paths(project_root, profile, args.experiment, data_root=data_root)
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
