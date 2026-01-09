"""Typed render preset model and storage helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import structlog

from apps.onepiece.utils.errors import OnePieceIOError, OnePieceValidationError
from libraries.automation.render.base import AdapterCapabilities

from .submit.helpers import (
    DCC_CHOICES,
    FARM_CHOICES,
    get_adapter_capabilities,
    parse_frame_count,
    resolve_priority_and_chunk_size,
)

PresetCapabilityProvider = Callable[[str], AdapterCapabilities]

PRESET_VERSION = 1
PRESET_DIR_ENV = "ONEPIECE_RENDER_PRESET_DIR"
PRESET_EXTENSION = ".json"
PRESET_DIRECTORY_NAME = "render_presets"

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RenderPreset:
    """Strongly typed render preset validated against adapter capabilities."""

    name: str
    version: int
    farm: str
    dcc: str
    scene: Path
    frames: str
    output: Path
    priority: int
    chunk_size: int | None
    user: str | None

    @classmethod
    def from_mapping(
        cls,
        name: str,
        data: dict[str, Any],
        *,
        capability_provider: PresetCapabilityProvider = get_adapter_capabilities,
    ) -> "RenderPreset":
        version = _extract_version(data, name)
        farm = _require_string(data, "farm", name).lower()
        dcc = _require_string(data, "dcc", name).lower()
        if farm not in FARM_CHOICES:
            raise OnePieceValidationError(
                f"Preset '{name}' targets unknown farm '{farm}'. "
                f"Supported farms: {', '.join(FARM_CHOICES)}."
            )
        if dcc not in DCC_CHOICES:
            raise OnePieceValidationError(
                f"Preset '{name}' targets unknown DCC '{dcc}'. "
                f"Supported DCCs: {', '.join(DCC_CHOICES)}."
            )

        scene = Path(_require_string(data, "scene", name)).expanduser()
        output = Path(_require_string(data, "output", name)).expanduser()
        frames = _require_string(data, "frames", name)

        frame_count = parse_frame_count(frames)
        if frame_count is None:
            raise OnePieceValidationError(
                f"Preset '{name}' frame range '{frames}' is not valid."
            )

        priority = _optional_int(data.get("priority"), "priority", name)
        chunk_size = _optional_int(data.get("chunk_size"), "chunk_size", name)

        try:
            resolved_priority, resolved_chunk, _capabilities, _summary = (
                resolve_priority_and_chunk_size(
                    farm=farm,
                    priority=priority,
                    chunk_size=chunk_size,
                    capabilities=capability_provider(farm),
                    frame_count=frame_count,
                    optimize=False,
                )
            )
        except OnePieceValidationError as exc:
            raise OnePieceValidationError(
                f"Preset '{name}' is incompatible with '{farm}' capabilities: {exc}"
            ) from exc

        if resolved_priority is None:
            raise OnePieceValidationError(
                f"Preset '{name}' could not resolve a priority for '{farm}'."
            )

        return cls(
            name=name,
            version=version,
            farm=farm,
            dcc=dcc,
            scene=scene,
            frames=frames,
            output=output,
            priority=resolved_priority,
            chunk_size=resolved_chunk,
            user=_optional_string(data.get("user")),
        )

    def serialise(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "farm": self.farm,
            "dcc": self.dcc,
            "scene": str(self.scene),
            "frames": self.frames,
            "output": str(self.output),
            "priority": self.priority,
        }
        if self.chunk_size is not None:
            payload["chunk_size"] = self.chunk_size
        if self.user:
            payload["user"] = self.user
        return payload


@dataclass(frozen=True)
class StoredPreset:
    """Persisted preset metadata including its source on disk."""

    name: str
    path: Path
    preset: RenderPreset


class RenderPresetStore:
    """Manage render presets from project and user profile directories."""

    def __init__(
        self,
        *,
        capability_provider: PresetCapabilityProvider = get_adapter_capabilities,
        project_root: Path | None = None,
        env: dict[str, str] | os._Environ[str] | None = None,
    ) -> None:
        self.capability_provider = capability_provider
        self._project_root = project_root
        self._env = env if env is not None else os.environ
        self._roots = self._discover_roots()

    def _discover_roots(self) -> tuple[Path, ...]:
        override = self._env.get(PRESET_DIR_ENV)
        if override:
            return (Path(override).expanduser().resolve(),)

        roots: list[Path] = []
        project_root = self._project_root or _determine_project_root(self._env)
        if project_root is not None:
            project_root = project_root.expanduser().resolve()
            project_preset_dir = _project_preset_directory(project_root)
            roots.append(project_preset_dir)

        user_dir = Path.home() / ".onepiece" / PRESET_DIRECTORY_NAME
        roots.append(user_dir)

        unique_roots: list[Path] = []
        for root in roots:
            if root not in unique_roots:
                unique_roots.append(root)
        return tuple(unique_roots)

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    def _resolve_path(self, name: str) -> Path:
        safe_name = _validate_preset_name(name)
        root = self.roots[0]
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{safe_name}{PRESET_EXTENSION}"

    def save(self, preset: RenderPreset) -> Path:
        path = self._resolve_path(preset.name)
        serialised = json.dumps(preset.serialise(), indent=2, sort_keys=True)
        path.write_text(serialised, encoding="utf-8")
        return path

    def list(self) -> list[StoredPreset]:
        presets: list[StoredPreset] = []
        seen: set[str] = set()
        for root in self.roots:
            if not root.exists():
                continue
            for preset_file in sorted(root.glob(f"*{PRESET_EXTENSION}")):
                name = preset_file.stem
                if name in seen:
                    continue
                try:
                    preset = self._load_from_path(name, preset_file)
                except OnePieceValidationError as exc:
                    log.warning(
                        "render.presets.invalid",
                        preset=str(preset_file),
                        error=str(exc),
                    )
                    continue
                seen.add(name)
                presets.append(StoredPreset(name=name, path=preset_file, preset=preset))
        return presets

    def load(self, name: str) -> StoredPreset:
        safe_name = _validate_preset_name(name)
        for root in self.roots:
            candidate = root / f"{safe_name}{PRESET_EXTENSION}"
            if candidate.exists():
                preset = self._load_from_path(safe_name, candidate)
                return StoredPreset(name=safe_name, path=candidate, preset=preset)
        raise OnePieceIOError(f"Preset '{name}' was not found in any preset directory.")

    def export(self, name: str, destination: Path) -> Path:
        record = self.load(name)
        target = destination
        if destination.is_dir() or destination.suffix == "":
            target = destination / f"{record.name}{PRESET_EXTENSION}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(record.preset.serialise(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return target

    def import_file(self, path: Path, *, name: str | None = None) -> StoredPreset:
        if not path.exists() or not path.is_file():
            raise OnePieceIOError(
                f"Preset import path must be an existing file: {path}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OnePieceValidationError(
                f"Preset import file '{path}' is not valid JSON: {exc}"
            ) from exc
        preset_name = name or path.stem
        preset = RenderPreset.from_mapping(
            preset_name,
            payload,
            capability_provider=self.capability_provider,
        )
        saved_path = self.save(preset)
        return StoredPreset(name=preset_name, path=saved_path, preset=preset)

    def _load_from_path(self, name: str, path: Path) -> RenderPreset:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OnePieceValidationError(
                f"Preset file '{path}' is not valid JSON: {exc}"
            ) from exc
        return RenderPreset.from_mapping(
            name,
            payload,
            capability_provider=self.capability_provider,
        )


def _determine_project_root(env: Mapping[str, str]) -> Path | None:
    override = env.get("ONEPIECE_PROJECT_ROOT")
    if override:
        return Path(override)
    try:
        return Path.cwd()
    except FileNotFoundError:
        return None


def _project_preset_directory(project_root: Path) -> Path:
    if (project_root / ".onepiece").is_dir():
        return project_root / ".onepiece" / PRESET_DIRECTORY_NAME
    return project_root / PRESET_DIRECTORY_NAME


def _validate_preset_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise OnePieceValidationError("Preset name cannot be empty.")
    if any(sep in cleaned for sep in ("/", "\\")):
        raise OnePieceValidationError("Preset name cannot include path separators.")
    return cleaned


def _require_string(data: Mapping[str, Any], key: str, preset_name: str) -> str:
    value = data.get(key)
    if value is None:
        raise OnePieceValidationError(
            f"Preset '{preset_name}' is missing required field '{key}'."
        )
    text = str(value).strip()
    if not text:
        raise OnePieceValidationError(
            f"Preset '{preset_name}' must supply a value for '{key}'."
        )
    return text


def _optional_int(value: Any, field: str, preset_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OnePieceValidationError(
            f"Preset '{preset_name}' field '{field}' must be an integer."
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise OnePieceValidationError(
            f"Preset '{preset_name}' field '{field}' must be an integer."
        ) from exc


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_version(data: Mapping[str, Any], preset_name: str) -> int:
    version = data.get("version")
    if version is None:
        return PRESET_VERSION
    try:
        parsed = int(version)
    except (TypeError, ValueError) as exc:
        raise OnePieceValidationError(
            f"Preset '{preset_name}' has an invalid version field."
        ) from exc
    if parsed != PRESET_VERSION:
        raise OnePieceValidationError(
            f"Preset '{preset_name}' has unsupported version '{parsed}'. "
            f"Expected {PRESET_VERSION}."
        )
    return parsed


__all__ = [
    "PRESET_DIRECTORY_NAME",
    "PRESET_DIR_ENV",
    "PRESET_EXTENSION",
    "PRESET_VERSION",
    "RenderPreset",
    "RenderPresetStore",
    "StoredPreset",
]
