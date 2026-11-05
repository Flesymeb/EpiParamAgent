"""Software oracle and adversarial execution checks; no model or human gold."""
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

import pytest

from metaagent.synthesis.execution import execute_code, file_sha
from metaagent.synthesis.pi_agent import _prepare_workspace, pi_synthesis_fingerprint, run_pi_synthesis
from metaagent.synthesis.pi_tools import dispatch, validate_execution_result


ROWS=[{'estimate_id':'a','point_estimate':4,'se':1,'unit':'days','cohort_id':'cohort-a','estimate_measure':'mean','uncertainty_type':'SE'},
      {'estimate_id':'b','point_estimate':6,'se':1,'unit':'days','cohort_id':'cohort-b','estimate_measure':'mean','uncertainty_type':'SE'}]


def setup_workspace(tmp_path,rows=None,settings=None):
    method=tmp_path/'methods.md';method.write_text('Independent cohorts: normal inverse-variance fixed-effect mean, 95% confidence interval.')
    return _prepare_workspace(records=ROWS if rows is None else rows,research_question='What is the mean?',method_sources=[method],output_dir=tmp_path/'out',settings=settings)


def save(w,*,ids=None,status='reproduction',**extra):
    plan={'research_question':'What is the mean?','method':{'name':'fixed','unit':'days','interval_method':'normal','ci_level':0.95},
          'selection':{'selected_input_ids':ids or ['a','b'],'rationale':'One mean per independent cohort.'},
          'source_mapping':[{'source_id':'method_001','quote':'normal inverse-variance fixed-effect mean'}],
          'transformations':[],'assumptions':[],'sensitivity':[],'reproduction_status':status,**extra}
    return dispatch(w,'save_plan',{'plan':plan})


CODE="""
import json, math
import numpy as np, pandas as pd, scipy.stats as st, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
rows=[json.loads(x) for x in open('/inputs/table.jsonl')]
plan=json.load(open('/analysis_plan.json'))
rows=[r for r in rows if r['input_id'] in plan['selection']['selected_input_ids']]
y=np.array([r['point_estimate'] for r in rows],dtype=float)
w=np.array([1/r['se']**2 for r in rows]); mu=float(np.sum(y*w)/sum(w)); radius=float(st.norm.ppf(.975)/math.sqrt(sum(w)))
result={'status':'complete','result':{'point_estimate':mu,'ci_lower':mu-radius,'ci_upper':mu+radius,'ci_level':.95,'interval_type':'CI','unit':'days','method':'fixed'},'contributions':[{'input_id':r['input_id'],'value_used':r['point_estimate'],'se_used':r['se'],'weight':float(v/sum(w))} for r,v in zip(rows,w)],'transformations':[],'sensitivity':[]}
json.dump(result,open('/work/result.json','w'),allow_nan=False)
plt.errorbar(y,range(len(y)),xerr=[r['se']*st.norm.ppf(.975) for r in rows],fmt='o');plt.xlabel('days');plt.savefig('/work/forest.png');plt.close()
"""


def verified(w,code=CODE):
    dispatch(w,'write_code',{'code':code})
    run=dispatch(w,'run_code',{})
    assert run['status']=='verified',run
    return run


def test_known_oracle_actual_sandbox_repeated_and_published(tmp_path):
    w=setup_workspace(tmp_path); original=file_sha(w/'inputs/table.jsonl');save(w)
    receipt=verified(w);final=dispatch(w,'finalize',{'execution_id':receipt['execution_id']})
    assert final['result']['point_estimate']==5
    assert final['result']['ci_lower']==pytest.approx(3.614096175650322)
    assert final['result']['ci_upper']==pytest.approx(6.385903824349678)
    output=json.loads(Path(final['artifacts']['synthesis_result']).read_text())
    assert output['counts']=={'input':2,'selected':2,'excluded':0,'selected_needs_review':0,'independent_studies':None}
    assert [c['source_raw']['estimate_id'] for c in output['contributions']]==['a','b']
    proof=json.loads(Path(final['artifacts']['execution_receipt']).read_text())
    assert proof['sandbox']=='bubblewrap' and proof['repeat_execution_id']
    assert file_sha(w/'inputs/table.jsonl')==original
    assert Path(final['artifacts']['forest_png']).read_bytes().startswith(b'\x89PNG')


def test_fingerprint_is_read_only_pending_and_binds_source(tmp_path):
    method=tmp_path/'methods.txt';method.write_text('Method.')
    before=set(tmp_path.rglob('*'))
    value=pi_synthesis_fingerprint(records=[],research_question='Q?',method_sources=[method],settings={'backend':'pi','pi_command':None})
    assert value['input_pending'] and value['row_count']==0 and set(tmp_path.rglob('*'))==before
    method.write_text('Changed method.')
    assert pi_synthesis_fingerprint(records=[],research_question='Q?',method_sources=[method])['fingerprint']!=value['fingerprint']


def test_profile_query_bounded_readonly_and_worker_real_cli(tmp_path):
    w=setup_workspace(tmp_path)
    assert dispatch(w,'query',{'sql':'SELECT count(*) AS n FROM estimates'})['rows']==[{'n':2}]
    assert dispatch(w,'query',{'sql':'SELECT input_id FROM estimates ORDER BY input_id','limit':1,'offset':1})['rows']==[{'input_id':'b'}]
    for sql in ['DELETE FROM estimates','SELECT randomblob(1000000000)','SELECT * FROM readfile(\'/etc/passwd\')','ATTACH DATABASE \'/tmp/evil\' AS evil']:
        with pytest.raises(Exception):dispatch(w,'query',{'sql':sql})
    import os
    env={**os.environ,'METAAGENT_SYNTHESIS_WORKSPACE':str(w)}
    done=subprocess.run([sys.executable,'-m','metaagent.synthesis.pi_tools'],input=json.dumps({'action':'profile','payload':{}}),text=True,capture_output=True,env=env,check=True)
    result=json.loads(done.stdout)
    assert result['ok'] and result['result']['row_count']==2 and 'save_plan' in result['result']['tool_schema']


@pytest.mark.parametrize('attack',[
    "open('/home/yanhaoyang/.env').read()",
    "open('/inputs/table.jsonl','w').write('tamper')",
    "import socket; socket.create_connection(('1.1.1.1',443),timeout=.2)",
    "import os; os.symlink('/inputs/table.jsonl','/work/escape')",
    "print('x'*300000)",
    "open('/work/huge','wb').write(b'x'*2000000)",
    "while True: pass",
    "import os; os.mkdir('/work/deep'); [os.mkdir('/work/deep/d'+str(i)) for i in range(500)]",
])
def test_malicious_code_is_failed_or_rejected_without_input_mutation(tmp_path,attack):
    w=setup_workspace(tmp_path,settings={'exec_timeout_s':1,'max_log_bytes':10000,'max_output_bytes':1000000,'max_output_files':8})
    save(w);before=file_sha(w/'inputs/table.jsonl')
    path=w/'code/analysis.py';path.write_text(attack)
    result=execute_code(w,path,json.loads((w/'run_settings.json').read_text()))
    assert result['status']=='failed',result
    assert file_sha(w/'inputs/table.jsonl')==before
    assert result['walltime_s']<5


def test_secret_environment_and_host_canary_are_not_visible(tmp_path,monkeypatch):
    monkeypatch.setenv('SYNTHESIS_API_KEY','fake-local-private-canary')
    canary=tmp_path/'private.txt';canary.write_text('unavailable')
    w=setup_workspace(tmp_path);save(w)
    code=w/'code/analysis.py';code.write_text(f"import os,pathlib\nassert os.getenv('SYNTHESIS_API_KEY') is None\nassert not pathlib.Path({str(canary)!r}).exists()\nprint('isolated')\n")
    result=execute_code(w,code,{})
    assert result['status']=='complete' and result['stdout_tail'].strip()=='isolated'


def test_rejects_fabricated_contributions_wrong_ci_transform_and_result_tamper(tmp_path):
    w=setup_workspace(tmp_path);save(w);receipt=verified(w)
    proof=json.loads((w/'receipts'/f"{receipt['execution_id']}.json").read_text());result_path=Path(proof['output_directory'])/'result.json';value=json.loads(result_path.read_text())
    for change in ('id','point','ci','nan','unit','transform'):
        copy=json.loads(json.dumps(value))
        if change=='id':copy['contributions'][0]['input_id']='invented'
        if change=='point':copy['contributions'][0]['value_used']=999
        if change=='ci':copy['result']['ci_upper']=99
        if change=='nan':copy['result']['point_estimate']=float('nan')
        if change=='unit':copy['result']['unit']='hours'
        if change=='transform':copy['transformations']=[{'input_id':'a','field':'point_estimate','before':4,'after':5,'expression':'point_estimate/24','reason':'unit'}]
        with pytest.raises(ValueError):validate_execution_result(w,copy)
    result_path.write_text('{}')
    with pytest.raises(ValueError,match='changed'):dispatch(w,'finalize',{'execution_id':receipt['execution_id']})


def test_r_unavailable_and_bounded_execution_loop(tmp_path):
    w=setup_workspace(tmp_path,settings={'max_executions':1});save(w)
    with patch('metaagent.synthesis.execution.shutil.which',side_effect=lambda name:None if name=='Rscript' else '/usr/bin/bwrap'):
        result=execute_code(w,w/'code/analysis.R',{},language='r')
        assert result['recoverable'] and 'unavailable' in result['error']
    verified(w)
    with pytest.raises(ValueError,match='budget'):dispatch(w,'run_code',{})


def test_no_silent_mixing_or_duplicate_cohort_independence(tmp_path):
    rows=json.loads(json.dumps(ROWS));rows[1]['cohort_id']='cohort-a'
    w=setup_workspace(tmp_path,rows)
    with pytest.raises(ValueError,match='dependence'):save(w)
    rows[1]['cohort_id']='cohort-b';rows[1]['uncertainty_type']='CrI';w=setup_workspace(tmp_path,rows)
    with pytest.raises(ValueError,match='Heterogeneous'):save(w)


def test_agent_ignores_assistant_numbers_accepts_only_real_execution(tmp_path):
    source=tmp_path/'methods.md';source.write_text('normal inverse-variance fixed-effect mean')
    def fake(workspace,prompt,settings,runtime_overrides=None,completion_guard=False):
        assert completion_guard is True
        save(workspace);receipt=verified(workspace);dispatch(workspace,'finalize',{'execution_id':receipt['execution_id']})
        return {'status':'complete','assistant_text':'Pooled result is 999999','usage':{}}
    with patch('metaagent.synthesis.pi_runtime.run_pi_session',fake):
        result=run_pi_synthesis(records=ROWS,research_question='What is the mean?',method_sources=[source],output_dir=tmp_path/'run')
    assert result['status']=='complete' and result['result']['point_estimate']==5
    assert '999999' not in Path(result['artifacts']['synthesis_report']).read_text()
    with patch('metaagent.synthesis.pi_runtime.run_pi_session',return_value={'status':'complete','assistant_text':'5'}):
        result=run_pi_synthesis(records=ROWS,research_question='Q?',output_dir=tmp_path/'noexecution')
    assert result['status']=='failed' and result['result'] is None


def test_secrets_and_gold_rejected_before_worker_or_model(tmp_path):
    path=tmp_path/'oracle_expected.json';path.write_text('{}')
    with pytest.raises(ValueError,match='Gold'):pi_synthesis_fingerprint(input_path=path,research_question='Q?')
    with pytest.raises(ValueError,match='Credential'):_prepare_workspace(records=[{'note':'sk-fakeoffline12345678'}],research_question='Q?',output_dir=tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_ci_unit_conversion_ledger_is_numerically_grounded(tmp_path):
    from statistics import NormalDist
    rows=[{'estimate_id':'hours','point_estimate':72,'uncertainty_low':48,'uncertainty_high':96,'uncertainty_type':'CI','uncertainty_level':'95%','unit':'hours','cohort_id':'a','estimate_measure':'mean'}]
    w=setup_workspace(tmp_path,rows);save(w,ids=['hours'],transformations=[{'reason':'hours to days and normal CI to SE'}])
    se=2/(2*NormalDist().inv_cdf(.975))
    value={'status':'complete','result':{'point_estimate':3,'ci_lower':2,'ci_upper':4,'ci_level':.95,'interval_type':'CI','unit':'days','method':'fixed'},'contributions':[{'input_id':'hours','value_used':3,'se_used':se}],
           'transformations':[{'input_id':'hours','field':'point_estimate','before':72,'after':3,'expression':'point_estimate/24','reason':'hours to days'},
                             {'input_id':'hours','field':'se','before':None,'after':se,'expression':'(uncertainty_high-uncertainty_low)/24/(2*1.959963984540054)','reason':'explicit normal 95% CI'}],'sensitivity':[]}
    assert validate_execution_result(w,value)['result']['point_estimate']==3
    value['transformations'].pop()
    with pytest.raises(ValueError,match='SE'):validate_execution_result(w,value)


def test_input_csv_preserves_identity_and_source_values(tmp_path):
    csv=tmp_path/'estimates.csv';csv.write_text('estimate_id,cohort_id,point_estimate,se,unit\n001,0002,4,1,days\n')
    w=_prepare_workspace(input_path=csv,research_question='Q?',output_dir=tmp_path/'out')
    row=json.loads((w/'inputs/table.jsonl').read_text())
    assert row['estimate_id']=='001' and row['cohort_id']=='0002' and row['point_estimate']=='4'
    assert file_sha(csv)==file_sha(w/'inputs/original_input.csv')


def test_docx_pdf_html_staged_text_and_original_hashes(tmp_path):
    import fitz
    import zipfile
    docx=tmp_path/'methods.docx'
    with zipfile.ZipFile(docx,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Independent cohorts.</w:t></w:r></w:p></w:document>')
    pdf=tmp_path/'methods.pdf'
    with fitz.open() as document:
        page=document.new_page();page.insert_text((50,50),'A documented statistical method using independent cohort mean estimates.');document.save(pdf)
    html=tmp_path/'methods.html';html.write_text('<p>Fixed effects.</p>')
    w=_prepare_workspace(records=ROWS,research_question='Q?',method_sources=[docx,pdf,html],output_dir=tmp_path/'out')
    sources=dispatch(w,'profile',{})['sources']
    assert [s['original_sha256'] for s in sources]==[file_sha(x) for x in [docx,pdf,html]]
    assert 'Independent cohorts.' in dispatch(w,'evidence',{'source_id':'method_001'})['text']
    assert '[Page 1]' in dispatch(w,'evidence',{'source_id':'method_002'})['text']
    assert 'Fixed effects.' in dispatch(w,'evidence',{'source_id':'method_003'})['text']


def test_exploratory_plan_needs_assumptions_and_actual_sensitivity(tmp_path):
    w=setup_workspace(tmp_path)
    with pytest.raises(ValueError,match='assumptions'):save(w,status='exploratory')
    save(w,status='exploratory',assumptions=['The fixed model is an exploratory working assumption.'],sensitivity=['Leave one out.'])
    dispatch(w,'write_code',{'code':CODE})
    output=dispatch(w,'run_code',{})
    assert output['status']=='failed' and 'sensitivity' in output['validation_error']
    no_silent=CODE.replace("'sensitivity':[]", "'sensitivity':[{'name':'leave-one-out','selected_input_ids':['a'],'result':{'point_estimate':4}}]")
    final=verified(w,no_silent)
    assert dispatch(w,'finalize',{'execution_id':final['execution_id']})['status']=='complete'


def test_modified_plan_and_nondeterministic_code_never_finalize(tmp_path):
    w=setup_workspace(tmp_path);save(w)
    nondeterministic=CODE.replace("'sensitivity':[]", "'sensitivity':[{'name':'unseeded','result':float(np.random.random())}]")
    dispatch(w,'write_code',{'code':nondeterministic});result=dispatch(w,'run_code',{})
    assert result['status']=='failed' and 'inconsistent' in result['validation_error']
    receipt=verified(w)
    plan=json.loads((w/'analysis_plan.json').read_text());plan['method']['unit']='hours';(w/'analysis_plan.json').write_text(json.dumps(plan))
    with pytest.raises(ValueError,match='changed'):dispatch(w,'finalize',{'execution_id':receipt['execution_id']})


def test_review_flags_and_tool_budget_remain_visible(tmp_path):
    rows=json.loads(json.dumps(ROWS));rows[0]['review_flags']=['uncertain unit evidence']
    w=setup_workspace(tmp_path,rows);save(w);receipt=verified(w)
    output=dispatch(w,'finalize',{'execution_id':receipt['execution_id']})
    assert output['status']=='partial'
    small=setup_workspace(tmp_path,settings={'max_tool_calls':1})
    dispatch(small,'profile',{})
    with pytest.raises(ValueError,match='budget'):dispatch(small,'profile',{})


def test_normal_references_directory_and_filename_are_allowed(tmp_path):
    sources=tmp_path/'references';sources.mkdir();paper=sources/'reference_methods.md';paper.write_text('Original paper methods are a legitimate source.')
    w=_prepare_workspace(records=ROWS,research_question='Q?',method_sources=[paper],output_dir=tmp_path/'out')
    assert dispatch(w,'profile',{})['sources'][0]['original_sha256']==file_sha(paper)


def test_rejected_plan_payload_preserves_committed_plan_and_selection(tmp_path):
    w=setup_workspace(tmp_path);save(w)
    files=['analysis_plan.json','analysis_selection.jsonl','plan_commit.json'];before={p:(w/p).read_bytes() for p in files}
    plan=json.loads((w/'analysis_plan.json').read_text());plan['selection']['reasons']={'invented':'Bad ID'};plan['method']['name']='new-method'
    with pytest.raises(ValueError,match='reasons'):dispatch(w,'save_plan',{'plan':plan})
    assert before=={p:(w/p).read_bytes() for p in files}


def test_output_claim_reuse_stale_rejection_and_real_session_continuation(tmp_path):
    source=tmp_path/'methods.md';source.write_text('normal inverse-variance fixed-effect mean')
    calls=[]
    def fake(workspace,prompt,settings,runtime_overrides=None,completion_guard=False):
        calls.append((workspace,dict(settings)))
        save(workspace);receipt=verified(workspace);dispatch(workspace,'finalize',{'execution_id':receipt['execution_id']})
        return {'status':'complete'}
    kwargs=dict(records=ROWS,research_question='What is the mean?',method_sources=[source],output_dir=tmp_path/'run')
    with patch('metaagent.synthesis.pi_runtime.run_pi_session',fake):
        first=run_pi_synthesis(**kwargs);assert first['status']=='complete'
        result_bytes=(tmp_path/'run/synthesis_result.json').read_bytes()
        assert run_pi_synthesis(**kwargs)['reused'] is True and len(calls)==1
        changed=run_pi_synthesis(**{**kwargs,'research_question':'Another question?'})
        assert changed['status']=='failed' and 'claimed' in changed['error']['message'] and len(calls)==1
        assert result_bytes==(tmp_path/'run/synthesis_result.json').read_bytes()
        invalid=run_pi_synthesis(**{**kwargs,'records':[{'note':'sk-fakeoffline12345678'}]})
        assert invalid['status']=='failed' and result_bytes==(tmp_path/'run/synthesis_result.json').read_bytes()
    attempts=[]
    def interrupted(workspace,prompt,settings,runtime_overrides=None,completion_guard=False):
        attempts.append((workspace,dict(settings)))
        directory=workspace/'pi/sessions';directory.mkdir(parents=True,exist_ok=True);session=directory/'local.jsonl';session.touch()
        return {'status':'failed','session_path':str(session)}
    other={**kwargs,'output_dir':tmp_path/'interrupted'}
    with patch('metaagent.synthesis.pi_runtime.run_pi_session',interrupted):
        assert run_pi_synthesis(**other)['status']=='failed'
        assert run_pi_synthesis(**other)['status']=='failed' and len(attempts)==1
        assert run_pi_synthesis(**other,resume=True)['status']=='failed' and len(attempts)==2
    assert attempts[0][0]==attempts[1][0]
    assert attempts[1][1]['session_path'].endswith('/pi/sessions/local.jsonl')


def test_source_mutation_prevents_reuse_without_overwriting_success(tmp_path):
    w=setup_workspace(tmp_path);save(w);receipt=verified(w)
    source=json.loads((w/'workspace.json').read_text())['sources'][0]
    (w/source['text_path']).write_text('changed source')
    with pytest.raises(ValueError,match='source changed'):dispatch(w,'finalize',{'execution_id':receipt['execution_id']})


def test_generated_process_creation_is_kernel_denied(tmp_path):
    w=setup_workspace(tmp_path);save(w)
    path=w/'code/analysis.py';path.write_text("import os,errno\ntry: os.fork()\nexcept OSError as e:\n assert e.errno==errno.EPERM\n print('fork denied')\nelse: raise AssertionError('fork permitted')\n")
    result=execute_code(w,path,{})
    assert result['status']=='complete' and 'fork denied' in result['stdout_tail']
    assert result['limits']['generated_process_creation']=='seccomp_denied'


def test_primary_source_roles_are_staged_and_fingerprint_bound(tmp_path):
    paper=tmp_path/'primary.md';paper.write_text('Primary study evidence.')
    kwargs=dict(records=ROWS,research_question='Q?',method_sources=[paper],source_roles={paper:'primary_study'})
    w=_prepare_workspace(**kwargs,output_dir=tmp_path/'out')
    assert dispatch(w,'profile',{})['sources'][0]['role']=='primary_study'
    primary=pi_synthesis_fingerprint(**kwargs)
    methods=pi_synthesis_fingerprint(**{**kwargs,'source_roles':{paper:'original_methods'}})
    assert primary['fingerprint']!=methods['fingerprint']


@pytest.mark.parametrize('value',[False,None,0,0.0,'False','false','FALSE','0','no','No','', '  ', [],{},'[]','{}'])
def test_review_flags_false_values_are_not_pending(value):
    from metaagent.synthesis.pi_tools import _review_flag
    assert _review_flag(value) is False


@pytest.mark.parametrize('value',[True,1,'True','true','1','yes','YES','ambiguous',2,['missing_evidence'],'["missing_evidence"]'])
def test_review_flags_true_and_unknown_nonempty_remain_pending(value):
    from metaagent.synthesis.pi_tools import _review_flag
    assert _review_flag(value) is True


def test_csv_false_flags_real_finalization_preserves_numeric_and_input(tmp_path):
    csv=tmp_path/'coding.csv';csv.write_text('estimate_id,cohort_id,point_estimate,se,unit,estimate_measure,uncertainty_type,needs_review,review_flags\na,cohort-a,4,1,days,mean,SE,False,[]\nb,cohort-b,6,1,days,mean,SE,false,[]\n')
    method=tmp_path/'methods.md';method.write_text('normal inverse-variance fixed-effect mean')
    original=csv.read_bytes();w=_prepare_workspace(input_path=csv,research_question='What is the mean?',method_sources=[method],output_dir=tmp_path/'out');save(w)
    code=CODE.replace("1/r['se']**2","1/float(r['se'])**2").replace("r['se']*st.norm", "float(r['se'])*st.norm")
    verified_receipt=verified(w,code);result=dispatch(w,'finalize',{'execution_id':verified_receipt['execution_id']})
    artifact=json.loads(Path(result['artifacts']['synthesis_result']).read_text())
    assert result['status']=='complete' and artifact['counts']['selected_needs_review']==0
    assert artifact['result']['point_estimate']==5 and artifact['result']['ci_lower']==pytest.approx(3.614096175650322)
    assert csv.read_bytes()==original


def test_unknown_nonempty_review_string_stays_partial_with_same_numeric(tmp_path):
    rows=json.loads(json.dumps(ROWS));rows[0]['needs_review']='unresolved-from-source';rows[1]['needs_review']='no'
    w=setup_workspace(tmp_path,rows);save(w);receipt=verified(w);result=dispatch(w,'finalize',{'execution_id':receipt['execution_id']})
    value=json.loads(Path(result['artifacts']['synthesis_result']).read_text())
    assert result['status']=='partial' and value['counts']['selected_needs_review']==1
    assert value['result']['point_estimate']==5


def test_dependence_diagnostic_and_tool_schema_give_exact_nested_path(tmp_path):
    from metaagent.synthesis.pi_tools import TOOL_SCHEMA
    rows=json.loads(json.dumps(ROWS));rows[1]['cohort_id']=rows[0]['cohort_id'];w=setup_workspace(tmp_path,rows)
    with pytest.raises(ValueError,match=r'selection\.dependence=\{strategy: .*justification:'):
        save(w)
    example=TOOL_SCHEMA['save_plan']['plan']
    assert set(example['selection']['dependence'])=={'strategy','justification'}
    assert {'mixed_statistics','mixed_uncertainty','mixed_parameters','mixed_groups','mixed_timepoints','mixed_endpoints'} <= set(example['compatibility'])
    assert not (w/'analysis_plan.json').exists()


def test_failed_runtime_preserves_actionable_429_and_redacts_diagnostics(tmp_path):
    secret='sk-offlineDiagnosticFixture123456'
    runtime={'status':'failed','pi_version':'1.3.0','error':{'status':429,'message':'cluster_rpm_rate_limit_exceeded retry_after16 credential='+secret,'retry_after':16},'abort_reason':'provider failed '+secret,'usage':{'coverage':'partial','total_tokens':None},'budget':{}}
    with patch('metaagent.synthesis.pi_runtime.run_pi_session',return_value=runtime):
        result=run_pi_synthesis(records=ROWS,research_question='Q?',output_dir=tmp_path/'run',runtime_overrides={'llm_api_key':secret})
    assert result['status']=='failed' and result['result'] is None
    assert result['pi_runtime']['error']['status']==429 and result['pi_runtime']['error']['retry_after']==16
    assert 'cluster_rpm_rate_limit_exceeded' in result['reason'] and 'retry_after16' in result['reason']
    assert result['pi_runtime']['abort_reason'].startswith('provider failed ')
    assert secret not in json.dumps(result)
    for artifact in result['artifacts'].values():
        assert secret not in Path(artifact).read_text()


def _ci_se_error_case(tmp_path):
    from statistics import NormalDist
    rows=[dict(estimate_id='a',cohort_id='a',point_estimate='2',uncertainty_low='1',uncertainty_high='3',uncertainty_type='CI',uncertainty_level='95%',estimate_measure='mean',unit='days'),
          dict(estimate_id='b',cohort_id='b',point_estimate='72',uncertainty_low='48',uncertainty_high='96',uncertainty_type='CI',uncertainty_level='95%',estimate_measure='mean',unit='hours')]
    w=setup_workspace(tmp_path,rows);save(w,transformations=[{'reason':'Explicit normal95CI-to-SE and common days scale'}])
    se=1/NormalDist().inv_cdf(.975);radius=1/(2**.5)
    value={'status':'complete','result':{'point_estimate':2.5,'ci_lower':2.5-radius,'ci_upper':2.5+radius,'ci_level':.95,'interval_type':'CI','unit':'days','method':'fixed'},
           'contributions':[{'input_id':'a','value_used':2,'se_used':se,'weight':.5},{'input_id':'b','value_used':3,'se_used':se,'weight':.5}],
           'transformations':[{'input_id':'b','field':'point_estimate','before':'72','after':3,'expression':'point_estimate/24','reason':'Hours to days'},
               {'input_id':'b','field':'se','before':None,'after':se,'expression':'(uncertainty_high-uncertainty_low)/(2*1.959963984540054)/24','reason':'Normal CI to SE in hours then days'}], 'sensitivity':[]}
    a={'input_id':'a','field':'se','before':None,'after':se,'expression':'(uncertainty_high-uncertainty_low)/(2*1.959963984540054)','reason':'Days CI still needs explicit SE derivation'}
    return w,value,a


def test_missing_same_unit_ci_se_ledger_identifies_exact_record(tmp_path):
    w,value,_=_ci_se_error_case(tmp_path)
    with pytest.raises(ValueError,match='input_id=a: missing se derivation.*source unit already matches'):
        validate_execution_result(w,value)
    assert not (w/'final_result.json').exists()


def test_valid_ci_se_ledgers_for_days_and_hours_keep_numeric_guard(tmp_path):
    w,value,a=_ci_se_error_case(tmp_path);value['transformations'].append(a)
    checked=validate_execution_result(w,value)
    assert checked['independent_verification']['status']=='verified'
    assert checked['result']['point_estimate']==2.5
    assert checked['result']['ci_lower']==pytest.approx(1.7928932188134525)


def test_wrong_ci_se_unit_factor_identifies_record_and_reason(tmp_path):
    w,value,a=_ci_se_error_case(tmp_path);value['transformations'].append(a)
    value['transformations'][1].update(after=a['after']*24,expression='(uncertainty_high-uncertainty_low)/(2*1.959963984540054)')
    value['contributions'][1]['se_used']=a['after']*24
    with pytest.raises(ValueError,match='input_id=b: SE derivation conflicts.*reason=declared SE differs'):
        validate_execution_result(w,value)


@pytest.mark.parametrize('change', ['before','after'])
def test_bad_se_ledger_source_or_expression_error_identifies_record(tmp_path,change):
    w,value,a=_ci_se_error_case(tmp_path)
    if change=='before':a['before']=0
    else:a['after']+=.1
    value['transformations'].append(a)
    with pytest.raises(ValueError,match='input_id=a, field=se: Transformation'):
        validate_execution_result(w,value)


def test_raw_inverse_variance_error_identifies_normalized_weight_contract(tmp_path):
    w,value,a=_ci_se_error_case(tmp_path);value['transformations'].append(a)
    for contribution in value['contributions']:contribution['weight']=1/contribution['se_used']**2
    with pytest.raises(ValueError,match='input_id=a: Independent study-weight.*normalized to sum1.*raw inverse variance'):
        validate_execution_result(w,value)


def test_same_unit_sd_requires_explicit_ledger_without_inventing_n(tmp_path):
    w=setup_workspace(tmp_path,[dict(estimate_id='a',cohort_id='a',point_estimate=4,sd=2,sample_size=100,uncertainty_type='SD',estimate_measure='mean',unit='days')])
    save(w,ids=['a'],transformations=[{'reason':'Reported SD divided by sqrt of reported sample size'}])
    value={'status':'complete','result':{'point_estimate':4,'unit':'days','method':'fixed'},'contributions':[{'input_id':'a','value_used':4,'se_used':.2,'weight':1}],'transformations':[]}
    with pytest.raises(ValueError,match='input_id=a: missing se derivation'):
        validate_execution_result(w,value)
    value['transformations']=[{'input_id':'a','field':'se','before':None,'after':.2,'expression':'sd/sqrt(sample_size)','reason':'Only reported SD and sample size used'}]
    assert validate_execution_result(w,value)['independent_verification']['status']=='verified'
