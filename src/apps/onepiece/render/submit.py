"""Render submission CLI command with preset helpers."""

from __future__ import annotations

import getpass
import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Final, Mapping, cast

import click
import structlog
import typer

from apps.onepiece.config import load_profile
from apps.onepiece.utils.errors import (
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceIOError,
    OnePieceRuntimeError,
    OnePieceValidationError,
)
from .jobs import RenderJobClient, RenderJobClientError
from libraries.automation.render import deadline, mock, opencue, tractor
from libraries.automation.render.base import (
    AdapterCapabilities,
    RenderAdapterNotImplementedError,
    RenderSubmissionError,
)
from libraries.automation.render.models import CapabilityProvider, RenderAdapter
from libraries.automation.render.optimization import (
    AdapterDefaults,
    FarmMetrics,
    SubmissionOptimizationDecision,
    compute_submission_adjustments,
)

log = structlog.get_logger(__name__)

app = typer.Typer(
    name="render", help="Render farm submission and management commands."
)
presets_app = typer.Typer(name="preset", help="Manage render submission presets.")
app.add_typer(presets_app, name="preset")

DCC_CHOICES: Final[tuple[str, ...]] = (
    "maya",
    "nuke",
    "houdini",
    "blender",
    "max",
    "vray",
)
FARM_CHOICES: Final[tuple[str, ...]] = ("deadline", "tractor", "opencue", "mock")

PRESET_DIR_ENV: Final[str] = "ONEPIECE_RENDER_PRESET_DIR"
PRESET_DIR_DEFAULT: Final[Path] = Path.home() / ".onepiece" / "render_presets"
PRESET_EXTENSION: Final[str] = ".json"

FARM_ADAPTERS: Final[dict[str, RenderAdapter]] = {
    "deadline": deadline.submit_job,
    "tractor": tractor.submit_job,
    "opencue": opencue.submit_job,
    "mock": mock.submit_job,
}

FARM_CAPABILITY_PROVIDERS: Final[dict[str, CapabilityProvider]] = {
    "deadline": deadline.get_capabilities,
    "tractor": tractor.get_capabilities,
    "opencue": opencue.get_capabilities,
    "mock": mock.get_capabilities,
}

_CAPABILITIES_CACHE_TTL_SECONDS: Final[float] = 60.0
_CAPABILITIES_CACHE_MAXSIZE: Final[int] = 32
_CAPABILITIES_CACHE_LOCK = threading.RLock()
_CAPABILITIES_CACHE: OrderedDict[str, tuple[float, AdapterCapabilities]] = OrderedDict()

_FRAME_SEGMENT_PATTERN = re.compile(
    r"^\s*(?P<start>-?\d+)(?:\s*-\s*(?P<end>-?\d+))?(?:x(?P<step>\d+))?\s*$"
)


def _optional_int(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OnePieceValidationError(
            f"Profile optimisation value '{label}' must be an integer."
        )
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError as exc:
            raise OnePieceValidationError(
                f"Profile optimisation value '{label}' must be an integer."
            ) from exc
    raise OnePieceValidationError(
        f"Profile optimisation value '{label}' must be an integer."
    )


def _optional_float(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OnePieceValidationError(
            f"Profile optimisation value '{label}' must be numeric."
        )
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError as exc:
            raise OnePieceValidationError(
                f"Profile optimisation value '{label}' must be numeric."
            ) from exc
    raise OnePieceValidationError(
        f"Profile optimisation value '{label}' must be numeric."
    )


def _parse_frame_count(spec: str) -> int | None:
    """Best-effort parser for frame range specifications."""

    total = 0
    segments = [part.strip() for part in spec.split(",") if part.strip()]
    if not segments:
        return None

    for segment in segments:
        match = _FRAME_SEGMENT_PATTERN.match(segment)
        if not match:
            return None
        start = int(match.group("start"))
        end = match.group("end")
        end_value = int(end) if end is not None else start
        step = int(match.group("step") or 1)
        if step <= 0:
            return None

        if start <= end_value:
            span = end_value - start
        else:
            span = start - end_value
        total += span // step + 1

    return total if total > 0 else None


def _extract_metrics_from_profile(data: Mapping[str, Any]) -> FarmMetrics:
    render_block = data.get("render")
    if not isinstance(render_block, Mapping):
        return FarmMetrics()
    optimisation_block = render_block.get("optimization")
    if not isinstance(optimisation_block, Mapping):
        return FarmMetrics()

    queue_depth = _optional_int(
        optimisation_block.get("queue_depth"), label="queue_depth"
    )
    average_ms = optimisation_block.get("average_frame_ms")
    if average_ms is None:
        average_ms = optimisation_block.get("average_frame_time_ms")
    average_frame_ms = _optional_float(average_ms, label="average_frame_ms")

    return FarmMetrics(
        queue_depth=queue_depth,
        average_frame_time_ms=average_frame_ms,
    )


def _resolve_metrics(
    *,
    optimize: bool,
    profile_name: str | None,
    queue_depth: int | None,
    average_frame_ms: float | None,
) -> tuple[FarmMetrics, tuple[str, ...]]:
    metrics = FarmMetrics()
    sources: list[str] = []

    if not optimize:
        return metrics, tuple(sources)

    try:
        profile_context = load_profile(profile=profile_name)
    except OnePieceConfigError as exc:
        raise OnePieceValidationError(str(exc)) from exc

    profile_metrics = _extract_metrics_from_profile(profile_context.data)
    if (
        profile_metrics.queue_depth is not None
        or profile_metrics.average_frame_time_ms is not None
    ):
        metrics = profile_metrics
        sources.append("profile")

    if queue_depth is not None:
        metrics = FarmMetrics(
            queue_depth=queue_depth,
            average_frame_time_ms=metrics.average_frame_time_ms,
        )
        sources.append("cli.queue_depth")

    if average_frame_ms is not None:
        metrics = FarmMetrics(
            queue_depth=metrics.queue_depth,
            average_frame_time_ms=average_frame_ms,
        )
        sources.append("cli.average_frame_ms")

    return metrics, tuple(sources)


def _get_adapter(farm: str) -> RenderAdapter:
    adapter = FARM_ADAPTERS.get(farm)
    if adapter is None:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")
    return adapter


def _refresh_capabilities_cache(*, farm: str | None = None) -> None:
    """Clear cached capability information for one or all farms."""

    with _CAPABILITIES_CACHE_LOCK:
        if farm is None:
            _CAPABILITIES_CACHE.clear()
        else:
            _CAPABILITIES_CACHE.pop(farm, None)


def _fetch_adapter_capabilities(farm: str) -> AdapterCapabilities:
    provider = FARM_CAPABILITY_PROVIDERS.get(farm)
    if provider is None:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")
    try:
        raw_capabilities = provider() or {}
    except RenderSubmissionError as exc:
        raise OnePieceExternalServiceError(
            f"Failed to query capabilities from '{farm}' adapter: {exc}"
        ) from exc
    return dict(raw_capabilities)


def _get_adapter_capabilities(farm: str) -> AdapterCapabilities:
    now = time.monotonic()
    with _CAPABILITIES_CACHE_LOCK:
        cached = _CAPABILITIES_CACHE.get(farm)
        if cached is not None:
            expires_at, capabilities = cached
            if expires_at > now:
                _CAPABILITIES_CACHE.move_to_end(farm)
                return dict(capabilities)

    capabilities = _fetch_adapter_capabilities(farm)
    expiry = time.monotonic() + _CAPABILITIES_CACHE_TTL_SECONDS

    with _CAPABILITIES_CACHE_LOCK:
        _CAPABILITIES_CACHE[farm] = (expiry, dict(capabilities))
        _CAPABILITIES_CACHE.move_to_end(farm)
        while len(_CAPABILITIES_CACHE) > _CAPABILITIES_CACHE_MAXSIZE:
            _CAPABILITIES_CACHE.popitem(last=False)

    return dict(capabilities)


def _resolve_priority_and_chunk_size(
    *,
    farm: str,
    priority: int | None,
    chunk_size: int | None,
    capabilities: AdapterCapabilities | None = None,
    capability_provider: CapabilityProvider | None = None,
    frame_count: int | None = None,
    optimize: bool = True,
    metrics: FarmMetrics | None = None,
) -> tuple[
    int | None,
    int | None,
    AdapterCapabilities,
    SubmissionOptimizationDecision | None,
]:
    resolved_capabilities: AdapterCapabilities
    if capabilities is not None:
        resolved_capabilities = dict(capabilities)
    else:
        provider = capability_provider
        if provider is None:
            resolved_capabilities = _get_adapter_capabilities(farm)
        else:
            try:
                resolved_capabilities = provider() or {}
            except RenderSubmissionError as exc:
                raise OnePieceExternalServiceError(
                    f"Failed to query capabilities from '{farm}' adapter: {exc}"
                ) from exc

    resolved_priority = priority
    if resolved_priority is None:
        resolved_priority = resolved_capabilities.get("default_priority", 50)

    adapter_default_priority = resolved_capabilities.get("default_priority", 50)

    min_priority = resolved_capabilities.get("priority_min")
    max_priority = resolved_capabilities.get("priority_max")
    if min_priority is not None and resolved_priority < min_priority:
        raise OnePieceValidationError(
            f"Priority {resolved_priority} is below the supported minimum of {min_priority} (--priority)."
        )
    if max_priority is not None and resolved_priority > max_priority:
        raise OnePieceValidationError(
            f"Priority {resolved_priority} exceeds the supported maximum of {max_priority} (--priority)."
        )

    chunk_enabled = resolved_capabilities.get("chunk_size_enabled", False)
    chunk_min = resolved_capabilities.get("chunk_size_min")
    chunk_max = resolved_capabilities.get("chunk_size_max")
    adapter_default_chunk = (
        resolved_capabilities.get("default_chunk_size") if chunk_enabled else None
    )
    if chunk_size is not None:
        resolved_chunk = chunk_size
    elif chunk_enabled:
        resolved_chunk = adapter_default_chunk
    else:
        resolved_chunk = None

    optimisation_summary: SubmissionOptimizationDecision | None = None
    if (
        optimize
        and frame_count is not None
        and frame_count > 0
        and (priority is None or (chunk_enabled and chunk_size is None))
    ):
        defaults = AdapterDefaults(
            default_priority=adapter_default_priority,
            priority_min=min_priority,
            priority_max=max_priority,
            default_chunk_size=adapter_default_chunk,
            chunk_size_min=chunk_min,
            chunk_size_max=chunk_max,
            chunk_size_enabled=chunk_enabled and adapter_default_chunk is not None,
        )
        try:
            optimisation_summary = compute_submission_adjustments(
                frame_count,
                defaults,
                metrics=metrics,
            )
        except ValueError:
            optimisation_summary = None
        else:
            if priority is None:
                resolved_priority = optimisation_summary.priority
            if chunk_size is None and chunk_enabled:
                resolved_chunk = optimisation_summary.chunk_size

    if resolved_chunk is not None:
        if not chunk_enabled:
            raise OnePieceValidationError(
                "Chunk sizing is not supported by this adapter (--chunk-size)."
            )
        if chunk_min is not None and resolved_chunk < chunk_min:
            raise OnePieceValidationError(
                f"Chunk size {resolved_chunk} is below the supported minimum of {chunk_min} (--chunk-size)."
            )
        if chunk_max is not None and resolved_chunk > chunk_max:
            raise OnePieceValidationError(
                f"Chunk size {resolved_chunk} exceeds the supported maximum of {chunk_max} (--chunk-size)."
            )
    elif chunk_size is not None:
        # Explicitly requested None but the adapter does not support chunking.
        raise OnePieceValidationError(
            "Chunk sizing is not supported by this adapter (--chunk-size)."
        )

    return (
        resolved_priority,
        resolved_chunk,
        resolved_capabilities,
        optimisation_summary,
    )


def _validate_preset_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise OnePieceValidationError("Preset name cannot be empty.")
    if any(sep in cleaned for sep in ("/", "\\")):
        raise OnePieceValidationError("Preset name cannot include path separators.")
    return cleaned


def _get_preset_dir() -> Path:
    override = os.environ.get(PRESET_DIR_ENV)
    if override:
        base = Path(override).expanduser().resolve()
    else:
        base = PRESET_DIR_DEFAULT
    base.mkdir(parents=True, exist_ok=True)
    return base


def _preset_path(name: str) -> Path:
    safe_name = _validate_preset_name(name)
    return _get_preset_dir() / f"{safe_name}{PRESET_EXTENSION}"


def _load_preset(name: str) -> dict[str, Any]:
    path = _preset_path(name)
    if not path.exists():
        raise OnePieceIOError(f"Preset '{name}' was not found at {path}.")
    return cast(dict[str, Any], json.loads(path.read_text()))


def _save_preset(name: str, data: dict[str, Any]) -> Path:
    path = _preset_path(name)
    serialised = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(serialised)
    return path


def _list_presets() -> list[tuple[str, dict[str, Any]]]:
    directory = _get_preset_dir()
    presets: list[tuple[str, dict[str, Any]]] = []
    for preset_file in sorted(directory.glob(f"*{PRESET_EXTENSION}")):
        name = preset_file.stem
        try:
            presets.append((name, json.loads(preset_file.read_text())))
        except json.JSONDecodeError:
            log.warning("render.presets.invalid", preset=str(preset_file))
    return presets


@app.command("submit")
def submit(
    *,
    dcc: str = typer.Option(
        ...,
        "--dcc",
        help="Which DCC generated the render.",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    scene: Path = typer.Option(
        ..., "--scene", help="Path to the scene file to render."
    ),
    frames: str = typer.Option(
        "1-100",
        "--frames",
        help="Frame range to render (e.g. 1-100 or 1-100x2).",
    ),
    output: Path = typer.Option(..., "--output", help="Directory for rendered frames."),
    farm: str = typer.Option(
        "mock",
        "--farm",
        help="Render farm manager to submit to.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    priority: int | None = typer.Option(
        None,
        "--priority",
        help="Render job priority (falls back to the adapter default).",
    ),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        help="Frames per chunk to dispatch when supported by the adapter.",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Submitting user (defaults to the current system user).",
    ),
    refresh_capabilities: bool = typer.Option(
        False,
        "--refresh-capabilities",
        help="Reload farm capabilities before submitting.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Configuration profile providing render optimisation defaults.",
    ),
    optimize: bool = typer.Option(
        True,
        "--optimize/--no-optimize",
        help="Derive priority and chunk size from heuristics when possible.",
    ),
    farm_queue_depth: int | None = typer.Option(
        None,
        "--farm-queue-depth",
        help="Recent farm queue depth used for optimisation heuristics.",
    ),
    farm_average_frame_ms: float | None = typer.Option(
        None,
        "--farm-average-frame-ms",
        help="Average frame time in milliseconds used for optimisation heuristics.",
    ),
) -> None:
    """Submit a render job to the configured farm."""

    resolved_user = user or getpass.getuser()
    farm = farm.lower()
    dcc = dcc.lower()

    if refresh_capabilities:
        _refresh_capabilities_cache(farm=farm)

    if not scene.exists():
        raise OnePieceValidationError(f"Scene file '{scene}' does not exist (--scene).")
    if not scene.is_file():
        raise OnePieceValidationError(f"Scene path '{scene}' is not a file (--scene).")

    if not output.exists():
        raise OnePieceValidationError(
            f"Output directory '{output}' does not exist (--output)."
        )
    if not output.is_dir():
        raise OnePieceValidationError(
            f"Output path '{output}' is not a directory (--output)."
        )

    frame_count = _parse_frame_count(frames)
    metrics, metric_sources = _resolve_metrics(
        optimize=optimize,
        profile_name=profile,
        queue_depth=farm_queue_depth,
        average_frame_ms=farm_average_frame_ms,
    )

    (
        resolved_priority,
        resolved_chunk,
        capabilities,
        optimisation_summary,
    ) = _resolve_priority_and_chunk_size(
        farm=farm,
        priority=priority,
        chunk_size=chunk_size,
        frame_count=frame_count,
        optimize=optimize,
        metrics=metrics,
    )

    if optimisation_summary is None and optimize:
        skip_reasons: list[str] = []
        if frame_count is None or frame_count <= 0:
            skip_reasons.append("frame count unavailable")
        if priority is not None:
            skip_reasons.append("priority manually specified")
        if chunk_size is not None:
            skip_reasons.append("chunk size manually specified")
        if chunk_size is None and not capabilities.get("chunk_size_enabled", False):
            skip_reasons.append("chunk sizing unsupported")
        optimisation_summary = SubmissionOptimizationDecision(
            priority=resolved_priority,
            chunk_size=resolved_chunk,
            reasons=tuple(skip_reasons),
            applied=False,
        )

    metrics_source = ", ".join(metric_sources) if metric_sources else "none"
    if optimisation_summary is not None:
        log.info(
            "render.submit.optimized",
            applied=optimisation_summary.applied,
            frame_count=frame_count,
            priority=resolved_priority,
            recommended_priority=optimisation_summary.priority,
            chunk_size=resolved_chunk,
            recommended_chunk_size=optimisation_summary.chunk_size,
            reasons=optimisation_summary.reasons,
            metrics_source=metrics_source,
        )
        if optimisation_summary.applied:
            reason_text = (
                "; ".join(optimisation_summary.reasons) or "heuristics applied"
            )
            chunk_display = (
                str(resolved_chunk) if resolved_chunk is not None else "disabled"
            )
            typer.secho(
                f"Optimised submission ({metrics_source}): priority={resolved_priority}, chunk_size={chunk_display} ({reason_text}).",
                fg=typer.colors.CYAN,
            )

    log.info(
        "render.submit.start",
        dcc=dcc,
        scene=str(scene),
        frames=frames,
        output=str(output),
        farm=farm,
        priority=resolved_priority,
        chunk_size=resolved_chunk,
        user=resolved_user,
        capabilities=capabilities,
    )

    adapter: RenderAdapter = _get_adapter(farm)

    try:
        result = adapter(
            scene=str(scene),
            frames=frames,
            output=str(output),
            dcc=dcc,
            priority=resolved_priority,
            user=resolved_user,
            chunk_size=resolved_chunk,
        )
    except RenderAdapterNotImplementedError as exc:
        log.warning(
            "render.submit.not_implemented",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            hint=exc.hint,
        )
        typer.secho(
            f"Render adapter response: {exc}",
            fg=typer.colors.YELLOW,
        )
        if exc.hint:
            typer.secho(exc.hint, fg=typer.colors.YELLOW)
        return
    except RenderSubmissionError as exc:
        log.error(
            "render.submit.failed",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            error=str(exc),
        )
        raise OnePieceExternalServiceError(f"Render submission failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive programming
        log.exception(
            "render.submit.error",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
        )
        raise OnePieceRuntimeError(
            "Render submission failed due to an unexpected error."
        ) from exc

    job_id = result.get("job_id", "")
    status = result.get("status", "unknown")
    farm_type = result.get("farm_type", farm)

    message = result.get("message")

    log.info(
        "render.submit.success",
        dcc=dcc,
        farm=farm_type,
        scene=str(scene),
        frames=frames,
        job_id=job_id,
        status=status,
        user=resolved_user,
        message=message,
        chunk_size=resolved_chunk,
    )

    if status == "not_implemented":
        detail = message or f"{farm_type.title()} adapter is not implemented yet."
        typer.secho(f"Render adapter response: {detail}", fg=typer.colors.YELLOW)
        return

    typer.secho(
        f"Submitted {dcc} scene '{scene}' to {farm_type} with job ID {job_id} (status: {status}).",
        fg=typer.colors.GREEN,
    )

    if message:
        typer.secho(message, fg=typer.colors.GREEN)


@presets_app.command("list")
def list_presets() -> None:
    """List available render submission presets."""

    presets = _list_presets()
    if not presets:
        typer.secho("No render presets found.", fg=typer.colors.YELLOW)
        return

    for name, data in presets:
        farm = data.get("farm", "?")
        dcc = data.get("dcc", "?")
        frames = data.get("frames", "?")
        summary_parts = [f"farm={farm}"]
        if dcc != "?":
            summary_parts.append(f"dcc={dcc}")
        if frames != "?":
            summary_parts.append(f"frames={frames}")
        chunk = data.get("chunk_size")
        if chunk is not None:
            summary_parts.append(f"chunk={chunk}")
        typer.echo(f"{name}: {', '.join(summary_parts)}")


@presets_app.command("save")
def save_preset(
    name: str = typer.Argument(..., help="Name used to identify the preset."),
    *,
    farm: str = typer.Option(
        ...,
        "--farm",
        help="Render farm targeted by this preset.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    dcc: str | None = typer.Option(
        None,
        "--dcc",
        help="DCC associated with the preset (defaults to prompting during use).",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    scene: Path | None = typer.Option(None, "--scene", help="Default scene file path."),
    frames: str | None = typer.Option(None, "--frames", help="Default frame range."),
    output: Path | None = typer.Option(
        None, "--output", help="Default output directory."
    ),
    priority: int | None = typer.Option(
        None,
        "--priority",
        help="Override the adapter priority default for this preset.",
    ),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        help="Override the adapter chunk size default for this preset.",
    ),
    user: str | None = typer.Option(None, "--user", help="Default submitting user."),
    refresh_capabilities: bool = typer.Option(
        False,
        "--refresh-capabilities",
        help="Reload farm capabilities before validating the preset.",
    ),
) -> None:
    """Persist a render submission preset to disk."""

    farm = farm.lower()
    resolved_dcc = dcc.lower() if dcc else None

    if refresh_capabilities:
        _refresh_capabilities_cache(farm=farm)

    explicit_priority = priority is not None
    explicit_chunk = chunk_size is not None

    try:
        (
            resolved_priority,
            resolved_chunk,
            _,
            _,
        ) = _resolve_priority_and_chunk_size(
            farm=farm,
            priority=priority,
            chunk_size=chunk_size,
            optimize=False,
        )
    except OnePieceExternalServiceError as exc:
        if explicit_priority or explicit_chunk:
            raise
        log.warning(
            "render.presets.capabilities_unavailable",
            farm=farm,
            error=str(exc),
        )
        resolved_priority = None
        resolved_chunk = None

    payload: dict[str, Any] = {"farm": farm}
    if resolved_priority is not None:
        payload["priority"] = resolved_priority
    if resolved_chunk is not None:
        payload["chunk_size"] = resolved_chunk
    if resolved_dcc:
        payload["dcc"] = resolved_dcc
    if scene:
        payload["scene"] = str(scene)
    if frames:
        payload["frames"] = frames
    if output:
        payload["output"] = str(output)
    if user:
        payload["user"] = user

    path = _save_preset(name, payload)
    typer.secho(f"Saved preset '{name}' to {path}.", fg=typer.colors.GREEN)


@presets_app.command("use")
def use_preset(
    name: str = typer.Argument(..., help="Name of the preset to execute."),
    *,
    scene: Path | None = typer.Option(None, "--scene", help="Override the scene file."),
    frames: str | None = typer.Option(
        None, "--frames", help="Override the frame range."
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Override the output directory."
    ),
    farm: str | None = typer.Option(
        None,
        "--farm",
        help="Override the preset farm.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    dcc: str | None = typer.Option(
        None,
        "--dcc",
        help="Override the preset DCC.",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    priority: int | None = typer.Option(
        None, "--priority", help="Override the preset priority."
    ),
    chunk_size: int | None = typer.Option(
        None, "--chunk-size", help="Override the preset chunk size."
    ),
    user: str | None = typer.Option(
        None, "--user", help="Override the submitting user."
    ),
    refresh_capabilities: bool = typer.Option(
        False,
        "--refresh-capabilities",
        help="Reload farm capabilities before executing the preset.",
    ),
) -> None:
    """Execute a preset, optionally overriding fields before submission."""

    preset = _load_preset(name)

    merged: dict[str, Any] = dict(preset)

    overrides: dict[str, Any] = {}
    if scene is not None:
        overrides["scene"] = str(scene)
    if frames is not None:
        overrides["frames"] = frames
    if output is not None:
        overrides["output"] = str(output)
    if farm is not None:
        overrides["farm"] = farm.lower()
    if dcc is not None:
        overrides["dcc"] = dcc.lower()
    if priority is not None:
        overrides["priority"] = priority
    if chunk_size is not None:
        overrides["chunk_size"] = chunk_size
    if user is not None:
        overrides["user"] = user

    merged.update(overrides)

    required_fields = {
        "farm": "--farm",
        "dcc": "--dcc",
        "scene": "--scene",
        "output": "--output",
    }
    missing = [hint for field, hint in required_fields.items() if not merged.get(field)]
    if missing:
        raise OnePieceValidationError(
            "Preset is missing required fields. Provide overrides for: "
            + ", ".join(missing)
        )

    typer.secho(f"Using preset '{name}'.", fg=typer.colors.BLUE)

    submit(
        dcc=str(merged["dcc"]),
        scene=Path(str(merged["scene"])),
        frames=str(merged.get("frames", frames or "1-100")),
        output=Path(str(merged["output"])),
        farm=str(merged["farm"]),
        priority=merged.get("priority"),
        chunk_size=merged.get("chunk_size"),
        user=merged.get("user"),
        refresh_capabilities=refresh_capabilities,
    )


@app.command("status")
def render_status(
    job_id: str = typer.Argument(..., help="Identifier returned by the render farm."),
    farm: str | None = typer.Option(
        None,
        "--farm",
        help="Optional farm filter when job identifiers overlap between adapters.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Configuration profile providing Trafalgar render settings.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Output the raw JSON payload for scripting integrations.",
    ),
) -> None:
    """Fetch render job metadata from the Trafalgar render API."""

    try:
        client = RenderJobClient(profile=profile)
    except OnePieceConfigError as exc:
        raise OnePieceValidationError(str(exc)) from exc
    except RenderJobClientError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc

    with client:
        try:
            job = client.get_job(job_id, farm=farm)
        except RenderJobClientError as exc:
            if exc.status_code == 404:
                raise OnePieceExternalServiceError(
                    f"Render job '{job_id}' was not found."
                ) from exc
            raise OnePieceExternalServiceError(str(exc)) from exc

    if raw:
        typer.echo(json.dumps(job, indent=2, sort_keys=True))
        return

    typer.secho(f"Render job {job.get('job_id', job_id)}", fg=typer.colors.CYAN)
    farm_value = job.get("farm") or farm or "<unknown>"
    farm_type = job.get("farm_type") or "<unknown>"
    typer.echo(f"Farm: {farm_value} ({farm_type})")
    typer.echo(f"Status: {job.get('status', '<unknown>')}")
    message = job.get("message")
    if isinstance(message, str) and message:
        typer.echo(f"Message: {message}")

    history = _extract_history(job)
    if history:
        typer.echo("History:")
        for entry in history:
            typer.echo(f"  - {entry}")
    else:
        typer.echo("History: <not available>")


@app.command("cancel")
def cancel_render_job(
    job_id: str = typer.Argument(
        ..., help="Identifier returned by the render farm."
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Configuration profile providing Trafalgar render settings.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Ignore cancellation unsupported warnings returned by the adapter.",
    ),
) -> None:
    """Request cancellation of an in-flight render job via Trafalgar."""

    log.info(
        "render.cancel.start",
        job_id=job_id,
        profile=profile,
        force=force,
    )

    try:
        client = RenderJobClient(profile=profile)
    except OnePieceConfigError as exc:
        raise OnePieceValidationError(str(exc)) from exc
    except RenderJobClientError as exc:
        log.error(
            "render.cancel.client_error",
            job_id=job_id,
            error=str(exc),
            code=exc.code,
            status=exc.status_code,
        )
        raise OnePieceExternalServiceError(str(exc)) from exc

    with client:
        try:
            result = client.cancel_job(job_id)
        except RenderJobClientError as exc:
            if exc.code == "render.cancellation_unsupported" and force:
                log.warning(
                    "render.cancel.unsupported",
                    job_id=job_id,
                    code=exc.code,
                    hint=exc.hint,
                    status=exc.status_code,
                    force=True,
                )
                message = exc.message or "Render farm does not support job cancellation."
                typer.secho(
                    f"{message} (ignored due to --force).",
                    fg=typer.colors.YELLOW,
                )
                if exc.hint:
                    typer.secho(f"Hint: {exc.hint}", fg=typer.colors.YELLOW)
                return

            log.error(
                "render.cancel.failed",
                job_id=job_id,
                code=exc.code,
                status=exc.status_code,
                hint=exc.hint,
                force=force,
            )
            error_message = f"Render cancellation failed: {exc.message}"
            if exc.hint:
                error_message = f"{error_message} Hint: {exc.hint}"
            raise OnePieceExternalServiceError(error_message) from exc

    job_label = _coerce_text(result.get("job_id") or job_id)
    status = _coerce_text(result.get("status")) or "<unknown>"
    farm_type = _coerce_text(result.get("farm_type")) or "<unknown>"
    message = result.get("message")
    log.info(
        "render.cancel.success",
        job_id=job_label,
        status=status,
        farm_type=farm_type,
        message=message if isinstance(message, str) else None,
    )

    typer.secho(
        f"Cancellation status for {job_label}: {status}",
        fg=typer.colors.GREEN,
    )
    if farm_type:
        typer.echo(f"Adapter: {farm_type}")
    if isinstance(message, str) and message.strip():
        typer.secho(f"Message: {message.strip()}", fg=typer.colors.GREEN)


def _extract_history(job: Mapping[str, Any]) -> list[str]:
    history: list[str] = []
    raw_history = job.get("history") or job.get("status_history")
    if isinstance(raw_history, list):
        for entry in raw_history:
            if isinstance(entry, Mapping):
                status = _coerce_text(entry.get("status") or entry.get("state"))
                timestamp = _coerce_text(entry.get("timestamp") or entry.get("time"))
                if status and timestamp:
                    history.append(f"{status} at {timestamp}")
                elif status:
                    history.append(status)
                elif timestamp:
                    history.append(timestamp)
            elif isinstance(entry, (list, tuple)):
                parts = [part for part in entry if _coerce_text(part)]
                if parts:
                    history.append(" at ".join(_coerce_text(part) for part in parts))
            else:
                text = _coerce_text(entry)
                if text:
                    history.append(text)
    return history


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
