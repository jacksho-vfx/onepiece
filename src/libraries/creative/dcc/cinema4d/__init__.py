"""Cinema 4D specific helpers for OnePiece."""

from .cleanup import cleanup_scene
from .gather import GatherResult, gather_references
from .panel import CommandDefinition, CommandPanel, register_cleanup_command

__all__ = [
    "GatherResult",
    "gather_references",
    "CommandDefinition",
    "CommandPanel",
    "cleanup_scene",
    "register_cleanup_command",
]
