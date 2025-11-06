from __future__ import annotations

from importlib import import_module
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from typer.testing import CliRunner

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
            str(package_dir),
        ],
    )

    assert result.exit_code == 1
    assert "Cinema 4D package validation detected issues:" in result.output
    assert "- Missing Cinema4D texture files: tex/mat.png" in result.output
    assert "- Missing Cinema4D preset files: presets/lighting.c4d" in result.output
