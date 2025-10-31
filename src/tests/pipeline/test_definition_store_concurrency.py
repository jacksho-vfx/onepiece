"""Regression tests for the pipeline definition store's file locking."""

from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineDefinitionStore,
)
from libraries.pipeline.models import Pipeline, PipelineStep


def _persist_definitions(path: str, prefix: str, iterations: int) -> None:
    store = PipelineDefinitionStore(path=path)
    pipeline = Pipeline(
        name=f"{prefix}-pipeline",
        steps=[PipelineStep(name="only", provider="demo.provider")],
    )
    for index in range(iterations):
        definition = PipelineDefinition(name=f"{prefix}-{index}", pipeline=pipeline)
        store.save(definition)


def test_definition_store_serialises_concurrent_saves(tmp_path: Path) -> None:
    store_path = tmp_path / "definitions.json"

    workers = []
    expected_names: set[str] = set()
    iterations = 5
    ctx = get_context("spawn")
    for worker_index in range(4):
        prefix = f"worker-{worker_index}"
        expected_names.update({f"{prefix}-{index}" for index in range(iterations)})
        process = ctx.Process(
            target=_persist_definitions,
            args=(str(store_path), prefix, iterations),
        )
        workers.append(process)
        process.start()

    for process in workers:
        process.join(timeout=10)
        assert process.exitcode == 0, "worker process failed"

    store = PipelineDefinitionStore(path=store_path)
    persisted_names = {definition.name for definition in store.list_definitions()}
    assert persisted_names == expected_names
