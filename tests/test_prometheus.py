from __future__ import annotations

import re

from clusterwatch.controller.prometheus import _escape_label


SAMPLE_PATTERN = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*(?:\{.*\})? (?:[-+]?[0-9.eE]+|NaN|[+-]Inf)$")


def test_metrics_endpoint_exports_latest_node_values(client, registration, metric):
    client.post("/api/v1/nodes/register", json=registration)
    client.post("/api/v1/nodes/node-01/metrics", json=metric)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    assert 'clusterwatch_nodes_total{status="healthy"} 1' in response.text
    assert 'clusterwatch_node_info{node_id="node-01",hostname="compute-01",agent_version="0.1.0"} 1' in response.text
    assert 'clusterwatch_node_cpu_percent{node_id="node-01",hostname="compute-01"} 22.5' in response.text
    assert 'clusterwatch_node_memory_bytes{node_id="node-01",hostname="compute-01",kind="total"} 8000000' in response.text
    assert 'clusterwatch_node_load_average{node_id="node-01",hostname="compute-01",period="15"} 0.4' in response.text
    assert 'clusterwatch_node_temperature_celsius{node_id="node-01",hostname="compute-01",sensor="cpu"} 45.0' in response.text

    for line in response.text.splitlines():
        if not line.startswith("#"):
            assert SAMPLE_PATTERN.fullmatch(line), line


def test_metrics_endpoint_handles_an_empty_cluster(client):
    response = client.get("/metrics")
    assert 'clusterwatch_nodes_total{status="healthy"} 0' in response.text
    assert 'clusterwatch_nodes_total{status="warning"} 0' in response.text
    assert 'clusterwatch_nodes_total{status="offline"} 0' in response.text


def test_prometheus_label_values_are_escaped():
    assert _escape_label('node\\name\n"quoted"') == 'node\\\\name\\n\\"quoted\\"'
