from typer.testing import CliRunner

from apps.onepiece.app import app

runner = CliRunner()


def test_greet() -> None:
    result = runner.invoke(app, ["greet", "World"])
    assert result.exit_code == 0
    assert "Hello World" in result.output
