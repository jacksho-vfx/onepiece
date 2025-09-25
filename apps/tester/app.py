from typer.testing import CliRunner
from onepice.cli import app

runner = CliRunner()


def test_greet():
    result = runner.invoke(app, ["greet", "World"])
    assert result.exit_code == 0
    assert "Hello World" in result.output
