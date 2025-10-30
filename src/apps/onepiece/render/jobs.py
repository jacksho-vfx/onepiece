"""HTTP client for querying Trafalgar render jobs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from apps.onepiece.config import load_profile
from apps.trafalgar.transport import resolve_pipeline_auth_headers

RENDER_API_URL_ENV = "TRAFALGAR_RENDER_API_URL"
RENDER_API_TIMEOUT_ENV = "TRAFALGAR_RENDER_API_TIMEOUT"
DEFAULT_RENDER_API_URL = "http://127.0.0.1:8000/render"
DEFAULT_RENDER_API_TIMEOUT = 10.0


@dataclass(slots=True)
class RenderJobClientError(RuntimeError):
    """Raised when Trafalgar render job lookups fail."""

    message: str
    status_code: int | None = None

    def __str__(self) -> str:  # pragma: no cover - dataclass hook
        return self.message


class RenderJobClient:
    """Small helper around :mod:`httpx` for render job lookups."""

    def __init__(
        self,
        *,
        profile: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if client is None:
            resolved_base = base_url or resolve_render_base_url(profile=profile)
            resolved_timeout = timeout or resolve_render_api_timeout()
            headers = resolve_pipeline_auth_headers()
            self._client = httpx.Client(
                base_url=resolved_base,
                timeout=resolved_timeout,
                headers=headers,
            )
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RenderJobClient":
        return self

    def __exit__(
        self,
        exc_type: object | None,
        exc: object | None,
        traceback: object | None,
    ) -> None:
        self.close()

    def get_job(self, job_id: str, *, farm: str | None = None) -> Mapping[str, Any]:
        params: dict[str, Any] | None = None
        if farm:
            params = {"farm": farm}
        try:
            response = self._client.get(f"jobs/{job_id}", params=params)
        except httpx.RequestError as exc:  # pragma: no cover - network failures are rare in tests
            raise RenderJobClientError(
                "Unable to reach Trafalgar render API."
            ) from exc

        if response.status_code == 404:
            detail = _extract_response_detail(response)
            raise RenderJobClientError(detail or "Render job not found.", status_code=404)

        if not response.is_success:
            detail = _extract_response_detail(response)
            raise RenderJobClientError(detail, status_code=response.status_code)

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RenderJobClientError(
                "Render API returned a malformed response."
            ) from exc

        if not isinstance(payload, Mapping):
            raise RenderJobClientError("Render API returned an unexpected payload.")
        return dict(payload)


def resolve_render_base_url(*, profile: str | None = None) -> str:
    """Determine the Trafalgar render API base URL."""

    env_override = _coerce_text(os.environ.get(RENDER_API_URL_ENV))
    if env_override:
        return _normalise_base_url(env_override)

    profile_data: Mapping[str, Any] | None = None
    context = load_profile(profile=profile)
    profile_data = context.data

    if profile_data:
        candidates = _iter_profile_url_candidates(profile_data)
        for candidate in candidates:
            url = _coerce_text(candidate)
            if url:
                return _normalise_base_url(url)

    return _normalise_base_url(DEFAULT_RENDER_API_URL)


def resolve_render_api_timeout() -> float:
    """Read the render API timeout from the environment."""

    raw = _coerce_text(os.environ.get(RENDER_API_TIMEOUT_ENV))
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = DEFAULT_RENDER_API_TIMEOUT
        else:
            if value <= 0:
                value = DEFAULT_RENDER_API_TIMEOUT
        return value
    return DEFAULT_RENDER_API_TIMEOUT


def _iter_profile_url_candidates(data: Mapping[str, Any]) -> list[Any]:
    render_block = data.get("render")
    candidates: list[Any] = []
    if isinstance(render_block, Mapping):
        trafalgar_block = render_block.get("trafalgar")
        if isinstance(trafalgar_block, Mapping):
            candidates.extend(
                trafalgar_block.get(key)
                for key in ("base_url", "api_url", "url")
            )
        candidates.extend(
            render_block.get(key)
            for key in (
                "trafalgar_base_url",
                "trafalgar_url",
                "base_url",
            )
        )
    return candidates


def _extract_response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"Render API request failed ({response.status_code})."

    if isinstance(payload, Mapping):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
    text = response.text.strip()
    return text or f"Render API request failed ({response.status_code})."


def _normalise_base_url(url: str) -> str:
    stripped = url.strip().rstrip("/")
    if not stripped:
        stripped = DEFAULT_RENDER_API_URL
    return stripped + "/"


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


__all__ = [
    "RenderJobClient",
    "RenderJobClientError",
    "resolve_render_api_timeout",
    "resolve_render_base_url",
]
