"""Render submission command implementation."""

from __future__ import annotations

import getpass
from pathlib import Path

import click
import structlog
import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceRuntimeError,
)
from libraries.automation.render.base import (
    RenderAdapterNotImplementedError,
    RenderSubmissionError,
)
from libraries.automation.render.models import RenderAdapter
from libraries.automation.render.optimization import SubmissionOptimizationDecision

from .helpers import (
    DCC_CHOICES,
    FARM_CHOICES,
    RenderCliModuleResolver,
    get_adapter,
    parse_frame_count,
    refresh_capabilities_cache,
    resolve_metrics,
    resolve_priority_and_chunk_size,
    validate_scene_and_output,
)

_resolver = RenderCliModuleResolver()
_default_log = structlog.get_logger(__name__)
log = _resolver.resolve_logger(_default_log)


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
    logger = _resolver.resolve_logger(_default_log)
    farm = farm.lower()
    dcc = dcc.lower()

    if refresh_capabilities:
        refresh_capabilities_cache(farm=farm)

    validate_scene_and_output(scene, output)

    frame_count = parse_frame_count(frames)
    metrics, metric_sources = resolve_metrics(
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
    ) = resolve_priority_and_chunk_size(
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
        logger.info(
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
                f"Optimised submission ({metrics_source}): priority={resolved_priority}, "
                f"chunk_size={chunk_display} ({reason_text}).",
                fg=typer.colors.CYAN,
            )

    logger.info(
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

    adapter: RenderAdapter = get_adapter(farm)

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
        logger.warning(
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
        logger.error(
            "render.submit.failed",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            error=str(exc),
        )
        raise OnePieceExternalServiceError(f"Render submission failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive programming
        logger.exception(
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

    logger.info(
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


__all__ = ["submit"]
