"""Coding transport thinking policy is explicit and provider-native."""
import json
from types import SimpleNamespace

import pytest

from metaagent.coding.llm import init_llm


@pytest.fixture
def transport(monkeypatch):
    captured=[]
    def capture(**options):
        captured.append(options)
        return options
    monkeypatch.setattr('metaagent.coding.llm.ChatOpenAI',capture)
    monkeypatch.setattr('metaagent.coding.llm.httpx.Client',lambda **_:object())
    monkeypatch.delenv('CODING_LLM_EXTRA_BODY_JSON',raising=False)
    def configure(thinking=None,provider='pjlab',model='model'):
        cfg=SimpleNamespace(provider=provider,model=model,api_key='offline-test-key',
            api_base='http://node.invalid/v1',timeout_s=30,max_tokens=8000,temperature=0.1,
            verify_ssl=True,force_streaming=False,reasoning_effort=None,thinking=thinking)
        monkeypatch.setattr('metaagent.config.load_llm_config',lambda *a,**k:cfg)
        return cfg
    return configure,captured


@pytest.mark.parametrize('thinking',['enabled','disabled'])
def test_configured_thinking_becomes_native_request_body(transport,thinking):
    configure,captured=transport
    configure(thinking)
    options=init_llm()
    assert options['extra_body']=={'thinking':{'type':thinking}}
    assert options['max_tokens']==8000 and options['max_retries']==0


def test_unspecified_policy_does_not_change_provider_default(transport):
    configure,_=transport
    configure(None)
    assert init_llm()['extra_body'] in (None,{})


def test_explicit_coding_json_overrides_configured_policy(transport,monkeypatch):
    configure,_=transport
    configure('disabled')
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON',json.dumps({'thinking':{'type':'enabled'},'custom_option':True}))
    assert init_llm()['extra_body']=={'thinking':{'type':'enabled'},'custom_option':True}


def test_explicit_legacy_override_has_no_conflicting_generated_native_flag(transport,monkeypatch):
    configure,_=transport
    configure('enabled')
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"enable_thinking":false}')
    assert init_llm()['extra_body']=={'enable_thinking':False}


def test_bailian_auto_default_preserved_without_explicit_policy(transport):
    configure,_=transport
    configure(None,provider='bailian',model='qwen-test')
    assert init_llm()['extra_body']=={'enable_thinking':False}


def test_bailian_hidden_disable_does_not_conflict_with_explicit_enable(transport):
    configure,_=transport
    configure('enabled',provider='bailian',model='qwen-test')
    assert init_llm()['extra_body']=={'thinking':{'type':'enabled'}}


def test_explicit_body_cannot_transmit_self_contradictory_aliases(transport,monkeypatch):
    configure,_=transport
    configure(None)
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"thinking":{"type":"disabled"},"enable_thinking":true}')
    with pytest.raises(ValueError,match='contradictory'):
        init_llm()
