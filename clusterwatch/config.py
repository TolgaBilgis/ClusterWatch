from __future__ import annotations

import os
from dataclasses import dataclass


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ControllerSettings:
    database_path: str = "./data/clusterwatch.db"
    offline_timeout_seconds: float = 15.0
    cpu_warning_percent: float = 85.0
    memory_warning_percent: float = 85.0
    disk_warning_percent: float = 90.0
    temperature_warning_c: float = 80.0
    history_retention_days: int = 7

    @classmethod
    def from_env(cls) -> "ControllerSettings":
        return cls(
            database_path=os.getenv("CW_DATABASE_PATH", "./data/clusterwatch.db"),
            offline_timeout_seconds=_float("CW_OFFLINE_TIMEOUT_SECONDS", 15),
            cpu_warning_percent=_float("CW_CPU_WARNING_PERCENT", 85),
            memory_warning_percent=_float("CW_MEMORY_WARNING_PERCENT", 85),
            disk_warning_percent=_float("CW_DISK_WARNING_PERCENT", 90),
            temperature_warning_c=_float("CW_TEMPERATURE_WARNING_C", 80),
            history_retention_days=_int("CW_HISTORY_RETENTION_DAYS", 7),
        )


@dataclass(frozen=True)
class AgentSettings:
    controller_url: str
    sample_interval_seconds: float
    node_id: str | None
    labels: dict[str, str]
    enable_jetson_telemetry: bool

    @classmethod
    def from_env(cls) -> "AgentSettings":
        labels: dict[str, str] = {}
        for item in os.getenv("CW_NODE_LABELS", "").split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                labels[key.strip()] = value.strip()
        return cls(
            controller_url=os.getenv("CW_CONTROLLER_URL", "http://127.0.0.1:8000").rstrip("/"),
            sample_interval_seconds=_float("CW_SAMPLE_INTERVAL_SECONDS", 5),
            node_id=os.getenv("CW_NODE_ID") or None,
            labels=labels,
            enable_jetson_telemetry=_bool("CW_ENABLE_JETSON_TELEMETRY", True),
        )

