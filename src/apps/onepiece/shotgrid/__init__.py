"""Aggregate Typer application for ShotGrid related commands."""

from __future__ import annotations

from typing import cast, Callable, Any

import typer


app = typer.Typer(name="shotgrid", help="Shotgrid related commands.")


def _merge_sub_apps(*sub_apps: typer.Typer) -> None:
    """Register commands from nested Typer apps onto the main ShotGrid app."""

    for sub_app in sub_apps:
        for command in sub_app.registered_commands:
            callback = cast(Callable[..., Any], command.callback)
            app.command(
                name=command.name,
                cls=command.cls,
                help=command.help,
                epilog=command.epilog,
                short_help=command.short_help,
                context_settings=command.context_settings,
                deprecated=command.deprecated,
                hidden=command.hidden,
                rich_help_panel=command.rich_help_panel,
                no_args_is_help=command.no_args_is_help,
                add_help_option=command.add_help_option,
                options_metavar=command.options_metavar,
            )(callback)


def _register_commands() -> None:
    from .deliver_cli import app as deliver_app
    from .delivery import app as delivery_app
    from .flow_setup import app as flow_setup_app
    from .upload_version import app as upload_version_app
    from .version_zero import app as version_zero_app

    _merge_sub_apps(
        deliver_app,
        delivery_app,
        flow_setup_app,
        upload_version_app,
        version_zero_app,
    )


_register_commands()
