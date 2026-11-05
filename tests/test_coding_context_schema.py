"""Common context schema contracts using synthetic sources, no model or gold data."""
from dataclasses import asdict
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from metaagent.coding.schema.config_loader import FieldConfig, ProjectConfig, create_model_from_config, load_config
from metaagent.coding.schema.context_fields import context_field_definitions
from metaagent.coding.schema.prompt_factory import generate_field_descriptions
from metaagent.coding.pipeline.langextract_backend import _instructions, _records
from metaagent.coding.stages import run_stages

ROOT=Path(__file__).resolve().parents[1]
CONTEXT={r['name'] for r in context_field_definitions()}
SOURCE=('The North cohort included 80 people. The adult subgroup model used 40 participants at day 7. '
        'The mean incubation period from exposure to rash onset was 4.2 days. '
        'Maximum likelihood fitted a lognormal interval-censored model, adjusted for age and sex. '
        'This was the prespecified primary analysis.')
VALUES={'parameter_type':'incubation_period','point_estimate':4.2,'unit':'days','cohort_id':'North cohort',
        'stratum':'adult subgroup','group_label':'adult subgroup','analysis_method':'Maximum likelihood',
        'statistical_model':'lognormal interval-censored model','adjustment_status':'adjusted',
        'adjustment_variables':['age','sex'],'cohort_sample_size':'80 people','estimate_sample_size':'40 participants',
        'estimate_sample_size_unit':'participants','timepoint':'day 7','endpoint_definition':'from exposure to rash onset',
        'analysis_role':'primary'}
QUOTES={key:SOURCE for key in VALUES}


def config(**kw):
    return ProjectConfig(name='Synthetic incubation study',effect_type='incubation_period',fields=[
        FieldConfig(name='parameter_type',label='Parameter',type='str'),
        FieldConfig(name='point_estimate',label='Point',type='float'),
        FieldConfig(name='unit',label='Unit',type='str'),
        FieldConfig(name='method',label='Old method',type='str'),
        FieldConfig(name='sample_size',label='Old sample',type='str'),
    ],**kw)


@pytest.mark.parametrize('path',sorted((ROOT/'configs').glob('*/codebooks/*.yaml')))
def test_all_effect_codebooks_have_common_optional_fields_without_yaml_copy(path):
    book=load_config(path);fields={f.name:f for f in book.fields}
    assert CONTEXT<=fields.keys()
    assert len(fields)==len(book.fields)
    assert all(not fields[name].required for name in CONTEXT if name not in {'method'})
    domain=' '.join([book.name,book.disease]).casefold()
    assert ('clade' in fields)==('mpox' in domain or 'monkeypox' in domain)


def test_explicit_field_definitions_win_and_index_and_empty_books_stay_separate():
    declared=FieldConfig(name='cohort_id',label='Custom cohort',type='str',required=True,prompt='Operator defined cohort requirement')
    book=ProjectConfig(name='Custom',fields=[declared,FieldConfig(name='point_estimate',label='p',type='float')])
    assert book.fields[0] is declared and book.fields[0].prompt=='Operator defined cohort requirement'
    assert len([f for f in book.fields if f.name=='cohort_id'])==1
    index=ProjectConfig(name='Mpox structural index',effect_type='index',fields=[FieldConfig(name='index',label='Index',type='str')])
    assert [f.name for f in index.fields]==['index']
    with pytest.raises(ValueError,match='nonempty fields'):
        ProjectConfig.from_dict({'project':{'name':'empty'},'fields':[]})


def test_clade_is_domain_scoped_and_all_optional_context_is_null_without_inference():
    generic=config();model=create_model_from_config(generic)
    row=model.model_validate({'point_estimate':4.2,'method':'source data collection','sample_size':'80 people'}).model_dump()
    assert all(row[name] is None for name in CONTEXT-{'method'})
    assert row['method']=='source data collection' and row['sample_size']=='80 people'
    assert 'clade' not in model.model_fields
    mpox=ProjectConfig(name='Custom source',disease='mpox',fields=[FieldConfig(name='point_estimate',label='p',type='float')])
    assert 'clade' in create_model_from_config(mpox).model_fields


def entity(kind,quote,attrs):
    return SimpleNamespace(extraction_class=kind,extraction_text=quote,attributes=attrs,char_interval=None,alignment_status=None)


def test_real_lx_mapping_accepts_declared_context_and_preserves_strict_unknown_rejection():
    book=config()
    entities=[entity('coding_record',SOURCE,{'_record_id':'candidate-one',**VALUES})]
    entities += [entity('field_evidence',SOURCE,{'_record_id':'candidate-one','fields':list(VALUES)})]
    result=_records(entities,source=SOURCE,config=book,pmid='NR',truncated=False,document_id='synthetic-report')
    assert len(result)==1 and result[0]['analysis_method']=='Maximum likelihood'
    assert result[0]['adjustment_variables']==['age','sex'] and not result[0]['needs_review']
    assert set(VALUES)<={*result[0]}
    bad=copy.deepcopy(entities);bad[0].attributes['undeclared_magic_field']='invented'
    with pytest.raises(ValueError,match='Unknown codebook fields'):
        _records(bad,source=SOURCE,config=book,pmid='NR',truncated=False)
    bad=copy.deepcopy(entities);bad[1].attributes['fields']=['undeclared_magic_field']
    with pytest.raises(ValueError,match='Unknown field_evidence'):
        _records(bad,source=SOURCE,config=book,pmid='NR',truncated=False)


@pytest.mark.parametrize('variant,expected',[('full',['stage_a','stage_b']),('without_a',['stage_b']),('without_b',['stage_a'])])
def test_context_reaches_actual_A_B_stage_envelopes_with_no_missing_optional_penalty(tmp_path,variant,expected):
    book=config();calls=[]
    def invoke(stage,messages):
        calls.append(stage)
        wire='\n'.join(m['content'] for m in messages)
        for name in ['analysis_method','statistical_model','adjustment_variables','estimate_sample_size','endpoint_definition']:
            assert name in wire
        row={**VALUES,'_field_evidence':QUOTES}
        if stage=='stage_a':return json.dumps({'records':[row]})
        candidates=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])
        identifier=candidates[0]['candidate_id'] if candidates else None
        return json.dumps({'records':[{**row,'candidate_id':identifier}],
                           'dispositions':[{'candidate_id':identifier,'action':'keep','reason':'Exact source context'}] if identifier else []})
    rows=run_stages(text=SOURCE,config=book,record_id='synthetic-source',pmid=None,invoke=invoke,output_dir=tmp_path,ablation=variant)
    assert calls==expected and len(rows)==1
    assert not rows[0]['needs_review'] and rows[0]['time_window'] is None and rows[0]['comparator'] is None
    assert rows[0]['analysis_method']==VALUES['analysis_method']
    assert rows[0]['cohort_id']==VALUES['cohort_id']
    assert rows[0]['semantic_review']==('not_run' if variant=='without_b' else 'reviewed')


def test_lx_prompt_has_same_effective_fields_and_missing_evidence_remains_review(tmp_path):
    book=config();wire=_instructions(book)
    assert 'ONLY\nthe codebook field names' in wire
    for key in CONTEXT:assert '"name": "'+key+'"' in wire
    assert 'optional fields' in generate_field_descriptions(book)
    def invoke(stage,messages):
        row={**VALUES,'_field_evidence':{k:v for k,v in QUOTES.items() if k!='analysis_method'}}
        return json.dumps({'records':[row]})
    rows=run_stages(text=SOURCE,config=book,record_id='synthetic-source',pmid=None,invoke=invoke,output_dir=tmp_path,ablation='without_b')
    assert rows[0]['analysis_method']==VALUES['analysis_method']
    assert rows[0]['needs_review'] and 'missing_or_unlocated_evidence:analysis_method' in rows[0]['review_flags']


def test_context_source_fingerprint_invalidates_coding_but_not_PDF_cache_stage():
    from metaagent.workflow_runner import _stage_config_hash
    dependency=str(ROOT/'metaagent/coding/schema/context_fields.py')
    plan={'config':{'codebook':str(ROOT/'configs/mpox/codebooks/incubation_period.yaml'),
                    'effective_llm_runtime':{'coding':{'llm_model':'offline-model'}},'dependency_hashes':{dependency:'before'}}}
    coding_before=_stage_config_hash(plan,'coding');pdf_before=_stage_config_hash(plan,'fulltext_fetch')
    plan['config']['dependency_hashes'][dependency]='after'
    assert _stage_config_hash(plan,'coding')!=coding_before
    assert _stage_config_hash(plan,'fulltext_fetch')==pdf_before


def test_real_lx_context_records_flow_through_full_A_B_without_extra_transport_fields(tmp_path):
    book=config();seen=[]
    def extract_a(block,candidate_config):
        seen.append('lx_A')
        entities=[entity('coding_record',SOURCE,{'_record_id':'context-one',**VALUES}),
                  entity('field_evidence',SOURCE,{'_record_id':'context-one','fields':list(VALUES)})]
        return _records(entities,source=block['text'],config=candidate_config,pmid='NR',truncated=False)
    def invoke(stage,messages):
        seen.append(stage);assert stage=='stage_b'
        candidates=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1]);row=candidates[0]
        return json.dumps({'records':[row],'dispositions':[{'candidate_id':row['candidate_id'],'action':'keep','reason':'Primary source context checked'}]})
    result=run_stages(text=SOURCE,config=book,record_id='synthetic-report',pmid=None,invoke=invoke,extract_a=extract_a,output_dir=tmp_path)
    assert seen==['lx_A','stage_b'] and len(result)==1
    assert result[0]['adjustment_variables']==['age','sex'] and result[0]['endpoint_definition']=='from exposure to rash onset'
    assert not result[0]['needs_review']


def test_distinct_groups_and_models_with_same_numeric_point_remain_distinct(tmp_path):
    text=('In Cohort Alpha, the adult group mean incubation period was 4 days using maximum likelihood. '
          'In Cohort Alpha, the child group mean incubation period was 4 days using Bayesian estimation.')
    values=[{'parameter_type':'incubation_period','point_estimate':4,'unit':'days','cohort_id':'Cohort Alpha',
             'statistic':'mean','group_label':group,'analysis_method':method}
            for group,method in [('adult group','maximum likelihood'),('child group','Bayesian estimation')]]
    def invoke(stage,messages):
        assert stage=='stage_a'
        return json.dumps({'records':[{**row,'_field_evidence':{key:text for key in row}} for row in values]})
    rows=run_stages(text=text,config=config(),record_id='synthetic-report',pmid=None,invoke=invoke,output_dir=tmp_path,ablation='without_b')
    assert len(rows)==2 and len({r['estimate_id'] for r in rows})==2
    assert {r['group_label'] for r in rows}=={'adult group','child group'}
    assert {r['analysis_method'] for r in rows}=={'maximum likelihood','Bayesian estimation'}


def test_context_extension_does_not_mutate_shared_declared_field_list():
    declared=[FieldConfig(name='point_estimate',label='Point',type='float')]
    mpox=ProjectConfig(name='Mpox project',fields=declared)
    covid=ProjectConfig(name='Covid project',fields=declared)
    assert [f.name for f in declared]==['point_estimate']
    assert 'clade' in {f.name for f in mpox.fields}
    assert 'clade' not in {f.name for f in covid.fields}


def test_existing_parameter_kind_distinguishes_Rt_CrI_and_same_cohort_assumption_alternatives(tmp_path):
    for disease in ['covid19','mpox','avian_influenza']:
        book=load_config(ROOT/'configs'/disease/'codebooks/reproduction_number.yaml')
        declared=next(f for f in book.fields if f.name=='parameter_type')
        assert 'R0' in declared.prompt and 'Rt' in declared.prompt
        assert 'reproduction_number_type' not in {f.name for f in book.fields}
    text=('Title: An investigation of R0. The Delta cohort shared one case curve. '
          'Sensitivity analyses using a Bayesian branching model reported dimensionless Rt as 0.8 '
          'with a 95% credible interval of 0.6 to 1.1 under both assumed serial intervals of 2 days and 3 days.')
    book=ProjectConfig(name='Synthetic reproduction number',effect_type='reproduction_number',fields=[
        FieldConfig(name=name,label=name,type=kind) for name,kind in [
            ('parameter_type','str'),('point_estimate','float'),('unit','str'),('uncertainty_type','str'),
            ('uncertainty_level','str'),('uncertainty_low','float'),('uncertainty_high','float'),('generation_interval_assumed','str')]])
    def invoke(stage,messages):
        assert stage=='stage_a'
        assert 'A paper title or a numerical' in messages[0]['content']
        rows=[]
        for assumption in ['2 days','3 days']:
            row={'parameter_type':'Rt','point_estimate':0.8,'unit':'dimensionless','uncertainty_type':'CrI',
                 'uncertainty_level':'95%','uncertainty_low':0.6,'uncertainty_high':1.1,
                 'cohort_id':'Delta cohort','analysis_method':'Bayesian branching model','analysis_role':'Sensitivity analyses',
                 'generation_interval_assumed':assumption}
            rows.append({**row,'_field_evidence':{name:text for name in row}})
        return json.dumps({'records':rows})
    rows=run_stages(text=text,config=book,record_id='synthetic-R',pmid=None,invoke=invoke,output_dir=tmp_path,ablation='without_b')
    assert len(rows)==2 and len({r['estimate_id'] for r in rows})==2
    assert {r['cohort_id'] for r in rows}=={'Delta cohort'}
    assert {r['parameter_type'] for r in rows}=={'Rt'} and {r['uncertainty_type'] for r in rows}=={'CrI'}
    assert {r['generation_interval_assumed'] for r in rows}=={'2 days','3 days'}
