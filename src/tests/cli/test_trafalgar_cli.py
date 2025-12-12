from __future__ import annotations

from datetime import datetime, timezone
import json
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

    result = runner.invoke(trafalgar_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 0, result.stdout
    orchestrator.upsert.assert_called_once()
    definition = orchestrator.upsert.call_args[0][0]
    assert definition.name == "custom"
    assert "Pipeline 'custom' created" in result.stdout


def test_pipeline_validate_reports_schema_errors(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    manifest = tmp_path / "invalid.toml"
    manifest.write_text(
        textwrap.dedent(
            """
            name = "broken"

            [steps]
            name = "prepare"
            uses = "tests.pipeline:prepare"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")

    result = runner.invoke(trafalgar_app, ["pipeline", "validate", str(manifest)])

    assert result.exit_code != 0
    assert str(manifest) in result.stderr
    assert "pipeline 'broken'" in result.stderr
    assert "Invalid value:" in result.stderr


def test_pipeline_validate_handles_multiple_entries(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    manifest = tmp_path / "pipelines.toml"
    manifest.write_text(
        textwrap.dedent(
            """
            [pipelines.alpha]
            summary = "Alpha pipeline"

            [[pipelines.alpha.steps]]
            id = "first"
            uses = "tests.pipeline:prepare"

            [pipelines.beta]
            summary = "Beta pipeline"

            [[pipelines.beta.steps]]
            id = "prepare"
            uses = "tests.pipeline:publish"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")

    result = runner.invoke(trafalgar_app, ["pipeline", "validate", str(manifest)])

    assert result.exit_code == 0, result.stderr
    assert "Validated 2 pipeline manifests" in result.stdout
    assert "alpha" in result.stdout
    assert "beta" in result.stdout


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

    result = runner.invoke(trafalgar_app, ["pipeline", "delete", "custom"])

    assert result.exit_code == 0
    orchestrator.deregister.assert_called_once_with("custom")
    assert "Pipeline 'custom' deregistered" in result.stdout


def test_pipeline_stats_command_displays_results(
    mocker: pytest_mock.MockerFixture,
) -> None:
    stats = {
        "render": {
            "failed": {"count": 1},
            "queued": {"count": 2, "backlog_count": 2},
            "succeeded": {
                "count": 3,
                "durations": {
                    "average_seconds": 30.0,
                    "min_seconds": 20.0,
                    "max_seconds": 45.0,
                },
                "queue_waits": {
                    "average_seconds": 6.0,
                    "min_seconds": 2.0,
                    "max_seconds": 8.0,
                },
            },
        }
    }
    orchestrator = SimpleNamespace(aggregate_runs=Mock(return_value=stats))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(
        trafalgar_app,
        [
            "pipeline",
            "stats",
            "--include-durations",
            "--pipeline",
            "render",
            "--since",
            "2024-01-01T00:00:00+00:00",
        ],
    )

    assert result.exit_code == 0, result.stdout
    orchestrator.aggregate_runs.assert_called_once()
    kwargs = orchestrator.aggregate_runs.call_args.kwargs
    assert kwargs["include_durations"] is True
    assert kwargs["since"] == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert kwargs["pipeline"] == "render"
    assert "Pipeline: render" in result.stdout
    assert "queued: 2 runs [backlog: 2]" in result.stdout
    assert (
        "succeeded: 3 runs (avg 30.00s, min 20.00s, max 45.00s; "
        "queue wait avg 6.00s, min 2.00s, max 8.00s)" in result.stdout
    )


def test_pipeline_stats_command_handles_empty(
    mocker: pytest_mock.MockerFixture,
) -> None:
    orchestrator = SimpleNamespace(aggregate_runs=Mock(return_value={}))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(trafalgar_app, ["pipeline", "stats"])

    assert result.exit_code == 0
    assert orchestrator.aggregate_runs.called
    assert "No pipeline run statistics available." in result.stdout


def test_pipeline_workers_command_displays_metrics(
    mocker: pytest_mock.MockerFixture,
) -> None:
    metrics = SimpleNamespace(max_workers=5, active_workers=2)
    orchestrator = SimpleNamespace(worker_pool_metrics=Mock(return_value=metrics))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(trafalgar_app, ["pipeline", "workers"])

    assert result.exit_code == 0
    orchestrator.worker_pool_metrics.assert_called_once()
    assert "Active workers: 2 (limit: 5)." in result.stdout


def test_pipeline_workers_command_supports_json(
    mocker: pytest_mock.MockerFixture,
) -> None:
    metrics = SimpleNamespace(max_workers=None, active_workers=1)
    orchestrator = SimpleNamespace(worker_pool_metrics=Mock(return_value=metrics))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(
        trafalgar_app,
        ["pipeline", "workers", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"max_workers": None, "active_workers": 1}


def test_pipeline_workers_command_validates_format(
    mocker: pytest_mock.MockerFixture,
) -> None:
    metrics = SimpleNamespace(max_workers=3, active_workers=1)
    orchestrator = SimpleNamespace(worker_pool_metrics=Mock(return_value=metrics))

    mocker.patch("apps.trafalgar.app.load_profile")
    mocker.patch("apps.trafalgar.app.configure_orchestrator_from_profile")
    mocker.patch(
        "apps.trafalgar.app.get_pipeline_orchestrator",
        return_value=orchestrator,
    )

    result = runner.invoke(
        trafalgar_app,
        ["pipeline", "workers", "--format", "yaml"],
    )

    assert result.exit_code != 0
    orchestrator.worker_pool_metrics.assert_not_called()
    terms = ["trafalgar", "pipeline", "workers"]
    for term in terms:
        assert term in result.stderr
