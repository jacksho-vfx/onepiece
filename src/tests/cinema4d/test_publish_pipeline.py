"""Tests for the Cinema 4D scene validation and publishing pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from libraries.creative.dcc.cinema4d.publish_pipeline import (
    RenderLayer,
    SceneContext,
    Take,
    build_pipeline,
    collect_scene_context,
)


def test_collect_scene_context_loads_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.json"
    state_payload = {
        "frame_range": [1001, 1050],
        "textures": [str(tmp_path / "tex" / "wood.tx")],
        "render_layers": ["Beauty"],
        "takes": [{"name": "Main", "renderable": False}],
        "texture_color_spaces": {str(tmp_path / "tex" / "wood.tx"): "sRGB"},
    }
    state_path.write_text(json.dumps(state_payload))

    monkeypatch.setenv("SHOW", "TEST")
    monkeypatch.setenv("SHOT", "010")
    monkeypatch.setenv("ASSET", "Tree")
    monkeypatch.setenv("TASK", "lookdev")
    monkeypatch.setenv("SCENE_VERSION", "7")
    monkeypatch.setenv("EXPECTED_FRAME_RANGE", "1001-1050")
    monkeypatch.setenv("C4D_SCENE_STATE", str(state_path))
    monkeypatch.setenv("SCENE_FILE", str(tmp_path / "forest.c4d"))

    context = collect_scene_context(None)

    assert context.show == "TEST"
    assert context.shot == "010"
    assert context.asset == "Tree"
    assert context.task == "lookdev"
    assert context.version == 7
    assert context.frame_range == (1001, 1050)
    assert context.expected_frame_range == (1001, 1050)
    assert context.render_layers[0].name == "Beauty"
    assert context.takes[0].renderable is False


def test_scene_publish_pipeline_runs_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texture = tmp_path / "tex" / "wood.tx"
    texture.parent.mkdir(parents=True, exist_ok=True)
    texture.write_text("texture")

    context = SceneContext(
        show="SHOW",
        shot="SHOT",
        scene_path=tmp_path / "scene.c4d",
        version=3,
        textures=(texture,),
        render_layers=(RenderLayer(name="Beauty", renderable=True),),
        takes=(Take(name="Main", renderable=True),),
    )

    config = {
        "validators": ["missing_assets", "renderable_items"],
        "exports": [
            {
                "name": "geometry",
                "format": "usd",
                "output_dir": str(tmp_path / "exports"),
            },
            {"name": "metadata", "output_dir": str(tmp_path / "exports")},
        ],
        "log_directory": str(tmp_path / "logs"),
    }

    config_path = tmp_path / "show.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("ONEPIECE_C4D_PUBLISH_CONFIG", str(config_path))

    pipeline = build_pipeline(None)
    pipeline._context_provider = lambda: context  # type: ignore[attr-defined]

    result = pipeline.run()

    assert result.success is True
    assert result.version == 4
    geometry_exports = [
        summary for summary in result.exports if summary.name == "geometry"
    ]
    assert geometry_exports
    for export in geometry_exports[0].outputs:
        assert export.exists()
    assert result.metadata_path is not None and result.metadata_path.exists()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["show"] == "SHOW"
    assert result.log_file is not None and result.log_file.exists()


def test_scene_publish_pipeline_reports_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = SceneContext(
        show="SHOW",
        shot="SHOT",
        scene_path=tmp_path / "scene.c4d",
        version=1,
        textures=(tmp_path / "missing.tx",),
    )

    config = {
        "validators": ["missing_assets"],
        "exports": ["geometry"],
        "log_directory": str(tmp_path / "logs"),
    }

    config_path = tmp_path / "show.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("ONEPIECE_C4D_PUBLISH_CONFIG", str(config_path))

    pipeline = build_pipeline(None)
    pipeline._context_provider = lambda: context  # type: ignore[attr-defined]

    result = pipeline.run()

    assert result.success is False
    assert any("Missing texture" in issue.message for issue in result.report.issues)
    assert result.exports == ()
    assert result.metadata_path is None
    assert result.log_file is not None and result.log_file.exists()
