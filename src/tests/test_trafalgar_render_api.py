from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.trafalgar.web import render as render_module
from libraries.render.base import RenderAdapterUnavailableError


@pytest.fixture()
def client() -> TestClient:
    return TestClient(render_module.app)


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
    farms = {farm["name"]: farm for farm in response.json()["farms"]}

    expected = {
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
        capabilities = farm["capabilities"]
        priority = capabilities["priority"]
        assert priority["default"] == expectation["priority"]["default"]
        assert priority["minimum"] == expectation["priority"]["minimum"]
        assert priority["maximum"] == expectation["priority"]["maximum"]

        chunking = capabilities["chunking"]
        assert chunking["enabled"] == expectation["chunking"]["enabled"]
        assert chunking["minimum"] == expectation["chunking"]["minimum"]
        assert chunking["maximum"] == expectation["chunking"]["maximum"]
        assert chunking["default"] == expectation["chunking"]["default"]

        cancellation = capabilities["cancellation"]
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

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "render.farm_not_found"
    assert error["context"]["farm"] == "mock"


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
