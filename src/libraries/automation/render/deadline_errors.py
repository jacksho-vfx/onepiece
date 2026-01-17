"""Shared Deadline error definitions."""

from __future__ import annotations


class DeadlineError(RuntimeError):
    """Base error raised for Deadline client issues."""


class DeadlineAuthenticationError(DeadlineError):
    """Raised when Deadline rejects the provided credentials."""


class DeadlineValidationError(DeadlineError):
    """Raised when Deadline rejects a job payload."""


class DeadlineUnavailableError(DeadlineError):
    """Raised when Deadline cannot be contacted or returns a server error."""


class DeadlineResponseError(DeadlineError):
    """Raised when Deadline returns an unexpected payload."""


__all__ = [
    "DeadlineError",
    "DeadlineAuthenticationError",
    "DeadlineValidationError",
    "DeadlineUnavailableError",
    "DeadlineResponseError",
]
