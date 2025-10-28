"""Tests for the Trafalgar pipeline API wiring."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    set_pipeline_orchestrator,
)
from apps.trafalgar.web import pipeline as pipeline_module
from apps.trafalgar.web import security as security_module
from apps.trafalgar.web.security import reset_security_state


@pytest.fixture(autouse=True)
def _reset_security_state() -> Iterator[None]:
    reset_security_state()
    yield
    reset_security_state()


@pytest.fixture(autouse=True)
def _configure_orchestrator() -> Iterator[PipelineOrchestrator]:
    orchestrator = PipelineOrchestrator(
        (
            PipelineDefinition(
                name="render_shots",
                display_name="Render Shots",
                description="Render queued shots with default settings.",
                parameters={"quality": "string", "priority": "int"},
            ),
            PipelineDefinition(
                name="publish_assets",
                display_name="Publish Assets",
                description="Publish ready assets to downstream systems.",
            ),
        )
    )
    set_pipeline_orchestrator(orchestrator)
    yield orchestrator
    set_pipeline_orchestrator(None)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(pipeline_module.app)


def _auth_headers() -> dict[str, str]:
    return {
        security_module.DEFAULT_API_KEY_HEADER: "suite-key",
        security_module.DEFAULT_API_SECRET_HEADER: "suite-secret",
    }


def test_list_pipelines_returns_registered_definitions(client: TestClient) -> None:
    response = client.get("/pipelines", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    names = [item["name"] for item in payload]
    assert names == sorted(names)
    render = next(item for item in payload if item["name"] == "render_shots")
    assert render["display_name"] == "Render Shots"
    assert "Render queued shots" in render["description"]
    assert set(render["parameters"]) == {"quality", "priority"}


def test_trigger_pipeline_run_returns_run_payload(client: TestClient) -> None:
    response = client.post(
        "/pipelines/render_shots/runs",
        headers=_auth_headers(),
        json={"parameters": {"quality": "high"}},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["pipeline"] == "render_shots"
    assert payload["parameters"] == {"quality": "high"}
    assert payload["status"] == "succeeded"
    assert "created_at" in payload


def test_stream_run_events_returns_status_sequence(client: TestClient) -> None:
    creation = client.post(
        "/pipelines/render_shots/runs",
        headers=_auth_headers(),
        json={"parameters": {"shot": "SQ01"}},
    )
    run_id = creation.json()["id"]

    with client.stream(
        "GET", f"/runs/{run_id}/events", headers=_auth_headers()
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events: list[dict[str, object]] = []
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.split("data: ", 1)[1])
            events.append(payload)
            if len(events) == 3:
                break

    statuses = [event["status"] for event in events]
    assert statuses == ["queued", "running", "succeeded"]
    assert all(event["id"] == run_id for event in events)
