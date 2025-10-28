"""Dummy providers used within pipeline tests."""

from __future__ import annotations

from typing import Any


def uppercase_provider(value: str) -> str:
    """Return the uppercase version of ``value`` for visibility during tests."""

    return value.upper()


class Accumulator:
    """Simple callable provider accumulating received payloads."""

    def __init__(self) -> None:
        self.payloads: list[Any] = []

    def __call__(self, payload: Any) -> list[Any]:
        self.payloads.append(payload)
        return list(self.payloads)
