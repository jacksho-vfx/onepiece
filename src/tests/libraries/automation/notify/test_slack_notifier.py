"""Tests for Slack notifier HTTP interactions."""

from __future__ import annotations

import pytest
import requests  # type: ignore[import-untyped]

import libraries.automation.notify.slack as slack_module
from libraries.automation.notify.slack import SlackNotifier


class StubLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append({"event": event, **kwargs})

    def error(self, event: str, **kwargs: object) -> None:
        self.events.append({"event": event, **kwargs})


class StubResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "OK",
        error: requests.RequestException | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._error = error
        if self._error is not None:
            self._error.response = self  # type: ignore[assignment]

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error


@pytest.mark.parametrize(
    "subject,message,expected",
    [
        ("Hello", "Body", "*Hello*\nBody"),
        ("Hi & team", "<payload>", "*Hi &amp; team*\n&lt;payload&gt;"),
    ],
)
def test_slack_notifier_formats_and_sends_messages(
    subject: str, message: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = StubLogger()
    monkeypatch.setattr(slack_module, "log", logger)

    sent: list[dict[str, object]] = []

    def fake_post(url: str, json: dict[str, object], timeout: float) -> StubResponse:
        sent.append({"url": url, "json": json, "timeout": timeout})
        return StubResponse()

    monkeypatch.setattr(slack_module.requests, "post", fake_post)

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.test/example",
        timeout=2.0,
        max_attempts=1,
    )

    assert notifier.send(subject, message, ["ignored"])
    assert sent

    payload = sent[0]
    assert payload["url"] == "https://hooks.slack.test/example"
    assert payload["json"] == {"text": expected}
    assert payload["timeout"] == 2.0

    assert logger.events[-1]["event"] == "notify.slack.sent"
    assert logger.events[-1]["attempt"] == 1


def test_slack_notifier_retries_and_aborts_after_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = StubLogger()
    monkeypatch.setattr(slack_module, "log", logger)

    error = requests.HTTPError("server blew up")
    failing_response = StubResponse(status_code=503, text="boom", error=error)

    attempts: list[dict[str, object]] = []

    def fake_post(url: str, json: dict[str, object], timeout: float) -> StubResponse:
        attempts.append({"url": url, "json": json})
        return failing_response

    monkeypatch.setattr(slack_module.requests, "post", fake_post)
    monkeypatch.setattr(slack_module.time, "sleep", lambda *_args, **_kwargs: None)

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.test/example",
        max_attempts=2,
        backoff_base=0.0,
        backoff_jitter=0.0,
    )

    assert notifier.send("Subject", "Body", []) is False
    assert len(attempts) == 2

    failed_events = [
        entry for entry in logger.events if entry["event"] == "notify.slack.failed"
    ]
    assert len(failed_events) == 2

    aborted_events = [
        entry for entry in logger.events if entry["event"] == "notify.slack.aborted"
    ]
    assert aborted_events and aborted_events[0]["attempts"] == 2


def test_slack_notifier_requires_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = StubLogger()
    monkeypatch.setattr(slack_module, "log", logger)

    notifier = SlackNotifier(webhook_url="")

    assert notifier.send("Subject", "Message", []) is False
    assert logger.events[0]["event"] == "notify.slack.no_webhook"


def test_slack_notifier_uses_environment_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = StubLogger()
    monkeypatch.setattr(slack_module, "log", logger)
    monkeypatch.setenv(
        "ONEPIECE_SLACK_WEBHOOK", "  https://hooks.slack.test/from-env  "
    )

    sent: list[dict[str, object]] = []

    def fake_post(url: str, json: dict[str, object], timeout: float) -> StubResponse:
        sent.append({"url": url, "json": json, "timeout": timeout})
        return StubResponse()

    monkeypatch.setattr(slack_module.requests, "post", fake_post)

    notifier = SlackNotifier(timeout=5.0)

    assert notifier.send("Env", "Body", []) is True
    assert sent[0]["url"] == "https://hooks.slack.test/from-env"
    assert logger.events[-1]["event"] == "notify.slack.sent"
