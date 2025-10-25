from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest_mock
from typer.testing import CliRunner

from apps.trafalgar import app as trafalgar_app


runner = CliRunner()


def test_dashboard_command_invokes_uvicorn(mocker: pytest_mock.MockerFixture) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)

    result = runner.invoke(
        trafalgar_app,
        [
            "web",
            "dashboard",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--log-level",
            "debug",
        ],
    )

    assert result.exit_code == 0
    uvicorn_mock.run.assert_called_once_with(
        "apps.trafalgar.web.dashboard:app",
        host="0.0.0.0",
        port=9000,
        reload=False,
        log_level="debug",
    )


def test_dashboard_command_can_open_browser(mocker: pytest_mock.MockerFixture) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)
    browser_controller = SimpleNamespace(open=Mock(return_value=True))
    browser_get = mocker.patch(
        "apps.trafalgar.app.webbrowser.get", return_value=browser_controller
    )

    result = runner.invoke(
        trafalgar_app,
        [
            "web",
            "dashboard",
            "--host",
            "0.0.0.0",
            "--port",
            "9050",
            "--open-browser",
        ],
    )

    assert result.exit_code == 0
    browser_get.assert_called_once_with()
    browser_controller.open.assert_called_once_with(
        "http://0.0.0.0:9050", new=2
    )
    uvicorn_mock.run.assert_called_once()


def test_ingest_command_invokes_uvicorn(mocker: pytest_mock.MockerFixture) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)

    result = runner.invoke(
        trafalgar_app,
        [
            "ingest",
            "--host",
            "0.0.0.0",
            "--port",
            "9100",
            "--log-level",
            "warning",
        ],
    )

    assert result.exit_code == 0
    uvicorn_mock.run.assert_called_once_with(
        "apps.trafalgar.web.ingest:app",
        host="0.0.0.0",
        port=9100,
        reload=False,
        log_level="warning",
    )


def test_web_ingest_command_is_still_supported(
    mocker: pytest_mock.MockerFixture,
) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)

    result = runner.invoke(
        trafalgar_app,
        [
            "web",
            "ingest",
            "--host",
            "0.0.0.0",
            "--port",
            "9200",
            "--log-level",
            "error",
        ],
    )

    assert result.exit_code == 0
    uvicorn_mock.run.assert_called_once_with(
        "apps.trafalgar.web.ingest:app",
        host="0.0.0.0",
        port=9200,
        reload=False,
        log_level="error",
    )


def test_web_review_command_invokes_uvicorn(mocker: pytest_mock.MockerFixture) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)

    result = runner.invoke(
        trafalgar_app,
        [
            "web",
            "review",
            "--host",
            "0.0.0.0",
            "--port",
            "9300",
            "--log-level",
            "critical",
        ],
    )

    assert result.exit_code == 0
    uvicorn_mock.run.assert_called_once_with(
        "apps.trafalgar.web.review:app",
        host="0.0.0.0",
        port=9300,
        reload=False,
        log_level="critical",
    )
