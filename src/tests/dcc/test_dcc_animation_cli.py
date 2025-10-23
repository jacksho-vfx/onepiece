from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from _pytest.monkeypatch import MonkeyPatch
from typer.testing import CliRunner

from libraries.dcc.maya.playblast_tool import PlayblastRequest


dcc_animation = import_module("apps.onepiece.dcc.animation")


class DummyLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.records.append((event, kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self.records.append((event, kwargs))


runner = CliRunner()


def test_debug_animation_reports_and_logs(monkeypatch: MonkeyPatch) -> None:
    log = DummyLogger()
    monkeypatch.setattr(dcc_animation, "log", log)

    issues = (
        SimpleNamespace(
            code="FRAME_RANGE_INVALID", message="Frame range broken", severity="error"
        ),
        SimpleNamespace(
            code="CACHE_NOT_LOADED", message="Cache not loaded", severity="warning"
        ),
    )
    report = SimpleNamespace(issues=issues)

    captured: dict[str, object] = {}

    def fake_debug_animation(*, scene_name: str) -> object:
        captured["scene_name"] = scene_name
        return report

    monkeypatch.setattr(dcc_animation, "debug_animation", fake_debug_animation)

    result = runner.invoke(
        dcc_animation.app, ["debug-animation", "--scene-name", "shot010"]
    )

    assert result.exit_code == dcc_animation.OnePieceValidationError.exit_code
    assert "Animation issues for shot010" in result.output
    assert captured["scene_name"] == "shot010"

    assert any(event == "dcc_animation_debug_issues" for event, _ in log.records)


def test_cleanup_scene_requires_operation(monkeypatch: MonkeyPatch) -> None:
    log = DummyLogger()
    monkeypatch.setattr(dcc_animation, "log", log)

    result = runner.invoke(
        dcc_animation.app,
        [
            "cleanup-scene",
            "--keep-unused-references",
            "--keep-namespaces",
            "--keep-layers",
            "--keep-unknown-nodes",
        ],
    )

    assert result.exit_code != 0
    assert "At least one cleanup operation" in result.output
    assert log.records == []


def test_cleanup_scene_logs_summary(monkeypatch: MonkeyPatch) -> None:
    log = DummyLogger()
    monkeypatch.setattr(dcc_animation, "log", log)

    def fake_cleanup_scene(**kwargs: object) -> dict[str, int]:
        assert kwargs == {
            "remove_unused_references": True,
            "clean_namespaces": False,
            "optimize_layers": True,
            "prune_unknown_nodes": True,
        }
        return {"removed_references": 2, "pruned_layers": 1}

    monkeypatch.setattr(dcc_animation, "cleanup_scene", fake_cleanup_scene)

    result = runner.invoke(
        dcc_animation.app,
        ["cleanup-scene", "--keep-namespaces"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Cleanup summary" in result.output
    assert any(event == "dcc_animation_cleanup_summary" for event, _ in log.records)


def test_playblast_validates_frame_range(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    log = DummyLogger()
    monkeypatch.setattr(dcc_animation, "log", log)

    result = runner.invoke(
        dcc_animation.app,
        [
            "playblast",
            "--project",
            "PROJ",
            "--shot",
            "SHOT010",
            "--artist",
            "alice",
            "--camera",
            "renderCam",
            "--version",
            "1",
            "--output-directory",
            str(tmp_path),
            "--frame-start",
            "1001",
        ],
    )

    assert result.exit_code != 0
    assert "frame-start and frame-end" in result.output
    assert log.records == []


def test_playblast_triggers_tool_and_logs(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    log = DummyLogger()
    monkeypatch.setattr(dcc_animation, "log", log)

    extra_metadata_file = tmp_path / "metadata.json"
    extra_metadata_file.write_text('{"department": "anim"}')

    class FakeTool:
        def __init__(self) -> None:
            self.request: PlayblastRequest | None = None

        def execute(self, request: PlayblastRequest) -> object:
            self.request = request
            return SimpleNamespace(
                output_path=Path(tmp_path / "playblast.mov"),
                frame_range=(1001, 1100),
                metadata={"department": "anim"},
                shotgrid_version={"code": "PB-010"},
                review_id="rv-123",
            )

    fake_tool = FakeTool()

    def fake_create_tool() -> FakeTool:
        return fake_tool

    monkeypatch.setattr(dcc_animation, "_create_playblast_tool", fake_create_tool)

    result = runner.invoke(
        dcc_animation.app,
        [
            "playblast",
            "--project",
            "PROJ",
            "--sequence",
            "SQ01",
            "--shot",
            "SHOT010",
            "--artist",
            "alice",
            "--camera",
            "renderCam",
            "--version",
            "2",
            "--output-directory",
            str(tmp_path),
            "--width",
            "1280",
            "--height",
            "720",
            "--frame-start",
            "1001",
            "--frame-end",
            "1100",
            "--description",
            "blocking pass",
            "--include-audio",
            "--metadata",
            str(extra_metadata_file),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert fake_tool.request is not None
    assert fake_tool.request.frame_range == (1001, 1100)
    assert fake_tool.request.resolution == (1280, 720)
    assert fake_tool.request.include_audio is True
    assert fake_tool.request.extra_metadata == {"department": "anim"}

    assert any(event == "dcc_animation_playblast_complete" for event, _ in log.records)
    assert "ShotGrid Version: PB-010" in result.output
    assert "Review ID: rv-123" in result.output
