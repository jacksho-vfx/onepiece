"""CLI command group registry for the OnePiece toolchain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, cast

import typer

from apps.onepiece.utils.errors import OnePieceConfigError
from apps.onepiece.config import ProfileContext


@dataclass(frozen=True)
class CommandGroup:
    """Represents a named CLI command group and its lazy loader."""

    name: str
    loader: Callable[[], typer.Typer]


def _load_info() -> typer.Typer:
    from apps.onepiece.misc.info import app as info

    return cast(typer.Typer, info)


def _load_aws() -> typer.Typer:
    from apps.onepiece.aws import app as aws

    return cast(typer.Typer, aws)


def _load_dcc() -> typer.Typer:
    from apps.onepiece.dcc import app as dcc

    return cast(typer.Typer, dcc)


def _load_review() -> typer.Typer:
    from libraries.automation.review import app as review

    return cast(typer.Typer, review)


def _load_chopper() -> typer.Typer:
    from apps.chopper.app import app as chopper

    return cast(typer.Typer, chopper)


def _load_hub() -> typer.Typer:
    from apps.onepiece.hub import app as hub

    return cast(typer.Typer, hub)


def _load_render() -> typer.Typer:
    from apps.onepiece.render import app as render

    return cast(typer.Typer, render)


def _load_notify() -> typer.Typer:
    from apps.onepiece.notify import app as notify

    return cast(typer.Typer, notify)


def _load_healthcheck() -> typer.Typer:
    from apps.onepiece.healthcheck import app as healthcheck

    return cast(typer.Typer, healthcheck)


def _load_ingest() -> typer.Typer:
    from apps.onepiece.ingest import app as ingest

    return cast(typer.Typer, ingest)


def _load_shotgrid() -> typer.Typer:
    from apps.onepiece.shotgrid import app as shotgrid

    return cast(typer.Typer, shotgrid)


def _load_validate() -> typer.Typer:
    from apps.onepiece.validate import app as validate

    return cast(typer.Typer, validate)


def _load_pipeline() -> typer.Typer:
    from apps.onepiece.pipeline import app as pipeline

    return cast(typer.Typer, pipeline)


COMMAND_GROUPS: dict[str, CommandGroup] = {
    "info": CommandGroup("info", _load_info),
    "aws": CommandGroup("aws", _load_aws),
    "dcc": CommandGroup("dcc", _load_dcc),
    "review": CommandGroup("review", _load_review),
    "chopper": CommandGroup("chopper", _load_chopper),
    "hub": CommandGroup("hub", _load_hub),
    "render": CommandGroup("render", _load_render),
    "notify": CommandGroup("notify", _load_notify),
    "healthcheck": CommandGroup("healthcheck", _load_healthcheck),
    "ingest": CommandGroup("ingest", _load_ingest),
    "shotgrid": CommandGroup("shotgrid", _load_shotgrid),
    "validate": CommandGroup("validate", _load_validate),
    "pipeline": CommandGroup("pipeline", _load_pipeline),
}

DEFAULT_COMMAND_ORDER = tuple(COMMAND_GROUPS.keys())


def resolve_command_groups(context: ProfileContext) -> tuple[CommandGroup, ...]:
    """Return the command groups enabled for the resolved profile."""

    enabled = context.cli_enabled_groups
    disabled = context.cli_disabled_groups

    if enabled is not None:
        return tuple(_resolve_group(name, context.name) for name in enabled)

    groups = [COMMAND_GROUPS[name] for name in DEFAULT_COMMAND_ORDER]
    if disabled:
        disabled_set = {name.strip() for name in disabled if name.strip()}
        unknown = sorted(disabled_set.difference(COMMAND_GROUPS.keys()))
        if unknown:
            raise OnePieceConfigError(
                f"Profile '{context.name}' cli.disabled_groups contains unknown entries: {', '.join(unknown)}."
            )
        groups = [group for group in groups if group.name not in disabled_set]
    return tuple(groups)


def default_command_groups() -> tuple[CommandGroup, ...]:
    """Return the default command groups in registration order."""

    return tuple(COMMAND_GROUPS[name] for name in DEFAULT_COMMAND_ORDER)


def _resolve_group(name: str, profile_name: str) -> CommandGroup:
    key = name.strip()
    if not key:
        raise OnePieceConfigError(
            f"Profile '{profile_name}' cli.enabled_groups must not contain empty values"
        )
    try:
        return COMMAND_GROUPS[key]
    except KeyError as exc:
        raise OnePieceConfigError(
            f"Profile '{profile_name}' cli.enabled_groups contains unknown entry '{key}'."
        ) from exc
