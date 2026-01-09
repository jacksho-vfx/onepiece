import typer

from apps.onepiece.cli_registry import (
    CATEGORY_ORDER,
    default_command_groups,
    resolve_command_groups,
)
from apps.onepiece.config import ProfileContext, load_profile
from apps.onepiece.utils.errors import OnePieceError

app = typer.Typer(
    help="OnePiece pipeline command line interface.",
    no_args_is_help=True,
)

_profile_or_error: ProfileContext | OnePieceError
try:
    _profile_or_error = load_profile()
except OnePieceError as exc:
    _profile_or_error = exc

if isinstance(_profile_or_error, OnePieceError):
    groups = default_command_groups()
else:
    groups = resolve_command_groups(_profile_or_error)

for group in groups:
    app.add_typer(group.loader(), name=group.name, help=group.summary)


@app.callback()
def _ensure_profile_loaded() -> None:
    if isinstance(_profile_or_error, OnePieceError):
        raise _profile_or_error


@app.command("commands")
def list_commands(
    show_all: bool = typer.Option(
        False,
        "--all",
        help="Show all command groups, ignoring profile filters.",
    )
) -> None:
    """Show a categorized summary of available command groups."""

    visible_groups = list(default_command_groups()) if show_all else list(groups)

    categories = {category: [] for category in CATEGORY_ORDER}
    for group in visible_groups:
        categories.setdefault(group.category, []).append(group)

    typer.echo("OnePiece command groups:")
    for category in CATEGORY_ORDER:
        category_groups = categories.get(category, [])
        if not category_groups:
            continue
        typer.echo(f"\n{category}:")
        for group in category_groups:
            typer.echo(f"  {group.name:<12} {group.summary}")
