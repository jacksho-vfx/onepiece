"""Tests for shared DCC helper utilities."""

from __future__ import annotations

import pytest

from libraries.creative.dcc.utils import normalize_frame_range, sanitize_token


def test_sanitize_token_uppercases_and_replaces_non_alnum() -> None:
    assert sanitize_token(" hero:Main  ") == "HERO_MAIN"


def test_sanitize_token_uses_sanitized_fallback() -> None:
    assert sanitize_token(None) == "UNTITLED"
    assert sanitize_token("", fallback="unknown value") == "UNKNOWN_VALUE"


@pytest.mark.parametrize(
    "frame_range,expected",
    [
        ((100.2, 110.7), (100, 111)),
        ((-1.2, 5.9), (-1, 6)),
    ],
)
def test_normalize_frame_range_rounds_to_ints(
    frame_range: tuple[float, float], expected: tuple[int, int]
) -> None:
    assert normalize_frame_range(frame_range) == expected


def test_normalize_frame_range_handles_none_when_allowed() -> None:
    assert normalize_frame_range(None, allow_none=True) is None


def test_normalize_frame_range_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        normalize_frame_range((10, 5))
    with pytest.raises(ValueError):
        normalize_frame_range(None)
