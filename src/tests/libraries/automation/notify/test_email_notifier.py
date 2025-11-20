"""Unit tests for EmailNotifier SMTP interactions."""

from __future__ import annotations

from contextlib import contextmanager
from email.message import EmailMessage
from types import TracebackType
import smtplib
from typing import Iterator

import pytest

import libraries.automation.notify.email as email_module
from libraries.automation.notify.email import EmailNotifier


class StubLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def _record(self, event: str, **kwargs: object) -> None:
        self.events.append({"event": event, **kwargs})

    def warning(self, event: str, **kwargs: object) -> None:
        self._record(event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._record(event, **kwargs)

    def info(self, event: str, **kwargs: object) -> None:
        self._record(event, **kwargs)


@contextmanager
def capture_email_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[StubLogger]:
    logger = StubLogger()
    monkeypatch.setattr(email_module, "log", logger)
    try:
        yield logger
    finally:
        monkeypatch.undo()


class FakeSMTP:
    """Simple SMTP test double tracking calls and optionally raising errors."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        *,
        starttls_error: Exception | None = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_error = starttls_error
        self.starttls_called = False
        self.login_args: tuple[str, str] | None = None
        self.sent_messages: list[EmailMessage] = []

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def starttls(self) -> None:
        self.starttls_called = True
        if self.starttls_error:
            raise self.starttls_error

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent_messages.append(message)


def test_starttls_mode_uses_smtp_and_attempts_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeSMTP] = []

    def fake_smtp(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(host, port, timeout)
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    notifier = EmailNotifier(
        host="smtp.test",
        port=25,
        user="user",
        password="pass",
        timeout=5.0,
    )

    assert notifier.send("Subject", "Body", ["to@example.com"])
    assert created, "SMTP client should be instantiated"
    smtp = created[0]
    assert smtp.starttls_called is True
    assert smtp.login_args == ("user", "pass")
    assert len(smtp.sent_messages) == 1


def test_ssl_mode_uses_smtp_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    created_ssl: list[FakeSMTP] = []

    def fake_smtp_ssl(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(host, port, timeout)
        created_ssl.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp_ssl)
    monkeypatch.setattr(
        smtplib, "SMTP", lambda *args, **kwargs: pytest.fail("SMTP should not be used")
    )

    notifier = EmailNotifier(
        host="smtp.test",
        port=465,
        security_mode="ssl",
    )

    assert notifier.send("Subject", "Body", ["to@example.com"])
    assert created_ssl, "SMTP_SSL client should be instantiated"
    smtp = created_ssl[0]
    assert smtp.starttls_called is False
    assert len(smtp.sent_messages) == 1


def test_plain_mode_warns_and_can_send_without_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeSMTP] = []

    def fake_smtp(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(host, port, timeout)
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    notifier = EmailNotifier(host="smtp.test", port=25, security_mode="plain")

    with capture_email_logs(monkeypatch) as logs:
        assert notifier.send("Subject", "Body", ["to@example.com"])

    assert any(entry["event"] == "notify.email.insecure_mode" for entry in logs.events)
    assert created and created[0].sent_messages


def test_plain_mode_rejects_when_tls_required(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[FakeSMTP] = []

    def fake_smtp(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(host, port, timeout)
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    notifier = EmailNotifier(
        host="smtp.test", port=25, security_mode="plain", require_tls=True
    )

    assert notifier.send("Subject", "Body", ["to@example.com"]) is False
    assert created and not created[0].sent_messages


def test_starttls_failure_continues_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeSMTP] = []

    def fake_smtp(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(
            host, port, timeout, starttls_error=smtplib.SMTPException("fail")
        )
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    notifier = EmailNotifier(
        host="smtp.test", port=25, security_mode="starttls", require_tls=False
    )

    with capture_email_logs(monkeypatch) as logs:
        assert notifier.send("Subject", "Body", ["to@example.com"])

    smtp = created[0]
    assert smtp.starttls_called is True
    assert smtp.sent_messages, "Message should still be sent when TLS not required"
    assert any(entry["event"] == "notify.email.tls_failed" for entry in logs.events)


def test_starttls_failure_blocks_when_tls_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeSMTP] = []

    def fake_smtp(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(
            host, port, timeout, starttls_error=smtplib.SMTPException("fail")
        )
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    notifier = EmailNotifier(
        host="smtp.test", port=25, security_mode="starttls", require_tls=True
    )

    with capture_email_logs(monkeypatch) as logs:
        assert notifier.send("Subject", "Body", ["to@example.com"]) is False

    smtp = created[0]
    assert smtp.starttls_called is True
    assert not smtp.sent_messages
    assert any(entry["event"] == "notify.email.tls_required" for entry in logs.events)


def test_missing_config_returns_false() -> None:
    notifier = EmailNotifier(host="", port=None)
    assert notifier.send("Subject", "Body", ["to@example.com"]) is False


def test_send_failure_is_logged_and_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeSMTP] = []

    def fake_smtp(host: str, port: int, timeout: float) -> FakeSMTP:
        smtp = FakeSMTP(host, port, timeout)
        created.append(smtp)

        def fail_send(_: EmailMessage) -> None:
            raise smtplib.SMTPException("cannot send")

        smtp.send_message = fail_send  # type: ignore[assignment]
        return smtp

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    notifier = EmailNotifier(host="smtp.test", port=25)

    with capture_email_logs(monkeypatch) as logs:
        assert notifier.send("Subject", "Body", ["to@example.com"]) is False

    assert created and not created[0].sent_messages
    assert any(entry["event"] == "notify.email.failed" for entry in logs.events)
