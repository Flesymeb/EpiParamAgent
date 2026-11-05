"""Optional synthesis-model explanations validated against immutable artifacts."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REPORT_TEMPLATES = {
    "The synthesis estimate is {{n0}}.": {"n0": "/result/pooled_mean"},
    "The interval is {{n0}} to {{n1}}.": {"n0": "/result/ci_lower", "n1": "/result/ci_upper"},
    "The analysis selected {{n0}} estimates.": {"n0": "/counts/selected"},
    "Inputs requiring review: {{n0}}.": {"n0": "/counts/review"},
}

PROMPTS = Path(__file__).resolve().parents[1] / "prompts" / "synthesis"


class DecisionExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estimate_id: str
    decision: Literal["select", "exclude", "review"]
    reason: str
    rule_refs: list[str]


class SelectionExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[DecisionExplanation]


class NumericReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^n\d+$")
    path: str


class ReportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_template: str
    numeric_refs: list[NumericReference]
    citation_ids: list[str]


class ReportExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[ReportClaim]


def _runtime_invoke():
    from metaagent.config import load_llm_config, is_usable_secret, merge_thinking_policy
    from langchain_openai import ChatOpenAI
    from metaagent.llm_rate_limit import httpx_event_hooks
    import httpx
    cfg = load_llm_config(module_hint="synthesis")
    if not is_usable_secret(cfg.api_key):
        raise ValueError("SYNTHESIS runtime credential is unavailable")
    client = httpx.Client(verify=cfg.verify_ssl, timeout=cfg.timeout_s, event_hooks=httpx_event_hooks())
    import os
    extra_body = None
    raw_extra_body = os.environ.get("SYNTHESIS_LLM_EXTRA_BODY_JSON", "").strip()
    if raw_extra_body:
        extra_body = json.loads(raw_extra_body)
        if not isinstance(extra_body, dict):
            raise ValueError("SYNTHESIS_LLM_EXTRA_BODY_JSON must be a JSON object")
    policy_body = merge_thinking_policy(None, cfg.thinking) or {}
    if extra_body:
        if "thinking" in extra_body or "enable_thinking" in extra_body:
            policy_body.pop("thinking", None)
            policy_body.pop("enable_thinking", None)
        policy_body.update(extra_body)
    options = dict(model=cfg.model, api_key=cfg.api_key, base_url=cfg.api_base, temperature=cfg.temperature,
                   max_tokens=cfg.max_tokens, timeout=cfg.timeout_s, http_client=client,
                   streaming=cfg.force_streaming,
                   extra_body=merge_thinking_policy(policy_body, None))
    if cfg.reasoning_effort:
        options["reasoning_effort"] = cfg.reasoning_effort
    model = ChatOpenAI(**options)
    def invoke(messages):
        response = model.bind(response_format={"type": "json_object"}).invoke(messages)
        return {"content": response.content, "usage": response.usage_metadata or {},
                "model": cfg.model, "provider": cfg.provider, "api_base": cfg.api_base}
    return invoke


def _pointer(document, path):
    if not path.startswith(("/result/", "/counts/")):
        raise ValueError("Numeric pointer is outside authoritative result/count fields")
    value = document
    for token in path.strip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Numeric pointer is not a finite computed number")
    return value


def assist_synthesis(output, protocol, invoke=None):
    """Add optional explanations; model failures never change deterministic numbers."""
    for stage, enabled in (("selection", protocol.get("llm_selection", False)), ("report", protocol.get("llm_report", False))):
        if not enabled:
            continue
        audit = {"status": "failed", "purpose": "validated_explanation_only"}
        try:
            caller = invoke or _runtime_invoke()
            data = {"protocol": protocol, "selection": output["selection"], "result": output["result"], "counts": output["counts"], "allowed_report_templates": REPORT_TEMPLATES, "allowed_citation_ids": sorted({str(v) for r in output["selected_estimates"] for v in r.get("evidence_ids", []) if isinstance(v, str)})}
            response = caller([{"role": "system", "content": (PROMPTS / f"{stage}.md").read_text()},
                               {"role": "user", "content": json.dumps(data, ensure_ascii=False)}])
            if isinstance(response, dict) and "content" in response:
                audit.update({k: response.get(k) for k in ("usage", "model", "provider", "api_base") if k in response})
                response = response["content"]
            if isinstance(response, str):
                audit["raw_response"] = response
                response = json.loads(response)
            if stage == "selection":
                parsed = SelectionExplanation.model_validate(response)
                expected = {r["estimate_id"]: r["decision"] for r in output["selection"]}
                actual = [r.estimate_id for r in parsed.decisions]
                if len(actual) != len(set(actual)) or set(actual) != set(expected):
                    raise ValueError("Selection explanation IDs do not match immutable decisions")
                for row in parsed.decisions:
                    if row.decision != expected[row.estimate_id] or any(ref.split(".")[0] not in protocol for ref in row.rule_refs):
                        raise ValueError("Selection explanation contradicts decision or references an absent protocol rule")
                audit.update(status="accepted", explanation=parsed.model_dump())
            else:
                parsed = ReportExplanation.model_validate(response)
                rendered = []
                # Cite only evidence identities already attached to selected records.
                citations = set()
                for row in output["selected_estimates"]:
                    citations.update(str(v) for v in row.get("evidence_ids", []) if isinstance(v, str))
                for claim in parsed.claims:
                    text = claim.text_template
                    expected_refs = REPORT_TEMPLATES.get(text)
                    if expected_refs is None or {r.name: r.path for r in claim.numeric_refs} != expected_refs:
                        raise ValueError("Report template or numeric bindings are not authorized")
                    names = [ref.name for ref in claim.numeric_refs]
                    if len(names) != len(set(names)) or set(re.findall(r"\{\{(n\d+)\}\}", text)) != set(names):
                        raise ValueError("Numeric placeholders and references do not match")
                    if re.search(r"\d", re.sub(r"\{\{n\d+\}\}", "", text)):
                        raise ValueError("Literal numbers are forbidden in model-written claims")
                    if set(claim.citation_ids) - citations:
                        raise ValueError("Unknown citation identity")
                    for ref in claim.numeric_refs:
                        text = text.replace("{{" + ref.name + "}}", str(_pointer(output, ref.path)))
                    rendered.append({"text": text, "numeric_refs": [r.model_dump() for r in claim.numeric_refs], "citation_ids": claim.citation_ids})
                audit.update(status="accepted", claims=rendered)
        except Exception as exc:
            # Never serialize exception messages that may include provider credentials.
            audit.update(status="rejected_or_unavailable", error_type=type(exc).__name__)
        output["llm_" + stage] = audit
    return output
