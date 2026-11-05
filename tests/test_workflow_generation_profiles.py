"""Generation profiles bind the actual adapters and invalidate only their stage."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from test_workflow_task import task, options
from metaagent.workflow_runner import STAGES, _stage_config_hash, plan_workflow
from metaagent.workflow_task import resolve_runtime


@pytest.fixture(autouse=True)
def isolated_module_extra_body(monkeypatch):
    # Do not inherit the developer's selected live model profile. Tests declare
    # their generation extensions explicitly, including contradictory cases.
    for module in ("QUERY", "SCREENING", "CODING", "SYNTHESIS"):
        monkeypatch.delenv(module + "_LLM_EXTRA_BODY_JSON", raising=False)
    monkeypatch.delenv("LLM_EXTRA_BODY_JSON", raising=False)


def pi_options(task,monkeypatch,**kw):
    monkeypatch.setattr('metaagent.synthesis.pi_runtime.inspect_pi_runtime',lambda *a,**k:{'available':True,'compatible':True,'version':'1.3.0','fingerprint':'local-only-fixture'})
    return options(task,synthesis_backend='pi',**kw)


def hashes(plan):return {stage:_stage_config_hash(plan,stage) for stage in STAGES}


def test_synthesis_effective_body_is_bound_to_plan_and_only_pooling(task,monkeypatch):
    opts=pi_options(task,monkeypatch,model='same-unified-model')
    first=plan_workflow(opts)
    monkeypatch.setenv('SYNTHESIS_LLM_EXTRA_BODY_JSON','{"top_p":0.7}')
    second=plan_workflow(opts)
    assert {s for s in STAGES if hashes(first)[s]!=hashes(second)[s]}=={'pooling'}
    generation=second['config']['synthesis_inspection']['agent']['generation_binding']
    assert generation['model']=='same-unified-model' and generation['extra_body']['top_p']==.7
    invocation,_=resolve_runtime(opts,'synthesis')
    from metaagent.synthesis.pi_runtime import synthesis_generation_binding
    assert generation==synthesis_generation_binding(invocation)
    assert not opts.output_dir.exists()


def test_same_body_key_order_reuses_semantic_hash_and_screening_is_separate(task,monkeypatch):
    opts=pi_options(task,monkeypatch)
    first=plan_workflow(opts)
    monkeypatch.setenv('SCREENING_LLM_EXTRA_BODY_JSON','{"top_p":0.7,"thinking":{"type":"enabled","clear_thinking":false}}')
    second=plan_workflow(opts)
    assert {s for s in STAGES if hashes(first)[s]!=hashes(second)[s]}=={'screening','fulltext_screening'}
    monkeypatch.setenv('SCREENING_LLM_EXTRA_BODY_JSON','{"thinking":{"clear_thinking":false,"type":"enabled"},"top_p":0.7}')
    third=plan_workflow(opts)
    assert hashes(second)==hashes(third)
    assert second['config']['effective_llm_runtime']['screening']['extra_body_sha256']


def test_task_body_reaches_actual_screening_adapter_and_preserves_coding_env(task,monkeypatch):
    data=yaml.safe_load(task.read_text());profile={'thinking':'enabled','reasoning_effort':'low',
        'extra_body':{'thinking':{'type':'enabled','clear_thinking':False},'top_p':.4}}
    data['llm']={'screening':profile,'coding':profile}
    task.write_text(yaml.safe_dump(data));opts=options(task)
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"response_format":{"type":"json_object"}}')
    invoke,public=resolve_runtime(opts,'screening')
    assert invoke['llm_extra_body']['thinking']['clear_thinking'] is False
    assert 'llm_extra_body' not in public
    from metaagent.screening.engine import init_llm_model
    captured={}
    monkeypatch.setattr('metaagent.screening.engine.ChatOpenAI',lambda **kw:captured.update(kw) or SimpleNamespace())
    init_llm_model(config_overrides=invoke)
    try:
        assert captured['extra_body']=={'thinking':{'type':'enabled','clear_thinking':False},'top_p':.4}
        assert captured['reasoning_effort']=='low'
    finally:
        captured['http_client'].close();asyncio.run(captured['http_async_client'].aclose())
    coding,_=resolve_runtime(opts,'coding')
    assert coding['llm_extra_body']['response_format']=={'type':'json_object'}
    assert coding['llm_extra_body']['thinking']['clear_thinking'] is False


@pytest.mark.parametrize('module,value',[
    ('SCREENING','[]'),('CODING','not json'),('SYNTHESIS','{"top_p":NaN}'),('SYNTHESIS','{"messages":[]}'),
])
def test_invalid_body_fails_readonly_plan_without_writes(task,monkeypatch,module,value):
    opts=pi_options(task,monkeypatch)
    before=set(task.parent.rglob('*'))
    monkeypatch.setenv(module+'_LLM_EXTRA_BODY_JSON',value)
    with pytest.raises(ValueError):plan_workflow(opts)
    assert set(task.parent.rglob('*'))==before and not opts.output_dir.exists()


def test_opaque_vendor_body_secret_is_hash_only_not_public_manifest(task,monkeypatch):
    monkeypatch.setenv('SCREENING_LLM_EXTRA_BODY_JSON','{"vendor_private_token":"private-value-opaque-68492"}')
    plan=plan_workflow(options(task,stop_after='screening'))
    assert 'private-value-opaque-68492' not in json.dumps(plan)
    invocation,public=resolve_runtime(options(task),'screening')
    assert invocation['llm_extra_body']['vendor_private_token']=='private-value-opaque-68492'
    assert public['extra_body_sha256'] and 'llm_extra_body' not in public


@pytest.mark.parametrize('body,mode',[
    ({'thinking':{'type':'enabled'},'chat_template_kwargs':{'enable_thinking':False}},None),
    ({'enable_thinking':True,'chat_template_kwargs':{'enable_thinking':False}},None),
    ({'thinking':{'type':'disabled'},'enable_thinking':False,'chat_template_kwargs':{'enable_thinking':True}},None),
    ({'chat_template_kwargs':{'enable_thinking':False}},'enabled'),
    ({'chat_template_kwargs':{'enable_thinking':True}},'disabled'),
])
def test_nested_thinking_contradictions_fail_without_mutating_fields(body,mode):
    from metaagent.config import merge_thinking_policy
    original=copy.deepcopy(body)
    with pytest.raises(ValueError,match='contradictory|conflicts'):
        merge_thinking_policy(body,mode)
    assert body==original


@pytest.mark.parametrize('bad',['false',0,1,None,{},[]])
def test_nested_thinking_requires_actual_boolean(bad):
    from metaagent.config import merge_thinking_policy
    with pytest.raises(ValueError,match='must be a boolean'):
        merge_thinking_policy({'chat_template_kwargs':{'enable_thinking':bad}},None)


def test_matching_qwen_and_glm_thinking_preserve_all_extensions():
    from metaagent.config import merge_thinking_policy
    qwen={'chat_template_kwargs':{'enable_thinking':False,'vendor_extension':'kept'},'top_p':.8}
    assert merge_thinking_policy(qwen,None)==qwen
    assert merge_thinking_policy(qwen,'disabled')=={**qwen,'thinking':{'type':'disabled'}}
    glm={'thinking':{'type':'enabled','clear_thinking':False},'enable_thinking':True,'chat_template_kwargs':{'enable_thinking':True}}
    assert merge_thinking_policy(glm,'enabled')==glm


@pytest.mark.parametrize('module',['screening','coding'])
def test_nested_policy_blocks_adapter_before_model_construction(monkeypatch,module):
    cfg=SimpleNamespace(provider='pjlab',model='offline',api_key='synthetic',api_base='http://127.0.0.1:9/v1',timeout_s=1,max_tokens=32,temperature=0,verify_ssl=True,force_streaming=False,reasoning_effort=None,thinking='enabled')
    constructors=[]
    monkeypatch.setattr('metaagent.config.load_llm_config',lambda *a,**kw:cfg)
    if module=='screening':
        import metaagent.screening.engine as adapter
        monkeypatch.setattr(adapter,'load_llm_config',lambda *a,**kw:cfg)
        factory=adapter.init_llm_model
    else:
        import metaagent.coding.llm as adapter
        factory=adapter.init_llm
    monkeypatch.setattr(adapter,'ChatOpenAI',lambda **kw:constructors.append(kw))
    monkeypatch.setattr(adapter.httpx,'Client',lambda **kw:object())
    monkeypatch.setattr(adapter.httpx,'AsyncClient',lambda **kw:object())
    with pytest.raises(ValueError,match='contradictory|conflicts'):
        factory(config_overrides={'llm_extra_body':{'chat_template_kwargs':{'enable_thinking':False}}})
    assert constructors==[]


def test_common_env_native_and_task_nested_conflict_fail_readonly_plan(task,monkeypatch):
    data=yaml.safe_load(task.read_text())
    data['llm']={'screening':{'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}}}
    task.write_text(yaml.safe_dump(data))
    monkeypatch.setenv('SCREENING_LLM_EXTRA_BODY_JSON','{"thinking":{"type":"enabled","clear_thinking":false}}')
    original=set(task.parent.rglob('*'))
    with pytest.raises(ValueError,match='contradictory'):
        plan_workflow(options(task,stop_after='screening'))
    assert set(task.parent.rglob('*'))==original


def test_pi_matching_nested_qwen_kept_and_conflict_rejected():
    from metaagent.config import LLMConfig
    from metaagent.synthesis.pi_runtime import load_synthesis_extra_body
    cfg=LLMConfig(provider='local',model='offline',api_key='synthetic',api_base='http://127.0.0.1:9/v1',thinking='disabled')
    qwen={'chat_template_kwargs':{'enable_thinking':False}}
    value=load_synthesis_extra_body(cfg,{'llm_extra_body':qwen})
    assert value=={**qwen,'thinking':{'type':'disabled'}}
    with pytest.raises(ValueError,match='conflicts'):
        load_synthesis_extra_body(cfg,{'llm_extra_body':{'chat_template_kwargs':{'enable_thinking':True}}})
