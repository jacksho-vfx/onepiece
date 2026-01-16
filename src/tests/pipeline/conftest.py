"""Reusable fixtures for pipeline-related tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from apps.trafalgar.pipeline import PipelineDefinition
from libraries.pipeline.models import Pipeline, PipelineStep, TriggerPolicy


@pytest.fixture
def pipeline_factory() -> Callable[[str, int], Pipeline]:
    """Create simple in-memory pipeline instances for testing."""

    def factory(name: str = "demo", step_count: int = 1) -> Pipeline:
        steps: list[PipelineStep] = []
        for index in range(step_count):
            step_name = f"step_{index + 1}"
            trigger = TriggerPolicy(depends_on=(steps[-1].name,) if steps else ())
            steps.append(
                PipelineStep(
                    name=step_name,
                    provider=f"provider.{step_name}",
                    trigger=trigger,
                )
            )
        return Pipeline(name=name, steps=steps)

    return factory


@pytest.fixture
def pipeline_definition_factory(
    pipeline_factory: Callable[[str, int], Pipeline],
) -> Callable[[str], PipelineDefinition]:
    """Build lightweight :class:`PipelineDefinition` instances."""

    def factory(name: str = "demo") -> PipelineDefinition:
        return PipelineDefinition(
            name=name,
            pipeline=pipeline_factory,
            display_name=f"Display {name.title()}",
            description=f"Definition for {name}",
            parameters={"sample": "value"},
        )

    return factory


@pytest.fixture
def mock_step_executor() -> (
    Callable[
        [str], tuple[list[tuple[tuple[Any, ...], dict[str, Any]]], Callable[..., None]]
    ]
):
    """Return a factory for capturing calls to mock pipeline step executors."""

    def factory(
        step_name: str,
    ) -> tuple[list[tuple[tuple[Any, ...], dict[str, Any]]], Callable[..., None]]:
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def executor(*args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

        executor.__name__ = f"mock_executor_{step_name}"
        return calls, executor

    return factory
