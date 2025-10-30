"""OpenCue render farm submission adapter."""

from __future__ import annotations

import time
import json
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

DEFAULT_BASE_URL = "http://localhost:8443"
REQUEST_TIMEOUT = 10.0
CAPABILITIES_CACHE_TTL = 60.0


class OpenCueError(RuntimeError):
    """Base error raised for OpenCue client issues."""


class OpenCueAuthenticationError(OpenCueError):
    """Raised when OpenCue rejects the provided credentials."""


class OpenCueValidationError(OpenCueError):
    """Raised when OpenCue rejects a job payload."""


class OpenCueUnavailableError(OpenCueError):
    """Raised when OpenCue cannot be contacted or returns a server error."""


class OpenCueResponseError(OpenCueError):
    """Raised when OpenCue returns an unexpected payload."""


@dataclass
class OpenCueClient:
    """Minimal OpenCue REST client used by the adapter."""

    base_url: str
    token: str | None = None
    session_factory: Callable[[], requests.Session] = requests.Session

    def __post_init__(self) -> None:
        self._session: requests.Session | None = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self.session_factory()
        return self._session

    def _headers(self) -> Mapping[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def submit_job(self, payload: Mapping[str, Any]) -> Any:
        """Submit a job payload to OpenCue."""

        url = f"{self.base_url.rstrip('/')}/api/jobs"

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise OpenCueUnavailableError("Unable to reach OpenCue API") from exc

        if response.status_code in {401, 403}:
            raise OpenCueAuthenticationError(
                _response_message(response) or "OpenCue authentication failed"
            )
        if response.status_code in {400, 409, 422}:
            raise OpenCueValidationError(
                _response_message(response) or "OpenCue rejected the job payload"
            )
        if response.status_code >= 500:
            raise OpenCueUnavailableError(
                _response_message(response) or "OpenCue encountered an error"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise OpenCueResponseError("OpenCue returned invalid JSON") from exc

    def get_job(self, job_id: str) -> Any:
        """Return metadata for the OpenCue job identified by ``job_id``."""

        url = f"{self.base_url.rstrip('/')}/api/jobs/{job_id}"

        try:
            response = self.session.get(
                url, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise OpenCueUnavailableError("Unable to reach OpenCue API") from exc

        if response.status_code in {401, 403}:
            raise OpenCueAuthenticationError(
                _response_message(response) or "OpenCue authentication failed"
            )
        if response.status_code == 404:
            raise OpenCueResponseError(
                _response_message(response) or "OpenCue job not found"
            )
        if response.status_code >= 500:
            raise OpenCueUnavailableError(
                _response_message(response) or "OpenCue encountered an error"
            )

        if not response.content:
            raise OpenCueResponseError("OpenCue returned an empty response")

        try:
            return response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise OpenCueResponseError("OpenCue returned invalid JSON") from exc

    def cancel_job(self, job_id: str) -> Any:
        """Request cancellation of the OpenCue job identified by ``job_id``."""

        url = f"{self.base_url.rstrip('/')}/api/jobs/{job_id}"

        try:
            response = self.session.delete(
                url, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise OpenCueUnavailableError("Unable to reach OpenCue API") from exc

        if response.status_code in {401, 403}:
            raise OpenCueAuthenticationError(
                _response_message(response) or "OpenCue authentication failed"
            )
        if response.status_code in {400, 409}:
            raise OpenCueValidationError(
                _response_message(response)
                or "OpenCue refused to cancel the requested job"
            )
        if response.status_code == 404:
            raise OpenCueResponseError(
                _response_message(response) or "OpenCue job not found"
            )
        if response.status_code >= 500:
            raise OpenCueUnavailableError(
                _response_message(response) or "OpenCue encountered an error"
            )

        if not response.content:
            return {"status": "cancelled", "message": "Job cancelled"}

        try:
            return response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise OpenCueResponseError("OpenCue returned invalid JSON") from exc

    def get_limits(self) -> Any:
        """Return adapter limits advertised by OpenCue."""

        url = f"{self.base_url.rstrip('/')}/api/capabilities"

        try:
            response = self.session.get(
                url, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise OpenCueUnavailableError("Unable to reach OpenCue API") from exc

        if response.status_code >= 500:
            raise OpenCueUnavailableError(
                _response_message(response) or "OpenCue capabilities unavailable"
            )
        if response.status_code in {401, 403}:
            raise OpenCueAuthenticationError(
                _response_message(response) or "OpenCue authentication failed"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise OpenCueResponseError("OpenCue returned invalid JSON") from exc


def _response_message(response: requests.Response) -> str | None:
    """Extract a helpful error message from an OpenCue HTTP response."""

    try:
        data = response.json()
    except ValueError:
        return response.text or None

    if isinstance(data, Mapping):
        message = data.get("message") or data.get("Message")
        if isinstance(message, str):
            return message
    return response.text or None


def _default_capabilities() -> AdapterCapabilities:
    return AdapterCapabilities(
        default_priority=60,
        priority_min=0,
        priority_max=120,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=25,
        default_chunk_size=6,
        cancellation_supported=False,
    )


_CAPABILITIES_CACHE: tuple[float, AdapterCapabilities] | None = None


def _build_base_url() -> str:
    url_override = get_adapter_setting("opencue", "url")
    if url_override:
        return url_override.rstrip("/")

    host = get_adapter_setting("opencue", "host")
    if host:
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"http://{host}".rstrip("/")

    return DEFAULT_BASE_URL


def _get_client() -> OpenCueClient:
    token = get_adapter_setting("opencue", "token")

    return OpenCueClient(
        base_url=_build_base_url(),
        token=token,
    )


def _translate_capabilities(data: Mapping[str, Any]) -> AdapterCapabilities:
    defaults = _default_capabilities()

    priority = data.get("priority", {}) if isinstance(data, Mapping) else {}
    chunk = data.get("chunk", {}) if isinstance(data, Mapping) else {}
    cancellation = data.get("cancellation", {}) if isinstance(data, Mapping) else {}

    capabilities: AdapterCapabilities = AdapterCapabilities(
        default_priority=int(
            priority.get("default", defaults.get("default_priority", 60))
        ),
        priority_min=int(priority.get("min", defaults.get("priority_min", 0))),
        priority_max=int(priority.get("max", defaults.get("priority_max", 120))),
        chunk_size_enabled=bool(chunk.get("enabled", True)),
        chunk_size_min=int(chunk.get("min", defaults.get("chunk_size_min", 1))),
        chunk_size_max=int(chunk.get("max", defaults.get("chunk_size_max", 25))),
        default_chunk_size=int(
            chunk.get("default", defaults.get("default_chunk_size", 6))
        ),
        cancellation_supported=bool(
            cancellation.get("supported", defaults.get("cancellation_supported", False))
        ),
    )

    return capabilities


def _build_layer_spec(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    chunk_size: int | None,
    capabilities: AdapterCapabilities | None,
) -> Mapping[str, Any]:
    """Create the layer specification payload for OpenCue submissions."""

    layer: dict[str, Any] = {
        "name": f"{dcc}_layer",
        "type": "RENDER",
        "range": frames,
        "command": {
            "dcc": dcc,
            "scene": scene,
            "output": output,
        },
        "environment": {
            "OC_SCENE": scene,
            "OC_OUTPUT": output,
            "OC_DCC": dcc,
        },
    }

    if chunk_size is None:
        caps: AdapterCapabilities | None = capabilities
        if caps is None and _CAPABILITIES_CACHE:
            caps = _CAPABILITIES_CACHE[1]
        if caps is None:
            caps = _default_capabilities()
        if caps.get("chunk_size_enabled", True):
            layer["chunk"] = caps.get("default_chunk_size", 6)
    else:
        layer["chunk"] = chunk_size

    return layer


def _build_job_spec(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> Mapping[str, Any]:
    """Construct an OpenCue job specification."""

    show_override = get_adapter_setting("opencue", "show")
    pool_override = get_adapter_setting("opencue", "pool")
    facility_override = get_adapter_setting("opencue", "facility")

    capabilities = get_capabilities()

    job_spec: dict[str, Any] = {
        "name": f"{dcc} render",
        "user": user,
        "priority": priority,
        "layers": [
            _build_layer_spec(
                scene,
                frames,
                output,
                dcc,
                chunk_size,
                capabilities,
            )
        ],
        "metadata": {
            "scene": scene,
            "output": output,
            "dcc": dcc,
        },
    }

    if show_override:
        job_spec["show"] = show_override
    if pool_override:
        job_spec["pool"] = pool_override
    if facility_override:
        job_spec["facility"] = facility_override

    return job_spec


def submit_job(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> SubmissionResult:
    """Submit a render job to OpenCue and return its metadata."""

    client = _get_client()
    job_spec = _build_job_spec(scene, frames, output, dcc, priority, user, chunk_size)

    log.debug("render.opencue.submit_job", payload=job_spec, base_url=client.base_url)

    try:
        response = client.submit_job(job_spec)
    except OpenCueAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "OpenCue rejected the configured credentials.",
            hint="Verify the RENDER_OPENCUE_TOKEN setting or API access.",
            context={"adapter": "opencue", "scene": scene, "user": user},
        ) from exc
    except OpenCueValidationError as exc:
        raise RenderAdapterJobRejectedError(
            str(exc),
            context={"adapter": "opencue", "scene": scene, "user": user},
        ) from exc
    except OpenCueUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "OpenCue is unavailable.",
            hint="Confirm the Cuebot host is reachable and the REST API is enabled.",
            context={"adapter": "opencue", "scene": scene},
        ) from exc
    except OpenCueResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "opencue", "scene": scene},
        ) from exc
    except OpenCueError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected OpenCue error.",
            context={"adapter": "opencue", "scene": scene},
        ) from exc

    if not isinstance(response, Mapping):
        raise RenderAdapterError(
            "OpenCue returned unexpected job payload.",
            context={"adapter": "opencue", "scene": scene},
        )

    job_id = str(
        response.get("id")
        or response.get("job_id")
        or response.get("jobId")
        or response.get("JobID")
    )
    if not job_id or job_id == "None":
        raise RenderAdapterError(
            "OpenCue did not return a job identifier.",
            context={"adapter": "opencue", "scene": scene},
        )

    status = str(response.get("status") or response.get("state") or "submitted")
    message = response.get("message") or response.get("StatusMessage")

    result: SubmissionResult = SubmissionResult(
        job_id=job_id,
        status=status,
        farm_type="opencue",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    return result


def get_job_status(job_id: str) -> SubmissionResult:
    """Return the most recent state for an OpenCue job."""

    client = _get_client()

    log.debug("render.opencue.get_job_status", job_id=job_id, base_url=client.base_url)

    try:
        payload = client.get_job(job_id)
    except OpenCueAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "OpenCue rejected the configured credentials.",
            hint="Verify the RENDER_OPENCUE_TOKEN setting or API access.",
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "OpenCue is unavailable.",
            hint="Confirm the Cuebot host is reachable and the REST API is enabled.",
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected OpenCue error.",
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc

    if not isinstance(payload, Mapping):
        raise RenderAdapterError(
            "OpenCue returned unexpected job payload.",
            context={"adapter": "opencue", "job_id": job_id},
        )

    payload_job_id = str(
        payload.get("id")
        or payload.get("job_id")
        or payload.get("jobId")
        or payload.get("JobID")
        or job_id
    )
    status = str(
        payload.get("status")
        or payload.get("state")
        or payload.get("jobStatus")
        or "unknown"
    )
    message = payload.get("message") or payload.get("StatusMessage")

    result: SubmissionResult = SubmissionResult(
        job_id=payload_job_id,
        status=status,
        farm_type="opencue",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    return result


def cancel_job(job_id: str) -> SubmissionResult:
    """Cancel an OpenCue job and update adapter capabilities when supported."""

    client = _get_client()

    log.debug("render.opencue.cancel_job", job_id=job_id, base_url=client.base_url)

    try:
        payload = client.cancel_job(job_id)
    except OpenCueAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "OpenCue rejected the configured credentials.",
            hint="Verify the RENDER_OPENCUE_TOKEN setting or API access.",
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueValidationError as exc:
        raise RenderAdapterJobRejectedError(
            str(exc),
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "OpenCue is unavailable.",
            hint="Confirm the Cuebot host is reachable and the REST API is enabled.",
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc
    except OpenCueError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected OpenCue error.",
            context={"adapter": "opencue", "job_id": job_id},
        ) from exc

    if not isinstance(payload, Mapping):
        raise RenderAdapterError(
            "OpenCue returned unexpected job payload.",
            context={"adapter": "opencue", "job_id": job_id},
        )

    status = str(
        payload.get("status")
        or payload.get("state")
        or payload.get("jobStatus")
        or "cancelled"
    )
    message = payload.get("message") or payload.get("StatusMessage")

    result: SubmissionResult = SubmissionResult(
        job_id=str(job_id),
        status=status,
        farm_type="opencue",
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
    """Return OpenCue capabilities, querying and caching API metadata when possible."""

    global _CAPABILITIES_CACHE

    now = time.monotonic()
    if _CAPABILITIES_CACHE and now - _CAPABILITIES_CACHE[0] < CAPABILITIES_CACHE_TTL:
        return _CAPABILITIES_CACHE[1]

    client = _get_client()

    try:
        limits = client.get_limits()
    except (
        OpenCueUnavailableError,
        OpenCueAuthenticationError,
        OpenCueResponseError,
    ) as exc:
        log.warning(
            "render.opencue.capabilities_fallback",
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
    "OpenCueClient",
    "OpenCueError",
    "OpenCueAuthenticationError",
    "OpenCueValidationError",
    "OpenCueUnavailableError",
    "OpenCueResponseError",
]
