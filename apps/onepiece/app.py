import typer

from apps.onepiece.dcc.publish import publish
from apps.onepiece.misc.greet import app as greet
from apps.onepiece.misc.info import app as info
from apps.onepiece.shotgrid.flow_setup import app as flow_setup
from apps.onepiece.utils.errors import OnePieceError

def handle_onepiece_error(exc: OnePieceError):
    typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=exc.exit_code)

app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(greet)
app.add_typer(info)
app.add_typer(flow_setup)
app.command("publish")(publish)

if hasattr(app, "exception_handler"):
    app.exception_handler(OnePieceError)(handle_onepiece_error)
