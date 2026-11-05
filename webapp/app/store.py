"""Managed workspace, atomic metadata and server-private runtime configuration."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import yaml

MODULES = ('query', 'screening', 'coding', 'synthesis')
ACTIVE = {'queued', 'running'}
ROOT = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(UTC).isoformat()


def identifier(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', value):
        raise ValueError('Invalid identifier')
    return value


def atomic(path, value, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600 if private else 0o644)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
    temp.replace(path)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._thread_lock = threading.RLock()
        self._lock_state = threading.local()
        self._secret_snapshots = {}
        for folder in ('tasks', 'runs', 'private'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / 'private').chmod(0o700)

    @contextmanager
    def lock(self):
        with self._thread_lock:
            if getattr(self._lock_state, 'held', False):
                yield
                return
            with (self.root / '.lock').open('a') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                self._lock_state.held = True
                try:
                    yield
                finally:
                    self._lock_state.held = False
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def path(self, kind, identity):
        return self.root / kind / identifier(identity)

    def read(self, kind, identity):
        return json.loads((self.path(kind, identity) / 'meta.json').read_text())

    def save(self, kind, identity, value):
        atomic(self.path(kind, identity) / 'meta.json', value)

    def list(self, kind):
        return [json.loads(p.read_text()) for p in sorted((self.root / kind).glob('*/meta.json'), key=lambda p: p.stat().st_mtime, reverse=True)]

    def private_config(self):
        path = self.root / 'private' / 'runtime.json'
        return json.loads(path.read_text()) if path.exists() else {'modules': {}, 'mineru': {}}

    def effective_config(self):
        from metaagent.config import load_llm_config, load_mineru_config
        value = self.private_config()
        modules = {}
        for module in MODULES:
            patch = value.get('modules', {}).get(module, {})
            cfg = load_llm_config({'llm_' + key: val for key, val in patch.items()}, module_hint=module)
            modules[module] = {key: getattr(cfg, key, None) for key in ('provider', 'model', 'api_base', 'thinking', 'timeout_s', 'max_tokens', 'api_key')}
        cfg = load_mineru_config(module_hint='coding')
        mineru = {key: getattr(cfg, key, None) for key in ('base_url', 'endpoint', 'api_key', 'timeout_s')}
        mineru.update(value.get('mineru', {}))
        return {'modules': modules, 'mineru': mineru}

    def secrets(self):
        cfg = self.effective_config()
        values = [m.get('api_key') for m in cfg['modules'].values()] + [cfg['mineru'].get('api_key')]
        # Rotating current settings must not expose an older job's credentials in
        # its logs or provider exception text.
        for path in (self.root / 'private').glob('*.runtime.json'):
            try:
                stamp = (path.stat().st_mtime_ns, path.stat().st_size)
                cached = self._secret_snapshots.get(path)
                if cached is None or cached[0] != stamp:
                    snapshot = json.loads(path.read_text())
                    keys = [m.get('api_key') for m in snapshot.get('modules', {}).values()]
                    keys.append(snapshot.get('mineru', {}).get('api_key'))
                    self._secret_snapshots[path] = (stamp, keys)
                values.extend(self._secret_snapshots[path][1])
            except (OSError, ValueError):
                continue
        return [str(v) for v in values if v and len(str(v)) >= 4]

    def public_config(self):
        from tools.literature.cli import SOURCES
        cfg = self.effective_config()
        for value in [*cfg['modules'].values(), cfg['mineru']]:
            value['api_key_configured'] = bool(value.pop('api_key', None))
        cfg['sources'] = {source: {'available': True} for source in SOURCES}
        return cfg

    def redact(self, value):
        secrets = self.secrets()
        def scrub(item):
            if isinstance(item, dict):
                return {k: scrub(v) for k, v in item.items() if k.lower() not in {'api_key', 'authorization', 'access_token'}}
            if isinstance(item, list):
                return [scrub(v) for v in item]
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, '[REDACTED]')
            return item
        return scrub(value)

    def reject_secrets(self, text):
        if any(secret in text for secret in self.secrets()) or re.search(r'sk-[A-Za-z0-9_-]{12,}', text):
            raise ValueError('Credentials belong in server runtime settings, not task or codebook content')


def validate_task_content(task_yaml, codebook_yaml, task_path):
    from metaagent.workflow_task import ReviewTask
    from metaagent.screening.protocol import validate_protocol
    from metaagent.coding.schema.config_loader import ProjectConfig, create_model_from_config
    from metaagent.synthesis.engine import AnalysisProtocol
    task = yaml.safe_load(task_yaml)
    if not isinstance(task, dict):
        raise ValueError('Task YAML must contain an object')
    task['codebook'] = str((task_path / 'codebook.yaml').resolve())
    parsed = ReviewTask.model_validate(task)
    validate_protocol(parsed.review_protocol)
    from metaagent.config import normalize_api_base
    for runtime in parsed.llm.values():
        if runtime.api_base:
            normalize_api_base(runtime.api_base)
    from tools.literature.cli import SOURCES
    if set(parsed.search) - set(SOURCES):
        raise ValueError('Unsupported search source')
    if parsed.analysis_protocol and parsed.analysis_protocols:
        raise ValueError('Use analysis_protocol or analysis_protocols, not both')
    for protocol in ([parsed.analysis_protocol] if parsed.analysis_protocol else parsed.analysis_protocols):
        AnalysisProtocol.model_validate(protocol)
    book = yaml.safe_load(codebook_yaml)
    if not isinstance(book, dict) or not isinstance(book.get('fields'), list) or not book['fields']:
        raise ValueError('Codebook requires a nonempty fields list')
    # Remote clients cannot instruct the server to import arbitrary Python files.
    for stage in ('stage_a', 'stage_b'):
        if isinstance(book.get(stage), dict) and book[stage].get('prompt_file'):
            raise ValueError('Use editable codebook instructions; external prompt_file imports are not supported')
    supported_types = {'str', 'int', 'float', 'bool', 'list[str]', 'list[int]', 'dict', 'list[dict]'}
    for field in book['fields']:
        if not isinstance(field, dict) or not isinstance(field.get('name'), str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', field['name']):
            raise ValueError('Every codebook field needs a valid name')
        if field.get('type', 'str') not in supported_types:
            raise ValueError('Unsupported codebook field type')
        if 'range' in field and field['range'] is not None and (not isinstance(field['range'], list) or len(field['range']) != 2):
            raise ValueError('Field range must contain two bounds')
    config = ProjectConfig.from_dict(book)
    if len({f.name for f in config.fields}) != len(config.fields):
        raise ValueError('Codebook field names must be unique')
    create_model_from_config(config)
    return yaml.safe_dump(parsed.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False), codebook_yaml


def default_template():
    task = yaml.safe_load((ROOT / 'configs/templates/review_task.yaml').read_text())
    codebook = yaml.safe_load((ROOT / 'configs/mpox/codebooks/incubation_period.yaml').read_text())
    codebook.pop('stage_a', None); codebook.pop('stage_b', None)
    task['codebook'] = 'codebook.yaml'
    return {'name': 'Mpox incubation review', 'task_yaml': yaml.safe_dump(task, allow_unicode=True, sort_keys=False),
            'codebook_yaml': yaml.safe_dump(codebook, allow_unicode=True, sort_keys=False)}
