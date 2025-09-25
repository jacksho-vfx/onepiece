from pathlib import Path
import typer
from onepiece.validations.filesystem import preflight_report

app = typer.Typer(help="Validate filepaths")


@app.command("paths")
def validate_paths(
    paths: list[Path] = typer.Argument(
        ..., help="Paths to check for existence, writability, and disk space"
    )
):
    """
    Validate filesystem paths and print a report.
    Exits with code 1 if any path fails.
    """
    ok = preflight_report(paths)
    if not ok:
        raise typer.Exit(code=1)
