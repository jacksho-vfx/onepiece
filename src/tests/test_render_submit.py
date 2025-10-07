"""Tests for the render submission CLI."""

from __future__ import annotations

import getpass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from libraries.render.base import RenderSubmissionError
from apps.onepiece.render import submit as submit_module

runner = CliRunner()


def _capture_logger(
    log_events: list[tuple[str, str, dict[str, Any]]]
) -> SimpleNamespace:
    def _info(event: str, **kwargs: Any) -> None:
        log_events.append(("info", event, kwargs))

    def _error(event: str, **kwargs: Any) -> None:
        log_events.append(("error", event, kwargs))

    def _exception(event: str, **kwargs: Any) -> None:
        log_events.append(("exception", event, kwargs))

    return SimpleNamespace(info=_info, error=_error, exception=_exception)


def test_render_submit_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    called: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        called.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-123",
            "status": "queued",
            "farm_type": "mock",
        }

    log_events: list[tuple[str, str, dict[str, Any]]] = []

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 55,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 4,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        },
    )
    monkeypatch.setattr(submit_module, "log", _capture_logger(log_events))

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "Nuke",
            "--scene",
            str(scene_file),
            "--frames",
            "1-10",
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Submitted nuke scene" in result.stdout
    assert called["scene"] == str(scene_file)
    assert called["output"] == str(output_dir)
    assert called["frames"] == "1-10"
    assert called["dcc"] == "nuke"
    assert called["priority"] == 55
    assert called["user"] == getpass.getuser()
    assert called["chunk_size"] == 4

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.start") in events
    assert ("info", "render.submit.success") in events


def test_render_submit_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scene_file = tmp_path / "shot01.ma"
    scene_file.write_text("requires maya")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    def failing_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        raise RenderSubmissionError("Adapter failure")

    log_events: list[tuple[str, str, dict[str, Any]]] = []

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", failing_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 50,
            "priority_min": 0,
            "priority_max": 100,
            "chunk_size_enabled": False,
        },
    )
    monkeypatch.setattr(submit_module, "log", _capture_logger(log_events))

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "maya",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 1
    assert "Render submission failed: Adapter failure" in result.stderr

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.start") in events
    assert ("error", "render.submit.failed") in events


def test_render_submit_priority_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.hip"
    scene_file.write_text("requires houdini")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        return {}

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 50,
            "priority_min": 1,
            "priority_max": 100,
            "chunk_size_enabled": True,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        },
    )

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "houdini",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
            "--priority",
            "200",
        ],
    )

    assert result.exit_code != 0
    assert "supported maximum" in result.stderr


def test_render_preset_crud_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    preset_dir = tmp_path / "presets"
    monkeypatch.setenv("ONEPIECE_RENDER_PRESET_DIR", str(preset_dir))

    captured: dict[str, Any] = {}

    def fake_submit(
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        captured.update(
            {
                "scene": scene,
                "frames": frames,
                "output": output,
                "dcc": dcc,
                "priority": priority,
                "user": user,
                "chunk_size": chunk_size,
            }
        )
        return {
            "job_id": "job-456",
            "status": "submitted",
            "farm_type": "mock",
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 65,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 3,
            "chunk_size_min": 1,
            "chunk_size_max": 8,
        },
    )

    save_result = runner.invoke(
        app,
        [
            "render",
            "preset",
            "save",
            "daily_nuke",
            "--farm",
            "mock",
            "--dcc",
            "nuke",
            "--frames",
            "1-20",
        ],
    )

    assert save_result.exit_code == 0, save_result.stdout
    assert "Saved preset" in save_result.stdout

    list_result = runner.invoke(app, ["render", "preset", "list"])
    assert list_result.exit_code == 0
    assert "daily_nuke" in list_result.stdout

    use_result = runner.invoke(
        app,
        [
            "render",
            "preset",
            "use",
            "daily_nuke",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
        ],
    )

    assert use_result.exit_code == 0, use_result.stdout
    assert "Submitted nuke scene" in use_result.stdout
    assert captured["scene"] == str(scene_file)
    assert captured["output"] == str(output_dir)
    assert captured["frames"] == "1-20"
    assert captured["dcc"] == "nuke"
    assert captured["priority"] == 65
    assert captured["chunk_size"] == 3
