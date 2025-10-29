"""Tests for the Trafalgar pipeline API wiring."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from apps.onepiece.config import ProfileContext, load_profile
from apps.trafalgar.pipeline import set_pipeline_orchestrator
from apps.trafalgar.web import pipeline as pipeline_module
from apps.trafalgar.web import security as security_module
from apps.trafalgar.web.security import reset_security_state


@pytest.fixture(autouse=True)
def _reset_security_state() -> Iterator[None]:
    reset_security_state()
    yield
    reset_security_state()


def _write_pipeline_config(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            [pipelines.render_shots]
            display_name = "Render Shots"
            description = "Render queued shots with default settings."

            [[pipelines.render_shots.steps]]
            name = "prepare"
            provider = "tests.pipeline:prepare"

            [[pipelines.render_shots.steps]]
            name = "render"
            provider = "tests.pipeline:render"

            [pipelines.render_shots.parameters]
            quality = "string"
            priority = "int"

            [pipelines.publish_assets]
            display_name = "Publish Assets"
            description = "Publish ready assets to downstream systems."

            [[pipelines.publish_assets.steps]]
            name = "publish"
            provider = "tests.pipeline:publish"
            """
        ).strip()
        + "\n"
    )


@pytest.fixture()
def profile_context(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> Iterator[ProfileContext]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / "onepiece.toml"
    _write_pipeline_config(config_path)

    monkeypatch.setenv("ONEPIECE_PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ONEPIECE_PROFILE", raising=False)

    context = load_profile()
    yield context

    set_pipeline_orchestrator(None)
    monkeypatch.delenv("ONEPIECE_PROJECT_ROOT", raising=False)


@pytest.fixture()
def client(profile_context: ProfileContext) -> Iterator[TestClient]:
    set_pipeline_orchestrator(None)
    with TestClient(pipeline_module.app) as instance:
        yield instance
    set_pipeline_orchestrator(None)


def _auth_headers() -> dict[str, str]:
    return {
        security_module.DEFAULT_API_KEY_HEADER: "suite-key",
        security_module.DEFAULT_API_SECRET_HEADER: "suite-secret",
    }


def test_list_pipelines_returns_registered_definitions(
    client: TestClient, profile_context: ProfileContext
) -> None:
    response = client.get("/pipelines", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    names = [item["name"] for item in payload]
    assert names == sorted(names)
    render = next(item for item in payload if item["name"] == "render_shots")
    assert render["display_name"] == "Render Shots"
    assert "Render queued shots" in render["description"]
    assert set(render["parameters"]) == {"quality", "priority"}
    assert set(names) == set(profile_context.pipelines)


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
