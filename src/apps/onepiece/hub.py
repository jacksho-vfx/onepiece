"""Guided pipeline + render hub commands."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, cast

import click
import typer

from apps.onepiece.pipeline import (
    PipelineClient,
    PipelineClientError,
    _build_parameter_schema_from_definition,
    create_pipeline_client,
)
from apps.onepiece.pipeline.io import _resolve_parameters_with_schema
from apps.onepiece.pipeline.output import (
    _format_pipeline_definition,
    _format_pipeline_run,
    _format_run_event,
)
from apps.onepiece.render.presets import RenderPreset, RenderPresetStore
from apps.onepiece.render.submit.scripts import run_render_submission
from apps.onepiece.render.submit.status_command import render_status
from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceValidationError,
)

app = typer.Typer(
    name="hub",
    help=(
        "Guided hub that ties together pipeline runs, render submissions, and status lookups."
    ),
)


@contextmanager
def _using_pipeline_client() -> Iterator[PipelineClient]:
    client = create_pipeline_client()
    try:
        yield client
    finally:
        client.close()


def _prompt_choice(
    label: str, choices: list[str], *, default: str | None = None
) -> str:
    if not choices:
        raise typer.Exit(code=1)
    prompt_default = default or choices[0]
    return cast(
        str,
        typer.prompt(
            label,
            default=prompt_default,
            type=click.Choice(choices, case_sensitive=False),
            show_default=True,
        ),
    )


def _prompt_optional(label: str, *, default: str | None = None) -> str | None:
    value = cast(
        str | None,
        typer.prompt(label, default=default, show_default=default is not None),
    )
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _render_pipeline_definitions(definitions: list[Mapping[str, Any]]) -> None:
    typer.secho("Available pipelines:", fg=typer.colors.CYAN)
    for definition in definitions:
        for line in _format_pipeline_definition(definition):
            typer.echo(line)
        typer.echo("-")


def _select_pipeline(
    client: PipelineClient,
) -> tuple[str, Mapping[str, Any]] | None:
    try:
        definitions = client.list_definitions()
    except PipelineClientError as exc:
        typer.secho(f"Pipeline request failed: {exc.message}", fg=typer.colors.RED)
        return None

    if not definitions:
        typer.secho(
            "No pipelines are currently registered with the orchestrator.",
            fg=typer.colors.YELLOW,
        )
        return None

    _render_pipeline_definitions(definitions)

    names = [
        str(definition.get("name"))
        for definition in definitions
        if definition.get("name")
    ]
    if not names:
        typer.secho("Pipelines are missing identifiers.", fg=typer.colors.RED)
        return None

    selected_name = _prompt_choice("Pipeline to run", names, default=names[0])
    selected_definition: Mapping[str, Any] | None = None
    for definition in definitions:
        if str(definition.get("name")) == selected_name:
            selected_definition = definition
            break

    if selected_definition is None:
        typer.secho(
            f"Pipeline '{selected_name}' could not be resolved.",
            fg=typer.colors.RED,
        )
        return None

    return selected_name, selected_definition


def _collect_pipeline_parameters(definition: Mapping[str, Any]) -> dict[str, Any]:
    schema = _build_parameter_schema_from_definition(
        definition,
        fallback_name=str(definition.get("name") or "pipeline"),
    )
    if schema is None:
        return {}
    typer.secho(
        "Provide values for any required parameters (press Enter to accept defaults).",
        fg=typer.colors.BLUE,
    )
    try:
        return cast(
            dict[str, Any],
            _resolve_parameters_with_schema({}, schema=schema, interactive=True),
        )
    except PipelineClientError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        return {}


def _trigger_pipeline_run(
    client: PipelineClient, name: str, parameters: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    try:
        run = cast(Mapping[str, Any], client.trigger_run(name, parameters))
    except PipelineClientError as exc:
        if exc.status_code == 404:
            typer.secho(f"Unknown pipeline '{name}'.", fg=typer.colors.RED)
        else:
            typer.secho(f"Pipeline request failed: {exc.message}", fg=typer.colors.RED)
        return None

    typer.secho("Pipeline run queued:", fg=typer.colors.GREEN)
    for line in _format_pipeline_run(run):
        typer.echo(line)
    return run


def _stream_pipeline_run(client: PipelineClient, run_id: str) -> None:
    typer.secho("Streaming pipeline events…", fg=typer.colors.CYAN)
    try:
        for event in client.stream_events(run_id):
            for line in _format_run_event(event):
                typer.echo(line)
            status = str(event.get("status", "")).lower()
            if status in {"succeeded", "failed"}:
                typer.secho(
                    f"Run completed with status: {status}.", fg=typer.colors.GREEN
                )
                return
    except PipelineClientError as exc:
        typer.secho(f"Pipeline request failed: {exc.message}", fg=typer.colors.RED)


def _check_pipeline_run_status(client: PipelineClient, run_id: str) -> None:
    try:
        run = client.get_run(run_id)
    except PipelineClientError as exc:
        if exc.status_code == 404:
            typer.secho(f"Run '{run_id}' was not found.", fg=typer.colors.RED)
        else:
            typer.secho(f"Pipeline request failed: {exc.message}", fg=typer.colors.RED)
        return

    typer.secho("Pipeline run status:", fg=typer.colors.CYAN)
    for line in _format_pipeline_run(run):
        typer.echo(line)


def _choose_render_preset(store: RenderPresetStore) -> RenderPreset | None:
    presets = store.list()
    if not presets:
        typer.secho("No render presets found.", fg=typer.colors.YELLOW)
        return None

    typer.secho("Available render presets:", fg=typer.colors.CYAN)
    for record in presets:
        preset = record.preset
        summary = [
            f"farm={preset.farm}",
            f"dcc={preset.dcc}",
            f"frames={preset.frames}",
            f"priority={preset.priority}",
        ]
        if preset.chunk_size is not None:
            summary.append(f"chunk={preset.chunk_size}")
        if preset.user:
            summary.append(f"user={preset.user}")
        typer.echo(f"- {record.name}: {', '.join(summary)}")

    names = [record.name for record in presets]
    selected = _prompt_choice("Render preset", names, default=names[0])
    try:
        record = store.load(selected)
    except Exception as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        return None
    return record.preset


def _prompt_render_overrides(preset: RenderPreset) -> RenderPreset:
    typer.secho(
        "Press Enter to keep the preset defaults (edit if this shot needs a tweak).",
        fg=typer.colors.BLUE,
    )
    scene_value = _prompt_optional("Scene path", default=str(preset.scene))
    frames_value = _prompt_optional("Frame range", default=preset.frames)
    output_value = _prompt_optional("Output folder", default=str(preset.output))
    user_value = _prompt_optional(
        "Submitting user (optional)", default=preset.user or ""
    )

    merged = preset.serialise()
    if scene_value:
        merged["scene"] = scene_value
    if frames_value:
        merged["frames"] = frames_value
    if output_value:
        merged["output"] = output_value
    if user_value:
        merged["user"] = user_value

    store = RenderPresetStore()
    return RenderPreset.from_mapping(
        preset.name,
        merged,
        capability_provider=store.capability_provider,
    )


def _submit_render(preset: RenderPreset) -> dict[str, Any] | None:
    try:
        result = run_render_submission(
            dcc=preset.dcc,
            farm=preset.farm,
            scene=preset.scene,
            frames=preset.frames,
            output=preset.output,
            user=preset.user,
            optimize=False,
        )
    except (OnePieceValidationError, OnePieceExternalServiceError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        return None

    payload = cast(dict[str, Any], result.get("result", {}))
    job_id = payload.get("job_id", "<unknown>")
    status = payload.get("status", "unknown")
    farm_type = payload.get("farm_type", preset.farm)
    message = payload.get("message")

    typer.secho(
        f"Submitted render job {job_id} to {farm_type} (status: {status}).",
        fg=typer.colors.GREEN,
    )
    if message:
        typer.echo(message)

    return payload


def _handle_render_status(job_id: str, farm: str | None = None) -> None:
    try:
        render_status(job_id=job_id, farm=farm, profile=None, raw=False)
    except Exception as exc:
        typer.secho(str(exc), fg=typer.colors.RED)


def _pipeline_and_render_flow() -> None:
    with _using_pipeline_client() as client:
        selection = _select_pipeline(client)
        if selection is None:
            return
        pipeline_name, definition = selection
        parameters = _collect_pipeline_parameters(definition)
        run = _trigger_pipeline_run(client, pipeline_name, parameters)
        if run is None:
            return
        run_id = str(run.get("id")) if run.get("id") is not None else ""
        if run_id and typer.confirm("Watch pipeline events until completion?", True):
            _stream_pipeline_run(client, run_id)

    if typer.confirm("Submit a render job after this pipeline run?", True):
        store = RenderPresetStore()
        preset = _choose_render_preset(store)
        if preset is None:
            return
        preset = _prompt_render_overrides(preset)
        render_payload = _submit_render(preset)
        if render_payload is None:
            return
        job_id = render_payload.get("job_id")
        if job_id and typer.confirm("Check render status now?", True):
            _handle_render_status(str(job_id), farm=render_payload.get("farm"))


def _render_preset_only_flow() -> None:
    store = RenderPresetStore()
    preset = _choose_render_preset(store)
    if preset is None:
        return
    preset = _prompt_render_overrides(preset)
    render_payload = _submit_render(preset)
    if render_payload is None:
        return
    job_id = render_payload.get("job_id")
    if job_id and typer.confirm("Check render status now?", True):
        _handle_render_status(str(job_id), farm=render_payload.get("farm"))


def _pipeline_status_flow() -> None:
    run_id = _prompt_optional("Pipeline run ID")
    if not run_id:
        typer.secho("Run ID is required.", fg=typer.colors.RED)
        return
    with _using_pipeline_client() as client:
        _check_pipeline_run_status(client, run_id)


def _render_status_flow() -> None:
    job_id = _prompt_optional("Render job ID")
    if not job_id:
        typer.secho("Render job ID is required.", fg=typer.colors.RED)
        return
    farm = _prompt_optional("Farm filter (optional)")
    _handle_render_status(job_id, farm=farm or None)


@app.callback(invoke_without_command=True)
def hub(ctx: typer.Context) -> None:
    """Launch the interactive pipeline + render hub."""

    if ctx.invoked_subcommand is not None:
        return

    typer.secho("Pipeline & Render Hub", fg=typer.colors.CYAN, bold=True)
    typer.echo(
        "Follow the prompts to trigger a pipeline run, submit a render preset, "
        "or check current statuses without memorising flags."
    )

    actions = {
        "pipeline-render": "Run a pipeline, then submit a render",
        "pipeline-status": "Check pipeline run status",
        "render-preset": "Submit a render preset",
        "render-status": "Check render job status",
        "exit": "Exit the hub",
    }

    while True:
        typer.echo("\nWhat would you like to do?")
        for key, label in actions.items():
            typer.echo(f"- {key}: {label}")

        selection = _prompt_choice(
            "Selection",
            list(actions.keys()),
            default="pipeline-render",
        )

        if selection == "pipeline-render":
            _pipeline_and_render_flow()
        elif selection == "pipeline-status":
            _pipeline_status_flow()
        elif selection == "render-preset":
            _render_preset_only_flow()
        elif selection == "render-status":
            _render_status_flow()
        elif selection == "exit":
            typer.echo("Goodbye!")
            break


__all__ = ["app"]
