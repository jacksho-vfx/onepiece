"""Tests covering Trafalgar render job submission lifecycle endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.trafalgar.web.job_store import JobStore, JobStoreStats

import fastapi.security
import fastapi.security.api_key
import apps.trafalgar.web.security as security
from fastapi.security.http import HTTPAuthorizationCredentials
from apps.trafalgar.web import render


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


class RecordingJobStore:
    """In-memory JobStore replacement that records persisted batches."""

    def __init__(self) -> None:
        self.saved_batches: list[list[str]] = []
        self.stats = JobStoreStats(retention=None)

    def load(self) -> list[render._JobRecord]:
        return []

    def save(self, records: Iterable[render._JobRecord]) -> None:
        self.saved_batches.append([record.job_id for record in records])


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
async def test_background_poller_refreshes_jobs_without_requests() -> None:
    adapter = StubJobAdapter()
    store = RecordingJobStore()
    service = render.RenderSubmissionService(
        {"mock": adapter},
        job_store=store,
        status_poll_interval=0.01,
        store_persist_interval=0.2,
    )
    request = render.RenderJobRequest(
        dcc="maya",
        scene="/projects/demo/scene.ma",
        frames="1-10",
        output="/tmp/output",
        farm="mock",
        priority=50,
        user="tester",
    )
    result = service.submit_job(request)
    job_id = result["job_id"]

    service.start_background_polling()
    try:
        adapter.set_status(job_id, "running", "frame 5 of 10")

        for _ in range(50):
            record = service._jobs[job_id]
            if record.status == "running" and record.message == "frame 5 of 10":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Background poller did not refresh job status")
    finally:
        await service.stop_background_polling()


@pytest.mark.anyio("asyncio")
async def test_background_poller_throttles_persist_operations() -> None:
    adapter = StubJobAdapter()
    store = RecordingJobStore()
    service = render.RenderSubmissionService(
        {"mock": adapter},
        job_store=store,
        status_poll_interval=0.01,
        store_persist_interval=0.3,
    )
    request = render.RenderJobRequest(
        dcc="maya",
        scene="/projects/demo/scene.ma",
        frames="1-10",
        output="/tmp/output",
        farm="mock",
        priority=50,
        user="tester",
    )
    result = service.submit_job(request)
    job_id = result["job_id"]

    assert len(store.saved_batches) == 1

    service.start_background_polling()
    try:
        adapter.set_status(job_id, "running")

        await asyncio.sleep(0.05)
        assert len(store.saved_batches) == 1

        for _ in range(40):
            if len(store.saved_batches) > 1:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("Persisted records were not flushed after throttle interval")
    finally:
        await service.stop_background_polling()


@pytest.mark.anyio("asyncio")
async def test_list_jobs_reflects_latest_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure that /jobs reflects the latest adapter status updates."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles={"render:read", "render:submit"},
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles={"render:read", "render:submit"},
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    adapter = StubJobAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        assert submit_response.status_code == 201, submit_response.text
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
async def test_list_jobs_supports_limit_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles={render.ROLE_RENDER_READ, render.ROLE_RENDER_SUBMIT},
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles={render.ROLE_RENDER_READ, render.ROLE_RENDER_SUBMIT},
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    adapter = StubJobAdapter()
    service = render.RenderSubmissionService({"mock": adapter, "tractor": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created_jobs: list[tuple[str, str]] = []
        for farm in ("mock", "tractor", "mock"):
            response = await client.post("/jobs", json=_job_payload(farm=farm))
            assert response.status_code == 201, response.text
            job_id = response.json()["job_id"]
            created_jobs.append((farm, job_id))

        adapter.set_status(created_jobs[0][1], "running")
        adapter.set_status(created_jobs[1][1], "completed")
        adapter.set_status(created_jobs[2][1], "failed")

        limited = await client.get("/jobs", params={"limit": 2})
        status_filtered = await client.get("/jobs", params=[("status", "running")])
        farm_filtered = await client.get("/jobs", params=[("farm", "tractor")])
        combined = await client.get(
            "/jobs",
            params=[("farm", "mock"), ("status", "failed"), ("limit", "1")],
        )

    limited_payload = limited.json()
    assert len(limited_payload["jobs"]) == 2
    assert [job["job_id"] for job in limited_payload["jobs"]] == [
        created_jobs[0][1],
        created_jobs[1][1],
    ]

    status_payload = status_filtered.json()
    assert [job["job_id"] for job in status_payload["jobs"]] == [created_jobs[0][1]]

    farm_payload = farm_filtered.json()
    assert [job["job_id"] for job in farm_payload["jobs"]] == [created_jobs[1][1]]

    combined_payload = combined.json()
    assert [job["job_id"] for job in combined_payload["jobs"]] == [created_jobs[2][1]]


@pytest.mark.anyio("asyncio")
async def test_get_job_returns_detail_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure GET /jobs/{job_id} returns the correct detailed job info."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    ROLE_WRITE = getattr(render, "ROLE_RENDER_WRITE", None)
    ROLE_SUBMIT = getattr(render, "ROLE_RENDER_SUBMIT", None)
    write_role = ROLE_WRITE or ROLE_SUBMIT or render.ROLE_RENDER_READ

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles={render.ROLE_RENDER_READ, write_role},
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles={render.ROLE_RENDER_READ, write_role},
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    adapter = StubJobAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        assert submit_response.status_code == 201, submit_response.text
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
async def test_get_job_missing_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure GET /jobs/{job_id} returns 404 for unknown job IDs."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    ROLE_WRITE = getattr(render, "ROLE_RENDER_WRITE", None)
    ROLE_SUBMIT = getattr(render, "ROLE_RENDER_SUBMIT", None)
    write_role = ROLE_WRITE or ROLE_SUBMIT or render.ROLE_RENDER_READ

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles={render.ROLE_RENDER_READ, write_role},
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles={render.ROLE_RENDER_READ, write_role},
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    service = render.RenderSubmissionService({})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/jobs/unknown")

    assert response.status_code == 404
    payload = response.json()
    assert payload["detail"] == "Job not found."


@pytest.mark.anyio("asyncio")
async def test_cancel_job_reports_adapter_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure DELETE /jobs/{job_id} returns 409 if adapter doesn't support cancellation."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    role_names = [
        "ROLE_RENDER_READ",
        "ROLE_RENDER_SUBMIT",
        "ROLE_RENDER_WRITE",
        "ROLE_RENDER_CANCEL",
        "ROLE_RENDER_MANAGE",
        "ROLE_RENDER_ADMIN",
    ]
    available_roles = {
        getattr(render, name) for name in role_names if hasattr(render, name)
    }

    if not available_roles:
        available_roles = {render.ROLE_RENDER_READ}

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles=available_roles,
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles=available_roles,
            )

    monkeypatch.setattr(
        security,
        "get_credential_store",
        lambda *a, **kw: DummyCredentialStore(),
    )

    adapter = StubStatusOnlyAdapter()
    service = render.RenderSubmissionService({"mock": adapter})
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=_job_payload())
        assert submit_response.status_code == 201, submit_response.text
        job_id = submit_response.json()["job_id"]

        response = await client.delete(f"/jobs/{job_id}")

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "render.cancellation_unsupported"
    assert error["context"]["job_id"] == job_id


@pytest.mark.anyio("asyncio")
async def test_job_store_persists_records_between_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ensure jobs persist across RenderSubmissionService instances."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles=set(
                    getattr(render, n)
                    for n in dir(render)
                    if n.startswith("ROLE_RENDER_")
                ),
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles=set(
                    getattr(render, n)
                    for n in dir(render)
                    if n.startswith("ROLE_RENDER_")
                ),
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    store_path = tmp_path / "jobs.json"
    adapter = StubJobAdapter()

    payload = _job_payload()
    adapter_name = payload.get("adapter", "mock")

    service = render.RenderSubmissionService(
        {adapter_name: adapter}, job_store=JobStore(store_path)
    )
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submit_response = await client.post("/jobs", json=payload)
        assert submit_response.status_code == 201, submit_response.text
        job_id = submit_response.json()["job_id"]

    new_service = render.RenderSubmissionService({}, job_store=JobStore(store_path))
    render.app.dependency_overrides[render.get_render_service] = lambda: new_service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        list_response = await client.get("/jobs")

    assert list_response.status_code == 200, list_response.text
    jobs = list_response.json()["jobs"]
    assert [job["job_id"] for job in jobs] == [job_id]


def test_reload_jobs_with_unregistered_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Persisted jobs should be reloaded even if their farm is no longer registered."""

    adapter = StubJobAdapter()
    legacy_farm = "retired"
    store_path = tmp_path / "jobs.json"

    monkeypatch.setattr(
        render.RenderJobRequest,
        "_farm_registry_provider",
        lambda: (legacy_farm,),
    )

    service = render.RenderSubmissionService(
        {legacy_farm: adapter}, job_store=JobStore(store_path)
    )

    request = render.RenderJobRequest.model_validate(
        _job_payload("Retired"), context={"farm_registry": (legacy_farm,)}
    )
    result = service.submit_job(request)
    job_id = result["job_id"]
    assert job_id

    monkeypatch.setattr(
        render.RenderJobRequest,
        "_farm_registry_provider",
        lambda: (),
    )

    new_service = render.RenderSubmissionService({}, job_store=JobStore(store_path))
    jobs = new_service.list_jobs()

    assert [job.job_id for job in jobs] == [job_id]
    assert jobs[0].request.farm == legacy_farm


@pytest.mark.anyio("asyncio")
async def test_history_limit_removes_old_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ensure old jobs are pruned when exceeding history_limit."""
    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="Bearer",
                roles=set(
                    getattr(render, n)
                    for n in dir(render)
                    if n.startswith("ROLE_RENDER_")
                ),
            )

        def authenticate_api_key(self, key: str) -> render.AuthenticatedPrincipal:
            return render.AuthenticatedPrincipal(
                identifier="mock-service",
                scheme="APIKey",
                roles=set(
                    getattr(render, n)
                    for n in dir(render)
                    if n.startswith("ROLE_RENDER_")
                ),
            )

    monkeypatch.setattr(
        security, "get_credential_store", lambda *a, **kw: DummyCredentialStore()
    )

    store_path = tmp_path / "jobs.json"
    adapter = StubJobAdapter()

    payload = _job_payload()
    adapter_name = payload.get("adapter", "mock")

    service = render.RenderSubmissionService(
        {adapter_name: adapter},
        job_store=JobStore(store_path),
        history_limit=1,
    )
    render.app.dependency_overrides[render.get_render_service] = lambda: service

    transport = ASGITransport(app=render.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/jobs", json=payload)
        assert first.status_code == 201, first.text
        second = await client.post("/jobs", json=payload)
        assert second.status_code == 201, second.text
        latest_job_id = second.json()["job_id"]

    new_service = render.RenderSubmissionService({}, job_store=JobStore(store_path))
    jobs = new_service.list_jobs()
    assert [job.job_id for job in jobs] == [latest_job_id]
