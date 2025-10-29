"""Render adapter that submits jobs to Deadline's REST API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

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

DEFAULT_BASE_URL = "http://localhost:8082"
REQUEST_TIMEOUT = 10.0
CAPABILITIES_CACHE_TTL = 60.0


class DeadlineError(RuntimeError):
    """Base error raised for Deadline client issues."""


class DeadlineAuthenticationError(DeadlineError):
    """Raised when Deadline rejects the provided credentials."""


class DeadlineValidationError(DeadlineError):
    """Raised when Deadline rejects a job payload."""


class DeadlineUnavailableError(DeadlineError):
    """Raised when Deadline cannot be contacted or returns a server error."""


class DeadlineResponseError(DeadlineError):
    """Raised when Deadline returns an unexpected payload."""


@dataclass
class DeadlineClient:
    """Minimal Deadline REST client used by the adapter."""

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

    def submit_job(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Submit a job payload to Deadline."""

        url = f"{self.base_url.rstrip('/')}/api/jobs"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.post(url, json=payload, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:  # pragma: no cover - exercised via DeadlineUnavailableError
            raise DeadlineUnavailableError("Unable to reach Deadline API") from exc

        if response.status_code in {401, 403}:
            raise DeadlineAuthenticationError(_response_message(response) or "Deadline authentication failed")
        if response.status_code in {400, 422}:
            raise DeadlineValidationError(_response_message(response) or "Deadline rejected the job payload")
        if response.status_code == 409:
            raise DeadlineValidationError(_response_message(response) or "Deadline refused to queue the job")
        if response.status_code >= 500:
            raise DeadlineUnavailableError(_response_message(response) or "Deadline encountered an error")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise DeadlineResponseError("Deadline returned invalid JSON") from exc

        return data

    def get_limits(self) -> Mapping[str, Any]:
        """Return adapter limits advertised by Deadline."""

        url = f"{self.base_url.rstrip('/')}/api/capabilities"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:  # pragma: no cover - handled by DeadlineUnavailableError
            raise DeadlineUnavailableError("Unable to reach Deadline API") from exc

        if response.status_code >= 500:
            raise DeadlineUnavailableError(_response_message(response) or "Deadline capabilities unavailable")
        if response.status_code in {401, 403}:
            raise DeadlineAuthenticationError(_response_message(response) or "Deadline authentication failed")

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise DeadlineResponseError("Deadline returned invalid JSON") from exc


def _response_message(response: requests.Response) -> str | None:
    """Extract a helpful error message from a Deadline HTTP response."""

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
        default_priority=50,
        priority_min=0,
        priority_max=100,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=50,
        default_chunk_size=10,
        cancellation_supported=False,
    )


_CAPABILITIES_CACHE: tuple[float, AdapterCapabilities] | None = None


def _build_base_url() -> str:
    url_override = get_adapter_setting("deadline", "url")
    if url_override:
        return url_override.rstrip("/")

    host = get_adapter_setting("deadline", "host")
    if host:
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"http://{host}".rstrip("/")

    return DEFAULT_BASE_URL


def _get_client() -> DeadlineClient:
    username = get_adapter_setting("deadline", "username")
    password = get_adapter_setting("deadline", "password")

    return DeadlineClient(
        base_url=_build_base_url(),
        username=username,
        password=password,
    )


def _translate_capabilities(data: Mapping[str, Any]) -> AdapterCapabilities:
    defaults = _default_capabilities()

    priority = data.get("priority", {}) if isinstance(data, Mapping) else {}
    chunk = data.get("chunkSize", {}) if isinstance(data, Mapping) else {}
    cancellation = data.get("cancellation", {}) if isinstance(data, Mapping) else {}

    capabilities: AdapterCapabilities = AdapterCapabilities(
        default_priority=int(priority.get("default", defaults.get("default_priority", 50))),
        priority_min=int(priority.get("min", defaults.get("priority_min", 0))),
        priority_max=int(priority.get("max", defaults.get("priority_max", 100))),
        chunk_size_enabled=bool(chunk.get("enabled", True)),
        chunk_size_min=int(chunk.get("min", defaults.get("chunk_size_min", 1))),
        chunk_size_max=int(chunk.get("max", defaults.get("chunk_size_max", 50))),
        default_chunk_size=int(chunk.get("default", defaults.get("default_chunk_size", 10))),
        cancellation_supported=bool(cancellation.get("supported", defaults.get("cancellation_supported", False))),
    )

    return capabilities


def submit_job(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> SubmissionResult:
    """Submit a render job to Deadline and return its metadata."""

    client = _get_client()
    pool_override = get_adapter_setting("deadline", "pool")

    job_info: dict[str, Any] = {
        "Name": f"{dcc} render",
        "UserName": user,
        "Plugin": dcc,
        "Frames": frames,
        "Priority": priority,
        "OutputFilename0": output,
    }
    if pool_override:
        job_info["Pool"] = pool_override
    if chunk_size is not None:
        job_info["ChunkSize"] = chunk_size

    plugin_info = {"SceneFile": scene}

    payload = {"JobInfo": job_info, "PluginInfo": plugin_info}

    log.debug(
        "render.deadline.submit_job",
        payload=payload,
        base_url=client.base_url,
    )

    try:
        response = client.submit_job(payload)
    except DeadlineAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "Deadline rejected the configured credentials.",
            hint="Verify the RENDER_DEADLINE_USERNAME and RENDER_DEADLINE_PASSWORD settings.",
            context={"adapter": "deadline", "scene": scene, "user": user},
        ) from exc
    except DeadlineValidationError as exc:
        raise RenderAdapterJobRejectedError(
            str(exc),
            context={"adapter": "deadline", "scene": scene, "user": user},
        ) from exc
    except DeadlineUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "Deadline is unavailable.",
            hint="Confirm the Deadline host is reachable and the REST API is enabled.",
            context={"adapter": "deadline", "scene": scene},
        ) from exc
    except DeadlineError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected Deadline error.",
            context={"adapter": "deadline", "scene": scene},
        ) from exc

    job_id = str(
        response.get("jobId")
        or response.get("JobID")
        or response.get("Id")
        or response.get("id")
    )
    if not job_id or job_id == "None":
        raise RenderAdapterError(
            "Deadline did not return a job identifier.",
            context={"adapter": "deadline", "scene": scene},
        )

    status = str(response.get("status") or response.get("State") or "submitted")
    message = response.get("message") or response.get("Message")

    result: SubmissionResult = SubmissionResult(
        job_id=job_id,
        status=status,
        farm_type="deadline",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    return result


def get_capabilities() -> AdapterCapabilities:
    """Return Deadline capabilities, querying and caching API metadata when possible."""

    global _CAPABILITIES_CACHE

    now = time.monotonic()
    if _CAPABILITIES_CACHE and now - _CAPABILITIES_CACHE[0] < CAPABILITIES_CACHE_TTL:
        return _CAPABILITIES_CACHE[1]

    client = _get_client()

    try:
        limits = client.get_limits()
    except (DeadlineUnavailableError, DeadlineAuthenticationError, DeadlineResponseError) as exc:
        log.warning(
            "render.deadline.capabilities_fallback",
            error=str(exc),
        )
        capabilities = _default_capabilities()
    else:
        capabilities = _translate_capabilities(limits)

    _CAPABILITIES_CACHE = (now, capabilities)
    return capabilities


__all__ = [
    "submit_job",
    "get_capabilities",
    "DeadlineClient",
    "DeadlineError",
    "DeadlineAuthenticationError",
    "DeadlineValidationError",
    "DeadlineUnavailableError",
    "DeadlineResponseError",
]
