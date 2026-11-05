"""Subprocess transport regressions: drain output before exit, enforce deadline."""
import multiprocessing as mp
import time
from types import SimpleNamespace

import pytest

from metaagent.coding.pipeline import extraction


class FakeLargeModel:
    def invoke(self,messages):
        return SimpleNamespace(content='x'*(4*1024*1024),usage_metadata={'output_tokens':4096},response_metadata={'model_name':'fake-large'})



def fake_pipe_worker(messages,overrides,connection):
    response=FakeLargeModel().invoke(messages)
    connection.send({'ok':True,'content':response.content,
        'usage':response.usage_metadata,'response_metadata':response.response_metadata})
    connection.close()


def hung_worker(messages,overrides,connection):
    time.sleep(20)


def failed_worker(messages,overrides,connection):
    from metaagent.coding.pipeline import extraction as module
    class Broken:
        def invoke(self,_):raise RuntimeError('request contains '+overrides['llm_api_key'])
    module.init_llm=lambda *_:Broken()
    # Spawn imports the original module function, unaffected by parent monkeypatch.
    module._invoke_messages_worker(messages,overrides,connection)


def provider_failed_worker(messages,overrides,connection):
    from metaagent.coding.pipeline import extraction as module
    class ProviderError(RuntimeError):
        status_code=429
        body={'error':{'details':{'retry_after':30}}}
    class Broken:
        def invoke(self,_):raise ProviderError('Provider throttled this request')
    module.init_llm=lambda *_:Broken()
    module._invoke_messages_worker(messages,overrides,connection)


def test_large_payload_does_not_wait_for_child_exit_before_reading(monkeypatch):
    monkeypatch.setenv('CODING_LLM_SUBPROCESS_TIMEOUT_S','10')
    monkeypatch.setattr(extraction,'_invoke_messages_worker',fake_pipe_worker)
    telemetry={};started=time.monotonic()
    result=extraction._invoke_model_content_once(model=None,messages=[],llm_overrides={},pmid='synthetic',stage_name='stage_a',telemetry=telemetry)
    assert len(result)==4*1024*1024
    assert telemetry['usage']['output_tokens']==4096
    assert telemetry['response_metadata']['model_name']=='fake-large'
    assert time.monotonic()-started<9


def test_process_deadline_kills_worker_and_leaves_no_live_child(monkeypatch):
    before={p.pid for p in mp.active_children()}
    monkeypatch.setenv('CODING_LLM_SUBPROCESS_TIMEOUT_S','1')
    monkeypatch.setattr(extraction,'_invoke_messages_worker',hung_worker)
    started=time.monotonic()
    with pytest.raises(extraction.LLMCallTimeoutError):
        extraction._invoke_model_content_once(model=None,messages=[],llm_overrides={},pmid='synthetic',stage_name='stage_b')
    assert time.monotonic()-started<5
    assert {p.pid for p in mp.active_children()}<=before


def test_worker_error_redacts_credential_before_crossing_process(monkeypatch):
    monkeypatch.setenv('CODING_LLM_SUBPROCESS_TIMEOUT_S','10')
    monkeypatch.setattr(extraction,'_invoke_messages_worker',failed_worker)
    secret='offline-only-private-test-key'
    with pytest.raises(RuntimeError) as exc:
        extraction._invoke_model_content_once(model=None,messages=[],llm_overrides={'llm_api_key':secret},pmid='synthetic',stage_name='stage_a')
    assert secret not in str(exc.value) and '[REDACTED]' in str(exc.value)


def test_isolated_context_uses_spawn_not_fork(monkeypatch):
    actual=mp.get_context;seen=[]
    monkeypatch.setattr(extraction.mp,'get_context',lambda mode:(seen.append(mode) or actual(mode)))
    monkeypatch.setattr(extraction,'_invoke_messages_worker',fake_pipe_worker)
    extraction._isolated_model_result([],{},10,pmid='synthetic',stage_name='stage_a')
    assert seen==['spawn']


def legacy_queue_writer(result_queue,enqueued):
    result_queue.put({'content':FakeLargeModel().invoke([]).content})
    enqueued.set()


def partial_send_worker(messages,overrides,connection):
    import os,struct
    os.write(connection.fileno(),struct.pack('!i',100000)+b'x'*16)
    time.sleep(20)


def test_old_join_before_get_pattern_reproduces_blocked_feeder():
    ctx=mp.get_context('spawn');payload=ctx.Queue(maxsize=1);enqueued=ctx.Event()
    worker=ctx.Process(target=legacy_queue_writer,args=(payload,enqueued))
    worker.start()
    try:
        assert enqueued.wait(10)
        worker.join(.2)
        assert worker.is_alive(), 'Large Queue payload cannot finish until parent drains it'
        assert len(payload.get(timeout=5)['content'])==4*1024*1024
        worker.join(5)
        assert worker.exitcode==0
    finally:
        if worker.is_alive():worker.terminate();worker.join(2)
        worker.close();payload.close();payload.join_thread()


@pytest.mark.skipif(__import__('os').name!='posix',reason='Raw pipe framing regression uses POSIX descriptors')
def test_deadline_covers_partial_payload_not_only_pipe_header(monkeypatch):
    monkeypatch.setenv('CODING_LLM_SUBPROCESS_TIMEOUT_S','1')
    monkeypatch.setattr(extraction,'_invoke_messages_worker',partial_send_worker)
    start=time.monotonic()
    with pytest.raises(extraction.LLMCallTimeoutError):
        extraction._invoke_model_content_once(model=None,messages=[],llm_overrides={},pmid='synthetic',stage_name='stage_a')
    assert time.monotonic()-start<5


def test_background_thread_uses_process_deadline_instead_of_sigalrm(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.delenv('CODING_LLM_SUBPROCESS_TIMEOUT_S',raising=False)
    monkeypatch.setenv('CODING_LLM_CALL_TIMEOUT_S','10')
    monkeypatch.setattr(extraction,'_invoke_messages_worker',fake_pipe_worker)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(extraction._invoke_model_content_once,model=None,messages=[],
            llm_overrides={},pmid='synthetic',stage_name='stage_a').result(timeout=15)
    assert len(result)==4*1024*1024


def test_spawn_retains_safe_provider_status_and_body_cooldown(monkeypatch):
    monkeypatch.setenv('CODING_LLM_SUBPROCESS_TIMEOUT_S','10')
    monkeypatch.setattr(extraction,'_invoke_messages_worker',provider_failed_worker)
    with pytest.raises(extraction.LLMSubprocessError) as exc:
        extraction._invoke_model_content_once(model=None,messages=[],llm_overrides={},pmid='synthetic',stage_name='stage_a')
    assert exc.value.status_code==429 and exc.value.retry_after_s==30


@pytest.mark.parametrize('status,expected_calls,delay',[(429,2,30),(400,1,None)])
def test_retry_policy_honors_provider_status_delay_and_logs_every_wire(monkeypatch,tmp_path,status,expected_calls,delay):
    import json
    monkeypatch.setenv('CODING_LLM_MAX_RETRIES','1');calls=[];sleeps=[]
    def invoke(**_):
        calls.append(1)
        if len(calls)==1:
            raise extraction.LLMSubprocessError('Safe provider error',status_code=status,retry_after_s=30,error_type='ProviderError')
        return '{"records":[]}'
    monkeypatch.setattr(extraction,'_invoke_model_content_once',invoke)
    monkeypatch.setattr(extraction.time,'sleep',sleeps.append)
    log=tmp_path/'calls.jsonl'
    kwargs=dict(model=None,messages=[],llm_overrides={'_coding_call_log':str(log)},pmid='synthetic',stage_name='stage_a')
    if status==400:
        with pytest.raises(extraction.LLMSubprocessError):extraction._invoke_model_content(**kwargs)
    else:assert extraction._invoke_model_content(**kwargs)=='{"records":[]}'
    events=[json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls)==expected_calls and len(events)==expected_calls
    assert events[0]['status_code']==status
    assert events[0]['provider_retry_after_s']==30
    assert sleeps==([delay] if delay else [])


def test_provider_delay_over_explicit_retry_wait_budget_is_terminal(monkeypatch,tmp_path):
    monkeypatch.setenv('CODING_LLM_MAX_RETRIES','1');monkeypatch.setenv('CODING_LLM_RETRY_MAX_WAIT_S','5')
    def invoke(**_):raise extraction.LLMSubprocessError('Cooldown exceeds wait budget',status_code=429,retry_after_s=30)
    monkeypatch.setattr(extraction,'_invoke_model_content_once',invoke)
    monkeypatch.setattr(extraction.time,'sleep',lambda *_:pytest.fail('Do not retry before provider cooldown'))
    with pytest.raises(extraction.LLMSubprocessError):
        extraction._invoke_model_content(model=None,messages=[],llm_overrides={'_coding_call_log':str(tmp_path/'call.jsonl')},pmid='synthetic',stage_name='stage_a')
