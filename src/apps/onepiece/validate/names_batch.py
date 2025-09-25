import typer
from pathlib import Path
import structlog
from src.libraries.validations.naming_batch import (
    validate_names_in_csv,
    validate_names_in_dir,
)

log = structlog.get_logger(__name__)
app = typer.Typer(help="Validatie names in batch.")


@app.command("names-batch")
def names_batch(
    csv: Path = typer.Option(None, "--csv", "-c", help="CSV with a 'name' column."),
    directory: Path = typer.Option(
        None, "--dir", "-d", help="Directory of files to validate."
    ),
) -> None:
    """
    Validate show/shot/asset names from a CSV or a directory of files.
    """
    if not csv and not directory:
        typer.echo("Provide either --csv or --dir", err=True)
        raise typer.Exit(code=1)

    if csv:
        results = validate_names_in_csv(csv)
        typer.echo(f"Validated {len(results)} names from CSV {csv}")
    else:
        results = validate_names_in_dir(directory)
        typer.echo(f"Validated {len(results)} filenames in directory {directory}")

    invalid = [r for r in results if not r[1]]
    for name, valid, reason in results:
        status = "OK" if valid else f"FAIL ({reason})"
        typer.echo(f"{name}: {status}")

    if invalid:
        typer.echo(f"\n{len(invalid)} invalid name(s) found.", err=True)
        raise typer.Exit(code=1)
    else:
        typer.echo("\nAll names are valid.")
