"""Console entry point for running OnePiece as a module."""

from __future__ import annotations

from apps.onepiece.app import app


def main() -> None:
    """Invoke the root Typer application."""

    app()


if __name__ == "__main__":
    main()
