from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from apps.trafalgar.web import ingest, render
from apps.trafalgar.web.events import EventBroadcaster, clear_keepalive_caches
from libraries.ingest.registry import IngestRunRecord
from libraries.ingest.service import IngestReport, IngestedMedia, MediaInfo
from tests.security_patches import patch_security


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
    clear_keepalive_caches()
    yield
    render.app.dependency_overrides.clear()
    ingest.app.dependency_overrides.clear()
    clear_keepalive_caches()


def _request_with_app_state(**state: Any) -> Any:
    app = SimpleNamespace(state=SimpleNamespace(**state))
    return SimpleNamespace(app=app)


def test_render_keepalive_interval_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(render.RENDER_SSE_KEEPALIVE_INTERVAL_ENV, "12.5")
    clear_keepalive_caches()
    request = SimpleNamespace()
    assert render._resolve_render_keepalive_interval(request) == 12.5


def test_render_keepalive_interval_state_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(render.RENDER_SSE_KEEPALIVE_INTERVAL_ENV, raising=False)
    clear_keepalive_caches()
    request = _request_with_app_state(render_sse_keepalive_interval="7.5")
    assert render._resolve_render_keepalive_interval(request) == 7.5


def test_ingest_keepalive_interval_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ingest.INGEST_SSE_KEEPALIVE_INTERVAL_ENV, "9.75")
    clear_keepalive_caches()
    request = SimpleNamespace()
    assert ingest._resolve_ingest_keepalive_interval(request) == 9.75


def test_ingest_keepalive_interval_state_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ingest.INGEST_SSE_KEEPALIVE_INTERVAL_ENV, raising=False)
    clear_keepalive_caches()
    request = _request_with_app_state(ingest_sse_keepalive_interval=4)
    assert ingest._resolve_ingest_keepalive_interval(request) == 4.0


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_publish_from_thread_without_running_loop() -> None:
    broadcaster = EventBroadcaster(max_buffer=4)
    queue = await broadcaster.subscribe()

    def _emit() -> None:
        broadcaster.publish({"event": "thread"})

    thread = threading.Thread(target=_emit)
    thread.start()
    thread.join()

    message = await asyncio.wait_for(queue.get(), timeout=1)
    await broadcaster.unsubscribe(queue)

    assert message == {"event": "thread"}


@pytest.mark.anyio("asyncio")
async def test_render_job_stream_emits_created_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = StubJobAdapter()
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(render, "JOB_EVENTS", broadcaster)
    service = render.RenderSubmissionService({"mock": adapter}, broadcaster=broadcaster)
    monkeypatch.setattr(render, "get_render_service", lambda: service)

    class _Request:
        async def is_disconnected(self) -> bool:  # pragma: no cover - simple stub
            return False

    stream = render._job_event_stream(_Request())
    event_task = asyncio.create_task(stream.__anext__())
    snapshot_chunk = await asyncio.wait_for(event_task, timeout=1)

    assert snapshot_chunk.startswith(b"event: jobs.snapshot")
    snapshot_lines = [line for line in snapshot_chunk.split(b"\n") if line]
    snapshot_data = next(line for line in snapshot_lines if line.startswith(b"data: "))
    snapshot_payload = json.loads(snapshot_data.split(b": ", 1)[1].strip())
    assert snapshot_payload["event"] == "jobs.snapshot"
    assert snapshot_payload["jobs"] == []

    event_task = asyncio.create_task(stream.__anext__())

    request = render.RenderJobRequest(**_job_payload())
    service.submit_job(request)
    await asyncio.sleep(0)

    chunk = await asyncio.wait_for(event_task, timeout=1)
    await stream.aclose()

    assert chunk.startswith(b"event: job.created")
    payload_line = next(
        line for line in chunk.split(b"\n") if line.startswith(b"data: ")
    )
    payload = json.loads(payload_line.split(b": ", 1)[1].strip())
    assert payload["event"] == "job.created"
    assert payload["job"]["job_id"] == "stub-1"


@pytest.mark.anyio("asyncio")
async def test_render_job_websocket_receives_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Ensure the /jobs/ws websocket connects and receives job updates.
    This patches out all authentication and dependency layers so the
    test runs without real service credentials.
    """

    provide_principal = patch_security(monkeypatch, roles={"render:read"})

    adapter = StubJobAdapter()
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(render, "JOB_EVENTS", broadcaster)
    service = render.RenderSubmissionService({"mock": adapter}, broadcaster=broadcaster)

    render.app.dependency_overrides[render.get_render_service] = lambda: service

    jobs_route = next(r for r in render.app.router.routes if r.path == "/jobs/ws")

    def find_role_dependency(dependant: Any) -> Any:
        for dep in dependant.dependencies:
            if "require_roles" in repr(dep.call):
                return dep.call
            found = find_role_dependency(dep)
            if found:
                return found
        return None

    role_dependency = find_role_dependency(jobs_route.dependant)
    assert role_dependency, "Could not locate require_roles dependency for /jobs/ws"

    render.app.dependency_overrides[role_dependency] = provide_principal

    request = render.RenderJobRequest(**_job_payload())
    service.submit_job(request)

    client = TestClient(render.app)

    with client.websocket_connect("/jobs/ws") as websocket:
        msg = websocket.receive_json()
        assert msg["type"] == "connected"
        assert msg["snapshot"]["event"] == "jobs.snapshot"
        assert [job["job_id"] for job in msg["snapshot"]["jobs"]] == ["stub-1"]


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
async def test_ingest_websocket_receives_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StaticIngestProvider([_ingest_record("run-ws")])
    broadcaster = EventBroadcaster(max_buffer=4)
    monkeypatch.setattr(ingest, "INGEST_EVENTS", broadcaster)
    service = ingest.IngestRunService(provider=provider, broadcaster=broadcaster)
    ingest.app.dependency_overrides[ingest.get_ingest_run_service] = lambda: service

    provide_principal = patch_security(monkeypatch, roles={"ingest:read"})

    runs_route = next(r for r in ingest.app.router.routes if r.path == "/runs/ws")

    def find_role_dependency(dependant: Any) -> Any:
        for dep in dependant.dependencies:
            if "require_roles" in repr(dep.call):
                return dep.call
            found = find_role_dependency(dep)
            if found:
                return found
        return None

    role_dependency = find_role_dependency(runs_route.dependant)
    assert role_dependency, "Could not locate require_roles dependency for /runs/ws"

    ingest.app.dependency_overrides[role_dependency] = provide_principal

    runs_list_route = next(r for r in ingest.app.router.routes if r.path == "/runs")
    list_role_dependency = find_role_dependency(runs_list_route.dependant)
    assert list_role_dependency, "Could not locate require_roles dependency for /runs"
    ingest.app.dependency_overrides[list_role_dependency] = provide_principal

    client = TestClient(ingest.app)
    with client.websocket_connect("/runs/ws") as websocket:
        response = client.get("/runs")
        assert response.status_code == 200
        message = websocket.receive_json()

    assert message["event"] == "run.created"
    assert message["run"]["id"] == "run-ws"
