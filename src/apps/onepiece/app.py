import typer

from apps.onepiece.aws import app as aws
from apps.onepiece.shotgrid.deliver_cli import app as deliver
from apps.onepiece.dcc.publish import app as publish
from apps.onepiece.aws.ingest import app as ingest
from apps.onepiece.misc.greet import app as greet
from apps.onepiece.misc.info import app as info
from apps.onepiece.shotgrid.delivery import app as shotgrid_delivery
from apps.onepiece.shotgrid.flow_setup import app as flow_setup
from apps.onepiece.validate import app as validate
from apps.onepiece.dcc.open_shot import app as open_shot
from apps.onepiece.utils.errors import OnePieceError


def handle_onepiece_error(exc: OnePieceError) -> None:
    typer.secho(f"{exc.heading}: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=exc.exit_code)


app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(ingest)
app.add_typer(greet)
app.add_typer(info)
app.add_typer(flow_setup)
app.add_typer(shotgrid_delivery)
app.add_typer(aws)
app.add_typer(validate)
app.add_typer(publish)
app.add_typer(open_shot)
app.add_typer(deliver)

if hasattr(app, "exception_handler"):
    app.exception_handler(OnePieceError)(handle_onepiece_error)
