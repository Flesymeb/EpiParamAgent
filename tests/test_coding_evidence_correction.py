"""One bounded evidence patch never rewrites the accepted scientific payload."""
import copy
import hashlib
import json

import pytest

from metaagent.coding.schema.config_loader import FieldConfig, ProjectConfig
from metaagent.coding.stages import run_stages

GOOD='COV-ID-Z serial intervals were fitted with a normal distribution.'
BAD='COVID-Z serial intervals were fitted with a normal distribution.'
VALUE='The overall mean serial interval was 6.4 days.'
SOURCE=GOOD+'\n\n'+VALUE


@pytest.fixture
def config():
    return ProjectConfig(name='serial_interval',effect_type='serial_interval',fields=[
        FieldConfig(name='parameter_type',label='Parameter',type='str'),
        FieldConfig(name='point_estimate',label='Value',type='float'),
        FieldConfig(name='distribution',label='Distribution',type='str')])


def record(*,value=6.4,quote=BAD,point_quote=VALUE,semantic_review=False):
    return {'parameter_type':'serial_interval','point_estimate':value,'distribution':'normal',
            'notes':'Original semantic statement stays unchanged','needs_review':semantic_review,
            '_field_evidence':{'parameter_type':VALUE,'point_estimate':point_quote,'distribution':[quote] if quote else []}}


def exercise(config,tmp_path,patcher=None,*,variant='full',semantic_review=False,pending=False,
             value=6.4,point_quote=VALUE,quote=BAD,schema_failure=False):
    calls=[];requests=[];accepted=[];normal_B=0
    def invoke(stage,messages):
        nonlocal normal_B
        calls.append(stage)
        raw=record(value=value,quote=quote,point_quote=point_quote,semantic_review=semantic_review)
        if stage=='stage_a':return json.dumps({'records':[raw]})
        user=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[0])
        if user.get('operation')=='evidence_only_correction':
            requests.append(copy.deepcopy(user))
            assert user['readonly_payload']==accepted[-1]
            assert 'Return exactly {"evidence_patches": [...]}' in messages[0]['content']
            assert '"dispositions":' not in messages[0]['content']
            assert any(s['text']==SOURCE for s in user['source_segments'])
            response={'evidence_patches':[{'record_index':t['record_index'],'candidate_id':t['candidate_id'],
                                           'field':t['field'],'quotes':[GOOD if t['field']=='distribution' else VALUE]}
                                          for t in user['targets']]}
            if patcher:return patcher(response,user)
            return json.dumps(response)
        normal_B+=1
        candidates=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])
        cid=candidates[0]['candidate_id'] if candidates else None
        raw['candidate_id']=cid
        payload={'records':[raw],'dispositions':[{'candidate_id':cid,'action':'pending' if pending else 'keep','reason':'Original disposition'}] if cid else []}
        if schema_failure and normal_B==1:payload['records'][0].pop('candidate_id')
        else:accepted.append(copy.deepcopy(payload))
        return json.dumps(payload)
    rows=run_stages(text=SOURCE,config=config,record_id='software-report',pmid=None,invoke=invoke,
                    output_dir=tmp_path,ablation=variant)
    return rows,calls,requests,accepted,json.loads((tmp_path/'coverage.json').read_text())


def test_exact_original_OCR_quote_restores_grounding_once_without_changing_values(config,tmp_path):
    rows,calls,requests,accepted,coverage=exercise(config,tmp_path)
    assert calls==['stage_a','stage_b','stage_b'] and len(requests)==1
    row=rows[0];assert not row['needs_review']
    assert row['point_estimate']==6.4 and row['distribution']=='normal'
    assert row['notes']==accepted[0]['records'][0]['notes']
    assert row['candidate_id']==accepted[0]['records'][0]['candidate_id']
    assert row['field_evidence']['distribution'][0]['quote']==GOOD
    audit=coverage['stage_b_evidence_corrections'][0]
    assert audit['status']=='evidence_located' and coverage['stage_b_calls']==2
    assert coverage['stage_b_evidence_calls']==1 and coverage['evidence_correction_version']=='coding_v3'
    messages=[{'role':'system','content':__import__('metaagent.coding.stages',fromlist=['B_EVIDENCE_RULES']).B_EVIDENCE_RULES},
              {'role':'user','content':json.dumps(requests[0],ensure_ascii=False)}]
    assert audit['request_sha256']==hashlib.sha256(json.dumps(messages,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert accepted[0]['records'][0]['_field_evidence']['distribution']==[BAD]


def test_normalized_quote_still_does_not_locate_and_has_no_second_correction(config,tmp_path):
    def patch(response,user):
        response['evidence_patches'][0]['quotes']=[BAD]
        return json.dumps(response)
    rows,calls,requests,_,coverage=exercise(config,tmp_path,patch)
    assert len(calls)==3 and len(requests)==1
    assert rows[0]['needs_review'] and rows[0]['distribution']=='normal'
    assert 'missing_or_unlocated_evidence:distribution' in rows[0]['review_flags']
    assert coverage['stage_b_evidence_corrections'][0]['status']=='unresolved_original_retained'


@pytest.mark.parametrize('mutation',['scientific_value','notes','needs_review','new_records','wrong_id','unknown_target','duplicate','missing_target','empty_quote','invalid_json'])
def test_invalid_patch_batch_is_soft_rejected_without_scientific_changes(config,tmp_path,mutation):
    def patch(response,user):
        p=response['evidence_patches'][0]
        if mutation in {'scientific_value','notes','needs_review'}:p[{'scientific_value':'point_estimate','notes':'notes','needs_review':'needs_review'}[mutation]]=None
        elif mutation=='new_records':response['records']=[]
        elif mutation=='wrong_id':p['candidate_id']='invented-association'
        elif mutation=='unknown_target':p['field']='different_field'
        elif mutation=='duplicate':response['evidence_patches'].append(copy.deepcopy(p))
        elif mutation=='missing_target':response['evidence_patches']=[]
        elif mutation=='empty_quote':p['quotes']=[]
        else:return '{"evidence_patches":['
        return json.dumps(response)
    rows,calls,requests,accepted,coverage=exercise(config,tmp_path,patch)
    assert len(calls)==3 and len(requests)==1
    assert rows[0]['point_estimate']==6.4 and rows[0]['distribution']=='normal' and rows[0]['needs_review']
    assert rows[0]['notes']==accepted[0]['records'][0]['notes']
    assert rows[0]['field_evidence']['distribution']==[]
    assert coverage['status']=='complete'
    assert coverage['stage_b_evidence_corrections'][0]['status']=='failed_original_retained'


def test_wrong_numeric_value_cannot_be_washed_by_an_exact_different_number_quote(config,tmp_path):
    rows,calls,_,_,coverage=exercise(config,tmp_path,value=9.7,point_quote='The overall mean serial interval was 9.7 dayz.')
    assert len(calls)==3 and rows[0]['point_estimate']==9.7 and rows[0]['needs_review']
    # Even the good distribution patch is not half-committed when another
    # target's exact source quote contradicts the locked numeric assertion.
    assert rows[0]['field_evidence']['distribution']==[]
    assert rows[0]['field_evidence']['point_estimate']==[]
    assert coverage['stage_b_evidence_corrections'][0]['status']=='unresolved_original_retained'


@pytest.mark.parametrize('semantic,pending',[(True,False),(False,True)])
def test_original_semantic_review_claim_or_pending_disposition_never_clears(config,tmp_path,semantic,pending):
    rows,_,_,_,coverage=exercise(config,tmp_path,semantic_review=semantic,pending=pending)
    assert rows[0]['field_evidence']['distribution'][0]['quote']==GOOD
    assert rows[0]['needs_review'] and rows[0]['semantic_review']=='pending'
    assert coverage['stage_b_evidence_corrections'][0]['status']=='evidence_located'


def test_evidence_transport_failure_retains_original_pending_instead_of_failing_stage(config,tmp_path):
    def fail(*_):raise RuntimeError('Offline provider unavailable')
    rows,calls,_,_,coverage=exercise(config,tmp_path,fail)
    assert len(calls)==3 and rows[0]['needs_review'] and coverage['status']=='complete'
    assert coverage['stage_b_evidence_corrections'][0]['error_type']=='RuntimeError'


def test_zero_budget_and_removed_B_make_no_evidence_calls_and_B_only_does_not_run_A(config,tmp_path):
    config.parameters['stage_b_evidence_retries']=0
    rows,calls,requests,_,coverage=exercise(config,tmp_path/'zero')
    assert calls==['stage_a','stage_b'] and not requests and rows[0]['needs_review']
    assert coverage['stage_b_evidence_calls']==0
    config.parameters['stage_b_evidence_retries']=1
    _,calls,requests,_,coverage=exercise(config,tmp_path/'noB',variant='without_b')
    assert calls==['stage_a'] and not requests and coverage['stage_b_calls']==0
    rows,calls,requests,_,coverage=exercise(config,tmp_path/'noA',variant='without_a')
    assert calls==['stage_b','stage_b'] and len(requests)==1 and not rows[0]['needs_review']
    assert coverage['stage_a_calls']==0


def test_absent_evidence_quote_is_not_invented_by_correction(config,tmp_path):
    rows,calls,requests,_,coverage=exercise(config,tmp_path,quote=None)
    assert calls==['stage_a','stage_b'] and not requests and rows[0]['needs_review']
    assert coverage['stage_b_evidence_calls']==0


def test_structure_correction_then_evidence_correction_keeps_separate_one_call_budgets(config,tmp_path):
    rows,calls,requests,_,coverage=exercise(config,tmp_path,schema_failure=True)
    assert calls==['stage_a','stage_b','stage_b','stage_b'] and len(requests)==1
    assert not rows[0]['needs_review']
    assert len(coverage['stage_b_contract_corrections'])==1 and coverage['stage_b_evidence_calls']==1


def test_one_structurally_bad_patch_does_not_partially_commit_a_good_sibling(config,tmp_path):
    def patch(response,user):
        assert len(response['evidence_patches'])==2
        response['evidence_patches'][-1]['notes']='Forbidden change'
        return json.dumps(response)
    rows,_,_,_,coverage=exercise(config,tmp_path,patch,point_quote='The overall mean serial interval was 6.4 dayz.')
    assert rows[0]['field_evidence']['distribution']==[] and rows[0]['field_evidence']['point_estimate']==[]
    assert coverage['stage_b_evidence_corrections'][0]['status']=='failed_original_retained'


@pytest.mark.parametrize('budget',[-1,2,True,'1'])
def test_invalid_evidence_budget_fails_before_calls_or_outputs(config,tmp_path,budget):
    config.parameters['stage_b_evidence_retries']=budget
    out=tmp_path/'not-created'
    with pytest.raises(ValueError,match='stage_b_evidence_retries'):
        run_stages(text=SOURCE,config=config,record_id='software',pmid=None,
                   invoke=lambda *_:pytest.fail('Invalid budget must not call models'),output_dir=out)
    assert not out.exists()
