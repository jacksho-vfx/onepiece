"""Batch export helpers for Maya scenes."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Protocol

import structlog

log = structlog.get_logger(__name__)


class ExportFormat(str, Enum):
    """Supported interchange formats for Maya batch exports."""

    FBX = "FBX"
    ALEMBIC = "ALEMBIC"
    USD = "USD"


DEFAULT_EXPORT_SETTINGS: Mapping[ExportFormat, Mapping[str, Any]] = {
    ExportFormat.FBX: {
        "file_type": "binary",
        "embed_media": False,
        "triangulate": False,
        "bake_complex_animation": True,
        "bake_complex_step": 1.0,
        "preserve_references": True,
    },
    ExportFormat.ALEMBIC: {
        "uv_write": True,
        "world_space": True,
        "write_visibility": True,
        "write_creases": False,
        "data_format": "ogawa",
    },
    ExportFormat.USD: {
        "file_format": "usdc",
        "merge_transform_and_shape": True,
        "write_mesh_uvs": True,
        "write_mesh_normals": True,
        "write_animation": True,
    },
}

_EXTENSIONS: Mapping[ExportFormat, str] = {
    ExportFormat.FBX: ".fbx",
    ExportFormat.ALEMBIC: ".abc",
    ExportFormat.USD: ".usd",
}


class ExportCallback(Protocol):
    """Function signature used to execute an individual export."""

    def __call__(
        self,
        scene_path: Path,
        output_path: Path,
        *,
        root_nodes: tuple[str, ...],
        settings: Mapping[str, Any],
        frame_range: tuple[int, int] | None,
    ) -> Path:
        """Execute the export and return the path that was written to disk."""


def _sanitize_token(token: str | None) -> str:
    if not token:
        return "UNTITLED"
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in token.strip())
    cleaned = cleaned.strip("_")
    return cleaned.upper() or "UNTITLED"


def _normalize_frame_range(
    frame_range: tuple[int | float, int | float] | None,
) -> tuple[int, int] | None:
    if frame_range is None:
        return None
    start_raw, end_raw = frame_range
    start = int(round(float(start_raw)))
    end = int(round(float(end_raw)))
    if start > end:
        raise ValueError("frame_range start must be <= end")
    return (start, end)


@dataclass(slots=True)
class BatchExportItem:
    """Describe a single asset or shot that should be exported."""

    scene_path: Path
    output_directory: Path
    root_nodes: tuple[str, ...]
    shot: str | None = None
    asset: str | None = None
    tag: str | None = None
    formats: tuple[ExportFormat, ...] = (
        ExportFormat.FBX,
        ExportFormat.ALEMBIC,
        ExportFormat.USD,
    )
    frame_range: tuple[int, int] | None = None
    custom_settings: Mapping[ExportFormat, Mapping[str, Any]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.root_nodes:
            raise ValueError("root_nodes must contain at least one entry")
        unique_nodes = tuple(dict.fromkeys(self.root_nodes))
        object.__setattr__(self, "root_nodes", unique_nodes)

        if not self.formats:
            raise ValueError("formats must contain at least one export format")
        normalized_formats = tuple(dict.fromkeys(self.formats))
        object.__setattr__(self, "formats", normalized_formats)

        normalized_range = _normalize_frame_range(self.frame_range)
        object.__setattr__(self, "frame_range", normalized_range)

        invalid_overrides = set(self.custom_settings).difference(self.formats)
        if invalid_overrides:
            raise ValueError(
                "custom_settings contains formats not present in formats: "
                f"{sorted(fmt.value for fmt in invalid_overrides)}"
            )

    @property
    def label(self) -> str:
        tokens = [self.shot, self.asset, self.tag]
        fallback = self.root_nodes[0]
        filtered = [token for token in tokens if token]
        base = filtered or [fallback]
        return "_".join(_sanitize_token(token) for token in base)


@dataclass(slots=True)
class ExportRecord:
    """Result of exporting a single format for a :class:`BatchExportItem`."""

    format: ExportFormat
    output_path: Path
    settings: Mapping[str, Any]


@dataclass(slots=True)
class BatchExportResult:
    """Summary of all exports produced for an item."""

    item: BatchExportItem
    exports: tuple[ExportRecord, ...]
    started_at: _dt.datetime
    completed_at: _dt.datetime


class BatchExporter:
    """Coordinate consistent multi-format Maya exports for a batch of items."""

    def __init__(
        self,
        *,
        exporters: Mapping[ExportFormat, ExportCallback] | None = None,
        base_settings: Mapping[ExportFormat, Mapping[str, Any]] | None = None,
        clock: Callable[[], _dt.datetime] | None = None,
    ) -> None:
        self._clock = clock or _dt.datetime.utcnow
        self._exporters = dict(exporters or {})
        self._base_settings: dict[ExportFormat, dict[str, Any]] = {
            fmt: dict(DEFAULT_EXPORT_SETTINGS[fmt]) for fmt in ExportFormat
        }
        if base_settings:
            for fmt, overrides in base_settings.items():
                if fmt not in self._base_settings:
                    raise ValueError(f"Unsupported export format: {fmt}")
                self._base_settings[fmt].update(overrides)

    def register_exporter(self, format: ExportFormat, callback: ExportCallback) -> None:
        """Register ``callback`` to handle exports for ``format``."""

        self._exporters[format] = callback

    def export(self, items: Iterable[BatchExportItem]) -> list[BatchExportResult]:
        """Export ``items`` and return structured results for each entry."""

        results: list[BatchExportResult] = []
        for item in items:
            results.append(self._export_item(item))
        return results

    def _export_item(self, item: BatchExportItem) -> BatchExportResult:
        started = self._clock()
        exports: list[ExportRecord] = []
        for format in item.formats:
            exporter = self._exporters.get(format)
            if exporter is None:
                raise RuntimeError(f"No exporter registered for format {format.value}")

            output_path = self._build_output_path(item, format, started)
            settings = self._resolve_settings(item, format)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            log.info(
                "maya_batch_export_start",
                format=format.value,
                scene=str(item.scene_path),
                output=str(output_path),
                root_nodes=item.root_nodes,
            )
            written_path = exporter(
                item.scene_path,
                output_path,
                root_nodes=item.root_nodes,
                settings=settings,
                frame_range=item.frame_range,
            )
            exports.append(
                ExportRecord(
                    format=format,
                    output_path=Path(written_path),
                    settings=settings,
                )
            )

        completed = self._clock()
        return BatchExportResult(
            item=item,
            exports=tuple(exports),
            started_at=started,
            completed_at=completed,
        )

    def _resolve_settings(
        self, item: BatchExportItem, format: ExportFormat
    ) -> Mapping[str, Any]:
        base: MutableMapping[str, Any] = dict(self._base_settings[format])
        overrides = item.custom_settings.get(format)
        if overrides:
            base.update(overrides)
        return base

    def _build_output_path(
        self, item: BatchExportItem, format: ExportFormat, timestamp: _dt.datetime
    ) -> Path:
        extension = _EXTENSIONS[format]
        stamp = timestamp.strftime("%Y%m%dT%H%M%S")
        filename = f"{item.label}_{format.value.lower()}_{stamp}{extension}"
        return item.output_directory / filename


__all__ = [
    "ExportFormat",
    "DEFAULT_EXPORT_SETTINGS",
    "BatchExportItem",
    "ExportRecord",
    "BatchExportResult",
    "BatchExporter",
]

