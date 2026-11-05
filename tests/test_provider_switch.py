"""Provider switches isolate endpoint/model/credential identity without remote calls."""
import pytest

import metaagent.config as config


@pytest.fixture
def env(monkeypatch):
    # Isolate from real credentials and do not load or edit the user's env files.
    values = {
        "LLM_PROVIDER": "pjlab", "LLM_MODEL": "global-gateway-model", "LLM_API_KEY": "global-gateway-secret",
        "LLM_API_BASE": "https://global.gateway.invalid/v1", "ANTHROPIC_MODEL": "unrelated-model",
        "OPENAI_API_KEY": "unrelated-secret", "OPENROUTER_API_KEY": "another-unrelated-secret",
        "CODING_LLM_PROVIDER": "pjlab", "CODING_LLM_MODEL": "module-gateway-model",
        "CODING_LLM_API_KEY": "module-gateway-secret", "CODING_LLM_API_BASE": "https://module.gateway.invalid/v1",
        "CODING_LLM_TEMPERATURE": "0.2", "CODING_LLM_MAX_TOKENS": "8192", "CODING_LLM_TIMEOUT_S": "75",
        "PJLAB_MODEL": "provider-gateway-model", "PJLAB_API_KEY": "provider-gateway-secret",
        "PJLAB_BASE_URL": "https://provider.gateway.invalid/v1",
        "SELFHOSTED_MODEL": "own-model", "SELFHOSTED_API_KEY": "own-secret",
        "SELFHOSTED_BASE_URL": "http://selfhosted.invalid/v1/chat/completions",
    }
    monkeypatch.setattr(config, "load_runtime_env", lambda **kwargs: None)
    monkeypatch.setattr(config.os, "environ", values)
    return values


@pytest.mark.parametrize("key", ["llm_provider", "provider"])
def test_provider_only_task_switch_uses_selected_provider_identity(env, key, capsys):
    cfg = config.load_llm_config({key: "selfhosted"}, module_hint="coding")
    assert (cfg.provider, cfg.model, cfg.api_base, cfg.api_key) == ("selfhosted", "own-model", "http://selfhosted.invalid/v1", "own-secret")
    assert cfg.temperature == .2
    assert cfg.max_tokens == 8192
    assert cfg.timeout_s == 75
    assert "secret" not in repr(cfg)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("missing", ["MODEL", "API_KEY", "BASE_URL"])
def test_missing_switched_provider_identity_never_uses_gateway_fallback(env, missing):
    env.pop("SELFHOSTED_" + missing)
    cfg = config.load_llm_config({"llm_provider": "selfhosted"}, module_hint="coding")
    attr = {"MODEL": "model", "API_KEY": "api_key", "BASE_URL": "api_base"}[missing]
    assert getattr(cfg, attr) is None
    assert cfg.provider == "selfhosted"


def test_all_missing_selected_provider_fields_remain_unconfigured(env):
    for name in ("SELFHOSTED_MODEL", "SELFHOSTED_API_KEY", "SELFHOSTED_BASE_URL"):
        env.pop(name)
    cfg = config.load_llm_config({"provider": "selfhosted"}, module_hint="coding")
    assert cfg.model is cfg.api_key is cfg.api_base is None


def test_explicit_same_provider_keeps_existing_stage_identity_overrides(env):
    for params in ({}, {"llm_provider": "pjlab"}, {"provider": " PJLAB "}):
        cfg = config.load_llm_config(params, module_hint="coding")
        assert cfg.model == "module-gateway-model"
        assert cfg.api_key == "module-gateway-secret"
        assert cfg.api_base == "https://module.gateway.invalid/v1"


@pytest.mark.parametrize("alias", [False, True])
def test_explicit_identity_and_budgets_override_selected_provider(env, alias):
    prefix = "" if alias else "llm_"
    params = {"provider": "selfhosted", prefix + "model": "explicit-model", prefix + "api_key": "explicit-secret",
              prefix + "api_base": "http://explicit.invalid/chat/completions", "llm_temperature": .4,
              "llm_timeout_s": 15, "llm_max_tokens": 2048}
    cfg = config.load_llm_config(params, module_hint="coding")
    assert (cfg.model, cfg.api_key, cfg.api_base) == ("explicit-model", "explicit-secret", "http://explicit.invalid")
    assert (cfg.temperature, cfg.timeout_s, cfg.max_tokens) == (.4, 15, 2048)


def test_switch_against_global_provider_when_module_provider_absent(env):
    env.pop("CODING_LLM_PROVIDER")
    cfg = config.load_llm_config({"provider": "selfhosted"}, module_hint="coding")
    assert cfg.model == "own-model"
    assert cfg.api_key == "own-secret"


def test_provider_normalization_alias_is_not_a_switch(env):
    env["CODING_LLM_PROVIDER"] = "lab"
    cfg = config.load_llm_config({"provider": "lab1"}, module_hint="coding")
    assert cfg.provider == "lab"
    assert cfg.model == "module-gateway-model"


def test_switched_provider_can_use_its_documented_default_base(env):
    cfg = config.load_llm_config({"provider": "openai"}, module_hint="coding")
    assert cfg.api_base == "https://api.openai.com/v1"
    assert cfg.api_key == "unrelated-secret"  # It belongs to the newly selected provider.
    assert cfg.model is None  # No OPENAI_MODEL is configured in this isolated env.


def test_explicit_provider_without_any_prior_selection_is_isolated(env):
    env.pop("CODING_LLM_PROVIDER")
    env.pop("LLM_PROVIDER")
    cfg = config.load_llm_config({"provider": "selfhosted"}, module_hint="coding")
    assert cfg.model == "own-model"
    assert cfg.api_key == "own-secret"
