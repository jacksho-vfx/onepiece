"""Tests for the Trafalgar pipeline API wiring."""

from __future__ import annotations

import json
import textwrap
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from apps.onepiece.config import ProfileContext, load_profile
from apps.trafalgar.pipeline import (
    PipelineRun,
    PipelineRunEvent,
    get_pipeline_orchestrator,
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

            [[pipelines.render_shots.steps]]
            name = "notify"
            provider = "tests.pipeline:notify"

            [pipelines.render_shots.steps.trigger]
            kind = "event"
            event = "render.completed"
            depends_on = ["render"]

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


def _parse_stream_events(payload: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in payload.splitlines():
        if not line or not line.startswith("data: "):
            continue
        events.append(json.loads(line.split("data: ", 1)[1]))
    return events


def _seed_run(
    *,
    run_id: str,
    pipeline: str,
    status: str,
    created_at: datetime,
) -> None:
    orchestrator = get_pipeline_orchestrator()
    store = orchestrator._store
    store.create_run(
        PipelineRun(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            parameters={},
        ),
        PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=created_at,
            parameters={},
        ),
    )


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


def test_list_pipelines_includes_step_metadata(client: TestClient) -> None:
    response = client.get("/pipelines", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    render = next(item for item in payload if item["name"] == "render_shots")

    steps = render["steps"]
    assert [step["name"] for step in steps] == ["prepare", "render", "notify"]

    providers = render["providers"]
    assert providers == {
        "prepare": "tests.pipeline:prepare",
        "render": "tests.pipeline:render",
        "notify": "tests.pipeline:notify",
    }

    graph = render["dependency_graph"]
    assert graph["prepare"] == []
    assert graph["render"] == ["prepare"]
    assert graph["notify"] == ["render"]

    triggers = {step["name"]: step["trigger"] for step in steps}
    assert triggers["prepare"]["kind"] == "sequential"
    assert triggers["render"]["depends_on"] == ["prepare"]
    assert triggers["notify"] == {
        "kind": "event",
        "depends_on": ["render"],
        "event": "render.completed",
        "filters": {},
    }


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

    response = client.get(f"/runs/{run_id}/events", headers=_auth_headers())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_stream_events(response.text)

    statuses = [event["status"] for event in events]
    assert statuses == ["queued", "running", "succeeded"]
    assert all(event["id"] == run_id for event in events)


def test_stream_run_events_delivers_live_updates(client: TestClient) -> None:
    orchestrator = get_pipeline_orchestrator()
    store = orchestrator._store
    run_id = "live-run"
    base = datetime.now(timezone.utc)
    store.create_run(
        PipelineRun(
            run_id=run_id,
            pipeline="render_shots",
            status="queued",
            created_at=base,
            updated_at=base,
            parameters={},
        ),
        PipelineRunEvent(
            run_id=run_id,
            pipeline="render_shots",
            status="queued",
            timestamp=base,
            parameters={},
        ),
    )

    def _publish() -> None:
        time.sleep(0.05)
        store.append_event(
            run_id,
            status="running",
            timestamp=base + timedelta(seconds=1),
            parameters={},
            run_status="running",
        )
        time.sleep(0.05)
        store.append_event(
            run_id,
            status="succeeded",
            timestamp=base + timedelta(seconds=2),
            parameters={},
            run_status="succeeded",
        )

    publisher = threading.Thread(target=_publish)
    publisher.start()
    response = client.get(f"/runs/{run_id}/events", headers=_auth_headers())
    publisher.join(timeout=1)
    assert not publisher.is_alive()

    events = _parse_stream_events(response.text)
    statuses = [event["status"] for event in events if event["id"] == run_id]
    assert statuses == ["queued", "running", "succeeded"]


def test_describe_pipeline_returns_enriched_metadata(client: TestClient) -> None:
    response = client.get("/pipelines/render_shots", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()

    assert payload["name"] == "render_shots"
    assert payload["providers"]["notify"] == "tests.pipeline:notify"
    assert payload["dependency_graph"]["render"] == ["prepare"]

    notify_trigger = next(
        step["trigger"] for step in payload["steps"] if step["name"] == "notify"
    )
    assert notify_trigger == {
        "kind": "event",
        "depends_on": ["render"],
        "event": "render.completed",
        "filters": {},
    }


def test_list_runs_endpoint_supports_filters(client: TestClient) -> None:
    base = datetime(2024, 3, 1, 9, tzinfo=timezone.utc)
    _seed_run(
        run_id="run-a", pipeline="render_shots", status="succeeded", created_at=base
    )
    _seed_run(
        run_id="run-b",
        pipeline="render_shots",
        status="failed",
        created_at=base + timedelta(hours=1),
    )
    _seed_run(
        run_id="run-c",
        pipeline="publish_assets",
        status="succeeded",
        created_at=base + timedelta(hours=2),
    )

    response = client.get("/runs", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["run-c", "run-b", "run-a"]

    response = client.get(
        "/runs", headers=_auth_headers(), params={"pipeline": "render_shots"}
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["run-b", "run-a"]

    response = client.get("/runs", headers=_auth_headers(), params={"status": "failed"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["run-b"]

    since_iso = (base + timedelta(hours=1)).isoformat()
    response = client.get("/runs", headers=_auth_headers(), params={"since": since_iso})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["run-c", "run-b"]

    response = client.get("/runs", headers=_auth_headers(), params={"limit": 1})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["run-c"]


def test_list_runs_endpoint_validates_since_parameter(client: TestClient) -> None:
    response = client.get("/runs", headers=_auth_headers(), params={"since": "invalid"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Invalid 'since' timestamp"
