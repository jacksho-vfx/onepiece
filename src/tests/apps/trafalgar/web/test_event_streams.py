from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from apps.trafalgar.web import ingest, render
from apps.trafalgar.web.events import EventBroadcaster
from libraries.ingest.registry import IngestRunRecord
from libraries.ingest.service import IngestReport, IngestedMedia, MediaInfo


class StubJobAdapter:
    """Adapter that returns a deterministic job identifier."""

    def __init__(self) -> None:
        self.counter = 0

    def __call__(
        self,
        *,
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, Any]:
        self.counter += 1
        return {
            "job_id": f"stub-{self.counter}",
            "status": "queued",
            "farm_type": "stub",
        }


class StaticIngestProvider(ingest.IngestRunProvider):  # type: ignore[misc]
    """Provider that returns a fixed set of ingest runs."""

    def __init__(self, records: list[IngestRunRecord]):
        super().__init__()
        self._records = records

    def load_recent_runs(self, limit: int | None = None) -> list[IngestRunRecord]:
        return list(self._records[: limit or len(self._records)])

    def get_run(self, run_id: str) -> IngestRunRecord | None:
        for record in self._records:
            if record.run_id == run_id:
                return record
        return None


def _job_payload() -> dict[str, Any]:
    return {
        "dcc": "maya",
        "scene": "/projects/demo/scene.ma",
        "frames": "1-5",
        "output": "/tmp/out",
        "farm": "mock",
        "priority": 50,
        "user": "tester",
    }


def _ingest_record(run_id: str = "run-001") -> IngestRunRecord:
    report = IngestReport(
        processed=[
            IngestedMedia(
                path=Path("/mnt/incoming/shot.mov"),
                bucket="vendor_in",
                key="show/shot.mov",
                media_info=MediaInfo(
                    show_code="OP",
                    episode="E001",
                    scene="S001",
                    shot="SH001",
                    descriptor="final",
                    extension="mov",
                ),
            )
        ]
    )
    return IngestRunRecord(
        run_id=run_id,
        started_at=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc),
        report=report,
    )
@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    render.app.dependency_overrides.clear()
    ingest.app.dependency_overrides.clear()
    yield
    render.app.dependency_overrides.clear()
    ingest.app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_render_job_stream_emits_created_events(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = StubJobAdapter()
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(render, "JOB_EVENTS", broadcaster)
    service = render.RenderSubmissionService({"mock": adapter}, broadcaster=broadcaster)

    class _Request:
        async def is_disconnected(self) -> bool:  # pragma: no cover - simple stub
            return False

    stream = render._job_event_stream(_Request())
    event_task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)

    request = render.RenderJobRequest(**_job_payload())
    service.submit_job(request)
    await asyncio.sleep(0)

    chunk = await asyncio.wait_for(event_task, timeout=1)
    await stream.aclose()

    assert chunk.startswith(b"data: ")
    payload = json.loads(chunk.split(b": ", 1)[1].strip())
    assert payload["event"] == "job.created"
    assert payload["job"]["job_id"] == "stub-1"


@pytest.mark.anyio("asyncio")
async def test_render_job_websocket_receives_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = StubJobAdapter()
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(render, "JOB_EVENTS", broadcaster)
    service = render.RenderSubmissionService({"mock": adapter}, broadcaster=broadcaster)
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    client = TestClient(render.app)
    with client.websocket_connect("/jobs/ws") as websocket:
        response = client.post("/jobs", json=_job_payload())
        assert response.status_code == 201
        message = websocket.receive_json()

    assert message["event"] == "job.created"
    assert message["job"]["job_id"] == "stub-1"


@pytest.mark.anyio("asyncio")
async def test_ingest_stream_emits_run_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = StaticIngestProvider([_ingest_record()])
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(ingest, "INGEST_EVENTS", broadcaster)
    service = ingest.IngestRunService(provider=provider, broadcaster=broadcaster)

    class _Request:
        async def is_disconnected(self) -> bool:  # pragma: no cover - simple stub
            return False

    stream = ingest._ingest_event_stream(_Request())
    event_task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)

    service.list_runs(20)
    await asyncio.sleep(0)

    chunk = await asyncio.wait_for(event_task, timeout=1)
    await stream.aclose()

    assert chunk.startswith(b"data: ")
    payload = json.loads(chunk.split(b": ", 1)[1].strip())
    assert payload["event"] == "run.created"
    assert payload["run"]["id"] == "run-001"


@pytest.mark.anyio("asyncio")
async def test_ingest_websocket_receives_events(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = StaticIngestProvider([_ingest_record("run-ws")])
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(ingest, "INGEST_EVENTS", broadcaster)
    service = ingest.IngestRunService(provider=provider, broadcaster=broadcaster)
    ingest.app.dependency_overrides[ingest.get_ingest_run_service] = lambda: service

    client = TestClient(ingest.app)
    with client.websocket_connect("/runs/ws") as websocket:
        response = client.get("/runs")
        assert response.status_code == 200
        message = websocket.receive_json()

    assert message["event"] == "run.created"
    assert message["run"]["id"] == "run-ws"
