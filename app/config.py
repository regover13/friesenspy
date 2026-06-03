from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="config.env", extra="ignore")

    FRIESENFLIEGER_CIDS: str = ""
    SECRET_KEY: str
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    VATSIM_POLL_INTERVAL: int = 15
    DB_PATH: str = "/opt/friesenspy/data/friesenspy.db"

    @field_validator("FRIESENFLIEGER_CIDS", mode="before")
    @classmethod
    def _parse_cids_raw(cls, v: object) -> object:
        # Keep raw value; actual list parsing happens via a property
        return v

    @property
    def cids(self) -> List[int]:
        """Return parsed list of CIDs from the comma-separated string."""
        raw = self.FRIESENFLIEGER_CIDS.strip()
        if not raw:
            return []
        return [int(cid.strip()) for cid in raw.split(",") if cid.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
