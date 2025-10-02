import typer

from apps.onepiece.aws import app as aws
from apps.onepiece.dcc import app as dcc
from apps.onepiece.shotgrid import app as shotgrid
from apps.onepiece.misc.info import app as info
from onepiece.review import app as review
from onepiece.render import app as render_app
from apps.onepiece.validate import app as validate
from apps.onepiece.utils.errors import OnePieceError
from apps.onepiece.validate.reconcile import app as reconcile


def handle_onepiece_error(exc: OnePieceError) -> None:
    typer.secho(f"{exc.heading}: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=exc.exit_code)


app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(info)

app.add_typer(aws)
app.add_typer(dcc)
app.add_typer(review)
app.add_typer(render_app)

app.add_typer(shotgrid)
app.add_typer(validate)
app.add_typer(reconcile)

if hasattr(app, "exception_handler"):
    app.exception_handler(OnePieceError)(handle_onepiece_error)
