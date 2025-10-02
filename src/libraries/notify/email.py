"""SMTP email notification backend."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Sequence

import structlog

from .base import Notifier

log = structlog.get_logger(__name__)


class EmailNotifier(Notifier):
    """Send plain-text notifications via SMTP."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.host = host or os.environ.get("ONEPIECE_SMTP_HOST", "")
        port_value = port if port is not None else os.environ.get("ONEPIECE_SMTP_PORT")
        self.port = int(port_value) if port_value else None
        self.user = user or os.environ.get("ONEPIECE_SMTP_USER")
        self.password = password or os.environ.get("ONEPIECE_SMTP_PASS")
        self.timeout = timeout

    def send(self, subject: str, message: str, recipients: Sequence[str]) -> bool:
        if not self.host or not self.port:
            log.error(
                "notify.email.missing_config",
                host=bool(self.host),
                port=bool(self.port),
            )
            return False

        if not recipients:
            log.error("notify.email.no_recipients", subject=subject)
            return False

        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = self.user or "no-reply@onepiece"
        email["To"] = ", ".join(recipients)
        email.set_content(message)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as client:
                self._login(client)
                client.send_message(email)
        except (smtplib.SMTPException, OSError) as exc:
            log.error(
                "notify.email.failed",
                subject=subject,
                error=str(exc),
            )
            return False

        log.info(
            "notify.email.sent",
            subject=subject,
            recipients=list(recipients),
        )
        return True

    def _login(self, client: smtplib.SMTP) -> None:
        try:
            client.starttls()
        except (smtplib.SMTPException, OSError):
            # If STARTTLS is not supported we proceed without upgrading the connection.
            log.debug("notify.email.starttls_unavailable", host=self.host, port=self.port)

        if self.user and self.password:
            client.login(self.user, self.password)
