from __future__ import annotations

from typing import Any, Callable, Iterable

import pytest

from libraries.pipeline import (
    ENTRY_POINT_GROUP,
    InvalidPipelineStepError,
    InvalidPipelineStepFactoryError,
    MissingPipelineStepRequirementError,
    PipelinePluginError,
    PipelineStep,
    discover_pipeline_step_factories,
)


class DummyEntryPoint:
    def __init__(self, name: str, *, loader: Callable[[], Any]) -> None:
        self.name = name
        self._loader = loader

    def load(self) -> Any:
        return self._loader()


class DummyEntryPoints(list[DummyEntryPoint]):
    def select(self, *, group: str) -> Iterable[DummyEntryPoint]:
        if group == ENTRY_POINT_GROUP:
            return list(self)
        return []


@pytest.fixture()
def entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[DummyEntryPoint, *DummyEntryPoint], None]:  # type: ignore[valid-type]
    holders: list[DummyEntryPoint] = []

    def factory() -> DummyEntryPoints:
        return DummyEntryPoints(holders)

    monkeypatch.setattr(
        "libraries.pipeline.plugins.metadata.entry_points",
        lambda: factory(),
    )

    def register(first: DummyEntryPoint, *rest: DummyEntryPoint) -> None:
        holders[:] = [first, *rest]

    return register


def test_discovery_merges_builtin_and_plugins(
    entry_points: Callable[[DummyEntryPoint], None],
) -> None:
    def builtin_factory(config: dict[str, Any]) -> dict[str, Any]:
        return config

    observed_config: dict[str, Any] | None = None

    def plugin_factory(config: dict[str, Any]) -> PipelineStep:
        nonlocal observed_config
        observed_config = dict(config)
        return PipelineStep.from_config({"name": "plugin-step", "provider": "dummy"})

    entry_points(
        DummyEntryPoint(
            "plugin-step",
            loader=lambda: plugin_factory,
        )
    )

    factories = discover_pipeline_step_factories(builtin={"builtin": builtin_factory})

    assert factories["builtin"] is builtin_factory
    assert factories["plugin-step"] is plugin_factory
    assert observed_config == {"name": "plugin-step", "provider": "plugin-step"}


def test_missing_dependency_raises_actionable_error(
    entry_points: Callable[[DummyEntryPoint], None],
) -> None:
    def loader() -> None:
        raise ModuleNotFoundError("cool-extra")

    entry_points(DummyEntryPoint("needs-extra", loader=loader))

    with pytest.raises(MissingPipelineStepRequirementError) as excinfo:
        discover_pipeline_step_factories()

    assert excinfo.value.step_name == "needs-extra"
    assert excinfo.value.requirement == "cool-extra"
    assert "requires the optional dependency" in str(excinfo.value)


def test_conflicting_entry_point_with_builtin_is_rejected(
    entry_points: Callable[[DummyEntryPoint], None],
) -> None:
    entry_points(
        DummyEntryPoint(
            "builtin",
            loader=lambda: lambda config: config,
        )
    )

    with pytest.raises(PipelinePluginError):
        discover_pipeline_step_factories(builtin={"builtin": lambda config: config})


def test_non_callable_factory_raises(
    entry_points: Callable[[DummyEntryPoint], None],
) -> None:
    entry_points(
        DummyEntryPoint(
            "broken",
            loader=lambda: object(),
        )
    )

    with pytest.raises(InvalidPipelineStepFactoryError):
        discover_pipeline_step_factories()


def test_factory_returning_wrong_type_is_rejected(
    entry_points: Callable[[DummyEntryPoint], None],
) -> None:
    def loader() -> Callable[[dict[str, Any]], str]:
        return lambda config: "not-a-pipeline-step"

    entry_points(DummyEntryPoint("not-a-step", loader=loader))

    with pytest.raises(InvalidPipelineStepError) as excinfo:
        discover_pipeline_step_factories()

    assert excinfo.value.step_name == "not-a-step"
    assert "PipelineStep instance" in str(excinfo.value)


def test_factory_exception_is_wrapped(
    entry_points: Callable[[DummyEntryPoint], None],
) -> None:
    def loader() -> Callable[[dict[str, Any]], PipelineStep]:
        def factory(config: dict[str, Any]) -> PipelineStep:
            raise RuntimeError(f"bad config {config!r}")

        return factory

    entry_points(DummyEntryPoint("explode", loader=loader))

    with pytest.raises(PipelinePluginError) as excinfo:
        discover_pipeline_step_factories()

    assert "factory raised an exception" in str(excinfo.value)
