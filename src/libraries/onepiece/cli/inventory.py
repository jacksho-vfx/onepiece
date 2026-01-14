"""Inventory CLI commands for pipeline ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from libraries.pipeline.ingest.inventory import (
    load_asset_record,
    rebuild_index,
    search_by_name,
    search_by_tag,
)


app = typer.Typer(name="inventory", help="Search the pipeline ingest inventory.")


def _resolve_project_root(project_root: Path) -> Path:
    return project_root.expanduser().resolve()


@app.command("search")
def inventory_search(
    tag: Optional[str] = typer.Option(None, "--tag", help="Tag to match."),
    name: Optional[str] = typer.Option(
        None, "--name", help="Partial payload name to match."
    ),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    results = []
    if tag:
        results.extend(search_by_tag(project_root, tag))
    if name:
        results.extend(search_by_name(project_root, name))
    if not tag and not name:
        raise typer.BadParameter("Provide --tag or --name to search.")
    for entry in results:
        typer.echo(f"{entry.asset_id} {entry.payload_name} tags={','.join(entry.tags)}")


@app.command("show")
def inventory_show(
    asset_id: str = typer.Argument(..., help="Asset ID to inspect."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    record = load_asset_record(project_root, asset_id)
    typer.echo(f"asset_id={record.asset_id}")
    typer.echo(f"payload={record.payload_name}")
    typer.echo(f"source={record.source_uri}")
    typer.echo(f"hash={record.payload_hash}")
    typer.echo(f"size_bytes={record.payload_size_bytes}")
    typer.echo(f"tags={', '.join(record.tags)}")
    typer.echo(f"file_types={', '.join(record.file_types)}")
    typer.echo("links=")
    for link in record.links:
        typer.echo(f"  - {link.get('destination')} -> {link.get('source')}")


@app.command("rebuild")
def inventory_rebuild(
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    rebuild_index(project_root)
    typer.echo("Inventory index rebuilt.")
