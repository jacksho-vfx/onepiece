"""Public package exposing the Trafalgar dashboard application."""

from apps.trafalgar import web as web  # re-export for convenience
from apps.trafalgar.version import TRAFALGAR_VERSION

__all__ = ["web", "TRAFALGAR_VERSION"]
