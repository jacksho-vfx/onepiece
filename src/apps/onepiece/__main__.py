"""Console entry point for the OnePiece CLI application."""

from __future__ import annotations

import sys
from typing import Sequence

import typer

from apps.onepiece.app import app
from apps.onepiece.utils.errors import ExitCode, OnePieceError


def _handle_cli_error(exc: OnePieceError) -> ExitCode:
    """Render a user friendly error message and return the exit code."""

    typer.secho(f"{exc.heading}: {exc}", fg=typer.colors.RED, err=True)
    return exc.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """Invoke the root Typer application."""

    try:
        result = app(
            args=list(argv) if argv is not None else None,
            standalone_mode=False,
        )
        if result is None:
            return int(ExitCode.SUCCESS)
        if isinstance(result, ExitCode):
            return int(result)
        return int(result)
    except OnePieceError as exc:
        exit_code = _handle_cli_error(exc)
        return int(exit_code)


if __name__ == "__main__":
    sys.exit(main())
