from __future__ import annotations

from pydantic import BaseModel, Field


class Registration(BaseModel):
    node_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    hostname: str = Field(min_length=1, max_length=255)
    labels: dict[str, str] = Field(default_factory=dict)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    agent_version: str = "unknown"


class MetricSample(BaseModel):
    collected_at: float
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    memory_used_bytes: int = Field(ge=0)
    memory_total_bytes: int = Field(gt=0)
    disk_percent: float = Field(ge=0, le=100)
    disk_used_bytes: int = Field(ge=0)
    disk_total_bytes: int = Field(gt=0)
    load_1: float = Field(ge=0)
    load_5: float = Field(ge=0)
    load_15: float = Field(ge=0)
    uptime_seconds: float = Field(ge=0)
    network_rx_bytes_per_sec: float = Field(ge=0)
    network_tx_bytes_per_sec: float = Field(ge=0)
    temperatures_c: dict[str, float] = Field(default_factory=dict)
    gpu: dict[str, float | str | None] = Field(default_factory=dict)


class Heartbeat(BaseModel):
    agent_time: float
    collection_error: str | None = Field(default=None, max_length=500)

