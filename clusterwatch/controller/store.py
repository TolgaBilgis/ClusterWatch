from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from clusterwatch.schemas import MetricSample, Registration


class Store:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._lock = threading.RLock()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    address TEXT,
                    labels_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    registered_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                    collected_at REAL NOT NULL,
                    received_at REAL NOT NULL,
                    cpu_percent REAL NOT NULL,
                    memory_percent REAL NOT NULL,
                    memory_used_bytes INTEGER NOT NULL,
                    memory_total_bytes INTEGER NOT NULL,
                    disk_percent REAL NOT NULL,
                    disk_used_bytes INTEGER NOT NULL,
                    disk_total_bytes INTEGER NOT NULL,
                    load_1 REAL NOT NULL,
                    load_5 REAL NOT NULL,
                    load_15 REAL NOT NULL,
                    uptime_seconds REAL NOT NULL,
                    network_rx_bytes_per_sec REAL NOT NULL,
                    network_tx_bytes_per_sec REAL NOT NULL,
                    temperatures_json TEXT NOT NULL,
                    gpu_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_metrics_node_time
                    ON metrics(node_id, collected_at DESC);
                """
            )

    @staticmethod
    def _decode_node(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["labels"] = json.loads(item.pop("labels_json"))
        item["capabilities"] = json.loads(item.pop("capabilities_json"))
        return item

    @staticmethod
    def _decode_metric(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["temperatures_c"] = json.loads(item.pop("temperatures_json"))
        item["gpu"] = json.loads(item.pop("gpu_json"))
        return item

    def register(self, registration: Registration, address: str | None, now: float | None = None) -> dict[str, Any]:
        timestamp = time.time() if now is None else now
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO nodes (
                    node_id, hostname, address, labels_json, capabilities_json,
                    agent_version, registered_at, last_seen, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(node_id) DO UPDATE SET
                    hostname=excluded.hostname,
                    address=excluded.address,
                    labels_json=excluded.labels_json,
                    capabilities_json=excluded.capabilities_json,
                    agent_version=excluded.agent_version,
                    last_seen=excluded.last_seen,
                    last_error=NULL
                """,
                (
                    registration.node_id,
                    registration.hostname,
                    address,
                    json.dumps(registration.labels, sort_keys=True),
                    json.dumps(registration.capabilities, sort_keys=True),
                    registration.agent_version,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_node(registration.node_id)  # type: ignore[return-value]

    def heartbeat(self, node_id: str, error: str | None = None, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else now
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE nodes SET last_seen=?, last_error=? WHERE node_id=?", (timestamp, error, node_id)
            )
        return cursor.rowcount > 0

    def add_metric(self, node_id: str, sample: MetricSample, now: float | None = None) -> bool:
        received_at = time.time() if now is None else now
        values = sample.model_dump()
        with self._lock, self._connection:
            exists = self._connection.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if not exists:
                return False
            self._connection.execute(
                """
                INSERT INTO metrics (
                    node_id, collected_at, received_at, cpu_percent, memory_percent,
                    memory_used_bytes, memory_total_bytes, disk_percent, disk_used_bytes,
                    disk_total_bytes, load_1, load_5, load_15, uptime_seconds,
                    network_rx_bytes_per_sec, network_tx_bytes_per_sec,
                    temperatures_json, gpu_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    values["collected_at"],
                    received_at,
                    values["cpu_percent"],
                    values["memory_percent"],
                    values["memory_used_bytes"],
                    values["memory_total_bytes"],
                    values["disk_percent"],
                    values["disk_used_bytes"],
                    values["disk_total_bytes"],
                    values["load_1"],
                    values["load_5"],
                    values["load_15"],
                    values["uptime_seconds"],
                    values["network_rx_bytes_per_sec"],
                    values["network_tx_bytes_per_sec"],
                    json.dumps(values["temperatures_c"], sort_keys=True),
                    json.dumps(values["gpu"], sort_keys=True),
                ),
            )
            self._connection.execute(
                "UPDATE nodes SET last_seen=?, last_error=NULL WHERE node_id=?", (received_at, node_id)
            )
        return True

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        return self._decode_node(row) if row else None

    def list_nodes(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()
        return [self._decode_node(row) for row in rows]

    def latest_metric(self, node_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM metrics WHERE node_id=? ORDER BY collected_at DESC LIMIT 1", (node_id,)
            ).fetchone()
        return self._decode_metric(row) if row else None

    def metric_history(self, node_id: str, since: float, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM metrics
                WHERE node_id=? AND collected_at>=?
                ORDER BY collected_at DESC LIMIT ?
                """,
                (node_id, since, limit),
            ).fetchall()
        return [self._decode_metric(row) for row in reversed(rows)]

    def prune(self, before: float) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM metrics WHERE collected_at < ?", (before,))
        return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._connection.close()

