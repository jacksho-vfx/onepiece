from pathlib import Path

import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.platform.validations.filesystem import preflight_report

app = typer.Typer(help="Validate filepaths")


@app.command("paths")
def validate_paths(
    paths: list[Path] = typer.Argument(
        ..., help="Paths to check for existence, writability, and disk space"
    ),
) -> None:
    """
    Validate filesystem paths and print a report.
    Exits with code 1 if any path fails.
    """
    ok = preflight_report(paths)
    if not ok:
        raise OnePieceValidationError(
            "One or more paths failed the validation checks above."
        )
