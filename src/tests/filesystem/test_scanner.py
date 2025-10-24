from __future__ import annotations

from pathlib import Path
from typing import Iterator, Any

from _pytest.monkeypatch import MonkeyPatch

from libraries.platform.filesystem import scanner
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


def test_scan_project_files_skips_unreadable_directories(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    readable_file = tmp_path / "seq" / "ep101_sc01_0010" / "playblast_v001.mov"
    unreadable_dir = tmp_path / "seq" / "ep101_sc02_0010"
    unreadable_file = unreadable_dir / "playblast_v010.mov"

    _touch(readable_file)
    _touch(unreadable_file)

    original_iterdir = Path.iterdir

    def fake_iterdir(self: Path) -> Iterator[Path]:
        if self == unreadable_dir:
            raise PermissionError("access denied")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)

    class DummyLog:
        def __init__(self) -> None:
            self.warning_calls: list[Any] = []

        def warning(self, *args: Any, **kwargs: Any) -> None:
            self.warning_calls.append((args, kwargs))

        def info(
            self, *args: Any, **kwargs: Any
        ) -> None:  # pragma: no cover - not asserted
            pass

    dummy_log = DummyLog()
    monkeypatch.setattr(scanner, "log", dummy_log)

    results = scan_project_files(tmp_path)

    assert results == [
        {"shot": "ep101_sc01_0010", "version": "v001", "path": str(readable_file)}
    ]
    assert dummy_log.warning_calls
    assert dummy_log.warning_calls[0][0][0] == "filesystem.scan.unreadable_path"
