"""Unit tests for the Slack notifier implementation."""

from __future__ import annotations

import pytest

from libraries.automation.notify.slack import SlackNotifier


class DummyResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:  # pragma: no cover - behavior is trivial
        if self.status_code >= 400:
            raise RuntimeError("request failed")


def test_slack_notifier_escapes_reserved_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slack payloads must escape reserved characters while keeping formatting."""

    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, str], timeout: float) -> DummyResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("libraries.automation.notify.slack.requests.post", fake_post)

    notifier = SlackNotifier(webhook_url="https://hooks.slack.test/", timeout=5)

    result = notifier.send("<Alert>", "Check & fix", recipients=[])

    assert result is True
    assert captured["url"] == "https://hooks.slack.test/"
    assert captured["timeout"] == 5
    assert captured["json"] == {"text": "*&lt;Alert&gt;*\nCheck &amp; fix"}
