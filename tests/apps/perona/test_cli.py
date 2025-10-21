"""CLI regression tests for the Perona Typer application."""

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from apps.perona.app import app
from apps.perona.version import PERONA_VERSION


runner = CliRunner()


def test_version_command_outputs_perona_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert PERONA_VERSION in result.output


def test_dashboard_command_reports_missing_uvicorn(mocker: MockerFixture) -> None:
    mocker.patch("apps.perona.app.import_module", side_effect=ImportError("uvicorn"))

    result = runner.invoke(app, ["web", "dashboard"])

    assert result.exit_code != 0
    assert "Install it with `pip install onepiece[uvicorn]`" in result.output
