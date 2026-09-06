from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clusterwatch.config import ControllerSettings
from clusterwatch.controller.prometheus import CONTENT_TYPE, render_metrics
from clusterwatch.controller.status import evaluate_status
from clusterwatch.controller.store import Store
from clusterwatch.schemas import Heartbeat, MetricSample, Registration


def _node_view(store: Store, settings: ControllerSettings, node: dict[str, Any]) -> dict[str, Any]:
    latest = store.latest_metric(node["node_id"])
    node_status, reasons = evaluate_status(node, latest, settings)
    return {
        **node,
        "status": node_status,
        "status_reasons": reasons,
        "heartbeat_age_seconds": max(0, time.time() - node["last_seen"]),
        "latest": latest,
    }


def create_app(settings: ControllerSettings | None = None) -> FastAPI:
    config = settings or ControllerSettings.from_env()
    store = Store(config.database_path)
    dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"

    async def maintenance() -> None:
        while True:
            await asyncio.sleep(3600)
            cutoff = time.time() - config.history_retention_days * 86400
            await asyncio.to_thread(store.prune, cutoff)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(maintenance())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        store.close()

    app = FastAPI(
        title="ClusterWatch Controller API",
        version="0.1.0",
        description="Registration, heartbeat, health evaluation, and metric history for ClusterWatch nodes.",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.settings = config

    def require_agent_api_key(
        x_clusterwatch_key: Annotated[str | None, Header()] = None,
    ) -> None:
        if config.api_key is None:
            return
        if x_clusterwatch_key is None or not secrets.compare_digest(x_clusterwatch_key, config.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing agent API key",
            )

    agent_auth = [Depends(require_agent_api_key)]

    if dashboard_dir.exists():
        app.mount("/static", StaticFiles(directory=dashboard_dir), name="static")

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", tags=["system"], response_class=Response)
    def prometheus_metrics() -> Response:
        nodes = [_node_view(store, config, node) for node in store.list_nodes()]
        return Response(render_metrics(nodes), headers={"Content-Type": CONTENT_TYPE})

    @app.post(
        "/api/v1/nodes/register",
        status_code=status.HTTP_201_CREATED,
        tags=["agents"],
        dependencies=agent_auth,
    )
    def register(payload: Registration, request: Request) -> dict[str, Any]:
        address = request.client.host if request.client else None
        node = store.register(payload, address)
        return {"node": node, "offline_timeout_seconds": config.offline_timeout_seconds}

    @app.post(
        "/api/v1/nodes/{node_id}/metrics",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["agents"],
        dependencies=agent_auth,
    )
    def ingest_metrics(node_id: str, payload: MetricSample) -> dict[str, bool]:
        if not store.add_metric(node_id, payload):
            raise HTTPException(status_code=404, detail="Node is not registered")
        return {"accepted": True}

    @app.post(
        "/api/v1/nodes/{node_id}/heartbeat",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["agents"],
        dependencies=agent_auth,
    )
    def heartbeat(node_id: str, payload: Heartbeat) -> dict[str, bool]:
        if not store.heartbeat(node_id, payload.collection_error):
            raise HTTPException(status_code=404, detail="Node is not registered")
        return {"accepted": True}

    @app.get("/api/v1/nodes", tags=["dashboard"])
    def list_nodes() -> dict[str, Any]:
        nodes = [_node_view(store, config, node) for node in store.list_nodes()]
        counts = {name: sum(node["status"] == name for node in nodes) for name in ("HEALTHY", "WARNING", "OFFLINE")}
        return {"nodes": nodes, "counts": counts, "total": len(nodes), "generated_at": time.time()}

    @app.get("/api/v1/nodes/{node_id}", tags=["dashboard"])
    def get_node(node_id: str) -> dict[str, Any]:
        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        return _node_view(store, config, node)

    @app.get("/api/v1/nodes/{node_id}/metrics", tags=["dashboard"])
    def get_metrics(
        node_id: str,
        minutes: int = Query(default=60, ge=1, le=10080),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        if store.get_node(node_id) is None:
            raise HTTPException(status_code=404, detail="Node not found")
        since = time.time() - minutes * 60
        return {"node_id": node_id, "metrics": store.metric_history(node_id, since, limit)}

    @app.get("/api/v1/config", tags=["dashboard"])
    def public_config() -> dict[str, Any]:
        return {
            "offline_timeout_seconds": config.offline_timeout_seconds,
            "thresholds": {
                "cpu_percent": config.cpu_warning_percent,
                "memory_percent": config.memory_warning_percent,
                "disk_percent": config.disk_warning_percent,
                "temperature_c": config.temperature_warning_c,
            },
            "history_retention_days": config.history_retention_days,
        }

    @app.get("/", include_in_schema=False)
    @app.get("/nodes/{node_id}", include_in_schema=False)
    def dashboard() -> Response:
        index = dashboard_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Dashboard assets are not installed")
        return FileResponse(index)

    return app


def run() -> None:
    uvicorn.run("clusterwatch.controller.app:create_app", factory=True, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
