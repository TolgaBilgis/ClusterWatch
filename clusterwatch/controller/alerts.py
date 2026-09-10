from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from clusterwatch.config import ControllerSettings
from clusterwatch.controller.status import evaluate_status
from clusterwatch.controller.store import Store


AlertSender = Callable[[str, dict[str, Any]], Awaitable[None]]
logger = logging.getLogger(__name__)


async def send_webhook(url: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"User-Agent": "ClusterWatch/0.1"},
        )
        response.raise_for_status()


class AlertManager:
    def __init__(
        self,
        store: Store,
        settings: ControllerSettings,
        sender: AlertSender = send_webhook,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._settings = settings
        self._sender = sender
        self._clock = clock
        self._wake = asyncio.Event()
        self._active_alerts: set[str] = set()
        self._delivered_status: dict[str, str] = {}
        self._last_attempt: dict[tuple[str, str], float] = {}

    @property
    def enabled(self) -> bool:
        return self._settings.alert_webhook_url is not None

    def notify(self) -> None:
        if self.enabled:
            self._wake.set()

    async def run(self) -> None:
        while True:
            self._wake.clear()
            await self.evaluate()
            try:
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self._settings.alert_check_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def evaluate(self) -> None:
        if not self.enabled:
            return
        nodes = await asyncio.to_thread(self._store.list_nodes)
        for node in nodes:
            latest = await asyncio.to_thread(self._store.latest_metric, node["node_id"])
            status, reasons = evaluate_status(node, latest, self._settings, now=self._clock())
            await self._evaluate_node(node, latest, status, reasons)

    async def _evaluate_node(
        self,
        node: dict[str, Any],
        latest: dict[str, Any] | None,
        status: str,
        reasons: list[str],
    ) -> None:
        node_id = node["node_id"]
        if status == "WARNING" and latest is None and not node.get("last_error"):
            return

        if status == "HEALTHY":
            if node_id not in self._active_alerts:
                return
        else:
            self._active_alerts.add(node_id)

        if self._delivered_status.get(node_id) == status:
            return

        now = self._clock()
        cooldown_key = (node_id, status)
        last_attempt = self._last_attempt.get(cooldown_key)
        if last_attempt is not None and now - last_attempt < self._settings.alert_cooldown_seconds:
            return
        self._last_attempt[cooldown_key] = now

        payload = {
            "event": "node_status_changed",
            "node_id": node_id,
            "hostname": node["hostname"],
            "status": status,
            "previous_status": self._delivered_status.get(node_id),
            "reasons": reasons,
            "observed_at": now,
        }
        try:
            await self._sender(self._settings.alert_webhook_url or "", payload)
        except Exception as error:
            logger.warning("Alert delivery failed for node %s (%s)", node_id, type(error).__name__)
            return

        self._delivered_status[node_id] = status
        if status == "HEALTHY":
            self._active_alerts.discard(node_id)
