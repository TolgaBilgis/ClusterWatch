from __future__ import annotations

from clusterwatch.agent.telemetry import TelemetryCollector


def test_collector_returns_schema_compatible_linux_metrics():
    sample = TelemetryCollector(enable_jetson=False).collect()
    assert 0 <= sample["cpu_percent"] <= 100
    assert 0 <= sample["memory_percent"] <= 100
    assert sample["memory_total_bytes"] > 0
    assert sample["disk_total_bytes"] > 0
    assert sample["network_rx_bytes_per_sec"] >= 0
    assert sample["gpu"] == {}

