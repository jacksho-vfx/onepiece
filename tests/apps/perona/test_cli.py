"""CLI regression tests for the Perona Typer application."""

from typer.testing import CliRunner

from apps.perona.app import app
from apps.perona.version import PERONA_VERSION


runner = CliRunner()


def test_version_command_outputs_perona_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert PERONA_VERSION in result.output
