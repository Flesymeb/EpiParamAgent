"""Offline prompt delivery/contract tests; not measurements of model accuracy."""
import json

import pytest

from metaagent.coding.schema.config_loader import FieldConfig, ProjectConfig
from metaagent.coding.stages import run_stages

OVERALL='The overall serial interval had a mean of 6.4 days.'
SUBGROUP='In children, the mean serial interval was 8.1 days.'
FITTED='Figure caption: blue curves show fitted normal distributions for the overall serial interval.'
APPROXIMATION='The confidence intervals used a normal approximation.'
SOURCE='\n\n'.join([OVERALL,SUBGROUP,FITTED,APPROXIMATION])
SCOPE='Only the overall mean serial interval; exclude subgroup-only results.'


@pytest.fixture
def config():
    return ProjectConfig(name='serial_interval',effect_type='serial_interval',fields=[
        FieldConfig(name='parameter_type',label='Parameter',type='str'),
        FieldConfig(name='estimate_measure',label='Statistic',type='str'),
        FieldConfig(name='point_estimate',label='Value',type='float'),
        FieldConfig(name='unit',label='Unit',type='str'),
        FieldConfig(name='distribution',label='Distribution',type='str'),
    ],notes='Retain all estimates, strata and statistics; analysis selection happens later.')


def row(quote=OVERALL,value=6.4,**kwargs):
    return {'parameter_type':'serial_interval','estimate_measure':'mean','point_estimate':value,'unit':'days',
            '_field_evidence':{name:quote for name in ['parameter_type','estimate_measure','point_estimate','unit']},**kwargs}


def payload(messages):
    body=messages[-1]['content']
    return json.loads(body.split('\nCandidates (guidance only):\n')[0])


def assert_rules(system):
    assert 'Coding scope has priority over generic codebook retention instructions' in system
    assert 'outcome distribution is normal' in system
    assert 'not the sampling distribution of its' in system
    assert 'Do not join noncontiguous passages into one quote' in system


@pytest.mark.parametrize('backend',['llm','langextract'])
@pytest.mark.parametrize('scope',[None,SCOPE])
def test_scope_delivered_to_both_A_backends_and_B_accounts_for_excluded_candidates(config,tmp_path,backend,scope):
    if scope:config.parameters['extraction_scope']=scope
    raw=[row(),row(SUBGROUP,8.1)];seen=[]
    def extract_a(block,candidate_config):
        from metaagent.coding.pipeline.langextract_backend import _instructions
        wire=_instructions(candidate_config);assert_rules(wire)
        assert json.dumps({'prompt_version':'coding_v2','extraction_scope':scope,'scope_is_explicit':bool(scope)},ensure_ascii=False) in wire
        assert candidate_config.prompt.user_preamble==''
        seen.append('stage_a')
        # A may still make a semantic error; B must account for, not silently
        # delete, the source-supported but explicitly excluded candidate.
        return raw
    def invoke(stage,messages):
        seen.append(stage);user=payload(messages);assert_rules(messages[0]['content'])
        assert user['coding_task']=={'prompt_version':'coding_v2','extraction_scope':scope,'scope_is_explicit':bool(scope)}
        if stage=='stage_a':return json.dumps({'records':raw})
        assert 'MUST have action=reject' in messages[0]['content']
        assert 'Only a genuinely unresolved source-to-scope relationship warrants pending' in messages[0]['content']
        candidates=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])
        records=[];dispositions=[]
        for candidate in candidates:
            reject=bool(scope and candidate['point_estimate']==8.1)
            dispositions.append({'candidate_id':candidate['candidate_id'],'action':'reject' if reject else 'keep',
                                 'reason':SUBGROUP+'; excluded subgroup by the declared coding scope' if reject else 'Within supplied coding scope'})
            if not reject:records.append(candidate)
        return json.dumps({'records':records,'dispositions':dispositions})
    rows=run_stages(text=SOURCE,config=config,record_id='software-report',pmid=None,invoke=invoke,
                    extract_a=extract_a if backend=='langextract' else None,output_dir=tmp_path)
    assert seen==['stage_a','stage_b']
    assert len(rows)==(1 if scope else 2)
    ds=[json.loads(s) for s in (tmp_path/'candidate_dispositions.jsonl').read_text().splitlines()]
    assert len(ds)==2 and sum(d['action']=='reject' for d in ds)==(1 if scope else 0)
    assert json.loads((tmp_path/'coverage.json').read_text())['prompt_version']=='coding_v2'


def test_without_A_still_receives_binding_scope_and_without_B_does_not_run_B(config,tmp_path):
    config.parameters['extraction_scope']=SCOPE;calls=[]
    def invoke(stage,messages):
        calls.append(stage);assert payload(messages)['coding_task']['extraction_scope']==SCOPE
        return json.dumps({'records':[row(candidate_id=None)],'dispositions':[]})
    rows=run_stages(text=SOURCE,config=config,record_id='software',pmid=None,invoke=invoke,
                    output_dir=tmp_path/'noA',ablation='without_a',extract_a=lambda *_:pytest.fail('A removed'))
    assert len(rows)==1 and calls==['stage_b']
    def only_A(stage,messages):
        calls.append(stage);assert stage=='stage_a';assert payload(messages)['coding_task']['extraction_scope']==SCOPE
        return json.dumps({'records':[row()]})
    run_stages(text=SOURCE,config=config,record_id='software',pmid=None,invoke=only_A,
               output_dir=tmp_path/'noB',ablation='without_b')
    assert calls==['stage_b','stage_a']


@pytest.mark.parametrize('distribution_quote',[None,'normal',FITTED])
def test_distribution_evidence_guard_is_not_relaxed_or_replaced_with_automatic_null(config,tmp_path,distribution_quote):
    def invoke(stage,messages):
        assert_rules(messages[0]['content'])
        candidate=row(distribution='normal')
        if stage=='stage_a':return json.dumps({'records':[candidate]})
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        if distribution_quote:candidate['_field_evidence']['distribution']=distribution_quote
        return json.dumps({'records':[{**candidate,'candidate_id':cid}],
                           'dispositions':[{'candidate_id':cid,'action':'correct','reason':'Checked source model family and its field quotation'}]})
    rows=run_stages(text=SOURCE,config=config,record_id='software',pmid=None,invoke=invoke,output_dir=tmp_path)
    result=rows[0]
    assert result['distribution']=='normal', 'No code-based clearing of unsupported model assertions'
    if distribution_quote==FITTED:
        assert not result['needs_review'] and result['field_evidence']['distribution'][0]['quote']==FITTED
    else:
        assert result['needs_review']
        expected='missing_or_unlocated_evidence:distribution' if distribution_quote is None else 'ambiguous_evidence_location:distribution'
        assert expected in result['review_flags']
