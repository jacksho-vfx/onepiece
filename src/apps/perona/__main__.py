"""Console entry point for the Perona dashboard."""

from apps.perona.app import app


def main() -> None:
    """Invoke the Perona Typer application."""

    app()


if __name__ == "__main__":
    main()
