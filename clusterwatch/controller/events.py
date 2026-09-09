from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Protocol


class DisconnectAware(Protocol):
    async def is_disconnected(self) -> bool: ...


class EventBroker:
    """Wake connected dashboards when controller state changes."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    async def publish(self) -> None:
        async with self._condition:
            self._revision += 1
            self._condition.notify_all()

    async def wait_for_update(self, revision: int, timeout: float) -> int:
        async with self._condition:
            if self._revision != revision:
                return self._revision
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._revision != revision),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                pass
            return self._revision


def encode_event(revision: int) -> str:
    payload = json.dumps(
        {"revision": revision, "generated_at": time.time()},
        separators=(",", ":"),
    )
    return f"event: cluster-update\ndata: {payload}\n\n"


async def event_stream(
    request: DisconnectAware,
    broker: EventBroker,
    keepalive_seconds: float = 5.0,
) -> AsyncIterator[str]:
    """Emit immediately, after writes, and periodically for liveness aging."""

    revision = broker.revision
    while not await request.is_disconnected():
        yield encode_event(revision)
        revision = await broker.wait_for_update(revision, keepalive_seconds)
