import json

import pytest
from typer.testing import CliRunner

from apps.onepiece import healthcheck
from apps.onepiece.app import app


class _StubCredentials:
    access_key = "AKIA1234"
    token = "session-token"

    def get_frozen_credentials(self) -> "_StubCredentials":
        return self


class _StubSession:
    def __init__(self, profile_name: str | None = None) -> None:
        self.profile_name = profile_name

    def get_credentials(self) -> _StubCredentials:
        return _StubCredentials()


runner = CliRunner()


def test_healthcheck_succeeds_with_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_URL", "https://shotgrid.example")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_SCRIPT", "luffy")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "verysecret")
    monkeypatch.setattr(healthcheck, "Session", _StubSession)

    result = runner.invoke(
        app,
        ["healthcheck", "run", "--format", "json", "--aws-profile", "demo"],
    )

    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert any(probe["name"] == "aws" for probe in payload["probes"])


def test_healthcheck_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        healthcheck,
        "probe_shotgrid",
        lambda: healthcheck.HealthProbeResult(
            name="shotgrid", ok=False, summary="Missing ShotGrid configuration"
        ),
    )
    monkeypatch.setattr(healthcheck, "Session", _StubSession)

    result = runner.invoke(app, ["healthcheck", "run"])

    assert result.exit_code == 1
    assert "Missing ShotGrid configuration" in result.stdout
