"""Helpers for configuring Trafalgar service transports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from apps.trafalgar.web.security import (
    CREDENTIALS_ENV,
    CREDENTIALS_FILE_ENV,
    ROLE_PIPELINE_READ,
    ROLE_PIPELINE_RUN,
    get_security_settings,
)

PIPELINE_API_URL_ENV = "TRAFALGAR_PIPELINE_API_URL"
LEGACY_PIPELINE_API_URL_ENV = "UTA_PIPELINE_API_URL"
PIPELINE_API_TIMEOUT_ENV = "TRAFALGAR_PIPELINE_API_TIMEOUT"
LEGACY_PIPELINE_API_TIMEOUT_ENV = "UTA_PIPELINE_API_TIMEOUT"
DEFAULT_PIPELINE_API_URL = "http://127.0.0.1:8000/pipeline"
DEFAULT_PIPELINE_API_TIMEOUT = 10.0

API_KEY_ENV = "TRAFALGAR_API_KEY"
API_SECRET_ENV = "TRAFALGAR_API_SECRET"
DASHBOARD_TOKEN_ENV = "TRAFALGAR_DASHBOARD_TOKEN"
CREDENTIAL_ID_ENV = "TRAFALGAR_CREDENTIAL_ID"


def resolve_pipeline_api_url() -> str:
    """Return the pipeline API base URL derived from environment overrides."""

    for variable in (PIPELINE_API_URL_ENV, LEGACY_PIPELINE_API_URL_ENV):
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    return DEFAULT_PIPELINE_API_URL


def resolve_pipeline_api_timeout() -> float:
    """Return the configured pipeline API timeout, falling back to defaults."""

    for variable in (PIPELINE_API_TIMEOUT_ENV, LEGACY_PIPELINE_API_TIMEOUT_ENV):
        raw = os.environ.get(variable, "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return DEFAULT_PIPELINE_API_TIMEOUT


def resolve_pipeline_auth_headers() -> dict[str, str]:
    """Build authentication headers for Trafalgar pipeline requests."""

    headers: dict[str, str] = {}

    token = os.environ.get(DASHBOARD_TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    settings = get_security_settings()
    key_header = settings.api_key_header
    secret_header = settings.api_secret_header

    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        headers[key_header] = key
        secret = os.environ.get(API_SECRET_ENV, "").strip()
        if secret:
            headers[secret_header] = secret

    credential = _select_service_credential()
    if credential:
        if "Authorization" not in headers:
            bearer = _coerce_text(
                credential.get("token") or credential.get("bearer_token")
            )
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"

        if key_header not in headers:
            entry_key = _coerce_text(credential.get("api_key") or credential.get("key"))
            if entry_key:
                headers[key_header] = entry_key
                entry_secret = _coerce_text(
                    credential.get("api_secret") or credential.get("secret")
                )
                if entry_secret:
                    headers[secret_header] = entry_secret

    return headers


def _select_service_credential() -> Mapping[str, Any] | None:
    entries = list(_iter_credential_entries())
    if not entries:
        return None

    preferred = os.environ.get(CREDENTIAL_ID_ENV, "").strip()
    if preferred:
        for entry in entries:
            identifier = _coerce_text(entry.get("id") or entry.get("identifier"))
            if identifier and identifier == preferred:
                return entry

    best_entry: Mapping[str, Any] | None = None
    best_score = -1
    for entry in entries:
        score = _credential_score(entry)
        if score > best_score:
            best_entry = entry
            best_score = score
    return best_entry


def _iter_credential_entries() -> Iterator[Mapping[str, Any]]:
    inline = os.environ.get(CREDENTIALS_ENV, "").strip()
    if inline:
        try:
            payload = json.loads(inline)
        except json.JSONDecodeError:
            payload = None
        else:
            yield from _normalise_credential_payload(payload)

    path = os.environ.get(CREDENTIALS_FILE_ENV, "").strip()
    if path:
        try:
            with Path(path).expanduser().open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            payload = None
        if payload is not None:
            yield from _normalise_credential_payload(payload)


def _normalise_credential_payload(payload: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if isinstance(value, Mapping):
                entry = dict(value)
                entry.setdefault("id", key)
                yield entry
        return
    if isinstance(payload, Iterable):
        for item in payload:
            if isinstance(item, Mapping):
                yield dict(item)


def _credential_score(entry: Mapping[str, Any]) -> int:
    score = 0
    roles = _coerce_roles(entry.get("roles"))
    if ROLE_PIPELINE_RUN in roles:
        score = 3
    elif ROLE_PIPELINE_READ in roles:
        score = 2
    elif roles:
        score = 1

    token = _coerce_text(entry.get("token") or entry.get("bearer_token"))
    key = _coerce_text(entry.get("api_key") or entry.get("key"))
    if token:
        score += 1
    elif key:
        score += 1
    return score


def _coerce_roles(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item for item in (part.strip() for part in value.split()) if item}
    roles: set[str] = set()
    if isinstance(value, Iterable):
        for item in value:
            text = _coerce_text(item)
            if text:
                roles.add(text)
    else:
        text = _coerce_text(value)
        if text:
            roles.add(text)
    return roles


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


__all__ = [
    "API_KEY_ENV",
    "API_SECRET_ENV",
    "CREDENTIAL_ID_ENV",
    "DASHBOARD_TOKEN_ENV",
    "DEFAULT_PIPELINE_API_TIMEOUT",
    "DEFAULT_PIPELINE_API_URL",
    "LEGACY_PIPELINE_API_TIMEOUT_ENV",
    "LEGACY_PIPELINE_API_URL_ENV",
    "PIPELINE_API_TIMEOUT_ENV",
    "PIPELINE_API_URL_ENV",
    "resolve_pipeline_api_timeout",
    "resolve_pipeline_api_url",
    "resolve_pipeline_auth_headers",
]
