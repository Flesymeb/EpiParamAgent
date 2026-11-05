"""Behavior tests of real stage orchestration with offline model responses."""
import json
import re
from pathlib import Path

import pytest

from metaagent.coding.schema.config_loader import FieldConfig, ProjectConfig
from metaagent.coding.stages import run_stages, source_blocks

SOURCE = 'The basic reproduction number R0 was 0.8.'


@pytest.fixture
def config():
    return ProjectConfig(name='synthetic', fields=[
        FieldConfig(name='pmid', label='PMID', type='str', required=True),
        FieldConfig(name='parameter_type', label='Parameter', type='str', required=True),
        FieldConfig(name='point_estimate', label='Value', type='float'),
    ])


def record(**extra):
    return dict(parameter_type='R0', point_estimate=0.8,
                _field_evidence={'parameter_type':SOURCE, 'point_estimate':SOURCE}, **extra)


@pytest.mark.parametrize('variant,expected', [('full',['stage_a','stage_b']),
    ('without_a',['stage_b']), ('without_b',['stage_a'])])
def test_stage_removal_is_actual_zero_calls(config,tmp_path,variant,expected):
    calls=[]
    def invoke(stage,messages):
        calls.append(stage)
        if stage=='stage_a':
            return json.dumps([record()])
        ids=re.findall(r'"candidate_id": "([^"]+)"',messages[-1]['content'])
        cid=ids[0] if ids else None
        return json.dumps({'records':[record(candidate_id=cid)],'dispositions':
            [{'candidate_id':cid,'action':'keep','reason':'source matches'}] if cid else []})
    rows=run_stages(text=SOURCE,config=config,record_id='report-one',pmid=None,
                    invoke=invoke,output_dir=tmp_path,ablation=variant)
    assert calls==expected
    assert rows[0]['point_estimate']==0.8 and rows[0]['parameter_type']=='R0'
    assert rows[0]['estimate_id'].startswith('estimate:')
    assert not rows[0]['needs_review']
    assert rows[0]['semantic_review']==('not_run' if variant=='without_b' else 'reviewed')
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['status']=='complete'
    assert (tmp_path/'coding_estimates.jsonl').read_text().strip()


def test_lx_is_inside_a_and_not_used_by_without_a(config,tmp_path):
    backend_calls=[]
    def extract_a(block,cfg):
        backend_calls.append(block['block_id'])
        return [record()]
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
        invoke=lambda *_:pytest.fail('B should be removed'),extract_a=extract_a,
        output_dir=tmp_path,ablation='without_b')
    assert backend_calls==['main-block-1'] and rows[0]['producer']=='stage_a'
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
        invoke=lambda *_:json.dumps({'records':[record(candidate_id=None)],'dispositions':[]}),
        extract_a=lambda *_:pytest.fail('A backend must not run in without_a'),
        output_dir=tmp_path/'without_a',ablation='without_a')
    assert rows[0]['producer']=='stage_b' 


def test_full_text_tail_processed_without_truncation(config,tmp_path):
    text=('Filler paragraph. '*10+'\n\n')*4 + SOURCE
    blocks=source_blocks(text,256)
    assert all(b['text']==text[b['start']:b['end']] for b in blocks)
    assert set().union(*(set(range(b['start'],b['end'])) for b in blocks))==set(range(len(text)))
    assert blocks[-1]['end']==len(text)
    assert all(len(b['text'])<=256 for b in blocks)
    calls=[]
    def invoke(stage,messages):
        calls.append(messages[-1]['content'])
        return '[]'
    assert run_stages(text=text,config=config,record_id='r',pmid=None,invoke=invoke,
                      output_dir=tmp_path,ablation='without_b',chunk_chars=256)==[]
    assert any(SOURCE in call for call in calls)
    assert json.loads((tmp_path/'coverage.json').read_text())['status']=='complete'


def test_malformed_model_output_is_failure_not_absence(config,tmp_path):
    with pytest.raises(json.JSONDecodeError):
        run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
                   invoke=lambda *_:'[{"point_estimate":',output_dir=tmp_path)
    assert json.loads((tmp_path/'coverage.json').read_text())['status']=='failed'


def test_dropped_candidate_fails(config,tmp_path):
    def invoke(stage,_):
        return json.dumps([record()]) if stage=='stage_a' else '{"records":[],"dispositions":[]}'
    with pytest.raises(ValueError,match='every candidate'):
        run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)


def test_unsupported_identity_cannot_be_used_as_cohort(config,tmp_path):
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
                   invoke=lambda *_:json.dumps([record(cohort_id='invented-cohort')]),
                   output_dir=tmp_path,ablation='without_b')
    assert rows[0]['cohort_id'] is None
    assert rows[0]['needs_review']
    assert rows[0]['unverified_identity']['cohort_id']=='invented-cohort'


def test_long_paragraph_is_split_with_overlap():
    blocks=source_blocks('x'*600,256)
    assert len(blocks)>1 and all(len(b['text'])<=256 for b in blocks)
    assert blocks[1]['start']<blocks[0]['end'] and blocks[-1]['end']==600


@pytest.mark.parametrize('empty', [False, True])
def test_pipeline_custom_codebook_lossless_and_valid_empty(tmp_path,monkeypatch,empty):
    from metaagent.coding.pipeline import extraction
    import pandas as pd
    source=tmp_path/'source.md'; source.write_text(SOURCE)
    codebook=tmp_path/'custom.yaml'
    codebook.write_text('''project:
  name: custom
fields:
  - {name: pmid, type: str, required: true}
  - {name: parameter_type, type: str, required: true}
  - {name: point_estimate, type: float}
''')
    manifest=tmp_path/'documents.jsonl'
    manifest.write_text(json.dumps({'record_id':'report-one','path':str(source)})+'\n')
    monkeypatch.setattr(extraction,'init_llm',lambda *_:object())
    monkeypatch.setattr(extraction,'_invoke_model_content',lambda **_:json.dumps([] if empty else [record()]))
    out=tmp_path/'out'
    extraction.run_pipeline(source,out,'both',codebook,document_manifest=manifest,
                            ablation='without_b', extraction_backend='llm', llm_overrides={
                                'llm_provider':'openai','llm_model':'offline-test',
                                'llm_api_base':'http://localhost:1/v1','llm_api_key':'offline-placeholder'})
    rows=[json.loads(s) for s in (out/'coding_estimates.jsonl').read_text().splitlines()]
    if empty:
        assert rows==[] and pd.read_excel(out/'coding_sheet_empty.xlsx').empty
    else:
        assert rows[0]['record_id']=='report-one'
        assert rows[0]['field_evidence']['point_estimate'][0]['quote']==SOURCE
        assert rows[0]['estimate_id'].startswith('estimate:')
    executed=list(out.glob('run_manifest*.json'))
    assert len(executed)==1
    extra=json.loads(executed[0].read_text())['extra']
    assert extra['error_count']==0
    assert Path(extra['coding_estimates_path']).is_file()


def test_long_table_header_and_footnote_have_original_offsets(config,tmp_path):
    from metaagent.coding.stages import _validated
    table='| Parameter | Value |\n| --- | --- |\n'+'| filler | 1 |\n'*30+'| R0 | 0.8 |\n'+'| filler | 2 |\n'*30+'Notes: values are dimensionless.\n'
    blocks=source_blocks(table,256)
    row_block=next(b for b in blocks if '| R0 | 0.8 |' in b['text'])
    assert any('| Parameter | Value |' in seg['text'] for seg in row_block['segments'])
    assert any('Notes:' in seg['text'] for seg in row_block['segments'])
    row=_validated({'parameter_type':'R0','point_estimate':0.8,'_field_evidence':{
        'parameter_type':'| R0 | 0.8 |','point_estimate':'| R0 | 0.8 |'}},config,row_block,None)
    for entry in row['field_evidence']['point_estimate']:
        assert table[entry['start']:entry['end']]==entry['quote']


def test_overlap_duplicate_merges_only_same_original_evidence(config,tmp_path):
    source='filler '*34+'\n'+SOURCE+'\n'+'more filler '*30
    def invoke(_,messages):
        content=json.loads(messages[-1]['content'])
        found=any(SOURCE in s['text'] for s in content['source_segments'])
        return json.dumps([record()] if found else [])
    rows=run_stages(text=source,config=config,record_id='r',pmid=None,
        invoke=invoke,output_dir=tmp_path,ablation='without_b',chunk_chars=256)
    assert len(rows)==1
    spans=rows[0]['field_evidence']['point_estimate']
    assert source[spans[0]['start']:spans[0]['end']]==SOURCE


def test_b_can_request_distant_original_source_without_a(config,tmp_path):
    text=SOURCE+'\n\n'+('filler '*35+'\n\n')*8+'A named cohort comprises 40 patients.'
    call=0
    def invoke(stage,messages):
        nonlocal call
        call+=1
        payload=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[0])
        # Request a distant block once; both the catalog and retrieved source are
        # independent of an A output, which is absent in this experiment.
        if call==1:
            return json.dumps({'request_block_ids':[payload['source_catalog'][-1]['block_id']]})
        assert stage=='stage_b'
        return json.dumps({'records':[],'dispositions':[]})
    rows=run_stages(text=text,config=config,record_id='r',pmid=None,invoke=invoke,
        output_dir=tmp_path,ablation='without_a',chunk_chars=256)
    assert rows==[]
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['stage_a_calls']==0 and coverage['source_requests']
    assert coverage['stage_b_calls']==len(coverage['blocks'])+1


def test_real_parameter_packs_and_examples_are_source_aligned():
    from metaagent.coding.prompt_context import parameter_context
    from metaagent.coding.schema.config_loader import load_config
    config=load_config(Path('configs/covid19/codebooks/reproduction_number.yaml'))
    pack,examples=parameter_context(config)
    assert 'never by whether a numeric value exceeds one' in pack
    assert examples and any(len(e['records'])==2 for e in examples)
    for example in examples:
        assert example['synthetic']
        for row in example['records']:
            for quotes in row['_field_evidence'].values():
                assert all(quote in example['source'] for quote in quotes)


def test_supplement_bundle_and_unverified_absence(config,tmp_path):
    from metaagent.coding.pipeline.extraction import load_document_manifest,read_document_sources
    main=tmp_path/'main.md';main.write_text(SOURCE)
    supplement=tmp_path/'supp.md';supplement.write_text('Supplementary interval estimate.')
    manifest=tmp_path/'bundle.jsonl'
    manifest.write_text(json.dumps({'record_id':'r','path':'main.md','supplements':[{'path':'supp.md','source_id':'s1'}]})+'\n')
    document=load_document_manifest(manifest)[0]
    sources=read_document_sources(document)
    assert [s['source_id'] for s in sources]==['main','s1']
    run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=lambda *_:'[]',
               output_dir=tmp_path/'out',ablation='without_b',document_sources=sources)
    coverage=json.loads((tmp_path/'out/coverage.json').read_text())
    assert len(coverage['sources'])==2 and coverage['status']=='complete'


def test_valid_quote_does_not_authorize_copied_example_number(config,tmp_path):
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
        invoke=lambda *_:json.dumps([{**record(),'point_estimate':99}]),
        output_dir=tmp_path,ablation='without_b')
    assert rows[0]['needs_review']
    assert 'numeric_value_not_in_evidence:point_estimate' in rows[0]['review_flags']


@pytest.mark.parametrize('variant,b_calls',[('full',1),('without_b',0)])
def test_empty_candidate_rescan_is_a_only_and_equally_budgeted(config,tmp_path,variant,b_calls):
    a_passes=[];calls=[]
    def extract_a(block,cfg):
        a_passes.append(block['candidate_pass'])
        if block['candidate_pass']==0:return []
        assert 'additional independent candidate-discovery scan' in cfg.prompt.system
        return [record()]
    def invoke(stage,messages):
        calls.append(stage)
        cid=re.findall(r'"candidate_id": "([^"]+)"',messages[-1]['content'])[0]
        return json.dumps({'records':[record(candidate_id=cid)],'dispositions':[{'candidate_id':cid,'action':'keep','reason':'source'}]})
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,
        extract_a=extract_a,output_dir=tmp_path,ablation=variant,stage_a_empty_retries=1)
    assert a_passes==[0,1] and calls==['stage_b']*b_calls
    assert len(rows)==1
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['stage_a_calls']==2 and coverage['stage_b_calls']==b_calls
    assert [r['status'] for r in coverage['stage_a_passes']]==['empty','candidates']
    assert coverage['empty_candidate_checks'][0]['outcome']=='recovered_candidates'
    assert coverage['empty_candidate_checks'][0]['scientific_absence_verified'] is False


@pytest.mark.parametrize('budget,expected_calls',[(0,1),(1,2),(2,3)])
def test_legitimate_empty_remains_empty_with_frozen_finite_budget(config,tmp_path,budget,expected_calls):
    calls=[]
    def invoke(stage,messages):
        calls.append(stage)
        return '[]'
    rows=run_stages(text='No original parameter was estimated.',config=config,record_id='r',pmid=None,
        invoke=invoke,output_dir=tmp_path,ablation='without_b',stage_a_empty_retries=budget)
    assert rows==[] and calls==['stage_a']*expected_calls
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['stage_a_empty_retries']==budget
    assert coverage['empty_candidate_checks'][0]['outcome']=='still_empty'
    assert not coverage['empty_candidate_checks'][0]['scientific_absence_verified']


def test_lx_semantics_do_not_request_json_array_or_nested_evidence(config,tmp_path):
    from metaagent.coding.pipeline.langextract_backend import _instructions
    instructions=[]
    def extract_a(block,cfg):
        instructions.append(_instructions(cfg))
        return [record()]
    run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
        invoke=lambda *_:pytest.fail('No B'),extract_a=extract_a,
        output_dir=tmp_path,ablation='without_b')
    prompt=instructions[0]
    assert 'Return a JSON array' not in prompt and 'Return a JSON\narray' not in prompt
    assert 'provide _field_evidence mapping' not in prompt
    assert 'LangExtract serialization' in prompt
    assert 'whether that input describes observed or synthetic data' in prompt
    assert 'marker labels' in prompt


def test_curated_lx_examples_have_exact_nonoverlapping_alignment():
    lx=pytest.importorskip('langextract')
    from langextract.prompt_validation import validate_prompt_alignment
    from metaagent.coding.pipeline.langextract_backend import _examples
    from metaagent.coding.schema.config_loader import load_config
    for path in Path('configs').glob('*/codebooks/*.yaml'):
        examples=_examples(lx,load_config(path))
        assert not validate_prompt_alignment(examples).issues, str(path)


def test_lx_overlapping_envelope_uses_unique_exact_source_match(config):
    pytest.importorskip('langextract')
    from metaagent.coding.pipeline.langextract_backend import extract_with_langextract
    source='The fitted basic reproduction number R0 was 3.7.'
    def invoke(_):
        return json.dumps({'extractions':[
            {'coding_record':source,'coding_record_attributes':{'_record_id':'a','parameter_type':'R0','point_estimate':'3.7'}},
            {'field_evidence':source,'field_evidence_attributes':{'_record_id':'a','fields':['parameter_type','point_estimate']}}
        ]})
    rows=extract_with_langextract(fulltext=source,tables_summary='',was_truncated=False,
        title='Declared synthetic report',abstract='',index_json='{}',config=config,invoke=invoke,document_id='r',source_pmid='123')
    assert rows[0]['point_estimate']==3.7
    assert not rows[0]['needs_review']
    assert rows[0]['field_evidence']['point_estimate'][0]['exact_text_match']


def test_provider_attempt_counts_are_distinct_from_logical_passes(tmp_path):
    from metaagent.coding.pipeline.extraction import _publish_coding_call_counts
    coverage=tmp_path/'documents/doc/coverage.json';coverage.parent.mkdir(parents=True)
    coverage.write_text(json.dumps({'stage_a_calls':1,'stage_b_calls':0}))
    (tmp_path/'llm_calls.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in [
        {'record_id':'r','stage':'stage_a','retry_index':0},
        {'record_id':'r','stage':'stage_a','retry_index':1},
        {'record_id':'other','stage':'stage_a','retry_index':0}]))
    _publish_coding_call_counts(tmp_path,'doc','r')
    data=json.loads(coverage.read_text())
    assert data['stage_a_calls']==1 and data['stage_a_logged_provider_attempts']==2
    assert data['stage_b_logged_provider_attempts']==0


def test_real_lx_adapter_to_stage_a_preserves_structured_evidence_without_b(config,tmp_path):
    pytest.importorskip('langextract')
    from metaagent.coding.pipeline.langextract_backend import extract_with_langextract
    source='The fitted basic reproduction number R0 was 3.7.'
    def backend(block,cfg):
        def native_model(_):
            return json.dumps({'extractions':[
                {'coding_record':source,'coding_record_attributes':{'_record_id':'a','parameter_type':'R0','point_estimate':'3.7'}},
                {'field_evidence':source,'field_evidence_attributes':{'_record_id':'a','fields':['parameter_type','point_estimate']}}
            ]})
        return extract_with_langextract(fulltext=source,tables_summary='',was_truncated=False,
            title='Supplied report',abstract='',index_json='{}',config=cfg,invoke=native_model,document_id='doi:report')
    rows=run_stages(text=source,config=config,record_id='doi:report',pmid=None,
        invoke=lambda *_:pytest.fail('Stage B must remain absent'),extract_a=backend,
        output_dir=tmp_path,ablation='without_b')
    assert rows[0]['point_estimate']==3.7 and not rows[0]['needs_review']
    assert rows[0]['pmid']=='NR'
    span=rows[0]['field_evidence']['point_estimate'][0]
    assert source[span['start']:span['end']]==source
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['stage_a_calls']==1 and coverage['stage_b_calls']==0


def test_unique_whitespace_grounding_retains_literal_source_and_provider_provenance():
    from types import SimpleNamespace
    from metaagent.coding.pipeline.langextract_backend import _span
    source='Synthetic cohort.\n\nThe mean interval was 7.3 days.\n\nThe bounds were 6.2 to 8.4.'
    model='Synthetic cohort. The mean interval was 7.3 days. The bounds were 6.2 to 8.4.'
    entity=SimpleNamespace(extraction_text=model,char_interval=SimpleNamespace(start_pos=0,end_pos=len(model)),
                           alignment_status=SimpleNamespace(value='match_exact'))
    span=_span(entity,source)
    assert span['text']==source and span['model_text']==model
    assert source[span['start']:span['end']]==source
    assert span['provider_interval']=={'start':0,'end':len(model)}
    assert span['raw_exact_text_match'] is False
    assert span['repair_mode']=='unique_whitespace' and span['exact_text_match']
    assert span['source_occurrences']==1


@pytest.mark.parametrize('source,model',[
    ('Mean interval 7.3 days.\n\nMean\ninterval 7.3 days.','Mean interval 7.3 days.'),
    ('Mean\ninterval 7.3 days.','Mean interval 8.3 days.'),
    ('Mean\ninterval: 7.3 days.','Mean interval 7.3 days.'),
    ('Mean\ninterval was 7.3 days.','Average interval was 7.3 days.'),
    ('Mean interval 2 3 days.','Mean interval 23 days.'),
])
def test_whitespace_repair_never_guesses_ambiguity_or_rewrites_numbers(source,model):
    from types import SimpleNamespace
    from metaagent.coding.pipeline.langextract_backend import _span
    entity=SimpleNamespace(extraction_text=model,char_interval=None,
                           alignment_status=SimpleNamespace(value='match_fuzzy'))
    span=_span(entity,source)
    assert not span['exact_text_match'] and span['repair_mode']=='none'


def test_ambiguous_whitespace_record_still_requires_review(config):
    from types import SimpleNamespace
    from metaagent.coding.pipeline.langextract_backend import _records
    source='The fitted R0 was 3.7.\n\nThe fitted\nR0 was 3.7.'
    entity=SimpleNamespace(extraction_class='coding_record',attributes={'_record_id':'a','parameter_type':'R0','point_estimate':'3.7'},
        extraction_text='The fitted R0 was 3.7.',char_interval=None,alignment_status=SimpleNamespace(value='match_fuzzy'))
    row=_records([entity],source=source,config=config,pmid='123',truncated=False,document_id='r')[0]
    assert row['needs_review']
    assert 'record_evidence_not_exact' in row['review_notes']
    assert 'ambiguous_record_evidence_location' in row['review_notes']


def test_b_missing_record_association_corrected_once_then_published_atomically(config,tmp_path):
    b_calls=[];a_calls=[]
    def invoke(stage,messages):
        if stage=='stage_a':
            a_calls.append(stage)
            return json.dumps([record()])
        b_calls.append(messages)
        user=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[0])
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        ds=[{'candidate_id':cid,'action':'keep','reason':'source-supported'}]
        if len(b_calls)==1:
            return json.dumps({'records':[record()],'dispositions':ds})
        feedback=user['candidate_contract_feedback']
        assert feedback['missing_candidate_ids']==[cid]
        assert feedback['records_missing_candidate_id']==[0]
        assert feedback['locked_disposition_actions']=={cid:'keep'}
        assert (tmp_path/'coding_estimates.jsonl').read_text()==''
        assert (tmp_path/'candidate_dispositions.jsonl').read_text()==''
        initial=json.loads(b_calls[0][-1]['content'].split('\nCandidates (guidance only):\n')[0])
        assert user['source_segments']==initial['source_segments']
        return json.dumps({'records':[record(candidate_id=cid)],'dispositions':ds})
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
    assert len(a_calls)==1 and len(b_calls)==2 and len(rows)==1
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['stage_a_calls']==1 and coverage['stage_b_calls']==2
    assert coverage['stage_b_contract_corrections'][0]['status']=='corrected'


@pytest.mark.parametrize('bad_repair',['missing_id','reject_escape','unknown_id','malformed_json'])
def test_b_failed_correction_keeps_guards_and_no_unvalidated_rows(config,tmp_path,bad_repair):
    counts={'stage_a':0,'stage_b':0}
    def invoke(stage,messages):
        counts[stage]+=1
        if stage=='stage_a':return json.dumps([record()])
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        if counts['stage_b']==1 or bad_repair=='missing_id':
            return json.dumps({'records':[record()],'dispositions':[{'candidate_id':cid,'action':'keep'}]})
        if bad_repair=='reject_escape':
            return json.dumps({'records':[],'dispositions':[{'candidate_id':cid,'action':'reject'}]})
        if bad_repair=='unknown_id':
            return json.dumps({'records':[record(candidate_id='invented')],'dispositions':[{'candidate_id':cid,'action':'keep'}]})
        return '{"records":['
    with pytest.raises(ValueError):
        run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
    assert counts=={'stage_a':1,'stage_b':2}
    assert (tmp_path/'coding_estimates.jsonl').read_text()==''
    assert (tmp_path/'candidate_dispositions.jsonl').read_text()==''
    coverage=json.loads((tmp_path/'coverage.json').read_text())
    assert coverage['status']=='failed' and coverage['stage_b_contract_corrections'][0]['status']=='failed'


def test_legitimate_b_rejection_needs_no_contract_correction(config,tmp_path):
    stages=[]
    def invoke(stage,messages):
        stages.append(stage)
        if stage=='stage_a':return json.dumps([record()])
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        return json.dumps({'records':[],'dispositions':[{'candidate_id':cid,'action':'reject','reason':'Source estimate is outside declared scope'}]})
    assert run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)==[]
    assert stages==['stage_a','stage_b']
    assert not json.loads((tmp_path/'coverage.json').read_text()).get('stage_b_contract_corrections')


def test_initial_b_malformed_json_gets_one_contract_correction(config,tmp_path):
    calls=[]
    def invoke(stage,messages):
        if stage=='stage_a':return json.dumps([record()])
        calls.append(messages)
        if len(calls)==1:return '{"records":['
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        feedback=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[0])['candidate_contract_feedback']
        assert feedback['missing_candidate_ids']==[cid]
        return json.dumps({'records':[record(candidate_id=cid)],'dispositions':[{'candidate_id':cid,'action':'pending','reason':'Requires source review'}]})
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
    assert len(calls)==2 and rows[0]['needs_review']


def test_duplicate_equal_keep_dispositions_still_lock_semantic_action(config,tmp_path):
    calls=[]
    def invoke(stage,messages):
        if stage=='stage_a':return json.dumps([record()])
        calls.append(messages)
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        if len(calls)==1:
            return json.dumps({'records':[],'dispositions':[{'candidate_id':cid,'action':'keep'},{'candidate_id':cid,'action':'keep'}]})
        feedback=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[0])['candidate_contract_feedback']
        assert feedback['locked_disposition_actions']=={cid:'keep'}
        return json.dumps({'records':[],'dispositions':[{'candidate_id':cid,'action':'reject'}]})
    with pytest.raises(ValueError,match='cannot change'):
        run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
    assert len(calls)==2 and (tmp_path/'coding_estimates.jsonl').read_text()==''


def test_mixed_valid_and_invalid_b_records_never_publish_partial_block(config,tmp_path):
    calls=[]
    def invoke(stage,messages):
        if stage=='stage_a':return json.dumps([record()])
        calls.append(messages)
        assert (tmp_path/'coding_estimates.jsonl').read_text()==''
        assert (tmp_path/'candidate_dispositions.jsonl').read_text()==''
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        return json.dumps({'records':[record(candidate_id=cid),record()],
                           'dispositions':[{'candidate_id':cid,'action':'keep'}]})
    with pytest.raises(ValueError,match='explicit candidate_id'):
        run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
    assert len(calls)==2
    assert (tmp_path/'coding_estimates.jsonl').read_text()==''
    assert (tmp_path/'candidate_dispositions.jsonl').read_text()==''


@pytest.mark.parametrize('repair_succeeds',[True,False])
def test_lx_misplaced_record_id_has_only_one_same_source_contract_correction(config,tmp_path,repair_succeeds):
    pytest.importorskip('langextract')
    from metaagent.coding.pipeline.langextract_backend import extract_with_langextract
    source='The fitted basic reproduction number R0 was 3.7.'
    calls=[]
    def invoke(messages):
        calls.append(messages)
        attrs={'parameter_type':'R0','point_estimate':'3.7'}
        if len(calls)==2:
            assert 'Every LangExtract extraction must have a nonempty _record_id' in messages[0]['content']
            assert source in messages[0]['content']
            if repair_succeeds:attrs['_record_id']='one'
        record_item={'coding_record':source,'coding_record_attributes':attrs}
        if not (len(calls)==2 and repair_succeeds):record_item['_record_id']='one'
        return json.dumps({'extractions':[
            record_item,
            {'field_evidence':source,'field_evidence_attributes':{'_record_id':'one','fields':['parameter_type','point_estimate']}}
        ]})
    kwargs=dict(fulltext=source,tables_summary='',was_truncated=False,title='Source report',abstract='',
                index_json='{}',config=config,invoke=invoke,document_id='r',evidence_dir=tmp_path)
    if repair_succeeds:
        rows=extract_with_langextract(**kwargs)
        assert rows[0]['point_estimate']==3.7 and not rows[0]['needs_review']
    else:
        with pytest.raises(ValueError,match='nonempty _record_id'):
            extract_with_langextract(**kwargs)
    assert len(calls)==2
    payload=json.loads(next(tmp_path.glob('*.evidence.json')).read_text())
    assert payload['source_text']==source
    assert len(payload['wire_responses'])==2
    assert [a['status'] for a in payload['contract_attempts']]==['rejected','accepted' if repair_succeeds else 'rejected']
    assert payload['settings']['wire_calls_max']==2


def test_lx_invalid_latex_json_escape_uses_same_bounded_contract_correction(config,tmp_path):
    pytest.importorskip('langextract')
    from metaagent.coding.pipeline.langextract_backend import extract_with_langextract
    source='The fitted R0 was 3.7; literal marker '+chr(92)+'% remains source data.'
    calls=[]
    envelope={'extractions':[
        {'coding_record':source,'coding_record_attributes':{'_record_id':'r','parameter_type':'R0','point_estimate':'3.7'}},
        {'field_evidence':source,'field_evidence_attributes':{'_record_id':'r','fields':['parameter_type','point_estimate']}}]}
    def invoke(messages):
        calls.append(messages)
        response=json.dumps(envelope)
        if len(calls)==1:return response.replace(chr(92)*2+'%',chr(92)+'%')
        assert 'Invalid' in messages[0]['content'] and 'escape' in messages[0]['content']
        return response
    rows=extract_with_langextract(fulltext=source,tables_summary='',was_truncated=False,title='Source',
        abstract='',index_json='{}',config=config,invoke=invoke,evidence_dir=tmp_path,document_id='r')
    assert len(calls)==2 and rows[0]['point_estimate']==3.7 and not rows[0]['needs_review']
    assert rows[0]['field_evidence']['point_estimate'][0]['text']==source
    audit=json.loads(next(tmp_path.glob('*.evidence.json')).read_text())
    assert audit['contract_attempts'][0]['error_type']=='ResolverParsingError'
    assert audit['contract_attempts'][1]['status']=='accepted'


@pytest.mark.parametrize('science_supported',[True,False])
def test_evidence_location_metadata_is_derived_without_weakening_scientific_grounding(config,tmp_path,science_supported):
    config.fields.append(FieldConfig(name='evidence_locations',label='Locations',type='list[str]'))
    def invoke(stage,messages):
        row=record(evidence_locations=['Invented page 999'])
        if not science_supported:row['_field_evidence']['point_estimate']='Unseen evidence'
        return json.dumps([row])
    rows=run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,
                    output_dir=tmp_path,ablation='without_b')
    row=rows[0]
    assert row['evidence_locations']==[f'main:0-{len(SOURCE)}']
    assert row['field_status']['evidence_locations']=='derived_provenance'
    assert row['needs_review'] is (not science_supported)
    assert ('missing_or_unlocated_evidence:point_estimate' in row['review_flags']) is (not science_supported)
    assert not any(flag.endswith(':evidence_locations') for flag in row['review_flags'])


def test_lx_locations_use_only_exact_grounded_source_spans(config,tmp_path):
    pytest.importorskip('langextract')
    from metaagent.coding.pipeline.langextract_backend import extract_with_langextract
    config.fields.append(FieldConfig(name='evidence_locations',label='Locations',type='list[str]'))
    envelope={'extractions':[
        {'coding_record':SOURCE,'coding_record_attributes':{'_record_id':'r','parameter_type':'R0','point_estimate':'0.8','evidence_locations':['Invented page 999']}},
        {'field_evidence':SOURCE,'field_evidence_attributes':{'_record_id':'r','fields':['parameter_type','point_estimate']}}]}
    row=extract_with_langextract(fulltext=SOURCE,tables_summary='',was_truncated=False,title='Source',
        abstract='',index_json='{}',config=config,invoke=lambda _:json.dumps(envelope),evidence_dir=tmp_path,document_id='r')[0]
    assert row['evidence_locations']==[f'main:0-{len(SOURCE)}']
    assert not row['needs_review']


@pytest.mark.parametrize('correct_null_disposition',[True,False])
def test_b_addition_null_disposition_must_be_explicitly_corrected(config,tmp_path,correct_null_disposition):
    calls=[]
    def invoke(stage,messages):
        if stage=='stage_a':return json.dumps([record()])
        calls.append(messages)
        cid=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[1])[0]['candidate_id']
        ds=[{'candidate_id':cid,'action':'keep'}]
        if len(calls)==1 or not correct_null_disposition:ds.append({'candidate_id':None,'action':'keep'})
        if len(calls)==2:
            feedback=json.loads(messages[-1]['content'].split('\nCandidates (guidance only):\n')[0])['candidate_contract_feedback']
            assert feedback['invalid_disposition_indices']==[1]
            assert 'no disposition entry' in feedback['disposition_scope']
            assert feedback['locked_disposition_actions']=={cid:'keep'}
        return json.dumps({'records':[record(candidate_id=cid),record(candidate_id=None)],'dispositions':ds})
    if correct_null_disposition:
        assert run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
    else:
        with pytest.raises(ValueError,match='Invalid candidate disposition'):
            run_stages(text=SOURCE,config=config,record_id='r',pmid=None,invoke=invoke,output_dir=tmp_path)
        assert (tmp_path/'coding_estimates.jsonl').read_text()==''
    assert len(calls)==2


@pytest.mark.parametrize('payload',[{}, {'error':'service failure'}, {'records':None}, {'records':[3]}, {'records':[],'error':'partial output'}])
def test_invalid_LLM_candidate_envelope_cannot_become_successful_empty(config,tmp_path,payload):
    with pytest.raises(ValueError,match='Stage A must return'):
        run_stages(text=SOURCE,config=config,record_id='r',pmid=None,
            invoke=lambda *_:json.dumps(payload),output_dir=tmp_path,ablation='without_b')
    assert json.loads((tmp_path/'coverage.json').read_text())['status']=='failed'
