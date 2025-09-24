from __future__ import annotations

from types import EllipsisType
from typing import Any, Callable, ContextManager, Iterable, ParamSpec, TypeVar, overload

_P = ParamSpec("_P")
_R = TypeVar("_R")
_T = TypeVar("_T")
_E = TypeVar("_E", bound=BaseException)


class BadParameter(ValueError): ...


class Exit(SystemExit):
    code: int | None
    def __init__(self, *, code: int | None = ...) -> None: ...


class _Colors:
    RED: str
    def __getattr__(self, name: str) -> str: ...


def echo(message: object = ..., *, err: bool = ...) -> None: ...

def secho(message: object = ..., *, fg: str | None = ..., err: bool = ...) -> None: ...


@overload
def Option(__default: EllipsisType, *names: str, **kwargs: Any) -> Any: ...

@overload
def Option(__default: _T, *names: str, **kwargs: Any) -> _T: ...


@overload
def Argument(__default: EllipsisType, *names: str, **kwargs: Any) -> Any: ...

@overload
def Argument(__default: _T, *names: str, **kwargs: Any) -> _T: ...


def progressbar(iterable: Iterable[_T], *, label: str | None = ...) -> ContextManager[Iterable[_T]]: ...


class Typer:
    def __init__(self, *, help: str | None = ..., add_completion: bool = ...) -> None: ...

    def command(self, name: str | None = ..., **kwargs: Any) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]: ...

    def callback(self, **kwargs: Any) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]: ...

    def add_typer(self, typer: Typer, *, name: str | None = ..., **kwargs: Any) -> None: ...

    def exception_handler(
        self, exception_type: type[_E]
    ) -> Callable[[Callable[[_E], Any]], Callable[[_E], Any]]: ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


colors: _Colors
