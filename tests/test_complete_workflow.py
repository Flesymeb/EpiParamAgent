"""Complete module operation, reviewed revisions and retrieval coverage."""
import copy
import json
from pathlib import Path

import pytest
import yaml

from test_workflow_task import task, options
from metaagent.workflow_runner import run_workflow
from metaagent.review import export_review, apply_review
from metaagent.retrieval import search_sources


def estimates():
    return [{'estimate_id':f'e{i}', 'record_id':f'r{i}', 'parameter_type':'serial_interval',
             'estimate_measure':'mean','unit':'days','point_estimate':v,
             'uncertainty_type':'CI','uncertainty_level':'95%',
             'uncertainty_low':v-1,'uncertainty_high':v+1} for i,v in enumerate((4,6))]


def test_synthesis_module_and_review_revision_resume(task):
    inp=task.parent/'estimates.jsonl'
    inp.write_text(''.join(json.dumps(r)+'\n' for r in estimates()))
    opts=options(task,start_at='pooling',estimates_input=inp)
    first=run_workflow(opts)
    result=json.loads(Path(first['artifacts']['synthesis_result']).read_text())
    assert result['result']['pooled_mean']==pytest.approx(5)
    patch=export_review(opts.output_dir,'coding_estimates')
    original=Path(first['artifacts']['coding_estimates']).read_bytes()
    patch.update(reviewer='Human reviewer',reason='Source correction',changes=[{'estimate_id':'e0','fields':{
        'point_estimate':5,'uncertainty_low':4,'uncertainty_high':6}}])
    receipt=apply_review(opts.output_dir,patch)
    with pytest.raises(ValueError,match='conflict'):
        apply_review(opts.output_dir,patch)
    second=run_workflow(opts)
    assert not second['stage_results']['pooling']['reused']
    assert second['artifact_overrides']['coding_estimates']['status']=='applied'
    assert Path(first['artifacts']['coding_estimates']).read_bytes()==original
    result=json.loads(Path(second['artifacts']['synthesis_result']).read_text())
    assert result['result']['pooled_mean']==pytest.approx(5.5)
    assert receipt['reviewer']=='Human reviewer'


def test_multiple_analyses_same_module_input(task):
    data=yaml.safe_load(task.read_text());p=data.pop('analysis_protocol')
    q=copy.deepcopy(p);q['analysis_id']='second';q['method']='random'
    data['analysis_protocols']=[p,q];task.write_text(yaml.safe_dump(data))
    inp=task.parent/'estimates.jsonl';inp.write_text(''.join(json.dumps(r)+'\n' for r in estimates()))
    result=run_workflow(options(task,start_at='pooling',estimates_input=inp))
    summary=json.loads(Path(result['artifacts']['synthesis_result']).read_text())
    assert len(summary['analyses'])==2
    assert summary['status']=='complete'
    assert all(a['result']['pooled_mean']==pytest.approx(5) for a in summary['analyses'])


def test_unbounded_retrieval_incomplete_audit_is_not_successful_coverage(monkeypatch,tmp_path):
    def fake(source,query,limit,*,audit,checkpoint):
        audit.update(complete=False)
        return [{'source_id':'1','title':'one'}],2,query
    monkeypatch.setattr('metaagent.retrieval.search',fake)
    rows,stats=search_sources({'europepmc':'x'},tmp_path,limit=None,complete_pubmed=None)
    assert len(rows)==1 and stats['incomplete_sources']==1
    assert not stats['retrieval_complete']


def test_document_bundle_relative_primary_supplements(tmp_path):
    from metaagent.documents import document_bundle
    from metaagent.workflow_runner import read_records
    (tmp_path/'main.md').write_text('Main source')
    (tmp_path/'supp.md').write_text('Supplement outcome')
    path=tmp_path/'input.jsonl'
    path.write_text(json.dumps({'record_id':'r','fulltext_path':'main.md','fulltext_coverage':{'complete':True},
      'supplements':[{'source_id':'S1','path':'supp.md'}]})+'\n')
    row=read_records(path)[0]
    text,coverage=document_bundle(row)
    assert 'Supplement outcome' in text and coverage['complete']
    (tmp_path/'supp.md').unlink()
    _,coverage=document_bundle(row)
    assert coverage['missing_materials']==['S1'] and not coverage['complete']


def test_pagination_checkpoints_replay_cached_pages(monkeypatch,tmp_path):
    from tools.literature.sources import search
    calls=[]
    def get(url,params):
        calls.append(params['cursorMark'])
        if params['cursorMark']=='*':
            return {'hitCount':2,'resultList':{'result':[{'id':'1','title':'One'}]},'nextCursorMark':'next'}
        return {'hitCount':2,'resultList':{'result':[{'id':'2','title':'Two'}]}}
    monkeypatch.setattr('tools.literature.sources._get',get)
    audit={}
    rows,total,_=search('europepmc','x',None,audit=audit,page_cache=tmp_path)
    assert len(rows)==total==2 and audit['complete']
    assert calls==['*','next']
    def unavailable(*args,**kwargs): raise AssertionError('Cached pages should replay without network calls')
    monkeypatch.setattr('tools.literature.sources._get',unavailable)
    audit={}
    rows,total,_=search('europepmc','x',None,audit=audit,page_cache=tmp_path)
    assert len(rows)==2 and audit['cached_pages']==2 and audit['complete']


def test_review_cannot_change_machine_source_snapshot(task):
    inp=task.parent/'estimates.jsonl';inp.write_text(''.join(json.dumps(r)+'\n' for r in estimates()))
    opts=options(task,start_at='pooling',estimates_input=inp)
    run_workflow(opts)
    patch=export_review(opts.output_dir,'coding_estimates')
    patch.update(reviewer='Reviewer',reason='Correction',changes=[{'estimate_id':'e0','fields':{'source_raw':{'point_estimate':99}}}])
    with pytest.raises(ValueError,match='immutable'):
        apply_review(opts.output_dir,patch)


def test_paired_variants_share_one_prefix_and_identical_document_input(task,monkeypatch,tmp_path):
    from metaagent.experiments import run_variants
    calls=[]
    prefix=tmp_path/'prefix.jsonl'
    paper=tmp_path/'paper.md';paper.write_text('Source')
    prefix.write_text(json.dumps({'record_id':'r','record_status':'screened','llm_tier':'S','fulltext_path':str(paper)})+'\n')
    def run(opts):
        calls.append(opts)
        if opts.stop_after=='fulltext_screening':
            return {'status':'complete','artifacts':{'fulltext_predictions':str(prefix)}}
        docs=[json.loads(line) for line in opts.document_manifest.read_text().splitlines()]
        assert len(docs)==1 and docs[0]['record_id']=='r'
        return {'status':'complete','artifacts':{}}
    monkeypatch.setattr('metaagent.experiments.run_workflow',run)
    result=run_variants(options(task))
    assert result['status']=='complete' and len(calls)==4
    assert len({o.document_manifest for o in calls[1:]})==1
    assert [o.ablation for o in calls[1:]]==['full','without_a','without_b']
    assert result['scheduled_coding_reports']==1


def test_screening_audit_records_actual_attempts(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from metaagent.screening.engine import invoke_with_retry_async, _CALL_AUDIT
    class Model:
        attempts=0
        async def ainvoke(self,*args,**kwargs):
            self.attempts+=1
            if self.attempts==1: raise ConnectionError('temporary transport error')
            return SimpleNamespace(content='{"ok":true}',usage_metadata={'input_tokens':10,'output_tokens':3})
    path=tmp_path/'calls.jsonl'
    async def run():
        token=_CALL_AUDIT.set((path,['r']))
        try: return await invoke_with_retry_async(Model(),[],max_retries=2,delay=0)
        finally: _CALL_AUDIT.reset(token)
    asyncio.run(run())
    events=[json.loads(line) for line in path.read_text().splitlines()]
    assert [r['status'] for r in events]==['error','ok']
    assert events[1]['usage']['input_tokens']==10
    assert events[0]['error_type']=='ConnectionError'
