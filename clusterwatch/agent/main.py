from __future__ import annotations

import asyncio
import logging
import platform
import random
import socket
import time
from collections.abc import Awaitable, Callable

import httpx

from clusterwatch import __version__
from clusterwatch.agent.telemetry import TelemetryCollector, default_node_id
from clusterwatch.config import AgentSettings

LOGGER = logging.getLogger("clusterwatch.agent")


class Agent:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.node_id = settings.node_id or default_node_id()
        self.collector = TelemetryCollector(
            settings.enable_jetson_telemetry,
            settings.enable_slurm_telemetry,
            settings.slurm_node_name or self.node_id,
        )

    def _client_headers(self) -> dict[str, str]:
        if self.settings.api_key is None:
            return {}
        return {"X-ClusterWatch-Key": self.settings.api_key}

    def _retry_delay(self, failed_attempt: int) -> float:
        exponential = min(
            self.settings.delivery_retry_max_seconds,
            self.settings.delivery_retry_base_seconds * (2 ** (failed_attempt - 1)),
        )
        jitter = self.settings.delivery_retry_jitter
        lower = max(0, exponential * (1 - jitter))
        upper = min(self.settings.delivery_retry_max_seconds, exponential * (1 + jitter))
        return random.uniform(lower, upper)

    @staticmethod
    def _is_retryable(exc: httpx.HTTPError) -> bool:
        if isinstance(exc, httpx.TransportError):
            return True
        return isinstance(exc, httpx.HTTPStatusError) and (
            exc.response.status_code in {408, 425, 429} or exc.response.status_code >= 500
        )

    async def _deliver(
        self,
        description: str,
        request: Callable[[], Awaitable[httpx.Response]],
        allow_not_found: bool = False,
    ) -> httpx.Response:
        for attempt in range(1, self.settings.delivery_max_attempts + 1):
            try:
                response = await request()
                if allow_not_found and response.status_code == 404:
                    return response
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                if attempt == self.settings.delivery_max_attempts or not self._is_retryable(exc):
                    raise
                delay = self._retry_delay(attempt)
                LOGGER.warning(
                    "%s failed (attempt %d/%d); retrying in %.2f seconds",
                    description,
                    attempt,
                    self.settings.delivery_max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError("delivery retry loop exited unexpectedly")

    async def register(self, client: httpx.AsyncClient) -> None:
        payload = {
            "node_id": self.node_id,
            "hostname": socket.gethostname(),
            "labels": {**self.settings.labels, "os": platform.system().lower(), "arch": platform.machine()},
            "capabilities": self.collector.capabilities,
            "agent_version": __version__,
        }
        await self._deliver(
            "Node registration",
            lambda: client.post("/api/v1/nodes/register", json=payload),
        )
        LOGGER.info("Registered node %s with %s", self.node_id, self.settings.controller_url)

    async def send_once(self, client: httpx.AsyncClient) -> None:
        try:
            sample = await asyncio.to_thread(self.collector.collect)
        except Exception as exc:  # the agent must remain alive when one sensor misbehaves
            LOGGER.exception("Metric collection failed")
            payload = {"agent_time": time.time(), "collection_error": str(exc)[:500]}
            response = await self._deliver(
                "Heartbeat delivery",
                lambda: client.post(f"/api/v1/nodes/{self.node_id}/heartbeat", json=payload),
                allow_not_found=True,
            )
        else:
            response = await self._deliver(
                "Telemetry delivery",
                lambda: client.post(f"/api/v1/nodes/{self.node_id}/metrics", json=sample),
                allow_not_found=True,
            )

        if response.status_code == 404:
            await self.register(client)
            return

    async def serve(self) -> None:
        timeout = httpx.Timeout(10)
        async with httpx.AsyncClient(
            base_url=self.settings.controller_url,
            timeout=timeout,
            headers=self._client_headers(),
        ) as client:
            while True:
                try:
                    await self.register(client)
                    break
                except (httpx.HTTPError, OSError):
                    LOGGER.warning("Controller unavailable; retrying in 3 seconds")
                    await asyncio.sleep(3)

            while True:
                started = time.monotonic()
                try:
                    await self.send_once(client)
                except (httpx.HTTPError, OSError):
                    LOGGER.warning("Unable to deliver telemetry; will retry", exc_info=True)
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.1, self.settings.sample_interval_seconds - elapsed))


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(Agent(AgentSettings.from_env()).serve())


if __name__ == "__main__":
    run()
