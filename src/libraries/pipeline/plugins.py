"""Plugin loading helpers for pipeline step factories."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import metadata
from typing import Any, Protocol

from .models import PipelineStep

ENTRY_POINT_GROUP = "onepiece.pipeline_steps"


class PipelinePluginError(RuntimeError):
    """Base error for plugin related issues."""


class MissingPipelineStepRequirementError(PipelinePluginError):
    """Raised when an optional dependency required by a plugin is missing."""

    def __init__(self, *, step_name: str, requirement: str, original: Exception) -> None:
        self.step_name = step_name
        self.requirement = requirement
        message = (
            f"pipeline step '{step_name}' requires the optional dependency "
            f"'{requirement}' to be installed"
        )
        super().__init__(message)
        self.__cause__ = original


class InvalidPipelineStepFactoryError(PipelinePluginError):
    """Raised when a loaded entry point does not provide a valid factory."""

    def __init__(self, *, step_name: str, factory: Any) -> None:
        self.step_name = step_name
        self.factory = factory
        message = (
            f"pipeline step '{step_name}' must expose a callable factory, "
            f"received {type(factory)!r}"
        )
        super().__init__(message)


class PipelineStepFactory(Protocol):
    """Callable converting configuration mappings into :class:`PipelineStep` objects."""

    def __call__(self, config: Mapping[str, Any]) -> PipelineStep:  # pragma: no cover - Protocol definition
        """Create a :class:`PipelineStep` from ``config``."""


def _iter_entry_points(group: str):
    """Return an iterable of entry points for ``group`` supporting both metadata APIs."""

    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return entry_points.select(group=group)
    return entry_points.get(group, [])  # type: ignore[return-value]


def _missing_requirement(exc: Exception) -> str:
    name = getattr(exc, "name", None)
    if isinstance(name, str) and name:
        return name

    message = str(exc)
    if message.startswith("No module named '") and message.endswith("'"):
        return message.split("'", 2)[1]
    return message


def discover_pipeline_step_factories(
    *,
    builtin: Mapping[str, PipelineStepFactory] | None = None,
    group: str = ENTRY_POINT_GROUP,
) -> dict[str, PipelineStepFactory]:
    """Return registered pipeline step factories from entry points.

    Parameters
    ----------
    builtin:
        Mapping of built-in factories that cannot be overridden by third party
        entry points.
    group:
        Entry-point group to discover. Defaults to :data:`ENTRY_POINT_GROUP`.
    """

    registry: dict[str, PipelineStepFactory] = dict(builtin or {})

    for entry_point in _iter_entry_points(group):
        name = entry_point.name
        if name in registry:
            msg = (
                f"pipeline step '{name}' conflicts with an existing implementation; "
                "use a unique entry point name"
            )
            raise PipelinePluginError(msg)

        try:
            loaded = entry_point.load()
        except metadata.PackageNotFoundError as exc:
            requirement = _missing_requirement(exc)
            raise MissingPipelineStepRequirementError(
                step_name=name,
                requirement=requirement,
                original=exc,
            ) from exc
        except ModuleNotFoundError as exc:
            requirement = _missing_requirement(exc)
            raise MissingPipelineStepRequirementError(
                step_name=name,
                requirement=requirement,
                original=exc,
            ) from exc
        except ImportError as exc:
            msg = f"pipeline step '{name}' could not be imported: {exc}"
            raise PipelinePluginError(msg) from exc

        if not isinstance(loaded, Callable):
            raise InvalidPipelineStepFactoryError(step_name=name, factory=loaded)

        registry[name] = loaded

    return registry
