"""Unit tests for the UTA web command metadata helpers."""

import click

from apps.uta import web


def test_required_option_omits_placeholder_default() -> None:
    """Required options should not display sentinel defaults."""

    @click.command()
    @click.option("--foo", required=True, help="Example option")
    def cli(foo: str) -> None:  # pragma: no cover - executed via metadata extraction
        raise NotImplementedError

    parameters = web._extract_parameters(cli)
    assert parameters, "Expected the command to expose at least one parameter"

    parameter = parameters[0]
    assert parameter.required is True
    assert parameter.default is None

    rendered = web._render_parameters(
        web.CommandSpec(path=["cli"], summary="", parameters=parameters)
    )

    assert "required" in rendered
    assert "default:" not in rendered
    assert "Ellipsis" not in rendered
