from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "load_test.py"
SPEC = importlib.util.spec_from_file_location("clusterwatch_load_test", SCRIPT)
assert SPEC and SPEC.loader
load_test = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = load_test
SPEC.loader.exec_module(load_test)

BenchmarkConfig = load_test.BenchmarkConfig
metric_template = load_test.metric_template
parse_args = load_test.parse_args
percentile = load_test.percentile
run_benchmark = load_test.run_benchmark


def test_percentile_interpolates_and_metric_templates_are_reproducible():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert metric_template(7, 2026) == metric_template(7, 2026)
    assert metric_template(7, 2026) != metric_template(8, 2026)


def test_load_test_registers_nodes_sends_auth_and_reports_results():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = 201 if request.url.path.endswith("/register") else 202
        return httpx.Response(status, json={"accepted": True})

    config = BenchmarkConfig(
        url="http://controller.test",
        nodes=3,
        requests=12,
        concurrency=4,
        warmup_requests=3,
        timeout_seconds=1,
        seed=42,
        api_key="secret",
    )
    report = asyncio.run(run_benchmark(config, httpx.MockTransport(handler)))

    assert report["results"]["successful_requests"] == 12
    assert report["results"]["failed_requests"] == 0
    assert report["results"]["latency_ms"]["p99"] >= 0
    assert report["configuration"]["seed"] == 42
    assert "api_key" not in report["configuration"]
    assert len([request for request in requests if request.url.path.endswith("/register")]) == 3
    assert all(request.headers["X-ClusterWatch-Key"] == "secret" for request in requests)


def test_load_test_counts_non_successful_responses():
    metric_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metric_count
        if request.url.path.endswith("/register"):
            return httpx.Response(201)
        metric_count += 1
        return httpx.Response(500 if metric_count == 1 else 202)

    config = BenchmarkConfig(
        url="http://controller.test",
        nodes=1,
        requests=3,
        concurrency=1,
        warmup_requests=0,
        timeout_seconds=1,
        seed=1,
    )
    report = asyncio.run(run_benchmark(config, httpx.MockTransport(handler)))

    assert report["results"]["successful_requests"] == 2
    assert report["results"]["failed_requests"] == 1
    assert report["results"]["errors"] == {"HTTP 500": 1}


def test_cli_rejects_invalid_workload_sizes():
    with pytest.raises(SystemExit):
        parse_args(["--nodes", "0"])
