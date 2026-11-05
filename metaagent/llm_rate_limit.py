"""Opt-in, process-shared HTTP request pacing and provider Retry-After cooldown.

The state contains scheduling times only, never credentials, prompts or responses.
Use one state path for all workflows sharing an account-wide provider quota.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import json
import math
import os
from pathlib import Path
import tempfile
import time


def _settings():
    raw = os.environ.get('METAAGENT_LLM_REQUESTS_PER_MINUTE', '').strip()
    if not raw:
        return None
    try:
        rpm = float(raw)
    except ValueError:
        raise ValueError('METAAGENT_LLM_REQUESTS_PER_MINUTE must be positive') from None
    if not math.isfinite(rpm) or rpm <= 0:
        raise ValueError('METAAGENT_LLM_REQUESTS_PER_MINUTE must be positive')
    path = Path(os.environ.get('METAAGENT_LLM_RATE_STATE_PATH') or
                str(Path(tempfile.gettempdir()) / f'metaagent-llm-rate-{os.getuid()}.json')).expanduser().resolve()
    return 60.0 / rpm, path


@contextmanager
def _state(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # The same inode is locked and updated in place; atomic rename would break
    # inter-process exclusion for clients already holding the old inode.
    with path.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            content = handle.read()
            data = json.loads(content) if content else {}
            yield data
            handle.seek(0)
            handle.truncate()
            json.dump(data, handle)
            handle.flush()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _try_grant(interval, path):
    with _state(path) as state:
        now = time.time()
        slot = max(now, float(state.get('next_request_at', 0)), float(state.get('cooldown_until', 0)))
        if slot <= now:
            # Grant against actual send time. Reserving a future slot and
            # accepting it after a late wake-up can cause catch-up bursts.
            state['next_request_at'] = now + interval
            state['interval_seconds'] = interval
            return 0.0
        return slot - now


def _gate(interval, path):
    while delay := _try_grant(interval, path):
        time.sleep(delay)


def _cooldown(response, path):
    if response.status_code not in {429, 503}:
        return
    raw = response.headers.get('retry-after') or response.headers.get('x-ratelimit-reset')
    if not raw:
        return
    try:
        seconds = float(raw)
        # A reset header may contain an absolute Unix timestamp.
        if seconds > 1_000_000_000:
            seconds -= time.time()
    except ValueError:
        try:
            date = parsedate_to_datetime(raw)
            date = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return
    if not math.isfinite(seconds) or seconds < 0:
        return
    with _state(path) as state:
        state['cooldown_until'] = max(float(state.get('cooldown_until', 0)), time.time() + seconds)
        state['last_throttle_status'] = response.status_code


def httpx_event_hooks():
    settings = _settings()
    if settings is None:
        return {}
    interval, path = settings
    return {'request': [lambda request: _gate(interval, path)],
            'response': [lambda response: _cooldown(response, path)]}


def async_httpx_event_hooks():
    settings = _settings()
    if settings is None:
        return {}
    interval, path = settings

    async def request_hook(request):
        # Do not occupy a thread while queued: a saturated request queue must
        # still allow a response hook to publish provider cooldown promptly.
        while delay := await asyncio.to_thread(_try_grant, interval, path):
            await asyncio.sleep(delay)

    async def response_hook(response):
        await asyncio.to_thread(_cooldown, response, path)

    return {'request': [request_hook], 'response': [response_hook]}
