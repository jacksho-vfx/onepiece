"""Utilities for importing published Maya assets into Unreal Engine.

The importer consumes the metadata generated during the publish step to
construct :class:`unreal.AssetImportTask` objects.  This keeps the behaviour
fully data-driven and allows us to run the same import logic in automation as
artists do locally.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, MutableMapping, Sequence

import structlog


log = structlog.get_logger(__name__)


class UnrealImportError(RuntimeError):
    """Raised when the Unreal Engine import pipeline cannot continue."""


DEFAULT_TASK_SETTINGS: Mapping[str, Any] = {
    "automated": True,
    "replace_existing": True,
    "save": True,
}


@dataclass(frozen=True)
class UnrealImportSummary:
    """Describes a single asset import task prepared for Unreal Engine."""

    source: Path
    destination_path: str
    destination_name: str | None
    task_settings: Mapping[str, Any]
    factory_class: str | None
    factory_settings: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable representation of the task."""

        return {
            "source": str(self.source),
            "destination_path": self.destination_path,
            "destination_name": self.destination_name,
            "task_settings": dict(self.task_settings),
            "factory_class": self.factory_class,
            "factory_settings": dict(self.factory_settings),
        }


def _load_metadata(package_dir: Path) -> Mapping[str, Any]:
    """Return the publish metadata for ``package_dir``."""

    metadata_path = package_dir / "metadata.json"
    try:
        payload = metadata_path.read_text()
    except FileNotFoundError as exc:
        raise UnrealImportError(
            f"Package metadata is missing: {metadata_path}"
        ) from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UnrealImportError(f"Metadata JSON is invalid: {exc}") from exc

    if not isinstance(data, Mapping):
        raise UnrealImportError("Metadata JSON must contain an object")

    return data


def _assert_maya_package(metadata: Mapping[str, Any]) -> None:
    """Ensure the package originates from Maya and passed validation."""

    dcc = metadata.get("dcc")
    if not isinstance(dcc, str) or dcc.lower() != "maya":
        raise UnrealImportError("Package metadata must originate from Maya")

    validations = metadata.get("validations")
    if not isinstance(validations, Mapping):
        raise UnrealImportError("Metadata missing validation results")

    maya_validation = validations.get("maya_to_unreal")
    if not isinstance(maya_validation, Mapping):
        raise UnrealImportError("Metadata missing Maya to Unreal validation entry")

    status = maya_validation.get("status")
    if not isinstance(status, str) or status.lower() != "passed":
        raise UnrealImportError("Maya to Unreal validation must pass before importing")


def _normalise_task_settings(
    task_settings: Mapping[str, Any] | None,
) -> MutableMapping[str, Any]:
    merged: MutableMapping[str, Any] = dict(DEFAULT_TASK_SETTINGS)
    if task_settings:
        if not isinstance(task_settings, Mapping):
            raise UnrealImportError("task_options must be a mapping when provided")
        merged.update(task_settings)
    return merged


def _normalise_factory_settings(
    factory_settings: Mapping[str, Any] | None,
) -> MutableMapping[str, Any]:
    if not factory_settings:
        return {}
    if not isinstance(factory_settings, Mapping):
        raise UnrealImportError("factory_options must be a mapping when provided")
    return dict(factory_settings)


def _collect_import_summaries(
    package_dir: Path,
    metadata: Mapping[str, Any],
    *,
    project: str,
    asset_name: str,
) -> list[UnrealImportSummary]:
    """Return the Unreal import tasks defined in ``metadata``."""

    unreal_section = metadata.get("unreal")
    if not isinstance(unreal_section, Mapping):
        raise UnrealImportError("Metadata missing 'unreal' section")

    assets: Sequence[object] | None = unreal_section.get("assets")
    if not isinstance(assets, Sequence) or not assets:
        raise UnrealImportError("Metadata must describe at least one Unreal asset")

    default_destination = unreal_section.get("project_path")
    if default_destination is not None and not isinstance(default_destination, str):
        raise UnrealImportError("unreal.project_path must be a string when provided")

    summaries: list[UnrealImportSummary] = []

    for index, raw_entry in enumerate(assets):
        if not isinstance(raw_entry, Mapping):
            raise UnrealImportError(f"Unreal asset entry #{index} must be a mapping")

        source_rel = raw_entry.get("source")
        if not isinstance(source_rel, str) or not source_rel:
            raise UnrealImportError("Unreal asset entry missing 'source'")

        source = package_dir / source_rel
        if not source.is_file():
            raise UnrealImportError(f"Unreal asset source does not exist: {source_rel}")

        destination_path = raw_entry.get("destination_path")
        if destination_path is None:
            destination_path = default_destination or f"/Game/{project}"
        if not isinstance(destination_path, str) or not destination_path:
            raise UnrealImportError(
                "destination_path must resolve to a non-empty string"
            )

        destination_name = raw_entry.get("destination_name")
        if destination_name is None:
            destination_name = metadata.get("asset_name") or asset_name
        elif not isinstance(destination_name, str):
            raise UnrealImportError("destination_name must be a string when provided")

        factory_class = raw_entry.get("factory_class")
        if factory_class is not None and not isinstance(factory_class, str):
            raise UnrealImportError("factory_class must be a string when provided")

        task_settings = _normalise_task_settings(raw_entry.get("task_options"))
        factory_settings = _normalise_factory_settings(raw_entry.get("factory_options"))

        summaries.append(
            UnrealImportSummary(
                source=source,
                destination_path=destination_path,
                destination_name=destination_name,
                task_settings=task_settings,
                factory_class=factory_class,
                factory_settings=factory_settings,
            )
        )

    return summaries


def _set_editor_property(target: Any, name: str, value: Any) -> None:
    setter = getattr(target, "set_editor_property", None)
    if callable(setter):
        setter(name, value)
    else:
        setattr(target, name, value)


class UnrealPackageImporter:
    """Convert published Maya packages into Unreal Engine assets."""

    def __init__(self, *, unreal_module: Any | None = None) -> None:
        self._unreal = unreal_module

    def import_package(
        self,
        package_dir: Path,
        *,
        project: str,
        asset_name: str,
        dry_run: bool = False,
    ) -> list[UnrealImportSummary]:
        """Import ``package_dir`` into ``project`` using Unreal Engine."""

        metadata = _load_metadata(package_dir)
        _assert_maya_package(metadata)
        summaries = _collect_import_summaries(
            package_dir, metadata, project=project, asset_name=asset_name
        )

        if dry_run:
            log.info(
                "unreal_import_dry_run",
                project=project,
                asset=asset_name,
                package=str(package_dir),
                tasks=len(summaries),
            )
            return summaries

        unreal = self._resolve_unreal_module()

        try:
            asset_tools_helpers = unreal.AssetToolsHelpers
            asset_tools = asset_tools_helpers.get_asset_tools()
        except AttributeError as exc:  # pragma: no cover - defensive guard
            raise UnrealImportError("Unreal module missing AssetToolsHelpers") from exc

        tasks = [self._build_task(unreal, summary) for summary in summaries]

        log.info(
            "unreal_import_start",
            project=project,
            asset=asset_name,
            package=str(package_dir),
            tasks=len(tasks),
        )

        try:
            asset_tools.import_asset_tasks(tasks)
        except Exception as exc:  # pragma: no cover - depends on Unreal runtime
            log.error(
                "unreal_import_failed",
                project=project,
                asset=asset_name,
                package=str(package_dir),
                error=str(exc),
            )
            raise UnrealImportError(f"Unreal import failed: {exc}") from exc

        log.info(
            "unreal_import_completed",
            project=project,
            asset=asset_name,
            package=str(package_dir),
            imported=len(tasks),
        )

        return summaries

    def _resolve_unreal_module(self) -> Any:
        if self._unreal is not None:
            return self._unreal

        try:
            from importlib import import_module

            self._unreal = import_module("unreal")
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on runtime
            raise UnrealImportError(
                "Unreal Python API is unavailable; run inside Unreal's Python interpreter"
            ) from exc

        return self._unreal

    def _build_task(self, unreal: Any, summary: UnrealImportSummary) -> Any:
        task = unreal.AssetImportTask()

        _set_editor_property(task, "filename", str(summary.source))
        _set_editor_property(task, "destination_path", summary.destination_path)
        if summary.destination_name:
            _set_editor_property(task, "destination_name", summary.destination_name)

        for name, value in summary.task_settings.items():
            _set_editor_property(task, name, value)

        options = self._build_factory_options(unreal, summary)
        if options is not None:
            setattr(task, "options", options)

        return task

    def _build_factory_options(
        self, unreal: Any, summary: UnrealImportSummary
    ) -> Any | None:
        if not summary.factory_settings and summary.factory_class is None:
            return None

        factory_class_name = summary.factory_class
        factory_class = None
        if factory_class_name:
            factory_class = getattr(unreal, factory_class_name, None)
            if factory_class is None:
                raise UnrealImportError(
                    f"Unreal module missing factory class '{factory_class_name}'"
                )

        if factory_class is None:
            factory_class = getattr(unreal, "FbxImportUI", None)

        if callable(factory_class):
            options = factory_class()
        else:
            options = SimpleNamespace()

        for name, value in summary.factory_settings.items():
            _set_editor_property(options, name, value)

        return options


__all__ = [
    "UnrealImportError",
    "UnrealImportSummary",
    "UnrealPackageImporter",
]
