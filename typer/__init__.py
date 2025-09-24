"""A lightweight subset of the :mod:`typer` API used in tests.

The real Typer package is built on top of Click and ships with a sizeable
dependency graph.  The CI environment that exercises these kata repositories
does not install third party dependencies, so we provide a very small shim that
implements just enough functionality for the OnePiece CLI.

Only the pieces of the public API that the codebase imports are implemented:

* :class:`Typer` and the ``@app.command`` decorator for declaring commands.
* :func:`Option` for marking keyword arguments as CLI options.
* :func:`echo`, :func:`secho`, and :class:`Exit` for communicating with the
  command runner.
* :class:`BadParameter` for validation errors.
* :data:`colors` with a ``RED`` attribute which is used when printing
  highlighted error messages.
* :func:`progressbar` returning a no-op context manager.

The implementation intentionally keeps the parsing logic tiny – it understands
``--option value`` style flags and converts values using standard Python type
annotations.  That is more than enough for the small collection of commands in
this repository.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import inspect
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional
from typing import Sequence, Tuple
from typing import get_args, get_origin, get_type_hints
import sys


class Exit(Exception):
    """Signal that command execution should exit early."""

    def __init__(self, code: int | None = 0) -> None:
        super().__init__(code)
        self.code = 0 if code is None else code


class BadParameter(Exception):
    """Raised when parameter validation fails."""


def echo(message: str, *, err: bool = False) -> None:
    """Write ``message`` to stdout (or stderr when ``err`` is true)."""

    target = sys.stderr if err else sys.stdout
    print(message, file=target)


def secho(message: str, *, fg: str | None = None, err: bool = False) -> None:
    """A coloured variant of :func:`echo`.

    The shim ignores the colour information but keeps the API compatible.
    """

    del fg  # Colour information is not used in the shim.
    echo(message, err=err)


class _Colors:
    RED = "red"


colors = _Colors()


@dataclass
class OptionInfo:
    names: Tuple[str, ...]
    default: Any
    required: bool


def Option(default: Any = ..., *names: str, **_: Any) -> OptionInfo:
    """Declare a CLI option.

    Only the information required by the tests is captured: the flag names and
    whether the option is required.  Validation flags such as ``exists`` or
    ``dir_okay`` are accepted for API compatibility but ignored.
    """

    option_names = names or (None,)
    required = default is ...
    return OptionInfo(names=option_names, default=None if required else default, required=required)


@dataclass
class _Parameter:
    name: str
    option_names: Tuple[str, ...]
    annotation: Any
    default: Any
    required: bool


@dataclass
class _Command:
    name: str
    callback: Callable[..., Any]
    parameters: List[_Parameter]


class Typer:
    """Extremely small command container used by the tests."""

    def __init__(self, *, help: str | None = None) -> None:  # noqa: A002 - "help" matches Typer.
        self._help = help
        self._commands: Dict[str, _Command] = {}
        self._exception_handlers: Dict[type[BaseException], Callable[[BaseException], Any]] = {}

    # -- registration -------------------------------------------------
    def command(self, name: str | None = None, **_: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            command_name = name or func.__name__.replace("_", "-")
            parameters = self._build_parameters(func)
            self._commands[command_name] = _Command(command_name, func, parameters)
            return func

        return decorator

    def add_typer(self, other: "Typer", name: str | None = None) -> None:
        prefix = f"{name} " if name else ""
        for command_name, command in other._commands.items():
            joined_name = f"{prefix}{command_name}".strip()
            self._commands[joined_name] = command

    def exception_handler(self, exc_type: type[BaseException]) -> Callable[[Callable[[BaseException], Any]], Callable[[BaseException], Any]]:
        def decorator(handler: Callable[[BaseException], Any]) -> Callable[[BaseException], Any]:
            self._exception_handlers[exc_type] = handler
            return handler

        return decorator

    # -- invocation ---------------------------------------------------
    def __call__(self, args: Optional[Sequence[str]] = None) -> None:
        self._run(args or [])

    def _run(self, args: Sequence[str]) -> None:
        if not args:
            raise Exit(0)

        command_name, *command_args = args
        command = self._commands.get(command_name)
        if command is None:
            raise Exit(1)

        kwargs = self._parse_kwargs(command, command_args)
        try:
            command.callback(**kwargs)
        except tuple(self._exception_handlers) as exc:  # type: ignore[arg-type]
            handler = self._exception_handlers[type(exc)]
            handler(exc)
        except Exit:
            raise
        except SystemExit as exc:
            raise Exit(exc.code)

    # -- helpers ------------------------------------------------------
    def _build_parameters(self, func: Callable[..., Any]) -> List[_Parameter]:
        parameters: List[_Parameter] = []
        signature = inspect.signature(func)
        type_hints = get_type_hints(func)
        for parameter in signature.parameters.values():
            default = parameter.default
            annotation = type_hints.get(parameter.name, parameter.annotation)
            if isinstance(default, OptionInfo):
                option_info = default
                option_names = tuple(
                    name if name is not None else f"--{parameter.name.replace('_', '-')}"
                    for name in option_info.names
                )
                default_value = option_info.default
                required = option_info.required
            else:
                option_names = (f"--{parameter.name.replace('_', '-')}",)
                default_value = None if default is inspect._empty else default
                required = default is inspect._empty

            parameters.append(
                _Parameter(
                    name=parameter.name,
                    option_names=option_names,
                    annotation=annotation,
                    default=default_value,
                    required=required,
                )
            )
        return parameters

    def _parse_kwargs(self, command: _Command, args: Sequence[str]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        mapping: Dict[str, _Parameter] = {}
        for parameter in command.parameters:
            for name in parameter.option_names:
                mapping[name] = parameter

        it = iter(args)
        for raw in it:
            if not raw.startswith("--"):
                continue
            param = mapping.get(raw)
            if param is None:
                raise Exit(1)
            try:
                value = next(it)
            except StopIteration:
                raise Exit(1)
            kwargs[param.name] = _convert_value(value, param.annotation)

        for parameter in command.parameters:
            if parameter.name not in kwargs:
                if parameter.required:
                    raise Exit(1)
                kwargs[parameter.name] = parameter.default

        return kwargs


def _convert_value(value: str, annotation: Any) -> Any:
    if annotation is inspect._empty:
        return value

    origin = get_origin(annotation)
    if origin is None:
        if annotation is Path:
            return Path(value)
        if annotation in {str, int, float}:
            return annotation(value)
        return value

    if origin is Optional:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]  # noqa: E721
        if not args:
            return value
        return _convert_value(value, args[0])

    return value


@contextmanager
def progressbar(iterable: Iterable[Any], label: str | None = None) -> Iterator[Iterable[Any]]:  # noqa: ARG001
    yield iterable


class _Result:
    def __init__(self, exit_code: int, output: str, exception: Exception | None) -> None:
        self.exit_code = exit_code
        self.output = output
        self.exception = exception


class _CliRunner:
    def invoke(self, app: Typer, args: Sequence[str]) -> _Result:
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = 0
        exception: Exception | None = None

        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                app._run(args)
            except Exit as exc:
                exit_code = exc.code
            except Exception as exc:  # pragma: no cover - surfaced to tests.
                exit_code = 1
                exception = exc

        output = stdout.getvalue() + stderr.getvalue()
        return _Result(exit_code=exit_code, output=output, exception=exception)


testing = type("testing", (), {"CliRunner": _CliRunner})


__all__ = [
    "BadParameter",
    "CliRunner",
    "Exit",
    "Option",
    "Typer",
    "colors",
    "echo",
    "progressbar",
    "secho",
]


# Export ``CliRunner`` from ``typer.testing`` style namespace and module level.
CliRunner = _CliRunner

