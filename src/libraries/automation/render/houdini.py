"""Render adapter that wraps ``hrender`` and ``husk`` command line tools."""

from __future__ import annotations

import re
import subprocess
import uuid
from typing import Sequence

import structlog

from .base import (
    AdapterCapabilities,
    RenderAdapterConfigurationError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
    SubmissionResult,
)
from .config import get_adapter_setting

log = structlog.get_logger(__name__)

_FRAME_RANGE_PATTERN = re.compile(
    r"^\s*(?P<start>-?\d+)(?:\s*-\s*(?P<end>-?\d+))?(?:x(?P<step>\d+))?\s*$"
)

_DEFAULT_CAPABILITIES = AdapterCapabilities(
    default_priority=50,
    priority_min=1,
    priority_max=99,
    chunk_size_enabled=False,
    cancellation_supported=False,
)


def _parse_frame_range(frames: str) -> tuple[int, int, int]:
    match = _FRAME_RANGE_PATTERN.match(frames)
    if not match:
        raise RenderAdapterConfigurationError(
            "Frames must be provided as a single contiguous range (e.g. '1-10x2')."
        )

    start = int(match.group("start"))
    end_group = match.group("end")
    end = int(end_group) if end_group is not None else start
    step = int(match.group("step") or 1)
    if step <= 0:
        raise RenderAdapterConfigurationError("Frame step must be a positive integer.")

    return start, end, step


def _build_hrender_command(
    executable: str,
    *,
    scene: str,
    output: str,
    start: int,
    end: int,
    step: int,
) -> list[str]:
    return [
        executable,
        "-e",
        "-f",
        str(start),
        str(end),
        str(step),
        "-o",
        output,
        scene,
    ]


def _build_husk_command(
    executable: str,
    *,
    scene: str,
    output: str,
    start: int,
    end: int,
    step: int,
) -> list[str]:
    return [
        executable,
        "-f",
        str(start),
        str(end),
        str(step),
        "-o",
        output,
        scene,
    ]


def _select_renderer(scene: str) -> str:
    renderer = get_adapter_setting("houdini", "renderer")
    if renderer:
        renderer = renderer.lower()
    elif scene.lower().endswith((".usd", ".usda", ".usdc")):
        renderer = "husk"
    else:
        renderer = "hrender"

    if renderer not in {"hrender", "husk"}:
        raise RenderAdapterConfigurationError(
            "Unsupported Houdini renderer requested; choose either 'hrender' or 'husk'."
        )

    return renderer


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - handled in submit_job
        raise RenderAdapterUnavailableError(
            "Houdini render executable is not available on this host."
        ) from exc
    except (
        subprocess.CalledProcessError
    ) as exc:  # pragma: no cover - handled in submit_job
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RenderAdapterJobRejectedError(message) from exc


def get_capabilities() -> AdapterCapabilities:
    """Return static capabilities for the Houdini adapter."""

    return AdapterCapabilities(**_DEFAULT_CAPABILITIES)


def submit_job(
    *,
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> SubmissionResult:
    """Submit a Houdini render via ``hrender`` or ``husk``."""

    if chunk_size is not None:
        raise RenderAdapterConfigurationError(
            "Chunk sizing is not supported for Houdini command line renders."
        )

    start, end, step = _parse_frame_range(frames)
    renderer = _select_renderer(scene)
    executable_setting = "hrender_path" if renderer == "hrender" else "husk_path"
    executable = (
        get_adapter_setting("houdini", executable_setting, renderer) or renderer
    )

    build_command = (
        _build_hrender_command if renderer == "hrender" else _build_husk_command
    )
    command = build_command(
        executable,
        scene=scene,
        output=output,
        start=start,
        end=end,
        step=step,
    )

    log.debug(
        "render.houdini.submit_job",
        renderer=renderer,
        scene=scene,
        frames=frames,
        output=output,
        priority=priority,
        user=user,
        command=command,
    )

    try:
        result = _run_command(command)
    except RenderAdapterUnavailableError:
        raise
    except RenderAdapterJobRejectedError:
        raise

    job_id = f"houdini-{uuid.uuid4().hex}"
    message = (result.stdout or "submitted").strip()

    return SubmissionResult(
        job_id=job_id,
        status="submitted",
        farm_type="houdini",
        message=message,
    )


__all__ = ["get_capabilities", "submit_job"]
