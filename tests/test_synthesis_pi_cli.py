"""Native CLI integration; only the external Pi boundary is a test double.

The child process uses the real Click entry point, task validation, workflow
executor, input adapters and content-addressed resume. A socket guard prevents
accidental service calls; Pi scientific/tool contracts are tested separately.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native(tmp_path):
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text('''
import hashlib,json,os,socket,sys,types
from pathlib import Path
def deny(*a,**k): raise AssertionError("test forbids external network")
socket.socket.connect=deny
socket.socket.connect_ex=deny
socket.getaddrinfo=deny
import metaagent.config as config
config.load_runtime_env=lambda **kw: None
runtime=types.ModuleType('metaagent.synthesis.pi_runtime')
def inspect(command=None):
    return {'available':os.environ.get('PI_FIXTURE_AVAILABLE','1')=='1','compatible':True,
            'version':'1.3.0','executable':command or '/fixture/pi',
            'fingerprint':os.environ.get('PI_FIXTURE_RUNTIME_HASH','stable')}
runtime.inspect_pi_runtime=inspect
def binding(runtime_overrides=None,*,cfg=None):
    cfg=cfg or config.load_llm_config(runtime_overrides or {},module_hint='synthesis')
    return {**{key:getattr(cfg,key) for key in ['provider','model','api_base','temperature','timeout_s','max_tokens','verify_ssl','force_streaming','reasoning_effort','thinking']},'extra_body':{}}
runtime.synthesis_generation_binding=binding
sys.modules[runtime.__name__]=runtime
agent=types.ModuleType('metaagent.synthesis.pi_agent')
def fingerprint(*,input_path=None,records=None,research_question,method_sources,protocol=None,settings=None,source_roles=None,runtime_overrides=None,review_context=None):
    return {'input':hashlib.sha256(Path(input_path).read_bytes()).hexdigest() if input_path else 'pending',
            'methods':{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in method_sources}, 'source_roles':source_roles, 'review_context':review_context, 'generation_model':(runtime_overrides or {}).get('llm_model')}
def run(*,input_path=None,records=None,research_question,method_sources,output_dir,protocol=None,settings=None,runtime_overrides=None,resume=False,source_roles=None,review_context=None):
    from metaagent.synthesis.cli import read_estimates
    rows=read_estimates(Path(input_path)) if input_path else records
    event={'question':research_question,'methods':[str(p) for p in method_sources],
           'protocol_supplied':protocol is not None,'records':len(rows),'settings':settings,
           'model':runtime_overrides.get('llm_model'),'credential_received':bool(runtime_overrides.get('llm_api_key')),
           'resume':resume,'output_dir':str(output_dir),'source_roles':source_roles,'review_context':review_context}
    with Path(os.environ['PI_FIXTURE_CALLS']).open('a') as f:f.write(json.dumps(event)+'\\n')
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    print('Pi fixture diagnostics')
    status=os.environ.get('PI_FIXTURE_STATUS','complete')
    result={'status':status,'backend':'pi','exploratory':protocol is None,
            'counts':{'input':len(rows),'selected':len(rows),'review':0},
            'result':{'point_estimate':4.5} if status=='complete' else None}
    artifact=output_dir/'synthesis_result.json';artifact.write_text(json.dumps(result))
    report=output_dir/'synthesis_report.md';report.write_text('Fixture execution artifact')
    result['artifacts']={'synthesis_result':str(artifact),'synthesis_report':str(report)}
    return result
agent.pi_synthesis_fingerprint=fingerprint
agent.run_pi_synthesis=run
sys.modules[agent.__name__]=agent
''')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(guard) + os.pathsep + str(ROOT)
    env['PI_FIXTURE_CALLS'] = str(tmp_path / 'calls.jsonl')
    for module in ('QUERY', 'SCREENING', 'CODING', 'SYNTHESIS'):
        env.update({f'{module}_LLM_PROVIDER': 'openai', f'{module}_LLM_MODEL': module.lower()+'-fixture',
                    f'{module}_LLM_API_BASE': 'http://127.0.0.1:9/v1',
                    f'{module}_LLM_API_KEY': 'synthetic-private-pi-credential'})
    data = tmp_path / 'coding.jsonl'
    data.write_text(json.dumps({'record_id':'study:one','parameter_type':'serial_interval','estimate_measure':'mean',
                               'unit':'days','point_estimate':4.5})+'\n')
    method = tmp_path / 'methods.md'
    method.write_text('Methods: keep distinct cohorts and report assumptions.')
    book = tmp_path / 'book.yaml'
    book.write_text(yaml.safe_dump({'project':{'name':'synthetic','effect_type':'serial_interval'},
                                   'fields':[{'name':'point_estimate','type':'float'}]}))
    task = tmp_path / 'task.yaml'
    task.write_text(yaml.safe_dump({'version':'1','task_id':'pi-test','disease':'synthetic',
        'topic':'serial_interval','research_question':'What interval is supported?', 'coding':{'backend':'llm'},
        'codebook':'book.yaml','review_protocol':{'version':'v1','criteria':[{'id':'original','description':'Original observations'}],
        'logic':'original'},'synthesis':{'backend':'pi','method_sources':['methods.md'],'max_turns':3}}))
    def invoke(*arguments, **extra_env):
        return subprocess.run([sys.executable,'-m','metaagent.cli',*map(str,arguments)],cwd=ROOT,
                              env={**env,**extra_env},capture_output=True,text=True,timeout=30)
    return invoke, data, method, task, tmp_path


@pytest.mark.parametrize('extension',['jsonl','csv','xlsx'])
def test_actual_agent_cli_reads_coding_tables_and_keeps_secrets_private(native, extension):
    invoke, data, method, _, tmp = native
    if extension == 'csv':
        data = tmp/'coding.csv'
        data.write_text('record_id,point_estimate\nstudy:one,4.5\n')
    elif extension == 'xlsx':
        import pandas as pd
        data = tmp/'coding.xlsx'
        pd.DataFrame([{'record_id':'study:one','point_estimate':4.5}]).to_excel(data,index=False)
    output = tmp/'agent'
    result = invoke('synthesis','agent','--input',data,'--research-question','What interval?',
                    '--method-source',method,'--output',output,'--json')
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload['status'] == 'complete' and payload['exploratory']
    assert 'Pi fixture diagnostics' in result.stderr
    call = json.loads((tmp/'calls.jsonl').read_text())
    assert call['records'] == 1 and call['model'] == 'synthesis-fixture' and call['credential_received']
    assert 'synthetic-private-pi-credential' not in result.stdout + (tmp/'calls.jsonl').read_text()
    assert Path(payload['artifacts']['synthesis_result']).is_file()


def test_agent_dry_run_has_no_network_or_output_side_effects(native):
    invoke, data, method, _, tmp = native
    output = tmp/'dry-output'
    result = invoke('synthesis','agent','--input',data,'--research-question','Question',
                    '--method-source',method,'--output',output,'--dry-run','--json')
    assert result.returncode == 0, result.stderr + result.stdout
    payload=json.loads(result.stdout)
    assert payload['status'] == 'planned' and payload['runtime']['model']=='synthesis-fixture'
    assert 'synthetic-private-pi-credential' not in result.stdout
    assert not output.exists() and not (tmp/'calls.jsonl').exists()


def test_agent_dry_run_validates_environment_name_without_model_calls(native):
    invoke,data,_,_,tmp=native
    result=invoke('synthesis','agent','--input',data,'--research-question','Question',
                  '--output',tmp/'bad-key-env','--api-key-env','bad name','--dry-run','--json')
    assert result.returncode!=0
    assert '--api-key-env must name' in json.loads(result.stdout)['error']['message']
    assert not (tmp/'bad-key-env').exists() and not (tmp/'calls.jsonl').exists()


@pytest.mark.parametrize('case',['missing_input','missing_methods','missing_workflow_methods','invalid_budget'])
def test_json_parse_failures_are_one_document_before_any_side_effect(native,case):
    invoke,data,method,task,tmp=native
    args=['synthesis','agent','--input',data,'--research-question','Question','--output',tmp/'not-created','--json']
    if case=='missing_input':args[args.index('--input')+1]=tmp/'missing.csv'
    elif case=='missing_methods':args.extend(['--method-source',tmp/'missing.md'])
    elif case=='invalid_budget':args.extend(['--max-turns','0'])
    else:args=['workflow','plan','--task-config',task,'--start-at','pooling','--estimates-input',data,
               '--method-source',tmp/'missing.md','--output-dir',tmp/'not-created','--json']
    result=invoke(*args)
    assert result.returncode==2
    payload=json.loads(result.stdout)
    assert payload['status']=='failed' and payload['error']['suggestion']
    assert not (tmp/'not-created').exists() and not (tmp/'calls.jsonl').exists()


@pytest.mark.parametrize('status',['partial','failed','protocol_pending'])
def test_agent_pending_and_failure_keep_artifacts_and_nonzero_exit(native, status):
    invoke, data, _, _, tmp = native
    result = invoke('synthesis','agent','--input',data,'--research-question','Question',
                    '--output',tmp/'pending','--json',PI_FIXTURE_STATUS=status)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload['status'] == status and Path(payload['artifacts']['synthesis_result']).is_file()


def test_pi_unavailable_fails_before_writing_outputs_or_calling(native):
    invoke, data, _, _, tmp = native
    result = invoke('synthesis','agent','--input',data,'--research-question','Question',
                    '--output',tmp/'unavailable','--json',PI_FIXTURE_AVAILABLE='0')
    assert result.returncode != 0 and json.loads(result.stdout)['status'] == 'failed'
    assert not (tmp/'unavailable').exists() and not (tmp/'calls.jsonl').exists()


def test_workflow_plan_pi_without_protocol_is_local_and_task_relative(native):
    invoke, data, method, task, tmp = native
    output=tmp/'workflow'
    result=invoke('workflow','plan','--task-config',task,'--estimates-input',data,
                  '--start-at','pooling','--output-dir',output,'--json')
    assert result.returncode==0,result.stderr+result.stdout
    plan=json.loads(result.stdout)
    assert plan['config']['synthesis_settings']['backend']=='pi'
    assert plan['config']['synthesis_settings']['research_question']=='What interval is supported?'
    assert plan['config']['synthesis_inspection']['method_source_sha256'][str(method)]==hashlib.sha256(method.read_bytes()).hexdigest()
    assert not output.exists() and not (tmp/'calls.jsonl').exists()


def test_actual_workflow_pi_dispatch_resume_and_method_change_invalidation(native):
    invoke, data, method, task, tmp=native
    args=('workflow','run','--task-config',task,'--estimates-input',data,'--start-at','pooling','--output-dir',tmp/'flow','--json')
    result=invoke(*args)
    assert result.returncode==0,result.stderr+result.stdout
    first=json.loads(result.stdout)
    assert first['status']=='complete' and not first['stage_results']['pooling']['reused']
    assert first['config']['synthesis_settings']['max_turns']==3
    raw_result=json.loads(Path(first['artifacts']['synthesis_result']).read_text())
    assert 'workflow_coverage' not in raw_result
    assert Path(first['artifacts']['synthesis_report']).read_text()=='Fixture execution artifact'
    assert Path(first['artifacts']['workflow_coverage']).is_file()
    resumed=invoke(*args)
    assert resumed.returncode==0,resumed.stderr+resumed.stdout
    assert json.loads(resumed.stdout)['stage_results']['pooling']['reused']
    assert len((tmp/'calls.jsonl').read_text().splitlines())==1
    method.write_text(method.read_text()+'\nUpdated source version.')
    changed=invoke(*args)
    assert changed.returncode==0,changed.stderr+changed.stdout
    assert not json.loads(changed.stdout)['stage_results']['pooling']['reused']
    assert len((tmp/'calls.jsonl').read_text().splitlines())==2
    runtime_changed=invoke(*args,PI_FIXTURE_RUNTIME_HASH='different-local-version')
    assert runtime_changed.returncode==0,runtime_changed.stderr+runtime_changed.stdout
    assert not json.loads(runtime_changed.stdout)['stage_results']['pooling']['reused']
    assert len((tmp/'calls.jsonl').read_text().splitlines())==3


def test_workflow_cli_override_pi_and_partial_status(native):
    invoke,data,method,task,tmp=native
    definition=yaml.safe_load(task.read_text());definition.pop('synthesis');task.write_text(yaml.safe_dump(definition))
    result=invoke('workflow','run','--task-config',task,'--estimates-input',data,'--start-at','pooling',
                  '--synthesis-backend','pi','--research-question','Explicit question','--method-source',method,
                  '--synthesis-max-turns','2','--output-dir',tmp/'partial','--json',PI_FIXTURE_STATUS='partial')
    assert result.returncode==1
    payload=json.loads(result.stdout)
    assert payload['status']=='partial' and payload['stage_results']['pooling']['status']=='partial'
    call=json.loads((tmp/'calls.jsonl').read_text())
    assert call['question']=='Explicit question' and call['settings']['max_turns']==2


def test_workflow_pi_incomplete_resume_uses_original_attempt_and_preserves_log(native):
    invoke,data,_,task,tmp=native
    args=('workflow','run','--task-config',task,'--start-at','pooling','--estimates-input',data,
          '--output-dir',tmp/'resume-flow','--json')
    first=invoke(*args,PI_FIXTURE_STATUS='partial')
    assert first.returncode==1
    before=json.loads(first.stdout)['stage_results']['pooling']
    old_log=Path(before['log']);old_bytes=old_log.read_bytes()
    resumed=invoke(*args)
    assert resumed.returncode==0,resumed.stderr+resumed.stdout
    after=json.loads(resumed.stdout)['stage_results']['pooling']
    assert after['attempt_directory']==before['attempt_directory']
    assert after['log']!=before['log'] and old_log.read_bytes()==old_bytes
    calls=[json.loads(x) for x in (tmp/'calls.jsonl').read_text().splitlines()]
    assert len(calls)==2 and all(c['resume'] for c in calls)
    assert calls[0]['output_dir']==calls[1]['output_dir']


def test_standalone_resume_flag_reaches_business_api(native):
    invoke,data,_,_,tmp=native
    result=invoke('synthesis','agent','--input',data,'--research-question','Question',
                  '--output',tmp/'resume-agent','--resume','--json')
    assert result.returncode==0,result.stderr+result.stdout
    assert json.loads((tmp/'calls.jsonl').read_text())['resume'] is True


def test_old_deterministic_cli_and_omitted_task_backend_remain_compatible(native):
    invoke,_,_,task,tmp=native
    definition=yaml.safe_load(task.read_text());definition.pop('synthesis')
    protocol={'analysis_id':'fixture','parameter_type':'serial_interval','estimate_measure':'mean','unit':'days',
              'method':'fixed','uncertainty_rules':{'allowed_types':['SE']},
              'independence':{'unit':'record_id','assert_independent_reports':True}}
    definition['analysis_protocol']=protocol;task.write_text(yaml.safe_dump(definition))
    data=tmp/'legacy.jsonl';data.write_text(json.dumps({'record_id':'one','parameter_type':'serial_interval',
        'estimate_measure':'mean','unit':'days','point_estimate':4.5,'uncertainty_type':'SE','se':.2})+'\n')
    path=tmp/'analysis.yaml';path.write_text(yaml.safe_dump(protocol))
    old=invoke('synthesis','run','--input',data,'--protocol',path,'--output',tmp/'old','--json')
    assert old.returncode==0,old.stderr+old.stdout
    assert json.loads(old.stdout)['status']=='single_estimate'
    plan=invoke('workflow','plan','--task-config',task,'--estimates-input',data,'--start-at','pooling',
                '--output-dir',tmp/'legacy-flow','--json',PI_FIXTURE_AVAILABLE='0')
    assert plan.returncode==0,plan.stderr+plan.stdout
    assert json.loads(plan.stdout)['config']['synthesis_settings']['backend']=='deterministic'
    assert not (tmp/'calls.jsonl').exists()


def test_primary_source_role_and_execution_budget_reach_actual_cli(native):
    invoke,data,method,_,tmp=native
    primary=tmp/'study.md';primary.write_text('Primary study observations and interval evidence.')
    result=invoke('synthesis','agent','--input',data,'--research-question','Question',
        '--method-source',method,'--primary-source',primary,'--max-executions','6',
        '--output',tmp/'roles','--json')
    assert result.returncode==0,result.stdout+result.stderr
    call=json.loads((tmp/'calls.jsonl').read_text())
    assert call['source_roles']=={str(method):'original_methods',str(primary):'primary_study'}
    assert call['settings']['max_executions']==6
    planned=invoke('synthesis','agent','--input',data,'--research-question','Question',
        '--method-source',method,'--primary-source',primary,'--max-executions','6',
        '--output',tmp/'dry-roles','--dry-run','--json')
    payload=json.loads(planned.stdout)
    assert planned.returncode==0 and payload['source_roles']==call['source_roles']
    assert payload['fingerprint']['source_roles']==call['source_roles']
    assert not (tmp/'dry-roles').exists()


@pytest.mark.parametrize('flags',[
    ('--primary-source','missing-primary.pdf'), ('--max-executions','9'), ('--max-executions','0'),
])
def test_primary_missing_path_and_invalid_execution_budget_json(native,flags):
    invoke,data,_,_,tmp=native
    result=invoke('synthesis','agent','--input',data,'--research-question','Question',
        '--output',tmp/'bad-role','--json',*flags)
    assert result.returncode==2 and json.loads(result.stdout)['status']=='failed'
    assert not (tmp/'bad-role').exists() and not (tmp/'calls.jsonl').exists()


def test_same_source_cannot_claim_both_methods_and_primary(native):
    invoke,data,method,_,tmp=native
    result=invoke('synthesis','agent','--input',data,'--research-question','Question',
        '--method-source',method,'--primary-source',method,'--output',tmp/'roles','--json')
    assert result.returncode!=0 and json.loads(result.stdout)['status']=='failed'
    assert not (tmp/'calls.jsonl').exists()


def test_workflow_execution_budget_override_is_fingerprinted(native):
    invoke,data,_,task,tmp=native
    common=('workflow','run','--task-config',task,'--start-at','pooling','--estimates-input',data,
        '--output-dir',tmp/'workflow-budget','--dry-run','--json')
    first=invoke(*common,'--synthesis-max-executions','3')
    second=invoke(*common,'--synthesis-max-executions','6')
    assert first.returncode==second.returncode==0,first.stdout+second.stdout
    a,b=json.loads(first.stdout),json.loads(second.stdout)
    assert a['config']['synthesis_settings']['max_executions']==3
    assert b['config']['synthesis_settings']['max_executions']==6
    assert a['config_sha256']!=b['config_sha256'] and not (tmp/'workflow-budget').exists()


def test_standalone_shared_review_context_roundtrip_and_dryrun_binding(native):
    invoke, data, method, _, tmp = native
    context=tmp/'context.yaml'; context.write_text(yaml.safe_dump({'population':'adults','group':None}))
    common=('synthesis','agent','--input',data,'--research-question','Same question',
            '--review-context',context,'--method-source',method,'--output',tmp/'context-run','--json')
    plan=invoke(*common,'--dry-run')
    assert plan.returncode==0,plan.stdout+plan.stderr
    first=json.loads(plan.stdout)
    assert first['fingerprint']['review_context']=={'population':'adults','group':None}
    assert not (tmp/'context-run').exists() and not (tmp/'calls.jsonl').exists()
    context.write_text(yaml.safe_dump({'population':'children','group':None}))
    second=invoke(*common,'--dry-run')
    assert json.loads(second.stdout)['plan_sha256']!=first['plan_sha256']
    actual=invoke(*common)
    assert actual.returncode==0,actual.stdout+actual.stderr
    assert json.loads((tmp/'calls.jsonl').read_text())['review_context']=={'population':'children','group':None}
    # Invalid shapes fail before Pi invocation or output writes.
    context.write_text('- invalid-shape\n')
    rejected=invoke(*common)
    assert rejected.returncode==1 and 'must contain a JSON/YAML object' in rejected.stdout
    assert len((tmp/'calls.jsonl').read_text().splitlines())==1
