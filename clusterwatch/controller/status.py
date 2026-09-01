from __future__ import annotations

import time
from typing import Any

from clusterwatch.config import ControllerSettings


def evaluate_status(
    node: dict[str, Any], latest: dict[str, Any] | None, settings: ControllerSettings, now: float | None = None
) -> tuple[str, list[str]]:
    current_time = time.time() if now is None else now
    age = current_time - float(node["last_seen"])
    if age > settings.offline_timeout_seconds:
        return "OFFLINE", [f"No heartbeat for {age:.0f}s"]

    if latest is None:
        if node.get("last_error"):
            return "WARNING", [f"Agent collection error: {node['last_error']}"]
        return "WARNING", ["Waiting for first metric sample"]

    reasons: list[str] = []
    if node.get("last_error"):
        reasons.append(f"Agent collection error: {node['last_error']}")
    checks = (
        (latest["cpu_percent"], settings.cpu_warning_percent, "CPU"),
        (latest["memory_percent"], settings.memory_warning_percent, "Memory"),
        (latest["disk_percent"], settings.disk_warning_percent, "Disk"),
    )
    for value, threshold, label in checks:
        if float(value) >= threshold:
            reasons.append(f"{label} {float(value):.1f}% ≥ {threshold:.1f}%")

    temperatures = latest.get("temperatures_c") or {}
    hot_sensors = [f"{name} {value:.1f}°C" for name, value in temperatures.items() if value >= settings.temperature_warning_c]
    if hot_sensors:
        reasons.append("High temperature: " + ", ".join(hot_sensors))

    gpu_temperature = (latest.get("gpu") or {}).get("temperature_c")
    if isinstance(gpu_temperature, (int, float)) and gpu_temperature >= settings.temperature_warning_c:
        reasons.append(f"GPU {gpu_temperature:.1f}°C ≥ {settings.temperature_warning_c:.1f}°C")

    return ("WARNING", reasons) if reasons else ("HEALTHY", [])
