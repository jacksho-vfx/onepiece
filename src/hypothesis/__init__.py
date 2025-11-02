"""A minimal subset of the Hypothesis API required by the tests."""

from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Callable

from . import strategies
from .strategies import Strategy


class _Settings:
    def __init__(self) -> None:
        self._profiles: dict[str, dict[str, Any]] = {}
        self._current_profile: str | None = None

    def register_profile(self, name: str, **config: Any) -> None:
        self._profiles[name] = dict(config)

    def load_profile(self, name: str) -> None:
        if name not in self._profiles:
            self._profiles[name] = {}
        self._current_profile = name


class HealthCheck:
    too_slow = "too_slow"


settings = _Settings()


def given(*strategy_args: Strategy, **strategy_kwargs: Strategy) -> Callable[[Callable[..., Any]], Callable[..., None]]:
    """Simplified replacement for :func:`hypothesis.given`.

    The decorator executes the wrapped test function a handful of times using
    examples generated from the supplied strategies.  This provides enough
    coverage for the property-based tests included with the exercises while
    keeping the implementation compact.
    """

    def decorator(test_func: Callable[..., Any]) -> Callable[..., None]:
        @wraps(test_func)
        def wrapper(*args: Any, **kwargs: Any) -> None:
            for _ in range(5):
                generated_args = [strategy.example() for strategy in strategy_args]
                generated_kwargs = {
                    name: strategy.example() for name, strategy in strategy_kwargs.items()
                }
                test_func(*args, *generated_args, **{**kwargs, **generated_kwargs})

        wrapper.__signature__ = inspect.Signature()  # type: ignore[attr-defined]
        return wrapper

    return decorator


__all__ = ["given", "strategies", "settings", "HealthCheck"]
