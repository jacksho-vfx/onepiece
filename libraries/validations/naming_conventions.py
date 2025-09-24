import re

SHOW_PATTERN = re.compile(r"^[a-zA-Z]+[0-9]{2}$")               # e.g., show01, blah01, stop10, frog99
EPISODE_PATTERN = re.compile(r"^ep\d{3}$", re.IGNORECASE)       # e.g., ep101
SCENE_PATTERN = re.compile(r"^sc\d{2}$", re.IGNORECASE)         # e.g., sc01
SHOT_PATTERN = re.compile(r"^\d{4}$")                            # e.g., 0010
SHOT_NAME_PATTERN = re.compile(r"^ep\d{3}_sc\d{2}_\d{4}$", re.IGNORECASE) # e.g., ep101_sc01_0010
ASSET_NAME_PATTERN = re.compile(r"^ep\d{3}_sc\d{2}_\d{4}_[a-zA-Z0-9]+$", re.IGNORECASE) # e.g., ep101_sc01_0010_asset

def validate_show_name(name: str) -> bool:
    return bool(SHOW_PATTERN.match(name))

def validate_episode_name(name: str) -> bool:
    return bool(EPISODE_PATTERN.match(name))

def validate_scene_name(name: str) -> bool:
    return bool(SCENE_PATTERN.match(name))

def validate_shot(name: str) -> bool:
    return bool(SHOT_PATTERN.match(name))

def validate_shot_name(name: str) -> bool:
    return bool(SHOT_NAME_PATTERN.match(name))

def validate_asset_name(name: str) -> bool:
    return bool(ASSET_NAME_PATTERN.match(name))
