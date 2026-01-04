"""Deadline-specific CLI focused on geometry optimisation before submission."""

from __future__ import annotations

import getpass
from pathlib import Path
import sys
from typing import Any

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

from .helpers import DCC_CHOICES, parse_frame_count

_log = structlog.get_logger(__name__)
log = _log


def _get_logger() -> Any:
    module = sys.modules.get("apps.onepiece.render.submit")
    if module is not None and hasattr(module, "log"):
        return getattr(module, "log")
    return _log


def _validate_scene(scene: Path, output: Path) -> None:
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


def _optimise_scene(scene: Path, workspace: Path | None) -> GeometryOptimizationResult:
    try:
        return optimize_geometry(scene, output_dir=workspace)
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise OnePieceValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        log = _get_logger()
        log.exception("render.deadline.optimize_failed", scene=str(scene))
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

    logger = _get_logger()
    dcc = dcc.lower()
    resolved_user = user or getpass.getuser()
    _validate_scene(scene, output)

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
        result = submit_job(
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
