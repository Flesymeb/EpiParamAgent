"""FastAPI adapters for editable tasks, shared workflow jobs and core human review."""
from __future__ import annotations

import hashlib
import fcntl
from contextlib import asynccontextmanager
import json
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import jobs
from .store import ACTIVE, MODULES, ROOT, Store, atomic, default_template, now, validate_task_content


class TaskBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    task_yaml: str = Field(max_length=1_000_000)
    codebook_yaml: str = Field(max_length=1_000_000)


class RunBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['end_to_end', 'screening', 'coding', 'synthesis'] = 'end_to_end'
    input_text: str = Field(default='', max_length=10_000_000)
    resume: bool = False
    limit: int | None = Field(default=None, ge=1)
    ablation: Literal['full', 'without_a', 'without_b'] = 'full'


def inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Path is outside the managed workspace')
    return path


def read_manifest(store, run):
    path = store.path('runs', run['id']) / 'workflow' / 'workflow_manifest.json'
    return json.loads(path.read_text()) if path.exists() else None


def artifact_paths(store, run, manifest):
    root = store.path('runs', run['id']) / 'workflow'
    artifacts = {}
    for key, value in (manifest or {}).get('artifacts', {}).items():
        value = value.get('path') if isinstance(value, dict) else value
        if not isinstance(value, str):
            continue
        try:
            path = inside(value, root)
        except ValueError:
            continue
        if path.is_file():
            artifacts[key] = path
    return artifacts


def reconcile_worker(store, run):
    """Detect a terminated managed worker without presenting permanent running UI."""
    if run.get('status') not in ACTIVE or not run.get('pid'):
        return run
    pid = run['pid']
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace')
        alive = jobs.is_managed_command(command, store.root, run['id'])
    except OSError:
        alive = False
    if not alive:
        with store.lock():
            current = store.read('runs', run['id'])
            if current['status'] in ACTIVE and current.get('pid') == pid:
                current.update(status='interrupted', updated_at=now(), error='Worker stopped before recording a final result; resume to continue')
                store.save('runs', current['id'], current)
            return current
    return run


def run_summary(store, run):
    run = reconcile_worker(store, run)
    value = {k: run.get(k) for k in ('id', 'task_id', 'name', 'mode', 'status', 'created_at', 'updated_at', 'stage_results', 'error')}
    manifest = read_manifest(store, run)
    if manifest:
        value['stage_results'] = manifest.get('stage_results', {})
        key = 'coding_execution_manifest'
        paths = artifact_paths(store, run, manifest)
        if key in paths:
            actual = []
            for path in (paths[key].parent / 'documents').glob('*/coverage.json'):
                try:
                    path = inside(path, store.path('runs', run['id']) / 'workflow')
                    if path.stat().st_size < 2_000_000:
                        actual.append(json.loads(path.read_text()))
                except (OSError, ValueError):
                    continue
            value['stage_results'].setdefault('coding', {})['actual_ab'] = actual
    return store.redact(value)


def run_detail(store, run):
    value = run_summary(store, run)
    manifest = read_manifest(store, run)
    paths = artifact_paths(store, run, manifest)
    value['manifest'] = store.redact(manifest)
    value['artifacts'] = [{'key': key, 'name': path.name, 'size': path.stat().st_size,
                           'media_type': mimetypes.guess_type(path.name)[0] or ('text/plain' if path.suffix in {'.jsonl', '.md', '.txt', '.yaml', '.yml'} else 'application/octet-stream'),
                           'url': f"/api/runs/{run['id']}/artifacts/{quote(key, safe='')}"} for key, path in paths.items()]
    log = store.path('runs', run['id']) / 'worker.log'
    if log.exists():
        with log.open('rb') as handle:
            handle.seek(max(0, log.stat().st_size - 64000))
            value['log'] = store.redact(handle.read().decode(errors='replace'))
    else:
        value['log'] = ''
    return value


def task_detail(store, task):
    value = dict(task)
    recent = next((run for run in store.list('runs') if run['task_id'] == task['id']), None)
    value['latest_run'] = run_summary(store, recent) if recent else None
    return store.redact(value)


def parse_inputs(store, task, request):
    store.reject_secrets(request.input_text)
    if request.mode == 'end_to_end':
        if request.input_text.strip():
            raise ValueError('End-to-end runs use task queries; choose a module for structured inputs')
        return None
    if not request.input_text.strip():
        raise ValueError('This module requires input JSONL records')
    text = request.input_text.strip()
    rows = json.loads(text) if text.startswith('[') else [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Input must be a nonempty JSONL list of record objects')
    if request.mode != 'synthesis' and any(not str(r.get('record_id') or r.get('pmid') or r.get('PMID') or '').strip() for r in rows):
        raise ValueError('Every screening/document record requires record_id or PMID')
    for row in rows:
        for entry in [row, *(row.get('supplements') or [])]:
            for field in ('path', 'fulltext_path'):
                if not entry.get(field):
                    continue
                source = Path(entry[field]).expanduser()
                if not source.is_absolute():
                    source = store.path('tasks', task['id']) / 'files' / source
                resolved = source.resolve()
                allowed = (store.path('tasks', task['id']) / 'files', ROOT / 'paper_pool')
                if not any(resolved.is_relative_to(root.resolve()) for root in allowed) or resolved.suffix.lower() not in {'.pdf', '.md', '.txt', '.xml'} or not resolved.is_file():
                    raise ValueError('Document path must reference an uploaded or shared paper-pool PDF/MD/TXT/XML')
                entry[field] = str(resolved)
        if request.mode == 'coding' and not (row.get('path') or row.get('fulltext_path')):
            raise ValueError('Coding input needs an uploaded document path or fulltext_path')
    return rows


def create_app(workspace=None, *, launch_jobs=True):
    store = Store(workspace or os.getenv('METAAGENT_WEB_WORKSPACE') or ROOT / 'runs' / 'webapp')
    @asynccontextmanager
    async def lifespan(application):
        # Construction/import is inert. Only a server that owns this workspace
        # may recover old jobs. flock is attached to this open file description.
        lease = (store.root / 'server.lock').open('a')
        os.set_inheritable(lease.fileno(), False)
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease.close()
            raise RuntimeError('Web workspace is already owned by an active server') from None
        application.state.server_lease = lease
        try:
            jobs.interrupt_orphans(store)
            yield
        finally:
            fcntl.flock(lease, fcntl.LOCK_UN)
            lease.close()
            application.state.server_lease = None

    app = FastAPI(title='MetaAgent-Epi', version='0.4.0', lifespan=lifespan)
    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request, exc):
        return JSONResponse(status_code=422, content={'detail': [{'loc': list(e['loc']), 'msg': e['msg']} for e in exc.errors()]})

    app.state.store = store
    app.state.launcher = jobs.launch if launch_jobs else lambda *_: None

    def read(kind, identity):
        try:
            item = store.read(kind, identity)
            return reconcile_worker(store, item) if kind == 'runs' else item
        except (OSError, ValueError):
            raise HTTPException(404, 'Managed item not found') from None

    def start(run):
        try:
            app.state.launcher(store, run)
        except Exception as exc:
            run.update(status='failed', updated_at=now(), error=type(exc).__name__ + ': unable to launch worker')
            store.save('runs', run['id'], run)
        return run_detail(store, run)

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'version': app.version}

    @app.get('/api/templates/default')
    def template():
        return default_template()

    @app.get('/api/config')
    def config_get():
        return store.redact(store.public_config())

    @app.post('/api/config')
    def config_set(payload: dict):
        from metaagent.config import normalize_api_base, load_llm_config
        if set(payload) - {'modules', 'mineru'} or not isinstance(payload.get('modules', {}), dict):
            raise HTTPException(422, 'Use modules and optional mineru settings')
        try:
            with store.lock():
                value = store.private_config()
                before = store.effective_config()
                if set(payload.get('modules', {})) - set(MODULES):
                    raise ValueError('Unknown runtime module')
                for module, patch in payload.get('modules', {}).items():
                    if not isinstance(patch, dict) or set(patch) - {'provider', 'model', 'api_base', 'thinking', 'timeout_s', 'max_tokens', 'api_key'}:
                        raise ValueError('Unsupported module runtime setting')
                    target = value.setdefault('modules', {}).setdefault(module, {})
                    if patch.get('provider'):
                        selected = load_llm_config({'llm_provider': patch['provider']}, module_hint=module)
                        if selected.provider != before['modules'][module].get('provider'):
                            for key in ('provider', 'model', 'api_base', 'api_key', 'thinking'):
                                target.pop(key, None)
                    for key, supplied in patch.items():
                        if key == 'thinking' and supplied is None:
                            target.pop('thinking', None)
                            continue
                        if supplied in ('', None):
                            continue
                        if key == 'api_base':
                            normalize_api_base(supplied)
                        if key == 'thinking' and supplied not in {'enabled', 'disabled'}:
                            raise ValueError('thinking must be enabled or disabled')
                        if key in {'timeout_s', 'max_tokens'} and (type(supplied) is not int or supplied < 1):
                            raise ValueError('Runtime limits must be positive integers')
                        if key not in {'timeout_s', 'max_tokens'} and not isinstance(supplied, str):
                            raise ValueError('Runtime names and credentials must be strings')
                        target[key] = supplied
                if 'mineru' in payload:
                    patch = payload['mineru']
                    if not isinstance(patch, dict) or set(patch) - {'base_url', 'endpoint', 'api_key', 'timeout_s', 'api_key_configured'}:
                        raise ValueError('Unsupported MinerU setting')
                    for key, supplied in patch.items():
                        if key == 'api_key_configured':
                            continue
                        if supplied not in ('', None):
                            if key == 'base_url':
                                normalize_api_base(supplied)
                            if key == 'timeout_s' and (type(supplied) is not int or supplied < 1):
                                raise ValueError('MinerU timeout must be a positive integer')
                            value.setdefault('mineru', {})[key] = supplied
                atomic(store.root / 'private' / 'runtime.json', value, private=True)
        except (ValueError, TypeError):
            raise HTTPException(422, 'Invalid runtime configuration; check fields, endpoint and positive limits') from None
        return store.redact(store.public_config())

    @app.get('/api/tasks')
    def tasks():
        return {'tasks': [{k: v for k, v in task_detail(store, task).items() if k not in {'task_yaml', 'codebook_yaml'}} for task in store.list('tasks')]}

    def save_task(body, identity, previous=None):
        folder = store.path('tasks', identity)
        try:
            store.reject_secrets(body.name + '\n' + body.task_yaml + '\n' + body.codebook_yaml)
            task_yaml, codebook_yaml = validate_task_content(body.task_yaml, body.codebook_yaml, folder)
        except (ValueError, OSError, TypeError) as exc:
            if isinstance(exc, ValidationError):
                detail = [{'loc': e['loc'], 'msg': e['msg']} for e in exc.errors()]
            else:
                detail = str(store.redact(str(exc)))[:500]
            raise HTTPException(422, detail) from None
        if previous:
            old = folder / 'revisions' / (hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest() + '.json')
            if not old.exists():
                atomic(old, previous)
        value = {'id': identity, 'name': body.name, 'created_at': previous['created_at'] if previous else now(),
                 'updated_at': now(), 'task_yaml': task_yaml, 'codebook_yaml': codebook_yaml}
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'task.yaml').write_text(task_yaml)
        (folder / 'codebook.yaml').write_text(codebook_yaml)
        store.save('tasks', identity, value)
        return task_detail(store, value)

    @app.post('/api/tasks', status_code=201)
    def task_create(body: TaskBody):
        with store.lock():
            return save_task(body, uuid.uuid4().hex)

    @app.get('/api/tasks/{identity}')
    def task_get(identity: str):
        return task_detail(store, read('tasks', identity))

    @app.put('/api/tasks/{identity}')
    def task_put(identity: str, body: TaskBody):
        with store.lock():
            previous = read('tasks', identity)
            if any(r['task_id'] == identity and r['status'] in ACTIVE for r in (reconcile_worker(store, item) for item in store.list('runs'))):
                raise HTTPException(409, 'Cannot edit a task during an active run')
            return save_task(body, identity, previous)

    @app.post('/api/tasks/{identity}/files', status_code=201)
    async def upload(identity: str, request: Request, filename: str):
        read('tasks', identity)
        if Path(filename).name != filename or not re.fullmatch(r'[\w. -]+', filename) or Path(filename).suffix.lower() not in {'.pdf', '.md', '.txt', '.jsonl', '.csv', '.ris'}:
            raise HTTPException(422, 'Use a plain PDF/MD/TXT/JSONL/CSV/RIS filename without directories')
        parts, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 50_000_000:
                raise HTTPException(413, 'Upload exceeds 50 MB')
            parts.append(chunk)
        data = b''.join(parts)
        if not data:
            raise HTTPException(422, 'Empty upload')
        try:
            store.reject_secrets(filename)
            if Path(filename).suffix.lower() in {'.md', '.txt', '.jsonl', '.csv', '.ris'}:
                store.reject_secrets(data.decode('utf-8-sig'))
            elif any(secret.encode('utf-8') in data for secret in store.secrets()):
                raise ValueError('Configured credential detected in uploaded source')
        except (ValueError, UnicodeError):
            raise HTTPException(422, 'Upload contains a configured credential or invalid UTF-8 text; no source was saved') from None
        digest = hashlib.sha256(data).hexdigest()
        folder = store.path('tasks', identity) / 'files'
        folder.mkdir(exist_ok=True)
        path = folder / (digest[:20] + '_' + filename)
        if not path.exists():
            path.write_bytes(data)
        return {'filename': filename, 'path': str(path.resolve()), 'sha256': digest}

    @app.post('/api/tasks/{identity}/runs', status_code=202)
    def task_run(identity: str, body: RunBody):
        with store.lock():
            task = read('tasks', identity)
            if any(r['task_id'] == identity and r['status'] in ACTIVE for r in (reconcile_worker(store, item) for item in store.list('runs'))):
                raise HTTPException(409, 'Task already has an active execution')
            if body.resume:
                prior = next((r for r in store.list('runs') if r['task_id'] == identity and r['mode'] == body.mode), None)
                if prior is None:
                    raise HTTPException(409, 'No saved run to resume')
                if body.input_text.strip() or body.limit != prior.get('limit') or body.ablation != prior['ablation']:
                    raise HTTPException(409, 'Resume must use the saved inputs, limit and ablation; use the run resume endpoint')
                prior.update(status='queued', updated_at=now(), error=None, pid=None)
                store.save('runs', prior['id'], prior)
                return start(prior)
            try:
                rows = parse_inputs(store, task, body)
                run = jobs.new_run(store, task, body.mode, rows, ablation=body.ablation, limit=body.limit)
            except (ValueError, TypeError, OSError) as exc:
                raise HTTPException(422, str(store.redact(str(exc)))[:500]) from None
            return start(run)

    @app.get('/api/runs')
    def runs():
        return {'runs': [run_summary(store, run) for run in store.list('runs')]}

    @app.get('/api/runs/{identity}')
    def run_get(identity: str):
        return run_detail(store, read('runs', identity))

    @app.post('/api/runs/{identity}/resume', status_code=202)
    def resume(identity: str):
        with store.lock():
            run = read('runs', identity)
            if run['status'] in ACTIVE or any(r['task_id'] == run['task_id'] and r['status'] in ACTIVE for r in (reconcile_worker(store, item) for item in store.list('runs'))):
                raise HTTPException(409, 'An execution is already active')
            if not (store.root / 'private' / (identity + '.runtime.json')).is_file():
                raise HTTPException(409, 'Saved runtime snapshot is unavailable')
            run.update(status='queued', updated_at=now(), error=None, pid=None)
            store.save('runs', identity, run)
            return start(run)

    @app.post('/api/runs/{identity}/cancel')
    def cancel(identity: str):
        with store.lock():
            try:
                run = store.read('runs', identity)
            except (OSError, ValueError):
                raise HTTPException(404, 'Managed run not found') from None
            if run['status'] not in ACTIVE:
                raise HTTPException(409, 'Only an active run can be stopped')
            try:
                jobs.stop_managed_worker(store, run)
            except (ValueError, OSError) as exc:
                raise HTTPException(409, str(exc)) from None
            run.update(status='interrupted', updated_at=now(), error='Stopped by user; original artifacts retained for resume')
            store.save('runs', identity, run)
            return run_detail(store, run)

    @app.get('/api/runs/{identity}/artifacts/{key:path}')
    def artifact(identity: str, key: str, download: bool = True):
        run = read('runs', identity)
        paths = artifact_paths(store, run, read_manifest(store, run))
        if key not in paths:
            raise HTTPException(404, 'No downloadable managed artifact with this key')
        return FileResponse(paths[key], filename=paths[key].name if download else None)

    def review_guard(run, artifact):
        from metaagent.review import REVIEWABLE
        if run['status'] in ACTIVE:
            raise HTTPException(409, 'Wait for the active execution before human review')
        if artifact not in REVIEWABLE or artifact not in artifact_paths(store, run, read_manifest(store, run)):
            raise HTTPException(404, 'Reviewable prediction artifact not available')
        return store.path('runs', run['id']) / 'workflow'

    @app.get('/api/runs/{identity}/review')
    def review_get(identity: str, artifact: str = 'screening_predictions'):
        from metaagent.review import export_review
        try:
            return store.redact(export_review(review_guard(read('runs', identity), artifact), artifact))
        except (ValueError, OSError, KeyError):
            raise HTTPException(409, 'Review artifact is unavailable or inconsistent') from None

    @app.post('/api/runs/{identity}/review')
    def review_post(identity: str, body: dict):
        from metaagent.review import apply_review
        artifact, patch = body.get('artifact'), body.get('patch')
        if not isinstance(patch, dict) or patch.get('artifact') != artifact:
            raise HTTPException(422, 'Patch artifact must match the requested artifact')
        try:
            store.reject_secrets(json.dumps(patch, ensure_ascii=False))
        except ValueError:
            raise HTTPException(422, 'Credentials cannot be written into review fields, reviewer or reason') from None
        with store.lock():
            run = read('runs', identity)
            folder = review_guard(run, artifact)
            try:
                result = apply_review(folder, patch)
            except (ValueError, OSError, KeyError) as exc:
                raise HTTPException(409, str(store.redact(str(exc)))[:500]) from None
            run.update(status='partial', updated_at=now(), error='Human review changed outputs; resume downstream stages')
            store.save('runs', identity, run)
            return store.redact(result)

    dist = ROOT / 'webapp' / 'frontend' / 'dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app


app = create_app()
