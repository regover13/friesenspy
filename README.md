# FriesenSpy

VATSIM Live-Tracker für die FriesenFlieger Virtual Airline. Zeigt wer von der Gruppe gerade online fliegt — mit Live-Karte, Statistiken und Event-Suche.

**Live:** https://friesenspy.devprops.de

---

## Features

- **Live-Tab** — Echtzeit-Liste aller Friesen online (SSE); Callsign klicken → Flugplan-Modal; ◎ klicken → direkt zur Karte mit Zentrierung
- **Karte** — Leaflet.js mit Flugzeug-Symbolen, Heading-Rotation, Popup mit Details
- **Statistiken** — Letzter Flug + Anzahl pro Pilot (30/90/365 Tage); Pilot anklicken → Einzelflüge (mind. 365 Tage, „Alle laden" für volle Historik seit 2020); ◎ → Track auf Karte
- **Event-Suche** — Wer war bei einem Event in der Nähe von ICAO XY dabei? Mit Track-Anzeige auf Karte
- **StatSim-Integration** — Historische Flüge seit 2020 via [StatSim API](https://statsim.net) (API-Key nötig)
- **Telegram-Alerts** — Optional: Nachricht wenn ein Friese online geht

## Wie funktioniert das?

FriesenSpy erkennt Friesen-Piloten automatisch am Callsign-Prefix **`FRS`** (konfigurierbar). VATSIM-Daten werden alle 15 Sekunden von der [VATSIM Data API](https://data.vatsim.net/v3/vatsim-data.json) abgerufen — kein Account, keine CID-Liste nötig.

## Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11, FastAPI, APScheduler |
| Datenbank | SQLite (WAL-Mode) |
| HTTP-Client | httpx (async) |
| Frontend | Vanilla JS, Leaflet.js (Single-Page-App) |
| Deployment | Docker, GitHub Actions → GHCR → SSH |

---

## Lokale Entwicklung

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# config.env anlegen (SECRET_KEY ist Pflicht)
cp config.env.example config.env   # dann editieren

# Server starten
uvicorn app.main:app --reload
# → http://localhost:8091
```

### config.env

```bash
SECRET_KEY=<beliebiger-zufalls-string>     # Pflicht
CALLSIGN_PREFIX=FRS                         # Default: FRS
VATSIM_POLL_INTERVAL=15                     # Sekunden, Default: 15
DB_PATH=friesenspy.db                       # Lokal: relativer Pfad OK
TELEGRAM_BOT_TOKEN=                         # Optional
TELEGRAM_CHAT_ID=                           # Optional
STATSIM_API_KEY=                            # Optional: historische Flüge via statsim.net
```

### Tests

```bash
pytest tests/ -v
```

169 Tests, keine externen Abhängigkeiten (alles gemockt).

---

## Deployment

GitHub Push auf `main` → GitHub Actions baut Docker-Image → pushed nach GHCR → SSH-Deploy auf VPS.

```
main branch
    └─► GitHub Actions (.github/workflows/deploy.yml)
            └─► docker build → ghcr.io/regover13/friesenspy:latest
                    └─► SSH: docker compose pull + up -d
```

### GitHub Secrets (einmalig)

| Secret | Inhalt |
|--------|--------|
| `VPS_SSH_KEY` | Privater SSH-Key für `root@167.86.127.129` |
| `GHCR_TOKEN` | GitHub PAT mit `write:packages` |

### VPS-Einrichtung (einmalig)

```bash
# Verzeichnis + Daten-Volume
mkdir -p /opt/friesenspy/data
chown -R 1001:1001 /opt/friesenspy/data

# docker-compose.yml hochladen
scp docker-compose.yml root@167.86.127.129:/opt/friesenspy/

# config.env anlegen (NIE in Git!)
cat > /opt/friesenspy/config.env <<EOF
SECRET_KEY=$(openssl rand -hex 32)
CALLSIGN_PREFIX=FRS
VATSIM_POLL_INTERVAL=15
DB_PATH=/opt/friesenspy/data/friesenspy.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF

# nginx + certbot
cp nginx/friesenspy.devprops.de.conf /etc/nginx/sites-available/
ln -s /etc/nginx/sites-available/friesenspy.devprops.de.conf /etc/nginx/sites-enabled/
certbot --nginx -d friesenspy.devprops.de
nginx -s reload

# Ersten Start auslösen (oder warten auf GitHub-Push)
cd /opt/friesenspy && docker compose up -d
```

---

## Projektstruktur

```
FriesenSpy/
├── app/
│   ├── main.py        # FastAPI-App, REST + SSE-Endpoints
│   ├── config.py      # pydantic-settings (liest config.env)
│   ├── database.py    # SQLite WAL, alle DB-Funktionen
│   ├── vatsim.py      # VATSIM-API-Client + Callsign-Filter
│   ├── statsim.py     # StatSim API-Client (historische Flüge)
│   ├── geo.py         # Haversine, ICAO→Koordinaten, Event-Filter
│   ├── alerts.py      # Telegram-Alerts (silent fail)
│   ├── poller.py      # APScheduler, Flug-State-Machine, SSE-Queue
│   └── static/
│       └── index.html # Vanilla-JS-SPA (4 Tabs)
├── tests/             # 169 pytest-Tests
├── docs/              # Architektur, API, Deployment
├── nginx/             # nginx-Konfiguration für friesenspy.devprops.de
├── .github/workflows/ # CI/CD: Build → GHCR → SSH-Deploy
├── Dockerfile
└── docker-compose.yml
```

---

## API

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/` | GET | SPA (index.html) |
| `/health` | GET | `{"status": "ok"}` |
| `/api/live` | GET | Aktuelle Live-Positionen (inkl. Flugplan-Felder) |
| `/api/stats?days=30` | GET | Letzter Flug + Fluganzahl pro Pilot |
| `/api/pilots/{cid}/flights?days=365` | GET | Einzelflüge eines Piloten (FriesenSpy + StatSim, min. 365 Tage); `days=0` = alles seit 2020 |
| `/api/flights/{id}/track` | GET | GPS-Track eines FriesenSpy-Fluges |
| `/api/flights/statsim/{id}/track` | GET | GPS-Track eines StatSim-Fluges |
| `/api/events?icao=EDDK&radius=150&start=...&end=...` | GET | Event-Teilnehmer mit Tracks |
| `/api/sse` | GET | Server-Sent Events Stream |

Details: siehe [docs/api.md](docs/api.md)
