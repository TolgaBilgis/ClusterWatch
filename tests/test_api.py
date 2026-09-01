from __future__ import annotations

import time


def test_agent_registers_and_submits_metric(client, registration, metric):
    response = client.post("/api/v1/nodes/register", json=registration)
    assert response.status_code == 201

    response = client.post("/api/v1/nodes/node-01/metrics", json=metric)
    assert response.status_code == 202

    node = client.get("/api/v1/nodes/node-01").json()
    assert node["status"] == "HEALTHY"
    assert node["latest"]["cpu_percent"] == 22.5
    assert node["labels"] == {"role": "simulated"}


def test_warning_threshold_is_explained(client, registration, metric):
    client.post("/api/v1/nodes/register", json=registration)
    metric["cpu_percent"] = 91
    client.post("/api/v1/nodes/node-01/metrics", json=metric)

    node = client.get("/api/v1/nodes/node-01").json()
    assert node["status"] == "WARNING"
    assert node["status_reasons"] == ["CPU 91.0% ≥ 85.0%"]


def test_missed_heartbeat_marks_node_offline(client, registration, metric):
    client.post("/api/v1/nodes/register", json=registration)
    client.post("/api/v1/nodes/node-01/metrics", json=metric)
    client.app.state.store.heartbeat("node-01", now=time.time() - 2)

    node = client.get("/api/v1/nodes/node-01").json()
    assert node["status"] == "OFFLINE"
    assert node["status_reasons"][0].startswith("No heartbeat")


def test_metric_requires_registration(client, metric):
    response = client.post("/api/v1/nodes/unknown/metrics", json=metric)
    assert response.status_code == 404


def test_history_is_chronological(client, registration, metric):
    client.post("/api/v1/nodes/register", json=registration)
    current = time.time()
    for offset in (3, 1, 2):
        sample = {**metric, "collected_at": current - offset}
        client.post("/api/v1/nodes/node-01/metrics", json=sample)

    history = client.get("/api/v1/nodes/node-01/metrics?minutes=1").json()["metrics"]
    timestamps = [sample["collected_at"] for sample in history]
    assert timestamps == sorted(timestamps)


def test_heartbeat_preserves_liveness_when_collection_fails(client, registration):
    client.post("/api/v1/nodes/register", json=registration)
    response = client.post(
        "/api/v1/nodes/node-01/heartbeat",
        json={"agent_time": time.time(), "collection_error": "temperature sensor unavailable"},
    )
    assert response.status_code == 202
    node = client.get("/api/v1/nodes/node-01").json()
    assert node["status"] == "WARNING"
    assert node["last_error"] == "temperature sensor unavailable"
    assert node["status_reasons"] == ["Agent collection error: temperature sensor unavailable"]
