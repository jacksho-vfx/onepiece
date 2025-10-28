"""Typer application for interacting with the pipeline orchestrator."""

from __future__ import annotations

import typer


app = typer.Typer(
    name="pipeline",
    help="Interact with the OnePiece pipeline orchestrator.",
)


def _orchestrator_placeholder(action: str) -> None:
    """Display guidance for orchestrator-bound commands."""

    typer.echo(
        "Pipeline orchestrator integration is coming soon. "
        f"Hook the `{action}` command into the orchestrator service when it is available."
    )


@app.command("list")
def list_pipelines() -> None:
    """List pipelines exposed by the orchestrator."""

    _orchestrator_placeholder("list")


@app.command("describe")
def describe_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier.")
) -> None:
    """Describe a specific pipeline."""

    _orchestrator_placeholder(f"describe {name}")


@app.command("run")
def run_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    *,
    parameters: list[str] | None = typer.Option(
        None,
        "--param",
        "-p",
        help="Key=value parameters forwarded to the orchestrator.",
    ),
) -> None:
    """Trigger a pipeline execution."""

    details = " with parameters " + ", ".join(parameters) if parameters else ""
    _orchestrator_placeholder(f"run {name}{details}")


__all__ = ["app"]
