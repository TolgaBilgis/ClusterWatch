from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(values: dict[str, object]) -> str:
    if not values:
        return ""
    rendered = ",".join(f'{key}="{_escape_label(value)}"' for key, value in values.items())
    return "{" + rendered + "}"


def _number(value: int | float) -> str:
    number = float(value)
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "+Inf" if number > 0 else "-Inf"
    return str(value)


def _family(
    name: str,
    description: str,
    samples: Iterable[tuple[dict[str, object], int | float]],
) -> list[str]:
    lines = [f"# HELP {name} {description}", f"# TYPE {name} gauge"]
    lines.extend(f"{name}{_labels(labels)} {_number(value)}" for labels, value in samples)
    return lines


def _node_labels(node: dict[str, Any]) -> dict[str, object]:
    return {"node_id": node["node_id"], "hostname": node["hostname"]}


def render_metrics(nodes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    statuses = ("healthy", "warning", "offline")
    lines.extend(
        _family(
            "clusterwatch_nodes_total",
            "Number of registered nodes by current status.",
            (({"status": status}, sum(node["status"].lower() == status for node in nodes)) for status in statuses),
        )
    )

    lines.extend(
        _family(
            "clusterwatch_node_info",
            "Static information about a registered node.",
            (
                (
                    {
                        **_node_labels(node),
                        "agent_version": node["agent_version"],
                    },
                    1,
                )
                for node in nodes
            ),
        )
    )
    lines.extend(
        _family(
            "clusterwatch_node_status",
            "Current status of a node as a labeled value.",
            (({**_node_labels(node), "status": node["status"].lower()}, 1) for node in nodes),
        )
    )
    lines.extend(
        _family(
            "clusterwatch_node_heartbeat_age_seconds",
            "Seconds since the controller last heard from a node.",
            ((_node_labels(node), node["heartbeat_age_seconds"]) for node in nodes),
        )
    )

    latest_nodes = [node for node in nodes if node.get("latest") is not None]
    scalar_metrics = (
        ("cpu_percent", "clusterwatch_node_cpu_percent", "Latest node CPU utilization percentage."),
        ("memory_percent", "clusterwatch_node_memory_percent", "Latest node memory utilization percentage."),
        ("disk_percent", "clusterwatch_node_disk_percent", "Latest node disk utilization percentage."),
        ("uptime_seconds", "clusterwatch_node_uptime_seconds", "Latest reported node uptime in seconds."),
    )
    for field, name, description in scalar_metrics:
        lines.extend(
            _family(
                name,
                description,
                ((_node_labels(node), node["latest"][field]) for node in latest_nodes),
            )
        )

    lines.extend(
        _family(
            "clusterwatch_node_memory_bytes",
            "Latest node memory bytes by kind.",
            (
                ({**_node_labels(node), "kind": kind}, node["latest"][f"memory_{kind}_bytes"])
                for node in latest_nodes
                for kind in ("used", "total")
            ),
        )
    )
    lines.extend(
        _family(
            "clusterwatch_node_disk_bytes",
            "Latest node disk bytes by kind.",
            (
                ({**_node_labels(node), "kind": kind}, node["latest"][f"disk_{kind}_bytes"])
                for node in latest_nodes
                for kind in ("used", "total")
            ),
        )
    )
    lines.extend(
        _family(
            "clusterwatch_node_load_average",
            "Latest node load average by period.",
            (
                ({**_node_labels(node), "period": period}, node["latest"][f"load_{period}"])
                for node in latest_nodes
                for period in ("1", "5", "15")
            ),
        )
    )
    lines.extend(
        _family(
            "clusterwatch_node_network_bytes_per_second",
            "Latest node network throughput by direction.",
            (
                ({**_node_labels(node), "direction": direction}, node["latest"][f"network_{direction}_bytes_per_sec"])
                for node in latest_nodes
                for direction in ("rx", "tx")
            ),
        )
    )
    lines.extend(
        _family(
            "clusterwatch_node_temperature_celsius",
            "Latest node temperature by sensor in degrees Celsius.",
            (
                ({**_node_labels(node), "sensor": sensor}, value)
                for node in latest_nodes
                for sensor, value in node["latest"]["temperatures_c"].items()
            ),
        )
    )

    gpu_fields = (
        ("utilization_percent", "clusterwatch_node_gpu_utilization_percent", "Latest GPU utilization percentage."),
        ("temperature_c", "clusterwatch_node_gpu_temperature_celsius", "Latest GPU temperature in degrees Celsius."),
    )
    for field, name, description in gpu_fields:
        lines.extend(
            _family(
                name,
                description,
                (
                    (_node_labels(node), node["latest"]["gpu"][field])
                    for node in latest_nodes
                    if isinstance(node["latest"]["gpu"].get(field), (int, float))
                ),
            )
        )

    return "\n".join(lines) + "\n"
