"""Tests for render submission script helpers."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from apps.onepiece.app import app
from apps.onepiece.render.submit.scripts import (
    build_render_script_bundle,
    run_render_submission,
    sanity_check_submission,
)


def test_sanity_check_reports_errors(tmp_path: Path) -> None:
    scene = tmp_path / "scene.ma"
    output = tmp_path / "renders"

    report = sanity_check_submission(scene=scene, output=output, frames="1-10x0")

    assert not report["ok"]
    assert "does not exist" in " ".join(report["errors"])
    assert report["frame_count"] is None


def test_run_render_submission_with_mock_adapter(tmp_path: Path) -> None:
    scene = tmp_path / "scene.nk"
    scene.write_text("print('render')\n")
    output = tmp_path / "renders"
    output.mkdir()

    submission = run_render_submission(
        dcc="nuke",
        farm="mock",
        scene=scene,
        frames="1-5",
        output=output,
    )

    assert submission["result"]["farm_type"] == "mock"
    assert submission["decision"] is not None


def test_build_render_script_bundle_includes_identifiers() -> None:
    bundle = build_render_script_bundle(dcc="maya", farm="mock", profile="studio")

    assert "maya" in bundle.panel
    assert "mock" in bundle.menu
    assert "studio" in bundle.optimizer


def test_generate_scripts_command(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            "scripts",
            "--dcc",
            "maya",
            "--farm",
            "mock",
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "panel_submission.py").exists()
    assert (tmp_path / "menu_submission.py").exists()
    assert (tmp_path / "optimisation_helper.py").exists()
    assert (tmp_path / "sanity_checker.py").exists()
