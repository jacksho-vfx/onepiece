"""Utilities for loading OnePiece configuration profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older runtimes.
    import tomli as tomllib  # type: ignore[no-redef]

from apps.onepiece.utils.errors import OnePieceConfigError

CONFIG_FILENAME = "onepiece.toml"


@dataclass(frozen=True)
class ProfileContext:
    """Container describing a resolved configuration profile.

    Attributes
    ----------
    name:
        Selected profile name.
    data:
        Deep-merged configuration payload associated with ``name``.
    pipelines:
        Mapping of pipeline identifiers to their configuration blocks.
    pipeline_storage:
        Optional mapping describing pipeline persistence settings sourced from
        ``[profiles.<name>.pipeline.storage]``.  The section currently accepts
        a ``database`` (or ``path``) key pointing at a SQLite database file
        used by :class:`apps.trafalgar.pipeline.PipelineRunStore`, optional
        ``busy_timeout`` (seconds) or ``busy_timeout_ms`` keys that control
        SQLite's busy timeout, and ``max_workers`` to tune orchestrator
        concurrency when definitions are persisted.
    pipeline_workers_max:
        Maximum number of concurrent pipeline workers allowed for this
        profile.  When unspecified the value defaults to the number of CPUs on
        the current host (falling back to ``1`` if unknown).
    pipeline_executor_event_max_workers:
        Optional upper bound for concurrent event-driven pipeline step
        execution.  When unspecified, event-driven steps share the sequential
        executor pool.
    pipeline_executor_step_timeout:
        Optional maximum number of seconds a single pipeline step may run
        before being considered failed.
    pipeline_executor_run_timeout:
        Optional maximum number of seconds a pipeline run may take before it
        is aborted.
    sources:
        Ordered tuple of configuration files that contributed to the final
        profile.
    """

    name: str
    data: Mapping[str, Any]
    pipelines: Mapping[str, Mapping[str, Any]]
    pipeline_storage: Mapping[str, Any]
    sources: tuple[Path, ...]
    pipeline_workers_max: int
    pipeline_executor_event_max_workers: int | None
    pipeline_executor_step_timeout: float | None
    pipeline_executor_run_timeout: float | None


def load_profile(
    *,
    profile: str | None = None,
    workspace: Path | None = None,
    project_root: Path | None = None,
) -> ProfileContext:
    """Load and merge OnePiece configuration before selecting *profile*.

    The configuration is sourced from up to three locations, in the following
    precedence order (lowest to highest): user, project, then workspace.  Each
    location may provide a :mod:`toml` document containing a ``profiles`` table
    with named dictionaries of settings.  Later files override earlier ones via
    deep-merge semantics.

    When *profile* is ``None`` the loader falls back to the ``ONEPIECE_PROFILE``
    environment variable.  If the profile is still unspecified, the highest
    precedence configuration file that defines ``default_profile`` wins.  As a
    final fallback a profile named ``"default"`` is used.
    """

    merged_config: Dict[str, Any] = {}
    sources: list[Path] = []

    for path in _iter_config_paths(workspace=workspace, project_root=project_root):
        try:
            document = _load_toml(path)
        except OSError as exc:  # pragma: no cover - filesystem errors are rare.
            raise OnePieceConfigError(
                f"Unable to read configuration file '{path}': {exc}"
            ) from exc
        merged_config = _deep_merge(merged_config, document)
        sources.append(path)

    profiles = merged_config.get("profiles", {})
    if not isinstance(profiles, Mapping):
        raise OnePieceConfigError(
            "The 'profiles' table must contain mappings of settings"
        )

    pipelines = _extract_pipelines(merged_config)

    selected_profile = _determine_profile_name(merged_config, profile)

    profile_data: Mapping[str, Any]
    if profiles:
        if selected_profile in profiles:
            raw_data = profiles[selected_profile]
            if not isinstance(raw_data, Mapping):
                raise OnePieceConfigError(
                    f"Profile '{selected_profile}' must be a mapping of configuration values"
                )
            profile_data = dict(raw_data)
        elif selected_profile == "default":
            profile_data = {}
        else:
            available = ", ".join(sorted(str(name) for name in profiles)) or "<none>"
            raise OnePieceConfigError(
                f"Profile '{selected_profile}' was not found. Available profiles: {available}."
            )
    else:
        profile_data = {}

    pipeline_storage = _extract_pipeline_storage(selected_profile, profile_data)
    pipeline_workers_max = _extract_pipeline_workers_max(selected_profile, profile_data)
    pipeline_executor_event_max_workers = _extract_pipeline_executor_event_max_workers(
        selected_profile, profile_data
    )
    (
        pipeline_executor_step_timeout,
        pipeline_executor_run_timeout,
    ) = _extract_pipeline_executor_timeouts(selected_profile, profile_data)

    return ProfileContext(
        name=selected_profile,
        data=profile_data,
        pipelines=pipelines,
        pipeline_storage=pipeline_storage,
        sources=tuple(sources),
        pipeline_workers_max=pipeline_workers_max,
        pipeline_executor_event_max_workers=pipeline_executor_event_max_workers,
        pipeline_executor_step_timeout=pipeline_executor_step_timeout,
        pipeline_executor_run_timeout=pipeline_executor_run_timeout,
    )


def _iter_config_paths(
    *, workspace: Path | None, project_root: Path | None
) -> Iterable[Path]:
    """Yield configuration files in precedence order."""

    yielded: set[Path] = set()

    for path in _user_config_paths():
        if path.exists() and path not in yielded:
            yielded.add(path)
            yield path

    project_candidate = _normalise_project_root(project_root)
    if project_candidate is not None:
        for path in _project_config_paths(project_candidate):
            if path.exists() and path not in yielded:
                yielded.add(path)
                yield path

    if workspace is not None:
        workspace_path = workspace / CONFIG_FILENAME
        if workspace_path.exists() and workspace_path not in yielded:
            yielded.add(workspace_path)
            yield workspace_path


def _user_config_paths() -> tuple[Path, ...]:
    """Return user-level configuration search paths."""

    home = Path(os.path.expanduser("~"))
    xdg_config = os.environ.get("XDG_CONFIG_HOME")

    candidates = []
    if xdg_config:
        candidates.append(Path(xdg_config) / "onepiece" / CONFIG_FILENAME)

    candidates.append(home / ".config" / "onepiece" / CONFIG_FILENAME)
    candidates.append(home / ".onepiece" / CONFIG_FILENAME)
    candidates.append(home / CONFIG_FILENAME)

    return tuple(candidates)


def _project_config_paths(project_root: Path) -> tuple[Path, ...]:
    return (
        project_root / CONFIG_FILENAME,
        project_root / ".onepiece" / CONFIG_FILENAME,
    )


def _normalise_project_root(project_root: Path | None) -> Path | None:
    if project_root is None:
        env_root = os.environ.get("ONEPIECE_PROJECT_ROOT")
        if env_root:
            project_root = Path(env_root).expanduser()
        else:
            project_root = Path.cwd()
    return project_root


def _load_toml(path: Path) -> Dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise OnePieceConfigError(
            f"Configuration file '{path}' is not valid TOML: {exc}"
        ) from exc


def _deep_merge(base: Dict[str, Any], new: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {**base}
    for key, value in new.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _determine_profile_name(config: Mapping[str, Any], override: str | None) -> str:
    if override:
        return override

    env_profile = os.environ.get("ONEPIECE_PROFILE")
    if env_profile:
        return env_profile

    default_profile = config.get("default_profile")
    if isinstance(default_profile, str) and default_profile:
        return default_profile

    return "default"


def _extract_pipelines(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_pipelines = config.get("pipelines", {})
    if not raw_pipelines:
        return {}

    if not isinstance(raw_pipelines, Mapping):
        raise OnePieceConfigError(
            "The 'pipelines' table must contain mappings of pipeline metadata"
        )

    extracted: dict[str, dict[str, Any]] = {}
    for name, details in raw_pipelines.items():
        if not isinstance(details, Mapping):
            raise OnePieceConfigError(
                f"Pipeline '{name}' must be a mapping of configuration values"
            )

        extracted[str(name)] = dict(details)

    return extracted


def _default_worker_limit() -> int:
    cpu_count = os.cpu_count()
    if isinstance(cpu_count, int) and cpu_count > 0:
        return cpu_count
    return 1


def _extract_pipeline_config(
    profile_name: str, profile_data: Mapping[str, Any]
) -> Mapping[str, Any]:
    pipeline_config = profile_data.get("pipeline")
    if pipeline_config is None:
        return {}
    if not isinstance(pipeline_config, Mapping):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline section must be a mapping"
        )
    return pipeline_config


def _extract_pipeline_storage(
    profile_name: str, profile_data: Mapping[str, Any]
) -> Mapping[str, Any]:
    pipeline_config = _extract_pipeline_config(profile_name, profile_data)
    storage_config = pipeline_config.get("storage")
    if storage_config is None:
        return {}
    if not isinstance(storage_config, Mapping):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.storage section must be a mapping"
        )

    return dict(storage_config)


def _extract_pipeline_workers_max(
    profile_name: str, profile_data: Mapping[str, Any]
) -> int:
    pipeline_config = _extract_pipeline_config(profile_name, profile_data)
    workers_config = pipeline_config.get("workers")
    if workers_config is None:
        return _default_worker_limit()
    if not isinstance(workers_config, Mapping):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.workers section must be a mapping"
        )

    max_value = workers_config.get("max")
    if max_value is None:
        return _default_worker_limit()

    if isinstance(max_value, bool):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.workers.max must be an integer"
        )

    try:
        max_workers = int(max_value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.workers.max must be an integer"
        ) from exc

    if max_workers < 1:
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.workers.max must be at least 1"
        )

    return max_workers


def _extract_pipeline_executor_event_max_workers(
    profile_name: str, profile_data: Mapping[str, Any]
) -> int | None:
    pipeline_config = _extract_pipeline_config(profile_name, profile_data)
    executor_config = pipeline_config.get("executor")
    if executor_config is None:
        return None
    if not isinstance(executor_config, Mapping):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor section must be a mapping"
        )

    raw_value = executor_config.get("event_max_workers")
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor.event_max_workers must be an integer"
        )

    try:
        max_workers = int(raw_value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor.event_max_workers must be an integer"
        ) from exc

    if max_workers < 1:
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor.event_max_workers must be at least 1"
        )

    return max_workers


def _extract_pipeline_executor_timeouts(
    profile_name: str, profile_data: Mapping[str, Any]
) -> tuple[float | None, float | None]:
    pipeline_config = _extract_pipeline_config(profile_name, profile_data)
    executor_config = pipeline_config.get("executor")
    if executor_config is None:
        return (None, None)
    if not isinstance(executor_config, Mapping):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor section must be a mapping"
        )

    step_timeout = _coerce_executor_timeout(
        profile_name, executor_config, "step_timeout"
    )
    run_timeout = _coerce_executor_timeout(
        profile_name, executor_config, "run_timeout"
    )
    return step_timeout, run_timeout


def _coerce_executor_timeout(
    profile_name: str, executor_config: Mapping[str, Any], key: str
) -> float | None:
    raw_value = executor_config.get(key)
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor.{key} must be a positive number"
        )
    try:
        timeout = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor.{key} must be a positive number"
        ) from exc
    if timeout <= 0:
        raise OnePieceConfigError(
            f"Profile '{profile_name}' pipeline.executor.{key} must be greater than 0"
        )
    return timeout
