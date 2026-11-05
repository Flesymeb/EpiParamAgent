"""Real FastAPI routing to unified workflow/review adapters; no external APIs."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from webapp.app import jobs
from webapp.app.main import create_app
from webapp.app.store import Store, atomic


@pytest.fixture
def api(tmp_path, monkeypatch):
    def cfg(*args, module_hint=None, **kw):
        base = dict(provider='openai', model=f'{module_hint}-model', api_base='https://gateway.example/v1',
                    thinking='disabled', timeout_s=60, max_tokens=1000, api_key=f'private-{module_hint}-secret',
                    temperature=.1, verify_ssl=True, force_streaming=False, reasoning_effort=None)
        params = args[0] if args else {}
        if params.get('llm_provider') and params['llm_provider'] != base['provider']:
            for key in ('model', 'api_base', 'api_key', 'thinking'):
                base[key] = None
        base.update({k.removeprefix('llm_'): v for k, v in params.items()})
        return SimpleNamespace(**base)
    monkeypatch.setattr('metaagent.config.load_llm_config', cfg)
    monkeypatch.setattr('metaagent.config.load_mineru_config', lambda **kw: SimpleNamespace(base_url='https://miner.example', endpoint='/v4', timeout_s=30, api_key='miner-secret'))
    app = create_app(tmp_path / 'workspace', launch_jobs=False)
    with TestClient(app) as client:
        yield client, app.state.store, app


def task(api):
    client, _, _ = api
    payload = client.get('/api/templates/default').json()
    result = client.post('/api/tasks', json=payload)
    assert result.status_code == 201, result.text
    return result.json()


def run(api, mode='end_to_end', input_text='', **kw):
    client, _, _ = api
    item = task(api)
    result = client.post(f"/api/tasks/{item['id']}/runs", json={'mode': mode, 'input_text': input_text, **kw})
    assert result.status_code == 202, result.text
    return item, result.json()


def test_create_validates_and_persists_task_and_codebook(api):
    client, store, _ = api
    item = task(api)
    assert client.get(f"/api/tasks/{item['id']}").json()['task_yaml'] == item['task_yaml']
    assert (store.path('tasks', item['id']) / 'codebook.yaml').exists()
    bad = client.get('/api/templates/default').json()
    parsed = yaml.safe_load(bad['task_yaml'])
    parsed['review_protocol']['logic'] = 'nonexistent'
    bad['task_yaml'] = yaml.safe_dump(parsed)
    assert client.post('/api/tasks', json=bad).status_code == 422
    bad = client.get('/api/templates/default').json()
    bad['codebook_yaml'] = 'fields: []'
    assert client.post('/api/tasks', json=bad).status_code == 422


def test_config_merges_four_modules_blank_retains_and_never_leaks_key(api):
    client, store, _ = api
    result = client.post('/api/config', json={'modules': {'coding': {'model': 'new-coding', 'api_key': 'posted-private-key', 'thinking': 'enabled'}}})
    assert result.status_code == 200
    assert 'posted-private-key' not in result.text
    assert result.json()['modules']['coding']['api_key_configured'] is True
    assert result.json()['modules']['query']['model'] == 'query-model'
    client.post('/api/config', json={'modules': {'coding': {'api_key': '', 'timeout_s': 100}}})
    assert store.private_config()['modules']['coding']['api_key'] == 'posted-private-key'
    path = store.root / 'private' / 'runtime.json'
    assert path.stat().st_mode & 0o777 == 0o600
    assert (store.root / 'private').stat().st_mode & 0o777 == 0o700
    assert client.post('/api/config', json={'modules': {'coding': {'api_base': 'https://user:key@example.org/v1'}}}).status_code == 422


def test_task_revision_kept_and_active_edit_rejected(api):
    client, store, _ = api
    item = task(api)
    update = {k: item[k] for k in ('name', 'task_yaml', 'codebook_yaml')}
    update['name'] = 'Edited'
    assert client.put(f"/api/tasks/{item['id']}", json=update).status_code == 200
    assert list((store.path('tasks', item['id']) / 'revisions').glob('*.json'))
    client.post(f"/api/tasks/{item['id']}/runs", json={})
    assert client.put(f"/api/tasks/{item['id']}", json=update).status_code == 409


def test_normal_end_to_end_default_full_and_duplicate_prevented(api):
    client, store, _ = api
    item, created = run(api)
    saved = store.read('runs', created['id'])
    options = jobs.options_for(store, saved)
    assert options.ablation == 'full'
    assert options.start_at == 'retrieval' and options.stop_after == 'pooling'
    assert options.task_config.is_file()
    assert 'private-coding-secret' not in options.task_config.read_text()
    assert client.post(f"/api/tasks/{item['id']}/runs", json={}).status_code == 409


@pytest.mark.parametrize('mode,start,stop', [('screening', 'screening', 'screening'), ('coding', 'coding', 'coding'), ('synthesis', 'pooling', 'pooling')])
def test_standalone_modules_dispatch_same_workflow_options(api, mode, start, stop):
    client, store, _ = api
    item = task(api)
    if mode == 'coding':
        upload = client.post(f"/api/tasks/{item['id']}/files?filename=paper.md", content=b'Original full text').json()
        value = {'record_id': 'doc', 'path': upload['path']}
    elif mode == 'synthesis':
        value = {'record_id': 'doc', 'estimate_id': 'e1', 'point_estimate': 5, 'unit': 'days'}
    else:
        value = {'record_id': 'doc', 'title': 'Study', 'abstract': 'Original observations'}
    response = client.post(f"/api/tasks/{item['id']}/runs", json={'mode': mode, 'input_text': json.dumps(value)})
    assert response.status_code == 202, response.text
    options = jobs.options_for(store, store.read('runs', response.json()['id']))
    assert options.start_at == start and options.stop_after == stop
    if mode == 'coding':
        assert options.document_manifest and options.ablation == 'full'
    if mode == 'synthesis':
        assert options.estimates_input
    if mode == 'screening':
        assert options.raw_input and options.input_mode == 'raw_search'


@pytest.mark.parametrize('status,expected', [('complete', 'complete'), ('partial', 'partial'), ('failed', 'failed')])
def test_worker_status_is_core_status_no_fake_success(api, status, expected):
    client, store, _ = api
    _, created = run(api)
    captured = []
    def core(options):
        captured.append(options)
        manifest = {'status': status, 'stage_results': {'coding': {'status': status}}, 'artifacts': {}}
        options.output_dir.mkdir(parents=True, exist_ok=True)
        atomic(options.output_dir / 'workflow_manifest.json', manifest)
        return manifest
    jobs.run_job(store.root, created['id'], runner=core)
    value = client.get(f"/api/runs/{created['id']}").json()
    assert len(captured) == 1 and captured[0].ablation == 'full'
    assert value['status'] == expected
    assert value['stage_results']['coding']['status'] == status


def test_worker_failure_redacts_secrets_and_resume_preserves_snapshot(api):
    client, store, _ = api
    _, created = run(api)
    def failed(options):
        raise ValueError('private-coding-secret should never reach the browser')
    jobs.run_job(store.root, created['id'], runner=failed)
    detail = client.get(f"/api/runs/{created['id']}")
    assert detail.json()['status'] == 'failed'
    assert 'private-coding-secret' not in detail.text
    before = (store.path('runs', created['id']) / 'task.yaml').read_bytes()
    response = client.post(f"/api/runs/{created['id']}/resume")
    assert response.status_code == 202
    assert response.json()['status'] == 'queued'
    assert (store.path('runs', created['id']) / 'task.yaml').read_bytes() == before
    assert client.post(f"/api/runs/{created['id']}/resume").status_code == 409


def test_restart_preserves_tasks_marks_old_active_jobs_interrupted(api):
    client, store, _ = api
    item, created = run(api)
    client.__exit__(None, None, None)  # Real old-owner lifespan shutdown.
    with TestClient(create_app(store.root, launch_jobs=False)) as restarted:
        assert restarted.get(f"/api/tasks/{item['id']}").status_code == 200
        assert restarted.get(f"/api/runs/{created['id']}").json()['status'] == 'interrupted'
        assert restarted.post(f"/api/runs/{created['id']}/resume").status_code == 202


def test_upload_and_artifact_traversal_rejected(api, tmp_path):
    client, store, _ = api
    item = task(api)
    assert client.post(f"/api/tasks/{item['id']}/files?filename=../key.txt", content=b'private').status_code == 422
    assert client.post(f"/api/tasks/{item['id']}/runs", json={'mode': 'coding', 'input_text': json.dumps({'record_id': 'a', 'path': '/etc/passwd'})}).status_code == 422
    created = client.post(f"/api/tasks/{item['id']}/runs", json={}).json()
    folder = store.path('runs', created['id']) / 'workflow'
    folder.mkdir()
    secret = tmp_path / 'private.txt'; secret.write_text('not downloadable')
    inside = folder / 'result.json'; inside.write_text('{"status":"partial"}')
    atomic(folder / 'workflow_manifest.json', {'status': 'partial', 'artifacts': {'bad': str(secret), 'good': str(inside)}})
    detail = client.get(f"/api/runs/{created['id']}").json()
    assert [a['key'] for a in detail['artifacts']] == ['good']
    assert client.get(f"/api/runs/{created['id']}/artifacts/bad").status_code == 404
    assert client.get(f"/api/runs/{created['id']}/artifacts/good").json()['status'] == 'partial'


def test_review_uses_core_immutable_revision_and_protects_provenance(api):
    client, store, _ = api
    _, created = run(api)
    saved = store.read('runs', created['id']); saved['status'] = 'partial'; store.save('runs', created['id'], saved)
    folder = store.path('runs', created['id']) / 'workflow'; folder.mkdir()
    artifact = folder / 'coding.jsonl'
    artifact.write_text(json.dumps({'record_id': 'doc', 'estimate_id': 'e1', 'point_estimate': 5}) + '\n')
    task_config = yaml.safe_load((store.path('runs', created['id']) / 'task.yaml').read_text())
    atomic(folder / 'workflow_manifest.json', {'status': 'partial', 'config': {'codebook': task_config['codebook']},
                                             'artifacts': {'coding_estimates': str(artifact)}, 'stage_results': {'pooling': {'status': 'partial'}}})
    exported = client.get(f"/api/runs/{created['id']}/review?artifact=coding_estimates").json()
    patch = {'artifact': 'coding_estimates', 'revision': exported['revision'], 'reviewer': 'Actual supplied reviewer', 'reason': 'Source check',
             'changes': [{'estimate_id': 'e1', 'fields': {'producer': 'human-forged'}}]}
    response = client.post(f"/api/runs/{created['id']}/review", json={'artifact': 'coding_estimates', 'patch': patch})
    assert response.status_code == 409
    assert json.loads(artifact.read_text())['point_estimate'] == 5
    patch['changes'] = [{'estimate_id': 'e1', 'fields': {'notes': 'Checked source; pending cohort identity'}}]
    original = artifact.read_bytes()
    response = client.post(f"/api/runs/{created['id']}/review", json={'artifact': 'coding_estimates', 'patch': patch})
    assert response.status_code == 200, response.text
    assert artifact.read_bytes() == original
    assert client.post(f"/api/runs/{created['id']}/review", json={'artifact': 'coding_estimates', 'patch': patch}).status_code == 409


def test_task_provider_override_never_inherits_other_gateway_identity_or_key(api):
    client, store, _ = api
    payload = client.get('/api/templates/default').json()
    doc = yaml.safe_load(payload['task_yaml'])
    doc['llm'] = {'coding': {'provider': 'selfhosted', 'model': 'local-model', 'api_base': 'http://node.example/v1', 'api_key_env': 'MY_NODE_KEY'}}
    payload['task_yaml'] = yaml.safe_dump(doc)
    item = client.post('/api/tasks', json=payload).json()
    run = client.post(f"/api/tasks/{item['id']}/runs", json={}).json()
    snapshot = yaml.safe_load((store.path('runs', run['id']) / 'task.yaml').read_text())
    assert snapshot['llm']['coding']['model'] == 'local-model'
    assert snapshot['llm']['coding']['api_base'] == 'http://node.example/v1'
    assert snapshot['llm']['coding']['api_key_env'] == 'MY_NODE_KEY'
    assert 'gateway.example' not in json.dumps(snapshot['llm']['coding'])


def test_launch_is_a_nonblocking_managed_worker_process(api, monkeypatch):
    _, store, _ = api
    _, created = run(api)
    captured = []
    def popen(args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(pid=123456789)
    monkeypatch.setattr(jobs.subprocess, 'Popen', popen)
    saved = store.read('runs', created['id'])
    jobs.launch(store, saved)
    args, kwargs = captured[0]
    assert args[2:4] == ['-m', 'webapp.app.worker']
    assert kwargs['start_new_session'] is True
    assert kwargs['close_fds'] is True
    assert 'private-coding-secret' not in json.dumps(args)


def test_real_background_worker_executes_offline_synthesis_shared_engine(api, tmp_path, monkeypatch):
    import time
    client, store, app = api
    guard = tmp_path / "network_guard"
    guard.mkdir()
    guard_loaded = guard / "loaded"
    (guard / "sitecustomize.py").write_text(
        "from pathlib import Path\nPath(" + repr(str(guard_loaded)) + ").write_text('loaded')\n"
        "import socket\ndef deny(*a,**kw): raise AssertionError('offline worker forbids network')\n"
        "socket.socket.connect=deny\nsocket.socket.connect_ex=deny\nsocket.getaddrinfo=deny\n")
    monkeypatch.setenv("PYTHONPATH", str(guard) + os.pathsep + str(Path.cwd()) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    payload = client.get('/api/templates/default').json()
    definition = yaml.safe_load(payload['task_yaml'])
    definition['synthesis'] = {'backend': 'deterministic'}
    definition['analysis_protocol'] = {
        'analysis_id': 'offline-software-check', 'parameter_type': 'incubation_period',
        'estimate_measure': 'mean', 'unit': 'days', 'method': 'fixed',
        'uncertainty_rules': {'allowed_types': ['SE']},
        'independence': {'unit': 'cohort_id'}, 'minimum_estimates': 2,
    }
    payload['task_yaml'] = yaml.safe_dump(definition)
    created = client.post('/api/tasks', json=payload)
    assert created.status_code == 201, created.text
    item = created.json()
    app.state.launcher = jobs.launch
    records = [{'record_id': f'r{i}', 'estimate_id': f'e{i}', 'cohort_id': f'c{i}',
                'parameter_type': 'incubation_period', 'estimate_measure': 'mean', 'unit': 'days',
                'point_estimate': 5 + i, 'uncertainty_type': 'SE', 'se': 1} for i in range(2)]
    result = client.post(f"/api/tasks/{item['id']}/runs", json={'mode': 'synthesis', 'input_text': '\n'.join(json.dumps(row) for row in records)})
    assert result.status_code == 202, result.text
    identity = result.json()['id']
    latest = result.json()
    for _ in range(100):
        latest = client.get(f'/api/runs/{identity}').json()
        if latest['status'] not in {'queued', 'running'}:
            break
        time.sleep(.05)
    assert latest['status'] == 'complete', latest
    assert latest['manifest']['status'] == 'complete'
    result_artifact = next(a for a in latest['artifacts'] if a['key'] == 'synthesis_result')
    computed = client.get(result_artifact['url']).json()
    assert computed['result']['pooled_mean'] == 5.5
    assert computed['counts']['selected'] == 2
    assert guard_loaded.read_text() == 'loaded'
    assert not list((store.path('runs', identity) / 'workflow').rglob('*llm_calls.jsonl'))


def test_dead_worker_is_interrupted_instead_of_running_forever(api):
    client, store, _ = api
    _, created = run(api)
    saved = store.read('runs', created['id'])
    saved.update(status='running', pid=123456789)
    store.save('runs', created['id'], saved)
    assert client.get(f"/api/runs/{created['id']}").json()['status'] == 'interrupted'


def test_old_runtime_secret_stays_redacted_after_rotation(api):
    client, store, _ = api
    _, created = run(api)
    saved = store.read('runs', created['id']); saved['status'] = 'failed'; store.save('runs', created['id'], saved)
    client.post('/api/config', json={'modules': {'coding': {'api_key': 'rotated-new-secret'}}})
    (store.path('runs', created['id']) / 'worker.log').write_text('provider echoed private-coding-secret')
    response = client.get(f"/api/runs/{created['id']}")
    assert 'private-coding-secret' not in response.text
    assert '[REDACTED]' in response.json()['log']


def test_config_provider_only_switch_drops_old_gateway_identity_and_key(api):
    client, store, _ = api
    first = client.post('/api/config', json={'modules': {'coding': {'model': 'old-pjlab-model', 'api_base': 'https://old.gateway/v1', 'api_key': 'old-pjlab-private-key'}}})
    assert first.status_code == 200
    result = client.post('/api/config', json={'modules': {'coding': {'provider': 'selfhosted'}}})
    assert result.status_code == 200, result.text
    current = result.json()['modules']['coding']
    assert current['provider'] == 'selfhosted'
    assert current['model'] is None
    assert current['api_base'] is None
    assert current['api_key_configured'] is False
    assert store.private_config()['modules']['coding'] == {'provider': 'selfhosted'}
    assert result.json()['modules']['query']['model'] == 'query-model'


def test_mineru_public_roundtrip_keeps_private_key_and_ignores_presentation_flag(api):
    client, store, _ = api
    public = client.get('/api/config').json()['mineru']
    result = client.post('/api/config', json={'modules': {}, 'mineru': public})
    assert result.status_code == 200, result.text
    assert 'api_key_configured' not in store.private_config()['mineru']
    assert result.json()['mineru']['api_key_configured'] is True


def test_task_provider_only_override_has_no_gateway_model_base_or_key_identity(api):
    client, store, _ = api
    payload = client.get('/api/templates/default').json()
    doc = yaml.safe_load(payload['task_yaml'])
    doc['llm'] = {'coding': {'provider': 'selfhosted', 'api_key_env': 'MY_NODE_KEY'}}
    payload['task_yaml'] = yaml.safe_dump(doc)
    item = client.post('/api/tasks', json=payload).json()
    created = client.post(f"/api/tasks/{item['id']}/runs", json={}).json()
    snapshot = yaml.safe_load((store.path('runs', created['id']) / 'task.yaml').read_text())['llm']['coding']
    assert snapshot['provider'] == 'selfhosted'
    assert snapshot['api_key_env'] == 'MY_NODE_KEY'
    assert 'model' not in snapshot and 'api_base' not in snapshot and 'thinking' not in snapshot


def test_cancel_signals_only_identity_verified_managed_group_preserves_outputs(api, monkeypatch):
    client, store, _ = api
    _, created = run(api)
    saved = store.read('runs', created['id']); saved.update(status='running', pid=111222333); store.save('runs', created['id'], saved)
    folder = store.path('runs', created['id']) / 'workflow'; folder.mkdir()
    raw = folder / 'partial.jsonl'; raw.write_text('{"raw":"preserve"}\n')
    original_read = Path.read_bytes
    def process_command(path):
        if str(path) == '/proc/111222333/cmdline':
            return f'python\0-m\0webapp.app.worker\0{store.root}\0{created["id"]}\0'.encode()
        return original_read(path)
    monkeypatch.setattr(Path, 'read_bytes', process_command)
    signals = []
    monkeypatch.setattr(jobs.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    response = client.post(f"/api/runs/{created['id']}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'interrupted'
    assert signals == [(111222333, jobs.signal.SIGTERM)]
    assert raw.read_text() == '{"raw":"preserve"}\n'
    assert client.post(f"/api/runs/{created['id']}/resume").status_code == 202


def test_cancel_unmanaged_pid_or_completed_run_never_sends_signal(api, monkeypatch):
    client, store, _ = api
    _, created = run(api)
    saved = store.read('runs', created['id']); saved.update(status='running', pid=os.getpid()); store.save('runs', created['id'], saved)
    monkeypatch.setattr(jobs.os, 'killpg', lambda *_: pytest.fail('Must not signal this process'))
    assert client.post(f"/api/runs/{created['id']}/cancel").status_code == 409
    saved.update(status='complete'); store.save('runs', created['id'], saved)
    assert client.post(f"/api/runs/{created['id']}/cancel").status_code == 409


def test_artifact_metadata_and_download_report_actual_binary_mime(api):
    client, store, _ = api
    _, created = run(api)
    folder = store.path('runs', created['id']) / 'workflow'; folder.mkdir()
    image = folder / 'forest.png'; image.write_bytes(b'\x89PNG\r\n\x1a\n')
    pdf = folder / 'report.pdf'; pdf.write_bytes(b'%PDF-1.4')
    atomic(folder / 'workflow_manifest.json', {'status': 'partial', 'artifacts': {'forest': str(image), 'pdf': str(pdf)}})
    detail = client.get(f"/api/runs/{created['id']}").json()
    types = {item['key']: item['media_type'] for item in detail['artifacts']}
    assert types == {'forest': 'image/png', 'pdf': 'application/pdf'}
    assert client.get(f"/api/runs/{created['id']}/artifacts/forest").headers['content-type'] == 'image/png'


@pytest.mark.parametrize('fields', [[{'type': 'float'}], [{'name': 'value', 'type': 'unsupported_type'}], [{'name': 'value', 'type': 'float', 'range': [1]}]])
def test_malformed_editable_codebook_fields_return_actionable_422(api, fields):
    client, _, _ = api
    payload = client.get('/api/templates/default').json()
    payload['codebook_yaml'] = yaml.safe_dump({'fields': fields})
    result = client.post('/api/tasks', json=payload)
    assert result.status_code == 422, result.text
    assert 'detail' in result.json()


@pytest.mark.parametrize('where', ['notes', 'reviewer', 'reason'])
def test_review_rejects_known_credential_before_any_artifact_or_audit_write(api, where):
    client, store, _ = api
    _, created = run(api)
    saved = store.read('runs', created['id']); saved['status'] = 'partial'; store.save('runs', created['id'], saved)
    folder = store.path('runs', created['id']) / 'workflow'; folder.mkdir()
    artifact = folder / 'coding.jsonl'; artifact.write_text(json.dumps({'record_id': 'doc', 'estimate_id': 'e1', 'point_estimate': 5}) + '\n')
    codebook = yaml.safe_load((store.path('runs', created['id']) / 'task.yaml').read_text())['codebook']
    atomic(folder / 'workflow_manifest.json', {'status': 'partial', 'config': {'codebook': codebook}, 'artifacts': {'coding_estimates': str(artifact)}})
    exported = client.get(f"/api/runs/{created['id']}/review?artifact=coding_estimates").json()
    patch = {'artifact': 'coding_estimates', 'revision': exported['revision'], 'reviewer': 'Actual reviewer', 'reason': 'Checked source', 'changes': [{'estimate_id': 'e1', 'fields': {'notes': 'Ordinary note'}}]}
    if where == 'notes':
        patch['changes'][0]['fields']['notes'] = 'private-coding-secret'
    else:
        patch[where] = 'private-coding-secret'
    before = artifact.read_bytes()
    response = client.post(f"/api/runs/{created['id']}/review", json={'artifact': 'coding_estimates', 'patch': patch})
    assert response.status_code == 422, response.text
    assert 'private-coding-secret' not in response.text
    assert artifact.read_bytes() == before
    assert not (folder / 'reviews').exists()
    assert 'private-coding-secret' not in client.get(f"/api/runs/{created['id']}/artifacts/coding_estimates").text


@pytest.mark.parametrize('mode', ['screening', 'coding', 'synthesis'])
def test_module_input_known_secret_is_rejected_before_run_or_input_write(api, mode):
    client, store, _ = api
    item = task(api)
    text = json.dumps({'record_id': 'doc', 'title': 'private-coding-secret', 'point_estimate': 5})
    response = client.post(f"/api/tasks/{item['id']}/runs", json={'mode': mode, 'input_text': text})
    assert response.status_code == 422, response.text
    assert 'private-coding-secret' not in response.text
    assert store.list('runs') == []
    assert not list((store.root / 'runs').rglob('input.jsonl'))


@pytest.mark.parametrize('filename', ['paper.md', 'paper.txt', 'records.jsonl', 'records.csv', 'records.ris', 'paper.pdf'])
def test_upload_known_secret_is_rejected_without_rewriting_or_saving_source(api, filename):
    client, store, _ = api
    item = task(api)
    response = client.post(f"/api/tasks/{item['id']}/files", params={'filename': filename}, content=b'Original content with private-coding-secret')
    assert response.status_code == 422, response.text
    assert 'private-coding-secret' not in response.text
    assert not (store.path('tasks', item['id']) / 'files').exists()


def test_thinking_null_clears_private_override_inherits_environment_key_blank_retains(api):
    client, store, _ = api
    client.post('/api/config', json={'modules': {'coding': {'thinking': 'enabled', 'api_key': 'runtime-private-key'}}})
    assert store.private_config()['modules']['coding']['thinking'] == 'enabled'
    # Omission preserves an explicit override.
    client.post('/api/config', json={'modules': {'coding': {'timeout_s': 90}}})
    assert store.private_config()['modules']['coding']['thinking'] == 'enabled'
    response = client.post('/api/config', json={'modules': {'coding': {'thinking': None, 'api_key': ''}}})
    assert response.status_code == 200, response.text
    assert 'thinking' not in store.private_config()['modules']['coding']
    assert store.private_config()['modules']['coding']['api_key'] == 'runtime-private-key'
    assert response.json()['modules']['coding']['thinking'] == 'disabled'  # fixture environment/default


def test_real_multi_analysis_symbolic_keys_download_with_mime_and_no_path_escape(api, tmp_path):
    from metaagent.synthesis.engine import run_analyses
    client, store, _ = api
    _, created = run(api)
    folder = store.path('runs', created['id']) / 'workflow'
    records = [{'record_id': f'r{i}', 'estimate_id': f'e{i}', 'cohort_id': f'c{i}',
                'parameter_type': 'incubation_period', 'estimate_measure': 'mean', 'unit': 'days',
                'point_estimate': 5 + i, 'uncertainty_type': 'SE', 'se': 1} for i in range(2)]
    protocol = {'analysis_id': 'fixed-analysis', 'parameter_type': 'incubation_period', 'estimate_measure': 'mean',
                'unit': 'days', 'method': 'fixed', 'uncertainty_rules': {'allowed_types': ['SE']},
                'independence': {'unit': 'cohort_id'}}
    summary, artifacts = run_analyses(records, [protocol, {**protocol, 'analysis_id': 'random-analysis', 'method': 'random'}], output_dir=folder / 'pooling')
    assert summary['status'] == 'complete'
    assert 'analysis_001/forest_png' in artifacts and 'analysis_002/forest_pdf' in artifacts
    private = tmp_path / 'private.json'; private.write_text('{"private":true}')
    artifacts['analysis_001/private'] = str(private)
    atomic(folder / 'workflow_manifest.json', {'status': 'complete', 'artifacts': artifacts})
    saved = store.read('runs', created['id']); saved['status'] = 'complete'; store.save('runs', created['id'], saved)
    detail = client.get(f"/api/runs/{created['id']}").json()
    by_key = {a['key']: a for a in detail['artifacts']}
    assert 'analysis_001/private' not in by_key
    png = by_key['analysis_001/forest_png']
    assert '%2F' in png['url']
    assert png['media_type'] == 'image/png'
    response = client.get(png['url'])
    assert response.status_code == 200, response.text[:100]
    assert response.headers['content-type'] == 'image/png'
    assert response.content.startswith(b'\x89PNG')
    pdf = client.get(by_key['analysis_002/forest_pdf']['url'] + '?download=false')
    assert pdf.status_code == 200 and pdf.headers['content-type'] == 'application/pdf'
    assert pdf.content.startswith(b'%PDF')
    child_result = client.get(by_key['analysis_001/synthesis_result']['url']).json()
    assert child_result['analysis_id'] == 'fixed-analysis' and child_result['result']['pooled_mean'] == 5.5
    assert client.get(f"/api/runs/{created['id']}/artifacts/analysis_001%2Fprivate").status_code == 404
    assert client.get(f"/api/runs/{created['id']}/artifacts/analysis_001%2Fundelared_file").status_code == 404
    assert client.get(f"/api/runs/{created['id']}/artifacts/analysis_001%2F..%2F..%2Fprivate.json").status_code == 404


def test_import_and_construction_do_not_signal_or_modify_active_runs(api, monkeypatch):
    import importlib
    import webapp.app.main as module
    client, store, _ = api
    _, created = run(api)
    meta = store.path('runs', created['id']) / 'meta.json'
    before = meta.read_bytes()
    signals = []
    monkeypatch.setattr(jobs.os, 'killpg', lambda *args: signals.append(args))
    monkeypatch.setenv('METAAGENT_WEB_WORKSPACE', str(store.root))
    importlib.reload(module)  # Global app=create_app() must not recover jobs.
    module.create_app(store.root, launch_jobs=False)
    assert meta.read_bytes() == before
    assert store.read('runs', created['id'])['status'] == 'queued'
    assert signals == []


def test_live_workspace_owner_rejects_second_startup_without_touching_jobs(api, monkeypatch):
    client, store, owner = api
    _, created = run(api)
    meta = store.path('runs', created['id']) / 'meta.json'
    before = meta.read_bytes()
    signals = []
    monkeypatch.setattr(jobs.os, 'killpg', lambda *args: signals.append(args))
    second = create_app(store.root, launch_jobs=False)
    assert meta.read_bytes() == before
    with pytest.raises(RuntimeError, match='already owned'):
        with TestClient(second):
            pytest.fail('A second server cannot own the active workspace')
    assert meta.read_bytes() == before
    assert owner.state.server_lease is not None and not owner.state.server_lease.closed
    assert not os.get_inheritable(owner.state.server_lease.fileno())
    assert signals == []


def test_recovery_only_after_old_lifespan_releases_lease_then_new_startup(api):
    client, store, owner = api
    _, created = run(api)
    old_handle = owner.state.server_lease
    client.__exit__(None, None, None)
    assert old_handle.closed and owner.state.server_lease is None
    before = store.read('runs', created['id'])
    assert before['status'] == 'queued'
    next_app = create_app(store.root, launch_jobs=False)
    assert store.read('runs', created['id']) == before  # Construction is inert.
    with TestClient(next_app) as restarted:
        value = restarted.get(f"/api/runs/{created['id']}").json()
        assert value['status'] == 'interrupted'
        assert 'restarted' in value['error'].lower()
        assert next_app.state.server_lease is not None
    assert next_app.state.server_lease is None
