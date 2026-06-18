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
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""   # PEM mit \\n-Escaping (z.B. aus generate_vapid.py)
    VAPID_CONTACT_EMAIL: str = ""

    # TeamSpeak-ServerQuery (Phase 1: Login-Benachrichtigung)
    TS_NOTIFY_ENABLED: bool = False
    TS_HOST: str = "127.0.0.1"
    TS_QUERY_PORT: int = 10011
    TS_QUERY_USER: str = ""
    TS_QUERY_PASS: str = ""
    TS_SERVER_ID: int = 1
    TS_NOTIFY_CHANNEL_ID: int = 0   # 0 = ganzer Server
    TS_POLL_INTERVAL: int = 30
    TS_REJOIN_DEBOUNCE_SEC: int = 900


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
