"""Console entry point for the tester demo launcher."""

from apps.tester.app import app


def main() -> None:
    """Invoke the Typer application."""

    app()


if __name__ == "__main__":
    main()
