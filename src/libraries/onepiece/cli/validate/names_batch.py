import typer
from pathlib import Path
import structlog

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.platform.validations.naming_batch import (
    NameValidationResult,
    validate_names_in_csv,
    validate_names_in_dir,
)

log = structlog.get_logger(__name__)
app = typer.Typer(help="Validate names in batch.")


@app.command("names-batch")
def names_batch(
    csv: Path = typer.Option(
        None,
        "--csv",
        "-c",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="CSV with a 'name' column.",
    ),
    directory: Path = typer.Option(
        None,
        "--dir",
        "-d",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Directory of files to validate.",
    ),
) -> None:
    """
    Validate show/shot/asset names from a CSV or a directory of files.
    """
    if not csv and not directory:
        raise OnePieceValidationError(
            "Provide either --csv with a 'name' column or --dir to validate filenames."
        )

    if csv:
        try:
            results = validate_names_in_csv(csv)
        except (FileNotFoundError, ValueError, PermissionError) as exc:
            raise OnePieceValidationError(str(exc)) from exc
        typer.secho(
            f"Validated {len(results)} names from CSV {csv}", fg=typer.colors.CYAN
        )
    else:
        try:
            results = validate_names_in_dir(directory)
        except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
            raise OnePieceValidationError(str(exc)) from exc
        typer.secho(
            f"Validated {len(results)} filenames in directory {directory}",
            fg=typer.colors.CYAN,
        )

    invalid = [result for result in results if not result.valid]
    for result in results:
        _render_result(result)

    if invalid:
        log.warning(
            "validate.names_batch.invalid",
            invalid=[result.name for result in invalid],
            count=len(invalid),
        )
        raise OnePieceValidationError(
            f"{len(invalid)} invalid name(s) found. Review the details above."
        )

    typer.secho("\nAll names are valid.", fg=typer.colors.GREEN)
    log.info("validate.names_batch.success", count=len(results))


def _render_result(result: NameValidationResult) -> None:
    colour = typer.colors.GREEN if result.valid else typer.colors.RED
    status = "VALID" if result.valid else "INVALID"
    typer.secho(f"- {result.name}", fg=colour)
    typer.echo(f"    status : {status}")
    typer.echo(f"    schema : {result.detail}")
