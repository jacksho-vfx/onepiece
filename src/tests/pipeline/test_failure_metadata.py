from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from fastapi.testclient import TestClient

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    PipelineRunStore,
    set_pipeline_orchestrator,
)
from apps.trafalgar.web import pipeline as pipeline_module
from apps.trafalgar.web.security import (
    DEFAULT_API_KEY_HEADER,
    DEFAULT_API_SECRET_HEADER,
)
from libraries.pipeline.models import Pipeline, PipelineStep


def _failing_provider(parameters: Mapping[str, object]) -> None:
    _ = parameters
    raise RuntimeError("intentional failure")


def _build_failing_definition() -> PipelineDefinition:
    pipeline = Pipeline(
        name="demo",
        steps=[PipelineStep(name="explode", provider=_failing_provider)],
    )
    return PipelineDefinition(name="demo", pipeline=pipeline)


def _wait_for_status(
    orchestrator: PipelineOrchestrator,
    run_id: str,
    *,
    status: str,
    timeout: float = 5.0,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = orchestrator.get_run(run_id)
        if run.status == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"Run '{run_id}' did not reach status '{status}' within timeout")


def _auth_headers() -> dict[str, str]:
    return {
        DEFAULT_API_KEY_HEADER: "suite-key",
        DEFAULT_API_SECRET_HEADER: "suite-secret",
    }


def test_failed_runs_expose_structured_error_metadata(tmp_path: Path) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    orchestrator = PipelineOrchestrator(store=store)
    orchestrator.register(_build_failing_definition())

    try:
        run = orchestrator.trigger_run("demo")
        _wait_for_status(orchestrator, run.run_id, status="failed")

        events = list(orchestrator.iter_run_events(run.run_id))
        failure_event = next(event for event in events if event.status == "failed")
        step_failure = next(event for event in events if event.status == "step_failed")

        for payload in (failure_event.parameters, step_failure.parameters):
            assert payload["error_type"] == "RuntimeError"
            assert payload["error_message"] == "intentional failure"
            assert "RuntimeError: intentional failure" in payload["traceback"]
    finally:
        orchestrator.shutdown()


def test_traceback_round_trip_through_pipeline_api(tmp_path: Path) -> None:
    set_pipeline_orchestrator(None)
    store = PipelineRunStore(database=tmp_path / "api.sqlite3")
    orchestrator = PipelineOrchestrator(store=store)
    orchestrator.register(_build_failing_definition())

    try:
        run = orchestrator.trigger_run("demo")
        _wait_for_status(orchestrator, run.run_id, status="failed")

        with TestClient(pipeline_module.app) as client:
            set_pipeline_orchestrator(orchestrator)
            response = client.get(
                f"/runs/{run.run_id}/events",
                headers=_auth_headers(),
            )
            assert response.status_code == 200
            payloads: list[dict[str, Any]] = []
            text = response.text
            for block in text.split("\n\n"):
                for line in block.splitlines():
                    if line.startswith("data: "):
                        payloads.append(json.loads(line[6:]))
            failure_payload = next(
                item for item in payloads if item.get("status") == "failed"
            )
            error_details = failure_payload.get("parameters", {})
            assert error_details["error_type"] == "RuntimeError"
            assert "RuntimeError: intentional failure" in error_details["traceback"]
    finally:
        orchestrator.shutdown()
        set_pipeline_orchestrator(None)
