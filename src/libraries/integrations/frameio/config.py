"""Configuration loader for Frame.io API access."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FrameioSettings(BaseSettings):
    base_url: str = Field(
        default="https://api.frame.io",
        validation_alias=AliasChoices(
            "ONEPIECE_FRAMEIO_URL", "FRAMEIO_URL", "base_url"
        ),
    )
    api_token: str = Field(
        validation_alias=AliasChoices(
            "ONEPIECE_FRAMEIO_TOKEN",
            "ONEPIECE_FRAMEIO_API_TOKEN",
            "FRAMEIO_TOKEN",
            "FRAMEIO_API_TOKEN",
            "api_token",
            "token",
        )
    )
    team_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ONEPIECE_FRAMEIO_TEAM",
            "ONEPIECE_FRAMEIO_TEAM_ID",
            "FRAMEIO_TEAM",
            "FRAMEIO_TEAM_ID",
            "team_id",
            "team",
        ),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def load_config() -> FrameioSettings:
    """Load configuration from the environment or ``.env`` file."""

    return FrameioSettings()
