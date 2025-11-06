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
