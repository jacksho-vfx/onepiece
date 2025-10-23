"""Tests for the Maya batch export helper."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, cast

import pytest

from libraries.creative.dcc.maya.batch_exporter import (
    BatchExportItem,
    BatchExporter,
    ExportFormat,
)
from libraries.creative.dcc.utils import normalize_frame_range, sanitize_token


def _clock_factory(start: _dt.datetime) -> Callable[[], _dt.datetime]:
    current = start

    def _clock() -> _dt.datetime:
        nonlocal current
        value = current
        current = current + _dt.timedelta(seconds=1)
        return value

    return _clock


class _Recorder:
    def __init__(self, *, suffix: bytes) -> None:
        self.calls: list[dict[str, object]] = []
        self.suffix = suffix

    def __call__(
        self,
        scene_path: Path,
        output_path: Path,
        *,
        root_nodes: tuple[str, ...],
        settings: dict[str, object],
        frame_range: tuple[int, int] | None,
    ) -> Path:
        output_path.write_bytes(self.suffix)
        self.calls.append(
            {
                "scene_path": scene_path,
                "output_path": output_path,
                "root_nodes": root_nodes,
                "settings": settings,
                "frame_range": frame_range,
            }
        )
        return output_path


def test_exporter_runs_registered_formats(tmp_path: Path) -> None:
    scene = tmp_path / "shot.ma"
    scene.write_text("maya")
    clock = _clock_factory(_dt.datetime(2024, 5, 1, 9, 30))

    fbx = _Recorder(suffix=b"fbx")
    abc = _Recorder(suffix=b"abc")
    usd = _Recorder(suffix=b"usd")

    exporter = BatchExporter(
        exporters={
            ExportFormat.FBX: fbx,
            ExportFormat.ALEMBIC: abc,
            ExportFormat.USD: usd,
        },
        clock=clock,
    )

    item = BatchExportItem(
        scene_path=scene,
        output_directory=tmp_path / "exports",
        root_nodes=("char:root", "char:root"),
        shot="ep01_sh010",
        asset="Hero Character",
        frame_range=(100.2, 110.7),
        custom_settings={
            ExportFormat.FBX: {"triangulate": True},
            ExportFormat.USD: {"write_animation": False},
        },
    )

    results = exporter.export([item])

    assert len(results) == 1
    result = results[0]
    assert result.started_at == _dt.datetime(2024, 5, 1, 9, 30)
    assert result.completed_at == _dt.datetime(2024, 5, 1, 9, 30, 1)

    exports = {record.format: record for record in result.exports}
    assert set(exports) == {ExportFormat.FBX, ExportFormat.ALEMBIC, ExportFormat.USD}

    fbx_record = exports[ExportFormat.FBX]
    assert fbx_record.output_path.suffix == ".fbx"
    assert "EP01_SH010_HERO_CHARACTER" in fbx_record.output_path.name
    assert fbx_record.settings["triangulate"] is True
    assert fbx.calls[0]["frame_range"] == normalize_frame_range((100.2, 110.7))

    abc_record = exports[ExportFormat.ALEMBIC]
    assert abc_record.output_path.suffix == ".abc"
    assert abc_record.settings["uv_write"] is True
    assert cast("dict[str, Any]", abc.calls[0])["settings"]["world_space"] is True

    usd_record = exports[ExportFormat.USD]
    assert usd_record.output_path.suffix == ".usd"
    assert usd_record.settings["write_animation"] is False
    assert usd.calls[0]["root_nodes"] == ("char:root",)


def test_batch_export_item_normalizes_values(tmp_path: Path) -> None:
    item = BatchExportItem(
        scene_path=tmp_path / "scene.ma",
        output_directory=tmp_path / "exports",
        root_nodes=("char:root", "char:root"),
        formats=(ExportFormat.FBX, ExportFormat.FBX, ExportFormat.USD),
        frame_range=(150.5, 160.2),
    )

    assert item.root_nodes == ("char:root",)
    assert item.formats == (ExportFormat.FBX, ExportFormat.USD)
    assert item.frame_range == normalize_frame_range((150.5, 160.2))
    assert item.label == "CHAR_ROOT"


def test_batch_export_item_label_uses_shared_sanitizer(tmp_path: Path) -> None:
    item = BatchExportItem(
        scene_path=tmp_path / "scene.ma",
        output_directory=tmp_path / "exports",
        root_nodes=("root",),
        shot="Episode 01",
        asset="Hero/Main",
        tag="  preview!  ",
    )

    expected = "_".join(
        sanitize_token(token) for token in ("Episode 01", "Hero/Main", "  preview!  ")
    )
    assert item.label == expected


def test_custom_settings_must_match_formats(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BatchExportItem(
            scene_path=tmp_path / "scene.ma",
            output_directory=tmp_path / "exports",
            root_nodes=("char:root",),
            formats=(ExportFormat.FBX,),
            custom_settings={ExportFormat.USD: {}},
        )


def test_missing_exporter_raises(tmp_path: Path) -> None:
    exporter = BatchExporter(exporters={})
    item = BatchExportItem(
        scene_path=tmp_path / "scene.ma",
        output_directory=tmp_path / "exports",
        root_nodes=("char:root",),
        formats=(ExportFormat.FBX,),
    )

    with pytest.raises(RuntimeError):
        exporter.export([item])


def test_multiple_runs_produce_unique_paths(tmp_path: Path) -> None:
    scene = tmp_path / "shot.ma"
    scene.write_text("maya")

    def clock() -> _dt.datetime:
        return _dt.datetime(2024, 5, 1, 9, 30)

    recorder = _Recorder(suffix=b"fbx")
    exporter = BatchExporter(exporters={ExportFormat.FBX: recorder}, clock=clock)

    item = BatchExportItem(
        scene_path=scene,
        output_directory=tmp_path / "exports",
        root_nodes=("char:root",),
        shot="ep01_sh010",
        formats=(ExportFormat.FBX,),
    )

    exporter.export([item])
    exporter.export([item])

    assert len(recorder.calls) == 2
    first = Path(recorder.calls[0]["output_path"])  # type: ignore[arg-type]
    second = Path(recorder.calls[1]["output_path"])  # type: ignore[arg-type]

    assert first != second
    assert first.exists()
    assert second.exists()


def test_exporter_mutations_do_not_leak_into_records(tmp_path: Path) -> None:
    scene = tmp_path / "shot.ma"
    scene.write_text("maya")

    mutated_settings: dict[str, Any] = {}

    def mutating_exporter(
        scene_path: Path,
        output_path: Path,
        *,
        root_nodes: tuple[str, ...],
        settings: dict[str, Any],
        frame_range: tuple[int, int] | None,
    ) -> Path:
        del scene_path, root_nodes, frame_range
        settings["triangulate"] = False
        settings["in_exporter"] = True
        mutated_settings.clear()
        mutated_settings.update(settings)
        output_path.write_bytes(b"fbx")
        return output_path

    exporter = BatchExporter(exporters={ExportFormat.FBX: mutating_exporter})

    item = BatchExportItem(
        scene_path=scene,
        output_directory=tmp_path / "exports",
        root_nodes=("char:root",),
        formats=(ExportFormat.FBX,),
        custom_settings={ExportFormat.FBX: {"triangulate": True}},
    )

    result = exporter.export([item])[0]
    record = result.exports[0]

    assert isinstance(record.settings, MappingProxyType)
    assert record.settings["triangulate"] is True
    assert "in_exporter" not in record.settings
    assert mutated_settings["triangulate"] is False
    assert mutated_settings["in_exporter"] is True

    with pytest.raises(TypeError):
        record.settings["triangulate"] = False  # type: ignore[index]
