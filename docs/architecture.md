# Architektur

## Überblick

```
VATSIM Data API (15s)
        │
        ▼
  VatsimPoller (APScheduler)
        │
        ├─► filter_friesen_pilots(callsign_prefix)
        │         → alle Piloten mit Callsign FRS*
        │
        ├─► Flug-State-Machine
        │         newly_online → open_flight, Telegram-Alert
        │         still_online → update position
        │         went_offline → close_flight
        │
        ├─► SQLite WAL (positions, flights, history)
        │
        └─► asyncio.Queue → SSE-Stream → Browser
```

## Module

### `app/config.py`

pydantic-settings liest `config.env` oder Umgebungsvariablen. `get_settings()` ist mit `@lru_cache` als Singleton implementiert — einmal geladen, für die Prozess-Lebensdauer gecacht.

Einzige Pflichtfield: `SECRET_KEY`. Alle anderen haben sinnvolle Defaults.

### `app/vatsim.py`

Zwei öffentliche Funktionen:

- `fetch_vatsim_data(client)` — HTTP GET auf `https://data.vatsim.net/v3/vatsim-data.json`, gibt geparsten JSON-Dict zurück. Wirft `httpx.HTTPError` bei Fehler, wird in `_poll_once` gecatcht.

- `filter_friesen_pilots(callsign_prefix, vatsim_data)` — filtert Piloten-Liste nach Callsign-Prefix (case-insensitiv). Kein CID-Lookup, keine externe Abhängigkeit.

- `pilot_to_position(pilot)` — normalisiert rohe VATSIM-Daten in ein flaches Dict mit 13 Feldern. Null-`flight_plan` wird graceful behandelt (leere Strings).

### `app/database.py`

SQLite mit WAL-Mode und `PRAGMA foreign_keys=ON`. Vier Tabellen:

| Tabelle | Inhalt |
|---------|--------|
| `pilots` | CID + Name (INSERT OR IGNORE — niemals überschrieben) |
| `flights` | Pro Flug: Callsign, Typ, DEP/ARR, Logon/Logoff, Dauer |
| `live_positions` | Aktuelle Position pro CID (UPSERT, maximal 1 Zeile pro CID) |
| `position_history` | Jede einzelne VATSIM-Positions-Update (für Tracks + Events) |

Drei Indizes: `idx_ph_cid_ts`, `idx_ph_ts`, `idx_flights_cid`.

Alle DB-Operationen sind synchron (SQLite ist thread-safe mit WAL). Verbindungen werden pro Request geöffnet und in `finally`-Blöcken geschlossen.

### `app/poller.py`

`VatsimPoller` kapselt:
- **APScheduler `AsyncIOScheduler`** mit zwei Jobs: `vatsim_poll` (interval, 15s) und `daily_cleanup` (cron, 03:00)
- **`_active_flights: dict[int, int]`** — In-Memory State: CID → flight_id. Überlebt nicht einen Container-Neustart (Flüge die beim Restart offen sind, bleiben in der DB offen ohne Logoff-Zeit).
- **`sse_queue: asyncio.Queue`** — Jeder SSE-Client hat eine eigene Verbindung zum selben Queue-Objekt. `put_nowait` blockiert nicht.

Die Flug-State-Machine in `_poll_once`:

```
CIDs jetzt online: {A, B, C}
CIDs vorher aktiv: {B, C, D}

newly_online  = {A}       → open_flight, Alert
still_online  = {B, C}    → update position
went_offline  = {D}       → close_flight
```

Ein einziges `conn.commit()` am Ende — kein partieller Schreibzustand möglich.

### `app/geo.py`

- `haversine(lat1, lon1, lat2, lon2)` — Großkreis-Abstand in km
- `icao_to_coords(icao)` — ICAO → (lat, lon) via `airportsdata`-Package (keine Netzwerk-Anfrage, statische Daten)
- `filter_event_pilots(rows, icao_list, radius_km, start_utc, end_utc)` — filtert `position_history`-Zeilen auf Piloten die im Zeitfenster innerhalb von `radius_km` um einen der ICAOs waren

### `app/alerts.py`

Telegram-Alert beim "Online gehen" eines Piloten. Alle VATSIM-Felder werden mit `html.escape()` sanitized bevor sie in den `parse_mode=HTML` Telegram-Body eingebettet werden. Fehler werden nur als `type(e).__name__` geloggt (kein Full-Exception-String, der den Token in der Telegram-API-URL exponieren würde).

### `app/main.py`

FastAPI mit `lifespan`-Kontext-Manager (startup: DB init + Poller start; shutdown: Poller stop).

Der SSE-Endpoint (`/api/sse`) sendet alle 30 Sekunden einen `: keepalive`-Kommentar, um Proxy-Timeouts zu verhindern. Nginx ist mit `proxy_read_timeout 3600s` konfiguriert.

### `app/static/index.html`

Single-File-SPA (~1400 Zeilen) ohne Build-Step. Vier Tabs:

- **LIVE** — EventSource(`/api/sse`) mit automatischem Reconnect (5s Delay)
- **KARTE** — Leaflet.js mit CartoDB Dark Matter Tiles, SVG-Flugzeug-Marker
- **STATISTIKEN** — Chart via `/api/stats?days=N`
- **EVENTS** — Formular → `/api/events`

Design: Phosphoreszierender ATC-Radar-Look (`#060d0a` Hintergrund, `#39e75f` Grün).

## Datenfluss SSE

```
Browser                     FastAPI                  VatsimPoller
   │                           │                          │
   │─── GET /api/sse ──────────►│                          │
   │                           │                          │
   │                           │◄─── sse_queue.get() ─────│
   │                           │     (wartet bis Event)   │
   │                           │                          │
   │                           │    (15s später)          │
   │                           │    VATSIM poll ──────────►│
   │                           │                          │─ State-Machine
   │                           │                          │─ SQLite commit
   │                           │◄─── put_nowait({...}) ───│
   │                           │                          │
   │◄── data: {...}\n\n ────────│                          │
```

## Datenbankschema

```sql
CREATE TABLE pilots (
    cid       INTEGER PRIMARY KEY,
    name      TEXT NOT NULL
);

CREATE TABLE flights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cid           INTEGER NOT NULL REFERENCES pilots(cid),
    callsign      TEXT NOT NULL,
    aircraft      TEXT,
    departure     TEXT,
    arrival       TEXT,
    logon_time    TEXT NOT NULL,
    logoff_time   TEXT,
    duration_min  INTEGER
);

CREATE TABLE live_positions (
    cid           INTEGER PRIMARY KEY REFERENCES pilots(cid),
    callsign      TEXT NOT NULL,
    aircraft      TEXT,
    departure     TEXT,
    arrival       TEXT,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    altitude      INTEGER,
    groundspeed   INTEGER,
    heading       INTEGER,
    logon_time    TEXT,
    updated_at    TEXT NOT NULL
);

CREATE TABLE position_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cid         INTEGER NOT NULL REFERENCES pilots(cid),
    callsign    TEXT NOT NULL,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    altitude    INTEGER,
    groundspeed INTEGER,
    heading     INTEGER,
    ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
```
