"""Built-in pipeline step factories for small studio workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
import shlex
import subprocess
from typing import Any


class PipelineStepConfigError(ValueError):
    """Raised when a pipeline step configuration is invalid."""


def _coerce_command(command: Any) -> str | list[str]:
    if isinstance(command, str):
        return command
    if isinstance(command, Sequence) and not isinstance(
        command, (str, bytes, bytearray)
    ):
        return [str(item) for item in command]
    raise PipelineStepConfigError("command must be a string or sequence of strings")


def _format_template(value: str, *, context: Mapping[str, Any]) -> str:
    try:
        return value.format_map(context)
    except KeyError as exc:  # pragma: no cover - defensive
        missing = exc.args[0]
        raise PipelineStepConfigError(
            f"missing template value '{missing}' in command"
        ) from exc


def _resolve_command(
    raw_command: str | list[str], *, context: Mapping[str, Any], shell: bool
) -> str | list[str]:
    if isinstance(raw_command, str):
        formatted = _format_template(raw_command, context=context)
        if shell:
            return formatted
        return shlex.split(formatted)
    return [_format_template(item, context=context) for item in raw_command]


def _resolve_environment(env: Any) -> dict[str, str] | None:
    if env is None:
        return None
    if not isinstance(env, Mapping):
        raise PipelineStepConfigError("env must be a mapping of strings")
    base = dict(os.environ)
    for key, value in env.items():
        base[str(key)] = str(value)
    return base


def shell_step_factory(config: Mapping[str, Any]) -> Callable[..., dict[str, Any]]:
    """Create a provider that runs a shell command locally.

    Supported config keys:
    - command (required): string or list of strings. Strings can use
      Python format placeholders referencing pipeline parameters.
    - cwd: optional working directory.
    - env: mapping of environment overrides.
    - shell: bool (default False) to run via the shell.
    - check: bool (default True) to raise on non-zero exit.
    - capture_output: bool (default False) to capture stdout/stderr.
    """

    if "command" not in config:
        raise PipelineStepConfigError("shell step requires a 'command' value")

    raw_command = _coerce_command(config.get("command"))
    cwd = config.get("cwd")
    if cwd is not None:
        cwd = str(cwd)
    env = _resolve_environment(config.get("env"))
    shell = bool(config.get("shell", False))
    check = bool(config.get("check", True))
    capture_output = bool(config.get("capture_output", False))

    def _run(
        context: Any = None, parameters: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        context_payload = {
            "run_id": getattr(context, "run_id", ""),
            "pipeline_name": getattr(context, "pipeline_name", ""),
            "step_name": getattr(context, "step_name", ""),
        }
        payload = dict(parameters or {})
        template_context = {**context_payload, **payload}
        command = _resolve_command(raw_command, context=template_context, shell=shell)
        result = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=env,
            shell=shell,
            check=check,
            capture_output=capture_output,
            text=capture_output,
        )
        response: dict[str, Any] = {"returncode": result.returncode}
        if capture_output:
            response["stdout"] = result.stdout
            response["stderr"] = result.stderr
        return response

    return _run


def noop_step_factory(config: Mapping[str, Any]) -> Callable[..., dict[str, Any]]:
    """Return a provider that performs no work and returns metadata."""

    message = str(config.get("message") or "No-op step executed.")

    def _run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"message": message, "status": "noop"}

    return _run


def builtin_pipeline_step_factories() -> dict[str, Callable[[Mapping[str, Any]], Any]]:
    """Return built-in pipeline step factories."""

    return {
        "shell": shell_step_factory,
        "noop": noop_step_factory,
    }


__all__ = [
    "PipelineStepConfigError",
    "builtin_pipeline_step_factories",
    "noop_step_factory",
    "shell_step_factory",
]
