from metaagent import config
from metaagent.screening import engine


def test_custom_provider_runtime_controls_are_loaded(monkeypatch):
    monkeypatch.setattr(config, "_DOTENV_LOADED", {"__shared__"})
    monkeypatch.setenv("CRS_BASE_URL", "https://example.test/openai")
    monkeypatch.setenv("CRS_API_KEY", "test-key")
    monkeypatch.setenv("CRS_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("CRS_FORCE_STREAMING", "true")
    monkeypatch.setenv("CRS_REASONING_EFFORT", "none")

    cfg = config.load_llm_config(
        {"llm_provider": "crs"},
        module_hint=None,
    )

    assert cfg.api_base == "https://example.test/openai/v1"
    assert cfg.model == "gpt-5.4-mini"
    assert cfg.force_streaming is True
    assert cfg.reasoning_effort == "none"


def test_screening_client_forwards_reasoning_effort(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(engine, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        engine,
        "load_llm_config",
        lambda *args, **kwargs: config.LLMConfig(
            provider="crs",
            model="gpt-5.4-mini",
            api_key="test-key",
            api_base="https://example.test/openai/v1",
            force_streaming=True,
            reasoning_effort="none",
        ),
    )

    engine.init_llm_model()

    assert captured["streaming"] is True
    assert captured["reasoning_effort"] == "none"
