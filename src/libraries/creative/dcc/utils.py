"""Shared helpers for sanitizing tokens and normalizing frame ranges."""

from __future__ import annotations

FrameRangeLike = tuple[int | float, int | float]
FrameRange = tuple[int, int]


def _clean_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip())
    cleaned = cleaned.strip("_")
    return cleaned.upper()


def sanitize_token(token: str | None, *, fallback: str = "UNTITLED") -> str:
    """Return a normalized token suitable for filenames and identifiers.

    Parameters
    ----------
    token:
        The raw token to sanitize. ``None`` or empty values will cause the
        ``fallback`` to be used instead.
    fallback:
        Value to return when ``token`` does not contain any alphanumeric
        characters. The fallback itself will be sanitized using the same rules
        to guarantee a consistent output format.
    """

    if token:
        cleaned = _clean_token(token)
        if cleaned:
            return cleaned

    fallback_cleaned = _clean_token(fallback)
    if fallback_cleaned:
        return fallback_cleaned

    raise ValueError("fallback must contain at least one alphanumeric character")


def normalize_frame_range(
    frame_range: FrameRangeLike | None,
    *,
    allow_none: bool = False,
) -> FrameRange | None:
    """Normalize ``frame_range`` into an integer tuple.

    Parameters
    ----------
    frame_range:
        Two-value sequence representing the start and end frames.
    allow_none:
        When ``True`` and ``frame_range`` is ``None`` the function will return
        ``None`` instead of raising a :class:`ValueError`.
    """

    if frame_range is None:
        if allow_none:
            return None
        raise ValueError("frame_range cannot be None")

    start_raw, end_raw = frame_range
    start = int(round(float(start_raw)))
    end = int(round(float(end_raw)))
    if start > end:
        raise ValueError("frame_range start must be <= end")
    return (start, end)


__all__ = ["sanitize_token", "normalize_frame_range"]
