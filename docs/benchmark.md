# Controller load-test procedure

The repository includes a repeatable HTTP load driver for the controller's metric-ingestion path. It registers deterministic simulated nodes, performs an untimed warm-up, then reports throughput, successful and failed requests, error groups, and mean, p50, p95, p99, and maximum latency. Results are printed as JSON and can also be saved for later comparison.

## Prepare an isolated controller

Run benchmarks on an otherwise idle machine. Use the same Python version, ClusterWatch revision, hardware, power mode, and command-line arguments for every comparison. A fresh SQLite database prevents previous samples and maintenance activity from affecting a run.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

BENCH_DIR="$(mktemp -d)"
export CW_DATABASE_PATH="$BENCH_DIR/clusterwatch.db"
clusterwatch-controller >"$BENCH_DIR/controller.log" 2>&1 &
CONTROLLER_PID=$!
trap 'kill "$CONTROLLER_PID" 2>/dev/null || true' EXIT

until curl --fail --silent http://127.0.0.1:8000/health >/dev/null; do sleep 0.2; done
```

Do not point the load test at a production controller. It creates node and metric records and is intended to apply sustained write load.

## Run the baseline

From the repository root, run:

```bash
python scripts/load_test.py \
  --url http://127.0.0.1:8000 \
  --nodes 100 \
  --requests 10000 \
  --concurrency 32 \
  --warmup-requests 500 \
  --timeout 5 \
  --seed 2026 \
  --output "$BENCH_DIR/result.json"
```

If agent authentication is enabled, export `CW_API_KEY` before running the script. The key is sent in the same header used by agents and is deliberately excluded from the JSON report.

HTTP proxy variables are ignored by default so a local or private-network benchmark is not routed through an unrelated proxy. Add `--trust-env` only when the target requires proxy or certificate settings from the environment.

The seed fixes generated telemetry values; it does not make operating-system scheduling or network timing deterministic. The script exits with status 1 if any timed request fails and status 2 if setup or warm-up cannot complete.

## Compare changes

Run at least three trials for each revision. Restart the controller with a new temporary directory before every trial, keep all workload arguments unchanged, and compare the median requests per second and p95/p99 latency across trials. Record the commit SHA alongside each result:

```bash
git rev-parse HEAD
python -m json.tool "$BENCH_DIR/result.json"
```

For a remote controller, run the driver from the same client host and network path each time. Test several concurrency levels independently rather than changing concurrency during a run. A useful sweep is 1, 8, 32, and 64 workers with the baseline node and request counts.

Interpret throughput together with failures and tail latency. A higher request rate is not an improvement if error count or p99 latency rises beyond the service's operating requirements. This script measures the complete HTTP and SQLite ingestion path; it is not a microbenchmark of telemetry collection or dashboard rendering.
