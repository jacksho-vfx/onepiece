"""
Configuration loader for OnePiece ShotGrid client.

Reads from environment variables (or a .env file) and provides
a strongly-typed Settings object.

Environment variables:

    ONEPIECE_SHOTGRID_URL # e.g. https://mystudio.shotgrid.autodesk.com
    ONEPIECE_SHOTGRID_SCRIPT # API script name
    ONEPIECE_SHOTGRID_KEY # API script key
"""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class ShotGridSettings(BaseSettings):
    base_url: str
    script_name: str
    api_key: str

    model_config = SettingsConfigDict(
        env_prefix="ONEPIECE_SHOTGRID_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def load_config() -> ShotGridSettings:
    """
    Load configuration from environment variables or .env file.
    Will raise a ValidationError if required keys are missing.
    """
    return ShotGridSettings(
        base_url=os.getenv("ONEPIECE_SHOTGRID_URL", ""),
        script_name=os.getenv("ONEPIECE_SHOTGRID_SCRIPT", ""),
        api_key=os.getenv("ONEPIECE_SHOTGRID_KEY", ""),
    )
