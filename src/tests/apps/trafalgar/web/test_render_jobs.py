"""Tests covering Trafalgar render job submission lifecycle endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web import render
from apps.trafalgar.web.job_store import JobStore


class StubJobAdapter:
    """Stub render adapter supporting status and cancellation lookups."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self.cancelled: list[str] = []

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
    ) -> dict[str, str]:
        self._counter += 1
        job_id = f"stub-{self._counter}"
        self._jobs[job_id] = {
            "status": "submitted",
            "message": None,
            "chunk_size": chunk_size,
        }
        return {"job_id": job_id, "status": "submitted", "farm_type": "stub"}

    def set_status(self, job_id: str, status: str, message: str | None = None) -> None:
        self._jobs[job_id]["status"] = status
        self._jobs[job_id]["message"] = message

    def get_job_status(self, job_id: str) -> dict[str, str | None]:
        state = self._jobs[job_id]
        payload: dict[str, str | None] = {
            "job_id": job_id,
            "status": state["status"],
            "farm_type": "stub",
        }
        if state.get("message") is not None:
            payload["message"] = state["message"]
        return payload

    def cancel_job(self, job_id: str) -> dict[str, str]:
        self.cancelled.append(job_id)
        self._jobs[job_id]["status"] = "cancelled"
        return {"job_id": job_id, "status": "cancelled", "farm_type": "stub"}


class StubStatusOnlyAdapter(StubJobAdapter):
    """Adapter that supports status lookups but not cancellation."""

    cancel_job = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    render.app.dependency_overrides.clear()
    yield
    render.app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _job_payload(farm: str = "mock") -> dict[str, Any]:
    return {
        "dcc": "maya",
        "scene": "/projects/demo/scene.ma",
        "frames": "1-10",
        "output": "/tmp/output",
        "farm": farm,
        "priority": 75,
        "user": "tester",
    }


@pytest.mark.anyio("asyncio")
async def test_list_jobs_reflects_latest_status() -> None:
    adapter = StubJobAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        assert submit_response.status_code == 201
        job_id = submit_response.json()["job_id"]

        adapter.set_status(job_id, "running", "frame 5 of 10")

        list_response = await client.get("/jobs")

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["jobs"][0]["job_id"] == job_id
    assert payload["jobs"][0]["status"] == "running"
    assert payload["jobs"][0]["message"] == "frame 5 of 10"
    assert payload["jobs"][0]["request"]["scene"] == "/projects/demo/scene.ma"


@pytest.mark.anyio("asyncio")
async def test_get_job_returns_detail_payload() -> None:
    adapter = StubJobAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        job_id = submit_response.json()["job_id"]
        adapter.set_status(job_id, "completed")

        detail_response = await client.get(f"/jobs/{job_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["job_id"] == job_id
    assert detail["status"] == "completed"
    assert detail["farm"] == "mock"
    assert detail["farm_type"] == "stub"


@pytest.mark.anyio("asyncio")
async def test_get_job_missing_returns_404() -> None:
    service = render.RenderSubmissionService({})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/jobs/unknown")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


@pytest.mark.anyio("asyncio")
async def test_cancel_job_updates_status_when_supported() -> None:
    adapter = StubJobAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        job_id = submit_response.json()["job_id"]

        cancel_response = await client.delete(f"/jobs/{job_id}")

    assert cancel_response.status_code == 200
    payload = cancel_response.json()
    assert payload["status"] == "cancelled"
    assert adapter.cancelled == [job_id]


@pytest.mark.anyio("asyncio")
async def test_cancel_job_reports_adapter_errors() -> None:
    adapter = StubStatusOnlyAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        job_id = submit_response.json()["job_id"]

        response = await client.delete(f"/jobs/{job_id}")

    assert response.status_code == 400
    assert "does not support job cancellation" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_job_store_persists_records_between_services(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.json"
    adapter = StubJobAdapter()
    service = render.RenderSubmissionService(
        {"mock": adapter}, job_store=JobStore(store_path)
    )
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        assert submit_response.status_code == 201
        job_id = submit_response.json()["job_id"]

    # New service instance should load the previously stored job.
    new_service = render.RenderSubmissionService({}, job_store=JobStore(store_path))
    render.app.dependency_overrides[render.get_render_service] = lambda: new_service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        list_response = await client.get("/jobs")

    assert list_response.status_code == 200
    jobs = list_response.json()["jobs"]
    assert [job["job_id"] for job in jobs] == [job_id]


@pytest.mark.anyio("asyncio")
async def test_history_limit_removes_old_jobs(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.json"
    adapter = StubJobAdapter()
    service = render.RenderSubmissionService(
        {"mock": adapter}, job_store=JobStore(store_path), history_limit=1
    )
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/jobs", json=_job_payload())
        assert first.status_code == 201
        second = await client.post("/jobs", json=_job_payload())
        assert second.status_code == 201
        latest_job_id = second.json()["job_id"]

    # Reload the service to ensure only the latest job remains persisted.
    new_service = render.RenderSubmissionService({}, job_store=JobStore(store_path))
    jobs = new_service.list_jobs()
    assert [job.job_id for job in jobs] == [latest_job_id]
