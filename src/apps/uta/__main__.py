"""Console entry point for the Uta GUI launcher."""

from apps.uta.app import app


def main() -> None:
    """Invoke the Typer application."""

    app()


if __name__ == "__main__":
    main()
