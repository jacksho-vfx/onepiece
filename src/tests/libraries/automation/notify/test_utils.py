"""Tests for notification utilities."""

from __future__ import annotations

import pytest

import libraries.automation.notify.utils as utils_module
from libraries.automation.notify.email import EmailNotifier
from libraries.automation.notify.slack import SlackNotifier
from libraries.automation.notify.utils import (
    MockNotifier,
    NotifierOptions,
    get_notifier,
)


class StubLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append({"event": event, **kwargs})


def test_slack_notifier_accepts_injected_settings() -> None:
    options = NotifierOptions(webhook_url=" https://hooks.slack.test/example ")

    notifier = get_notifier("  SLACK  ", options=options)

    assert isinstance(notifier, SlackNotifier)
    assert notifier.webhook_url == "https://hooks.slack.test/example"


def test_email_notifier_validates_and_normalizes_inputs() -> None:
    options = NotifierOptions(
        smtp_host=" smtp.onepiece.test ",
        smtp_port="2525",
        smtp_user="nami",
        smtp_password="safepass",
    )

    notifier = get_notifier("Email", options=options)

    assert isinstance(notifier, EmailNotifier)
    assert notifier.host == "smtp.onepiece.test"
    assert notifier.port == 2525
    assert notifier.user == "nami"
    assert notifier.password == "safepass"


def test_mock_notifier_prefers_kind_channel_override() -> None:
    options = NotifierOptions(mock_channel="fallback")

    notifier = get_notifier("mock:cli", options=options)

    assert isinstance(notifier, MockNotifier)
    assert notifier.channel == "cli"


@pytest.mark.parametrize(
    "kind, options, expected_message",
    [
        ("", None, "Notifier kind cannot be empty."),
        (
            "sms",
            None,
            "Unsupported notifier type: sms. Supported kinds are: slack, email, mock.",
        ),
        (
            "slack",
            NotifierOptions(webhook_url=""),
            "Slack webhook URL must not be empty when provided.",
        ),
        (
            "email",
            NotifierOptions(smtp_host="", smtp_port=0),
            "SMTP host must not be empty when provided.",
        ),
    ],
)
def test_get_notifier_provides_descriptive_errors(
    kind: str, options: NotifierOptions | None, expected_message: str
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        get_notifier(kind, options=options)


def test_mock_notifier_redacts_payload_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = StubLogger()
    monkeypatch.setattr(utils_module, "log", logger)

    notifier = MockNotifier()
    notifier.send("Alert", "Sensitive message", ["a@example.com", "b@example.com"])

    assert logger.events, "A log entry should have been recorded"
    entry = logger.events[0]

    assert entry["event"] == "notify.mock.sent"
    assert entry["channel"] == "mock"
    assert entry["subject"] == "Alert"
    assert entry["message"] == "***"
    assert entry["recipients"] == ["***", "***"]


def test_mock_notifier_can_disable_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = StubLogger()
    monkeypatch.setattr(utils_module, "log", logger)

    notifier = MockNotifier(channel="cli", redact=False)
    notifier.send("Alert", "Plaintext", ("a@example.com",))

    entry = logger.events[0]

    assert entry["channel"] == "cli"
    assert entry["message"] == "Plaintext"
    assert entry["recipients"] == ["a@example.com"]
