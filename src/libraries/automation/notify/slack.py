"""Slack notification backend."""

import os
from typing import Sequence

import requests
import structlog

from .base import Notifier

log = structlog.get_logger(__name__)


class SlackNotifier(Notifier):
    """Send notifications to Slack via an incoming webhook."""

    def __init__(
        self, webhook_url: str | None = None, *, timeout: float = 10.0
    ) -> None:
        self.webhook_url = webhook_url or os.environ.get("ONEPIECE_SLACK_WEBHOOK", "")
        self.timeout = timeout

    def send(self, subject: str, message: str, recipients: Sequence[str]) -> bool:
        """Send a message to Slack.

        Recipients are ignored because Slack webhooks deliver to a fixed channel.
        """

        if not self.webhook_url:
            log.error("notify.slack.no_webhook", subject=subject)
            return False

        payload = {"text": self._format_message(subject, message)}

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log.error(
                "notify.slack.failed",
                subject=subject,
                error=str(exc),
            )
            return False

        log.info("notify.slack.sent", subject=subject)
        return True

    @staticmethod
    def _format_message(subject: str, message: str) -> str:
        if subject:
            return f"*{subject}*\n{message}"
        return message
