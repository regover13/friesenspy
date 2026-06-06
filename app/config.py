from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="config.env", extra="ignore")

    CALLSIGN_PREFIX: str = "FRS"
    SECRET_KEY: str
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    VATSIM_POLL_INTERVAL: int = 15
    DB_PATH: str = "/opt/friesenspy/data/friesenspy.db"
    STATSIM_API_KEY: str = ""
    OPENAIP_API_KEY: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
