from __future__ import annotations

import sqlite3
import subprocess

from clusterwatch.agent.slurm import SlurmCollector
from clusterwatch.config import AgentSettings
from clusterwatch.controller.store import Store


def test_slurm_collector_parses_node_and_running_jobs(monkeypatch):
    commands = []
    monkeypatch.setattr("clusterwatch.agent.slurm.shutil.which", lambda name: f"/usr/bin/{name}")

    def run(command, **_kwargs):
        commands.append(command)
        if command[0].endswith("scontrol"):
            output = "NodeName=node-01 CPUAlloc=8 CPUTot=32 State=ALLOCATED Reason=None"
        else:
            output = "1234|alice|training|RUNNING\n1235|bob|simulation|RUNNING\n"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr("clusterwatch.agent.slurm.subprocess.run", run)

    telemetry = SlurmCollector(enabled=True, node_name="node-01").collect()

    assert telemetry == {
        "node_name": "node-01",
        "node_state": "ALLOCATED",
        "reason": None,
        "allocated_cpus": 8,
        "total_cpus": 32,
        "running_jobs": [
            {"job_id": "1234", "user": "alice", "name": "training", "state": "RUNNING"},
            {"job_id": "1235", "user": "bob", "name": "simulation", "state": "RUNNING"},
        ],
        "jobs_truncated": False,
    }
    assert commands[0] == ["/usr/bin/scontrol", "--oneliner", "show", "node", "node-01"]
    assert "--nodelist" in commands[1]
    assert "--states=RUNNING" in commands[1]


def test_missing_slurm_commands_are_a_graceful_fallback(monkeypatch):
    monkeypatch.setattr("clusterwatch.agent.slurm.shutil.which", lambda _name: None)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("Slurm commands must not run when unavailable")

    monkeypatch.setattr("clusterwatch.agent.slurm.subprocess.run", unexpected_run)
    collector = SlurmCollector(enabled=True, node_name="node-01")

    assert collector.available is False
    assert collector.collect() is None


def test_slurm_command_failures_do_not_raise(monkeypatch):
    monkeypatch.setattr("clusterwatch.agent.slurm.shutil.which", lambda name: f"/usr/bin/{name}")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("slurm", 2)

    monkeypatch.setattr("clusterwatch.agent.slurm.subprocess.run", timeout)

    assert SlurmCollector(enabled=True, node_name="node-01").collect() is None


def test_slurm_telemetry_round_trips_through_api_and_prometheus(client, registration, metric):
    registration["capabilities"]["slurm"] = True
    metric["slurm"] = {
        "node_name": "node-01",
        "node_state": "ALLOCATED",
        "reason": None,
        "allocated_cpus": 8,
        "total_cpus": 32,
        "running_jobs": [
            {"job_id": "1234", "user": "alice", "name": "training", "state": "RUNNING"}
        ],
        "jobs_truncated": False,
    }
    client.post("/api/v1/nodes/register", json=registration)

    assert client.post("/api/v1/nodes/node-01/metrics", json=metric).status_code == 202
    latest = client.get("/api/v1/nodes/node-01").json()["latest"]
    prometheus = client.get("/metrics").text

    assert latest["slurm"] == metric["slurm"]
    assert 'clusterwatch_node_slurm_cpus{node_id="node-01",hostname="compute-01",kind="allocated"} 8' in prometheus
    assert 'clusterwatch_node_slurm_running_jobs{node_id="node-01",hostname="compute-01"} 1' in prometheus


def test_store_migrates_database_created_before_slurm_support(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE metrics (id INTEGER PRIMARY KEY, node_id TEXT, collected_at REAL)")
    connection.commit()
    connection.close()

    Store(str(database)).close()
    connection = sqlite3.connect(database)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(metrics)")}
    connection.close()

    assert "slurm_json" in columns


def test_slurm_configuration_is_opt_in(monkeypatch):
    monkeypatch.delenv("CW_ENABLE_SLURM_TELEMETRY", raising=False)
    assert AgentSettings.from_env().enable_slurm_telemetry is False

    monkeypatch.setenv("CW_ENABLE_SLURM_TELEMETRY", "true")
    monkeypatch.setenv("CW_SLURM_NODE_NAME", "compute-07")
    settings = AgentSettings.from_env()
    assert settings.enable_slurm_telemetry is True
    assert settings.slurm_node_name == "compute-07"
