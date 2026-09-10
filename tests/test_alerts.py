from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from clusterwatch.config import ControllerSettings
from clusterwatch.controller.alerts import AlertManager


def test_warning_and_recovery_webhooks(client, settings, registration, metric):
    client.post("/api/v1/nodes/register", json=registration)
    client.post("/api/v1/nodes/node-01/metrics", json={**metric, "cpu_percent": 95})
    delivered = []

    async def record(_url, payload):
        delivered.append(payload)

    manager = AlertManager(
        client.app.state.store,
        replace(settings, alert_webhook_url="https://alerts.example.test/hook"),
        sender=record,
    )
    asyncio.run(manager.evaluate())
    asyncio.run(manager.evaluate())

    client.post(
        "/api/v1/nodes/node-01/metrics",
        json={**metric, "collected_at": metric["collected_at"] + 1},
    )
    asyncio.run(manager.evaluate())

    assert [item["status"] for item in delivered] == ["WARNING", "HEALTHY"]
    assert delivered[0]["reasons"] == ["CPU 95.0% ≥ 85.0%"]
    assert delivered[1]["previous_status"] == "WARNING"


def test_cooldown_suppresses_flapping_alerts(client, settings, registration, metric):
    now = [100.0]
    delivered = []

    async def record(_url, payload):
        delivered.append(payload["status"])

    manager = AlertManager(
        client.app.state.store,
        replace(
            settings,
            alert_webhook_url="https://alerts.example.test/hook",
            alert_cooldown_seconds=60,
        ),
        sender=record,
        clock=lambda: now[0],
    )
    client.post("/api/v1/nodes/register", json=registration)
    client.post("/api/v1/nodes/node-01/metrics", json={**metric, "cpu_percent": 95})
    asyncio.run(manager.evaluate())

    client.post(
        "/api/v1/nodes/node-01/metrics",
        json={**metric, "collected_at": metric["collected_at"] + 1},
    )
    asyncio.run(manager.evaluate())
    now[0] = 110.0
    client.post(
        "/api/v1/nodes/node-01/metrics",
        json={**metric, "collected_at": metric["collected_at"] + 2, "cpu_percent": 95},
    )
    asyncio.run(manager.evaluate())
    now[0] = 161.0
    asyncio.run(manager.evaluate())

    assert delivered == ["WARNING", "HEALTHY", "WARNING"]


def test_delivery_failure_is_isolated_and_rate_limited(client, settings, registration, metric):
    now = [100.0]
    attempts = []

    async def fail(_url, _payload):
        attempts.append(now[0])
        raise RuntimeError("receiver unavailable")

    manager = AlertManager(
        client.app.state.store,
        replace(
            settings,
            alert_webhook_url="https://alerts.example.test/hook",
            alert_cooldown_seconds=60,
        ),
        sender=fail,
        clock=lambda: now[0],
    )
    client.post("/api/v1/nodes/register", json=registration)
    client.post("/api/v1/nodes/node-01/metrics", json={**metric, "cpu_percent": 95})

    asyncio.run(manager.evaluate())
    now[0] = 120.0
    asyncio.run(manager.evaluate())
    now[0] = 161.0
    asyncio.run(manager.evaluate())

    assert attempts == [100.0, 161.0]


def test_offline_node_sends_webhook(client, settings, registration):
    delivered = []

    async def record(_url, payload):
        delivered.append(payload)

    client.post("/api/v1/nodes/register", json=registration)
    client.app.state.store.heartbeat("node-01", now=time.time() - 2)
    manager = AlertManager(
        client.app.state.store,
        replace(settings, alert_webhook_url="https://alerts.example.test/hook"),
        sender=record,
    )

    asyncio.run(manager.evaluate())

    assert delivered[0]["status"] == "OFFLINE"
    assert delivered[0]["reasons"][0].startswith("No heartbeat")


def test_alert_configuration_is_optional(monkeypatch):
    monkeypatch.delenv("CW_ALERT_WEBHOOK_URL", raising=False)
    assert ControllerSettings.from_env().alert_webhook_url is None

    monkeypatch.setenv("CW_ALERT_WEBHOOK_URL", "https://alerts.example.test/hook")
    monkeypatch.setenv("CW_ALERT_COOLDOWN_SECONDS", "45")
    configured = ControllerSettings.from_env()
    assert configured.alert_webhook_url == "https://alerts.example.test/hook"
    assert configured.alert_cooldown_seconds == 45
