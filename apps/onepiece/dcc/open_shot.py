from pathlib import Path
from typing import List, Optional

import typer
import structlog

from onepiece.validations.dcc import validate_dcc, detect_dcc_from_file, SupportedDCC

@app.command("open-shot")
def open_shot(
    shot_path: Path = typer.Option(..., "--shot", "-s", exists=True, file_okay=True, help="Path to the shot scene file"),
    dcc: str = typer.Option(None, "--dcc", "-d", help="Optional DCC name. If omitted, auto-detect from file extension")
):
    """
    Open a shot in the specified DCC, or auto-detect DCC from file extension.
    """
    try:
        if dcc:
            dcc_enum: SupportedDCC = validate_dcc(dcc)
        else:
            dcc_enum: SupportedDCC = detect_dcc_from_file(shot_path)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)

    dcc_module = DCC_MODULES[dcc_enum.value]

    try:
        dcc_module.open_scene(str(shot_path))
        typer.echo(f"Successfully opened {shot_path} in {dcc_enum.value}")
    except Exception as e:
        log.error("failed_open_shot", dcc=dcc_enum.value, shot=str(shot_path), error=str(e))
        typer.echo(f"Failed to open shot: {e}", err=True)
        raise typer.Exit(code=1)

