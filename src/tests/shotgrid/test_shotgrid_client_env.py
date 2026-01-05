import pytest

import libraries.integrations.shotgrid.api as shotgrid_api
from libraries.integrations.shotgrid.api import ShotGridClient


def test_from_env_prefers_onepiece_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_URL", "https://onepiece.example.com")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_SCRIPT", "onepiece-script")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "onepiece-key")

    called: list[tuple[str, str]] = []

    def _capture_authenticate(self: ShotGridClient, script: str, key: str) -> None:
        called.append((script, key))

    monkeypatch.setattr(ShotGridClient, "_authenticate", _capture_authenticate)

    client = ShotGridClient.from_env()

    assert client.base_url == "https://onepiece.example.com"
    assert called == [("onepiece-script", "onepiece-key")]


def test_from_env_falls_back_to_legacy_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOTGRID_URL", "https://legacy.example.com")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "legacy-script")
    monkeypatch.setenv("SHOTGRID_API_KEY", "legacy-key")
    monkeypatch.delenv("ONEPIECE_SHOTGRID_URL", raising=False)
    monkeypatch.delenv("ONEPIECE_SHOTGRID_SCRIPT", raising=False)
    monkeypatch.delenv("ONEPIECE_SHOTGRID_SCRIPT_NAME", raising=False)
    monkeypatch.delenv("ONEPIECE_SHOTGRID_KEY", raising=False)
    monkeypatch.delenv("ONEPIECE_SHOTGRID_API_KEY", raising=False)

    called: list[tuple[str, str]] = []
    logged: list[dict[str, object]] = []

    def _capture_authenticate(self: ShotGridClient, script: str, key: str) -> None:
        called.append((script, key))

    def _capture_warning(event: str, **kwargs: object) -> None:
        logged.append({"event": event, **kwargs})

    monkeypatch.setattr(ShotGridClient, "_authenticate", _capture_authenticate)
    monkeypatch.setattr(shotgrid_api.log, "warning", _capture_warning)

    client = ShotGridClient.from_env()

    assert client.base_url == "https://legacy.example.com"
    assert called == [("legacy-script", "legacy-key")]
    assert any(log.get("event_code") == "shotgrid.env.legacy" for log in logged)
