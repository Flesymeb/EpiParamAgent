"""Actual Coding wire contracts; all model transports are offline fixtures."""

import json
from pathlib import Path
import httpx, pytest
from metaagent.config import LLMConfig
from metaagent.coding.response_contracts import (
    stage_b_response_format,
    stage_request_overrides,
)
from metaagent.coding.pipeline import extraction


@pytest.fixture
def transport(monkeypatch):
    from metaagent.coding import llm

    cfg = LLMConfig(
        provider="openai",
        model="offline-model",
        api_key="offline-synthetic-credential",
        api_base="http://127.0.0.1:9/v1",
        max_tokens=128,
        timeout_s=3,
        temperature=0,
        thinking="disabled",
    )
    monkeypatch.setattr("metaagent.config.load_llm_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("metaagent.config.load_runtime_env", lambda **kw: None)
    monkeypatch.setenv(
        "CODING_LLM_EXTRA_BODY_JSON",
        '{"response_format":{"type":"json_object"},"chat_template_kwargs":{"enable_thinking":false}}',
    )
    monkeypatch.setenv("METAAGENT_LLM_REQUESTS_PER_MINUTE", "")
    monkeypatch.setattr(extraction, "_llm_call_timeout_s", lambda: None)
    monkeypatch.delenv("CODING_LLM_SUBPROCESS_TIMEOUT_S", raising=False)
    requests = []
    clients = []
    original = httpx.Client

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "model": cfg.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"records":[],"dispositions":[]}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 4,
                    "total_tokens": 9,
                },
            },
        )

    class Client(original):
        def __init__(self, **kwargs):
            kwargs.pop("trust_env", None)
            super().__init__(
                transport=httpx.MockTransport(handle), trust_env=False, **kwargs
            )
            clients.append(self)

    monkeypatch.setattr(httpx, "Client", Client)
    yield llm, requests
    for value in clients:
        value.close()


@pytest.mark.parametrize("path", ["direct_bound", "worker_init"])
def test_actual_wire_preserves_native_profile_and_requires_B_arrays(transport, path):
    llm, requests = transport
    format = stage_b_response_format()
    overrides = {"_coding_response_format": format}
    model = llm.init_llm(overrides if path == "worker_init" else None)
    messages = [{"role": "user", "content": "Offline envelope test"}]
    if path == "worker_init":
        model.invoke(messages)
    else:
        extraction._invoke_model_content_once(
            model=model,
            messages=messages,
            llm_overrides=overrides,
            pmid="123",
            stage_name="stage_b",
        )
    assert len(requests) == 1
    body = requests[0]
    assert body["response_format"] == format
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body[
        "thinking"
    ] == {"type": "disabled"}
    assert (
        body["model"] == "offline-model"
        and (body.get("max_tokens") or body.get("max_completion_tokens")) == 128
    )
    assert format["json_schema"]["schema"]["required"] == ["records", "dispositions"]
    assert (
        format["json_schema"]["schema"]["properties"]["records"]["items"][
            "additionalProperties"
        ]
        is True
    )


def test_evidence_patch_has_its_own_contract_and_A_is_untouched():
    from metaagent.coding.stages import B_EVIDENCE_RULES

    evidence = [{"role": "system", "content": B_EVIDENCE_RULES}]
    value = stage_request_overrides({}, "stage_b", evidence)["_coding_response_format"]
    assert value["json_schema"]["schema"]["required"] == ["evidence_patches"]
    assert "dispositions" not in value["json_schema"]["schema"]["properties"]
    assert stage_request_overrides({}, "stage_a", evidence) == {}


@pytest.mark.parametrize("fixed", [True, False])
def test_records_only_B_gets_exact_missing_envelope_feedback_once(tmp_path, fixed):
    from metaagent.coding.schema.config_loader import ProjectConfig, FieldConfig
    from metaagent.coding.stages import run_stages

    source = "The original R0 estimate was 0.8."
    book = ProjectConfig(
        name="reproduction_number",
        effect_type="reproduction_number",
        fields=[
            FieldConfig(name="parameter_type", label="Parameter", type="str"),
            FieldConfig(name="point_estimate", label="Estimate", type="float"),
        ],
    )
    row = {
        "parameter_type": "R0",
        "point_estimate": 0.8,
        "_field_evidence": {"parameter_type": source, "point_estimate": source},
    }
    calls = []

    def invoke(stage, messages):
        calls.append(stage)
        if stage == "stage_a":
            return json.dumps({"records": [row]})
        text = messages[-1]["content"]
        body = json.JSONDecoder().raw_decode(text)[0]
        assert "synthetic_examples_guidance_only" not in body
        assert body["stage_b_output_contract"]["required_arrays"] == [
            "records",
            "dispositions",
        ]
        assert messages[0]["content"].startswith("STAGE B OUTPUT CONTRACT")
        candidates = json.loads(text.split("\nCandidates (guidance only):\n")[1])
        cid = candidates[0]["candidate_id"]
        payload = {"records": [{**row, "candidate_id": cid}]}
        if calls.count("stage_b") == 2:
            feedback = body["candidate_contract_feedback"]
            assert feedback["missing_top_level_fields"] == ["dispositions"]
            assert feedback["missing_disposition_candidate_ids"] == [cid]
            if fixed:
                payload["dispositions"] = [
                    {
                        "candidate_id": cid,
                        "action": "keep",
                        "reason": "Original source verified",
                    }
                ]
        return json.dumps(payload)

    kwargs = dict(
        text=source,
        config=book,
        record_id="synthetic:one",
        pmid=None,
        invoke=invoke,
        output_dir=tmp_path,
    )
    if fixed:
        assert len(run_stages(**kwargs)) == 1
    else:
        with pytest.raises(ValueError, match="records and dispositions"):
            run_stages(**kwargs)
        assert (tmp_path / "coding_estimates.jsonl").read_text() == ""
        assert (tmp_path / "candidate_dispositions.jsonl").read_text() == ""
    assert calls == ["stage_a", "stage_b", "stage_b"]
