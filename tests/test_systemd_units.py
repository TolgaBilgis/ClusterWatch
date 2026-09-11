from __future__ import annotations

import configparser
from pathlib import Path


SYSTEMD_DIR = Path(__file__).resolve().parents[1] / "deploy" / "systemd"


def load_unit(name: str) -> configparser.ConfigParser:
    unit = configparser.ConfigParser(interpolation=None, strict=True)
    assert unit.read(SYSTEMD_DIR / name)
    return unit


def test_controller_unit_uses_persistent_storage_and_environment():
    unit = load_unit("clusterwatch-controller.service")
    service = unit["Service"]

    assert service["User"] == "clusterwatch"
    assert service["EnvironmentFile"] == "/etc/clusterwatch/controller.env"
    assert service["ExecStart"] == "/opt/clusterwatch/venv/bin/clusterwatch-controller"
    assert service["WorkingDirectory"] == "/var/lib/clusterwatch"
    assert service["ReadWritePaths"] == "/var/lib/clusterwatch"
    assert service["Restart"] == "on-failure"
    assert unit["Install"]["WantedBy"] == "multi-user.target"


def test_agent_unit_restarts_and_uses_agent_environment():
    unit = load_unit("clusterwatch-agent.service")
    service = unit["Service"]

    assert service["User"] == "clusterwatch"
    assert service["EnvironmentFile"] == "/etc/clusterwatch/agent.env"
    assert service["ExecStart"] == "/opt/clusterwatch/venv/bin/clusterwatch-agent"
    assert service["Restart"] == "always"
    assert unit["Install"]["WantedBy"] == "multi-user.target"


def test_environment_templates_cover_required_service_settings():
    controller = (SYSTEMD_DIR / "controller.env.example").read_text()
    agent = (SYSTEMD_DIR / "agent.env.example").read_text()

    assert "CW_DATABASE_PATH=/var/lib/clusterwatch/clusterwatch.db" in controller
    assert "CW_CONTROLLER_URL=http://127.0.0.1:8000" in agent
    assert "CW_ENABLE_JETSON_TELEMETRY=true" in agent
    assert "CW_ENABLE_SLURM_TELEMETRY=false" in agent
    assert "CW_API_KEY=" in controller
    assert "CW_ALERT_WEBHOOK_URL=" in controller
    assert "CW_API_KEY=" in agent
