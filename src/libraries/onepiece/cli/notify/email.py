"""CLI command for sending email notifications."""

from __future__ import annotations

import structlog
import typer

from libraries.automation.notify.utils import get_notifier

log = structlog.get_logger(__name__)


def _parse_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [recipient.strip() for recipient in raw.split(",") if recipient.strip()]


def send_email_notification(
    *,
    subject: str = typer.Option(..., "--subject", help="Email subject."),
    message: str = typer.Option(..., "--message", help="Email message body."),
    recipients: str | None = typer.Option(
        None,
        "--recipients",
        help="Comma separated list of recipients.",
    ),
    mock: bool = typer.Option(
        False,
        "--mock/--no-mock",
        help="Log the notification instead of sending via SMTP.",
    ),
) -> None:
    """Send an email notification using the configured backend."""

    parsed_recipients = _parse_recipients(recipients)
    notifier_type = "mock:email" if mock else "email"

    log.info(
        "notify.email.start",
        subject=subject,
        recipients=parsed_recipients,
        mock=mock,
    )

    notifier = get_notifier(notifier_type)
    success = notifier.send(
        subject=subject, message=message, recipients=parsed_recipients
    )

    if success:
        log.info(
            "notify.email.success",
            subject=subject,
            recipients=parsed_recipients,
            mock=mock,
        )
        typer.secho("Email notification sent successfully.", fg=typer.colors.GREEN)
        return

    log.error(
        "notify.email.failure",
        subject=subject,
        recipients=parsed_recipients,
        mock=mock,
    )
    typer.secho("Failed to send email notification.", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)
