"""Utility types for consistent CLI error handling."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Standardised exit codes for the OnePiece CLI."""

    SUCCESS = 0
    VALIDATION = 1
    IO = 2
    CONFIG = 3
    EXTERNAL = 4
    RUNTIME = 5


class OnePieceError(Exception):
    """Base for predictable CLI errors that surface to users."""

    exit_code: ExitCode = ExitCode.RUNTIME
    label = "Error"

    def __init__(
        self, message: str, *, exit_code: ExitCode | int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if exit_code is None:
            exit_code = type(self).exit_code
        self.exit_code = ExitCode(exit_code)

    def __str__(self) -> str:  # pragma: no cover - exercised through Typer.
        return self.message

    @property
    def heading(self) -> str:
        """Return a short label describing the error class."""

        return type(self).label


class OnePieceValidationError(OnePieceError):
    """Raised when user input fails validation checks."""

    exit_code = ExitCode.VALIDATION
    label = "Validation error"


class OnePieceIOError(OnePieceError):
    """Raised when filesystem or network I/O fails."""

    exit_code = ExitCode.IO
    label = "I/O error"


class OnePieceConfigError(OnePieceError):
    """Raised when configuration or environment is invalid."""

    exit_code = ExitCode.CONFIG
    label = "Configuration error"


class OnePieceExternalServiceError(OnePieceError):
    """Raised when an external dependency fails to respond correctly."""

    exit_code = ExitCode.EXTERNAL
    label = "External service error"


class OnePieceRuntimeError(OnePieceError):
    """Raised for unexpected runtime failures."""

    exit_code = ExitCode.RUNTIME
    label = "Runtime error"
