"""Task-backed E2E exercises real stages with only external transports mocked."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from metaagent.workflow_runner import WorkflowOptions, plan_workflow, run_workflow
from metaagent.workflow_task import resolve_runtime


@pytest.fixture
def task(tmp_path, monkeypatch):
    monkeypatch.setattr('metaagent.config.load_runtime_env', lambda **kw: None)
    for module in ('QUERY', 'SCREENING', 'CODING', 'SYNTHESIS'):
        monkeypatch.setenv(f'{module}_LLM_PROVIDER', 'openai')
        monkeypatch.setenv(f'{module}_LLM_MODEL', module.lower() + '-model')
        monkeypatch.setenv(f'{module}_LLM_API_BASE', 'http://localhost:12345/v1')
        monkeypatch.setenv(f'{module}_LLM_API_KEY', 'synthetic-testing-credential')
    fields = [('parameter_type','str'), ('estimate_measure','str'), ('unit','str'),
              ('point_estimate','float'), ('uncertainty_type','str'), ('uncertainty_level','str'),
              ('uncertainty_low','float'), ('uncertainty_high','float')]
    (tmp_path/'codebook.yaml').write_text(yaml.safe_dump({'project':{'name':'Synthetic','effect_type':'serial_interval'},
        'fields':[{'name':name,'type':kind} for name,kind in fields]}))
    definition = {'version':'1','task_id':'synthetic','disease':'X','topic':'serial_interval',
        'research_question':'What are the intervals in disease X?', 'coding':{'backend':'llm'}, 'codebook':'codebook.yaml',
        'review_protocol':{'version':'v1','criteria':[{'id':'disease','description':'Studies disease X'}], 'logic':'disease'},
        'search':{'europepmc':'synthetic'},
        'analysis_protocol':{'analysis_id':'synthetic-mean','parameter_type':'serial_interval','estimate_measure':'mean',
            'unit':'days','method':'fixed','uncertainty_rules':{'allowed_types':['CI']},
            'independence':{'unit':'record_id','assert_independent_reports':True}}}
    path=tmp_path/'task.yaml';path.write_text(yaml.safe_dump(definition))
    return path


def options(task, **kw):
    return WorkflowOptions(profile='task', dataset_root=task.parent, output_dir=task.parent/'run', task_config=task, **kw)


def test_task_plan_no_benchmark_and_module_runtimes(task):
    plan=plan_workflow(options(task))
    assert plan['profile']=='synthetic'
    runtime=plan['config']['effective_llm_runtime']
    assert runtime['query']['llm_model']=='query-model'
    assert runtime['coding']['llm_model']=='coding-model'
    assert 'synthetic-testing-credential' not in json.dumps(plan)
    assert not (task.parent/'run').exists()
    assert resolve_runtime(options(task), 'screening', require_credentials=True)[0]['llm_model']=='screening-model'


def test_explicit_missing_key_never_falls_back(task):
    data=yaml.safe_load(task.read_text());data['llm']={'coding':{'api_key_env':'METAAGENT_MISSING_TEST_KEY'}}
    task.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError,match='METAAGENT_MISSING_TEST_KEY'):
        resolve_runtime(options(task),'coding',require_credentials=True)


@pytest.mark.parametrize('variant,a_calls,b_calls',[('full',2,2),('without_a',0,2),('without_b',2,0)])
def test_real_offline_e2e_and_resume(task, monkeypatch, variant,a_calls,b_calls):
    import metaagent.screening.engine as screening
    import metaagent.coding.pipeline.extraction as coding
    seen=[]
    def search(source, query, limit):
        rows=[]
        for i in (1,2):
            text=f'Disease X. Mean serial interval was {i+3} days, 95% CI {i+2} to {i+4}.'
            path=task.parent/f'paper{i}.md';path.write_text(text)
            rows.append({'source_id':str(i),'title':f'Disease X study {i}','abstract':text,
                         'fulltext_path':str(path),'fulltext_access':'public'})
        return rows,2,query
    monkeypatch.setattr('metaagent.retrieval.search',search)
    monkeypatch.setattr(screening,'init_llm_model',lambda **kw: SimpleNamespace(bind=lambda **kw: None))
    async def screen_invoke(model,messages,**kw):
        record=json.loads(messages[1]['content'])['records'][0]
        return {'record_id':record['record_id'],'assessments':[{'criterion_id':'disease','status':'met','evidence':'Disease X','reason':'explicit'}]},{}
    monkeypatch.setattr(screening,'invoke_with_retry_async',screen_invoke)
    monkeypatch.setattr(coding,'init_llm',lambda *args:None)
    def coding_invoke(*,messages,stage_name,**kw):
        seen.append(stage_name)
        payload=messages[1]['content'];source='\n'.join(x['text'] for x in json.JSONDecoder().raw_decode(payload)[0]['source_segments'])
        value=4 if '4 days' in source else 5
        row={'parameter_type':'serial_interval','estimate_measure':'mean','unit':'days',
             'point_estimate':value,'uncertainty_type':'CI','uncertainty_level':'95%',
             'uncertainty_low':value-1,'uncertainty_high':value+1}
        row['_field_evidence']={key:source for key in row}
        if stage_name=='stage_a': return json.dumps([row])
        candidates=json.loads(payload.split('Candidates (guidance only):',1)[1])
        row['candidate_id']=candidates[0]['candidate_id'] if candidates else None
        return json.dumps({'records':[row],'dispositions':[{'candidate_id':r['candidate_id'],'action':'keep','reason':'source checked'} for r in candidates]})
    monkeypatch.setattr(coding,'_invoke_model_content',coding_invoke)
    opts=options(task,ablation=variant,limit=10)
    run=run_workflow(opts)
    assert run['status']=='complete'
    result=json.loads(Path(run['artifacts']['synthesis_result']).read_text())
    assert result['status']=='complete'
    assert result['result']['pooled_mean']==pytest.approx(4.5)
    assert seen.count('stage_a')==a_calls
    assert seen.count('stage_b')==b_calls
    before=len(seen)
    resumed=run_workflow(opts)
    assert all(s['reused'] for s in resumed['stage_results'].values())
    assert len(seen)==before

    data=yaml.safe_load(task.read_text())
    data['analysis_protocol']['method']='random'
    task.write_text(yaml.safe_dump(data))
    changed=run_workflow(opts)
    assert all(changed['stage_results'][stage]['reused'] for stage in ('retrieval','screening','fulltext_fetch','fulltext_screening','coding'))
    assert not changed['stage_results']['pooling']['reused']
    assert len(seen)==before

    source=task.parent/'paper1.md'
    source.write_text(source.read_text()+'\n\nSource revision. Disease X.')
    revised=run_workflow(opts)
    assert revised['stage_results']['retrieval']['reused']
    assert revised['stage_results']['screening']['reused']
    assert not revised['stage_results']['fulltext_fetch']['reused']
    assert not revised['stage_results']['coding']['reused']


def test_fulltext_unknown_does_not_become_pooling_eligible(task, monkeypatch):
    from metaagent.workflow_runner import _context, _screen_rows, execute_stage
    import metaagent.screening.engine as engine
    monkeypatch.setattr(engine, 'init_llm_model', lambda **kw: None)
    async def unresolved(rows, *args, **kwargs):
        for row in rows:
            row.update(llm_tier='P', llm_suggest='possible_candidate', protocol_decision={'route':'review'})
    monkeypatch.setattr(engine, 'screen_papers_batch_async', unresolved)
    opts=options(task)
    row={'record_id':'pending', 'Title':'Disease X', 'fulltext':'Incomplete material', 'fulltext_path':'unused.md'}
    _screen_rows([row], opts, _context(opts), fulltext=True)
    assert row['record_status']=='eligibility_pending'
    path=task.parent/'pending.jsonl';path.write_text(json.dumps(row)+'\n')
    result=execute_stage('coding',opts,_context(opts),task.parent/'coding',{'fulltext_predictions':str(path)})
    assert result['unresolved']==1
    assert Path(result['artifacts']['coding_estimates']).read_text()==''


@pytest.mark.parametrize('prompt,changed',[
    ('metaagent/prompts/coding/stage_a.md',{'coding'}),
    ('metaagent/prompts/coding/examples.json',{'coding'}),
    ('metaagent/prompts/synthesis/report.md',{'pooling'}),
    ('metaagent/prompts/screening/protocol_system.md',{'screening','fulltext_screening'}),
])
def test_prompt_revision_only_invalidates_consuming_stages(task,prompt,changed):
    import copy
    from metaagent.workflow_runner import _stage_config_hash,STAGES
    plan=plan_workflow(options(task))
    before={stage:_stage_config_hash(plan,stage) for stage in STAGES}
    revised=copy.deepcopy(plan)
    revised['config']['dependency_hashes'][str(Path(prompt).resolve())]='changed-content-hash'
    assert {stage for stage in STAGES if _stage_config_hash(revised,stage)!=before[stage]}==changed

@pytest.mark.parametrize('relative',[
    'metaagent/prompts/5d/screening_system_title_abstract.md',
    'metaagent/prompts/screening/guides/fatality.md',
    'metaagent/prompts/binary/screening_system_title_abstract.md',
    'metaagent/prompts/peco/screening_system_title_abstract.md',
])
def test_real_prompt_bytes_only_invalidate_screening_stages(task,relative):
    from metaagent.workflow_runner import _stage_config_hash,STAGES
    root=task.parent/'temporary_project_root';path=root/relative
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Original local prompt bytes.')
    before=plan_workflow(options(task,project_root=root))
    path.write_text('Revised local prompt bytes.')
    after=plan_workflow(options(task,project_root=root))
    key=str(path.resolve())
    assert before['config']['dependency_hashes'][key]!=after['config']['dependency_hashes'][key]
    assert {stage for stage in STAGES if _stage_config_hash(before,stage)!=_stage_config_hash(after,stage)}=={'screening','fulltext_screening'}
