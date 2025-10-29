from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from inspect import _empty as INSPECT_EMPTY
from typing import Any, Sequence

import click
from typer.main import get_command

from apps.onepiece.app import app as cli_app

@dataclass
class ParameterSpec:
    """Metadata describing a single CLI parameter."""

    label: str
    help_text: str
    required: bool
    default: str | None
    name: str
    cli_names: list[str]
    kind: str
    accepts_value: bool
    is_flag: bool
    allows_multiple: bool
    nargs: int
    default_bool: bool | None = None


@dataclass
class CommandSpec:
    """Metadata describing a CLI command that can be invoked from the GUI."""

    path: list[str]
    summary: str
    parameters: list[ParameterSpec] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return " ".join(self.path)

    @property
    def invocation(self) -> str:
        return "onepiece " + " ".join(self.path)


@dataclass
class PageSpec:
    """Collection of commands grouped by the first CLI segment."""

    name: str
    help_text: str
    commands: list[CommandSpec] = field(default_factory=list)


AUTO_PARAM_NAMES = {"help", "install_completion", "show_completion"}


def _normalise_help(value: str | None) -> str:
    return (value or "").strip()


def _format_parameter_label(parameter: click.Parameter) -> Any:
    if isinstance(parameter, click.Option):
        names = list(parameter.opts) + list(parameter.secondary_opts)
        label = ", ".join(names) if names else parameter.name
    else:
        label = parameter.human_readable_name
    if parameter.type:
        label = f"{label} ({parameter.type.name})"
    return label


def _is_missing_default(parameter: click.Parameter, value: Any) -> bool:
    if value is None:
        return True
    if value is Ellipsis:
        return True
    parameter_empty = getattr(click.Parameter, "empty", None)
    if parameter_empty is not None and value is parameter_empty:
        return True
    if INSPECT_EMPTY is not None and value is INSPECT_EMPTY:
        return True
    if getattr(parameter, "required", False):
        if isinstance(value, Enum):
            return True
        value_type = type(value)
        module = getattr(value_type, "__module__", "")
        name = value_type.__name__
        if module.startswith("typer.") and (
            "Placeholder" in name or name.startswith("Default")
        ):
            return True
    return False


def _extract_parameters(command: click.Command) -> list[ParameterSpec]:
    specs: list[ParameterSpec] = []
    for parameter in command.params:
        if parameter.name in AUTO_PARAM_NAMES:
            continue
        default_value = getattr(parameter, "default", None)
        default: str | None
        if _is_missing_default(parameter, default_value):
            default = None
        else:
            default = str(default_value)
        if isinstance(parameter, click.Option):
            cli_names = list(parameter.opts) + list(parameter.secondary_opts)
            kind = "option"
            is_flag = bool(getattr(parameter, "is_flag", False)) or bool(
                getattr(parameter, "is_bool_flag", False)
            )
            accepts_value = not is_flag
            allows_multiple = bool(getattr(parameter, "multiple", False)) or bool(
                getattr(parameter, "nargs", 1) != 1
            )
            nargs = int(getattr(parameter, "nargs", 1))
        else:
            cli_names = [parameter.human_readable_name]
            kind = "argument"
            is_flag = False
            accepts_value = True
            nargs = int(getattr(parameter, "nargs", 1))
            allows_multiple = nargs != 1
        default_bool: bool | None = None
        if is_flag and isinstance(default_value, bool):
            default_bool = default_value
        specs.append(
            ParameterSpec(
                label=_format_parameter_label(parameter) or "",
                help_text=(getattr(parameter, "help", "") or "").strip(),
                required=getattr(parameter, "required", False),
                default=default,
                name=getattr(parameter, "name", ""),
                cli_names=cli_names,
                kind=kind,
                accepts_value=accepts_value,
                is_flag=is_flag,
                allows_multiple=allows_multiple,
                nargs=nargs,
                default_bool=default_bool,
            )
        )
    return specs


def _collect_click_commands(
    command: click.Command, path: Sequence[str]
) -> list[CommandSpec]:
    commands: list[CommandSpec] = []
    if isinstance(command, click.Group):
        if command.callback is not None:
            commands.append(
                CommandSpec(
                    path=list(path),
                    summary=_normalise_help(command.help),
                    parameters=_extract_parameters(command),
                )
            )
        for name, child in command.commands.items():
            commands.extend(_collect_click_commands(child, [*path, name]))
    else:
        commands.append(
            CommandSpec(
                path=list(path),
                summary=_normalise_help(command.help),
                parameters=_extract_parameters(command),
            )
        )
    return commands


def _build_pages() -> dict[str, PageSpec]:
    root_command = get_command(cli_app)
    pages: dict[str, PageSpec] = {}
    for name, command in root_command.commands.items():  # type: ignore[attr-defined]
        page = PageSpec(
            name=name, help_text=_normalise_help(getattr(command, "help", ""))
        )
        page.commands.extend(_collect_click_commands(command, [name]))
        pages[name] = page
    for page in pages.values():
        page.commands = sorted(page.commands, key=lambda item: item.path)
    return dict(sorted(pages.items(), key=lambda item: item[0]))


CLI_PAGES = _build_pages()
COMMAND_LOOKUP: dict[tuple[str, ...], CommandSpec] = {
    tuple(command.path): command
    for page in CLI_PAGES.values()
    for command in page.commands
}


__all__ = [
    "ParameterSpec",
    "CommandSpec",
    "PageSpec",
    "CLI_PAGES",
    "COMMAND_LOOKUP",
]


