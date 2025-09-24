"""Utility functions for validating production naming conventions."""

import re

__all__ = [
    "validate_show_name",
    "validate_episode_name",
    "validate_scene_name",
    "validate_shot",
    "validate_shot_name",
    "validate_asset_name",
]

_SHOW_PATTERN = re.compile(r"^[a-zA-Z]+[0-9]{2}$")
_EPISODE_PATTERN = re.compile(r"^ep\d{3}$", re.IGNORECASE)
_SCENE_PATTERN = re.compile(r"^sc\d{2}$", re.IGNORECASE)
_SHOT_PATTERN = re.compile(r"^\d{4}$")
_SHOT_NAME_PATTERN = re.compile(r"^ep\d{3}_sc\d{2}_\d{4}$", re.IGNORECASE)
_ASSET_NAME_PATTERN = re.compile(r"^ep\d{3}_sc\d{2}_\d{4}_[a-zA-Z0-9]+$", re.IGNORECASE)


def _matches(pattern: re.Pattern[str], value: str) -> bool:
    return bool(pattern.match(value))


def validate_show_name(name: str) -> bool:
    return _matches(_SHOW_PATTERN, name)


def validate_episode_name(name: str) -> bool:
    return _matches(_EPISODE_PATTERN, name)


def validate_scene_name(name: str) -> bool:
    return _matches(_SCENE_PATTERN, name)


def validate_shot(name: str) -> bool:
    return _matches(_SHOT_PATTERN, name)


def validate_shot_name(name: str) -> bool:
    return _matches(_SHOT_NAME_PATTERN, name)


def validate_asset_name(name: str) -> bool:
    return _matches(_ASSET_NAME_PATTERN, name)
