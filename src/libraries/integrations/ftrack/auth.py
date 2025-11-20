"""Credential helpers for configuring the Ftrack REST client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FtrackCredentials:
    """Container for credentials used when authenticating with Ftrack."""

    base_url: str
    api_user: str | None = None
    api_key: str | None = None
    bearer_token: str | None = None

    def __post_init__(self) -> None:  # type: ignore[override]
        if not self.base_url:
            raise ValueError("base_url must be provided")
        if not self.bearer_token and not (self.api_user and self.api_key):
            raise ValueError(
                "Either bearer_token or both api_user and api_key must be provided"
            )

    def as_kwargs(self) -> dict[str, Any]:
        """Return a mapping suitable for constructing :class:`FtrackRestClient`."""

        return {
            "base_url": self.base_url,
            "api_user": self.api_user,
            "api_key": self.api_key,
            "bearer_token": self.bearer_token,
        }


def load_credentials(path: str | Path | None = None) -> FtrackCredentials:
    """Load credentials from *path* or the environment."""

    resolved_path = Path(path) if path else None
    if resolved_path is None:
        env_path = os.environ.get("FTRACK_CREDENTIALS_FILE")
        if env_path:
            resolved_path = Path(env_path)

    raw: dict[str, Any] = {}
    if resolved_path:
        content = resolved_path.read_text(encoding="utf-8")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Credential file must contain a JSON object")
        raw.update(payload)

    env_values = {
        "base_url": os.environ.get("FTRACK_URL"),
        "api_user": os.environ.get("FTRACK_API_USER"),
        "api_key": os.environ.get("FTRACK_API_KEY"),
        "bearer_token": os.environ.get("FTRACK_BEARER_TOKEN"),
    }
    raw.update({key: value for key, value in env_values.items() if value})

    return FtrackCredentials(**raw)
