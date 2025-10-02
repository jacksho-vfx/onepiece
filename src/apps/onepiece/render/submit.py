"""Render submission CLI command."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Callable, Final

import click
import structlog
import typer

from libraries.render import deadline, mock, opencue, tractor
from libraries.render.base import RenderSubmissionError, SubmissionResult

log = structlog.get_logger(__name__)

app = typer.Typer(name="render", help="Render farm submission commands.")

DCC_CHOICES: Final[tuple[str, ...]] = ("maya", "nuke", "houdini", "blender", "max")
FARM_CHOICES: Final[tuple[str, ...]] = ("deadline", "tractor", "opencue", "mock")

SubmitFunc = Callable[[str, str, str, str, int, str], SubmissionResult]

FARM_ADAPTERS: Final[dict[str, SubmitFunc]] = {
    "deadline": deadline.submit_job,
    "tractor": tractor.submit_job,
    "opencue": opencue.submit_job,
    "mock": mock.submit_job,
}


def _get_adapter(farm: str) -> SubmitFunc:
    adapter = FARM_ADAPTERS.get(farm)
    if adapter is None:
        raise RenderSubmissionError(f"Unknown render farm '{farm}'.")
    return adapter


@app.command("submit")
def submit(
    *,
    dcc: str = typer.Option(
        ..., "--dcc", help="Which DCC generated the render.",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    scene: Path = typer.Option(..., "--scene", help="Path to the scene file to render."),
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
    priority: int = typer.Option(50, "--priority", help="Render job priority."),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Submitting user (defaults to the current system user).",
    ),
) -> None:
    """Submit a render job to the configured farm."""

    resolved_user = user or getpass.getuser()
    farm = farm.lower()
    dcc = dcc.lower()

    log.info(
        "render.submit.start",
        dcc=dcc,
        scene=str(scene),
        frames=frames,
        output=str(output),
        farm=farm,
        priority=priority,
        user=resolved_user,
    )

    adapter = _get_adapter(farm)

    try:
        result = adapter(
            scene=str(scene),
            frames=frames,
            output=str(output),
            dcc=dcc,
            priority=priority,
            user=resolved_user,
        )
    except RenderSubmissionError as exc:
        log.error(
            "render.submit.failed",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            error=str(exc),
        )
        typer.secho(f"Render submission failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # pragma: no cover - defensive programming
        log.exception(
            "render.submit.error",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
        )
        typer.secho(
            f"Render submission failed due to an unexpected error: {exc}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    job_id = result.get("job_id", "")
    status = result.get("status", "unknown")
    farm_type = result.get("farm_type", farm)

    log.info(
        "render.submit.success",
        dcc=dcc,
        farm=farm_type,
        scene=str(scene),
        frames=frames,
        job_id=job_id,
        status=status,
        user=resolved_user,
    )

    typer.secho(
        f"Submitted {dcc} scene '{scene}' to {farm_type} with job ID {job_id} (status: {status}).",
        fg=typer.colors.GREEN,
    )
