"""Console entry point for the Trafalgar CLI application."""

from apps.trafalgar.app import app


def main() -> None:
    """Invoke the Trafalgar Typer application."""

    app()


if __name__ == "__main__":
    main()
