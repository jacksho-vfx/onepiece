"""Tests for notification utilities."""

import pytest

from libraries.automation.notify.email import EmailNotifier
from libraries.automation.notify.slack import SlackNotifier
from libraries.automation.notify.utils import (
    MockNotifier,
    NotifierOptions,
    get_notifier,
)


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
