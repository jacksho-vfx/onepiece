"""Tests for the Trafalgar pipeline API wiring."""

from __future__ import annotations

import asyncio
import json
import textwrap
import threading
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from apps.onepiece.config import ProfileContext, load_profile
from apps.trafalgar.pipeline import (
    PipelineRetentionPolicy,
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

            [pipelines.render_shots.parameters.quality]
            default = "string"
            description = "Quality preset"

            [pipelines.render_shots.parameters.priority]
            default = "int"

            [pipelines.render_shots.parameters.shot]
            required = true
            description = "Shot identifier"

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
    updated_at: datetime | None = None,
) -> None:
    orchestrator = get_pipeline_orchestrator()
    store = orchestrator._store
    finished_at = updated_at or created_at
    store.create_run(
        PipelineRun(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            created_at=created_at,
            updated_at=finished_at,
            parameters={},
            definition_snapshot={"name": pipeline, "steps": []},
        ),
        PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=finished_at,
            parameters={},
        ),
    )


def _pipeline_submission(
    name: str = "custom_pipeline", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "display_name": "Custom Pipeline",
        "description": "Test pipeline",
        "metadata": {"owner": "pipeline"},
        "parameters": {"priority": "int"},
        "steps": [
            {"name": "prepare", "provider": "tests.pipeline:prepare"},
            {"name": "publish", "provider": "tests.pipeline:publish"},
        ],
    }
    payload.update(overrides)
    return payload


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
    assert set(render["parameters"]) == {"quality", "priority", "shot"}
    assert render["parameters"]["quality"]["default"] == "string"
    assert render["parameters"]["quality"]["description"] == "Quality preset"
    assert render["parameters"]["shot"]["required"] is True
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


def test_create_pipeline_registers_definition(client: TestClient) -> None:
    payload = _pipeline_submission()

    response = client.post("/pipelines", headers=_auth_headers(), json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == payload["name"]
    orchestrator = get_pipeline_orchestrator()
    stored = orchestrator.get_pipeline(payload["name"])
    assert stored.display_name == payload["display_name"]

    conflict = client.post("/pipelines", headers=_auth_headers(), json=payload)
    assert conflict.status_code == 409

    client.delete(f"/pipelines/{payload['name']}", headers=_auth_headers())


def test_create_pipeline_allows_translated_synonyms(client: TestClient) -> None:
    payload = _pipeline_submission(description=None)
    payload.update({"summary": "Pipeline summary", "version": "1"})

    response = client.post("/pipelines", headers=_auth_headers(), json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["description"] == "Pipeline summary"

    client.delete(f"/pipelines/{payload['name']}", headers=_auth_headers())


def test_create_pipeline_rejects_unexpected_fields(client: TestClient) -> None:
    payload = _pipeline_submission()
    payload.update({"summery": "typo", "stepp": []})

    response = client.post("/pipelines", headers=_auth_headers(), json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Unexpected fields: stepp, summery"


def test_update_pipeline_replaces_definition(client: TestClient) -> None:
    payload = _pipeline_submission("revision_pipeline")
    creation = client.post("/pipelines", headers=_auth_headers(), json=payload)
    assert creation.status_code == 201

    updated = _pipeline_submission(
        "revision_pipeline",
        description="Updated",
        metadata={"owner": "pipeline", "revision": 2},
        steps=[
            {"name": "seed", "provider": "tests.pipeline:prepare"},
            {"name": "publish", "provider": "tests.pipeline:publish"},
            {
                "name": "notify",
                "provider": "tests.pipeline:notify",
                "trigger": {"depends_on": ["publish"], "kind": "sequential"},
            },
        ],
    )

    response = client.put(
        "/pipelines/revision_pipeline",
        headers=_auth_headers(),
        json=updated,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["description"] == "Updated"
    assert payload["metadata"]["revision"] == 2

    orchestrator = get_pipeline_orchestrator()
    stored = orchestrator.get_pipeline("revision_pipeline")
    assert stored.description == "Updated"
    assert stored.pipeline.metadata["revision"] == 2
    assert [step.name for step in stored.pipeline.steps] == [
        "seed",
        "publish",
        "notify",
    ]

    client.delete("/pipelines/revision_pipeline", headers=_auth_headers())


def test_update_pipeline_rejects_name_mismatch(client: TestClient) -> None:
    payload = _pipeline_submission("mismatch_pipeline")
    response = client.put(
        "/pipelines/other_pipeline",
        headers=_auth_headers(),
        json=payload,
    )

    assert response.status_code == 400


def test_delete_pipeline_removes_definition(client: TestClient) -> None:
    payload = _pipeline_submission("temporary_pipeline")
    creation = client.post("/pipelines", headers=_auth_headers(), json=payload)
    assert creation.status_code == 201

    response = client.delete("/pipelines/temporary_pipeline", headers=_auth_headers())

    assert response.status_code == 204
    orchestrator = get_pipeline_orchestrator()
    with pytest.raises(KeyError):
        orchestrator.get_pipeline("temporary_pipeline")

    missing = client.delete("/pipelines/temporary_pipeline", headers=_auth_headers())
    assert missing.status_code == 404


def test_trigger_pipeline_run_returns_run_payload(client: TestClient) -> None:
    response = client.post(
        "/pipelines/render_shots/runs",
        headers=_auth_headers(),
        json={"parameters": {"quality": "high", "shot": "SQ01"}},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["pipeline"] == "render_shots"
    assert payload["parameters"] == {
        "quality": "high",
        "priority": "int",
        "shot": "SQ01",
    }
    assert payload["status"] == "running"
    assert "created_at" in payload
    assert payload["submitted_by"] == "suite"
    assert "pipeline:run" in payload.get("roles", [])


def test_trigger_pipeline_run_rejects_missing_required_parameter(
    client: TestClient,
) -> None:
    response = client.post(
        "/pipelines/render_shots/runs",
        headers=_auth_headers(),
        json={"parameters": {"quality": "high"}},
    )

    assert response.status_code == 400
    assert "requires parameter 'shot'" in response.json()["detail"]


def test_trigger_pipeline_run_rejects_unknown_parameter(client: TestClient) -> None:
    response = client.post(
        "/pipelines/render_shots/runs",
        headers=_auth_headers(),
        json={"parameters": {"shot": "SQ01", "unknown": "value"}},
    )

    assert response.status_code == 400
    assert "does not define parameters" in response.json()["detail"]


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
            definition_snapshot={"name": "render_shots", "steps": []},
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


class _SerializableEvent:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def serialise(self) -> dict[str, Any]:
        return self._payload


def test_live_event_stream_emits_heartbeats(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "_HEARTBEAT_INTERVAL", 0.01)

    async def _event_source() -> AsyncIterator[_SerializableEvent]:
        await asyncio.sleep(0.03)
        yield _SerializableEvent({"id": "run-1", "status": "running"})
        await asyncio.sleep(0.03)
        yield _SerializableEvent({"id": "run-1", "status": "succeeded"})

    async def _exercise() -> None:
        stream = pipeline_module._live_event_stream(_event_source())

        outputs: list[bytes] = []
        while True:
            try:
                item = await asyncio.wait_for(stream.__anext__(), timeout=1)
            except StopAsyncIteration:
                break
            outputs.append(item)

        assert outputs
        assert outputs[0] == pipeline_module._HEARTBEAT_COMMENT

        events = [chunk for chunk in outputs if chunk.startswith(b"data: ")]
        assert [json.loads(chunk.split(b"data: ", 1)[1]) for chunk in events] == [
            {"id": "run-1", "status": "running"},
            {"id": "run-1", "status": "succeeded"},
        ]

        running_index = outputs.index(events[0])
        succeeded_index = outputs.index(events[1])

        assert any(
            chunk == pipeline_module._HEARTBEAT_COMMENT
            for chunk in outputs[:running_index]
        )
        assert any(
            chunk == pipeline_module._HEARTBEAT_COMMENT
            for chunk in outputs[running_index + 1 : succeeded_index]
        )

    asyncio.run(_exercise())


def test_live_event_stream_honours_cancellation(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "_HEARTBEAT_INTERVAL", 0.05)

    cancelled = False

    async def _slow_events() -> AsyncIterator[_SerializableEvent]:
        nonlocal cancelled
        try:
            while True:
                await asyncio.sleep(1)
                yield _SerializableEvent({"id": "run-2", "status": "running"})
        except asyncio.CancelledError:
            cancelled = True
            raise

    async def _exercise() -> None:
        stream = pipeline_module._live_event_stream(_slow_events())

        first = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert first == pipeline_module._HEARTBEAT_COMMENT

        pending = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        await stream.aclose()
        assert cancelled

    asyncio.run(_exercise())


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


def test_run_stats_endpoint_returns_grouped_counts(client: TestClient) -> None:
    base = datetime(2024, 5, 1, 12, tzinfo=timezone.utc)
    _seed_run(
        run_id="run-1",
        pipeline="render_shots",
        status="succeeded",
        created_at=base,
        updated_at=base + timedelta(minutes=2),
    )
    _seed_run(
        run_id="run-2",
        pipeline="render_shots",
        status="failed",
        created_at=base + timedelta(minutes=5),
        updated_at=base + timedelta(minutes=7),
    )
    _seed_run(
        run_id="run-3",
        pipeline="publish_assets",
        status="succeeded",
        created_at=base + timedelta(minutes=10),
        updated_at=base + timedelta(minutes=12),
    )

    response = client.get("/runs/stats", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipelines"]["render_shots"]["failed"] == {"count": 1}
    assert payload["pipelines"]["render_shots"]["succeeded"] == {"count": 1}
    assert payload["pipelines"]["publish_assets"] == {"succeeded": {"count": 1}}


def test_run_stats_endpoint_includes_durations(client: TestClient) -> None:
    base = datetime(2024, 6, 1, 8, tzinfo=timezone.utc)
    orchestrator = get_pipeline_orchestrator()
    store = orchestrator._store

    def _enqueue_success(
        run_id: str,
        *,
        created_at: datetime,
        wait_seconds: int,
        finish_offset_seconds: int,
    ) -> None:
        run = PipelineRun(
            run_id=run_id,
            pipeline="render_shots",
            status="queued",
            created_at=created_at,
            updated_at=created_at,
            parameters={},
            definition_snapshot={"name": "render_shots", "steps": []},
        )
        store.create_run(
            run,
            PipelineRunEvent(
                run_id=run_id,
                pipeline="render_shots",
                status="queued",
                timestamp=created_at,
                parameters={},
            ),
        )
        store.append_event(
            run_id,
            status="running",
            timestamp=created_at + timedelta(seconds=wait_seconds),
            parameters={},
            run_status="running",
        )
        store.append_event(
            run_id,
            status="succeeded",
            timestamp=created_at + timedelta(seconds=finish_offset_seconds),
            parameters={},
            run_status="succeeded",
        )

    _enqueue_success(
        "run-1",
        created_at=base,
        wait_seconds=5,
        finish_offset_seconds=20,
    )
    _enqueue_success(
        "run-2",
        created_at=base + timedelta(seconds=20),
        wait_seconds=30,
        finish_offset_seconds=50,
    )

    queued_created = base + timedelta(minutes=2)
    store.create_run(
        PipelineRun(
            run_id="run-backlog",
            pipeline="render_shots",
            status="queued",
            created_at=queued_created,
            updated_at=queued_created,
            parameters={},
            definition_snapshot={"name": "render_shots", "steps": []},
        ),
        PipelineRunEvent(
            run_id="run-backlog",
            pipeline="render_shots",
            status="queued",
            timestamp=queued_created,
            parameters={},
        ),
    )

    response = client.get(
        "/runs/stats",
        headers=_auth_headers(),
        params={"include_durations": "true", "since": base.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    pipeline_stats = payload["pipelines"]["render_shots"]
    stats = pipeline_stats["succeeded"]
    assert stats["count"] == 2
    durations = stats["durations"]
    assert durations["min_seconds"] == 20.0
    assert durations["max_seconds"] == 50.0
    assert durations["average_seconds"] == 35.0
    waits = stats["queue_waits"]
    assert waits["min_seconds"] == 5.0
    assert waits["max_seconds"] == 30.0
    assert waits["average_seconds"] == pytest.approx(17.5)

    queued_stats = pipeline_stats["queued"]
    assert queued_stats["backlog_count"] == 1


def test_run_stats_endpoint_validates_since_parameter(client: TestClient) -> None:
    response = client.get(
        "/runs/stats",
        headers=_auth_headers(),
        params={"since": "not-a-timestamp"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Invalid 'since' timestamp"


def test_prune_runs_endpoint_applies_retention(client: TestClient) -> None:
    orchestrator = get_pipeline_orchestrator()
    orchestrator._retention = PipelineRetentionPolicy(
        max_age=timedelta(days=1), max_runs=1
    )

    now = datetime.now(timezone.utc)
    _seed_run(
        run_id="run-old",
        pipeline="render_shots",
        status="succeeded",
        created_at=now - timedelta(days=2),
    )
    _seed_run(
        run_id="run-recent",
        pipeline="render_shots",
        status="succeeded",
        created_at=now - timedelta(hours=1),
    )

    response = client.post("/runs/prune", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["removed_runs"] == 1
    assert payload["remaining_runs"] == 1
    assert payload["max_runs"] == 1
    assert payload["max_age_seconds"] == 86400

    runs = orchestrator.list_runs()
    assert [run.run_id for run in runs] == ["run-recent"]
