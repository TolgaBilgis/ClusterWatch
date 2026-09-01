from __future__ import annotations

import glob
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil


class TelemetryCollector:
    """Collect Linux telemetry, with optional best-effort NVIDIA Jetson data."""

    def __init__(self, enable_jetson: bool = True):
        network = psutil.net_io_counters()
        self._last_network = (network.bytes_recv, network.bytes_sent, time.monotonic())
        self.enable_jetson = enable_jetson
        self._tegrastats = shutil.which("tegrastats") if enable_jetson else None
        psutil.cpu_percent(interval=None)

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "linux_metrics": True,
            "temperatures": bool(self._read_temperatures()),
            "jetson": bool(self._tegrastats or self._jetson_gpu_load_path()),
        }

    def collect(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        get_load_average = getattr(os, "getloadavg", psutil.getloadavg)
        load_1, load_5, load_15 = get_load_average()
        network = psutil.net_io_counters()
        now_monotonic = time.monotonic()
        previous_rx, previous_tx, previous_time = self._last_network
        elapsed = max(now_monotonic - previous_time, 0.001)
        self._last_network = (network.bytes_recv, network.bytes_sent, now_monotonic)

        temperatures = self._read_temperatures()
        gpu = self._read_jetson_gpu(temperatures) if self.enable_jetson else {}
        return {
            "collected_at": time.time(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": memory.percent,
            "memory_used_bytes": memory.used,
            "memory_total_bytes": memory.total,
            "disk_percent": disk.percent,
            "disk_used_bytes": disk.used,
            "disk_total_bytes": disk.total,
            "load_1": load_1,
            "load_5": load_5,
            "load_15": load_15,
            "uptime_seconds": max(0, time.time() - psutil.boot_time()),
            "network_rx_bytes_per_sec": max(0, network.bytes_recv - previous_rx) / elapsed,
            "network_tx_bytes_per_sec": max(0, network.bytes_sent - previous_tx) / elapsed,
            "temperatures_c": temperatures,
            "gpu": gpu,
        }

    @staticmethod
    def _read_temperatures() -> dict[str, float]:
        readings: dict[str, float] = {}
        try:
            for group, sensors in psutil.sensors_temperatures().items():
                for index, sensor in enumerate(sensors):
                    label = sensor.label or f"sensor-{index}"
                    readings[f"{group}/{label}"] = round(float(sensor.current), 1)
        except (AttributeError, OSError):
            pass

        if readings:
            return readings
        for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
            try:
                zone_path = Path(zone)
                label = (zone_path / "type").read_text().strip()
                raw = float((zone_path / "temp").read_text().strip())
                readings[label] = round(raw / 1000 if raw > 1000 else raw, 1)
            except (OSError, ValueError):
                continue
        return readings

    @staticmethod
    def _jetson_gpu_load_path() -> str | None:
        candidates = [
            "/sys/devices/gpu.0/load",
            "/sys/devices/platform/host1x/17000000.gpu/load",
        ]
        return next((path for path in candidates if Path(path).exists()), None)

    def _read_jetson_gpu(self, temperatures: dict[str, float]) -> dict[str, float | str | None]:
        gpu: dict[str, float | str | None] = {}
        load_path = self._jetson_gpu_load_path()
        if load_path:
            try:
                raw = float(Path(load_path).read_text().strip())
                gpu["utilization_percent"] = round(raw / 10 if raw > 100 else raw, 1)
                gpu["source"] = "sysfs"
            except (OSError, ValueError):
                pass

        if self._tegrastats:
            output = self._sample_tegrastats()
            utilization = re.search(r"GR3D_FREQ\s+(\d+(?:\.\d+)?)%", output)
            gpu_temp = re.search(r"GPU@(-?\d+(?:\.\d+)?)C", output)
            if utilization:
                gpu["utilization_percent"] = float(utilization.group(1))
            if gpu_temp:
                gpu["temperature_c"] = float(gpu_temp.group(1))
            if output:
                gpu["source"] = "tegrastats"

        if "temperature_c" not in gpu:
            for name, value in temperatures.items():
                if "gpu" in name.lower():
                    gpu["temperature_c"] = value
                    break
        return gpu

    def _sample_tegrastats(self) -> str:
        if not self._tegrastats:
            return ""
        process = subprocess.Popen(
            [self._tegrastats, "--interval", "200"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            output, _ = process.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                output, _ = process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
        return next((line for line in output.splitlines() if line.strip()), "")


def default_node_id() -> str:
    return os.getenv("HOSTNAME") or socket.gethostname()
