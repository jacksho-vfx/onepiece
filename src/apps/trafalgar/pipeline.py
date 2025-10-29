"""Pipeline orchestration helpers shared across Trafalgar services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator, Iterable, Iterator, Mapping

import json
import sqlite3
import uuid

from apps.onepiece.config import ProfileContext
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.factories import pipeline_from_config
from libraries.pipeline.models import Pipeline, PipelineStep


@dataclass(slots=True)
class PipelineDefinition:
    """A lightweight description of a runnable pipeline."""

    name: str
    pipeline: Pipeline
    display_name: str | None = None
    description: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if not self.name:
            msg = "pipeline definitions require a name"
            raise ValueError(msg)
        if not isinstance(self.pipeline, Pipeline):
            msg = "pipeline definitions require a Pipeline instance"
            raise TypeError(msg)
        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        else:
            object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        steps = [self._serialise_step(step) for step in self.pipeline.steps]
        providers = {step["name"]: step["provider"] for step in steps}
        dependency_graph = {
            step["name"]: step["trigger"]["depends_on"] for step in steps
        }

        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "parameters": dict(self.parameters),
            "metadata": dict(self.pipeline.metadata),
            "steps": steps,
            "providers": providers,
            "dependency_graph": dependency_graph,
        }

    def _serialise_step(self, step: PipelineStep) -> Mapping[str, Any]:
        trigger = step.trigger
        return {
            "name": step.name,
            "provider": self._serialise_provider(step.provider),
            "config": dict(step.config),
            "metadata": dict(step.metadata),
            "trigger": {
                "kind": trigger.kind,
                "depends_on": list(trigger.depends_on),
                "event": trigger.event,
                "filters": dict(trigger.filters),
            },
        }

    @staticmethod
    def _serialise_provider(provider: Any) -> str:
        if isinstance(provider, str):
            return provider

        module = getattr(provider, "__module__", None)
        qualname = getattr(provider, "__qualname__", None)
        if module and qualname:
            return f"{module}:{qualname}"

        name = getattr(provider, "__name__", None)
        if module and name:
            return f"{module}:{name}"

        return repr(provider)


@dataclass(slots=True)
class PipelineRun:
    """Metadata describing a pipeline run returned by the orchestrator."""

    run_id: str
    pipeline: str
    status: str
    created_at: datetime
    updated_at: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        return {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "parameters": dict(self.parameters),
        }


@dataclass(slots=True)
class PipelineRunEvent:
    """A single status update emitted for a pipeline run."""

    run_id: str
    pipeline: str
    status: str
    timestamp: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        return {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "parameters": dict(self.parameters),
        }


@dataclass(slots=True)
class _RunEventSubscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[PipelineRunEvent]


class PipelineRunStore:
    """SQLite backed persistence layer for pipeline runs and events."""

    def __init__(
        self,
        *,
        database: str | Path | None = None,
    ) -> None:
        if database is None:
            database_path = ":memory:"
            self._path: Path | None = None
        else:
            database_str = str(database)
            if database_str == ":memory:":
                database_path = ":memory:"
                self._path = None
            else:
                path = Path(database)
                path.parent.mkdir(parents=True, exist_ok=True)
                database_path = str(path)
                self._path = path

        self._lock = Lock()
        self._connection = sqlite3.connect(
            database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._initialise_schema()
        self._subscribers: dict[str, list[_RunEventSubscriber]] = {}

    @staticmethod
    def _encode_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _encode_parameters(parameters: Mapping[str, Any]) -> str:
        def _default(value: Any) -> Any:
            return str(value)

        return json.dumps(dict(parameters), default=_default)

    @staticmethod
    def _decode_parameters(payload: str) -> dict[str, Any]:
        if not payload:
            return {}
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
        return {}

    def _initialise_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    pipeline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    parameters TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    pipeline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES pipeline_runs(run_id)
                )
                """
            )

    def create_run(self, run: PipelineRun, initial_event: PipelineRunEvent) -> None:
        payload = self._encode_parameters(run.parameters)
        event_payload = self._encode_parameters(initial_event.parameters)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id, pipeline, status, created_at, updated_at, parameters
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.pipeline,
                    run.status,
                    self._encode_datetime(run.created_at),
                    self._encode_datetime(run.updated_at),
                    payload,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO pipeline_run_events (
                    run_id, pipeline, status, timestamp, parameters
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    initial_event.run_id,
                    initial_event.pipeline,
                    initial_event.status,
                    self._encode_datetime(initial_event.timestamp),
                    event_payload,
                ),
            )

    def append_event(
        self,
        run_id: str,
        *,
        status: str,
        timestamp: datetime,
        parameters: Mapping[str, Any],
        run_status: str | None,
    ) -> None:
        with self._lock:
            cursor = self._connection.execute(
                "SELECT pipeline FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                msg = f"run '{run_id}' could not be found"
                raise KeyError(msg)
            pipeline = row["pipeline"]
            encoded_parameters = self._encode_parameters(parameters)
            encoded_timestamp = self._encode_datetime(timestamp)

            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO pipeline_run_events (
                        run_id, pipeline, status, timestamp, parameters
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        pipeline,
                        status,
                        encoded_timestamp,
                        encoded_parameters,
                    ),
                )
                if run_status is not None:
                    self._connection.execute(
                        """
                        UPDATE pipeline_runs
                        SET status = ?, updated_at = ?
                        WHERE run_id = ?
                        """,
                        (run_status, encoded_timestamp, run_id),
                    )
                else:
                    self._connection.execute(
                        """
                        UPDATE pipeline_runs
                        SET updated_at = ?
                        WHERE run_id = ?
                        """,
                        (encoded_timestamp, run_id),
                    )
            subscribers = tuple(self._subscribers.get(run_id, ()))

        event = PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=timestamp,
            parameters=dict(parameters),
        )
        self._publish_event(subscribers, event)

    def get_run(self, run_id: str) -> PipelineRun:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT run_id, pipeline, status, created_at, updated_at, parameters
                FROM pipeline_runs
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            msg = f"run '{run_id}' could not be found"
            raise KeyError(msg)

        return PipelineRun(
            run_id=row["run_id"],
            pipeline=row["pipeline"],
            status=row["status"],
            created_at=self._decode_datetime(row["created_at"]),
            updated_at=self._decode_datetime(row["updated_at"]),
            parameters=self._decode_parameters(row["parameters"]),
        )

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[PipelineRun]:
        clauses: list[str] = []
        bindings: list[object] = []
        if pipeline is not None:
            clauses.append("pipeline = ?")
            bindings.append(pipeline)
        if status is not None:
            clauses.append("status = ?")
            bindings.append(status)
        if since is not None:
            clauses.append("created_at >= ?")
            bindings.append(self._encode_datetime(since))

        query = [
            "SELECT run_id, pipeline, status, created_at, updated_at, parameters",
            "FROM pipeline_runs",
        ]
        if clauses:
            query.append("WHERE " + " AND ".join(clauses))
        query.append("ORDER BY created_at DESC, run_id DESC")
        if limit is not None:
            query.append("LIMIT ?")

        statement = "\n".join(query)
        params: tuple[object, ...]
        if limit is not None:
            params = (*bindings, limit)
        else:
            params = tuple(bindings)

        with self._lock:
            cursor = self._connection.execute(statement, params)
            rows = cursor.fetchall()

        return [
            PipelineRun(
                run_id=row["run_id"],
                pipeline=row["pipeline"],
                status=row["status"],
                created_at=self._decode_datetime(row["created_at"]),
                updated_at=self._decode_datetime(row["updated_at"]),
                parameters=self._decode_parameters(row["parameters"]),
            )
            for row in rows
        ]

    def iter_run_events(self, run_id: str) -> Iterator[PipelineRunEvent]:
        with self._lock:
            rows = self._load_run_event_rows_locked(run_id)

        for row in rows:
            yield self._row_to_run_event(row)

    def watch_run_events(self, run_id: str) -> AsyncIterator[PipelineRunEvent]:
        with self._lock:
            rows = self._load_run_event_rows_locked(run_id)

        events = [self._row_to_run_event(row) for row in rows]
        seen_count = len(events)

        subscriber: _RunEventSubscriber | None = None
        queue: asyncio.Queue[PipelineRunEvent] | None = None
        registered = False
        delivered_initial = False

        async def iterator() -> AsyncIterator[PipelineRunEvent]:
            nonlocal subscriber, queue, registered, delivered_initial, seen_count, events

            if not registered:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.get_event_loop_policy().new_event_loop()

                queue = asyncio.Queue()
                subscriber = _RunEventSubscriber(loop=loop, queue=queue)

                with self._lock:
                    rows_after_subscribe = self._load_run_event_rows_locked(run_id)
                    subscribers = self._subscribers.setdefault(run_id, [])
                    subscribers.append(subscriber)

                additional = [
                    self._row_to_run_event(row)
                    for row in rows_after_subscribe[seen_count:]
                ]
                if additional:
                    events.extend(additional)
                    seen_count = len(events)

                registered = True

            assert queue is not None
            assert subscriber is not None

            try:
                if not delivered_initial:
                    for event in events:
                        yield event
                    delivered_initial = True

                while True:
                    yield await queue.get()
            finally:
                with self._lock:
                    targets = self._subscribers.get(run_id)
                    if targets is not None and subscriber in targets:
                        targets.remove(subscriber)
                        if not targets:
                            self._subscribers.pop(run_id, None)

        return iterator()

    def _publish_event(
        self,
        subscribers: tuple[_RunEventSubscriber, ...],
        event: PipelineRunEvent,
    ) -> None:
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)

    def _load_run_event_rows_locked(self, run_id: str) -> list[sqlite3.Row]:
        cursor = self._connection.execute(
            """
            SELECT run_id, pipeline, status, timestamp, parameters
            FROM pipeline_run_events
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        if rows:
            return rows
        cursor = self._connection.execute(
            "SELECT 1 FROM pipeline_runs WHERE run_id = ?",
            (run_id,),
        )
        if cursor.fetchone() is None:
            msg = f"run '{run_id}' could not be found"
            raise KeyError(msg)
        return rows

    def _row_to_run_event(self, row: sqlite3.Row) -> PipelineRunEvent:
        return PipelineRunEvent(
            run_id=row["run_id"],
            pipeline=row["pipeline"],
            status=row["status"],
            timestamp=self._decode_datetime(row["timestamp"]),
            parameters=self._decode_parameters(row["parameters"]),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> PipelineRunStore:
        database = config.get("database") or config.get("path")
        if database is None:
            msg = "storage configuration requires a 'database' or 'path' value"
            raise ValueError(msg)
        return cls(database=database)


class PipelineOrchestrator:
    """Pipeline orchestrator used by the Trafalgar tooling layer.

    Runs and events are persisted through a configurable :class:`PipelineRunStore`.
    """

    def __init__(
        self,
        definitions: Iterable[PipelineDefinition] | None = None,
        *,
        store: PipelineRunStore | None = None,
        executor: pipeline_executor.PipelineExecutor | None = None,
    ) -> None:
        self._definitions: dict[str, PipelineDefinition] = {}
        self._lock = Lock()
        self._store = store or PipelineRunStore()
        self._executor = executor or pipeline_executor.PipelineExecutor()
        if definitions:
            for definition in definitions:
                self.register(definition)

    def register(self, definition: PipelineDefinition) -> None:
        stored = self._prepare_definition(definition)
        with self._lock:
            if definition.name in self._definitions:
                msg = f"pipeline '{definition.name}' is already registered"
                raise ValueError(msg)
            self._definitions[definition.name] = stored

    def upsert(self, definition: PipelineDefinition) -> bool:
        stored = self._prepare_definition(definition)
        with self._lock:
            created = definition.name not in self._definitions
            self._definitions[definition.name] = stored
        return created

    def deregister(self, name: str) -> None:
        with self._lock:
            try:
                del self._definitions[name]
            except KeyError as exc:
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc

    def list_pipelines(self) -> list[PipelineDefinition]:
        with self._lock:
            definitions = list(self._definitions.values())
        return sorted(definitions, key=lambda item: item.name)

    def get_pipeline(self, name: str) -> PipelineDefinition:
        with self._lock:
            try:
                return self._definitions[name]
            except KeyError as exc:  # pragma: no cover - defensive guard
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc

    def _prepare_definition(self, definition: PipelineDefinition) -> PipelineDefinition:
        resolved = self._executor.resolve_pipeline(definition.pipeline)
        return replace(definition, pipeline=resolved)

    def trigger_run(
        self, pipeline_name: str, *, parameters: Mapping[str, Any] | None = None
    ) -> PipelineRun:
        parameters = dict(parameters or {})
        definition = self.get_pipeline(pipeline_name)
        run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            created_at=now,
            updated_at=now,
            parameters=parameters,
        )
        initial_event = PipelineRunEvent(
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            timestamp=run.created_at,
            parameters=parameters,
        )
        self._store.create_run(run, initial_event)

        self._append_event(run_id, "running")

        try:
            self._executor.execute(
                definition.pipeline,
                parameters=parameters,
                emit=self._build_step_emitter(run_id),
            )
        except Exception as exc:
            self._append_event(
                run_id,
                "failed",
                parameters={"error": str(exc)},
            )
        else:
            self._append_event(run_id, "succeeded")

        return self.get_run(run_id)

    def _build_step_emitter(self, run_id: str) -> pipeline_executor.StepEventEmitter:
        def emit(
            status: str,
            *,
            step: pipeline_executor.ExecutedStep,
            event: pipeline_executor.StepTriggerEvent | None = None,
            error: Exception | None = None,
        ) -> None:
            payload: dict[str, Any] = {"step": step.name}
            if event is not None:
                payload["event"] = {
                    "name": event.name,
                    "payload": dict(event.payload),
                }
            if error is not None:
                payload["error"] = str(error)
            self._append_event(run_id, status, parameters=payload)

        return emit

    def _append_event(
        self,
        run_id: str,
        status: str,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc)
        parameters = dict(parameters or {})
        run_status: str | None
        if status in {"queued", "running", "succeeded", "failed"}:
            run_status = status
        elif status == "step_failed":
            run_status = "failed"
        else:
            run_status = None
        self._store.append_event(
            run_id,
            status=status,
            timestamp=timestamp,
            parameters=parameters,
            run_status=run_status,
        )

    def get_run(self, run_id: str) -> PipelineRun:
        try:
            return self._store.get_run(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[PipelineRun]:
        return self._store.list_runs(
            pipeline=pipeline, status=status, limit=limit, since=since
        )

    def iter_run_events(self, run_id: str) -> Iterator[PipelineRunEvent]:
        try:
            return self._store.iter_run_events(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def watch_run_events(self, run_id: str) -> AsyncIterator[PipelineRunEvent]:
        try:
            return self._store.watch_run_events(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def serialise_run(self, run_id: str) -> Mapping[str, Any]:
        run = self.get_run(run_id)
        return run.serialise()

    def serialise_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        return [event.serialise() for event in self.iter_run_events(run_id)]


_default_orchestrator: PipelineOrchestrator | None = None


def get_pipeline_orchestrator(
    *,
    storage: PipelineRunStore | None = None,
    storage_config: Mapping[str, Any] | None = None,
) -> PipelineOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        if storage is not None and storage_config is not None:
            msg = "provide either a storage instance or configuration, not both"
            raise ValueError(msg)
        if storage is None and storage_config is not None:
            storage = PipelineRunStore.from_config(storage_config)
        _default_orchestrator = PipelineOrchestrator(store=storage)
    elif storage is not None or storage_config is not None:
        msg = (
            "pipeline orchestrator is already configured; "
            "reset it with set_pipeline_orchestrator(None) before supplying storage"
        )
        raise RuntimeError(msg)
    return _default_orchestrator


def set_pipeline_orchestrator(orchestrator: PipelineOrchestrator | None) -> None:
    global _default_orchestrator
    _default_orchestrator = orchestrator


def pipeline_definition_from_profile_entry(
    name: str, config: Mapping[str, Any]
) -> PipelineDefinition:
    """Return a pipeline definition derived from profile configuration."""

    pipeline_config = dict(config)
    pipeline_config.setdefault("name", name)
    pipeline = pipeline_from_config(pipeline_config)

    metadata = pipeline.metadata or {}

    def _coerce_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    display_name = _coerce_optional_str(
        config.get("display_name", metadata.get("display_name"))
    )
    description = _coerce_optional_str(
        config.get("description", metadata.get("description"))
    )

    parameters_raw = config.get("parameters")
    if parameters_raw is None:
        parameters: Mapping[str, Any] = {}
    elif isinstance(parameters_raw, Mapping):
        parameters = dict(parameters_raw)
    else:
        msg = f"pipeline '{name}' parameters must be a mapping"
        raise TypeError(msg)

    return PipelineDefinition(
        name=pipeline.name,
        pipeline=pipeline,
        display_name=display_name,
        description=description,
        parameters=parameters,
    )


def pipeline_definitions_from_profile(
    profile: ProfileContext,
) -> tuple[PipelineDefinition, ...]:
    """Build pipeline definitions from a loaded profile context."""

    return tuple(
        pipeline_definition_from_profile_entry(name, config)
        for name, config in sorted(profile.pipelines.items())
    )


def configure_orchestrator_from_profile(
    profile: ProfileContext,
    *,
    storage_config: Mapping[str, Any] | None = None,
) -> PipelineOrchestrator:
    """Initialise the shared orchestrator with definitions from *profile*.

    When a storage configuration mapping is supplied the orchestrator persists
    pipeline run history using :class:`PipelineRunStore`.
    """

    definitions = pipeline_definitions_from_profile(profile)
    effective_storage = storage_config or profile.pipeline_storage
    store = (
        PipelineRunStore.from_config(effective_storage) if effective_storage else None
    )
    orchestrator = PipelineOrchestrator(definitions, store=store)
    set_pipeline_orchestrator(orchestrator)
    return orchestrator


__all__ = [
    "PipelineDefinition",
    "PipelineOrchestrator",
    "PipelineRun",
    "PipelineRunEvent",
    "PipelineRunStore",
    "get_pipeline_orchestrator",
    "set_pipeline_orchestrator",
    "pipeline_definition_from_profile_entry",
    "pipeline_definitions_from_profile",
    "configure_orchestrator_from_profile",
]
