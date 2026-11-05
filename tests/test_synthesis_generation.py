"""Effective production model options are bound to transport and output claims."""
from dataclasses import replace
import json
from pathlib import Path
import time

import httpx
import pytest

from metaagent.config import LLMConfig, merge_thinking_policy
from metaagent.synthesis import pi_agent, pi_runtime


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr('metaagent.config.load_runtime_env',lambda **kw:None)
    monkeypatch.setenv('SYNTHESIS_LLM_EXTRA_BODY_JSON','')
    monkeypatch.setenv('METAAGENT_LLM_REQUESTS_PER_MINUTE','')


def config(**kwargs):
    return LLMConfig(provider='local',model='model-A',api_key='sk-synthetic-generation-credential',
                     api_base='http://127.0.0.1:9/v1',max_tokens=1024,timeout_s=3,thinking='disabled',**kwargs)


def test_same_thinking_type_preserves_provider_extensions_and_conflicts_still_fail():
    body={'thinking':{'type':'enabled','clear_thinking':False,'provider_extension':'kept'},'tool_stream':True}
    assert merge_thinking_policy(body,'enabled')==body
    with pytest.raises(ValueError,match='conflicts'):merge_thinking_policy(body,'disabled')
    with pytest.raises(ValueError,match='contradictory'):merge_thinking_policy({'thinking':{'type':'enabled','clear_thinking':False},'enable_thinking':False},None)
    assert merge_thinking_policy(None,None) is None


@pytest.mark.parametrize('extra,thinking,effort',[
    ({'reasoning_split':True},'disabled',None),
    ({'chat_template_kwargs':{'enable_thinking':False}},'disabled',None),
    ({'thinking':{'type':'enabled','clear_thinking':False},'tool_stream':True},'enabled','low'),
])
def test_real_proxy_forwards_native_profile_to_upstream_without_control_changes(tmp_path,monkeypatch,extra,thinking,effort):
    cfg=replace(config(),thinking=thinking,reasoning_effort=effort)
    monkeypatch.setenv('SYNTHESIS_LLM_EXTRA_BODY_JSON',json.dumps(extra))
    captured=[];real_client=httpx.Client
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'data: {"model":"model-A","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\ndata: [DONE]\n\n')
    with real_client(trust_env=False) as caller:
        monkeypatch.setattr(httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(handle),trust_env=False,**kwargs))
        proxy=pi_runtime._RunProxy(cfg,{'max_turns':2,'max_tokens':5000},tmp_path,time.monotonic()+10)
        payload={'model':'model-A','messages':[{'role':'user','content':'fixture'}],'tools':[{'type':'function','function':{'name':'epi_tool'}}],'tool_choice':'auto','stream':True}
        try:response=caller.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},json=payload)
        finally:proxy.close()
    assert response.status_code==200 and len(captured)==1
    for key,value in extra.items():assert captured[0][key]==value
    assert captured[0]['model']==payload['model'] and captured[0]['messages']==payload['messages']
    assert captured[0]['tools']==payload['tools'] and captured[0]['tool_choice']=='auto'
    assert captured[0]['max_tokens']==1024 and captured[0]['stream'] is True
    if effort:assert captured[0]['reasoning_effort']==effort


@pytest.mark.parametrize('field',['model','messages','tools','tool_choice','stream','stream_options','max_tokens','max_completion_tokens','api_key','headers','response_format','temperature'])
def test_synthesis_extra_cannot_override_controls_or_credentials(field):
    with pytest.raises(ValueError,match='forbidden control'):
        pi_runtime.load_synthesis_extra_body(config(),{'llm_extra_body':{field:'blocked'}})


@pytest.mark.parametrize('body',[
    {'thinking':{'type':'enabled'}},
    {'enable_thinking':True},
    {'chat_template_kwargs':{'enable_thinking':True}},
    {'reasoning_effort':'low'},
])
def test_native_and_cfg_policies_must_agree(body):
    with pytest.raises(ValueError):pi_runtime.load_synthesis_extra_body(config(),{'llm_extra_body':body})


def test_effort_and_private_values_cannot_be_hidden_in_extra():
    cfg=replace(config(),thinking='enabled',reasoning_effort='high')
    with pytest.raises(ValueError,match='reasoning_effort conflicts'):
        pi_runtime.load_synthesis_extra_body(cfg,{'llm_extra_body':{'reasoning_effort':'low'}})
    with pytest.raises(ValueError,match='Credentials'):
        pi_runtime.load_synthesis_extra_body(config(),{'llm_extra_body':{'stop':[config().api_key]}})


def test_generation_fingerprint_binds_model_body_and_never_credential(tmp_path,monkeypatch):
    def load(params=None,**kw):
        params=params or {};cfg=config()
        return replace(cfg,**{field:params['llm_'+field] for field in ('model','provider','api_key','api_base','thinking','reasoning_effort','temperature','max_tokens') if 'llm_'+field in params})
    monkeypatch.setattr(pi_runtime,'load_llm_config',load)
    arguments={'records':[{'estimate_id':'a','point_estimate':1}],'research_question':'Synthetic question'}
    first=pi_agent.pi_synthesis_fingerprint(**arguments)
    changed=pi_agent.pi_synthesis_fingerprint(**arguments,runtime_overrides={'llm_model':'model-B'})
    assert first['fingerprint']!=changed['fingerprint']
    rotated=pi_agent.pi_synthesis_fingerprint(**arguments,runtime_overrides={'llm_api_key':'sk-rotated-synthetic-credential'})
    assert first['fingerprint']==rotated['fingerprint']
    one=pi_agent.pi_synthesis_fingerprint(**arguments,runtime_overrides={'llm_extra_body':{'reasoning_split':True,'top_p':.8}})
    two=pi_agent.pi_synthesis_fingerprint(**arguments,runtime_overrides={'llm_extra_body':'{"top_p":0.8,"reasoning_split":true}'})
    assert first['fingerprint']!=one['fingerprint'] and one['fingerprint']==two['fingerprint']
    assert config().api_key not in json.dumps(first) and 'api_key' not in first['generation_binding']
    assert first['generation_binding']['model']=='model-A'
    assert first['generation_binding']['extra_body']=={'thinking':{'type':'disabled'}}
    assert not list(tmp_path.iterdir())


def test_model_or_extra_change_does_not_resume_previous_claim(tmp_path,monkeypatch):
    def load(params=None,**kwargs):
        return replace(config(),model=(params or {}).get('llm_model','model-A'))
    monkeypatch.setattr(pi_runtime,'load_llm_config',load)
    calls=[]
    def session(workspace,*args,**kwargs):calls.append(str(workspace));return {'status':'failed','error':'synthetic interruption'}
    monkeypatch.setattr(pi_runtime,'run_pi_session',session)
    kwargs={'records':[{'estimate_id':'a','point_estimate':1}],'research_question':'Q?','output_dir':tmp_path/'out'}
    first=pi_agent.run_pi_synthesis(**kwargs)
    assert first['status']=='failed' and len(calls)==1
    claim=tmp_path/'out/pi_synthesis_manifest.json';before=claim.read_bytes()
    for override in ({'llm_model':'model-B'},{'llm_extra_body':{'reasoning_split':True}}):
        changed=pi_agent.run_pi_synthesis(**kwargs,resume=True,runtime_overrides=override)
        assert changed['status']=='failed' and 'claimed' in changed['error']['message']
        assert len(calls)==1 and claim.read_bytes()==before
    resumed=pi_agent.run_pi_synthesis(**kwargs,resume=True)
    assert resumed['status']=='failed' and len(calls)==2


def test_explicit_task_vendor_body_merges_environment_without_losing_coding_format(monkeypatch):
    from metaagent.config import resolve_extra_body
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"response_format":{"type":"json_object"},"reasoning_split":false}')
    value=resolve_extra_body({'llm_extra_body':{'reasoning_split':True,'chat_template_kwargs':{'enable_thinking':False}}},module_hint='coding')
    assert value=={'response_format':{'type':'json_object'},'reasoning_split':True,'chat_template_kwargs':{'enable_thinking':False}}
    assert resolve_extra_body({'extra_body':{'top_p':.9}},module_hint='synthesis')=={'top_p':.9}


def test_task_and_env_thinking_alias_conflicts_are_not_silently_normalized(monkeypatch):
    from metaagent.config import resolve_extra_body
    monkeypatch.setenv('SYNTHESIS_LLM_EXTRA_BODY_JSON','{"thinking":{"type":"enabled","clear_thinking":false}}')
    with pytest.raises(ValueError,match='contradictory'):
        resolve_extra_body({'llm_extra_body':{'enable_thinking':False}},module_hint='synthesis')


def test_coding_client_receives_explicit_vendor_body_and_retains_object_mode(monkeypatch):
    import metaagent.coding.llm as coding
    captured={}
    monkeypatch.setenv('CODING_LLM_PROVIDER','openai')
    monkeypatch.setenv('CODING_LLM_MODEL','model-A')
    monkeypatch.setenv('CODING_LLM_API_BASE','http://127.0.0.1:9/v1')
    monkeypatch.setenv('CODING_LLM_API_KEY','synthetic-client-credential')
    monkeypatch.setenv('CODING_LLM_THINKING','disabled')
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"response_format":{"type":"json_object"}}')
    monkeypatch.setattr(coding,'ChatOpenAI',lambda **kwargs:captured.update(kwargs) or object())
    coding.init_llm({'llm_extra_body':{'reasoning_split':True}})
    assert captured['extra_body']=={'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'reasoning_split':True}


@pytest.mark.parametrize('module',['screening','coding','synthesis'])
@pytest.mark.parametrize('field',['model','messages','tools','tool_choice','stream','stream_options',
    'max_tokens','max_completion_tokens','temperature','api_key','base_url','headers'])
def test_common_extra_body_cannot_override_declared_runtime(module,field,monkeypatch):
    from metaagent.config import resolve_extra_body
    monkeypatch.setenv(module.upper()+'_LLM_EXTRA_BODY_JSON','')
    with pytest.raises(ValueError,match='forbidden control'):
        resolve_extra_body({'llm_extra_body':{field:'blocked'}},module_hint=module)
    monkeypatch.setenv(module.upper()+'_LLM_EXTRA_BODY_JSON',json.dumps({field:'blocked'}))
    with pytest.raises(ValueError,match='forbidden control'):
        resolve_extra_body({},module_hint=module)


def test_coding_model_cap_override_rejected_before_any_actual_wire(monkeypatch):
    import metaagent.coding.llm as coding
    attempts=[];clients=[];real_client=httpx.Client
    def handle(request):
        attempts.append(request)
        return httpx.Response(500)
    def client(**kwargs):
        kwargs.pop('trust_env',None)
        value=real_client(transport=httpx.MockTransport(handle),trust_env=False,**kwargs)
        clients.append(value);return value
    monkeypatch.setattr(coding.httpx,'Client',client)
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"response_format":{"type":"json_object"}}')
    monkeypatch.setattr('metaagent.config.load_llm_config',lambda *a,**k:replace(config(),max_tokens=128))
    try:
        with pytest.raises(ValueError,match='forbidden control'):
            # This exact pair previously overrode model/cap in the actual SDK body.
            model=coding.init_llm({'llm_extra_body':{'model':'overridden-model','max_completion_tokens':999999}})
            model.invoke([{'role':'user','content':'Offline forbidden control probe'}])
    finally:
        for value in clients:value.close()
    assert not attempts
