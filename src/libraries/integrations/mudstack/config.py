"""Configuration loader for the OnePiece Mudstack client.

The settings model reads the following environment variables (optionally from a
``.env`` file when running locally):

``ONEPIECE_MUDSTACK_URL``
    Base URL of the Mudstack tenant to target.
``ONEPIECE_MUDSTACK_API_KEY`` / ``MUDSTACK_API_KEY``
    Personal access token used for authentication.
``ONEPIECE_MUDSTACK_WORKSPACE`` / ``MUDSTACK_WORKSPACE``
    Optional workspace or organisation hint sent as a header when provided.
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MudstackSettings(BaseSettings):
    base_url: str = Field(
        validation_alias=AliasChoices(
            "ONEPIECE_MUDSTACK_URL",
            "MUDSTACK_URL",
            "MUDSTACK_BASE_URL",
            "base_url",
        )
    )
    api_key: str = Field(
        validation_alias=AliasChoices(
            "ONEPIECE_MUDSTACK_API_KEY",
            "MUDSTACK_API_KEY",
            "api_key",
            "token",
        )
    )
    workspace: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ONEPIECE_MUDSTACK_WORKSPACE",
            "MUDSTACK_WORKSPACE",
            "workspace",
        ),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def load_config() -> MudstackSettings:
    """Load configuration from environment variables or the optional ``.env`` file."""

    return MudstackSettings()
