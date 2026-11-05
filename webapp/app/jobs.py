"""Background subprocess jobs adapting only the unified application workflow."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

from .store import ACTIVE, ROOT, Store, atomic, now


def options_for(store, run):
    from metaagent.workflow_runner import WorkflowOptions
    folder = store.path('runs', run['id'])
    kwargs = dict(profile=run['task_id'], dataset_root=ROOT / 'dataset', output_dir=folder / 'workflow',
                  project_root=ROOT, task_config=folder / 'task.yaml', ablation=run['ablation'],
                  limit=run.get('limit'), resume=True)
    if run['mode'] == 'screening':
        kwargs.update(start_at='screening', stop_after='screening', input_mode='raw_search', raw_input=folder / 'input.jsonl')
    elif run['mode'] == 'coding':
        kwargs.update(start_at='coding', stop_after='coding', document_manifest=folder / 'input.jsonl')
    elif run['mode'] == 'synthesis':
        kwargs.update(start_at='pooling', stop_after='pooling', estimates_input=folder / 'input.jsonl')
    return WorkflowOptions(**kwargs)


def launch(store, run):
    folder = store.path('runs', run['id'])
    with (folder / 'worker.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-u', '-m', 'webapp.app.worker', str(store.root), run['id']],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    run['pid'] = process.pid
    store.save('runs', run['id'], run)


def is_managed_command(command, workspace, identity):
    """Match the worker argv exactly, not an incidental substring in another job."""
    argv = command.rstrip('\x00').split('\x00')
    if len(argv) < 5:
        return False
    offset = 2 if argv[1] == '-u' else 1
    return argv[offset:] == ['-m', 'webapp.app.worker', str(workspace), identity]


def stop_managed_worker(store, run):
    """Signal only a worker whose command, workspace and run identity all match."""
    pid = run.get('pid')
    if not pid:
        if run['status'] == 'queued':
            return
        raise ValueError('Running worker has no verifiable process identity')
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace')
    except FileNotFoundError:
        return  # The managed job is already gone; keep interruption honest.
    if not is_managed_command(command, store.root, run['id']):
        raise ValueError('Process identity cannot be verified; no signal was sent')
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def interrupt_orphans(store):
    """A new service instance terminates only its identifiable managed workers."""
    with store.lock():
        for run in store.list('runs'):
            if run['status'] not in ACTIVE:
                continue
            pid = run.get('pid')
            if pid:
                try:
                    command = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace')
                    if is_managed_command(command, store.root, run['id']):
                        os.killpg(pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            run.update(status='interrupted', updated_at=now(), error='Backend restarted; resume this saved run to continue')
            store.save('runs', run['id'], run)


def new_run(store, task, mode, input_rows, *, ablation='full', limit=None):
    identity = uuid.uuid4().hex
    folder = store.path('runs', identity)
    folder.mkdir(parents=True)
    runtime = store.effective_config()
    task_doc = yaml.safe_load(task['task_yaml'])
    task_doc['codebook'] = str((folder / 'codebook.yaml').resolve())
    task_doc.setdefault('llm', {})
    for module, spec in runtime['modules'].items():
        override = task_doc['llm'].get(module) or {}
        merged = {k: v for k, v in spec.items() if k != 'api_key' and v is not None}
        changed_provider = bool(override.get('provider') and override['provider'] != spec.get('provider'))
        changed_endpoint = bool(override.get('api_base') and override['api_base'].rstrip('/') != str(spec.get('api_base') or '').rstrip('/'))
        if changed_provider:
            for key in ('model', 'api_base', 'thinking'):
                merged.pop(key, None)
        merged.update(override)
        if override.get('api_key_env'):
            pass  # An explicit task credential identity is authoritative.
        elif changed_provider or changed_endpoint:
            # Never route a different service using the global service's key.
            merged['api_key_env'] = f'WEBAPP_{module.upper()}_UNCONFIGURED_KEY'
        elif spec.get('api_key'):
            merged['api_key_env'] = f'WEBAPP_{module.upper()}_API_KEY'
        task_doc['llm'][module] = merged
    (folder / 'task.yaml').write_text(yaml.safe_dump(task_doc, allow_unicode=True, sort_keys=False))
    (folder / 'codebook.yaml').write_text(task['codebook_yaml'])
    if input_rows is not None:
        (folder / 'input.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in input_rows))
    atomic(store.root / 'private' / (identity + '.runtime.json'), runtime, private=True)
    run = {'id': identity, 'task_id': task['id'], 'name': task['name'], 'mode': mode,
           'status': 'queued', 'created_at': now(), 'updated_at': now(), 'stage_results': {},
           'ablation': ablation, 'limit': limit, 'error': None, 'pid': None}
    store.save('runs', identity, run)
    return run


def run_job(workspace, identity, runner=None):
    """Worker process boundary: persistent status; real core status is authoritative."""
    from metaagent.workflow_runner import run_workflow
    store = Store(workspace)
    private = json.loads((store.root / 'private' / (identity + '.runtime.json')).read_text())
    for module, spec in private['modules'].items():
        if spec.get('api_key'):
            os.environ[f'WEBAPP_{module.upper()}_API_KEY'] = spec['api_key']
    for key, value in private.get('mineru', {}).items():
        if value is not None:
            os.environ['MINERU_' + key.upper()] = str(value)
    with store.lock():
        run = store.read('runs', identity)
        if run['status'] != 'queued':
            return
        run.update(status='running', updated_at=now())
        store.save('runs', identity, run)
    try:
        manifest = (runner or run_workflow)(options_for(store, run))
        status = 'complete' if manifest.get('status') in {'complete', 'completed', 'ok'} else 'partial' if manifest.get('status') in {'partial', 'reviewed_requires_resume'} else 'failed'
        error = None if status == 'complete' else 'Workflow ended with ' + str(manifest.get('status', 'unknown'))
    except Exception as exc:
        manifest = getattr(exc, 'manifest', {}) or {}
        status = 'partial' if manifest.get('status') == 'partial' else 'failed'
        # Do not print full exceptions/tracebacks: providers may include secrets.
        error = type(exc).__name__ + ': ' + str(store.redact(str(exc)))[:500]
    with store.lock():
        current = store.read('runs', identity)
        if current['status'] == 'interrupted':
            return
        current.update(status=status, updated_at=now(), error=error, stage_results=manifest.get('stage_results', {}))
        store.save('runs', identity, current)
