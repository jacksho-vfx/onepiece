import typer

from apps.onepiece.aws import app as aws
from apps.onepiece.shotgrid import app as shotgrid
from apps.onepiece.dcc.publish import app as publish
from apps.onepiece.aws.ingest import app as ingest
from apps.onepiece.misc.greet import app as greet
from apps.onepiece.misc.info import app as info
from onepiece.review import app as review
from apps.onepiece.validate import app as validate
from apps.onepiece.dcc.open_shot import app as open_shot
from apps.onepiece.utils.errors import OnePieceError
from apps.onepiece.reconcile import reconcile as reconcile_command


def handle_onepiece_error(exc: OnePieceError) -> None:
    typer.secho(f"{exc.heading}: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=exc.exit_code)


app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(ingest)
app.add_typer(greet)
app.add_typer(info)
app.add_typer(shotgrid)
app.add_typer(aws)
app.add_typer(validate)
app.add_typer(publish)
app.add_typer(open_shot)
app.add_typer(review)
app.command("reconcile")(reconcile_command)

if hasattr(app, "exception_handler"):
    app.exception_handler(OnePieceError)(handle_onepiece_error)
