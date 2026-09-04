from __future__ import annotations

import asyncio

import httpx
import pytest

from clusterwatch.agent.main import Agent
from clusterwatch.config import AgentSettings


def make_agent(**overrides) -> Agent:
    values = {
        "controller_url": "http://controller.test",
        "sample_interval_seconds": 5,
        "node_id": "node-01",
        "labels": {},
        "enable_jetson_telemetry": False,
        "delivery_max_attempts": 4,
        "delivery_retry_base_seconds": 0.5,
        "delivery_retry_max_seconds": 2.0,
        "delivery_retry_jitter": 0.2,
    }
    values.update(overrides)
    return Agent(AgentSettings(**values))


def test_registration_retries_transient_failures(monkeypatch):
    attempts = 0
    sleeps = []
    jitter_ranges = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts < 3 else 204, request=request)

    async def record_sleep(delay):
        sleeps.append(delay)

    def choose_upper(lower, upper):
        jitter_ranges.append((lower, upper))
        return upper

    monkeypatch.setattr("clusterwatch.agent.main.asyncio.sleep", record_sleep)
    monkeypatch.setattr("clusterwatch.agent.main.random.uniform", choose_upper)

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://controller.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            await make_agent().register(client)

    asyncio.run(exercise())

    assert attempts == 3
    assert jitter_ranges == [(0.4, 0.6), (0.8, 1.2)]
    assert sleeps == [0.6, 1.2]


def test_delivery_stops_after_configured_attempts(monkeypatch):
    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("controller unavailable", request=request)

    async def no_wait(_delay):
        return None

    monkeypatch.setattr("clusterwatch.agent.main.asyncio.sleep", no_wait)

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://controller.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(httpx.ConnectError):
                await make_agent(delivery_max_attempts=3).register(client)

    asyncio.run(exercise())

    assert attempts == 3


def test_delivery_does_not_retry_permanent_client_error(monkeypatch):
    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, request=request)

    async def unexpected_sleep(_delay):
        pytest.fail("permanent errors must not be retried")

    monkeypatch.setattr("clusterwatch.agent.main.asyncio.sleep", unexpected_sleep)

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://controller.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await make_agent().register(client)

    asyncio.run(exercise())

    assert attempts == 1
