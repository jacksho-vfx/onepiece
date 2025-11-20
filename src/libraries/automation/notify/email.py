"""SMTP email notification backend."""

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
        security_mode: str | None = None,
        require_tls: bool | None = None,
    ) -> None:
        self.host = host or os.environ.get("ONEPIECE_SMTP_HOST", "")
        port_value = port if port is not None else os.environ.get("ONEPIECE_SMTP_PORT")
        self.port = int(port_value) if port_value else None
        self.user = user or os.environ.get("ONEPIECE_SMTP_USER")
        self.password = password or os.environ.get("ONEPIECE_SMTP_PASS")
        self.timeout = timeout
        security_value = security_mode or os.environ.get(
            "ONEPIECE_SMTP_SECURITY", "starttls"
        )
        self.security_mode = security_value.lower()
        require_tls_value = (
            require_tls
            if require_tls is not None
            else os.environ.get("ONEPIECE_SMTP_REQUIRE_TLS")
        )
        self.require_tls = self._parse_bool(require_tls_value)

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

        client_class: type[smtplib.SMTP]
        if self.security_mode == "ssl":
            client_class = smtplib.SMTP_SSL
        else:
            client_class = smtplib.SMTP

        try:
            with client_class(self.host, self.port, timeout=self.timeout) as client:
                if not self._negotiate_security(client):
                    return False
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
        if self.user and self.password:
            client.login(self.user, self.password)

    def _negotiate_security(self, client: smtplib.SMTP) -> bool:
        if self.security_mode == "plain":
            log.warning("notify.email.insecure_mode", security_mode=self.security_mode)
            if self.require_tls:
                log.error("notify.email.tls_required", security_mode=self.security_mode)
                return False
            return True

        if self.security_mode == "ssl":
            return True

        # Default to STARTTLS when possible
        try:
            client.starttls()
        except (smtplib.SMTPException, OSError) as exc:
            log.error(
                "notify.email.tls_failed",
                security_mode=self.security_mode,
                error=str(exc),
            )
            if self.require_tls:
                log.error("notify.email.tls_required", security_mode=self.security_mode)
                return False
            log.warning(
                "notify.email.insecure_mode",
                security_mode=f"{self.security_mode}-fallback",
            )
        return True

    @staticmethod
    def _parse_bool(value: bool | str | None) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return value.strip().lower() in {"1", "true", "yes", "on"}
