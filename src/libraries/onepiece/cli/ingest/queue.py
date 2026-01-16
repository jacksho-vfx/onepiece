"""Queue-aware ingest CLI commands."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Optional

import typer

from libraries.pipeline.ingest.executor import execute_queue_item, load_progress
from libraries.pipeline.ingest.payload import build_payload_manifest
from libraries.pipeline.ingest.queue import (
    add_queue_item,
    create_session,
    iter_session_items,
    load_queue_item,
    load_session,
    save_queue_item,
    save_session,
)
from libraries.pipeline.ingest.rules import (
    build_link_destination,
    load_ingest_rules,
    plan_ingest,
)
from libraries.pipeline.ingest.tagging import (
    infer_tags,
    load_tag_vocabulary,
    validate_tags,
)

app = typer.Typer(help="Queue and manage pipeline ingest sessions.")


def _resolve_project_root(project_root: Path) -> Path:
    return project_root.expanduser().resolve()


@app.command("add")
def ingest_add(
    paths: list[Path] = typer.Argument(..., help="Source files or folders to ingest."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    rules: Optional[Path] = typer.Option(
        None, "--rules", help="Path to ingest rules file."
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", help="Path to ingest config (hooks, Deadline)."
    ),
    tag: list[str] = typer.Option(
        None, "--tag", help="Freeform tag to attach. Can be repeated."
    ),
    controlled_tag: list[str] = typer.Option(
        None, "--controlled-tag", help="Controlled tag to attach. Can be repeated."
    ),
    user: Optional[str] = typer.Option(None, "--user", help="Override session user."),
    host: Optional[str] = typer.Option(None, "--host", help="Override session host."),
) -> None:
    project_root = _resolve_project_root(project_root)
    session = create_session(
        project_root=project_root,
        user=user or (os.getenv("USER") or os.getenv("USERNAME") or "unknown"),
        host=host or platform.node(),
    )
    for path in paths:
        add_queue_item(
            project_root=project_root,
            session=session,
            source=path.expanduser().resolve(),
            tags=tag or [],
            controlled_tags=controlled_tag or [],
            rules_path=rules,
            config_path=config,
        )
    typer.echo(f"Created session {session.session_id} with {len(paths)} item(s)")


@app.command("run")
def ingest_run(
    session_id: str = typer.Option(..., "--session", help="Session ID to run."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume from progress markers."
    ),
    force: bool = typer.Option(False, "--force", help="Force re-run all steps."),
) -> None:
    project_root = _resolve_project_root(project_root)
    session = load_session(project_root, session_id)
    session.status = "running"
    save_session(project_root, session)

    items = iter_session_items(project_root, session)
    summary = {"completed": 0, "failed": 0, "skipped": 0}

    for item in items:
        if item.status in {"cancelled"}:
            summary["skipped"] += 1
            continue
        if resume and item.status == "completed" and not force:
            summary["skipped"] += 1
            continue
        typer.echo(f"item.start id={item.item_id} source={item.source}")
        item.status = "running"
        save_queue_item(project_root, item)
        try:
            result = execute_queue_item(
                item=item,
                project_root=project_root,
                resume=resume,
                force=force,
            )
            item.status = "completed"
            item.error = None
            progress = load_progress(result.asset_dir)
            item.progress = progress
            save_queue_item(project_root, item)
            typer.echo(f"item.complete id={item.item_id} asset_id={result.asset_id}")
            summary["completed"] += 1
        except Exception as exc:  # noqa: BLE001
            item.status = "failed"
            item.error = str(exc)
            save_queue_item(project_root, item)
            typer.echo(f"item.failed id={item.item_id} error={exc}")
            summary["failed"] += 1

    session.status = "failed" if summary["failed"] else "completed"
    save_session(project_root, session)
    typer.echo(
        "session.summary completed={completed} failed={failed} skipped={skipped}".format(
            **summary
        )
    )


@app.command("status")
def ingest_status(
    session_id: str = typer.Option(..., "--session", help="Session ID to inspect."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    session = load_session(project_root, session_id)
    typer.echo(f"Session {session.session_id} status={session.status}")
    for item in iter_session_items(project_root, session):
        typer.echo(f"item id={item.item_id} status={item.status} source={item.source}")


@app.command("cancel")
def ingest_cancel(
    session_id: str = typer.Option(..., "--session", help="Session ID to cancel."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    session = load_session(project_root, session_id)
    items = iter_session_items(project_root, session)
    cancelled = 0
    for item in items:
        if item.status not in {"completed", "failed"}:
            item.status = "cancelled"
            save_queue_item(project_root, item)
            cancelled += 1
    session.status = "cancelled"
    save_session(project_root, session)
    typer.echo(f"Cancelled {cancelled} item(s) in session {session.session_id}")


@app.command("plan")
def ingest_plan(
    source: Path = typer.Argument(..., help="Source file or folder to plan."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    rules: Optional[Path] = typer.Option(
        None, "--rules", help="Path to ingest rules file."
    ),
    tag: list[str] = typer.Option(
        None, "--tag", help="Freeform tag to attach. Can be repeated."
    ),
    controlled_tag: list[str] = typer.Option(
        None, "--controlled-tag", help="Controlled tag to attach. Can be repeated."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    source = source.expanduser().resolve()
    manifest = build_payload_manifest(source)
    tags = infer_tags(
        source,
        manifest=manifest,
        user_tags=tag or [],
        controlled_tags=controlled_tag or [],
    )
    rules_path = rules or (project_root / ".pipeline" / "ingest_rules.yaml")
    ruleset = load_ingest_rules(rules_path)
    tag_set = set(tags.get("freeform", [])) | set(tags.get("controlled", []))
    plan = plan_ingest(
        rules=ruleset,
        tags=tag_set,
        file_types=set(manifest.file_types),
        extensions=manifest.extensions,
        source_path=source.as_posix().lower(),
        payload_size_bytes=manifest.payload_size_bytes,
    )
    planned_asset_id = "<asset-id>"
    typer.echo(f"canonical={project_root / '.pipeline' / 'ingest' / planned_asset_id}")
    typer.echo(f"payload={manifest.payload_name}")
    typer.echo("links=")
    for link in plan.links:
        destination = build_link_destination(
            output=link.output,
            project_root=project_root,
            asset_id=planned_asset_id,
            basename=manifest.payload_name,
            source_uri=source.as_posix(),
            payload_name=manifest.payload_name,
        )
        typer.echo(f"  - {destination}")
    typer.echo(f"hooks={', '.join(plan.hooks) if plan.hooks else 'none'}")
    typer.echo(
        f"deadline={', '.join(plan.deadline_actions) if plan.deadline_actions else 'none'}"
    )
    optimize_actions = (
        [f"{action.variant}:{action.mode}" for action in plan.optimize_actions]
        if plan.optimize_actions
        else []
    )
    typer.echo(
        f"optimize={', '.join(optimize_actions) if optimize_actions else 'none'}"
    )


@app.command("validate")
def ingest_validate(
    session_id: str = typer.Option(..., "--session", help="Session ID to validate."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    session = load_session(project_root, session_id)
    vocabulary = load_tag_vocabulary(project_root)
    has_errors = False
    for item_id in session.item_ids:
        item = load_queue_item(project_root, item_id)
        manifest = build_payload_manifest(Path(item.source))
        tags = infer_tags(
            Path(item.source),
            manifest=manifest,
            user_tags=item.tags,
            controlled_tags=item.controlled_tags,
        )
        validation = validate_tags(tags, vocabulary)
        if validation.is_valid:
            continue
        has_errors = True
        typer.echo(f"item {item.item_id} invalid tags:")
        for error in validation.errors:
            typer.echo(f"  - {error}")
    if not has_errors:
        typer.echo("All tags are valid.")
