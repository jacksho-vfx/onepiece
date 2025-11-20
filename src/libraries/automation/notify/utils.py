"""Utility helpers for notification backends."""

from dataclasses import dataclass
from typing import Sequence

import structlog

from .base import Notifier
from .email import EmailNotifier
from .slack import SlackNotifier

log = structlog.get_logger(__name__)


def _redact_notification_fields(
    *,
    subject: str,
    message: str,
    recipients: Sequence[str],
    redact: bool = True,
    placeholder: str = "***",
) -> dict[str, object]:
    """Return structured log fields with optional redaction applied."""

    if not redact:
        return {
            "subject": subject,
            "message": message,
            "recipients": list(recipients),
        }

    redacted_recipients = [placeholder for _ in recipients]
    redacted_message = placeholder if message else ""

    return {
        "subject": subject,
        "message": redacted_message,
        "recipients": redacted_recipients,
    }


class MockNotifier(Notifier):
    """Mock notifier used for dry-run mode."""

    def __init__(self, channel: str = "mock", *, redact: bool = True) -> None:
        self.channel = channel
        self.redact = redact

    def send(self, subject: str, message: str, recipients: Sequence[str]) -> bool:
        log_fields = _redact_notification_fields(
            subject=subject,
            message=message,
            recipients=recipients,
            redact=self.redact,
        )

        log.info("notify.mock.sent", channel=self.channel, **log_fields)
        return True


@dataclass(slots=True)
class NotifierOptions:
    """Configuration options for notifier construction."""

    webhook_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int | str | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    mock_channel: str | None = None


def _normalize_port(port: int | str | None) -> int | None:
    if port is None:
        return None

    try:
        normalized = int(port)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError("SMTP port must be an integer.") from exc

    if normalized <= 0:
        raise ValueError("SMTP port must be greater than zero.")

    return normalized


def get_notifier(kind: str, *, options: NotifierOptions | None = None) -> Notifier:
    """Return a notifier instance for the requested type.

    Args:
        kind: Desired notifier backend (e.g. ``"slack"`` or ``"email"``).
        options: Optional configuration overrides for the selected backend.

    Raises:
        ValueError: If the requested notifier kind is unknown or if provided
            options fail validation.
    """

    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("Notifier kind cannot be empty.")

    safe_options = options or NotifierOptions()
    normalized = kind.strip().lower()

    if normalized == "slack":
        webhook: str | None = None
        if safe_options.webhook_url is not None:
            webhook = safe_options.webhook_url.strip()
            if not webhook:
                raise ValueError("Slack webhook URL must not be empty when provided.")

        return SlackNotifier(webhook_url=webhook)

    if normalized == "email":
        host: str | None = None
        if safe_options.smtp_host is not None:
            host = safe_options.smtp_host.strip()
            if not host:
                raise ValueError("SMTP host must not be empty when provided.")

        port = _normalize_port(safe_options.smtp_port)
        return EmailNotifier(
            host=host,
            port=port,
            user=safe_options.smtp_user,
            password=safe_options.smtp_password,
        )

    if normalized.startswith("mock"):
        provided_channel = safe_options.mock_channel
        if ":" in normalized:
            provided_channel = normalized.split(":", 1)[1] or provided_channel

        channel = (provided_channel or "mock").strip()
        if not channel:
            raise ValueError("Mock notifier channel must not be empty.")
        return MockNotifier(channel=channel)

    raise ValueError(
        "Unsupported notifier type: "
        f"{kind}. Supported kinds are: slack, email, mock."
    )
