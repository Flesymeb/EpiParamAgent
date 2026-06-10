from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.models import RunEvent

EventPayload = dict[str, Any]


def serialize_event(event: RunEvent) -> EventPayload:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "step_no": event.step_no,
        "ts": event.ts.isoformat(),
        "level": event.level,
        "message": event.message,
    }


@dataclass(frozen=True)
class _Subscriber:
    queue: asyncio.Queue[EventPayload]
    loop: asyncio.AbstractEventLoop


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[_Subscriber]] = {}
        self._lock = threading.Lock()

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[EventPayload]]:
        subscriber = _Subscriber(
            queue=asyncio.Queue(),
            loop=asyncio.get_running_loop(),
        )
        with self._lock:
            self._subscribers.setdefault(run_id, set()).add(subscriber)

        try:
            yield subscriber.queue
        finally:
            with self._lock:
                subscribers = self._subscribers.get(run_id)
                if subscribers is None:
                    return
                subscribers.discard(subscriber)
                if not subscribers:
                    self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, payload: EventPayload) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(run_id, ()))

        for subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(
                    subscriber.queue.put_nowait,
                    payload,
                )
            except RuntimeError:
                pass


event_hub = EventHub()


def log_event(
    session: Session,
    run_id: str,
    step_no: int | None,
    level: str,
    message: str,
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        step_no=step_no,
        level=level,
        message=message,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    event_hub.publish(run_id, serialize_event(event))
    return event


class StreamToEvents:
    def __init__(
        self,
        session: Session,
        run_id: str,
        step_no: int | None,
        level: str = "info",
    ) -> None:
        self.session = session
        self.run_id = run_id
        self.step_no = step_no
        self.level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def _emit(self, line: str) -> None:
        message = line.rstrip("\r")
        if message:
            log_event(
                self.session,
                self.run_id,
                self.step_no,
                self.level,
                message,
            )

