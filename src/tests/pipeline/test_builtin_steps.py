from __future__ import annotations

import sys

import pytest

from libraries.pipeline.steps import (
    PipelineStepConfigError,
    noop_step_factory,
    shell_step_factory,
)


def test_shell_step_factory_requires_command() -> None:
    with pytest.raises(PipelineStepConfigError):
        shell_step_factory({})


def test_shell_step_factory_runs_command() -> None:
    factory = shell_step_factory(
        {
            "command": [
                sys.executable,
                "-c",
                "print('{name}')",
            ],
            "capture_output": True,
        }
    )

    result = factory(parameters={"name": "alice"})

    assert result["returncode"] == 0
    assert "alice" in result["stdout"]


def test_noop_step_factory_returns_message() -> None:
    factory = noop_step_factory({"message": "All done."})

    result = factory()

    assert result == {"message": "All done.", "status": "noop"}
