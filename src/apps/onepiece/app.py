import typer

from apps.onepiece.aws import app as aws
from apps.onepiece.dcc import app as dcc
from apps.onepiece.shotgrid import app as shotgrid
from apps.onepiece.misc.info import app as info
from libraries.review import app as review
from apps.onepiece.render import app as render
from apps.onepiece.notify import app as notify
from apps.onepiece.validate import app as validate
from apps.onepiece.validate.reconcile import app as reconcile


app = typer.Typer(help="OnePiece pipeline command line interface")

app.add_typer(info)

app.add_typer(aws)
app.add_typer(dcc)
app.add_typer(review)
app.add_typer(render)
app.add_typer(notify)

app.add_typer(shotgrid)
app.add_typer(validate)
app.add_typer(reconcile)
