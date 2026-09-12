#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class BenchmarkConfig:
    url: str
    nodes: int
    requests: int
    concurrency: int
    warmup_requests: int
    timeout_seconds: float
    seed: int
    api_key: str | None = None
    trust_env: bool = False


def percentile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def node_registration(index: int) -> dict[str, Any]:
    node_id = f"loadtest-{index:04d}"
    return {
        "node_id": node_id,
        "hostname": node_id,
        "labels": {"role": "load-test", "index": str(index)},
        "capabilities": {"linux_metrics": True, "temperatures": False, "jetson": False, "slurm": False},
        "agent_version": "load-test",
    }


def metric_template(index: int, seed: int) -> dict[str, Any]:
    randomizer = random.Random(seed + index)
    memory_total = 8 * 1024**3
    disk_total = 128 * 1024**3
    memory_percent = randomizer.uniform(25, 70)
    disk_percent = randomizer.uniform(20, 65)
    return {
        "collected_at": 0.0,
        "cpu_percent": randomizer.uniform(5, 75),
        "memory_percent": memory_percent,
        "memory_used_bytes": int(memory_total * memory_percent / 100),
        "memory_total_bytes": memory_total,
        "disk_percent": disk_percent,
        "disk_used_bytes": int(disk_total * disk_percent / 100),
        "disk_total_bytes": disk_total,
        "load_1": randomizer.uniform(0, 4),
        "load_5": randomizer.uniform(0, 4),
        "load_15": randomizer.uniform(0, 4),
        "uptime_seconds": randomizer.uniform(3600, 864000),
        "network_rx_bytes_per_sec": randomizer.uniform(0, 20_000_000),
        "network_tx_bytes_per_sec": randomizer.uniform(0, 20_000_000),
        "temperatures_c": {},
        "gpu": {},
        "slurm": None,
    }


async def _register_nodes(client: httpx.AsyncClient, count: int) -> None:
    responses = await asyncio.gather(
        *(client.post("/api/v1/nodes/register", json=node_registration(index)) for index in range(count))
    )
    failures = [response.status_code for response in responses if response.status_code != 201]
    if failures:
        raise RuntimeError(f"node registration failed with HTTP status {failures[0]}")


async def _metric_request(
    client: httpx.AsyncClient,
    node_index: int,
    template: dict[str, Any],
) -> tuple[bool, float, str | None]:
    payload = {**template, "collected_at": time.time()}
    started = time.perf_counter()
    try:
        response = await client.post(f"/api/v1/nodes/loadtest-{node_index:04d}/metrics", json=payload)
    except httpx.HTTPError as error:
        return False, (time.perf_counter() - started) * 1000, type(error).__name__
    elapsed_ms = (time.perf_counter() - started) * 1000
    if response.status_code != 202:
        return False, elapsed_ms, f"HTTP {response.status_code}"
    return True, elapsed_ms, None


async def _run_requests(
    client: httpx.AsyncClient,
    templates: list[dict[str, Any]],
    count: int,
    concurrency: int,
) -> list[tuple[bool, float, str | None]]:
    queue: asyncio.Queue[int | None] = asyncio.Queue()
    for request_index in range(count):
        queue.put_nowait(request_index)
    for _ in range(concurrency):
        queue.put_nowait(None)

    results: list[tuple[bool, float, str | None]] = []

    async def worker() -> None:
        while True:
            request_index = await queue.get()
            if request_index is None:
                return
            node_index = request_index % len(templates)
            results.append(await _metric_request(client, node_index, templates[node_index]))

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return results


async def run_benchmark(
    config: BenchmarkConfig,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    headers = {"X-ClusterWatch-Key": config.api_key} if config.api_key else {}
    templates = [metric_template(index, config.seed) for index in range(config.nodes)]
    limits = httpx.Limits(max_connections=config.concurrency, max_keepalive_connections=config.concurrency)
    async with httpx.AsyncClient(
        base_url=config.url.rstrip("/"),
        headers=headers,
        timeout=config.timeout_seconds,
        limits=limits,
        transport=transport,
        trust_env=config.trust_env,
    ) as client:
        await _register_nodes(client, config.nodes)
        warmup = await _run_requests(
            client,
            templates,
            config.warmup_requests,
            min(config.concurrency, max(1, config.warmup_requests)),
        )
        if any(not success for success, _, _ in warmup):
            raise RuntimeError("a warm-up request failed; benchmark was not started")

        started = time.perf_counter()
        results = await _run_requests(client, templates, config.requests, config.concurrency)
        duration = time.perf_counter() - started

    latencies = [latency for success, latency, _ in results if success]
    errors = Counter(error for success, _, error in results if not success and error)
    completed = len(latencies)
    latency_summary = None
    if latencies:
        latency_summary = {
            "mean": round(statistics.fmean(latencies), 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies), 3),
        }
    public_config = {key: value for key, value in asdict(config).items() if key != "api_key"}
    return {
        "benchmark": "clusterwatch-metric-ingestion",
        "started_at": started_at,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "configuration": public_config,
        "results": {
            "duration_seconds": round(duration, 3),
            "requests_per_second": round(completed / duration, 3) if duration else 0,
            "successful_requests": completed,
            "failed_requests": len(results) - completed,
            "errors": dict(sorted(errors.items())),
            "latency_ms": latency_summary,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark ClusterWatch metric ingestion.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="controller base URL")
    parser.add_argument("--nodes", type=int, default=100, help="simulated node count")
    parser.add_argument("--requests", type=int, default=10_000, help="timed metric request count")
    parser.add_argument("--concurrency", type=int, default=32, help="concurrent request workers")
    parser.add_argument("--warmup-requests", type=int, default=500, help="untimed metric requests")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-request timeout in seconds")
    parser.add_argument("--seed", type=int, default=2026, help="deterministic metric seed")
    parser.add_argument("--output", type=Path, help="optional JSON result path")
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="use HTTP proxy and certificate settings from the environment",
    )
    args = parser.parse_args(argv)
    for name in ("nodes", "requests", "concurrency"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if args.warmup_requests < 0:
        parser.error("--warmup-requests cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = BenchmarkConfig(
        url=args.url,
        nodes=args.nodes,
        requests=args.requests,
        concurrency=min(args.concurrency, args.requests),
        warmup_requests=args.warmup_requests,
        timeout_seconds=args.timeout,
        seed=args.seed,
        api_key=os.getenv("CW_API_KEY") or None,
        trust_env=args.trust_env,
    )
    try:
        report = asyncio.run(run_benchmark(config))
    except (httpx.HTTPError, RuntimeError) as error:
        print(f"load test failed: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if report["results"]["failed_requests"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
