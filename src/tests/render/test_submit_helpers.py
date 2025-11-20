from __future__ import annotations

import pytest

from apps.onepiece.render.submit.helpers import resolve_priority_and_chunk_size
from apps.onepiece.utils.errors import OnePieceValidationError


@pytest.mark.parametrize(
    "capabilities",
    [
        {
            "chunk_size_enabled": True,
            "default_chunk_size": 1,
            "chunk_size_min": 2,
            "chunk_size_max": 5,
        },
        {
            "chunk_size_enabled": True,
            "default_chunk_size": 6,
            "chunk_size_min": 2,
            "chunk_size_max": 5,
        },
    ],
)
def test_invalid_adapter_default_chunk_size_raises(
    capabilities: dict[str, int]
) -> None:
    with pytest.raises(OnePieceValidationError):
        resolve_priority_and_chunk_size(
            farm="mock",
            priority=None,
            chunk_size=None,
            capabilities=capabilities,
            optimize=False,
        )


def test_chunk_size_at_minimum_allowed() -> None:
    _, resolved_chunk, _, _ = resolve_priority_and_chunk_size(
        farm="mock",
        priority=None,
        chunk_size=None,
        capabilities={
            "chunk_size_enabled": True,
            "default_chunk_size": 2,
            "chunk_size_min": 2,
            "chunk_size_max": 5,
        },
        optimize=False,
    )

    assert resolved_chunk == 2


def test_chunk_size_at_maximum_allowed() -> None:
    _, resolved_chunk, _, _ = resolve_priority_and_chunk_size(
        farm="mock",
        priority=None,
        chunk_size=5,
        capabilities={
            "chunk_size_enabled": True,
            "default_chunk_size": 3,
            "chunk_size_min": 2,
            "chunk_size_max": 5,
        },
        optimize=False,
    )

    assert resolved_chunk == 5
