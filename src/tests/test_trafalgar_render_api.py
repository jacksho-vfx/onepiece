from typing import Any, cast, Dict

import pytest
from fastapi.testclient import TestClient

from apps.trafalgar.web import render as render_module
from libraries.render.base import RenderAdapterUnavailableError
from tests.security_patches import patch_security


@pytest.fixture(autouse=True)
def render_security(monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[misc]
    provider = patch_security(
        monkeypatch,
        roles={"render:read", "render:submit", "render:manage"},
    )
    import apps.trafalgar.web.security as security_module

    render_module.app.dependency_overrides[security_module.authenticate_request] = (
        provider
    )

    yield

    render_module.app.dependency_overrides.pop(
        security_module.authenticate_request, None
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(render_module.app)


@pytest.fixture()
def render_service() -> render_module.RenderSubmissionService:
    render_module.get_render_service.cache_clear()
    service = render_module.get_render_service()
    yield service
    render_module.get_render_service.cache_clear()


def test_get_farms_lists_registered_adapters(client: TestClient) -> None:
    response = client.get("/farms")
    assert response.status_code == 200
    payload = response.json()
    farms = {farm["name"]: farm for farm in payload["farms"]}
    assert "mock" in farms
    assert "deadline" in farms
    for farm in farms.values():
        assert "capabilities" in farm
        capabilities = farm["capabilities"]
        assert "priority" in capabilities
        assert "chunking" in capabilities
        assert "cancellation" in capabilities


def test_get_farms_returns_capabilities(client: TestClient) -> None:
    response = client.get("/farms")
    assert response.status_code == 200

    payload = cast(Dict[str, Any], response.json())
    farms_list = cast(list[Dict[str, Any]], payload["farms"])
    farms = {farm["name"]: farm for farm in farms_list}

    expected: Dict[str, Dict[str, Any]] = {
        "mock": {
            "priority": {"default": 50, "minimum": 0, "maximum": 100},
            "chunking": {
                "enabled": True,
                "minimum": 1,
                "maximum": 10,
                "default": 5,
            },
            "cancellation": {"supported": False},
        },
        "deadline": {
            "priority": {"default": 50, "minimum": 0, "maximum": 100},
            "chunking": {
                "enabled": True,
                "minimum": 1,
                "maximum": 50,
                "default": 10,
            },
            "cancellation": {"supported": False},
        },
        "tractor": {
            "priority": {"default": 75, "minimum": 1, "maximum": 150},
            "chunking": {
                "enabled": True,
                "minimum": 1,
                "maximum": 30,
                "default": 8,
            },
            "cancellation": {"supported": False},
        },
        "opencue": {
            "priority": {"default": 60, "minimum": 0, "maximum": 120},
            "chunking": {
                "enabled": True,
                "minimum": 1,
                "maximum": 25,
                "default": 6,
            },
            "cancellation": {"supported": False},
        },
    }

    for name, expectation in expected.items():
        farm = farms[name]
        capabilities = cast(Dict[str, Any], farm["capabilities"])
        priority = cast(Dict[str, Any], capabilities["priority"])
        chunking = cast(Dict[str, Any], capabilities["chunking"])
        cancellation = cast(Dict[str, Any], capabilities["cancellation"])

        assert priority["default"] == expectation["priority"]["default"]
        assert priority["minimum"] == expectation["priority"]["minimum"]
        assert priority["maximum"] == expectation["priority"]["maximum"]
        assert chunking["enabled"] == expectation["chunking"]["enabled"]
        assert chunking["minimum"] == expectation["chunking"]["minimum"]
        assert chunking["maximum"] == expectation["chunking"]["maximum"]
        assert chunking["default"] == expectation["chunking"]["default"]
        assert cancellation["supported"] == expectation["cancellation"]["supported"]


def test_submit_job_success(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    called: dict[str, Any] = {}

    def fake_submit(
        *, scene: str, frames: str, output: str, dcc: str, priority: int, user: str
    ) -> dict[str, Any]:
        called.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
            }
        )
        return {
            "job_id": "web-123",
            "status": "queued",
            "farm_type": "mock",
            "message": "Queued for processing.",
        }

    monkeypatch.setattr(
        "apps.trafalgar.web.render.RenderSubmissionService.submit_job",
        lambda self, request: fake_submit(
            scene=request.scene,
            frames=request.frames,
            output=request.output,
            dcc=request.dcc,
            priority=request.priority,
            user=request.user,
        ),
    )

    response = client.post(
        "/jobs",
        json={
            "dcc": "nuke",
            "scene": "/projects/show/shot_v001.nk",
            "frames": "1-5",
            "output": "/tmp/renders",
            "farm": "mock",
            "priority": 75,
            "user": "operator",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_id"] == "web-123"
    assert payload["status"] == "queued"
    assert payload["farm_type"] == "mock"
    assert payload["message"] == "Queued for processing."

    assert called["scene"] == "/projects/show/shot_v001.nk"
    assert called["frames"] == "1-5"
    assert called["output"] == "/tmp/renders"
    assert called["dcc"] == "nuke"
    assert called["priority"] == 75
    assert called["user"] == "operator"


def test_submit_job_accepts_runtime_registered_adapter(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    render_service: render_module.RenderSubmissionService,
) -> None:
    custom_called: dict[str, Any] = {}

    def fake_submit(
        self: render_module.RenderSubmissionService,
        request: render_module.RenderJobRequest,
    ) -> dict[str, Any]:
        custom_called.update(request.model_dump())
        return {
            "job_id": "custom-456",
            "status": "queued",
            "farm_type": request.farm,
        }

    render_service.register_adapter("bespoke", lambda **_: {})

    monkeypatch.setattr(
        render_module.RenderSubmissionService, "submit_job", fake_submit
    )

    response = client.post(
        "/jobs",
        json={
            "dcc": "maya",
            "scene": "/path/to/scene.ma",
            "frames": "1-10",
            "output": "/tmp/output",
            "farm": "BeSpOkE",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["job_id"] == "custom-456"
    assert payload["status"] == "queued"
    assert payload["farm_type"] == "bespoke"

    assert custom_called["farm"] == "bespoke"


def test_submit_job_not_implemented_response(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        json={
            "dcc": "maya",
            "scene": "/projects/show/shot_v002.ma",
            "output": "/tmp/renders",
            "farm": "deadline",
        },
    )

    assert response.status_code == 501
    payload = response.json()
    error = payload["error"]
    assert error["code"] == "adapter.not_implemented"
    assert "not implemented" in error["message"].lower()
    assert error["context"]["adapter"] == "deadline"


def test_submit_job_unknown_farm_response(client: TestClient) -> None:
    original_override = render_module.app.dependency_overrides.get(
        render_module.get_render_service
    )
    service = render_module.RenderSubmissionService(
        {"deadline": render_module.FARM_ADAPTERS["deadline"]}
    )
    render_module.app.dependency_overrides[render_module.get_render_service] = (
        lambda: service
    )
    try:
        response = client.post(
            "/jobs",
            json={
                "dcc": "maya",
                "scene": "/projects/show/shot_v003.ma",
                "output": "/tmp/renders",
                "farm": "mock",
            },
        )
    finally:
        if original_override is None:
            render_module.app.dependency_overrides.pop(
                render_module.get_render_service, None
            )
        else:
            render_module.app.dependency_overrides[render_module.get_render_service] = (
                original_override
            )

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"][-1] == "farm"
    assert "Unknown farm" in detail["msg"]


def test_submit_job_surfaces_adapter_unavailability(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:

    def fail_with_unavailability(self, request):  # type: ignore[no-untyped-def]
        raise RenderAdapterUnavailableError(
            "Farm is temporarily offline.",
            hint="Check the farm status page and retry once the outage is resolved.",
            context={"farm": request.farm},
        )

    monkeypatch.setattr(
        "apps.trafalgar.web.render.RenderSubmissionService.submit_job",
        fail_with_unavailability,
    )

    response = client.post(
        "/jobs",
        json={
            "dcc": "maya",
            "scene": "/projects/show/shot_v004.ma",
            "output": "/tmp/renders",
            "farm": "mock",
        },
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "adapter.unavailable"
    assert "outage" in error["hint"].lower()


def test_submit_job_invalid_priority_returns_api_error(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        json={
            "dcc": "maya",
            "scene": "/projects/show/shot_v005.ma",
            "output": "/tmp/renders",
            "farm": "mock",
            "priority": 200,
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "render.invalid_request"
    assert "priority" in error["message"].lower()
    assert error["context"]["priority"] == 200


def test_submit_job_invalid_chunk_size_returns_api_error(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        json={
            "dcc": "maya",
            "scene": "/projects/show/shot_v006.ma",
            "output": "/tmp/renders",
            "farm": "mock",
            "chunk_size": 20,
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "render.invalid_request"
    assert "chunk" in error["message"].lower()
    assert error["context"]["chunk_size"] == 20


def test_submit_job_invalid_dcc_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        json={
            "dcc": "aftereffects",
            "scene": "shot_v003.aep",
            "output": "/tmp/renders",
            "farm": "mock",
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"][0]["loc"][-1] == "dcc"
