"""Simple strategy implementations for the Hypothesis stub."""

from __future__ import annotations

import random
import string
from typing import Any, Callable


_RANDOM = random.Random(0)


class Strategy:
    def __init__(self, generator: Callable[[], Any]) -> None:
        self._generator = generator

    def example(self) -> Any:
        return self._generator()

    def filter(self, predicate: Callable[[Any], bool]) -> "Strategy":
        def generator() -> Any:
            for _ in range(100):
                value = self._generator()
                if predicate(value):
                    return value
            raise RuntimeError("filter condition could not be satisfied")

        return Strategy(generator)


def integers(*, min_value: int = 0, max_value: int = 100) -> Strategy:
    def generator() -> int:
        return _RANDOM.randint(min_value, max_value)

    return Strategy(generator)


def text(*, min_size: int = 0, max_size: int = 8) -> Strategy:
    alphabet = string.ascii_letters + string.digits

    def generator() -> str:
        size = _RANDOM.randint(min_size, max_size)
        return "".join(_RANDOM.choice(alphabet) for _ in range(size))

    return Strategy(generator)


def builds(function: Callable[..., Any], **strategies: Strategy) -> Strategy:
    def generator() -> Any:
        values = {name: strategy.example() for name, strategy in strategies.items()}
        return function(**values)

    return Strategy(generator)


def lists(
    element_strategy: Strategy,
    *,
    max_size: int = 10,
    unique_by: Callable[[Any], Any] | None = None,
) -> Strategy:
    def generator() -> list[Any]:
        size = _RANDOM.randint(0, max_size)
        values: list[Any] = []
        seen: set[Any] = set()
        attempts = 0
        while len(values) < size and attempts < max(1, size * 5):
            candidate = element_strategy.example()
            key = unique_by(candidate) if unique_by else candidate
            if unique_by:
                if key in seen:
                    attempts += 1
                    continue
                seen.add(key)
            values.append(candidate)
        return values

    return Strategy(generator)


__all__ = [
    "Strategy",
    "builds",
    "integers",
    "lists",
    "text",
]
