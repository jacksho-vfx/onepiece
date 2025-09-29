"""Console entry point for the OnePiece CLI application."""

from apps.onepiece.app import app


def main() -> None:
    """Invoke the root Typer application."""

    app()


if __name__ == "__main__":
    main()
