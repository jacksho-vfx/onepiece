"""CLI regression tests for the Perona Typer application."""

import os

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from apps.perona.app import DEFAULT_HOST, DEFAULT_PORT, app
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


def test_dashboard_command_sets_settings_path_env(
    mocker: MockerFixture, tmp_path
) -> None:
    env_key = "PERONA_SETTINGS_PATH"
    os.environ.pop(env_key, None)

    uvicorn_mock = mocker.Mock()
    uvicorn_mock.run = mocker.Mock()
    mocker.patch("apps.perona.app.import_module", return_value=uvicorn_mock)

    settings_path = tmp_path / "perona.toml"

    result = runner.invoke(
        app,
        ["web", "dashboard", "--settings-path", str(settings_path)],
    )

    assert result.exit_code == 0
    assert os.environ[env_key] == str(settings_path)
    uvicorn_mock.run.assert_called_once_with(
        "apps.perona.web.dashboard:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=False,
        log_level="info",
    )

    os.environ.pop(env_key, None)
