"""Notification helpers for Perona automation flows."""

from __future__ import annotations

import os
from typing import Iterable, Mapping, Sequence

import requests  # type: ignore[import-untyped]

DEFAULT_WEBHOOK_TIMEOUT = 5.0
WEBHOOK_TIMEOUT_ENV = "PERONA_WEBHOOK_TIMEOUT"
SLACK_WEBHOOK_ENV = "PERONA_VOLATILITY_SLACK_WEBHOOK_URL"
GENERIC_WEBHOOK_ENV = "PERONA_VOLATILITY_WEBHOOK_URL"


class NotificationDispatchError(RuntimeError):
    """Raised when a webhook notification cannot be delivered."""


def _resolve_timeout() -> float:
    raw_timeout = os.getenv(WEBHOOK_TIMEOUT_ENV)
    if raw_timeout is None:
        return DEFAULT_WEBHOOK_TIMEOUT

    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        return DEFAULT_WEBHOOK_TIMEOUT

    return timeout if timeout > 0 else DEFAULT_WEBHOOK_TIMEOUT


def configured_webhooks() -> list[str]:
    """Return the configured webhook URLs, if any."""

    urls: list[str] = []
    for env_var in (SLACK_WEBHOOK_ENV, GENERIC_WEBHOOK_ENV):
        candidate = os.getenv(env_var)
        if candidate:
            urls.append(candidate)
    return urls


def _format_volatility_message(
    headline: str, hotspots: Sequence[Mapping[str, object]]
) -> str:
    lines = [headline]
    for hotspot in hotspots[:3]:
        sequence = hotspot.get("sequence")
        shot = hotspot.get("shot")
        risk_score = hotspot.get("risk_score")
        variance = hotspot.get("variance")
        coefficient = None
        if isinstance(variance, Mapping):
            coefficient = variance.get("coefficient_of_variation")

        if sequence and shot and risk_score is not None:
            detail = f"{sequence} {shot} — risk {risk_score}"
        else:  # pragma: no cover - defensive rendering guard
            detail = "Hotspot"

        if coefficient is not None:
            detail += f", coeff {coefficient}"

        lines.append(f"- {detail}")

    if len(hotspots) > 3:
        lines.append(f"(+{len(hotspots) - 3} more hotspots)")

    return "\n".join(lines)


def _dispatch_webhook(url: str, payload: Mapping[str, object]) -> None:
    response = requests.post(url, json=payload, timeout=_resolve_timeout())
    if response.status_code >= 400:
        raise NotificationDispatchError(
            f"Webhook {url} returned HTTP {response.status_code}"
        )


def dispatch_render_volatility_alert(
    headline: str,
    hotspots: Sequence[Mapping[str, object]] | Iterable[Mapping[str, object]],
    *,
    webhooks: Sequence[str] | None = None,
) -> bool:
    """Send a volatility alert to all configured webhook destinations."""

    urls = list(webhooks) if webhooks is not None else configured_webhooks()
    if not urls:
        return False

    hotspots_list = list(hotspots)
    message = _format_volatility_message(headline, hotspots_list)
    payload = {"text": message, "headline": headline, "volatility": hotspots_list}

    for url in urls:
        _dispatch_webhook(url, payload)

    return True


__all__ = [
    "DEFAULT_WEBHOOK_TIMEOUT",
    "GENERIC_WEBHOOK_ENV",
    "SLACK_WEBHOOK_ENV",
    "WEBHOOK_TIMEOUT_ENV",
    "NotificationDispatchError",
    "configured_webhooks",
    "dispatch_render_volatility_alert",
]
