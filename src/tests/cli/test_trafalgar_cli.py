from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest_mock
from typer.testing import CliRunner

import textwrap

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
    browser_controller.open.assert_called_once_with("http://0.0.0.0:9050", new=2)
    uvicorn_mock.run.assert_called_once()


def test_dashboard_command_opens_demo_browser_when_requested(
    mocker: pytest_mock.MockerFixture,
) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)
    browser_controller = SimpleNamespace(open=Mock(return_value=True))
    mocker.patch("apps.trafalgar.app.webbrowser.get", return_value=browser_controller)
    process_instance = SimpleNamespace(
        start=Mock(return_value=None),
        terminate=Mock(return_value=None),
        join=Mock(return_value=None),
    )
    process_factory = mocker.patch(
        "apps.trafalgar.app.Process", return_value=process_instance
    )

    result = runner.invoke(
        trafalgar_app,
        [
            "web",
            "dashboard",
            "--demo-port",
            "8100",
            "--open-browser",
        ],
    )

    assert result.exit_code == 0
    process_factory.assert_called_once()
    browser_controller.open.assert_has_calls(
        [
            call("http://127.0.0.1:8000", new=2),
            call("http://127.0.0.1:8100", new=2),
        ]
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


def test_pipeline_push_upserts_definition(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    manifest = tmp_path / "pipeline.toml"
    manifest.write_text(
        textwrap.dedent(
            """
            name = "custom"
            display_name = "Custom Pipeline"
            description = "Example pipeline"

            [metadata]
            owner = "pipeline"

            [[steps]]
            name = "prepare"
            provider = "tests.pipeline:prepare"

            [[steps]]
            name = "publish"
            provider = "tests.pipeline:publish"
            """
        ).strip()
        + "\n"
    )

    orchestrator = SimpleNamespace(upsert=Mock(return_value=True))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(
        trafalgar_app, ["pipeline", "push", str(manifest)]
    )

    assert result.exit_code == 0, result.stdout
    orchestrator.upsert.assert_called_once()
    definition = orchestrator.upsert.call_args[0][0]
    assert definition.name == "custom"
    assert "Pipeline 'custom' created" in result.stdout


def test_pipeline_delete_invokes_deregister(
    mocker: pytest_mock.MockerFixture,
) -> None:
    orchestrator = SimpleNamespace(deregister=Mock(return_value=None))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(
        trafalgar_app, ["pipeline", "delete", "custom"]
    )

    assert result.exit_code == 0
    orchestrator.deregister.assert_called_once_with("custom")
    assert "Pipeline 'custom' deregistered" in result.stdout
