"""Server settings from environment variables (.env), read once at startup.

Changing a setting means editing .env and restarting the server.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # English is always on; Spanish and Japanese indexes load only when enabled.
    enable_spanish: bool = False
    enable_japanese: bool = False
    # When false, prices, offers, and the minimum buy price are in USD.
    convert_to_mxn: bool = True

    @property
    def languages(self) -> tuple[str, ...]:
        langs = ["en"]
        if self.enable_spanish:
            langs.append("es")
        if self.enable_japanese:
            langs.append("ja")
        return tuple(langs)


@lru_cache
def get_settings() -> Settings:
    return Settings()
