"""Slack notification backend."""

import os
import random
import time
from html import escape
from typing import Sequence

import requests  # type: ignore[import-untyped]
import structlog

from .base import Notifier

log = structlog.get_logger(__name__)


class SlackNotifier(Notifier):
    """Send notifications to Slack via an incoming webhook."""

    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        timeout: float = 10.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
        backoff_jitter: float = 0.5,
    ) -> None:
        webhook_from_env = os.environ.get("ONEPIECE_SLACK_WEBHOOK", "")
        raw_webhook = webhook_url or webhook_from_env
        self.webhook_url = raw_webhook.strip()
        self.timeout = timeout
        self.max_attempts = max(max_attempts, 1)
        self.backoff_base = max(backoff_base, 0.0)
        self.backoff_jitter = max(backoff_jitter, 0.0)

    def send(self, subject: str, message: str, recipients: Sequence[str]) -> bool:
        """Send a message to Slack.

        Recipients are ignored because Slack webhooks deliver to a fixed channel.
        """

        if not self.webhook_url:
            log.error("notify.slack.no_webhook", subject=subject)
            return False

        payload = {"text": self._format_message(subject, message)}

        last_exception: requests.RequestException | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                last_exception = exc
                status_code: int | None = None
                response_body: str | None = None

                if exc.response is not None:  # type: ignore[union-attr]
                    status_code = exc.response.status_code  # type: ignore[assignment]
                    try:
                        response_body = exc.response.text  # type: ignore[assignment]
                    except Exception:  # pragma: no cover - defensive
                        response_body = None

                log.error(
                    "notify.slack.failed",
                    subject=subject,
                    error=str(exc),
                    attempt=attempt,
                    status_code=status_code,
                    response_body=response_body,
                )

                if attempt >= self.max_attempts:
                    break

                delay = self.backoff_base * (2 ** (attempt - 1))
                jitter = random.uniform(0, self.backoff_jitter)
                time.sleep(delay + jitter)
            else:
                log.info("notify.slack.sent", subject=subject, attempt=attempt)
                return True

        if last_exception is not None:
            log.error(
                "notify.slack.aborted",
                subject=subject,
                attempts=self.max_attempts,
                error=str(last_exception),
            )

        return False

    @staticmethod
    def _format_message(subject: str, message: str) -> str:
        escaped_message = escape(message, quote=False)
        if subject:
            escaped_subject = escape(subject, quote=False)
            return f"*{escaped_subject}*\n{escaped_message}"
        return escaped_message
