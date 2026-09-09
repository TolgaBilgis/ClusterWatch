import asyncio
import json
from pathlib import Path

from clusterwatch.controller.events import EventBroker, event_stream


class DisconnectAfterFirstEvent:
    def __init__(self) -> None:
        self.checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > 1


def test_event_stream_emits_named_json_event():
    async def consume_one_event() -> str:
        stream = event_stream(DisconnectAfterFirstEvent(), EventBroker(), 0.001)
        return await anext(stream)

    event = asyncio.run(consume_one_event())
    lines = event.strip().splitlines()

    assert lines[0] == "event: cluster-update"
    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload["revision"] == 0
    assert isinstance(payload["generated_at"], float)


def test_broker_wakes_waiters_after_publish():
    async def wait_for_publish() -> int:
        broker = EventBroker()
        waiter = asyncio.create_task(broker.wait_for_update(0, timeout=1))
        await asyncio.sleep(0)
        await broker.publish()
        return await waiter

    assert asyncio.run(wait_for_publish()) == 1


def test_agent_write_publishes_dashboard_event(client, registration):
    initial_revision = client.app.state.event_broker.revision

    response = client.post("/api/v1/nodes/register", json=registration)

    assert response.status_code == 201
    assert client.app.state.event_broker.revision == initial_revision + 1


def test_event_route_and_browser_polling_fallback(client):
    paths = client.get("/openapi.json").json()["paths"]
    source = (Path(__file__).parents[1] / "clusterwatch/dashboard/app.js").read_text()

    assert "/api/v1/events" in paths
    assert 'new EventSource("/api/v1/events")' in source
    assert "eventSource.onerror" in source
    assert "schedulePolling()" in source
