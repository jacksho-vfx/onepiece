"""Cinema 4D specific helpers for OnePiece."""

from .cleanup import cleanup_scene
from .gather import GatherResult, gather_references
from .panel import CommandDefinition, CommandPanel, register_cleanup_command
from .script_library import (
    Cinema4DScript,
    default_script_directory,
    deploy_scripts_to_directory,
    discover_cinema4d_scripts,
)

__all__ = [
    "GatherResult",
    "gather_references",
    "CommandDefinition",
    "CommandPanel",
    "cleanup_scene",
    "register_cleanup_command",
    "Cinema4DScript",
    "default_script_directory",
    "deploy_scripts_to_directory",
    "discover_cinema4d_scripts",
]
