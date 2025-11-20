"""Unit tests for the Slack notifier implementation."""

from __future__ import annotations

import pytest
import requests

from libraries.automation.notify import slack as slack_module

from libraries.automation.notify.slack import SlackNotifier


class DummyResponse:
    def __init__(
        self, status_code: int = 200, text: str = "", raise_error: bool = False
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.raise_error = raise_error

    def raise_for_status(self) -> None:
        if self.raise_error:
            error = requests.HTTPError("request failed")
            error.response = self
            raise error


class CaptureLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.records.append(("info", event, kwargs))

    def error(self, event: str, **kwargs: object) -> None:
        self.records.append(("error", event, kwargs))


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


def test_slack_notifier_retries_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []
    logger = CaptureLogger()
    responses = [
        DummyResponse(status_code=500, text="server exploded", raise_error=True),
        DummyResponse(status_code=200, text="ok"),
    ]

    def fake_post(url: str, *, json: dict[str, str], timeout: float) -> DummyResponse:
        attempts.append(1)
        return responses[len(attempts) - 1]

    monkeypatch.setattr(slack_module, "log", logger)
    monkeypatch.setattr("libraries.automation.notify.slack.requests.post", fake_post)
    monkeypatch.setattr(
        "libraries.automation.notify.slack.random.uniform", lambda _a, _b: 0.0
    )

    recorded_sleeps: list[float] = []
    monkeypatch.setattr(
        "libraries.automation.notify.slack.time.sleep", recorded_sleeps.append
    )

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.test/",
        max_attempts=3,
        backoff_base=0.1,
        backoff_jitter=0,
    )

    result = notifier.send("Subject", "Body", recipients=[])

    assert result is True
    assert len(attempts) == 2
    assert recorded_sleeps == [0.1]

    error_event = next(
        (event for event in logger.records if event[1] == "notify.slack.failed"), None
    )
    assert error_event is not None
    assert error_event[2]["attempt"] == 1
    assert error_event[2]["status_code"] == 500
    assert error_event[2]["response_body"] == "server exploded"

    success_event = next(
        (event for event in logger.records if event[1] == "notify.slack.sent"), None
    )
    assert success_event is not None
    assert success_event[2]["attempt"] == 2


def test_slack_notifier_timeout_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = CaptureLogger()

    def fake_post(url: str, *, json: dict[str, str], timeout: float) -> DummyResponse:
        raise requests.Timeout("connection timed out")

    monkeypatch.setattr(slack_module, "log", logger)
    monkeypatch.setattr("libraries.automation.notify.slack.requests.post", fake_post)
    monkeypatch.setattr(
        "libraries.automation.notify.slack.random.uniform", lambda _a, _b: 0.0
    )
    monkeypatch.setattr(
        "libraries.automation.notify.slack.time.sleep", lambda _delay: None
    )

    notifier = SlackNotifier(webhook_url="https://hooks.slack.test/", max_attempts=2)

    result = notifier.send("Timeout", "Body", recipients=[])

    assert result is False

    failed_events = [
        event for event in logger.records if event[1] == "notify.slack.failed"
    ]
    assert len(failed_events) == 2
    assert failed_events[0][2]["attempt"] == 1
    assert failed_events[1][2]["attempt"] == 2

    aborted_event = next(
        (event for event in logger.records if event[1] == "notify.slack.aborted"), None
    )
    assert aborted_event is not None
    assert aborted_event[2]["attempts"] == 2
