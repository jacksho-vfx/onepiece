from __future__ import annotations

from pathlib import Path

from libraries.platform.filesystem.scanner import scan_project_files


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_scan_project_files_accepts_case_insensitive_scope(tmp_path: Path) -> None:
    file_one = tmp_path / "seq" / "ep101_sc01_0010" / "playblast_v001.mov"
    file_two = tmp_path / "assets" / "ep101_sc01_0010_asset" / "model_v010.ma"
    _touch(file_one)
    _touch(file_two)

    shots = scan_project_files(tmp_path, scope="SHOTS")
    assets = scan_project_files(tmp_path, scope="ASSETS")

    shot_names = {entry["shot"] for entry in shots}
    asset_names = {entry["shot"] for entry in assets}

    assert "ep101_sc01_0010" in shot_names
    assert "ep101_sc01_0010_asset" in asset_names


def test_scan_project_files_returns_sorted_results(tmp_path: Path) -> None:
    paths = [
        tmp_path / "ep101_sc01_0010" / "playblast_v010.mov",
        tmp_path / "ep101_sc01_0010" / "playblast_v002.mov",
        tmp_path / "ep101_sc02_0010" / "lighting_v001.mov",
    ]
    for path in reversed(paths):
        _touch(path)

    results = scan_project_files(tmp_path)

    ordered_pairs = [(entry["shot"], entry["version"]) for entry in results]

    assert ordered_pairs == [
        ("ep101_sc01_0010", "v002"),
        ("ep101_sc01_0010", "v010"),
        ("ep101_sc02_0010", "v001"),
    ]
