"""Deadline-specific CLI focused on geometry optimisation before submission."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import TypeVar, cast

import click
import structlog
import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceRuntimeError,
    OnePieceValidationError,
)
from libraries.automation.render.base import (
    RenderAdapterConfigurationError,
    RenderAdapterError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
)
from libraries.automation.render.deadline import submit_job
from libraries.automation.render.geometry import (
    GeometryOptimizationResult,
    optimize_geometry,
)

from .helpers import (
    DCC_CHOICES,
    RenderCliModuleResolver,
    parse_frame_count,
    validate_scene_and_output,
)

_resolver = RenderCliModuleResolver()
log = _resolver.resolve_logger(structlog.get_logger(__name__))
T = TypeVar("T")


def _resolve_override(name: str, default: T) -> T:
    from apps.onepiece.render.submit import optimize_deadline_command as command_module

    override = getattr(command_module, name, None)
    if override is not None and override is not default:
        return cast(T, override)
    return default


def _optimise_scene(scene: Path, workspace: Path | None) -> GeometryOptimizationResult:
    try:
        return _resolve_override("optimize_geometry", optimize_geometry)(
            scene, output_dir=workspace
        )
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise OnePieceValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger = _resolver.resolve_logger(log)
        logger.exception("render.deadline.optimize_failed", scene=str(scene))
        raise OnePieceRuntimeError("Geometry optimisation failed.") from exc


def optimize_and_submit_deadline(
    *,
    dcc: str = typer.Option(
        "maya",
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
    priority: int = typer.Option(50, "--priority", help="Render job priority."),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        help="Frames per chunk to dispatch when supported by Deadline.",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Submitting user (defaults to the current system user).",
    ),
    pool: str | None = typer.Option(None, "--pool", help="Deadline pool override."),
    optimized_dir: Path | None = typer.Option(
        None,
        "--optimized-dir",
        help="Directory to store the optimised scene before submission.",
    ),
) -> None:
    """Optimise geometry then submit a Deadline render job."""

    logger = _resolver.resolve_logger(log)
    dcc = dcc.lower()
    resolved_user = user or getpass.getuser()
    validate_scene_and_output(scene, output)

    if parse_frame_count(frames) is None:
        raise OnePieceValidationError(f"Frame range '{frames}' is invalid (--frames).")

    optimisation = _optimise_scene(scene, optimized_dir)

    logger.info(
        "render.deadline.optimized",
        scene=str(scene),
        optimized_scene=str(optimisation.optimized_scene),
        bytes_saved=optimisation.bytes_saved,
        reduction_percent=optimisation.reduction_percent,
        operations=optimisation.operations,
    )
    summary = (
        f"Optimised geometry copy at {optimisation.optimized_scene} "
        f"({optimisation.reduction_percent}% smaller)."
    )
    typer.secho(summary, fg=typer.colors.CYAN)

    try:
        result = _resolve_override("submit_job", submit_job)(
            scene=str(optimisation.optimized_scene),
            frames=frames,
            output=str(output),
            dcc=dcc,
            priority=priority,
            user=resolved_user,
            chunk_size=chunk_size,
            pool=pool,
        )
    except RenderAdapterConfigurationError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc
    except RenderAdapterJobRejectedError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc
    except RenderAdapterUnavailableError as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc
    except RenderAdapterError as exc:
        raise OnePieceExternalServiceError("Deadline rejected the submission.") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("render.deadline.submit_failed", scene=str(scene))
        raise OnePieceRuntimeError("Deadline submission failed.") from exc

    message = result.get("message", "")
    job_id = result.get("job_id", "unknown")
    status = result.get("status", "submitted")

    logger.info(
        "render.deadline.submitted",
        dcc=dcc,
        scene=str(scene),
        frames=frames,
        job_id=job_id,
        status=status,
        user=resolved_user,
        message=message,
        chunk_size=chunk_size,
        pool=pool,
    )

    typer.secho(
        f"Submitted optimised {dcc} scene to Deadline with job ID {job_id} (status: {status}).",
        fg=typer.colors.GREEN,
    )
    if message:
        typer.secho(message, fg=typer.colors.GREEN)


__all__ = ["optimize_and_submit_deadline"]
