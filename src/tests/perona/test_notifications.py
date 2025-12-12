import json
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.perona import app as perona_app
from apps.perona.notifications import (
    NotificationDispatchError,
    configured_webhooks,
    dispatch_render_volatility_alert,
)


def test_configured_webhooks_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PERONA_VOLATILITY_SLACK_WEBHOOK_URL", "https://hooks.slack.test"
    )
    monkeypatch.setenv("PERONA_VOLATILITY_WEBHOOK_URL", "https://hooks.generic.test")

    urls = configured_webhooks()

    assert urls == ["https://hooks.slack.test", "https://hooks.generic.test"]


def test_dispatch_render_volatility_alert_posts_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_post(url: str, json: dict[str, Any], timeout: float) -> Any:
        calls.append({"url": url, "payload": json, "timeout": timeout})

        response = SimpleNamespace(status_code=200)
        return response

    monkeypatch.setenv("PERONA_VOLATILITY_WEBHOOK_URL", "https://hooks.example.test")
    monkeypatch.setattr("apps.perona.notifications.requests.post", _fake_post)
    monkeypatch.setenv("PERONA_WEBHOOK_TIMEOUT", "4.5")

    dispatched = dispatch_render_volatility_alert(
        "2 hotspots detected",
        [
            {
                "sequence": "SEQ",
                "shot": "SH01",
                "risk_score": 87.5,
                "variance": {"coefficient_of_variation": 0.3123},
            }
        ],
    )

    assert dispatched is True
    assert calls == [
        {
            "url": "https://hooks.example.test",
            "payload": {
                "text": "2 hotspots detected\n- SEQ SH01 — risk 87.5, coeff 0.3123",
                "headline": "2 hotspots detected",
                "volatility": [
                    {
                        "sequence": "SEQ",
                        "shot": "SH01",
                        "risk_score": 87.5,
                        "variance": {"coefficient_of_variation": 0.3123},
                    }
                ],
            },
            "timeout": 4.5,
        }
    ]


def test_dispatch_render_volatility_alert_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_post(url: str, json: dict[str, Any], timeout: float) -> Any:  # noqa: A002
        return SimpleNamespace(status_code=500)

    monkeypatch.setenv("PERONA_VOLATILITY_WEBHOOK_URL", "https://hooks.example.test")
    monkeypatch.setattr("apps.perona.notifications.requests.post", _fake_post)

    with pytest.raises(NotificationDispatchError):
        dispatch_render_volatility_alert("headline", [])


def test_cli_volatility_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()

    def _fake_from_settings(path: Any) -> Any:
        return SimpleNamespace(engine=SimpleNamespace(), settings_path=None)

    def _fake_report(engine: Any) -> tuple[str, list[dict[str, Any]]]:
        return (
            "Frame times steady",
            [
                {
                    "sequence": "SQ1",
                    "shot": "A001",
                    "risk_score": 75.0,
                    "variance": {
                        "average_frame_time_ms": 12.3,
                        "coefficient_of_variation": 0.15,
                    },
                }
            ],
        )

    monkeypatch.setattr(perona_app.PeronaEngine, "from_settings", _fake_from_settings)
    monkeypatch.setattr(perona_app, "_build_render_volatility_report", _fake_report)
    monkeypatch.setattr(
        perona_app, "dispatch_render_volatility_alert", lambda *_, **__: True
    )

    result = runner.invoke(
        perona_app.app,
        ["risk", "volatility", "--format", "json", "--notify"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["headline"] == "Frame times steady"
    assert payload["notification_dispatched"] is True
