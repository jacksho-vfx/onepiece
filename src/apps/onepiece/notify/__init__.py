"""Notification CLI commands."""

from typing import Any, Mapping

import structlog
import typer

import apps.onepiece.notify.email as _email_module
import apps.onepiece.notify.slack as _slack_module

log = structlog.get_logger(__name__)

app = typer.Typer(name="notify", help="Send notifications to various backends.")

app.command("email")(_email_module.send_email_notification)
app.command("slack")(_slack_module.send_slack_notification)

email = _email_module
slack = _slack_module


def webhook(
    *, url: str, payload: str | Mapping[str, Any], profile: str | None = None, **_: Any
) -> dict[str, Any]:
    """Emit webhook metadata for observability-friendly automation hooks."""

    log.info("notify.webhook", url=url, profile=profile)
    return {"url": url, "payload": payload, "profile": profile}


__all__ = ["app", "webhook", "email", "slack"]
