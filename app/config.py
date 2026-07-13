from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="config.env", extra="ignore")

    CALLSIGN_PREFIX: str = "FRS"
    SECRET_KEY: str
    # Passwort für die Admin-Seite (/admin) — NIE in git, nur in config.env. Leer = Admin aus.
    ADMIN_PASSWORD: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    VATSIM_POLL_INTERVAL: int = 15
    # Reconnect-Fenster für den Online-Push: geht ein Pilot innerhalb dieser Zeit erneut online
    # (vPilot-Reconnect), wird das als Reconnect gewertet und NICHT erneut gepusht.
    VATSIM_REJOIN_DEBOUNCE_SEC: int = 900
    DB_PATH: str = "/opt/friesenspy/data/friesenspy.db"
    STATSIM_API_KEY: str = ""
    OPENAIP_API_KEY: str = ""
    # Claude-API (FriesenKutter-Zuladungs-Vorschlag; Phase 2: Flug-Kommentare). Leer = deaktiviert.
    # Denselben Key wie TSBot verwenden (kein neues Secret).
    ANTHROPIC_API_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""   # PEM mit \\n-Escaping (z.B. aus generate_vapid.py)
    VAPID_CONTACT_EMAIL: str = ""
    # Log-Level für die App-Logger. Default INFO, damit Push-/Poll-Logs sichtbar sind
    # (unter uvicorn läuft der Root-Logger sonst auf WARNING → INFO-Zeilen verschwinden).
    LOG_LEVEL: str = "INFO"

    # TeamSpeak-ServerQuery (Phase 1: Login-Benachrichtigung)
    TS_NOTIFY_ENABLED: bool = False
    TS_HOST: str = "127.0.0.1"
    TS_QUERY_PORT: int = 10011
    TS_QUERY_USER: str = ""
    TS_QUERY_PASS: str = ""
    TS_SERVER_ID: int = 1
    TS_NOTIFY_CHANNEL_ID: int = 0   # 0 = ganzer Server
    TS_EXCLUDE_CHANNEL_IDS: str = ""  # Komma-separierte Kanal-IDs, die NIE benachrichtigen
    # Verweildauer-Bestätigung: Anzahl zusätzlicher Polls, die eine FRS präsent bleiben muss,
    # bevor benachrichtigt wird (0 = sofort beim ersten Erkennen; 1 = muss beim nächsten Poll
    # noch da sein → unterdrückt kurzes "Reinschauen").
    TS_MIN_DWELL_POLLS: int = 1
    TS_POLL_INTERVAL: int = 30
    TS_REJOIN_DEBOUNCE_SEC: int = 900

    # Forum-SSO (Board-Login) — Bridge sso.php auf board.friesenflieger.de.
    # Alle leer/Default = Board-Login inaktiv (unabhängig vom Admin-Schalter).
    SSO_SECRET: str = ""            # GETEILT mit sso.php; niemals in git
    FORUM_SSO_URL: str = ""         # z.B. https://board.friesenflieger.de/sso.php
    FORUM_SSO_CALLBACK: str = ""    # absolute URL zu /auth/forum/callback (muss der Whitelist in sso.php entsprechen)
    USER_SESSION_MAX_AGE_SEC: int = 3600  # kurze FriesenSpy-Session → spiegelt Forum-Logout verzögert


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
