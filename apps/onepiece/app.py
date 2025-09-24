import typer

from onepiece.apps.dcc.publish import app as publish
from onepiece.apps.onepiece.ingest import app as ingest
from onepiece.apps.onepiece.misc.greet import app as greet
from onepiece.apps.onepiece.misc.info import app as info
from onepiece.apps.onepiece.shotgrid.flow_setup import app as flow_setup
from onepiece.utils.errors import OnePieceError

def handle_onepiece_error(exc: OnePieceError):
    typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=exc.exit_code)

app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(ingest, name="ingest")
app.add_typer(greet)
app.add_typer(info)
app.add_typer(flow_setup)
app.command("publish")(publish)

if hasattr(app, "exception_handler"):
    app.exception_handler(OnePieceError)(handle_onepiece_error)
