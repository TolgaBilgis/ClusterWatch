from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from clusterwatch.agent.main import Agent
from clusterwatch.config import AgentSettings
from clusterwatch.controller.app import create_app


def test_agent_endpoints_require_configured_key(settings, registration, metric):
    with TestClient(create_app(replace(settings, api_key="shared-secret"))) as client:
        protected_requests = (
            ("/api/v1/nodes/register", registration),
            ("/api/v1/nodes/node-01/metrics", metric),
            ("/api/v1/nodes/node-01/heartbeat", {"agent_time": 1_800_000_000}),
        )
        for path, payload in protected_requests:
            assert client.post(path, json=payload).status_code == 401

        assert (
            client.post(
                "/api/v1/nodes/register",
                json=registration,
                headers={"X-ClusterWatch-Key": "wrong-secret"},
            ).status_code
            == 401
        )

        headers = {"X-ClusterWatch-Key": "shared-secret"}
        assert client.post("/api/v1/nodes/register", json=registration, headers=headers).status_code == 201
        assert client.post("/api/v1/nodes/node-01/metrics", json=metric, headers=headers).status_code == 202
        assert (
            client.post(
                "/api/v1/nodes/node-01/heartbeat",
                json={"agent_time": 1_800_000_000},
                headers=headers,
            ).status_code
            == 202
        )


def test_read_only_endpoints_remain_public_when_auth_is_enabled(settings):
    with TestClient(create_app(replace(settings, api_key="shared-secret"))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 200
        assert client.get("/api/v1/nodes").status_code == 200
        assert client.get("/api/v1/config").status_code == 200


def test_agent_adds_configured_key_to_client_headers():
    settings = AgentSettings(
        controller_url="http://controller.test",
        sample_interval_seconds=5,
        node_id="node-01",
        labels={},
        enable_jetson_telemetry=False,
        api_key="shared-secret",
    )
    agent = Agent(settings)
    assert agent._client_headers() == {"X-ClusterWatch-Key": "shared-secret"}
