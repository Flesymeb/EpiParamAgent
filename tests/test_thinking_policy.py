"""Explicit thinking control and native request payloads without network calls."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import metaagent.config as config
from metaagent.workflow_task import ModuleRuntime, resolve_runtime


@pytest.fixture
def env(monkeypatch):
    values = {"LLM_PROVIDER": "pjlab", "CODING_LLM_PROVIDER": "pjlab", "CODING_LLM_MODEL": "gateway-model",
              "CODING_LLM_API_KEY": "synthetic-credential", "CODING_LLM_API_BASE": "http://gateway.invalid/v1"}
    monkeypatch.setattr(config, "load_runtime_env", lambda **kwargs: None)
    monkeypatch.setattr(config.os, "environ", values)
    return values


@pytest.mark.parametrize("key", ["llm_thinking", "thinking"])
def test_explicit_policy_accepts_alias_and_normalizes_case(env, key):
    env["CODING_LLM_THINKING"] = "enabled"
    cfg = config.load_llm_config({key: "DISABLED"}, module_hint="coding")
    assert cfg.thinking == "disabled"


def test_no_explicit_setting_has_no_default_disable(env):
    cfg = config.load_llm_config(module_hint="coding")
    assert cfg.thinking is None
    assert config.merge_thinking_policy(None, cfg.thinking) is None


def test_module_provider_global_precedence_and_switch_isolation(env):
    env.update(LLM_THINKING="enabled", PJLAB_THINKING="enabled", CODING_LLM_THINKING="disabled",
               SELFHOSTED_MODEL="local-model", SELFHOSTED_API_KEY="local-credential", SELFHOSTED_BASE_URL="http://local.invalid/v1")
    assert config.load_llm_config(module_hint="coding").thinking == "disabled"
    switched = config.load_llm_config({"provider": "selfhosted"}, module_hint="coding")
    assert switched.thinking is None
    env["SELFHOSTED_THINKING"] = "enabled"
    assert config.load_llm_config({"provider": "selfhosted"}, module_hint="coding").thinking == "enabled"


@pytest.mark.parametrize("bad", ["auto", "false", False, 0])
def test_invalid_thinking_setting_is_rejected(env, bad):
    with pytest.raises(ValueError, match="enabled.*disabled"):
        config.load_llm_config({"thinking": bad}, module_hint="coding")


def test_disabled_reasoning_effort_conflict_is_explicit(env):
    with pytest.raises(ValueError, match="incompatible"):
        config.load_llm_config({"thinking": "disabled", "reasoning_effort": "high"}, module_hint="coding")
    # A switched provider does not inherit the old provider's reasoning policy.
    env["CODING_LLM_REASONING_EFFORT"] = "high"
    assert config.load_llm_config({"provider": "selfhosted", "thinking": "disabled"}, module_hint="coding").reasoning_effort is None


def test_helper_merges_native_payload_and_preserves_unrelated_fields():
    assert config.merge_thinking_policy({"custom": 1}, "disabled") == {"custom": 1, "thinking": {"type": "disabled"}}
    with pytest.raises(ValueError, match="conflicts"):
        config.merge_thinking_policy({"thinking": {"type": "enabled"}}, "disabled")


def test_task_runtime_schema_and_fingerprint_include_policy(env, tmp_path):
    import yaml
    task = tmp_path / "task.yaml"
    definition = {"task_id": "test", "disease": "X", "topic": "SI", "research_question": "Intervals?", "codebook": "unused.yaml",
                  "review_protocol": {"version": "1", "criteria": [{"id": "human", "description": "Human"}], "logic": "human"},
                  "llm": {"coding": {"thinking": "disabled"}}}
    task.write_text(yaml.safe_dump(definition))
    options = SimpleNamespace(task_config=task, model=None, api_base=None, temperature=None, api_key_env="UNUSED")
    invocation, public = resolve_runtime(options, "coding")
    assert invocation["llm_thinking"] == public["llm_thinking"] == "disabled"
    assert "synthetic-credential" not in str(public)
    with pytest.raises(ValidationError):
        ModuleRuntime(thinking="auto")


@pytest.mark.parametrize("body,expected", [(None, {"thinking": {"type": "disabled"}}),
    ('{"custom":1}', {"custom": 1, "thinking": {"type": "disabled"}}),
    ('{"thinking":{"type":"enabled"}}', {"thinking": {"type": "enabled"}}),
    ('{"enable_thinking":true}', {"enable_thinking": True})])
def test_screening_constructor_receives_effective_native_policy(env, monkeypatch, body, expected):
    import metaagent.screening.engine as screening
    env.update(SCREENING_LLM_PROVIDER="pjlab", SCREENING_LLM_MODEL="gateway-model", SCREENING_LLM_API_KEY="synthetic-credential",
               SCREENING_LLM_API_BASE="http://gateway.invalid/v1", SCREENING_LLM_THINKING="disabled")
    if body:
        env["SCREENING_LLM_EXTRA_BODY_JSON"] = body
    captured = {}
    monkeypatch.setattr(screening, "ChatOpenAI", lambda **kwargs: captured.update(kwargs) or SimpleNamespace())
    screening.init_llm_model()
    assert captured["extra_body"] == expected
    captured["http_client"].close()
    import asyncio
    asyncio.run(captured["http_async_client"].aclose())


def test_standalone_synthesis_uses_its_explicit_policy(env, monkeypatch):
    from metaagent.synthesis.assistance import _runtime_invoke
    import langchain_openai
    env.update(SYNTHESIS_LLM_PROVIDER="pjlab", SYNTHESIS_LLM_MODEL="report-model", SYNTHESIS_LLM_API_KEY="synthetic-credential",
               SYNTHESIS_LLM_API_BASE="http://report.invalid/v1", SYNTHESIS_LLM_THINKING="disabled",
               SYNTHESIS_LLM_EXTRA_BODY_JSON='{"custom":2}')
    captured = {}
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kwargs: captured.update(kwargs) or SimpleNamespace())
    _runtime_invoke()
    assert captured["model"] == "report-model"
    assert captured["extra_body"] == {"custom": 2, "thinking": {"type": "disabled"}}
    captured["http_client"].close()


@pytest.mark.parametrize("module", ["query", "synthesis"])
def test_shared_factory_uses_the_requested_modules_extra_body(env, monkeypatch, module):
    import metaagent.screening.engine as screening
    prefix = module.upper()
    env.update({prefix + "_LLM_PROVIDER": "pjlab", prefix + "_LLM_MODEL": module + "-model",
                prefix + "_LLM_API_KEY": "synthetic-credential", prefix + "_LLM_API_BASE": "http://service.invalid/v1",
                prefix + "_LLM_THINKING": "disabled", prefix + "_LLM_EXTRA_BODY_JSON": '{"custom":"correct-module"}',
                "SCREENING_LLM_EXTRA_BODY_JSON": '{"custom":"wrong-module","thinking":{"type":"enabled"}}'})
    captured = {}
    monkeypatch.setattr(screening, "ChatOpenAI", lambda **kwargs: captured.update(kwargs) or SimpleNamespace())
    screening.init_llm_model(module_hint=module)
    assert captured["model"] == module + "-model"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}, "custom": "correct-module"}
    captured["http_client"].close()
    import asyncio
    asyncio.run(captured["http_async_client"].aclose())


def test_explicit_extra_body_cannot_contain_contradictory_aliases():
    with pytest.raises(ValueError, match="contradictory"):
        config.merge_thinking_policy({"thinking": {"type": "disabled"}, "enable_thinking": True}, None)
