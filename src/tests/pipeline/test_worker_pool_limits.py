from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from threading import Event
from typing import Mapping
import time

import pytest

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    configure_orchestrator_from_profile,
    set_pipeline_orchestrator,
)
from apps.onepiece.config import ProfileContext
from libraries.pipeline.models import Pipeline, PipelineStep


def _make_orchestrator(
    max_workers: int,
) -> tuple[PipelineOrchestrator, Queue[tuple[int, float]], dict[int, Event]]:
    starts: Queue[tuple[int, float]] = Queue()
    releases: dict[int, Event] = defaultdict(Event)

    def _blocking_provider(parameters: Mapping[str, object]) -> None:
        index = int(parameters["index"])  # type: ignore[call-overload]
        starts.put((index, time.perf_counter()))
        releases[index].wait(timeout=5)

    pipeline = Pipeline(
        name="blocking",
        steps=[PipelineStep(name="wait", provider=_blocking_provider)],
    )
    definition = PipelineDefinition(name="blocking", pipeline=pipeline)
    worker_pool = ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="test-pipeline-runs"
    )
    orchestrator = PipelineOrchestrator((definition,), worker_pool=worker_pool)
    return orchestrator, starts, releases


def _wait_for_completion(
    orchestrator: PipelineOrchestrator, run_id: str, *, timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = orchestrator.get_run(run_id)
        if run.status in {"succeeded", "failed"}:
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for run '{run_id}' to complete")


def test_worker_pool_respects_single_worker_limit() -> None:
    orchestrator, starts, releases = _make_orchestrator(max_workers=1)

    try:
        first_run = orchestrator.trigger_run("blocking", parameters={"index": 1})
        first_started = starts.get(timeout=1.0)
        assert first_started[0] == 1

        second_run = orchestrator.trigger_run("blocking", parameters={"index": 2})
        with pytest.raises(Empty):
            starts.get(timeout=0.2)

        metrics = orchestrator.worker_pool_metrics()
        assert metrics.max_workers == 1
        assert metrics.active_workers == 1

        releases[1].set()
        second_started = starts.get(timeout=1.0)
        assert second_started[0] == 2
        releases[2].set()

        _wait_for_completion(orchestrator, first_run.run_id)
        _wait_for_completion(orchestrator, second_run.run_id)
    finally:
        orchestrator.shutdown()


def test_worker_pool_allows_parallel_runs() -> None:
    orchestrator, starts, releases = _make_orchestrator(max_workers=2)

    try:
        first_run = orchestrator.trigger_run("blocking", parameters={"index": 1})
        second_run = orchestrator.trigger_run("blocking", parameters={"index": 2})
        first_started = starts.get(timeout=1.0)
        second_started = starts.get(timeout=1.0)
        assert {first_started[0], second_started[0]} == {1, 2}

        metrics = orchestrator.worker_pool_metrics()
        assert metrics.max_workers == 2
        assert metrics.active_workers == 2

        releases[1].set()
        releases[2].set()

        _wait_for_completion(orchestrator, first_run.run_id)
        _wait_for_completion(orchestrator, second_run.run_id)
    finally:
        orchestrator.shutdown()


def test_configure_orchestrator_from_profile_uses_worker_limit() -> None:
    profile = ProfileContext(
        name="default",
        data={},
        pipelines={},
        pipeline_storage={},
        sources=(),
        pipeline_workers_max=3,
    )

    orchestrator = configure_orchestrator_from_profile(profile)
    try:
        metrics = orchestrator.worker_pool_metrics()
        assert metrics.max_workers == 3
        assert metrics.active_workers == 0
    finally:
        orchestrator.shutdown()
        set_pipeline_orchestrator(None)
