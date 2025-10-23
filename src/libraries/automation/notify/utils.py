"""Utility helpers for notification backends."""

from typing import Sequence

import structlog

from .base import Notifier
from .email import EmailNotifier
from .slack import SlackNotifier

log = structlog.get_logger(__name__)


class MockNotifier(Notifier):
    """Mock notifier used for dry-run mode."""

    def __init__(self, channel: str = "mock") -> None:
        self.channel = channel

    def send(self, subject: str, message: str, recipients: Sequence[str]) -> bool:
        log.info(
            "notify.mock.sent",
            channel=self.channel,
            subject=subject,
            message=message,
            recipients=list(recipients),
        )
        return True


def get_notifier(kind: str) -> Notifier:
    """Return a notifier instance for the requested type."""

    normalized = kind.lower()
    if normalized == "slack":
        return SlackNotifier()
    if normalized == "email":
        return EmailNotifier()
    if normalized.startswith("mock"):
        channel = normalized.split(":", 1)[1] if ":" in normalized else "mock"
        return MockNotifier(channel=channel)

    raise ValueError(f"Unsupported notifier type: {kind}")
