"""Offline tests for provider binding and real-service smoke orchestration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.scripts.smoke_workflow import build_fixture, main, module_settings, summarize_manifest


@pytest.fixture
def provider_env(monkeypatch):
    # Avoid loading real workspace credentials into these isolated tests.
    monkeypatch.setattr('metaagent.config.load_runtime_env', lambda *a, **k:None)
    monkeypatch.setenv('SELFHOSTED_MODEL','own-node-model')
    monkeypatch.setenv('SELFHOSTED_BASE_URL','http://node.invalid/v1')
    monkeypatch.setenv('SELFHOSTED_API_KEY','offline-node-test-key')
    for module in ('QUERY','SCREENING','CODING','SYNTHESIS'):
        monkeypatch.setenv(module+'_LLM_PROVIDER','pjlab')
        monkeypatch.setenv(module+'_LLM_MODEL','wrong-gateway-model')
        monkeypatch.setenv(module+'_LLM_API_BASE','https://wrong-gateway.invalid/v1')
        monkeypatch.setenv(module+'_LLM_API_KEY','wrong-gateway-test-key')


def test_provider_selection_binds_every_module_without_gateway_inheritance(tmp_path,provider_env):
    from metaagent.workflow_runner import WorkflowOptions
    from metaagent.workflow_task import resolve_runtime
    config, inputs, task = build_fixture(tmp_path,provider='selfhosted',backend='llm',max_tokens=3000,timeout=33)
    for name in ('query','screening','coding','synthesis'):
        spec=task['llm'][name]
        assert spec['provider']=='selfhosted'
        assert spec['model']=='own-node-model'
        assert spec['api_base']=='http://node.invalid/v1'
        assert spec['api_key_env']=='SELFHOSTED_API_KEY'
        assert spec['max_tokens']==3000 and spec['timeout_s']==33
        options=WorkflowOptions(profile='task',dataset_root=tmp_path,output_dir=tmp_path/'run',task_config=config,raw_input=inputs,input_mode='raw_pool')
        private,public=resolve_runtime(options,name,require_credentials=True)
        assert private['llm_model']=='own-node-model'
        assert private['llm_api_key']=='offline-node-test-key'
        assert private['llm_api_base']=='http://node.invalid/v1'
        assert 'offline-node-test-key' not in config.read_text()
        assert 'llm_api_key' not in public


def test_explicit_model_base_and_report_flag(tmp_path,provider_env):
    _,_,task=build_fixture(tmp_path,provider='selfhosted',model='override-model',
        api_base='http://override.invalid/v1/chat/completions',llm_report=True)
    assert task['analysis_protocol']['llm_report']
    assert all(s['model']=='override-model' and s['api_base']=='http://override.invalid/v1' for s in task['llm'].values())


def test_unknown_provider_does_not_fall_back_to_module_or_global(monkeypatch,provider_env):
    monkeypatch.setenv('LLM_MODEL','global-gateway-model')
    monkeypatch.delenv('UNCONFIGURED_MODEL',raising=False)
    with pytest.raises(ValueError,match='own model and API base'):
        module_settings(provider='unconfigured')


def test_unchanged_fixture_does_not_rewrite_inputs(tmp_path):
    build_fixture(tmp_path,backend='llm')
    files=[tmp_path/name for name in ('synthetic.pdf','codebook.yaml','task.yaml','inputs.jsonl')]
    before={p.name:(p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_ino) for p in files}
    build_fixture(tmp_path,backend='llm')
    after={p.name:(p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_ino) for p in files}
    assert before==after


def test_summary_distinguishes_configured_and_observed_models_and_cache_time(tmp_path):
    calls=tmp_path/'llm_calls.jsonl'
    calls.write_text(json.dumps({'stage':'stage_a','status':'ok','model':'requested-model',
        'response_metadata':{'model_name':'observed-model'},'raw_response':'never publish this',
        'wall_time_ms':1250,'usage':{'input_tokens':10,'output_tokens':20}})+'\n')
    coverage=tmp_path/'coverage.json'
    coverage.write_text(json.dumps({'record_id':'synthetic-report','status':'complete','variant':'without_b',
        'stage_a_calls':1,'stage_b_calls':0,'completed_blocks':['main-block-1']}))
    synthesis=tmp_path/'synthesis_result.json'
    synthesis.write_text(json.dumps({'status':'single_estimate','result':{'pooled_mean':5,'unit':'days'},
        'counts':{'selected':1},'llm_report':{'status':'accepted'}}))
    summary=summarize_manifest({'status':'complete','config':{'effective_llm_runtime':{
        'coding':{'llm_model':'requested-model','llm_provider':'selfhosted','llm_api_key':'never publish key'}}},
        'stage_results':{'coding':{'status':'complete','reused':True,'walltime_s':7,
            'output_hashes':{str(calls):'hash',str(coverage):'hash'}}},
        'artifacts':{'synthesis_result':str(synthesis)}})
    stage=summary['stages']['coding']
    assert stage['attempt_walltime_s']==7 and stage['current_execution_walltime_s']==0
    assert stage['observed_response_models']==['observed-model']
    assert stage['calls'][0]['walltime_s']==1.25
    assert stage['coding_coverage'][0]['stage_b_calls']==0
    assert summary['analyses']['synthesis_result']['result']['pooled_mean']==5
    assert 'never publish' not in json.dumps(summary)


def test_noarg_behavior_retains_original_output_and_full_run(tmp_path,monkeypatch,capsys):
    monkeypatch.chdir(tmp_path)
    options=[]
    def workflow(option):
        options.append(option)
        return {'status':'complete','artifacts':{},'stage_results':{}}
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',workflow)
    assert main([])==0
    assert len(options)==1 and options[0].ablation=='full'
    assert options[0].output_dir==tmp_path/'runs/service_smoke/run'
    result=json.loads((tmp_path/'runs/service_smoke/smoke_result.json').read_text())
    assert result['status']=='complete' and 'started_at' in result and 'finished_at' in result
    assert 'preflight' not in result


def test_variants_and_dry_run_never_contact_service(tmp_path,monkeypatch,provider_env,capsys):
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',lambda *_:pytest.fail('No workflow calls in dry-run'))
    assert main(['--output',str(tmp_path),'--provider','selfhosted','--backend','llm','--dry-run',
                 '--variants','full','without_a','without_b','--llm-report'])==0
    result=json.loads((tmp_path/'smoke_result.json').read_text())
    assert result['status']=='dry_run' and len(result['variants'])==3
    assert 'offline-node-test-key' not in json.dumps(result)


def test_outage_preflight_stops_before_workflow(tmp_path,monkeypatch,provider_env,capsys):
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',lambda *_:pytest.fail('No workflow/MinerU on outage'))
    probes=[]
    def probe(cfg,timeout):
        probes.append((cfg.model,cfg.api_base,timeout))
        return {'status':'service_unavailable','configured_model':cfg.model,'http_status':503,
                'classification':'no_healthy_upstream','elapsed_s':0.1}
    monkeypatch.setattr('metaagent.service_health.probe_runtime',probe)
    assert main(['--output',str(tmp_path),'--provider','selfhosted','--timeout','7'])==1
    assert probes==[('own-node-model','http://node.invalid/v1',7)]
    result=json.loads((tmp_path/'smoke_result.json').read_text())
    assert result['status']=='service_unavailable' and result['variants']=={}
    assert (tmp_path/'endpoint_health.json').is_file() and not (tmp_path/'run').exists()


def test_no_preflight_override_allows_explicit_workflow(tmp_path,monkeypatch,provider_env,capsys):
    called=[]
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',lambda o:(called.append(o) or {'status':'complete','artifacts':{},'stage_results':{}}))
    monkeypatch.setattr('metaagent.service_health.probe_runtime',lambda *a,**k:pytest.fail('Preflight disabled'))
    assert main(['--output',str(tmp_path),'--provider','selfhosted','--no-preflight'])==0
    assert len(called)==1


def test_requested_variants_run_in_isolated_directories(tmp_path,monkeypatch,capsys):
    called=[]
    def workflow(options):
        called.append(options)
        return {'status':'complete','artifacts':{},'stage_results':{}}
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',workflow)
    assert main(['--output',str(tmp_path),'--variants','full','without_a','without_b'])==0
    assert [option.ablation for option in called]==['full','without_a','without_b']
    assert len({option.output_dir for option in called})==3


def test_redaction_handles_json_special_characters(monkeypatch):
    from tools.scripts.smoke_workflow import _sanitize
    secret='offline-"quoted"-test-key\\suffix'
    monkeypatch.setenv('SELFHOSTED_API_KEY',secret)
    result=_sanitize({'nested':[{'model':'returned '+secret}]})
    assert result['nested'][0]['model']=='returned [REDACTED]'


def test_failed_invocations_keep_distinct_immutable_receipts_and_stable_inputs(tmp_path,monkeypatch,provider_env,capsys):
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',lambda *_:pytest.fail('No workflow during endpoint outage'))
    calls=[]
    def probe(cfg,timeout):
        calls.append(len(calls)+1)
        return {'status':'service_unavailable','configured_model':cfg.model,'http_status':503,
                'classification':'no_healthy_upstream','elapsed_s':calls[-1]/10}
    monkeypatch.setattr('metaagent.service_health.probe_runtime',probe)
    args=['--output',str(tmp_path),'--provider','selfhosted']
    assert main(args)==1
    first=json.loads((tmp_path/'smoke_result.json').read_text())
    first_path=Path(first['receipt_path'])
    first_bytes=first_path.read_bytes()
    health_path=first_path.parent/'endpoint_health.json'
    first_health=health_path.read_bytes()
    inputs=[tmp_path/name for name in ('synthetic.pdf','task.yaml','inputs.jsonl','codebook.yaml')]
    stable={p.name:(p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_ino) for p in inputs}
    assert main(args)==1
    second=json.loads((tmp_path/'smoke_result.json').read_text())
    assert first['attempt_id']!=second['attempt_id']
    assert first_path.read_bytes()==first_bytes and health_path.read_bytes()==first_health
    receipts=list((tmp_path/'attempts').glob('*/smoke_result.json'))
    assert len(receipts)==2 and Path(second['receipt_path']).is_file()
    assert json.loads((tmp_path/'endpoint_health.json').read_text())['elapsed_s']==0.2
    assert all((p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_ino)==stable[p.name] for p in inputs)
    assert all(json.loads(path.read_text())['status']=='service_unavailable' for path in receipts)


def test_default_budget_inherits_each_module_instead_of_capping_reasoning(tmp_path,provider_env,monkeypatch):
    from metaagent.workflow_runner import WorkflowOptions
    from metaagent.workflow_task import resolve_runtime
    monkeypatch.setenv('CODING_LLM_MAX_TOKENS','8192')
    monkeypatch.setenv('SCREENING_LLM_MAX_TOKENS','4096')
    config,inputs,task=build_fixture(tmp_path,provider='selfhosted')
    assert all('max_tokens' not in spec for spec in task['llm'].values())
    opts=WorkflowOptions(profile='task',dataset_root=tmp_path,output_dir=tmp_path/'run',task_config=config)
    assert resolve_runtime(opts,'coding')[0]['llm_max_tokens']==8192
    assert resolve_runtime(opts,'screening')[0]['llm_max_tokens']==4096


def test_explicit_thinking_policy_is_saved_for_all_modules(tmp_path,provider_env):
    _,_,task=build_fixture(tmp_path,provider='selfhosted',thinking='disabled')
    assert all(spec['thinking']=='disabled' for spec in task['llm'].values())
    with pytest.raises(ValueError,match='thinking'):
        module_settings(thinking='guess')


def test_provider_and_report_options_keep_full_pipeline_as_default(tmp_path,monkeypatch,provider_env,capsys):
    from metaagent.workflow_task import read_task
    called=[]
    def workflow(options):
        called.append(options)
        assert options.ablation=='full'
        assert options.start_at=='retrieval' and options.stop_after=='pooling'
        task=read_task(options.task_config)
        assert task.analysis_protocol['llm_report'] is True
        assert task.coding.backend=='langextract'
        return {'status':'complete','artifacts':{},'stage_results':{}}
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',workflow)
    assert main(['--output',str(tmp_path),'--provider','selfhosted',
                 '--no-preflight','--llm-report'])==0
    assert len(called)==1
    result=json.loads((tmp_path/'smoke_result.json').read_text())
    assert list(result['variants'])==['full']
    assert called[0].output_dir==tmp_path/'run'
    assert not (tmp_path/'run_without_a').exists()
    assert not (tmp_path/'run_without_b').exists()


def test_preflight_accepts_effective_vendor_body_but_labels_transport_scope(tmp_path,monkeypatch,provider_env,capsys):
    from metaagent.config import LLMConfig
    monkeypatch.setenv('CODING_LLM_EXTRA_BODY_JSON','{"response_format":{"type":"json_object"},"reasoning_split":true}')
    monkeypatch.setattr('metaagent.workflow_runner.run_workflow',lambda *_:pytest.fail('Unavailable service must stop workflow'))
    seen=[]
    def probe(cfg,timeout):
        assert isinstance(cfg,LLMConfig) and not hasattr(cfg,'extra_body')
        seen.append(cfg)
        return {'status':'service_unavailable','configured_model':cfg.model,'http_status':503}
    monkeypatch.setattr('metaagent.service_health.probe_runtime',probe)
    assert main(['--output',str(tmp_path),'--provider','selfhosted'])==1
    receipt=json.loads((tmp_path/'endpoint_health.json').read_text())
    assert len(seen)==1 and seen[0].model=='own-node-model'
    assert receipt['scope']=='transport_availability_only'
    assert receipt['extra_body_exercised'] is False and receipt['configured_extra_body_present'] is True
