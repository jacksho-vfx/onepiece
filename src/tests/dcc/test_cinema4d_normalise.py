from __future__ import annotations

import json
from pathlib import Path

from libraries.creative.dcc.cinema4d.validation import normalise_asset_paths


def _write_metadata(package: Path, payload: dict[str, object]) -> Path:
    metadata_path = package / "metadata.json"
    metadata_path.write_text(json.dumps(payload))
    return metadata_path


def test_normalise_asset_paths_rebases_absolute(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    texture_path = (package / "tex" / "wood.tx").resolve()
    _write_metadata(package, {"cinema4d": {"textures": [str(texture_path)]}})

    result = normalise_asset_paths(package)

    assert result.metadata is not None
    assert result.updated is True
    assert result.warnings == ()
    assert result.metadata["cinema4d"]["textures"] == ["tex/wood.tx"]


def test_normalise_asset_paths_warns_windows_absolute(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    _write_metadata(package, {"cinema4d": {"textures": [r"C:\\assets\\mat.tx"]}})

    result = normalise_asset_paths(package)

    assert result.metadata is not None
    assert result.updated is True
    assert any(
        "Unable to rebase Windows absolute path" in warning
        for warning in result.warnings
    )
    assert result.metadata["cinema4d"]["textures"] == ["C:/assets/mat.tx"]


def test_normalise_asset_paths_reports_traversal(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    _write_metadata(package, {"cinema4d": {"presets": ["../outside/preset.c4d"]}})

    result = normalise_asset_paths(package)

    assert result.metadata is not None
    assert result.updated is False
    assert any(
        "Relative path escapes the package" in warning for warning in result.warnings
    )
    assert result.metadata["cinema4d"]["presets"] == ["../outside/preset.c4d"]


def test_normalise_asset_paths_handles_already_relative(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    _write_metadata(
        package,
        {"cinema4d": {"textures": ["tex/wood.tx"], "presets": ["presets/light.c4d"]}},
    )

    result = normalise_asset_paths(package)

    assert result.metadata is not None
    assert result.updated is False
    assert result.warnings == ()
    assert result.metadata["cinema4d"]["textures"] == ["tex/wood.tx"]
    assert result.metadata["cinema4d"]["presets"] == ["presets/light.c4d"]
