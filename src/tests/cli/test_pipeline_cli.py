"""Smoke tests for the pipeline CLI wiring."""

from __future__ import annotations

from typer.testing import CliRunner

from apps.onepiece.app import app as onepiece_app


runner = CliRunner()


def test_pipeline_command_group_loads() -> None:
    result = runner.invoke(onepiece_app, ["pipeline", "--help"])

    assert result.exit_code == 0
    assert "Interact with the OnePiece pipeline orchestrator." in result.output
    assert "list" in result.output
    assert "describe" in result.output
    assert "run" in result.output
