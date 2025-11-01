from __future__ import annotations

from collections.abc import Iterator

import pytest

from apps.perona.web import wrangler as wrangler_module


@pytest.fixture(autouse=True)
def _reset_wrangler_registry() -> Iterator[None]:
    wrangler_module._reset_registry()
    try:
        yield
    finally:
        wrangler_module._reset_registry()
