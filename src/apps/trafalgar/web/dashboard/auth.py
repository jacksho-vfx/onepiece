"""Authentication and formatting helpers for the dashboard endpoints."""

from __future__ import annotations

import hmac
import os
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


STATUS_CANONICAL_PREFIXES: OrderedDict[str, str] = OrderedDict(
    {
        "apr": "approved",
        "approved": "approved",
        "pub": "published",
        "published": "published",
        "final": "published",
    }
)

_DASHBOARD_TOKEN_ENV = "TRAFALGAR_DASHBOARD_TOKEN"
_bearer_scheme = HTTPBearer(auto_error=False)

__all__ = [
    "STATUS_CANONICAL_PREFIXES",
    "require_dashboard_auth",
    "_bearer_scheme",
    "_parse_datetime",
    "_extract_episode",
    "_normalise_version_name",
    "_canonicalise_status",
]


def require_dashboard_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """Validate bearer token credentials for privileged dashboard endpoints."""

    expected_token = os.getenv(_DASHBOARD_TOKEN_ENV)
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Dashboard authentication token is not configured.",
        )

    provided = credentials.credentials if credentials else None
    if not provided or not hmac.compare_digest(provided, expected_token):
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


def _parse_datetime(value: Any) -> Any:
    """Return an ISO 8601 timestamp for *value* if possible."""

    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    return None


def _extract_episode(record: Mapping[str, Any]) -> str | None:
    """Return the episode identifier for *record* if one can be derived."""

    episode = record.get("episode")
    if isinstance(episode, str) and episode.strip():
        return episode.strip()

    shot = record.get("shot")
    if isinstance(shot, str) and shot:
        return shot.split("_")[0]
    return None


def _normalise_version_name(record: Mapping[str, Any]) -> str | None:
    for key in ("version", "code", "version_number"):
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, int):
            return f"v{value:03d}"
        return str(value)
    return None


def _canonicalise_status(value: Any) -> str:
    if not value:
        return "unknown"

    text = str(value).strip().lower()
    if not text:
        return "unknown"

    for prefix, label in STATUS_CANONICAL_PREFIXES.items():
        if text.startswith(prefix):
            return label

    return text
