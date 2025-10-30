"""Render adapter for Pixar Tractor's REST interface."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

import requests
import structlog

from .base import (
    AdapterCapabilities,
    RenderAdapterConfigurationError,
    RenderAdapterError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
    SubmissionResult,
)
from .config import get_adapter_setting

log = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "http://localhost:8085"
REQUEST_TIMEOUT = 10.0
CAPABILITIES_CACHE_TTL = 60.0


class TractorError(RuntimeError):
    """Base error raised for Tractor client issues."""


class TractorAuthenticationError(TractorError):
    """Raised when Tractor rejects the provided credentials."""


class TractorValidationError(TractorError):
    """Raised when Tractor rejects a job payload."""


class TractorUnavailableError(TractorError):
    """Raised when Tractor cannot be contacted or returns a server error."""


class TractorResponseError(TractorError):
    """Raised when Tractor returns an unexpected payload."""


@dataclass
class TractorClient:
    """Minimal Tractor REST client used by the adapter."""

    base_url: str
    username: str | None = None
    password: str | None = None
    session_factory: Callable[[], requests.Session] = requests.Session

    def __post_init__(self) -> None:
        self._session: requests.Session | None = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self.session_factory()
        return self._session

    def submit_job(self, payload: Mapping[str, Any]) -> Any:
        """Submit a job payload to Tractor."""

        url = f"{self.base_url.rstrip('/')}/api/jobs"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.post(
                url, json=payload, timeout=REQUEST_TIMEOUT, auth=auth
            )
        except requests.RequestException as exc:
            raise TractorUnavailableError("Unable to reach Tractor API") from exc

        if response.status_code in {401, 403}:
            raise TractorAuthenticationError(
                _response_message(response) or "Tractor authentication failed"
            )
        if response.status_code in {400, 422, 409}:
            raise TractorValidationError(
                _response_message(response) or "Tractor rejected the job payload"
            )
        if response.status_code >= 500:
            raise TractorUnavailableError(
                _response_message(response) or "Tractor encountered an error"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise TractorResponseError("Tractor returned invalid JSON") from exc

    def get_job(self, job_id: str) -> Any:
        """Return metadata for the Tractor job identified by ``job_id``."""

        url = f"{self.base_url.rstrip('/')}/api/jobs/{job_id}"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:
            raise TractorUnavailableError("Unable to reach Tractor API") from exc

        if response.status_code in {401, 403}:
            raise TractorAuthenticationError(
                _response_message(response) or "Tractor authentication failed"
            )
        if response.status_code == 404:
            raise TractorResponseError(
                _response_message(response) or "Tractor job not found"
            )
        if response.status_code >= 500:
            raise TractorUnavailableError(
                _response_message(response) or "Tractor encountered an error"
            )

        if not response.content:
            raise TractorResponseError("Tractor returned an empty response")

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise TractorResponseError("Tractor returned invalid JSON") from exc

    def cancel_job(self, job_id: str) -> Any:
        """Request cancellation of the Tractor job identified by ``job_id``."""

        url = f"{self.base_url.rstrip('/')}/api/jobs/{job_id}/cancel"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.post(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:
            raise TractorUnavailableError("Unable to reach Tractor API") from exc

        if response.status_code in {401, 403}:
            raise TractorAuthenticationError(
                _response_message(response) or "Tractor authentication failed"
            )
        if response.status_code in {400, 409}:
            raise TractorValidationError(
                _response_message(response)
                or "Tractor refused to cancel the requested job"
            )
        if response.status_code == 404:
            raise TractorResponseError(
                _response_message(response) or "Tractor job not found"
            )
        if response.status_code >= 500:
            raise TractorUnavailableError(
                _response_message(response) or "Tractor encountered an error"
            )

        if not response.content:
            return {"status": "cancelled", "message": "Job cancelled"}

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise TractorResponseError("Tractor returned invalid JSON") from exc

    def get_limits(self) -> Any:
        """Return adapter limits advertised by Tractor."""

        url = f"{self.base_url.rstrip('/')}/api/capabilities"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:
            raise TractorUnavailableError("Unable to reach Tractor API") from exc

        if response.status_code >= 500:
            raise TractorUnavailableError(
                _response_message(response) or "Tractor capabilities unavailable"
            )
        if response.status_code in {401, 403}:
            raise TractorAuthenticationError(
                _response_message(response) or "Tractor authentication failed"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise TractorResponseError("Tractor returned invalid JSON") from exc


def _response_message(response: requests.Response) -> str | None:
    """Extract a helpful error message from a Tractor HTTP response."""

    try:
        data = response.json()
    except json.JSONDecodeError:
        return response.text or None

    if isinstance(data, Mapping):
        message = data.get("message") or data.get("Message")
        if isinstance(message, str):
            return message
    return response.text or None


def _default_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        default_priority=75,
        priority_min=1,
        priority_max=150,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=30,
        default_chunk_size=8,
        cancellation_supported=False,
    )


_CAPABILITIES_CACHE: tuple[float, AdapterCapabilities] | None = None


def _build_base_url() -> str:
    url_override = get_adapter_setting("tractor", "url")
    if url_override:
        return url_override.rstrip("/")

    host = get_adapter_setting("tractor", "host")
    if host:
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"http://{host}".rstrip("/")

    return DEFAULT_BASE_URL


def _get_client() -> TractorClient:
    username = get_adapter_setting("tractor", "username")
    password = get_adapter_setting("tractor", "password")

    return TractorClient(
        base_url=_build_base_url(),
        username=username,
        password=password,
    )


def _translate_capabilities(data: Mapping[str, Any]) -> AdapterCapabilities:
    defaults = _default_capabilities()

    priority = data.get("priority", {}) if isinstance(data, Mapping) else {}
    chunk = data.get("chunking") or data.get("chunkSize")
    if not isinstance(chunk, Mapping):
        chunk = {}
    cancellation = data.get("cancellation") if isinstance(data, Mapping) else {}
    if not isinstance(cancellation, Mapping):
        cancellation = {}

    capabilities: AdapterCapabilities = AdapterCapabilities(
        default_priority=int(
            priority.get("default", defaults.get("default_priority", 75))
        ),
        priority_min=int(priority.get("min", defaults.get("priority_min", 1))),
        priority_max=int(priority.get("max", defaults.get("priority_max", 150))),
        chunk_size_enabled=bool(chunk.get("enabled", True)),
        chunk_size_min=int(chunk.get("min", defaults.get("chunk_size_min", 1))),
        chunk_size_max=int(chunk.get("max", defaults.get("chunk_size_max", 30))),
        default_chunk_size=int(
            chunk.get("default", defaults.get("default_chunk_size", 8))
        ),
        cancellation_supported=bool(
            cancellation.get("supported", defaults.get("cancellation_supported", False))
        ),
    )

    return capabilities


def _build_submission_payload(
    *,
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> Mapping[str, Any]:
    task: dict[str, Any] = {
        "scene": scene,
        "frames": frames,
        "output": output,
        "dcc": dcc,
    }
    if chunk_size is not None:
        task["chunkSize"] = chunk_size

    payload: dict[str, Any] = {
        "job": {
            "name": f"{dcc} render",
            "user": user,
            "priority": priority,
        },
        "task": task,
    }

    return payload


def submit_job(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> SubmissionResult:
    """Submit a render job to Tractor and return its metadata."""

    client = _get_client()
    payload = _build_submission_payload(
        scene=scene,
        frames=frames,
        output=output,
        dcc=dcc,
        priority=priority,
        user=user,
        chunk_size=chunk_size,
    )

    log.debug("render.tractor.submit_job", payload=payload, base_url=client.base_url)

    try:
        response = client.submit_job(payload)
    except TractorAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "Tractor rejected the configured credentials.",
            hint="Verify the RENDER_TRACTOR_USERNAME and RENDER_TRACTOR_PASSWORD settings.",
            context={"adapter": "tractor", "scene": scene, "user": user},
        ) from exc
    except TractorValidationError as exc:
        raise RenderAdapterJobRejectedError(
            str(exc),
            context={"adapter": "tractor", "scene": scene, "user": user},
        ) from exc
    except TractorUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "Tractor is unavailable.",
            hint="Confirm the Tractor host is reachable and the RPC bridge is enabled.",
            context={"adapter": "tractor", "scene": scene},
        ) from exc
    except TractorError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected Tractor error.",
            context={"adapter": "tractor", "scene": scene},
        ) from exc

    job_id = str(
        response.get("jobId")
        or response.get("id")
        or response.get("JobID")
        or response.get("JobId")
    )
    if not job_id or job_id == "None":
        raise RenderAdapterError(
            "Tractor did not return a job identifier.",
            context={"adapter": "tractor", "scene": scene},
        )

    status = str(response.get("status") or response.get("state") or "submitted")
    message = response.get("message") or response.get("Message")

    result: SubmissionResult = SubmissionResult(
        job_id=job_id,
        status=status,
        farm_type="tractor",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    return result


def get_job_status(job_id: str) -> SubmissionResult:
    """Return the most recent state for a Tractor job."""

    client = _get_client()

    log.debug("render.tractor.get_job_status", job_id=job_id, base_url=client.base_url)

    try:
        payload = client.get_job(job_id)
    except TractorAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "Tractor rejected the configured credentials.",
            hint="Verify the RENDER_TRACTOR_USERNAME and RENDER_TRACTOR_PASSWORD settings.",
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "Tractor is unavailable.",
            hint="Confirm the Tractor host is reachable and the RPC bridge is enabled.",
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected Tractor error.",
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc

    if not isinstance(payload, Mapping):
        raise RenderAdapterError(
            "Tractor returned unexpected job payload.",
            context={"adapter": "tractor", "job_id": job_id},
        )

    payload_job_id = str(
        payload.get("jobId")
        or payload.get("id")
        or payload.get("JobID")
        or payload.get("JobId")
        or job_id
    )
    status = str(
        payload.get("status")
        or payload.get("state")
        or payload.get("jobStatus")
        or "unknown"
    )
    message = payload.get("message") or payload.get("Message")

    result: SubmissionResult = SubmissionResult(
        job_id=payload_job_id,
        status=status,
        farm_type="tractor",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    return result


def cancel_job(job_id: str) -> SubmissionResult:
    """Cancel a Tractor job and update adapter capabilities when supported."""

    client = _get_client()

    log.debug("render.tractor.cancel_job", job_id=job_id, base_url=client.base_url)

    try:
        payload = client.cancel_job(job_id)
    except TractorAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "Tractor rejected the configured credentials.",
            hint="Verify the RENDER_TRACTOR_USERNAME and RENDER_TRACTOR_PASSWORD settings.",
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorValidationError as exc:
        raise RenderAdapterJobRejectedError(
            str(exc),
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "Tractor is unavailable.",
            hint="Confirm the Tractor host is reachable and the RPC bridge is enabled.",
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc
    except TractorError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected Tractor error.",
            context={"adapter": "tractor", "job_id": job_id},
        ) from exc

    if not isinstance(payload, Mapping):
        raise RenderAdapterError(
            "Tractor returned unexpected job payload.",
            context={"adapter": "tractor", "job_id": job_id},
        )

    status = str(payload.get("status") or payload.get("state") or "cancelled")
    message = payload.get("message") or payload.get("Message")

    result: SubmissionResult = SubmissionResult(
        job_id=str(job_id),
        status=status,
        farm_type="tractor",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    global _CAPABILITIES_CACHE
    cache_timestamp = time.monotonic()
    if _CAPABILITIES_CACHE:
        cached_capabilities: dict[str, Any] = dict(_CAPABILITIES_CACHE[1])
        if not cached_capabilities.get("cancellation_supported"):
            cached_capabilities["cancellation_supported"] = True
            _CAPABILITIES_CACHE = (
                cache_timestamp,
                cast(AdapterCapabilities, cached_capabilities),
            )
    else:
        capabilities = _default_capabilities()
        capabilities["cancellation_supported"] = True
        _CAPABILITIES_CACHE = (cache_timestamp, capabilities)

    return result


def get_capabilities() -> AdapterCapabilities:
    """Return Tractor capabilities, querying and caching API metadata when possible."""

    global _CAPABILITIES_CACHE

    now = time.monotonic()
    if _CAPABILITIES_CACHE and now - _CAPABILITIES_CACHE[0] < CAPABILITIES_CACHE_TTL:
        return _CAPABILITIES_CACHE[1]

    client = _get_client()

    try:
        limits = client.get_limits()
    except (
        TractorUnavailableError,
        TractorAuthenticationError,
        TractorResponseError,
    ) as exc:
        log.warning(
            "render.tractor.capabilities_fallback",
            error=str(exc),
        )
        capabilities = _default_capabilities()
    else:
        capabilities = _translate_capabilities(limits)

    _CAPABILITIES_CACHE = (now, capabilities)
    return capabilities


__all__ = [
    "submit_job",
    "get_job_status",
    "cancel_job",
    "get_capabilities",
    "TractorClient",
    "TractorError",
    "TractorAuthenticationError",
    "TractorValidationError",
    "TractorUnavailableError",
    "TractorResponseError",
]
