"""Isolated Pi 1.3.0 RPC transport; credentials stay in a run-scoped host proxy.

No global Pi configuration is read by this module. RPC acknowledgements and
agent_end are deliberately not completion signals: only agent_settled is final.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from metaagent.config import load_llm_config, merge_thinking_policy, normalize_api_base, resolve_extra_body

PI_VERSION = '1.3.0'
_EXTENSION = Path(__file__).with_name('pi_extension.ts')
_PROJECT = Path(__file__).resolve().parents[2]


def load_synthesis_extra_body(cfg, runtime_overrides: dict | None = None) -> dict:
    """Validate generation-only native options; transport/tool control stays host-owned."""
    body = resolve_extra_body(runtime_overrides, module_hint='synthesis') or {}
    allowed = {'thinking', 'enable_thinking', 'reasoning_effort', 'reasoning_split',
               'chat_template_kwargs', 'tool_stream', 'top_p', 'top_k', 'min_p',
               'repetition_penalty', 'presence_penalty', 'frequency_penalty', 'seed', 'stop'}
    if set(body) - allowed:
        raise ValueError('Synthesis extra body contains forbidden control or unsupported generation fields')
    # Copy/validate finite JSON before returning anything that can be serialized
    # into a public fingerprint. Never hash or publish credentials as options.
    try:
        body = json.loads(json.dumps(body, allow_nan=False))
    except (ValueError, TypeError):
        raise ValueError('Synthesis extra body must contain finite JSON values') from None
    def reject_private(value):
        if isinstance(value, dict):
            if any(re.search(r'api.?key|authorization|password|secret|headers|credential', key, re.I) for key in value):
                raise ValueError('Credentials are forbidden in synthesis generation options')
            for item in value.values():reject_private(item)
        elif isinstance(value, list):
            for item in value:reject_private(item)
        elif isinstance(value, str):
            if re.search(r'\bsk-[A-Za-z0-9_-]{8,}|(?i:Bearer\s+\S+)', value) or (cfg.api_key and len(cfg.api_key)>=8 and cfg.api_key in value):
                raise ValueError('Credentials are forbidden in synthesis generation options')
    reject_private(body)
    if 'thinking' in body:
        native = body['thinking']
        if not isinstance(native, dict) or set(native) - {'type', 'clear_thinking'} or native.get('type') not in {'enabled', 'disabled', 'adaptive'}:
            raise ValueError('Invalid synthesis native thinking options')
        if 'clear_thinking' in native and type(native['clear_thinking']) is not bool:
            raise ValueError('clear_thinking must be boolean')
    if 'enable_thinking' in body and type(body['enable_thinking']) is not bool:
        raise ValueError('enable_thinking must be boolean')
    if 'chat_template_kwargs' in body:
        template = body['chat_template_kwargs']
        if not isinstance(template, dict) or set(template) != {'enable_thinking'} or type(template['enable_thinking']) is not bool:
            raise ValueError('Only boolean enable_thinking is supported in synthesis chat_template_kwargs')
    for field in ('reasoning_split', 'tool_stream'):
        if field in body and type(body[field]) is not bool:
            raise ValueError(field + ' must be boolean')
    body = merge_thinking_policy(body, cfg.thinking) or {}
    if cfg.reasoning_effort and 'reasoning_effort' in body and body['reasoning_effort'] != cfg.reasoning_effort:
        raise ValueError('Explicit reasoning_effort conflicts with synthesis extra body')
    effort = cfg.reasoning_effort or body.get('reasoning_effort')
    if effort is not None and effort not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}:
        raise ValueError('Invalid synthesis reasoning_effort')
    mode = (body.get('thinking') or {}).get('type')
    disabled = mode == 'disabled' or body.get('enable_thinking') is False
    template = body.get('chat_template_kwargs') or {}
    if 'enable_thinking' in template and ((mode in {'enabled', 'disabled'} and template['enable_thinking'] != (mode == 'enabled')) or ('enable_thinking' in body and template['enable_thinking'] != body['enable_thinking'])):
        raise ValueError('Synthesis chat template conflicts with explicit thinking policy')
    if effort is not None and (disabled or template.get('enable_thinking') is False):
        raise ValueError('Disabled thinking is incompatible with reasoning_effort')
    if cfg.reasoning_effort:
        body['reasoning_effort'] = cfg.reasoning_effort
    return body


def synthesis_generation_binding(runtime_overrides: dict | None = None, *, cfg=None) -> dict[str, Any]:
    """Read-only, nonsecret binding of the actual Synthesis generation options."""
    cfg = cfg or load_llm_config(runtime_overrides or {}, module_hint='synthesis')
    extra = load_synthesis_extra_body(cfg, runtime_overrides)
    public = {key: getattr(cfg, key) for key in (
        'provider', 'model', 'api_base', 'thinking', 'reasoning_effort', 'temperature',
        'max_tokens', 'timeout_s', 'verify_ssl', 'force_streaming')}
    public['api_base'] = normalize_api_base(cfg.api_base) if cfg.api_base else None
    public['thinking'] = (extra.get('thinking') or {}).get('type') or public['thinking']
    public['reasoning_effort'] = extra.get('reasoning_effort') or public['reasoning_effort']
    public['extra_body'] = extra
    encoded = json.dumps(public, ensure_ascii=False, allow_nan=False)
    if re.search(r'\bsk-[A-Za-z0-9_-]{8,}|(?i:Bearer\s+\S+)', encoded) or (cfg.api_key and len(cfg.api_key)>=8 and cfg.api_key in encoded):
        raise ValueError('Private credentials cannot appear in public generation metadata')
    return public


def inspect_pi_runtime(command: str | None = None) -> dict[str, Any]:
    """Pure local inspection: no process, network, configuration writes or auth reads."""
    executable = shutil.which(command or 'pi')
    version = None
    metadata_hash = None
    installed_cli_hash = None
    if executable:
        binary = Path(executable).resolve()
        # Managed launcher, then normal npm installation. Only package metadata.
        current = binary.parent.parent / 'install' / 'current-version'
        candidates = []
        if current.is_file():
            selected = current.read_text().strip()
            if re.fullmatch(r'[\w.+-]+', selected):
                candidates.append(current.parent / 'releases' / selected / 'package.json')
        candidates += [parent / 'package.json' for parent in binary.parents]
        for path in candidates:
            if path.is_file():
                try:
                    package = json.loads(path.read_text())
                    if 'pi-coding-agent' in package.get('name', ''):
                        version = package.get('version')
                        metadata_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                        installed = path.parent / 'node_modules/@earendil-works/pi-coding-agent/package.json'
                        if installed.is_file():
                            path = installed
                            package = json.loads(path.read_text())
                            metadata_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                        cli = path.parent / package.get('bin', {}).get('pi', 'dist/bundle/cli.js')
                        if cli.is_file():
                            installed_cli_hash = hashlib.sha256(cli.read_bytes()).hexdigest()
                        break
                except (OSError, ValueError):
                    pass
    bridge_hash = hashlib.sha256(_EXTENSION.read_bytes()).hexdigest() if _EXTENSION.is_file() else None
    public = dict(available=bool(executable and bridge_hash), version=version,
                  compatible=version == PI_VERSION if version else None,
                  executable=executable,
                  executable_sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest() if executable else None,
                  package_sha256=metadata_hash, installed_cli_sha256=installed_cli_hash,
                  extension_path=str(_EXTENSION), extension_sha256=bridge_hash)
    public['fingerprint'] = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
    return public


def validate_pi_runtime(command: str | None = None) -> dict[str, Any]:
    info = inspect_pi_runtime(command)
    if not info['available']:
        raise ValueError('Pi executable or packaged analysis bridge is unavailable')
    if info['compatible'] is False:
        raise ValueError(f'Pi {PI_VERSION} is required; installed version is incompatible')
    return info


def _redact(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {k: '[REDACTED]' if re.search(r'(api.?key|authorization|password|secret)', k, re.I)
                else _redact(v, keys) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, keys) for v in value]
    if isinstance(value, str):
        for key in keys:
            if key:
                value = value.replace(key, '[REDACTED]')
        value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value)
        value = re.sub(r'(?i)Bearer\s+[\w.\-]+', 'Bearer [REDACTED]', value)
    return value


def _write(path: Path, value: Any) -> None:
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.chmod(temp, 0o600)
    temp.replace(path)


class _RunProxy:
    """One-session, loopback-only OpenAI relay. Every provider attempt is visible.

    Reserve the serialized UTF-8 input byte count plus framing overhead before
    sending, and cap completion to remaining budget. Missing provider usage is
    charged conservatively to that reservation and reported as unknown coverage.
    No SDK/provider retries or redirects are performed here.
    """
    def __init__(self, cfg, settings, directory: Path, deadline: float, runtime_overrides: dict | None = None):
        self.cfg, self.settings, self.deadline = cfg, settings, deadline
        self.extra_body = load_synthesis_extra_body(cfg, runtime_overrides)
        self.token = secrets.token_urlsafe(32)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.spent = 0
        self.calls = 0
        self.blocked = None
        self.last_prompt_tokens = 0
        self.last_body_bytes = 0
        self.clients = set()
        self.sockets = set()
        self.workers = set()
        self.path = directory / 'provider_calls.jsonl'
        self.path.touch(mode=0o600)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.path != '/v1/chat/completions' or self.headers.get('Authorization') != 'Bearer ' + owner.token:
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 32 * 1024 * 1024:
                        raise ValueError('Invalid request size')
                    payload = json.loads(self.rfile.read(length))
                    owner.forward(self, payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    owner.record({'type': 'proxy_error', 'error': str(exc)})
                    try:
                        body = b'{"error":{"message":"Analysis transport failed","type":"transport_error"}}'
                        self.send_response(502); self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                    except OSError:
                        pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'

    def record(self, event):
        event = _redact(event, (self.cfg.api_key or '', self.token))
        with self.lock:
            self.events.append(event)
            with self.path.open('a') as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + '\n')

    def _input_bound(self, body_bytes):
        """Estimate the request's input tokens, anchored by the last measured prompt.

        The body length in bytes overstates the token count about fourfold, so
        charging bytes against a token budget stopped sessions that were well
        inside their limit. The byte estimate stays as a floor at three bytes
        per token, and the measured prompt anchors the growth, so a provider
        that under-reports usage cannot widen the budget.
        """
        floor = body_bytes / 3
        if self.last_prompt_tokens:
            anchored = self.last_prompt_tokens + max(0, body_bytes - self.last_body_bytes) / 3
            return int(max(floor, anchored)) + 512
        return int(floor) + 512

    def forward(self, handler, payload):
        import httpx
        from metaagent import llm_rate_limit as pacing

        if not isinstance(payload, dict):
            raise ValueError('Provider payload must be an object')
        # Proxy owns model/generation identity; never accept a model substitution.
        if payload.get('model') != self.cfg.model:
            raise ValueError('Unexpected model')
        payload = dict(payload)
        payload.pop('max_completion_tokens', None)
        body_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
        input_bound = self._input_bound(body_bytes)
        with self.lock:
            remaining = self.settings['max_tokens'] - self.spent
            cap = min(self.cfg.max_tokens, remaining - input_bound)
            reason = ('max_turns' if self.calls >= self.settings['max_turns'] else
                      'max_tokens' if cap <= 0 else 'deadline' if time.monotonic() >= self.deadline or self.stop.is_set() else None)
            if reason:
                self.blocked = reason
            else:
                self.calls += 1
                call_id = self.calls
                reservation = input_bound + cap
                self.spent += reservation
        if reason:
            self.record({'type': 'budget_blocked', 'reason': reason, 'forwarded': False})
            body = b'{"error":{"message":"Analysis budget exhausted","type":"budget_exceeded"}}'
            handler.send_response(429); handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', str(len(body))); handler.end_headers(); handler.wfile.write(body)
            return
        payload['max_tokens'] = cap
        payload['temperature'] = self.cfg.temperature
        if self.cfg.reasoning_effort:
            payload['reasoning_effort'] = self.cfg.reasoning_effort
        payload.update(self.extra_body)
        payload = merge_thinking_policy(payload, self.cfg.thinking)
        if payload.get('stream'):
            payload['stream_options'] = {'include_usage': True}
        event = {'type': 'provider_attempt', 'call_id': call_id, 'model': self.cfg.model,
                 'request_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                 'max_output_tokens': cap, 'input_token_upper_bound': input_bound,
                 'started_at': time.time(), 'usage': None, 'forwarded': False,
                 'queue_wait_s': 0.0, 'wire_elapsed_s': None, 'wire_timeout_s': self.cfg.timeout_s}
        started = time.monotonic()
        self.record({**event, 'phase': 'started'})
        response_bytes = bytearray()
        worker = threading.current_thread()
        with self.lock:
            self.workers.add(worker)
        try:
            rate = pacing._settings()
            if rate:
                interval, path = rate
                while delay := pacing._try_grant(interval, path):
                    if self.stop.wait(min(delay, .2)) or time.monotonic() >= self.deadline:
                        raise TimeoutError('Analysis transport deadline while pacing')
            if self.stop.is_set() or time.monotonic() >= self.deadline:
                raise TimeoutError('Analysis transport cancelled before forwarding')
            event['queue_wait_s'] = time.monotonic() - started
            timeout = max(.001, min(self.cfg.timeout_s, self.deadline - time.monotonic()))
            event['wire_timeout_s'] = timeout
            wire_started = time.monotonic()
            wire_deadline = min(self.deadline, wire_started + timeout)
            with httpx.Client(verify=self.cfg.verify_ssl, timeout=timeout, follow_redirects=False) as client:
                with self.lock:
                    self.clients.add(client)
                event['forwarded'] = True
                self.record({**event, 'phase': 'forwarded'})
                with client.stream('POST', normalize_api_base(self.cfg.api_base) + '/chat/completions',
                                   headers={'Authorization': 'Bearer ' + (self.cfg.api_key or '')}, json=payload) as response:
                    stream = response.extensions.get('network_stream')
                    upstream_socket = stream.get_extra_info('socket') if stream else None
                    if upstream_socket:
                        with self.lock:
                            self.sockets.add(upstream_socket)
                    event['http_status'] = response.status_code
                    if rate:
                        pacing._cooldown(response, rate[1])
                    handler.send_response(response.status_code)
                    handler.send_header('Content-Type', response.headers.get('content-type', 'application/json'))
                    handler.send_header('Connection', 'close'); handler.end_headers()
                    for chunk in response.iter_bytes():
                        if self.stop.is_set() or time.monotonic() >= self.deadline:
                            raise TimeoutError('Analysis stream deadline exceeded')
                        if time.monotonic() >= wire_deadline:
                            raise TimeoutError('Upstream wire deadline exceeded after forwarding')
                        response_bytes.extend(chunk)
                        if len(response_bytes) > 64 * 1024 * 1024:
                            raise ValueError('Provider response exceeds transport limit')
                        handler.wfile.write(chunk); handler.wfile.flush()
            event['response_sha256'] = hashlib.sha256(response_bytes).hexdigest()
            candidates = []
            try:
                candidates.append(json.loads(response_bytes))
            except (ValueError, UnicodeError):
                for line in response_bytes.split(b'\n'):
                    if line.startswith(b'data: '):
                        try:
                            candidates.append(json.loads(line[6:]))
                        except (ValueError, UnicodeError):
                            pass
            for item in candidates:
                if item.get('usage'):
                    event['usage'] = item['usage']
            event['observed_models'] = sorted({item['model'] for item in candidates if isinstance(item.get('model'), str)})
            usage = event['usage']
            if usage and isinstance(usage.get('total_tokens'), int) and not isinstance(usage['total_tokens'], bool) and usage['total_tokens'] >= 0:
                with self.lock:
                    self.spent += usage['total_tokens'] - reservation
                    prompt_tokens = usage.get('prompt_tokens')
                    if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) and prompt_tokens > 0:
                        self.last_prompt_tokens = prompt_tokens
                        self.last_body_bytes = body_bytes
                    if usage['total_tokens'] > reservation:
                        self.blocked = 'provider_exceeded_token_reservation'
                        event['token_reservation_exceeded'] = True
        except Exception as exc:
            event['error'] = str(exc)
            raise
        finally:
            if event['forwarded']:
                event['wire_elapsed_s'] = time.monotonic() - wire_started
            else:
                event['queue_wait_s'] = time.monotonic() - started
                # A request never forwarded cannot incur provider token usage.
                # Keep the local attempt/cap audit but release its reservation.
                with self.lock:
                    self.spent -= reservation
                event['token_reservation_released'] = reservation
            event.update(phase='finished', elapsed_s=time.monotonic() - started)
            self.record(event)
            with self.lock:
                self.workers.discard(worker)
                if 'client' in locals():
                    self.clients.discard(client)
                if 'upstream_socket' in locals():
                    self.sockets.discard(upstream_socket)

    def close(self):
        import socket
        self.stop.set()
        with self.lock:
            sockets, clients, workers = list(self.sockets), list(self.clients), list(self.workers)
        # Closing from another thread alone need not interrupt a blocking recv;
        # shutdown does. Only sockets created for this isolated run are touched.
        for connection in sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        until = time.monotonic() + 2
        for worker in workers:
            worker.join(timeout=max(0, until - time.monotonic()))
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _positive(settings, name, default, *, integer=False):
    import math
    value = settings.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be positive')
    if integer and int(value) != value:
        raise ValueError(f'{name} must be an integer')
    return int(value) if integer else float(value)


def _completion_progress(workspace: Path) -> dict[str, Any]:
    """Inspect committed tool artifacts, never promote an assistant text claim."""
    from .execution import file_sha
    final = workspace / 'final_result.json'
    if final.is_file():
        try:
            # Only revalidate an already published tool result. This cannot
            # create a final result from a plan, prose or an unexecuted number.
            from .pi_tools import finalize
            value = json.loads(final.read_text())
            finalize(workspace, {'execution_id': value['execution_id']})
            return {'state': 'finalized', 'terminal': True}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    plan_path = workspace / 'analysis_plan.json'
    try:
        plan = json.loads(plan_path.read_text())
        commit = json.loads((workspace / 'plan_commit.json').read_text())
        if commit != {'plan_sha256': file_sha(plan_path),
                      'selection_sha256': file_sha(workspace / 'analysis_selection.jsonl')}:
            raise ValueError('Plan publication is incomplete')
        if plan.get('reproduction_status') in {'protocol_pending', 'not_computable'}:
            return {'state': plan['reproduction_status'], 'terminal': True}
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'missing_plan', 'action': 'save_plan', 'terminal': False}
    try:
        current = json.loads((workspace / 'code/current.json').read_text())
        code = (workspace / current['path']).resolve()
        if not code.is_relative_to(workspace) or not code.is_file():
            raise ValueError('Missing workspace code')
        bindings = {'plan_sha256': file_sha(plan_path), 'code_sha256': file_sha(code),
                    'input_sha256': file_sha(workspace / 'inputs/table.jsonl'),
                    'workspace_sha256': file_sha(workspace / 'workspace.json')}
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'missing_code', 'action': 'write_code', 'terminal': False}
    for path in sorted((workspace / 'receipts').glob('*.json')):
        try:
            receipt = json.loads(path.read_text())
            if receipt.get('validation_status') == 'verified' and all(receipt.get(k) == v for k, v in bindings.items()):
                return {'state': 'missing_finalize', 'action': 'finalize',
                        'execution_id': receipt['execution_id'], 'terminal': False}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {'state': 'missing_verified_execution', 'action': 'run_code', 'terminal': False}


def run_pi_session(workspace: Path, prompt: str, settings: dict,
                   runtime_overrides: dict | None = None, *,
                   completion_guard: bool = False) -> dict[str, Any]:
    """Run one real, isolated RPC session using only the project's analysis tool.

    Public settings: pi_command, max_turns (12), max_tokens (64000 aggregate),
    total_timeout_s (900), exec_timeout_s (120), optional session_path to continue.
    Runtime overrides use shared load_llm_config keys, scoped to synthesis.
    Returns a diagnostic result for provider/RPC/deadline failures; invalid local
    configuration raises ValueError before launching a model request. With the
    opt-in completion guard, at most three same-session continuation prompts
    request missing analysis tools using the original proxy budgets/deadline.
    """
    import uuid
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError('Analysis workspace must already exist')
    # A pre-existing symlink must not redirect private configuration/session
    # writes to global ~/.pi or to another run's workspace.
    for private_path in (workspace / 'pi', workspace / 'pi/attempts', workspace / 'pi/sessions'):
        if private_path.is_symlink() or not private_path.resolve().is_relative_to(workspace):
            raise ValueError('Private Pi directories must stay within the analysis workspace')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('Analysis prompt must be nonempty')
    options = {
        'max_turns': _positive(settings, 'max_turns', 12, integer=True),
        'max_tokens': _positive(settings, 'max_tokens', 64000, integer=True),
        'total_timeout_s': _positive(settings, 'total_timeout_s', 900),
        'exec_timeout_s': _positive(settings, 'exec_timeout_s', 120),
    }
    info = validate_pi_runtime(settings.get('pi_command'))
    cfg = load_llm_config(runtime_overrides or {}, module_hint='synthesis')
    if not cfg.model or not cfg.api_base or not cfg.api_key:
        raise ValueError('Synthesis model, API base and API key must be configured')
    normalize_api_base(cfg.api_base)
    generation = synthesis_generation_binding(runtime_overrides, cfg=cfg)
    continuation = settings.get('session_path')
    if continuation:
        continuation = Path(continuation).resolve()
        if not continuation.is_file() or not continuation.is_relative_to(workspace / 'pi'):
            raise ValueError('Continuation session must be an existing private workspace Pi session')
    directory = workspace / 'pi' / 'attempts' / uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    private = directory / 'agent'
    private.mkdir(mode=0o700)
    sessions = workspace / 'pi' / 'sessions'
    sessions.mkdir(mode=0o700, exist_ok=True)
    events_path, stderr_path = directory / 'events.jsonl', directory / 'stderr.log'
    events_path.touch(mode=0o600); stderr_path.touch(mode=0o600)
    started = time.monotonic()
    deadline = started + options['total_timeout_s']
    proxy = _RunProxy(cfg, options, directory, deadline, runtime_overrides=runtime_overrides)
    secret_values = (cfg.api_key, proxy.token)
    # Never inherit provider credentials, tracing tokens, NODE_OPTIONS or Pi paths.
    allowed = ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    env.update(PI_CODING_AGENT_DIR=str(private), PI_OFFLINE='1',
               METAAGENT_PI_PROXY_KEY=proxy.token,
               METAAGENT_SYNTHESIS_WORKSPACE=str(workspace),
               METAAGENT_SYNTHESIS_PYTHON=sys.executable,
               METAAGENT_SYNTHESIS_PROJECT=str(_PROJECT),
               METAAGENT_SYNTHESIS_TOOL_TIMEOUT=str(min(options['total_timeout_s'], options['exec_timeout_s'] * 2 + 15)))
    _write(private / 'models.json', {'providers': {'metaagent-synthesis': {
        'baseUrl': proxy.url, 'api': 'openai-completions', 'apiKey': '${METAAGENT_PI_PROXY_KEY}',
        'models': [{'id': cfg.model, 'name': cfg.model, 'reasoning': False, 'input': ['text'],
                    'contextWindow': options['max_tokens'], 'maxTokens': min(cfg.max_tokens, options['max_tokens']),
                    'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}],
    }}})
    # Pi speaks only to our loopback relay. Its wait must cover local pacing,
    # while the relay separately caps the upstream wire with cfg.timeout_s.
    # The original session deadline remains the hard cap for both phases.
    local_timeout_ms = max(1, int(options['total_timeout_s'] * 1000))
    _write(private / 'settings.json', {'retry': {'enabled': False, 'maxRetries': 0,
                                               'provider': {'maxRetries': 0, 'timeoutMs': local_timeout_ms}},
                                      'compaction': {'enabled': False}, 'httpIdleTimeoutMs': local_timeout_ms})
    command = [info['executable'], '--mode', 'rpc', '--provider', 'metaagent-synthesis', '--model', cfg.model,
               '--thinking', 'off', '--no-builtin-tools', '--no-extensions', '-e', str(_EXTENSION),
               '--tools', 'epi_tool', '--no-context-files', '--no-skills', '--no-prompt-templates',
               '--no-mcp', '--offline', '--no-approve', '--no-themes', '--session-dir', str(sessions),
               '--system-prompt', 'You are an epidemiological synthesis agent. Use only epi_tool for data, evidence, planning, code execution and finalization. Never invent analysis results or access external files. A final answer requires a successful finalize tool result.']
    if continuation:
        command += ['--session', str(continuation)]
    _write(directory / 'transport_manifest.json', {
        'pi': info, 'settings': options, 'model': cfg.model, 'provider': cfg.provider,
        'api_base': cfg.api_base, 'thinking': cfg.thinking, 'max_output_tokens': cfg.max_tokens,
        'generation_binding': generation,
        'temperature': cfg.temperature, 'session_continuation': str(continuation) if continuation else None,
        'command': command, 'automatic_retries': False, 'credential_storage': 'host_memory_only',
        'tool_actions': ['profile', 'read_skill', 'query', 'evidence', 'save_plan', 'write_code', 'run_code', 'finalize'],
        'completion_guard': {'enabled': completion_guard, 'max_continuations': 3},
        'timeout_policy': {'local_relay_wait_s': options['total_timeout_s'],
                           'upstream_wire_timeout_s': cfg.timeout_s,
                           'queue_deadline': 'original_session_deadline',
                           'automatic_queue_retries': False},
    })
    records: queue.Queue = queue.Queue()
    process = None
    threads = []
    usage_messages = []
    nudges = []
    completion = {'enabled': completion_guard, 'state': 'not_checked'}
    texts = []
    tools = []
    session_path = str(continuation) if continuation else None
    status, error, settled = 'failed', None, False
    abort_reason = None
    actual_version = None
    journal_lock = threading.Lock()

    def journal(record):
        clean = _redact(record, secret_values)
        with journal_lock:
            with events_path.open('a') as handle:
                handle.write(json.dumps(clean, ensure_ascii=False) + '\n')
        return clean

    def consume(stream, kind):
        try:
            for line in iter(stream.readline, b''):
                if kind == 'stderr':
                    with stderr_path.open('a') as handle:
                        handle.write(_redact(line.decode('utf-8', errors='replace'), secret_values))
                else:
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError('RPC record is not an object')
                        records.put(('event', journal(event)))
                    except ValueError:
                        records.put(('error', 'Pi emitted invalid RPC JSON'))
                        return
        finally:
            if kind == 'stdout':
                records.put(('eof', None))

    def send(payload, *, until=None):
        journal({'type': 'client_command', **payload})
        data = memoryview(json.dumps(payload, ensure_ascii=False).encode() + b'\n')
        until = deadline if until is None else until
        while data:
            if time.monotonic() >= until:
                raise TimeoutError('Pi RPC stdin deadline exceeded')
            _, writable, _ = select.select([], [process.stdin.fileno()], [], min(.1, max(.001, until-time.monotonic())))
            if writable:
                try:
                    written = os.write(process.stdin.fileno(), data)
                    data = data[written:]
                except BlockingIOError:
                    pass

    def next_event(until):
        while time.monotonic() < until:
            try:
                kind, event = records.get(timeout=min(.1, max(.001, until - time.monotonic())))
            except queue.Empty:
                continue
            if kind != 'event':
                raise RuntimeError(event or 'Pi exited before settlement')
            return event
        raise TimeoutError('Pi session deadline exceeded')

    try:
        version = subprocess.run([info['executable'], '--version'], env=env, cwd=directory,
                                 capture_output=True, timeout=min(10, options['total_timeout_s']), check=True)
        actual_version = version.stdout.decode().strip()
        if actual_version != PI_VERSION:
            raise ValueError(f'Pi {PI_VERSION} is required')
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=directory, env=env, start_new_session=True)
        os.set_blocking(process.stdin.fileno(), False)
        for stream, kind in ((process.stdout, 'stdout'), (process.stderr, 'stderr')):
            thread = threading.Thread(target=consume, args=(stream, kind), daemon=True)
            thread.start(); threads.append(thread)
        # Explicitly await setup acknowledgements before sending a prompt.
        for payload in ({'id': 'retry-off', 'type': 'set_auto_retry', 'enabled': False},
                        {'id': 'compact-off', 'type': 'set_auto_compaction', 'enabled': False},
                        {'id': 'state', 'type': 'get_state'}):
            send(payload)
            while True:
                event = next_event(deadline)
                if event.get('type') == 'response' and event.get('id') == payload['id']:
                    if not event.get('success'):
                        raise RuntimeError(event.get('error', 'Pi setup failed'))
                    if payload['id'] == 'state':
                        session_path = event.get('data', {}).get('sessionFile') or session_path
                    break
        send({'id': 'analysis-prompt', 'type': 'prompt', 'message': prompt})
        while True:
            event = next_event(deadline)
            kind = event.get('type')
            if kind == 'response' and (event.get('id') == 'analysis-prompt' or str(event.get('id', '')).startswith('completion-nudge-')):
                if not event.get('success'):
                    raise RuntimeError(event.get('error', 'Pi prompt rejected'))
                if event.get('data', {}).get('disposition') == 'handled':
                    raise RuntimeError('Pi handled the prompt without starting analysis')
            elif kind == 'message_end' and event.get('message', {}).get('role') == 'assistant':
                message = event['message']
                usage_messages.append({'model': message.get('model'), 'provider': message.get('provider'),
                                       'usage': message.get('usage'), 'stop_reason': message.get('stopReason')})
                texts.append(''.join(block.get('text', '') for block in message.get('content', []) if block.get('type') == 'text'))
                if message.get('stopReason') in {'error', 'aborted'}:
                    error = message.get('errorMessage') or 'Pi provider response failed'
            elif kind and kind.startswith('tool_execution_'):
                tools.append(event)
            elif kind == 'agent_settled':
                settled = True
                status = 'aborted' if event.get('aborted') else 'failed' if error else 'complete'
                if not completion_guard or status != 'complete':
                    break
                # Never hide an upstream failure behind a second prompt or a
                # fresh provider budget. All continuations reuse this proxy.
                with proxy.lock:
                    failed_provider = any(e.get('type') == 'provider_attempt' and
                        (e.get('error') or (e.get('http_status') or 0) >= 400) for e in proxy.events)
                    exhausted = ('max_turns' if proxy.calls >= options['max_turns'] else
                                 'max_tokens' if proxy.spent >= options['max_tokens'] else None)
                if proxy.blocked or failed_provider:
                    if failed_provider:
                        status, error = 'failed', 'Provider attempt failed; completion continuation was not attempted'
                    break
                completion = {'enabled': True, **_completion_progress(workspace)}
                journal({'type': 'completion_check', **completion})
                if completion['terminal']:
                    break
                # Tool/execution budgets are workspace-wide, unlike this RPC
                # provider budget. Do not spend more model calls asking for a
                # tool that the existing worker budget will necessarily reject.
                limits_path = workspace / 'run_settings.json'
                if limits_path.is_file():
                    limits = json.loads(limits_path.read_text())
                    history = workspace / 'tool_events.jsonl'
                    tool_count = sum(1 for _ in history.open()) if history.is_file() else 0
                    if tool_count >= int(limits.get('max_tool_calls', 80)):
                        exhausted = 'max_tool_calls'
                    elif completion['action'] == 'run_code' and len(list((workspace / 'receipts').glob('*.json'))) >= 2 * int(limits.get('max_executions', 3)):
                        exhausted = 'max_executions'
                if exhausted:
                    status, abort_reason = 'budget_exceeded', exhausted
                    break
                if time.monotonic() >= deadline or proxy.stop.is_set():
                    status, abort_reason = 'timeout', 'deadline'
                    break
                if len(nudges) >= 3:
                    status, error = 'incomplete', 'Completion continuation limit reached without a verified final result or committed pending plan'
                    break
                action = completion['action']
                message = ('The analysis is not complete: ' + completion['state'] +
                    '. Continue this same workspace with epi_tool action ' + action +
                    '. Use the existing tool schema, source evidence and actual input/execution IDs. '
                    'Call the tool instead of promising to do it in text. Do not invent numbers, '
                    'IDs or scientific assumptions. If the analysis cannot be justified, use '
                    'save_plan to record an honest protocol_pending or not_computable plan.')
                if action == 'finalize':
                    message += ' The matching verified execution_id is ' + str(completion['execution_id']) + '.'
                nudge = {'type': 'completion_nudge', 'index': len(nudges)+1,
                         'state': completion['state'], 'action': action,
                         'provider_calls_so_far': proxy.calls, 'charged_tokens_so_far': proxy.spent}
                nudges.append(journal(nudge))
                settled = False
                send({'id': 'completion-nudge-' + str(len(nudges)), 'type': 'prompt', 'message': message})
        if proxy.blocked:
            status = 'budget_exceeded'
            abort_reason = proxy.blocked
    except TimeoutError as exc:
        status, abort_reason, error = 'timeout', 'deadline', str(exc)
    except Exception as exc:
        error = str(exc)
    finally:
        proxy.stop.set()
        if process is not None:
            if not settled and process.poll() is None:
                try:
                    send({'id': 'abort', 'type': 'abort'}, until=time.monotonic() + .2)
                    # Keep draining/auditing while allowing an orderly abort.
                    until = time.monotonic() + 2
                    while time.monotonic() < until:
                        event = next_event(until)
                        if event.get('type') == 'agent_settled':
                            settled = True
                            break
                except (OSError, RuntimeError, TimeoutError):
                    pass
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
            for thread in threads:
                thread.join(timeout=2)
            for stream in (process.stdout, process.stderr):
                stream.close()
        proxy.close()
    # Include interrupted/incomplete attempts too; a missing final event must
    # never turn a real provider request into a zero-call success receipt.
    with proxy.lock:
        snapshot = list(proxy.events)
    attempts_by_id = {}
    for event in snapshot:
        if event.get('type') == 'provider_attempt' and event.get('forwarded'):
            attempts_by_id[event['call_id']] = event
    attempts = list(attempts_by_id.values())
    import math
    def valid_count(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
    known = [e['usage'] for e in attempts if isinstance(e.get('usage'), dict)]
    totals = {key: sum(u[key] for u in known if valid_count(u.get(key))) for key in keys}
    complete_usage = sum(all(valid_count(u.get(key)) for key in keys) for u in known)
    coverage = 'complete' if attempts and complete_usage == len(attempts) else 'partial' if known else 'unknown'
    result = _redact({
        'status': status, 'pi_version': actual_version, 'runtime_fingerprint': info['fingerprint'],
        'session_path': session_path, 'events_path': str(events_path), 'stderr_path': str(stderr_path),
        'provider_calls_path': str(proxy.path), 'attempt_dir': str(directory),
        'assistant_text': '\n'.join(t for t in texts if t), 'assistant_messages': usage_messages,
        'tool_events': tools, 'usage': {'coverage': coverage, 'provider_attempts': len(attempts),
                                      'incomplete_attempts': sum(e.get('phase') != 'finished' for e in attempts),
                                      'known_subtotal': totals, 'total_tokens': totals['total_tokens'] if coverage == 'complete' else None},
        'settled': settled, 'abort_reason': abort_reason, 'error': error,
        'completion': {**completion, 'max_continuations': 3, 'continuations': nudges},
        'elapsed_s': time.monotonic() - started, 'model': cfg.model,
        'observed_models': sorted({model for attempt in attempts for model in attempt.get('observed_models', [])}),
        'budget': {**options, 'charged_tokens': proxy.spent},
    }, secret_values)
    _write(directory / 'pi_result.json', result)
    return result
