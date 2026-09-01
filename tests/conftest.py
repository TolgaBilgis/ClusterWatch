from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clusterwatch.config import ControllerSettings
from clusterwatch.controller.app import create_app


@pytest.fixture
def settings(tmp_path):
    return ControllerSettings(
        database_path=str(tmp_path / "test.db"),
        offline_timeout_seconds=1.0,
        cpu_warning_percent=85,
        memory_warning_percent=85,
        disk_warning_percent=90,
        temperature_warning_c=80,
        history_retention_days=7,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def registration():
    return {
        "node_id": "node-01",
        "hostname": "compute-01",
        "labels": {"role": "simulated"},
        "capabilities": {"linux_metrics": True, "jetson": False},
        "agent_version": "0.1.0",
    }


@pytest.fixture
def metric():
    return {
        "collected_at": 1_800_000_000.0,
        "cpu_percent": 22.5,
        "memory_percent": 31.2,
        "memory_used_bytes": 2_000_000,
        "memory_total_bytes": 8_000_000,
        "disk_percent": 40.0,
        "disk_used_bytes": 4_000_000,
        "disk_total_bytes": 10_000_000,
        "load_1": 0.2,
        "load_5": 0.3,
        "load_15": 0.4,
        "uptime_seconds": 5000,
        "network_rx_bytes_per_sec": 1200,
        "network_tx_bytes_per_sec": 300,
        "temperatures_c": {"cpu": 45.0},
        "gpu": {},
    }
