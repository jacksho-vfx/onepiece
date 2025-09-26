import typer

from src.apps.onepiece.aws import app as aws
from src.apps.onepiece.dcc.publish import publish
from src.apps.onepiece.ingest import app as ingest
from src.apps.onepiece.misc.greet import app as greet
from src.apps.onepiece.misc.info import app as info
from src.apps.onepiece.shotgrid.flow_setup import app as flow_setup
from src.apps.onepiece.validate import app as validate
from src.apps.onepiece.utils.errors import OnePieceError


def handle_onepiece_error(exc: OnePieceError) -> None:
    typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=exc.exit_code)


app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(ingest, name="ingest")
app.add_typer(greet)
app.add_typer(info)
app.add_typer(flow_setup)
app.add_typer(aws)
app.add_typer(validate)
app.command("publish")(publish)

if hasattr(app, "exception_handler"):
    app.exception_handler(OnePieceError)(handle_onepiece_error)
