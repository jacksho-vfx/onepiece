from __future__ import annotations

from typer.testing import CliRunner

from apps.onepiece.app import app


runner = CliRunner()


def extract_command_names(help_output: str) -> list[str]:
    commands: list[str] = []
    in_commands = False
    for line in help_output.splitlines():
        if "Commands" in line:
            in_commands = True
            continue
        if in_commands:
            if line.startswith("╰") or not line.strip():
                break
            if line.startswith("│"):
                # Each command is listed as: "│ <name>   <description> │"
                command = line.strip("│ ").split()[0]
                commands.append(command)
    return commands


def test_cli_registers_dcc_once() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    commands = extract_command_names(result.stdout)
    assert commands.count("dcc") == 1, result.stdout
