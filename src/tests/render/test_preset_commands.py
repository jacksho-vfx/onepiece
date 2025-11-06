"""Tests for render preset CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from apps.onepiece.render import submit as submit_module
from libraries.automation.render.base import RenderSubmissionError


def test_render_preset_crud_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
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


def test_render_preset_save_handles_capability_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    preset_dir = tmp_path / "presets"
    monkeypatch.setenv("ONEPIECE_RENDER_PRESET_DIR", str(preset_dir))

    def failing_capabilities() -> dict[str, Any]:
        raise RenderSubmissionError("capabilities offline")

    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS, "mock", failing_capabilities
    )

    result = runner.invoke(
        app,
        [
            "render",
            "preset",
            "save",
            "offline_mock",
            "--farm",
            "mock",
            "--dcc",
            "nuke",
        ],
    )

    assert result.exit_code == 0, result.stdout

    preset_file = preset_dir / "offline_mock.json"
    payload = json.loads(preset_file.read_text())

    assert payload["farm"] == "mock"
    assert payload.get("dcc") == "nuke"
    assert "priority" not in payload
    assert "chunk_size" not in payload
