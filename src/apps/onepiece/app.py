import typer

from apps.onepiece.cli_registry import default_command_groups, resolve_command_groups
from apps.onepiece.config import ProfileContext, load_profile
from apps.onepiece.utils.errors import OnePieceError

app = typer.Typer(help="OnePiece pipeline command line interface")

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
    app.add_typer(group.loader())


@app.callback()
def _ensure_profile_loaded() -> None:
    if isinstance(_profile_or_error, OnePieceError):
        raise _profile_or_error
