"""Regression tests for streaming pipeline run events."""

from __future__ import annotations

from typing import Mapping

from apps.onepiece.pipeline import LocalPipelineClient
from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    PipelineRunStore,
    set_pipeline_orchestrator,
)
from libraries.pipeline.models import Pipeline, PipelineStep


def _build_pipeline() -> PipelineDefinition:
    def _provider(parameters: Mapping[str, object]) -> None:
        _ = parameters

    pipeline = Pipeline(
        name="demo",
        steps=[PipelineStep(name="initial", provider=_provider)],
    )
    return PipelineDefinition(name="demo", pipeline=pipeline)


def test_local_client_stream_events_without_running_loop() -> None:
    set_pipeline_orchestrator(None)
    store = PipelineRunStore()
    orchestrator = PipelineOrchestrator(store=store)
    orchestrator.register(_build_pipeline())
    set_pipeline_orchestrator(orchestrator)

    client = LocalPipelineClient()
    try:
        run = client.trigger_run("demo", parameters={})
        statuses = [payload["status"] for payload in client.stream_events(run["id"])]
        assert statuses[:2] == ["queued", "running"]
    finally:
        client.close()
        set_pipeline_orchestrator(None)


def test_local_client_stream_events_resume_from_cursor() -> None:
    set_pipeline_orchestrator(None)
    store = PipelineRunStore()
    orchestrator = PipelineOrchestrator(store=store)
    orchestrator.register(_build_pipeline())
    set_pipeline_orchestrator(orchestrator)

    client = LocalPipelineClient()
    try:
        run = client.trigger_run("demo", parameters={})
        initial_events = list(client.stream_events(run["id"]))
        assert initial_events
        first_event = initial_events[0]
        assert "event_id" in first_event

        resumed_from_id = list(
            client.stream_events(run["id"], resume_from=str(first_event["event_id"]))
        )
        assert [event["status"] for event in resumed_from_id] == [
            payload["status"] for payload in initial_events[1:]
        ]

        resumed_from_time = list(
            client.stream_events(run["id"], resume_from=first_event["timestamp"])
        )
        assert [event["status"] for event in resumed_from_time] == [
            payload["status"] for payload in initial_events[1:]
        ]
    finally:
        client.close()
        set_pipeline_orchestrator(None)
