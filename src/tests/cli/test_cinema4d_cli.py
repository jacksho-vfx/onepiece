from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from typer.testing import CliRunner

from libraries.creative.dcc.cinema4d.gather import GatherResult
from libraries.creative.dcc.cinema4d.metadata import SUMMARY_ENV_VAR

cinema4d_module = import_module("apps.onepiece.dcc.cinema4d")


def test_cinema4d_validate_success(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Successful validations emit a success message and exit cleanly."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    runner = CliRunner()
    received: dict[str, Path] = {}

    def fake_validate_package(path: Path) -> list[str]:
        received["path"] = path
        return []

    monkeypatch.setattr(cinema4d_module, "validate_package", fake_validate_package)

    result = runner.invoke(
        cinema4d_module.app,
        [
            "validate",
            str(package_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"Cinema 4D package at {package_dir} passed validation." in result.output
    assert received["path"] == package_dir


def test_cinema4d_validate_failure(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Validation issues are listed and return a non-zero exit code."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    runner = CliRunner()

    def fake_validate_package(path: Path) -> list[str]:
        assert path == package_dir
        return [
            "Missing Cinema4D texture files: tex/mat.png",
            "Missing Cinema4D preset files: presets/lighting.c4d",
        ]

    monkeypatch.setattr(cinema4d_module, "validate_package", fake_validate_package)

    result = runner.invoke(
        cinema4d_module.app,
        [
            "validate",
            str(package_dir),
        ],
    )

    assert result.exit_code == 1
    assert "Cinema 4D package validation detected issues:" in result.output
    assert "- Missing Cinema4D texture files: tex/mat.png" in result.output
    assert "- Missing Cinema4D preset files: presets/lighting.c4d" in result.output


def test_cinema4d_show_summary_success(tmp_path: Path) -> None:
    """The summary command prints key metadata and exits cleanly."""

    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "frame_range": [101, 124],
                "renderer": "Redshift",
                "take": "Final",
                "fps": 24,
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        cinema4d_module.app,
        ["show-summary", str(summary_path)],
    )

    assert result.exit_code == 0, result.output
    assert "Cinema 4D Summary" in result.output
    assert "Frame range: 101 - 124" in result.output
    assert "Renderer: Redshift" in result.output
    assert "Take: Final" in result.output
    assert "fps: 24" in result.output


def test_cinema4d_show_summary_missing_file(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Missing summary files surface an actionable error message."""

    missing_path = tmp_path / "missing.json"
    monkeypatch.setenv(SUMMARY_ENV_VAR, str(missing_path))

    runner = CliRunner()
    result = runner.invoke(
        cinema4d_module.app,
        ["show-summary"],
    )

    assert result.exit_code == 1
    assert "No Cinema 4D summary metadata is available." in result.output


def test_cinema4d_show_summary_empty(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Empty payloads are treated as missing summaries."""

    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}")

    monkeypatch.setenv(SUMMARY_ENV_VAR, str(summary_path))

    runner = CliRunner()
    result = runner.invoke(
        cinema4d_module.app,
        ["show-summary"],
    )

    assert result.exit_code == 1
    assert "No Cinema 4D summary metadata is available." in result.output


def test_cinema4d_gather_assets_success(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Gathering with no missing assets exits successfully."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    runner = CliRunner()

    def fake_gather_references(
        package_dir: Path, source_root: Path | None = None
    ) -> GatherResult:
        assert source_root is None
        return GatherResult(copied=("tex/diffuse.png",), missing=(), issues=())

    monkeypatch.setattr(cinema4d_module, "gather_references", fake_gather_references)

    result = runner.invoke(
        cinema4d_module.app,
        ["gather-assets", str(package_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "Copied assets" in result.output


def test_cinema4d_gather_assets_reports_missing(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Missing references surface in the CLI output and exit code."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    runner = CliRunner()

    def fake_gather_references(
        package_dir: Path, source_root: Path | None = None
    ) -> GatherResult:
        assert source_root == source_dir
        return GatherResult(
            copied=(),
            missing=("tex/specular.png",),
            issues=("Cinema4D references must stay within the package: ..",),
        )

    monkeypatch.setattr(cinema4d_module, "gather_references", fake_gather_references)

    result = runner.invoke(
        cinema4d_module.app,
        ["gather-assets", str(package_dir), str(source_dir)],
    )

    assert result.exit_code == 1
    assert "Missing assets" in result.output
    assert "Cinema 4D reference issues detected" in result.output


def test_cinema4d_normalise_paths_success(tmp_path: Path) -> None:
    """Paths are rebased relative to the package and written to disk."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    absolute_texture = (package_dir / "tex" / "mat.tx").resolve()
    metadata_path = package_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps({"cinema4d": {"textures": [str(absolute_texture)]}})
    )

    runner = CliRunner()
    result = runner.invoke(cinema4d_module.app, ["normalise-paths", str(package_dir)])

    assert result.exit_code == 0, result.output
    assert "asset paths normalised" in result.output

    payload = json.loads(metadata_path.read_text())
    assert payload["cinema4d"]["textures"] == ["tex/mat.tx"]


def test_cinema4d_normalise_paths_reports_warnings(tmp_path: Path) -> None:
    """Warnings are surfaced when paths cannot be rebased."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    metadata_path = package_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps({"cinema4d": {"textures": [r"C:\\assets\\wood.tx"]}})
    )

    runner = CliRunner()
    result = runner.invoke(cinema4d_module.app, ["normalise-paths", str(package_dir)])

    assert result.exit_code == 1
    assert "Some asset paths still need manual attention" in result.output
    assert "Unable to rebase Windows absolute path" in result.output

    payload = json.loads(metadata_path.read_text())
    assert payload["cinema4d"]["textures"] == ["C:/assets/wood.tx"]


def test_cinema4d_normalise_paths_already_relative(tmp_path: Path) -> None:
    """Already normalised metadata exits successfully without modifications."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    metadata_path = package_dir / "metadata.json"
    metadata_path.write_text(json.dumps({"cinema4d": {"textures": ["tex/mat.tx"]}}))

    original = metadata_path.read_text()

    runner = CliRunner()
    result = runner.invoke(cinema4d_module.app, ["normalise-paths", str(package_dir)])

    assert result.exit_code == 0
    assert "already normalised" in result.output
    assert metadata_path.read_text() == original


def test_cinema4d_normalise_paths_missing_metadata(tmp_path: Path) -> None:
    """Missing metadata surfaces a helpful error message."""

    package_dir = tmp_path / "package"
    package_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(cinema4d_module.app, ["normalise-paths", str(package_dir)])

    assert result.exit_code == 1
    assert "metadata.json is missing or unreadable" in result.output


def test_cinema4d_cleanup_scene_reports_summary(
    monkeypatch: MonkeyPatch,
) -> None:
    """Cleanup summary prints and logs aggregated statistics."""

    runner = CliRunner()

    def fake_cleanup_scene(**kwargs: object) -> dict[str, int]:
        assert kwargs == {
            "remove_unused_materials": True,
            "remove_empty_nulls": False,
            "remove_hidden_singletons": True,
            "remove_unused_layers": True,
        }
        return {
            "removed_materials": 5,
            "removed_empty_nulls": 0,
            "removed_hidden_singletons": 2,
            "removed_layers": 4,
        }

    monkeypatch.setattr(cinema4d_module, "cleanup_scene", fake_cleanup_scene)

    result = runner.invoke(
        cinema4d_module.app,
        ["cleanup-scene", "--keep-empty-nulls"],
    )

    assert result.exit_code == 0, result.output
    assert (
        "Cinema 4D cleanup complete. Removed 5 materials, 0 nulls, 2 hidden objects, 4 layers."
        in result.output
    )


def test_cinema4d_cleanup_scene_requires_enabled_operation() -> None:
    """At least one cleanup operation must run to avoid a misfire."""

    runner = CliRunner()

    result = runner.invoke(
        cinema4d_module.app,
        [
            "cleanup-scene",
            "--keep-unused-materials",
            "--keep-empty-nulls",
            "--keep-hidden-singletons",
            "--keep-unused-layers",
        ],
    )

    assert result.exit_code != 0
    assert "At least one cleanup operation must be enabled" in result.output
