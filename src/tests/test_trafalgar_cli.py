from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from typer.testing import CliRunner

from apps.trafalgar import app as trafalgar_app


runner = CliRunner()


def test_dashboard_command_invokes_uvicorn(mocker) -> None:
    uvicorn_mock = SimpleNamespace(run=Mock())
    mocker.patch("apps.trafalgar.app._load_uvicorn", return_value=uvicorn_mock)

    result = runner.invoke(
        trafalgar_app,
        ["web", "dashboard", "--host", "0.0.0.0", "--port", "9000", "--log-level", "debug"],
    )

    assert result.exit_code == 0
    uvicorn_mock.run.assert_called_once_with(
        "trafalgar.web.dashboard:app",
        host="0.0.0.0",
        port=9000,
        reload=False,
        log_level="debug",
    )
