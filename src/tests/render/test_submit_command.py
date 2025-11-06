"""Tests for the render submission CLI."""

from __future__ import annotations

import getpass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from apps.onepiece.render import submit as submit_module
from apps.onepiece.utils.errors import (
    ExitCode,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from libraries.automation.render.base import RenderSubmissionError


def test_render_submit_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
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
    monkeypatch.setattr(submit_module, "log", event_logger)

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
    assert called["priority"] == 65
    assert called["user"] == getpass.getuser()
    assert called["chunk_size"] == 2
    assert "Optimised submission" in result.stdout

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.start") in events
    assert ("info", "render.submit.optimized") in events
    assert ("info", "render.submit.success") in events


def test_render_submit_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
    event_logger: SimpleNamespace,
) -> None:
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
    monkeypatch.setattr(submit_module, "log", event_logger)

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
    assert isinstance(result.exception, OnePieceExternalServiceError)
    assert result.exception.exit_code == ExitCode.EXTERNAL
    assert "Render submission failed: Adapter failure" in str(result.exception)


def test_render_submit_reuses_capabilities_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
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
        return {
            "job_id": "job-456",
            "status": "queued",
            "farm_type": "mock",
        }

    capability_calls = 0

    def fake_capabilities() -> dict[str, Any]:
        nonlocal capability_calls
        capability_calls += 1
        return {
            "default_priority": 50,
            "priority_min": 10,
            "priority_max": 90,
            "chunk_size_enabled": True,
            "default_chunk_size": 5,
            "chunk_size_min": 1,
            "chunk_size_max": 10,
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS, "mock", fake_capabilities
    )

    args = [
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
        "--farm",
        "mock",
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout

    assert capability_calls == 1


def test_render_submit_refresh_capabilities_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")
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
        return {
            "job_id": "job-789",
            "status": "queued",
            "farm_type": "mock",
        }

    capability_calls = 0

    def fake_capabilities() -> dict[str, Any]:
        nonlocal capability_calls
        capability_calls += 1
        return {
            "default_priority": 45,
            "priority_min": 5,
            "priority_max": 95,
            "chunk_size_enabled": False,
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS, "mock", fake_capabilities
    )

    base_args = [
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
        "--farm",
        "mock",
    ]

    first = runner.invoke(app, base_args)
    assert first.exit_code == 0, first.stdout

    refreshed = runner.invoke(app, base_args + ["--refresh-capabilities"])
    assert refreshed.exit_code == 0, refreshed.stdout

    assert capability_calls == 2


def test_render_submit_ignores_default_chunk_when_adapter_disables_chunking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    scene_file = tmp_path / "shot01.blend"
    scene_file.write_text("requires blender")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

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
            "job_id": "job-789",
            "status": "submitted",
            "farm_type": "mock",
        }

    monkeypatch.setitem(submit_module.FARM_ADAPTERS, "mock", fake_submit)
    monkeypatch.setitem(
        submit_module.FARM_CAPABILITY_PROVIDERS,
        "mock",
        lambda: {
            "default_priority": 42,
            "priority_min": 0,
            "priority_max": 100,
            "chunk_size_enabled": False,
            "default_chunk_size": 6,
        },
    )

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "blender",
            "--scene",
            str(scene_file),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Submitted blender scene" in result.stdout
    assert captured["priority"] == 42
    assert captured["chunk_size"] is None


def test_render_submit_manual_overrides_bypass_optimization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
    scene_file = tmp_path / "shot02.nk"
    scene_file.write_text("print('manual overrides')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

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
            "job_id": "job-321",
            "status": "queued",
            "farm_type": "mock",
        }

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
    monkeypatch.setattr(submit_module, "log", event_logger)

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
            "--priority",
            "72",
            "--chunk-size",
            "6",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["priority"] == 72
    assert captured["chunk_size"] == 6

    optimisation_events = [
        event for event in log_events if event[1] == "render.submit.optimized"
    ]
    assert optimisation_events, "Expected optimisation summary log"
    for _, _, payload in optimisation_events:
        assert payload.get("applied") is False


def test_render_submit_no_optimize_uses_adapter_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
    scene_file = tmp_path / "shot03.nk"
    scene_file.write_text("print('no optimize')\n")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

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
            "job_id": "job-654",
            "status": "queued",
            "farm_type": "mock",
        }

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
    monkeypatch.setattr(submit_module, "log", event_logger)

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
            "--no-optimize",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["priority"] == 55
    assert captured["chunk_size"] == 4

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.submit.optimized") not in events


def test_render_submit_priority_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: CliRunner,
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
    assert isinstance(result.exception, OnePieceValidationError)
    assert result.exception.exit_code == ExitCode.VALIDATION
    assert "supported maximum" in str(result.exception)


def test_render_submit_requires_existing_scene(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    output_dir = tmp_path / "renders"
    output_dir.mkdir()

    missing_scene = tmp_path / "missing.nk"

    result = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "nuke",
            "--scene",
            str(missing_scene),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, OnePieceValidationError)
    assert "does not exist" in str(result.exception)


def test_render_submit_requires_output_directory(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    scene_file = tmp_path / "shot01.nk"
    scene_file.write_text("print('render')\n")

    output_file = tmp_path / "renders.txt"
    output_file.write_text("not a directory")

    result_missing = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "nuke",
            "--scene",
            str(scene_file),
            "--output",
            str(tmp_path / "missing"),
        ],
    )

    assert result_missing.exit_code != 0
    assert isinstance(result_missing.exception, OnePieceValidationError)
    assert "does not exist" in str(result_missing.exception)

    result_not_dir = runner.invoke(
        app,
        [
            "render",
            "submit",
            "--dcc",
            "nuke",
            "--scene",
            str(scene_file),
            "--output",
            str(output_file),
        ],
    )

    assert result_not_dir.exit_code != 0
    assert isinstance(result_not_dir.exception, OnePieceValidationError)
    assert "not a directory" in str(result_not_dir.exception)
