"""Trafalgar dashboard utilities and CLI entry points."""

from typing import TYPE_CHECKING, Any

from . import web as web
from .version import TRAFALGAR_VERSION, __version__

if TYPE_CHECKING:  # pragma: no cover - only for static analysis
    from typer import Typer

    app: Typer
    web_app: Typer


class _MissingTyperCallable:
    """Placeholder that raises a helpful error when Typer is unavailable."""

    __slots__ = ("_dependency", "_target")

    def __init__(self, dependency: str, target: str) -> None:
        self._dependency = dependency
        self._target = target

    def _raise(self) -> None:
        raise RuntimeError(
            f"{self._target} requires the optional dependency '{self._dependency}'. "
            "Install it to use the Trafalgar CLI."
        )

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - simple passthrough
        self._raise()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        self._raise()


def _load_typer_apps() -> tuple[Any, Any]:
    try:
        from apps.trafalgar.app import app as typer_app, web_app as typer_web_app
    except (
        ModuleNotFoundError
    ) as exc:  # pragma: no cover - exercised when typer missing
        if exc.name != "typer":
            raise
        placeholder = _MissingTyperCallable("typer", "apps.trafalgar.app")
        return placeholder, placeholder
    else:
        return typer_app, typer_web_app


app, web_app = _load_typer_apps()

__all__ = ["app", "web", "web_app", "TRAFALGAR_VERSION", "__version__"]
