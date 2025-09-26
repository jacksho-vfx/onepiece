"""CLI command to open a scene file in the appropriate DCC."""

from pathlib import Path

import structlog
import typer

from libraries.dcc.dcc_client import SupportedDCC, open_scene
from libraries.validations.dcc import detect_dcc_from_file, validate_dcc


log = structlog.get_logger(__name__)
app = typer.Typer(help="Open scenes in a supported DCC application.")


def _resolve_dcc(shot_path: Path, dcc: str | None) -> SupportedDCC:
    """Return the :class:`SupportedDCC` for ``shot_path``.

    The caller may provide a ``dcc`` name explicitly.  When omitted the value is
    inferred from the file extension which keeps the command convenient for
    day-to-day usage.
    """

    try:
        return validate_dcc(dcc) if dcc else detect_dcc_from_file(shot_path)
    except ValueError as exc:  # pragma: no cover - exercised via the CLI.
        raise typer.BadParameter(str(exc)) from exc


@app.command("open-shot")
def open_shot(
    shot_path: Path = typer.Option(
        ...,
        "--shot",
        "-s",
        exists=True,
        file_okay=True,
        help="Path to the shot scene file",
    ),
    dcc: str | None = typer.Option(
        None,
        "--dcc",
        "-d",
        help="Optional DCC name. If omitted, the value is inferred from the file extension.",
    ),
) -> None:
    """Open ``shot_path`` with the requested DCC application."""

    dcc_enum = _resolve_dcc(shot_path, dcc)

    try:
        open_scene(dcc_enum, shot_path)
        typer.echo(f"Successfully opened {shot_path} in {dcc_enum.value}")
    except Exception as exc:  # pragma: no cover - surfaced to the CLI.
        log.error(
            "failed_open_shot",
            dcc=dcc_enum.value,
            shot=str(shot_path),
            error=str(exc),
        )
        typer.echo(f"Failed to open shot: {exc}", err=True)
        raise typer.Exit(code=1) from exc
