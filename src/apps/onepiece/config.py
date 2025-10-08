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
    """Container describing a resolved configuration profile."""

    name: str
    data: Mapping[str, Any]
    sources: tuple[Path, ...]


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

    return ProfileContext(
        name=selected_profile,
        data=profile_data,
        sources=tuple(sources),
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
            project_root = Path(env_root)
        else:
            project_root = Path.cwd()
    return project_root


def _load_toml(path: Path) -> Dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


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
