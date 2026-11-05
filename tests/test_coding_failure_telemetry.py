"""Failed attempts retain their own costs and diagnostics without reuse/leakage."""
import hashlib
import json
from pathlib import Path

import pytest

from metaagent.telemetry import summarize_run
from metaagent.workflow_runner import WorkflowRunError, _reusable, run_workflow
from test_workflow_task import task, options


def summary(tmp_path,events):
    path=tmp_path/'llm_calls.jsonl';path.write_text(''.join(json.dumps(e)+'\n' for e in events))
    return summarize_run({'stage_results':{'coding':{'status':'failed','walltime_s':1.25,
        'output_hashes':{str(path):hashlib.sha256(path.read_bytes()).hexdigest()}}}})['stages']['coding']


def test_missing_failed_usage_never_becomes_complete_token_total(tmp_path):
    metrics=summary(tmp_path,[{'status':'ok','usage':{'input_tokens':100,'output_tokens':20}},
                              {'status':'error','error_type':'RateLimitError'}])
    assert metrics['logged_model_calls']==2
    assert metrics['model_calls_with_usage']==1 and metrics['model_calls_missing_usage']==1
    assert metrics['input_tokens'] is None and metrics['output_tokens'] is None
    assert metrics['input_tokens_coverage']=='partial'
    assert metrics['known_input_tokens_subtotal']==100 and metrics['known_output_tokens_subtotal']==20
    assert metrics['cost_usd'] is None


def test_only_failed_event_is_counted_with_unknown_tokens(tmp_path):
    metrics=summary(tmp_path,[{'status':'error','error_type':'TimeoutError'}])
    assert metrics['logged_model_calls']==1 and metrics['cold_attempt_walltime_s']==1.25
    assert metrics['input_tokens_coverage']=='unknown' and metrics['input_tokens'] is None


def test_hash_mismatch_does_not_summarize_mutated_call_history(tmp_path):
    path=tmp_path/'llm_calls.jsonl';path.write_text('{"usage":{"input_tokens":100}}\n')
    metrics=summarize_run({'stage_results':{'coding':{'status':'failed','output_hashes':{str(path):'different-hash'}}}})['stages']['coding']
    assert metrics['call_log_coverage']=='partial' and metrics['unread_or_hash_mismatched_call_logs']==1
    assert metrics['logged_model_calls'] is None
    assert metrics['input_tokens'] is None


def test_failed_attempt_is_indexed_and_next_attempt_counts_only_itself(task,monkeypatch):
    import metaagent.workflow_runner as runner
    source=task.parent/'paper.md';source.write_text('Disease X primary report.')
    documents=task.parent/'documents.jsonl';documents.write_text(json.dumps({'record_id':'report','path':str(source)})+'\n')
    attempts=[]
    def execute(stage,o,ctx,directory,artifacts):
        directory.mkdir(parents=True);attempts.append(directory)
        current=directory/'attempts'/'explicit-current';current.mkdir(parents=True)
        pointer=current/'attempt_manifest.json';pointer.write_text(json.dumps({'status':'failed' if len(attempts)==1 else 'complete'}))
        (directory/'stage_artifacts.json').write_text(json.dumps({'attempt_id':'explicit-current','artifacts':{'coding_attempt_manifest':str(pointer)}}))
        event={'status':'error'} if len(attempts)==1 else {'status':'ok','usage':{'input_tokens':7,'output_tokens':3}}
        (directory/'llm_calls.jsonl').write_text(json.dumps(event)+'\n')
        if len(attempts)==1:raise RuntimeError('Recorded external model failure')
        return {'artifacts':{},'unresolved':0}
    monkeypatch.setattr(runner,'execute_stage',execute)
    opts=options(task,start_at='coding',stop_after='coding',document_manifest=documents)
    with pytest.raises(WorkflowRunError) as exc:run_workflow(opts)
    failed=exc.value.manifest;stage=failed['stage_results']['coding']
    assert stage['status']=='failed' and stage['walltime_s']>=0 and not _reusable(stage)
    assert str(attempts[0]/'llm_calls.jsonl') in stage['output_hashes']
    assert failed['metrics']['stages']['coding']['logged_model_calls']==1
    diagnostic=Path(stage['diagnostic_artifacts']['coding_attempt_manifest'])
    assert diagnostic.is_relative_to(attempts[0]) and json.loads(diagnostic.read_text())['status']=='failed'
    assert 'coding_attempt_manifest' not in failed['artifacts']
    saved=json.loads((Path(opts.output_dir)/'run_metrics.json').read_text())
    assert saved['stages']['coding']['input_tokens'] is None
    complete=run_workflow(opts)
    assert len(attempts)==2 and attempts[0]!=attempts[1]
    assert complete['status']=='complete' and not complete['stage_results']['coding']['reused']
    assert complete['metrics']['stages']['coding']['logged_model_calls']==1
    assert complete['metrics']['stages']['coding']['input_tokens']==7
    assert all(Path(p).is_relative_to(attempts[1]) for p in complete['stage_results']['coding']['output_hashes'])


@pytest.mark.parametrize('invalid',[
    {'estimates_input':'estimates.jsonl','start_at':'coding'},
    {'document_manifest':'documents.jsonl','start_at':'retrieval'},
    {'document_manifest':'documents.jsonl','estimates_input':'estimates.jsonl','start_at':'pooling'},
])
def test_invalid_modular_scope_plan_and_run_fail_before_writes(task,invalid):
    from metaagent.workflow_runner import plan_workflow
    kwargs={key:task.parent/value if key in {'estimates_input','document_manifest'} else value for key,value in invalid.items()}
    opts=options(task,**kwargs)
    for operation in [plan_workflow,run_workflow]:
        with pytest.raises(ValueError):operation(opts)
        assert not Path(opts.output_dir).exists()


def test_real_coding_executor_never_leaks_failed_outputs_into_normal_artifacts(task,monkeypatch):
    from metaagent.coding.pipeline import extraction
    source=task.parent/'source.md';source.write_text('Disease X mean serial interval was 4 days.')
    documents=task.parent/'documents.jsonl';documents.write_text(json.dumps({'record_id':'real-executor','path':str(source)})+'\n')
    monkeypatch.setattr(extraction,'init_llm',lambda *_:object())
    def fail_transport(*,stage_name,llm_overrides,**_):
        path=Path(llm_overrides['_coding_call_log'])
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as handle:handle.write(json.dumps({'stage':stage_name,'status':'error','error_type':'OfflineTransportFailure'})+'\n')
        raise RuntimeError('Offline transport failure after recording the attempted wire request')
    monkeypatch.setattr(extraction,'_invoke_model_content',fail_transport)
    opts=options(task,start_at='coding',stop_after='coding',document_manifest=documents)
    with pytest.raises(WorkflowRunError) as exc:run_workflow(opts)
    failed=exc.value.manifest;stage=failed['stage_results']['coding']
    assert stage['status']=='failed' and not _reusable(stage)
    assert not any(key.startswith('coding_') for key in failed['artifacts'])
    diagnostic=stage['diagnostic_artifacts']
    assert {'coding_attempt_manifest','coding_predictions','coding_execution_manifest'}<=diagnostic.keys()
    assert all(Path(diagnostic[key]).is_file() for key in ['coding_attempt_manifest','coding_predictions','coding_execution_manifest'])
    assert json.loads(Path(diagnostic['coding_attempt_manifest']).read_text())['status']=='failed'
    assert failed['metrics']['stages']['coding']['logged_model_calls']==1
    assert failed['metrics']['stages']['coding']['input_tokens'] is None
