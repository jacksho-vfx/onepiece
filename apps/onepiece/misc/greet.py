import typer

app = typer.Typer(help="A simple demo command")

@app.command(name="greet", no_args_is_help=True)
def greet(name: str) -> None:
    """A simple demo command"""
    typer.echo(f"Hello {name}, OnePiece is ready.")
