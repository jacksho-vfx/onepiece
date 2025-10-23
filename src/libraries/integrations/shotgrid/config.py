"""Configuration loader for the OnePiece ShotGrid client.

The settings model reads the following environment variables (optionally from a
``.env`` file when running locally):

``ONEPIECE_SHOTGRID_URL``
    Base URL of the ShotGrid site to target.
``ONEPIECE_SHOTGRID_SCRIPT``
    API script identifier used for authentication.
``ONEPIECE_SHOTGRID_KEY``
    API script secret paired with the script identifier.
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ShotGridSettings(BaseSettings):
    base_url: str = Field(
        validation_alias=AliasChoices(
            "ONEPIECE_SHOTGRID_URL", "SHOTGRID_URL", "base_url"
        )
    )
    script_name: str = Field(
        validation_alias=AliasChoices(
            "ONEPIECE_SHOTGRID_SCRIPT", "SHOTGRID_SCRIPT", "script", "script_name"
        )
    )
    api_key: str = Field(
        validation_alias=AliasChoices(
            "ONEPIECE_SHOTGRID_KEY", "SHOTGRID_KEY", "api_key", "key"
        )
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def load_config() -> ShotGridSettings:
    """Load configuration from environment variables or the optional ``.env`` file."""

    # ``BaseSettings`` already knows how to pull values from the environment (or
    # ``.env``) using the declared ``env_prefix``.  The previous implementation
    # fetched the variables manually and defaulted to empty strings when they
    # were missing.  That bypassed ``BaseSettings``' validation and silently
    # produced ``ShotGridSettings`` objects with blank credentials, leading to
    # confusing authentication failures at runtime.  Instantiating the settings
    # class directly delegates to pydantic which will raise a ``ValidationError``
    # when required values are absent, giving callers actionable feedback.
    return ShotGridSettings()
