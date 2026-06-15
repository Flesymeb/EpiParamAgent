from __future__ import annotations

import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.db import engine, run_step_dir
from app.events import StreamToEvents


def run_query_gen_step(run_id: str, params: dict[str, Any]) -> str:
    out_dir = run_step_dir(run_id, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    query_path = out_dir / "query.json"

    with Session(engine) as session:
        stream = StreamToEvents(session=session, run_id=run_id, step_no=1)
        with redirect_stdout(stream), redirect_stderr(stream):
            from metaagent.screening.engine import init_llm_model

            keywords = _format_keywords(params.get("keywords"))
            research_question = str(params.get("research_question") or "").strip()
            disease = str(params.get("disease") or "").strip()
            parameter = str(params.get("parameter") or "").strip()

            if not keywords and not research_question:
                raise ValueError(
                    "params['keywords'] or params['research_question'] is required"
                )

            print("query_gen step: building LLM")
            llm = init_llm_model(
                model_override=params.get("model"),
                provider_override=params.get("provider"),
                temperature_override=params.get("temperature"),
                config_overrides=params,
            )

            messages = _build_messages(
                keywords=keywords,
                research_question=research_question,
                disease=disease,
                parameter=parameter,
                supplement=str(
                    params.get("query_prompt_supplement")
                    or params.get("prompt_supplement")
                    or ""
                ).strip(),
            )
            print("query_gen step: requesting PubMed boolean query")
            resp = llm.invoke(messages)
            raw_content = _response_text(resp.content)
            payload = _parse_query_payload(raw_content)

            query_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            print(f"query_gen step: generated query={payload['query']}")
            warnings = payload.get("warnings") or []
            if warnings:
                for warning in warnings:
                    print(f"query_gen step: warning={warning}")
            else:
                print("query_gen step: warnings=none")
            print(f"query_gen step: wrote {query_path}")

    return str(query_path)


def _format_keywords(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _build_messages(
    *,
    keywords: str,
    research_question: str,
    disease: str,
    parameter: str,
    supplement: str = "",
) -> list[dict[str, str]]:
    from app.prompt_templates import load_query_template

    sections = load_query_template()
    system_text = sections.get("system") or (
        "You are an expert medical information specialist designing PubMed "
        "searches for epidemiological systematic reviews. Generate precise, "
        "PubMed-ready boolean queries with synonym expansion and field tags."
    )
    user_template = sections.get("user") or _DEFAULT_USER_TEMPLATE
    substitutions = {
        "keywords": keywords or "not provided",
        "research_question": research_question or "not provided",
        "disease": disease or "not provided",
        "parameter": parameter or "not provided",
    }
    user_text = re.sub(
        r"\{(keywords|research_question|disease|parameter)\}",
        lambda match: substitutions[match.group(1)],
        user_template,
    ).strip()
    if supplement:
        user_text += (
            "\n\nAdditional reviewer guidance (incorporate into the query):\n"
            + supplement
        )
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


_DEFAULT_USER_TEMPLATE = """
Create a PubMed-ready boolean search query for the study topic below.

Inputs:
- keywords: {keywords}
- research_question: {research_question}
- disease: {disease}
- epidemiological_parameter: {parameter}

Requirements:
- Use valid PubMed boolean syntax with parentheses.
- Use PubMed field tags such as [Title/Abstract] and [MeSH Terms].
- Attach a field tag to each searchable term or phrase, not only to a grouped
  parenthetical expression.
- Expand synonyms for the disease, parameter, and study-design concepts when useful.
- Avoid unsupported syntax and avoid database-specific operators outside PubMed.
- Return STRICT JSON only, with exactly these top-level keys:
  "query": string,
  "terms": list of objects, each with "concept" and "synonyms",
  "rationale": short string,
  "warnings": list of strings.
""".strip()


def _response_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _parse_query_payload(raw_content: str) -> dict[str, Any]:
    from metaagent.coding.parsing import parse_json_records

    candidates = parse_json_records(raw_content)
    if candidates:
        return _validate_payload(candidates[0], raw_content)

    extracted = _extract_first_json_object(raw_content)
    if extracted:
        try:
            payload = json.loads(extracted)
        except json.JSONDecodeError:
            pass
        else:
            return _validate_payload(payload, raw_content)

    raise ValueError(f"Failed to parse query generation JSON. Raw content: {raw_content}")


def _extract_first_json_object(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None

    in_string = False
    escaped = False
    start: int | None = None
    depth = 0

    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : index + 1]
    return None


def _validate_payload(payload: dict[str, Any], raw_content: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"Query generation returned non-object JSON. Raw content: {raw_content}")

    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError(f"Query generation JSON has empty 'query'. Raw content: {raw_content}")

    terms = payload.get("terms")
    normalized_terms: list[dict[str, Any]] = []
    if isinstance(terms, list):
        for item in terms:
            if isinstance(item, dict):
                concept = str(item.get("concept") or "").strip()
                raw_synonyms = item.get("synonyms")
                synonyms = (
                    [str(s).strip() for s in raw_synonyms if str(s).strip()]
                    if isinstance(raw_synonyms, list)
                    else []
                )
                normalized_terms.append({"concept": concept, "synonyms": synonyms})

    warnings = payload.get("warnings")
    normalized_warnings = (
        [str(w).strip() for w in warnings if str(w).strip()]
        if isinstance(warnings, list)
        else []
    )

    return {
        "query": query,
        "terms": normalized_terms,
        "rationale": str(payload.get("rationale") or "").strip(),
        "warnings": normalized_warnings,
    }
