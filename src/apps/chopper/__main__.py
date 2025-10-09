"""Console entry point for the Chopper renderer CLI."""

from .app import app


def main() -> None:
    """Invoke the Typer application."""

    app()


if __name__ == "__main__":
    main()
