"""CLI command for sending Slack notifications."""

from __future__ import annotations

import structlog
import typer

from libraries.automation.notify.utils import get_notifier

log = structlog.get_logger(__name__)


def send_slack_notification(
    *,
    subject: str = typer.Option(..., "--subject", help="Slack message subject."),
    message: str = typer.Option(..., "--message", help="Slack message body."),
    mock: bool = typer.Option(
        False,
        "--mock/--no-mock",
        help="Log the notification instead of posting to Slack.",
    ),
) -> None:
    """Send a Slack notification using the configured backend."""

    notifier_type = "mock:slack" if mock else "slack"

    log.info(
        "notify.slack.start",
        subject=subject,
        mock=mock,
    )

    notifier = get_notifier(notifier_type)
    success = notifier.send(subject=subject, message=message, recipients=[])

    if success:
        log.info("notify.slack.success", subject=subject, mock=mock)
        typer.secho("Slack notification sent successfully.", fg=typer.colors.GREEN)
        return

    log.error("notify.slack.failure", subject=subject, mock=mock)
    typer.secho("Failed to send Slack notification.", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)
