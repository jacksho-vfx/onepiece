"""Tests for notification CLI commands."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from apps.onepiece.notify import email as email_cli
from apps.onepiece.notify import slack as slack_cli

runner = CliRunner()


class DummyNotifier:
    def __init__(self, *, result: bool, record: dict[str, Any]) -> None:
        self.result = result
        self.record = record

    def send(self, subject: str, message: str, recipients: list[str]) -> bool:
        self.record["subject"] = subject
        self.record["message"] = message
        self.record["recipients"] = recipients
        return self.result


def test_notify_email_success(monkeypatch: pytest.MonkeyPatch) -> None:
    record: dict[str, Any] = {}
    requested: list[str] = []

    def fake_get_notifier(kind: str) -> DummyNotifier:
        requested.append(kind)
        return DummyNotifier(result=True, record=record)

    monkeypatch.setattr(email_cli, "get_notifier", fake_get_notifier)

    result = runner.invoke(
        app,
        [
            "notify",
            "email",
            "--subject",
            "Greetings",
            "--message",
            "Hello crew!",
            "--recipients",
            "luffy@onepiece.test,zoro@onepiece.test",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Email notification sent successfully." in result.stdout
    assert requested == ["email"]
    assert record["subject"] == "Greetings"
    assert record["message"] == "Hello crew!"
    assert record["recipients"] == [
        "luffy@onepiece.test",
        "zoro@onepiece.test",
    ]


def test_notify_email_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    record: dict[str, Any] = {}

    def fake_get_notifier(kind: str) -> DummyNotifier:
        return DummyNotifier(result=False, record=record)

    monkeypatch.setattr(email_cli, "get_notifier", fake_get_notifier)

    result = runner.invoke(
        app,
        [
            "notify",
            "email",
            "--subject",
            "Alert",
            "--message",
            "Something happened",
            "--recipients",
            "nami@onepiece.test",
        ],
    )

    assert result.exit_code == 1
    assert "Failed to send email notification." in result.stderr


def test_notify_email_mock_uses_mock_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def fake_get_notifier(kind: str) -> DummyNotifier:
        requested.append(kind)
        return DummyNotifier(result=True, record={})

    monkeypatch.setattr(email_cli, "get_notifier", fake_get_notifier)

    result = runner.invoke(
        app,
        [
            "notify",
            "email",
            "--subject",
            "Test",
            "--message",
            "Test message",
            "--mock",
        ],
    )

    assert result.exit_code == 0
    assert requested == ["mock:email"]


def test_notify_slack_success(monkeypatch: pytest.MonkeyPatch) -> None:
    record: dict[str, Any] = {}
    requested: list[str] = []

    def fake_get_notifier(kind: str) -> DummyNotifier:
        requested.append(kind)
        return DummyNotifier(result=True, record=record)

    monkeypatch.setattr(slack_cli, "get_notifier", fake_get_notifier)

    result = runner.invoke(
        app,
        [
            "notify",
            "slack",
            "--subject",
            "Update",
            "--message",
            "Deployment finished",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Slack notification sent successfully." in result.stdout
    assert requested == ["slack"]
    assert record["recipients"] == []


def test_notify_slack_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_notifier(kind: str) -> DummyNotifier:
        return DummyNotifier(result=False, record={})

    monkeypatch.setattr(slack_cli, "get_notifier", fake_get_notifier)

    result = runner.invoke(
        app,
        [
            "notify",
            "slack",
            "--subject",
            "Incident",
            "--message",
            "Service unavailable",
            "--mock",
        ],
    )

    assert result.exit_code == 1
    assert "Failed to send Slack notification." in result.stderr
