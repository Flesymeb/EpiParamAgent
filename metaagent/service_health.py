"""Small opt-in OpenAI-compatible endpoint probes with no provider fallback."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from time import perf_counter

import requests

from metaagent.config import LLMConfig, normalize_api_base


def probe_runtime(config: LLMConfig, *, timeout: float = 10) -> dict:
    """Probe only the selected deployment using an invented structured question.

    HTTP success proves transport availability, not model identity or scientific
    quality. Empty reasoning-limited output is recorded separately from outage.
    Credential headers and arbitrary server error bodies are never returned.
    """
    result = {"status": "not_configured", "provider": config.provider,
              "configured_model": config.model, "observed_model": None, "thinking": getattr(config, "thinking", None),
              "endpoint": config.api_base, "started_at": datetime.now(timezone.utc).isoformat(),
              "elapsed_s": None, "time_to_first_content_s": None, "usage": None}
    if not config.api_base or not config.model:
        return result
    start = perf_counter()
    try:
        base = normalize_api_base(config.api_base)
        headers = {"Authorization": "Bearer " + config.api_key} if config.api_key else {}
        body = {"model": config.model, "messages": [{"role": "user", "content":
                'Software transport test: return JSON {"ok":true}.'}],
                "max_tokens": 128, "temperature": 0, "stream": config.force_streaming}
        if getattr(config, 'thinking', None) is not None:
            body['thinking'] = {'type': config.thinking}
        with requests.Session() as session:
            # requests otherwise prefers lowercase no_proxy, which can shadow
            # the project's uppercase NO_PROXY and send private nodes to a proxy.
            bypass = ','.join(v for v in (os.environ.get('NO_PROXY'), os.environ.get('no_proxy')) if v)
            session.trust_env = not requests.utils.should_bypass_proxies(base, no_proxy=bypass)
            with session.post(base + "/chat/completions", headers=headers, json=body,
                              timeout=timeout, verify=config.verify_ssl, stream=config.force_streaming) as response:
                result["http_status"] = response.status_code
                if not response.ok:
                    text = response.text[:1000]
                    result.update(status="service_unavailable",
                                  classification="deployment_unavailable" if "no healthy upstream" in text.casefold()
                                  else "authentication_failed" if response.status_code in {401, 403}
                                  else "http_error")
                    if "no healthy upstream" in text.casefold():
                        result["diagnostic"] = "no healthy upstream"
                    return result
                visible, choices_received = [], False
                if config.force_streaming:
                    for line in response.iter_lines():
                        if not line or not line.startswith(b"data:"):
                            continue
                        value = line[5:].strip()
                        if value == b"[DONE]":
                            break
                        payload = json.loads(value)
                        result["observed_model"] = payload.get("model") or result["observed_model"]
                        result["usage"] = payload.get("usage") or result["usage"]
                        for choice in payload.get("choices", []):
                            choices_received = True
                            content = (choice.get("delta") or {}).get("content")
                            if content:
                                if result["time_to_first_content_s"] is None:
                                    result["time_to_first_content_s"] = round(perf_counter() - start, 3)
                                visible.append(content)
                else:
                    payload = response.json()
                    result["observed_model"] = payload.get("model")
                    result["usage"] = payload.get("usage")
                    choices_received = bool(payload.get("choices"))
                    visible = [(c.get("message") or {}).get("content") or "" for c in payload.get("choices", [])]
                if not choices_received:
                    result.update(status="service_unavailable", classification="invalid_completion_envelope")
                else:
                    result.update(status="ready", visible_content_received=bool("".join(visible).strip()))
                return result
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        result.update(status="service_unavailable", classification="transport_or_protocol_error", error_type=type(exc).__name__)
        return result
    finally:
        result["elapsed_s"] = round(perf_counter() - start, 3)
