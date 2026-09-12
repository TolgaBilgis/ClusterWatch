# ClusterWatch

**A lightweight distributed Linux monitoring platform for a real NVIDIA Jetson and a cluster of containerized nodes.**

[![Tests](https://github.com/TolgaBilgis/ClusterWatch/actions/workflows/test.yml/badge.svg)](https://github.com/TolgaBilgis/ClusterWatch/actions/workflows/test.yml)

ClusterWatch demonstrates the control-plane mechanics behind infrastructure monitoring: node registration, periodic telemetry, heartbeats, failure detection, health policy, time-series history, and a centralized dashboard. It is intentionally small enough to understand end-to-end and structured so the same agent can later run on additional physical Linux machines.

![ClusterWatch architecture](docs/architecture.svg)

## What it does

- Runs a native agent on a Jetson for real host, thermal, and NVIDIA GPU telemetry.
- Scales containerized agents as simulated nodes with distinct IDs and network identities.
- Marks nodes `HEALTHY`, `WARNING`, or `OFFLINE` from controller-side evidence.
- Stores metric history in SQLite and exposes it through a documented FastAPI API.
- Shows a responsive cluster overview and per-node charts, with no frontend build step.
- Handles sensor failures separately from liveness: a failed collection sends a heartbeat carrying the error.
- Retries transient delivery failures with bounded exponential backoff and jitter.
- Optionally authenticates agent writes with a shared API key.
- Exposes current cluster and node telemetry in Prometheus text format.
- Streams controller changes to the dashboard with a polling fallback.
- Sends optional status-change webhooks with per-node cooldown protection.
- Optionally reports Slurm node allocation and running-job telemetry.
- Includes a reproducible controller ingestion benchmark with JSON results.

## Dashboard

The dashboard is available at `http://localhost:8000` after startup. It receives server-sent events after agent writes and includes cluster-wide status counts, per-node summary cards, one-hour CPU/memory/network charts, disk usage, load average, uptime, labels, sensor temperatures, and Jetson GPU readings. Browsers without EventSource support, or connections interrupted by a proxy or network failure, automatically fall back to five-second polling while SSE reconnects.

![Cluster overview dashboard](docs/dashboard.png)

![Per-node telemetry and history](docs/node-detail.png)

## Architecture

```text
Jetson agent ─────┐
                  ├── REST metrics / heartbeat ──> FastAPI controller ──> SQLite
Docker agent × N ─┘                                      │
                                                        └── Dashboard + REST API
```

Each agent chooses a stable `node_id`, registers metadata and capabilities, and pushes a metric sample on a configurable interval. The controller records its own receipt time, so agent clock drift cannot keep a dead node online. A metric submission is also a heartbeat. If collection itself fails, the agent sends the dedicated heartbeat endpoint with a bounded error message.

Status is evaluated when the API is read:

1. `OFFLINE` if the controller has not received a heartbeat within the timeout.
2. `WARNING` if the newest sample crosses a configured threshold, the agent reported a collection error, or no sample exists yet.
3. `HEALTHY` otherwise.

This avoids a per-node timer and ensures status is derived consistently after controller restarts.

## Quick start: simulated cluster

Requirements: Docker Engine with the Compose plugin.

```bash
git clone https://github.com/TolgaBilgis/ClusterWatch.git
cd clusterwatch
docker compose up --build --scale agent=5
```

Open [http://localhost:8000](http://localhost:8000). The OpenAPI explorer is at [http://localhost:8000/docs](http://localhost:8000/docs).

To test failure detection, list the containers and stop one agent:

```bash
docker compose ps
docker stop <one-agent-container-name>
```

After `CW_OFFLINE_TIMEOUT_SECONDS` (15 seconds by default), that node changes to `OFFLINE`. Start the container again and it re-registers and recovers automatically.

Compose intentionally does not set `container_name`; Docker assigns every scaled agent a unique hostname, which becomes its default node ID. All simulated agents ultimately share the Jetson kernel and hardware. They validate distributed coordination and failure handling—not performance scaling.

## Add the physical Jetson agent

Run the controller and simulated agents with Docker, then run one agent **on the Jetson host**. A host process has the cleanest access to `/sys` thermal sensors and `tegrastats`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

export CW_CONTROLLER_URL=http://127.0.0.1:8000
export CW_NODE_ID=jetson-main
export CW_NODE_LABELS=role=physical,accelerator=jetson
export CW_ENABLE_JETSON_TELEMETRY=true
export CW_API_KEY=replace-with-a-long-random-value
clusterwatch-agent
```

For another physical Linux machine, install the same package, set `CW_CONTROLLER_URL` to the Jetson's LAN address (for example `http://192.168.1.20:8000`), choose a unique node ID, and start `clusterwatch-agent`. No controller change is required.

For a persistent host installation, use the provided systemd services and the [Linux and Jetson installation guide](docs/install-linux.md). The controller and agent run as a dedicated unprivileged account, restart after failures, start at boot, and load secrets and settings from protected environment files.

For repeatable multi-node installation, use the [Ansible playbook](docs/ansible.md). Its inventory supports separate controller and agent machines or a Jetson that runs both roles.

### Jetson telemetry behavior

The collector uses layers of best-effort detection:

1. Standard Linux metrics from `psutil`.
2. Temperatures from `psutil` or `/sys/class/thermal`.
3. Jetson GPU load from the NVIDIA sysfs interface when present.
4. GPU utilization and temperature parsed from `tegrastats` when it is on `PATH`.

Non-Jetson Linux hosts and containers simply return an empty GPU object. Missing vendor telemetry never prevents ordinary metrics from being reported.

### Slurm telemetry

Set `CW_ENABLE_SLURM_TELEMETRY=true` on an agent whose host has Slurm client commands configured. The agent uses `scontrol` to report node state, reason, allocated CPUs, and total CPUs, and `squeue` to report up to 100 running jobs allocated to that node. If the Slurm `NodeName` differs from `CW_NODE_ID`, set `CW_SLURM_NODE_NAME` explicitly.

The collector has no Slurm library dependency. Each probe can return partial data independently; if neither command succeeds, the agent sends `slurm: null`. Missing commands, controller outages, permission errors, nonzero exits, and command timeouts never interrupt Linux or Jetson telemetry. Collected data appears in the node API and detail dashboard; CPU allocation and running-job count are also exported through `/metrics`. Job names and usernames are visible through the read-only API, so protect the controller network when that metadata is sensitive.

## Configuration

Copy `.env.example` to `.env` to customize Compose. Every setting is an environment variable.

| Variable | Default | Used by | Purpose |
|---|---:|---|---|
| `CW_CONTROLLER_URL` | `http://127.0.0.1:8000` | agent | Controller base URL |
| `CW_NODE_ID` | hostname | agent | Stable, unique node identity |
| `CW_NODE_LABELS` | empty | agent | Comma-separated `key=value` metadata |
| `CW_SAMPLE_INTERVAL_SECONDS` | `5` | agent | Collection and delivery interval |
| `CW_ENABLE_JETSON_TELEMETRY` | `true` | agent | Enable NVIDIA Jetson probes |
| `CW_ENABLE_SLURM_TELEMETRY` | `false` | agent | Enable best-effort `scontrol` and `squeue` probes |
| `CW_SLURM_NODE_NAME` | node ID | agent | Slurm node name when it differs from the agent ID |
| `CW_DELIVERY_MAX_ATTEMPTS` | `4` | agent | Maximum attempts for each registration or delivery |
| `CW_DELIVERY_RETRY_BASE_SECONDS` | `0.5` | agent | Initial retry delay before exponential growth |
| `CW_DELIVERY_RETRY_MAX_SECONDS` | `5` | agent | Upper bound for each retry delay |
| `CW_DELIVERY_RETRY_JITTER` | `0.2` | agent | Random delay variation from `0` to `1` |
| `CW_API_KEY` | unset | both | Shared key required for agent write requests when set |
| `CW_DATABASE_PATH` | `./data/clusterwatch.db` | controller | SQLite database file |
| `CW_OFFLINE_TIMEOUT_SECONDS` | `15` | controller | Missed-heartbeat deadline |
| `CW_CPU_WARNING_PERCENT` | `85` | controller | CPU warning threshold |
| `CW_MEMORY_WARNING_PERCENT` | `85` | controller | RAM warning threshold |
| `CW_DISK_WARNING_PERCENT` | `90` | controller | Disk warning threshold |
| `CW_TEMPERATURE_WARNING_C` | `80` | controller | Sensor/GPU warning threshold |
| `CW_HISTORY_RETENTION_DAYS` | `7` | controller | Metric retention window |
| `CW_ALERT_WEBHOOK_URL` | unset | controller | JSON webhook for status changes |
| `CW_ALERT_COOLDOWN_SECONDS` | `300` | controller | Minimum time between repeated alerts for one node and status |
| `CW_ALERT_CHECK_INTERVAL_SECONDS` | `5` | controller | Interval for detecting nodes that become offline |

A practical rule is to keep the offline timeout at least two or three times the sample interval to avoid false positives during brief scheduling or network delays.

Agents retry connection failures, timeouts, HTTP `408`, `425`, `429`, and server errors. Other client errors fail immediately. The retry count is bounded per sample so a prolonged outage does not block fresh telemetry forever; after the attempts are exhausted, the regular sampling loop continues.

### Agent authentication

Authentication is disabled when `CW_API_KEY` is unset, preserving the default trusted-LAN setup. To enable it, generate a strong random value and set the same `CW_API_KEY` on the controller and every agent. Compose passes the value to both services from `.env`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

When enabled, registration, metric, and heartbeat requests must include the key in the `X-ClusterWatch-Key` header. Read-only dashboard routes and `/health` remain public. Treat the key as a secret: do not commit a populated `.env` file, and use TLS or a trusted private network because the header itself is not encrypted.

### Alert webhooks

Set `CW_ALERT_WEBHOOK_URL` on the controller to receive an HTTP `POST` when a node enters `WARNING` or `OFFLINE`, and again when it recovers to `HEALTHY`. New registrations waiting for their first sample do not create alerts. The JSON body contains `event`, `node_id`, `hostname`, `status`, `previous_status`, `reasons`, and `observed_at` fields.

`CW_ALERT_COOLDOWN_SECONDS` suppresses repeated delivery for the same node and status during flapping. Failed requests are logged, do not reject agent telemetry, and are not attempted again until the cooldown expires. Keep credentials in the webhook URL out of version control and use an HTTPS receiver.

## API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/nodes/register` | Register or refresh agent metadata |
| `POST` | `/api/v1/nodes/{id}/metrics` | Store a sample and update heartbeat |
| `POST` | `/api/v1/nodes/{id}/heartbeat` | Preserve liveness after collection failure |
| `GET` | `/api/v1/nodes` | Cluster summary and latest samples |
| `GET` | `/api/v1/nodes/{id}` | Node status and current data |
| `GET` | `/api/v1/nodes/{id}/metrics` | Bounded historical series |
| `GET` | `/api/v1/config` | Public health-policy configuration |
| `GET` | `/api/v1/events` | Server-sent dashboard update notifications |
| `GET` | `/metrics` | Prometheus-compatible current metrics |
| `GET` | `/health` | Controller health probe |

FastAPI generates the exact schemas and an interactive client at `/docs`.

### Prometheus scraping

The controller exposes a dependency-free Prometheus text endpoint at `http://localhost:8000/metrics`. It includes node status counts, heartbeat age, identity, CPU, memory, disk, load averages, network throughput, uptime, temperatures, numeric Jetson GPU readings, and optional Slurm allocation summaries. The endpoint exports the latest received sample rather than historical rows.

Add the controller to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: clusterwatch
    scrape_interval: 5s
    static_configs:
      - targets: ["clusterwatch-controller:8000"]
```

When Prometheus runs outside the Compose network, replace the target with the controller's reachable host and port. Agent API-key authentication does not restrict `/metrics`; protect the controller at the network or reverse-proxy layer if scrape data should be private.

## Local development and tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest --cov=clusterwatch --cov-report=term-missing
```

Run the services without Docker in two terminals:

```bash
clusterwatch-controller
CW_NODE_ID=local-dev clusterwatch-agent
```

The tests cover registration, ingestion, chronological history, threshold warnings, heartbeat fallback, Jetson GPU temperature policy, and missed-heartbeat offline transitions. GitHub Actions runs the suite on every push and pull request.

## Load testing

Use `python scripts/load_test.py` to benchmark the controller's complete HTTP and SQLite metric-ingestion path with deterministic simulated telemetry. The script performs an untimed warm-up and reports request throughput, errors, and mean, p50, p95, p99, and maximum latency as JSON.

Run it only against an isolated controller because it intentionally creates node and metric records. The [benchmark procedure](docs/benchmark.md) provides a fixed baseline command, fresh-database setup, authentication instructions, repeat-trial guidance, and interpretation notes.

## Repository layout

```text
clusterwatch/
├── agent/          # collection, Jetson probes, registration, delivery loop
├── controller/     # FastAPI routes, health policy, SQLite repository
├── dashboard/      # dependency-free HTML/CSS/JavaScript UI
├── schemas.py      # shared wire contracts
└── config.py       # environment-based settings
tests/              # API, policy, and telemetry tests
docker-compose.yml  # controller plus horizontally scalable agents
deploy/systemd/     # controller and agent services plus environment templates
deploy/ansible/     # repeatable controller and agent deployment
scripts/            # reproducible controller ingestion load test
```

## Engineering choices and tradeoffs

- **Push agents, scrape controller:** agents work across simple networks and carry registration metadata, while Prometheus can scrape one stable controller endpoint.
- **SQLite first:** WAL mode and a narrow repository layer are enough for one controller and a small cluster. The storage boundary makes PostgreSQL a contained future change.
- **Controller receipt time for liveness:** avoids trusting node clocks for failure detection. `collected_at` is retained for chart chronology.
- **SSE with polling fallback:** one-way update notifications avoid needless polling during normal operation, while native EventSource reconnection and five-second polling preserve updates across transient failures and incompatible proxies.
- **One agent artifact:** physical nodes and simulated nodes run the same code. Jetson probes are capability-detected extensions, not a separate agent fork.
- **Optional shared-key authentication:** one key keeps small trusted clusters simple, while leaving room for per-node identities later. Do not expose port 8000 to the public internet without TLS.

## Portfolio demo checklist

1. Start five simulated nodes and the physical Jetson agent.
2. Show the cluster overview and Jetson GPU/thermal fields.
3. Apply load to one node and explain threshold-derived `WARNING` state.
4. Stop an agent container and watch it become `OFFLINE` after the deadline.
5. Restart it and show automatic recovery plus retained history.
6. Walk through the shared schema, controller-owned timestamps, SQLite index, and graceful vendor-telemetry fallback.

## Sensible next steps

Good extensions, in order of increasing operational scope: PostgreSQL and Kubernetes manifests. ClusterWatch is a credible control-plane project without pretending container replicas provide real HPC scaling.

## License

MIT — update the copyright notice before publishing.
