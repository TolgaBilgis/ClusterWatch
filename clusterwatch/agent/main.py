from __future__ import annotations

import asyncio
import logging
import platform
import socket
import time

import httpx

from clusterwatch import __version__
from clusterwatch.agent.telemetry import TelemetryCollector, default_node_id
from clusterwatch.config import AgentSettings

LOGGER = logging.getLogger("clusterwatch.agent")


class Agent:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.node_id = settings.node_id or default_node_id()
        self.collector = TelemetryCollector(settings.enable_jetson_telemetry)

    async def register(self, client: httpx.AsyncClient) -> None:
        payload = {
            "node_id": self.node_id,
            "hostname": socket.gethostname(),
            "labels": {**self.settings.labels, "os": platform.system().lower(), "arch": platform.machine()},
            "capabilities": self.collector.capabilities,
            "agent_version": __version__,
        }
        response = await client.post("/api/v1/nodes/register", json=payload)
        response.raise_for_status()
        LOGGER.info("Registered node %s with %s", self.node_id, self.settings.controller_url)

    async def send_once(self, client: httpx.AsyncClient) -> None:
        try:
            sample = await asyncio.to_thread(self.collector.collect)
        except Exception as exc:  # the agent must remain alive when one sensor misbehaves
            LOGGER.exception("Metric collection failed")
            response = await client.post(
                f"/api/v1/nodes/{self.node_id}/heartbeat",
                json={"agent_time": time.time(), "collection_error": str(exc)[:500]},
            )
        else:
            response = await client.post(f"/api/v1/nodes/{self.node_id}/metrics", json=sample)

        if response.status_code == 404:
            await self.register(client)
            return
        response.raise_for_status()

    async def serve(self) -> None:
        timeout = httpx.Timeout(10)
        async with httpx.AsyncClient(base_url=self.settings.controller_url, timeout=timeout) as client:
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

