"""Notification CLI commands."""

import typer

from .email import send_email_notification
from .slack import send_slack_notification

app = typer.Typer(name="notify", help="Send notifications to various backends.")

app.command("email")(send_email_notification)
app.command("slack")(send_slack_notification)

__all__ = ["app"]
