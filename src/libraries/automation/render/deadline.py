"""Render adapter that submits jobs to Deadline's REST API.

In addition to job submission the adapter now provides lightweight helpers for
polling job state and cancelling submissions when the Deadline REST API
supports it.  Successful cancellation attempts automatically flag the adapter
as supporting cancellation so callers can toggle related UI affordances.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, cast
import structlog

from tools.usd_bundler import BundleManifest

from .base import (
    AdapterCapabilities,
    RenderAdapterConfigurationError,
    RenderAdapterError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
    SubmissionResult,
)
from .config import get_adapter_setting
from .deadline_api import DeadlineClient
from .deadline_command import DeadlineCommandClient
from .deadline_errors import (
    DeadlineAuthenticationError,
    DeadlineError,
    DeadlineResponseError,
    DeadlineUnavailableError,
    DeadlineValidationError,
)

log = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "http://localhost:8082"
CAPABILITIES_CACHE_TTL = 60.0


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


def _build_deadline_command() -> str | None:
    command = get_adapter_setting("deadline", "command")
    if command:
        return command
    use_command = get_adapter_setting("deadline", "use_command")
    if use_command and use_command.strip().lower() in {"1", "true", "yes", "on"}:
        return "deadlinecommand"
    return None


def _get_client() -> DeadlineClient | DeadlineCommandClient:
    command = _build_deadline_command()
    if command:
        return DeadlineCommandClient(command=command)

    username = get_adapter_setting("deadline", "username")
    password = get_adapter_setting("deadline", "password")

    return DeadlineClient(
        base_url=_build_base_url(),
        username=username,
        password=password,
    )


def _load_bundle_metadata(scene: str) -> Mapping[str, str]:
    """Return Deadline JobInfo extras referencing a nearby USD bundle manifest."""

    scene_path = Path(scene)
    if not scene_path.exists():
        return {}

    candidates = [
        scene_path.parent / "bundle_manifest.json",
        scene_path.parent.parent / "bundle_manifest.json",
        scene_path.with_suffix(scene_path.suffix + ".bundle.json"),
    ]

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            manifest = BundleManifest.from_path(candidate)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning(
                "render.deadline.bundle_manifest_unreadable",
                scene=str(scene_path),
                manifest=str(candidate),
                error=str(exc),
            )
            continue

        return {
            "ExtraInfoKeyValue0": f"bundle_version={manifest.version_hash}",
            "ExtraInfoKeyValue1": f"bundle_manifest={candidate}",
        }

    return {}


def _translate_capabilities(data: Mapping[str, Any]) -> AdapterCapabilities:
    defaults = _default_capabilities()

    priority = data.get("priority", {}) if isinstance(data, Mapping) else {}
    chunk = data.get("chunkSize", {}) if isinstance(data, Mapping) else {}
    cancellation = data.get("cancellation", {}) if isinstance(data, Mapping) else {}

    capabilities: AdapterCapabilities = AdapterCapabilities(
        default_priority=int(
            priority.get("default", defaults.get("default_priority", 50))
        ),
        priority_min=int(priority.get("min", defaults.get("priority_min", 0))),
        priority_max=int(priority.get("max", defaults.get("priority_max", 100))),
        chunk_size_enabled=bool(chunk.get("enabled", True)),
        chunk_size_min=int(chunk.get("min", defaults.get("chunk_size_min", 1))),
        chunk_size_max=int(chunk.get("max", defaults.get("chunk_size_max", 50))),
        default_chunk_size=int(
            chunk.get("default", defaults.get("default_chunk_size", 10))
        ),
        cancellation_supported=bool(
            cancellation.get("supported", defaults.get("cancellation_supported", False))
        ),
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
    *,
    pool: str | None = None,
) -> SubmissionResult:
    """Submit a render job to Deadline and return its metadata."""

    client = _get_client()
    pool_override = pool or get_adapter_setting("deadline", "pool")

    bundle_metadata = _load_bundle_metadata(scene)

    job_info: dict[str, Any] = {
        "Name": f"{dcc} render",
        "UserName": user,
        "Plugin": dcc,
        "Frames": frames,
        "Priority": priority,
        "OutputFilename0": output,
    }
    job_info.update(bundle_metadata)
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


def get_job_status(job_id: str) -> SubmissionResult:
    """Return the most recent state for a Deadline job."""

    client = _get_client()

    log.debug("render.deadline.get_job_status", job_id=job_id, base_url=client.base_url)

    try:
        payload = client.get_job(job_id)
    except DeadlineAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "Deadline rejected the configured credentials.",
            hint="Verify the RENDER_DEADLINE_USERNAME and RENDER_DEADLINE_PASSWORD settings.",
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "Deadline is unavailable.",
            hint="Confirm the Deadline host is reachable and the REST API is enabled.",
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected Deadline error.",
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc

    if not isinstance(payload, Mapping):
        raise RenderAdapterError(
            "Deadline returned unexpected job payload.",
            context={"adapter": "deadline", "job_id": job_id},
        )

    payload_job_id = str(
        payload.get("jobId")
        or payload.get("JobID")
        or payload.get("Id")
        or payload.get("id")
        or job_id
    )
    status = str(
        payload.get("status")
        or payload.get("State")
        or payload.get("JobStatus")
        or "unknown"
    )
    message = (
        payload.get("message") or payload.get("Message") or payload.get("StatusMessage")
    )

    result: SubmissionResult = SubmissionResult(
        job_id=payload_job_id,
        status=status,
        farm_type="deadline",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    return result


def cancel_job(job_id: str) -> SubmissionResult:
    """Cancel a Deadline job and update adapter capabilities when supported."""

    client = _get_client()

    log.debug("render.deadline.cancel_job", job_id=job_id, base_url=client.base_url)

    try:
        payload = client.delete_job(job_id)
    except DeadlineAuthenticationError as exc:
        raise RenderAdapterConfigurationError(
            "Deadline rejected the configured credentials.",
            hint="Verify the RENDER_DEADLINE_USERNAME and RENDER_DEADLINE_PASSWORD settings.",
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineValidationError as exc:
        raise RenderAdapterJobRejectedError(
            str(exc),
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineUnavailableError as exc:
        raise RenderAdapterUnavailableError(
            "Deadline is unavailable.",
            hint="Confirm the Deadline host is reachable and the REST API is enabled.",
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineResponseError as exc:
        raise RenderAdapterError(
            str(exc),
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc
    except DeadlineError as exc:  # pragma: no cover - defensive guard
        raise RenderAdapterError(
            "Unexpected Deadline error.",
            context={"adapter": "deadline", "job_id": job_id},
        ) from exc

    if not isinstance(payload, Mapping):
        raise RenderAdapterError(
            "Deadline returned unexpected job payload.",
            context={"adapter": "deadline", "job_id": job_id},
        )

    status = str(
        payload.get("status")
        or payload.get("State")
        or payload.get("JobStatus")
        or "cancelled"
    )
    message = (
        payload.get("message") or payload.get("Message") or payload.get("StatusMessage")
    )

    result: SubmissionResult = SubmissionResult(
        job_id=str(job_id),
        status=status,
        farm_type="deadline",
    )
    if isinstance(message, str) and message:
        result["message"] = message

    # Successful cancellation implies Deadline supports the feature. Toggle the
    # cached capabilities so callers can react immediately.
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
    """Return Deadline capabilities, querying and caching API metadata when possible."""

    global _CAPABILITIES_CACHE

    now = time.monotonic()
    if _CAPABILITIES_CACHE and now - _CAPABILITIES_CACHE[0] < CAPABILITIES_CACHE_TTL:
        return _CAPABILITIES_CACHE[1]

    client = _get_client()

    try:
        limits = client.get_limits()
    except (
        DeadlineUnavailableError,
        DeadlineAuthenticationError,
        DeadlineResponseError,
    ) as exc:
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
    "get_job_status",
    "cancel_job",
    "get_capabilities",
    "DeadlineClient",
    "DeadlineCommandClient",
    "DeadlineError",
    "DeadlineAuthenticationError",
    "DeadlineValidationError",
    "DeadlineUnavailableError",
    "DeadlineResponseError",
]
