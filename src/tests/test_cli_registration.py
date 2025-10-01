from __future__ import annotations

import re

from typer.testing import CliRunner

from apps.onepiece.app import app


runner = CliRunner()


def extract_command_names(help_output: str) -> list[str]:
    commands = []
    for line in help_output.splitlines():
        m = re.match(r"^\s*│\s+(\w+)\s+", line)
        if m:
            commands.append(m.group(1))
            continue
        m = re.match(r"^\s+(\w+)\s{2,}", line)
        if m:
            commands.append(m.group(1))
    return commands


def test_cli_registers_dcc_once() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    commands = extract_command_names(result.stdout)
    assert commands.count("dcc") == 1, result.stdout
