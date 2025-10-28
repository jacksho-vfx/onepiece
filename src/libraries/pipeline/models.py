"""Dataclasses describing pipeline structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


def _normalise_dependencies(dependencies: Sequence[str] | str | None) -> tuple[str, ...]:
    if dependencies is None:
        return ()
    if isinstance(dependencies, str):
        return (dependencies,)
    return tuple(dependencies)


@dataclass(slots=True)
class TriggerPolicy:
    """Definition of how and when a pipeline step should execute."""

    kind: str = "sequential"
    depends_on: Sequence[str] = field(default_factory=tuple)
    event: str | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = self.kind.lower()
        if kind not in {"sequential", "event"}:
            msg = "trigger kind must be 'sequential' or 'event'"
            raise ValueError(msg)
        if kind == "event" and not self.event:
            msg = "event-driven triggers require an event name"
            raise ValueError(msg)
        if kind == "sequential" and self.event is not None:
            msg = "sequential triggers cannot define an event"
            raise ValueError(msg)

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "depends_on", _normalise_dependencies(self.depends_on))
        object.__setattr__(self, "filters", dict(self.filters))

    @property
    def is_sequential(self) -> bool:
        return self.kind == "sequential"

    @property
    def is_event_driven(self) -> bool:
        return self.kind == "event"

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None,
        *,
        default_dependency: str | None = None,
    ) -> "TriggerPolicy":
        if config is None:
            depends_on: Sequence[str] | str | None = (
                default_dependency if default_dependency is not None else ()
            )
            return cls(
                kind="sequential",
                depends_on=_normalise_dependencies(depends_on),
            )

        if not isinstance(config, Mapping):
            msg = "trigger configuration must be a mapping"
            raise TypeError(msg)

        kind = str(
            config.get("kind")
            or config.get("mode")
            or config.get("type")
            or "sequential"
        )

        depends_on = config.get("depends_on")
        if depends_on is None and default_dependency and kind.lower() == "sequential":
            depends_on = (default_dependency,)

        event = config.get("event")
        filters = config.get("filters") or {}
        return cls(
            kind=kind,
            depends_on=_normalise_dependencies(depends_on),
            event=event,
            filters=filters,
        )


@dataclass(slots=True)
class PipelineStep:
    """A single pipeline step and its execution policy."""

    name: str
    provider: Any
    config: Mapping[str, Any] = field(default_factory=dict)
    trigger: TriggerPolicy = field(default_factory=TriggerPolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            msg = "pipeline steps require a name"
            raise ValueError(msg)
        if not isinstance(self.trigger, TriggerPolicy):
            msg = "trigger must be a TriggerPolicy instance"
            raise TypeError(msg)

        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        default_dependency: str | None = None,
    ) -> "PipelineStep":
        if "name" not in config:
            msg = "step configuration missing 'name'"
            raise KeyError(msg)
        if "provider" not in config:
            msg = "step configuration missing 'provider'"
            raise KeyError(msg)

        trigger_cfg = config.get("trigger")
        trigger = TriggerPolicy.from_config(
            trigger_cfg,
            default_dependency=default_dependency,
        )

        return cls(
            name=str(config["name"]),
            provider=config["provider"],
            config=config.get("config", {}),
            trigger=trigger,
            metadata=config.get("metadata", {}),
        )


@dataclass(slots=True)
class Pipeline:
    """Collection of pipeline steps with shared metadata."""

    name: str
    steps: Sequence[PipelineStep]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            msg = "pipelines require a name"
            raise ValueError(msg)
        if not self.steps:
            msg = "pipelines require at least one step"
            raise ValueError(msg)

        steps_tuple = tuple(self.steps)
        object.__setattr__(self, "steps", steps_tuple)
        object.__setattr__(self, "metadata", dict(self.metadata))

        names = [step.name for step in steps_tuple]
        if len(names) != len(set(names)):
            msg = "pipeline step names must be unique"
            raise ValueError(msg)

        name_set = set(names)
        for step in steps_tuple:
            for dependency in step.trigger.depends_on:
                if dependency not in name_set:
                    msg = f"step '{step.name}' references unknown dependency '{dependency}'"
                    raise ValueError(msg)
                if dependency == step.name:
                    msg = f"step '{step.name}' cannot depend on itself"
                    raise ValueError(msg)

    def get_step(self, name: str) -> PipelineStep:
        for step in self.steps:
            if step.name == name:
                return step
        msg = f"pipeline '{self.name}' has no step '{name}'"
        raise KeyError(msg)

    def sequential_order(self) -> Iterable[PipelineStep]:
        return (step for step in self.steps if step.trigger.is_sequential)
