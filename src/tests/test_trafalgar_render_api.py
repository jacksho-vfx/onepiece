from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.trafalgar.web import render as render_module


@pytest.fixture()
def client() -> TestClient:
    return TestClient(render_module.app)


def test_get_farms_lists_registered_adapters(client: TestClient) -> None:
    response = client.get("/farms")
    assert response.status_code == 200
    payload = response.json()
    farm_names = {farm["name"] for farm in payload["farms"]}
    assert "mock" in farm_names
    assert "deadline" in farm_names


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

    monkeypatch.setitem(render_module.FARM_ADAPTERS, "mock", fake_submit)

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
    assert payload["status"] == "not_implemented"
    assert payload["farm_type"] == "deadline"
    assert "not implemented" in payload["message"].lower()


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
