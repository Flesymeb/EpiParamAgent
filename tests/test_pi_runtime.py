"""Transport tests use a local endpoint or a fake RPC child, never a provider."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metaagent.config import LLMConfig
from metaagent.synthesis import pi_runtime as runtime


@pytest.fixture
def local_only(monkeypatch):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1', 'localhost'}:
            raise AssertionError('Transport test attempted external network')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setenv('METAAGENT_LLM_REQUESTS_PER_MINUTE', '')
    monkeypatch.setenv('HTTP_PROXY', '')
    monkeypatch.setenv('HTTPS_PROXY', '')
    monkeypatch.setenv('ALL_PROXY', '')


@pytest.fixture
def model(monkeypatch):
    cfg = LLMConfig(provider='local-test', model='test-model', api_key='sk-private-transport-secret',
                    api_base='http://127.0.0.1:9/v1', max_tokens=1024, timeout_s=3,
                    temperature=0, thinking='disabled')
    monkeypatch.setattr(runtime, 'load_llm_config', lambda *args, **kwargs: cfg)
    return cfg


def fake_pi(tmp_path, body):
    script = tmp_path / 'fake-pi'
    script.write_text('#!/usr/bin/env python3\nimport os,sys,json,time\n'
                      'if "--version" in sys.argv: print("1.3.0"); sys.exit()\n'
                      'def emit(x): print(json.dumps(x), flush=True)\n'
                      'for line in sys.stdin:\n'
                      ' c=json.loads(line)\n'
                      ' if c["type"]=="get_state":\n'
                      '  emit({"type":"response","id":c["id"],"success":True,"data":{"sessionFile":os.getcwd()+"/session.jsonl"}})\n'
                      ' elif c["type"]=="prompt":\n' + body + '\n'
                      ' else: emit({"type":"response","id":c.get("id"),"success":True})\n')
    script.chmod(0o700)
    return str(script)


def test_inspection_has_no_process_or_writes(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *_a, **_kw: pytest.fail('process from inspect'))
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *_a, **_kw: pytest.fail('process from inspect'))
    info = runtime.inspect_pi_runtime()
    if info['available']:
        assert info['version'] == '1.3.0'
        assert info['compatible'] is True
        assert len(info['fingerprint']) == 64


def test_waits_settled_after_agent_end_and_redacts(tmp_path, model):
    executable = fake_pi(tmp_path, '  emit({"type":"response","id":c["id"],"success":True})\n'
                         '  emit({"type":"agent_end","messages":[]})\n'
                         '  time.sleep(.15)\n'
                         '  print("sk-private-transport-secret",file=sys.stderr,flush=True)\n'
                         '  emit({"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done\\u2028retained"}],"usage":{"input":3,"output":2}}})\n'
                         '  emit({"type":"agent_settled","aborted":False})')
    result = runtime.run_pi_session(tmp_path, 'test', {'pi_command': executable, 'total_timeout_s': 4})
    assert result['status'] == 'complete'
    assert result['assistant_text'] == 'done\u2028retained'
    assert result['elapsed_s'] >= .15
    assert result['settled']
    for path in (tmp_path / 'pi').rglob('*'):
        if path.is_file():
            assert model.api_key not in path.read_text()
    models = next((tmp_path / 'pi').rglob('models.json')).read_text()
    assert '${METAAGENT_PI_PROXY_KEY}' in models
    assert '127.0.0.1' in models


def test_deadline_aborts_and_terminates_child(tmp_path, model):
    executable = fake_pi(tmp_path, '  emit({"type":"response","id":c["id"],"success":True})\n'
                         '  emit({"type":"agent_end","messages":[]})')
    start = time.monotonic()
    result = runtime.run_pi_session(tmp_path, 'test', {'pi_command': executable, 'total_timeout_s': .3})
    assert result['status'] == 'timeout'
    assert result['abort_reason'] == 'deadline'
    assert any(e.get('type') == 'abort' for e in map(json.loads, Path(result['events_path']).read_text().splitlines()))
    assert time.monotonic() - start < 7


class LocalModel:
    def __init__(self, tool=False):
        self.requests = []
        self.tool = tool
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((data, dict(self.headers)))
                call = len(owner.requests)
                chunks = []
                if owner.tool and call == 1:
                    chunks = [{'choices':[{'index':0,'delta':{'role':'assistant','tool_calls':[{'index':0,'id':'profile-1','type':'function','function':{'name':'epi_tool','arguments':'{"action":"profile","payload":{}}'}}]},'finish_reason':None}]},
                              {'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]
                else:
                    chunks = [{'choices':[{'index':0,'delta':{'role':'assistant','content':'LOCAL COMPLETE'},'finish_reason':None}]},
                              {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
                chunks.append({'choices':[], 'usage': {'prompt_tokens':30,'completion_tokens':5,'total_tokens':35}})
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
                for chunk in chunks:
                    chunk.update(id='local-'+str(call),object='chat.completion.chunk',created=1,model='test-model')
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode()); self.wfile.flush()
                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()


def test_real_pi_local_streaming_tool_loop(tmp_path, model, local_only):
    if not runtime.inspect_pi_runtime()['available']:
        pytest.skip('Pi 1.3.0 not installed')
    endpoint = LocalModel(tool=True)
    # Real bridge invokes the actual Python worker with a minimal valid profile.
    (tmp_path/'inputs').mkdir()
    (tmp_path/'inputs/profile.json').write_text(json.dumps({'row_count':2,'columns':['input_id','mean']}))
    (tmp_path/'workspace.json').write_text(json.dumps({'sources':[]}))
    (tmp_path/'run_settings.json').write_text(json.dumps({'max_tool_calls':10}))
    model.api_base = f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:
        result = runtime.run_pi_session(tmp_path, 'Profile the input using epi_tool, then reply.',
                                        {'total_timeout_s': 25, 'max_tokens': 64000, 'max_turns': 3})
    finally:
        endpoint.close()
    assert result['status'] == 'complete', result
    assert result['assistant_text'] == 'LOCAL COMPLETE'
    assert result['usage']['provider_attempts'] == 2
    assert result['usage']['total_tokens'] == 70
    assert len(endpoint.requests) == 2
    assert any(event['type'] == 'tool_execution_end' for event in result['tool_events'])
    end = next(event for event in result['tool_events'] if event['type']=='tool_execution_end')
    assert end['isError'] is False
    assert end['result']['details']['ok'] is True
    assert end['result']['details']['action'] == 'profile'
    assert end['result']['details']['result']['row_count'] == 2
    assert 'tool_schema' in end['result']['details']['result']
    assert endpoint.requests[0][1]['Authorization'] == 'Bearer '+model.api_key
    assert endpoint.requests[0][0]['thinking'] == {'type':'disabled'}
    assert [tool['function']['name'] for tool in endpoint.requests[0][0]['tools']] == ['epi_tool']
    assert any(m.get('role') == 'tool' for m in endpoint.requests[1][0]['messages'])
    assert not any('response_format' in request for request,_ in endpoint.requests)


@pytest.mark.parametrize('limit,value,expected', [('max_turns',1,'max_turns'),('max_tokens',1,'max_tokens')])
def test_proxy_budget_blocks_before_upstream(tmp_path, model, local_only, limit, value, expected):
    import httpx
    endpoint = LocalModel()
    model.api_base = f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    options = {'max_turns':3,'max_tokens':10000}
    options[limit] = value
    proxy = runtime._RunProxy(model, options, tmp_path, time.monotonic()+10)
    try:
        with httpx.Client(trust_env=False) as client:
            payload = {'model':model.model,'messages':[],'stream':True}
            first = client.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},json=payload)
            if limit == 'max_turns':
                assert first.status_code == 200
                second = client.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},json=payload)
                assert second.status_code == 429
                assert len(endpoint.requests) == 1
            else:
                assert first.status_code == 429
                assert not endpoint.requests
        assert proxy.blocked == expected
        assert any(event.get('forwarded') is False for event in proxy.events)
    finally:
        proxy.close(); endpoint.close()


def test_proxy_charges_input_tokens_not_request_bytes(tmp_path, model, local_only):
    """A long prompt must not exhaust the budget by counting its bytes as tokens."""
    import httpx
    endpoint = LocalModel()
    model.api_base = f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    proxy = runtime._RunProxy(model, {'max_turns':3,'max_tokens':10000}, tmp_path, time.monotonic()+10)
    try:
        with httpx.Client(trust_env=False) as client:
            # Twenty thousand bytes of prompt are about seven thousand tokens, and
            # the budget must not be spent as if they were twenty thousand tokens.
            payload = {'model':model.model,'messages':[{'role':'user','content':'x'*20000}],'stream':True}
            for _ in range(2):
                response = client.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},json=payload)
                assert response.status_code == 200, response.text
        assert len(endpoint.requests) == 2
        assert proxy.spent < 10000
    finally:
        proxy.close(); endpoint.close()


def test_real_pi_budget_no_hidden_retry(tmp_path, model, local_only):
    if not runtime.inspect_pi_runtime()['available']:
        pytest.skip('Pi not installed')
    endpoint = LocalModel(tool=True)
    model.api_base = f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:
        result = runtime.run_pi_session(tmp_path, 'Use profile then answer.',
                                        {'max_turns':1,'total_timeout_s':20})
    finally:
        endpoint.close()
    assert result['status'] == 'budget_exceeded', result
    assert result['abort_reason'] == 'max_turns'
    assert len(endpoint.requests) == 1
    assert result['usage']['provider_attempts'] == 1
    assert result['usage']['total_tokens'] == 35
    blocked = [e for e in map(json.loads, Path(result['provider_calls_path']).read_text().splitlines()) if e['type']=='budget_blocked']
    assert len(blocked) == 1, 'Pi must not auto-retry a budget rejection'


def test_real_pi_session_continuation(tmp_path, model, local_only):
    if not runtime.inspect_pi_runtime()['available']:
        pytest.skip('Pi not installed')
    endpoint = LocalModel()
    model.api_base = f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:
        first = runtime.run_pi_session(tmp_path, 'First unique question.', {'total_timeout_s':20})
        assert first['status'] == 'complete', first
        assert Path(first['session_path']).is_file()
        before = Path(first['session_path']).read_text()
        second = runtime.run_pi_session(tmp_path, 'Second unique question.',
                                         {'total_timeout_s':20,'session_path':first['session_path']})
    finally:
        endpoint.close()
    assert second['status'] == 'complete', second
    assert second['session_path'] == first['session_path']
    assert second['attempt_dir'] != first['attempt_dir']
    assert Path(first['session_path']).read_text().startswith(before)
    history = json.dumps(endpoint.requests[1][0]['messages'])
    assert 'First unique question' in history and 'Second unique question' in history


def test_reject_external_continuation_before_launch(tmp_path, model):
    outside = tmp_path / 'outside.jsonl'; outside.write_text('{}\n')
    with pytest.raises(ValueError, match='private workspace'):
        runtime.run_pi_session(tmp_path, 'question', {'session_path':str(outside)})
    assert not (tmp_path/'pi').exists()


def test_proxy_failure_usage_unknown_and_secret_safe(tmp_path, model, local_only):
    import httpx
    # No service on this ephemeral port: records a real failed connection attempt.
    proxy = runtime._RunProxy(model, {'max_turns':2,'max_tokens':10000}, tmp_path, time.monotonic()+3)
    try:
        with httpx.Client(trust_env=False) as client:
            response = client.post(proxy.url+'/chat/completions', headers={'Authorization':'Bearer '+proxy.token},
                                   json={'model':model.model,'messages':[],'stream':True})
        assert response.status_code == 502
        final = [e for e in proxy.events if e.get('phase') == 'finished']
        assert len(final) == 1 and final[0]['forwarded'] is True
        assert final[0]['usage'] is None
        assert final[0]['error']
        assert proxy.spent == model.max_tokens + final[0]['input_token_upper_bound'], 'Unknown usage retains conservative reservation'
        assert model.api_key not in proxy.path.read_text()
        assert proxy.token not in proxy.path.read_text()
    finally:
        proxy.close()


def test_proxy_close_interrupts_stalled_stream(tmp_path, model, local_only):
    import httpx
    received = threading.Event()
    release = threading.Event()
    class Stall(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
            self.wfile.write(b'data: {}\n\n'); self.wfile.flush()
            received.set(); release.wait(10)
    server = ThreadingHTTPServer(('127.0.0.1',0), Stall); server.daemon_threads=True
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    model.api_base=f'http://127.0.0.1:{server.server_port}/v1'; model.timeout_s=30
    proxy=runtime._RunProxy(model,{'max_turns':2,'max_tokens':10000},tmp_path,time.monotonic()+30)
    def request():
        try:
            with httpx.Client(trust_env=False) as client:
                client.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},
                            json={'model':model.model,'messages':[],'stream':True})
        except httpx.HTTPError:
            pass
    caller=threading.Thread(target=request,daemon=True); caller.start()
    try:
        assert received.wait(3)
        started=time.monotonic(); proxy.close()
        assert time.monotonic()-started<3
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert not proxy.workers
        final=[event for event in proxy.events if event.get('phase')=='finished']
        assert len(final)==1 and final[0]['forwarded'] and final[0]['usage'] is None
    finally:
        release.set(); server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_real_pi_failed_request_is_counted_unknown(tmp_path, model, local_only):
    if not runtime.inspect_pi_runtime()['available']:
        pytest.skip('Pi not installed')
    result=runtime.run_pi_session(tmp_path,'No remote provider exists here.',{'total_timeout_s':20})
    assert result['status']=='failed',result
    assert result['settled']
    assert result['usage']['provider_attempts']==1
    assert result['usage']['coverage']=='unknown'
    assert result['usage']['total_tokens'] is None
    assert result['assistant_messages'][0]['stop_reason']=='error'
    assert model.api_key not in json.dumps(result)


def test_reject_private_directory_symlink_without_writes(tmp_path, model):
    workspace=tmp_path/'workspace';workspace.mkdir()
    outside=tmp_path/'private-global';outside.mkdir()
    (workspace/'pi').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='within the analysis workspace'):
        runtime.run_pi_session(workspace,'question',{})
    assert not list(outside.iterdir())


def test_rpc_stdin_backpressure_obeys_deadline(tmp_path, model):
    executable=fake_pi(tmp_path,'  pass')
    script=Path(executable)
    script.write_text(script.read_text().replace('"/session.jsonl"}})', '"/session.jsonl"}})\n  time.sleep(60)'))
    started=time.monotonic()
    result=runtime.run_pi_session(tmp_path,'q'*100000,{'pi_command':executable,'total_timeout_s':.3})
    assert result['status']=='timeout'
    assert 'stdin deadline' in result['error']
    assert time.monotonic()-started<9


def test_installed_package_root_uses_current_interpreter_without_repository_venv(tmp_path,model,monkeypatch):
    import shutil
    import sys
    installed=tmp_path/'installed-site-packages'
    for package in ('metaagent','tools'):
        shutil.copytree(runtime._PROJECT/package,installed/package,ignore=shutil.ignore_patterns('__pycache__'))
    assert not (installed/'.venv').exists()
    monkeypatch.setattr(runtime,'_PROJECT',installed)
    workspace=tmp_path/'workspace';(workspace/'inputs').mkdir(parents=True)
    (workspace/'workspace.json').write_text(json.dumps({'sources':[]}))
    (workspace/'run_settings.json').write_text('{}')
    (workspace/'inputs/profile.json').write_text(json.dumps({'row_count':2,'columns':['input_id']}))
    executable=fake_pi(tmp_path,
        '  import subprocess\n'
        '  worker_env={"PATH":os.environ["PATH"],"PYTHONPATH":os.environ["METAAGENT_SYNTHESIS_PROJECT"],"METAAGENT_SYNTHESIS_WORKSPACE":os.environ["METAAGENT_SYNTHESIS_WORKSPACE"]}\n'
        '  worker=subprocess.run([os.environ["METAAGENT_SYNTHESIS_PYTHON"],"-m","metaagent.synthesis.pi_tools"],input=json.dumps({"action":"profile","payload":{}}),env=worker_env,cwd=os.environ["METAAGENT_SYNTHESIS_PROJECT"],capture_output=True,text=True,timeout=5)\n'
        '  report={"configured_python":os.environ["METAAGENT_SYNTHESIS_PYTHON"],"project":os.environ["METAAGENT_SYNTHESIS_PROJECT"],"worker_exit":worker.returncode,"worker":json.loads(worker.stdout)}\n'
        '  emit({"type":"response","id":c["id"],"success":True})\n'
        '  emit({"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":json.dumps(report)}]}})\n'
        '  emit({"type":"agent_settled","aborted":False})')
    result=runtime.run_pi_session(workspace,'Offline installed-context probe',{'pi_command':executable,'total_timeout_s':10})
    assert result['status']=='complete',result
    report=json.loads(result['assistant_text'])
    # Do not resolve this path: resolving the venv symlink loses its environment.
    assert report['configured_python']==sys.executable
    assert report['project']==str(installed)
    assert report['worker_exit']==0 and report['worker']['ok'] is True
    assert report['worker']['result']['row_count']==2
    assert result['usage']['provider_attempts']==0


def guard_fake_pi(tmp_path, body):
    """A real RPC child with local provider calls and actual project tools."""
    import sys
    setup=('  import urllib.request\n'
           '  sys.path.insert(0,os.environ["METAAGENT_SYNTHESIS_PROJECT"])\n'
           '  from pathlib import Path\n'
           '  workspace=Path(os.environ["METAAGENT_SYNTHESIS_WORKSPACE"])\n'
           '  models=json.loads((Path(os.environ["PI_CODING_AGENT_DIR"])/"models.json").read_text())\n'
           '  base=models["providers"]["metaagent-synthesis"]["baseUrl"]\n'
           '  req=urllib.request.Request(base+"/chat/completions",data=json.dumps({"model":"test-model","messages":[{"role":"user","content":c["message"]}],"stream":True}).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["METAAGENT_PI_PROXY_KEY"]})\n'
           '  with urllib.request.urlopen(req) as response: response.read()\n'
           '  emit({"type":"response","id":c["id"],"success":True})\n')
    executable=Path(fake_pi(tmp_path,setup+body))
    executable.write_text(executable.read_text().replace('#!/usr/bin/env python3', '#!'+sys.executable,1))
    return str(executable)


def guard_workspace(tmp_path):
    from test_pi_synthesis_agent import setup_workspace
    return setup_workspace(tmp_path)


def test_completion_guard_same_rpc_nudge_finishes_actual_verified_tools(tmp_path,model,local_only):
    workspace=guard_workspace(tmp_path)
    body=('  if c["id"]!="analysis-prompt":\n'
          '   sys.path.insert(0,os.environ["METAAGENT_SYNTHESIS_PROJECT"]+"/tests")\n'
          '   from test_pi_synthesis_agent import save,verified\n'
          '   from metaagent.synthesis.pi_tools import dispatch\n'
          '   save(workspace); receipt=verified(workspace)\n'
          '   result=dispatch(workspace,"finalize",{"execution_id":receipt["execution_id"]})\n'
          '   emit({"type":"tool_execution_end","toolName":"epi_tool","isError":False,"result":{"details":{"ok":True,"action":"finalize","result":result}}})\n'
          '  emit({"type":"message_end","message":{"role":"assistant","stopReason":"stop","content":[{"type":"text","text":"Let me save the plan and write code."}]}})\n'
          '  emit({"type":"agent_settled","aborted":False})')
    executable=guard_fake_pi(tmp_path,body);endpoint=LocalModel();model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:
        result=runtime.run_pi_session(workspace,'Analyze using tools',{'pi_command':executable,'max_turns':4,'total_timeout_s':20},completion_guard=True)
    finally:endpoint.close()
    assert result['status']=='complete' and result['completion']['state']=='finalized',result
    assert len(result['completion']['continuations'])==1
    assert result['completion']['continuations'][0]['action']=='save_plan'
    assert result['completion']['continuations'][0]['provider_calls_so_far']==1
    assert result['usage']['provider_attempts']==2 and result['budget']['charged_tokens']==70
    final=json.loads((workspace/'final_result.json').read_text())
    assert final['result']['point_estimate']==5 and final['validation']['numeric_provenance']=='sandbox_executed_and_repeated'
    # Both prompt commands belong to this one attempt/proxy and child session.
    events=[json.loads(line) for line in Path(result['events_path']).read_text().splitlines()]
    assert [e['id'] for e in events if e.get('type')=='prompt']==['analysis-prompt','completion-nudge-1']
    assert len(list((workspace/'pi/attempts').iterdir()))==1


def test_completion_guard_three_nudges_share_budget_and_never_accept_prose(tmp_path,model,local_only):
    workspace=guard_workspace(tmp_path)
    executable=guard_fake_pi(tmp_path,'  emit({"type":"message_end","message":{"role":"assistant","stopReason":"stop","content":[{"type":"text","text":"Will calculate next."}]}})\n  emit({"type":"agent_settled","aborted":False})')
    endpoint=LocalModel();model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:result=runtime.run_pi_session(workspace,'Analyze',{'pi_command':executable,'max_turns':10,'total_timeout_s':10},completion_guard=True)
    finally:endpoint.close()
    assert result['status']=='incomplete' and 'limit reached' in result['error']
    nudges=result['completion']['continuations'];assert len(nudges)==3
    assert [n['provider_calls_so_far'] for n in nudges]==[1,2,3]
    assert [n['charged_tokens_so_far'] for n in nudges]==[35,70,105]
    assert len(endpoint.requests)==4 and result['budget']['charged_tokens']==140
    assert not (workspace/'analysis_plan.json').exists() and not (workspace/'final_result.json').exists()


def test_completion_guard_does_not_reset_exhausted_provider_budget(tmp_path,model,local_only):
    workspace=guard_workspace(tmp_path)
    executable=guard_fake_pi(tmp_path,'  emit({"type":"agent_settled","aborted":False})')
    endpoint=LocalModel();model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:result=runtime.run_pi_session(workspace,'Analyze',{'pi_command':executable,'max_turns':1,'total_timeout_s':10},completion_guard=True)
    finally:endpoint.close()
    assert result['status']=='budget_exceeded' and result['abort_reason']=='max_turns'
    assert len(endpoint.requests)==1 and result['usage']['provider_attempts']==1
    assert not result['completion']['continuations'] and result['budget']['charged_tokens']==35


@pytest.mark.parametrize('terminal',['protocol_pending','not_computable'])
def test_completion_guard_accepts_honest_committed_pending_plan(tmp_path,model,local_only,terminal):
    workspace=guard_workspace(tmp_path)
    body=('  from metaagent.synthesis.pi_tools import dispatch\n'
          f'  dispatch(workspace,"save_plan",{{"plan":{{"research_question":"What is the mean?","method":{{"name":"unresolved"}},"reproduction_status":{terminal!r},"selection":{{"selected_input_ids":[],"rationale":"Required protocol details unavailable."}}}}}})\n'
          '  emit({"type":"agent_settled","aborted":False})')
    executable=guard_fake_pi(tmp_path,body);endpoint=LocalModel();model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:result=runtime.run_pi_session(workspace,'Analyze',{'pi_command':executable,'total_timeout_s':10},completion_guard=True)
    finally:endpoint.close()
    assert result['status']=='complete' and result['completion']['state']==terminal,result
    assert not result['completion']['continuations'] and len(endpoint.requests)==1
    assert not (workspace/'final_result.json').exists()


@pytest.mark.parametrize('failure',['error','aborted'])
def test_completion_guard_does_not_continue_provider_error_or_abort(tmp_path,model,local_only,failure):
    workspace=guard_workspace(tmp_path)
    body=(f'  emit({{"type":"message_end","message":{{"role":"assistant","stopReason":{failure!r},"errorMessage":"deliberate failure","content":[]}}}})\n'
          f'  emit({{"type":"agent_settled","aborted":{failure=="aborted"!r}}})')
    executable=guard_fake_pi(tmp_path,body);endpoint=LocalModel();model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:result=runtime.run_pi_session(workspace,'Analyze',{'pi_command':executable,'total_timeout_s':10},completion_guard=True)
    finally:endpoint.close()
    assert result['status'] in {'failed','aborted'} and not result['completion']['continuations']
    assert len(endpoint.requests)==1


def test_completion_progress_requires_commits_and_directs_only_missing_action(tmp_path):
    from test_pi_synthesis_agent import save,verified
    from metaagent.synthesis.pi_tools import dispatch
    workspace=guard_workspace(tmp_path)
    assert runtime._completion_progress(workspace)['action']=='save_plan'
    (workspace/'analysis_plan.json').write_text('{"reproduction_status":"protocol_pending"}')
    assert runtime._completion_progress(workspace)['action']=='save_plan'
    save(workspace)
    assert runtime._completion_progress(workspace)['action']=='write_code'
    receipt=verified(workspace)
    progress=runtime._completion_progress(workspace)
    assert progress['action']=='finalize' and progress['execution_id']==receipt['execution_id']
    dispatch(workspace,'finalize',{'execution_id':receipt['execution_id']})
    assert runtime._completion_progress(workspace)=={'state':'finalized','terminal':True}


def test_completion_guard_does_not_nudge_exhausted_workspace_tool_budget(tmp_path,model,local_only):
    workspace=guard_workspace(tmp_path)
    limits=json.loads((workspace/'run_settings.json').read_text());limits['max_tool_calls']=1
    (workspace/'run_settings.json').write_text(json.dumps(limits))
    executable=guard_fake_pi(tmp_path,'  from metaagent.synthesis.pi_tools import dispatch\n  dispatch(workspace,"profile",{})\n  emit({"type":"agent_settled","aborted":False})')
    endpoint=LocalModel();model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    try:result=runtime.run_pi_session(workspace,'Analyze',{'pi_command':executable,'total_timeout_s':10},completion_guard=True)
    finally:endpoint.close()
    assert result['status']=='budget_exceeded' and result['abort_reason']=='max_tool_calls'
    assert not result['completion']['continuations'] and len(endpoint.requests)==1


def test_real_pi_queue_wait_exceeds_wire_timeout_without_local_sdk_timeout(tmp_path, model, local_only, monkeypatch):
    """Exercise installed Pi, its real request timer, proxy pacing and actual HTTP."""
    if not runtime.inspect_pi_runtime()['available']:
        pytest.skip('Pi 1.3.0 not installed')
    from metaagent import llm_rate_limit as pacing
    endpoint=LocalModel(); model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1'
    model.timeout_s=.15
    wait_started=[]
    def grant(*_):
        if not wait_started:wait_started.append(time.monotonic())
        return max(0, .4-(time.monotonic()-wait_started[0]))
    monkeypatch.setattr(pacing,'_settings',lambda:(1,tmp_path/'rate'))
    monkeypatch.setattr(pacing,'_try_grant',grant)
    monkeypatch.setattr(pacing,'_cooldown',lambda *_:None)
    try:
        result=runtime.run_pi_session(tmp_path,'Local text only.',{'total_timeout_s':8,'max_tokens':64000})
    finally:endpoint.close()
    assert result['status']=='complete',result
    assert len(endpoint.requests)==1 and result['usage']['total_tokens']==35
    attempt=next(e for e in map(json.loads,Path(result['provider_calls_path']).read_text().splitlines()) if e.get('phase')=='finished')
    assert attempt['queue_wait_s'] >= .35 > attempt['wire_timeout_s']
    assert attempt['forwarded'] and attempt['wire_elapsed_s'] is not None
    private=Path(result['attempt_dir'])/'agent/settings.json'
    settings=json.loads(private.read_text())
    assert settings['retry']['provider']['timeoutMs']==8000
    assert settings['httpIdleTimeoutMs']==8000


def test_virtual_121s_queue_then_real_wire_and_double_execution_finalize(tmp_path, model, local_only, monkeypatch):
    """Advance only this module's clock; never sleep for the production 120s."""
    from types import SimpleNamespace
    from metaagent import llm_rate_limit as pacing
    offset=[0.0]
    clock=SimpleNamespace(monotonic=lambda:time.monotonic()+offset[0],time=time.time)
    monkeypatch.setattr(runtime,'time',clock)
    monkeypatch.setattr(pacing,'_settings',lambda:(1,tmp_path/'rate'))
    def grant(*_):
        if not offset[0]:offset[0]=121.0
        return 0
    monkeypatch.setattr(pacing,'_try_grant',grant)
    monkeypatch.setattr(pacing,'_cooldown',lambda *_:None)
    workspace=guard_workspace(tmp_path)
    body=('  sys.path.insert(0,os.environ["METAAGENT_SYNTHESIS_PROJECT"]+"/tests")\n'
          '  from test_pi_synthesis_agent import save,verified\n'
          '  from metaagent.synthesis.pi_tools import dispatch\n'
          '  save(workspace); receipt=verified(workspace)\n'
          '  dispatch(workspace,"finalize",{"execution_id":receipt["execution_id"]})\n'
          '  emit({"type":"agent_settled","aborted":False})')
    executable=guard_fake_pi(tmp_path,body);endpoint=LocalModel()
    model.api_base=f'http://127.0.0.1:{endpoint.server.server_port}/v1';model.timeout_s=120
    try:result=runtime.run_pi_session(workspace,'Analyze',{'pi_command':executable,'total_timeout_s':900},completion_guard=True)
    finally:endpoint.close()
    assert result['status']=='complete' and result['completion']['state']=='finalized',result
    final=json.loads((workspace/'final_result.json').read_text())
    assert final['result']['point_estimate']==5
    assert len(list((workspace/'receipts').glob('*.json')))==2
    attempt=next(e for e in map(json.loads,Path(result['provider_calls_path']).read_text().splitlines()) if e.get('phase')=='finished')
    assert attempt['queue_wait_s'] >= 121 > attempt['wire_timeout_s']
    assert attempt['forwarded'] and attempt['http_status']==200
    assert result['usage']['provider_attempts']==1 and result['budget']['charged_tokens']==35


def test_queue_exhausts_original_deadline_without_wire_or_provider_charge(tmp_path,model,local_only,monkeypatch):
    import httpx
    from types import SimpleNamespace
    from metaagent import llm_rate_limit as pacing
    offset=[0.0]
    monkeypatch.setattr(runtime,'time',SimpleNamespace(monotonic=lambda:time.monotonic()+offset[0],time=time.time))
    monkeypatch.setattr(pacing,'_settings',lambda:(1,tmp_path/'rate'))
    def grant(*_):offset[0]=10;return .001
    monkeypatch.setattr(pacing,'_try_grant',grant)
    proxy=runtime._RunProxy(model,{'max_turns':2,'max_tokens':10000},tmp_path,time.monotonic()+5)
    try:
        response=httpx.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},json={'model':model.model,'messages':[],'stream':True},trust_env=False)
        assert response.status_code==502
        event=next(e for e in proxy.events if e.get('phase')=='finished')
        assert not event['forwarded'] and event['wire_elapsed_s'] is None
        assert event['queue_wait_s']>=10 and event['usage'] is None
        assert event['token_reservation_released']>0 and proxy.spent==0
        assert proxy.calls==1  # The local attempt still consumes its bounded call slot.
    finally:proxy.close()


def test_upstream_read_timeout_still_fails_without_retry_after_queue_fix(tmp_path, model, local_only):
    import httpx
    arrived=threading.Event();release=threading.Event()
    class Slow(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']));arrived.set();release.wait(2)
    server=ThreadingHTTPServer(('127.0.0.1',0),Slow);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    model.api_base=f'http://127.0.0.1:{server.server_port}/v1';model.timeout_s=.1
    proxy=runtime._RunProxy(model,{'max_turns':2,'max_tokens':10000},tmp_path,time.monotonic()+5)
    started=time.monotonic()
    try:
        response=httpx.post(proxy.url+'/chat/completions',headers={'Authorization':'Bearer '+proxy.token},json={'model':model.model,'messages':[],'stream':True},trust_env=False)
        assert response.status_code==502 and arrived.is_set() and time.monotonic()-started<1
        event=next(e for e in proxy.events if e.get('phase')=='finished')
        assert event['forwarded'] and event['wire_timeout_s']==.1 and event['usage'] is None
        assert event['error'] and not event.get('token_reservation_released')
        assert proxy.calls==1 and proxy.spent>0  # Unknown actual wire usage stays conservative.
    finally:
        release.set();proxy.close();server.shutdown();server.server_close();thread.join()
