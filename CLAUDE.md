# FriesenSpy

VATSIM Live-Tracker für die FriesenFlieger-Gruppe.

## Stack

Python 3.11, FastAPI, APScheduler, SQLite (WAL), httpx, pydantic-settings, airportsdata, ts3

## Lokale Entwicklung

```bash
pip install -r requirements.txt
# config.env anlegen (SECRET_KEY + FRIESENFLIEGER_CIDS erforderlich)
uvicorn app.main:app --reload
# http://localhost:8091
```

## Tests

```bash
pytest tests/ -v
```

## Deployment

GitHub Push → main-Branch → GitHub Actions → GHCR → SSH-Deploy auf VPS

- Container: `ghcr.io/regover13/friesenspy:latest`
- Port: 8091 (intern), friesenspy.devprops.de (extern)
- DB: `/opt/friesenspy/data/friesenspy.db` (Volume)
- Config: `/opt/friesenspy/config.env` (niemals in git!)

## VPS-Einrichtung (einmalig)

```bash
mkdir -p /opt/friesenspy/data
# config.env anlegen mit echten CIDs + Token
# nginx-Config: nginx/friesenspy.devprops.de.conf einbinden
# certbot: certbot --nginx -d friesenspy.devprops.de
```

## Projektstruktur

- `app/config.py` — pydantic-settings, FRIESENFLIEGER_CIDS
- `app/database.py` — SQLite WAL, alle DB-Funktionen
- `app/vatsim.py` — VATSIM-API-Client
- `app/geo.py` — Haversine, ICAO→Koordinaten, Event-Filter
- `app/alerts.py` — Telegram-Alerts (silent fail)
- `app/teamspeak.py` — TeamSpeak-ServerQuery-Client (parse_frs, fetch_channel_clients)
- `app/ts_notify.py` — Empfänger-Auswahl für TS-Login-Benachrichtigungen (recipients_for)
- `app/poller.py` — APScheduler, Flug-State-Machine, SSE-Queue
- `app/main.py` — FastAPI-App, REST + SSE-Endpoints
- `app/static/index.html` — Vanilla-JS-SPA (4 Tabs)

## Konfiguration (config.env — NIE in git)

```bash
FRIESENFLIEGER_CIDS=1234567,8901234,...
SECRET_KEY=<random-string>
TELEGRAM_BOT_TOKEN=          # Optional
TELEGRAM_CHAT_ID=            # Optional
VATSIM_POLL_INTERVAL=15
DB_PATH=/opt/friesenspy/data/friesenspy.db

# TeamSpeak-Login-Benachrichtigung (Phase 1, alle Optional)
TS_NOTIFY_ENABLED=false      # Default: false — Feature aktivieren
TS_HOST=127.0.0.1            # Default: 127.0.0.1
TS_QUERY_PORT=10011          # Default: 10011
TS_QUERY_USER=               # ServerQuery-Login
TS_QUERY_PASS=               # ServerQuery-Passwort
TS_SERVER_ID=1               # Default: 1
TS_NOTIFY_CHANNEL_ID=0       # Default: 0 = ganzer Server; sonst Kanal-ID
TS_EXCLUDE_CHANNEL_IDS=      # CSV Kanal-IDs, die nie benachrichtigen (z. B. Verwaltung)
TS_POLL_INTERVAL=30          # Default: 30 Sekunden
TS_REJOIN_DEBOUNCE_SEC=900   # Default: 900 s (15 min) Debounce gegen Re-Join-Spam
```
