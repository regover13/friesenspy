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

Pflichtfelder: `SECRET_KEY`. Optional: `STATSIM_API_KEY` für historische Flugdaten.

### `app/vatsim.py`

- `fetch_vatsim_data(client)` — HTTP GET auf die VATSIM Data API, gibt geparsten JSON-Dict zurück.
- `filter_friesen_pilots(callsign_prefix, vatsim_data)` — filtert Piloten-Liste nach Callsign-Prefix (case-insensitiv).
- `pilot_to_position(pilot)` — normalisiert rohe VATSIM-Daten in ein flaches Dict mit 22 Feldern, inkl. aller `flight_plan`-Details (flight_rules, aircraft_icao, route, remarks, …).

### `app/statsim.py`

StatSim API-Client für historische Flugdaten (Daten ab 2020-01-22).

- `fetch_pilot_flights(client, cid, api_key, days)` — paginierte Abfrage in ≤31-Tage-Chunks. Fehlerhafte Chunks werden einzeln übersprungen (kein Abbruch der Gesamtabfrage). Timeout: 30s. Silent fail → []. Normalisiert Felder: `statsim_id`, `callsign`, `departure`, `arrival`, `aircraft`, `logon_time`, `logoff_time`, `duration_min`.
- `fetch_flight_track(client, statsim_id, api_key)` — GPS-Track eines einzelnen Fluges. Silent fail → [].

StatSim API: `https://api.statsim.net`, Auth: `X-API-Key` Header, max. 31 Tage pro Query.

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
- `segment_into_flights(positions, flights_rows)` — gruppiert Positionen anhand echter VATSIM-Session-Records aus der `flights`-Tabelle; jedes Segment erhält `callsign`, `departure`, `arrival`, `aircraft` aus dem passenden `flights`-Eintrag. Fallback auf Zeitlücken-Segmentierung (30-min-Gap) wenn kein `flights`-Eintrag für eine Position gefunden wird (z.B. Altdaten vor FriesenSpy-Start)

### `app/alerts.py`

Telegram-Alert beim "Online gehen" eines Piloten. Alle VATSIM-Felder werden mit `html.escape()` sanitized bevor sie in den `parse_mode=HTML` Telegram-Body eingebettet werden. Fehler werden nur als `type(e).__name__` geloggt (kein Full-Exception-String, der den Token in der Telegram-API-URL exponieren würde).

### `app/main.py`

FastAPI mit `lifespan`-Kontext-Manager (startup: DB init + Poller start; shutdown: Poller stop).

Endpoints: `/api/live`, `/api/stats`, `/api/pilots/{cid}/flights`, `/api/flights/{id}/track`, `/api/flights/statsim/{id}/track`, `/api/events`, `/api/sse`.

`/api/pilots/{cid}/flights` lädt StatSim-Daten lazy (beim ersten Aufruf oder wenn Cache > 24h alt) und cached sie in `statsim_cache`. StatSim wird immer mit mindestens 365 Tagen abgefragt (`days=0` → alle Flüge seit 2020-01-22). `days=0` umgeht den 24h-Cache immer (force full refetch), da ein vorhandener Cache aus einer normalen `days=365`-Anfrage den vollen Abruf sonst fälschlich verhindert.

### `app/static/index.html`

Single-File-SPA ohne Build-Step. Vier Tabs:

- **LIVE** — EventSource(`/api/sse`) mit Reconnect; Callsign-Klick → Flugplan-Modal; ◎-Klick → `switchToMapAndCenter()`
- **KARTE** — Leaflet.js; Marker mit Heading-Rotation; Double-RAF-Init beim Tab-Wechsel
- **STATISTIKEN** — `/api/stats?days=N`; zeigt letzten Flug + Anzahl, sortiert nach Datum; Pilot-Klick → `openPilotFlights()` → `/api/pilots/{cid}/flights?days=365`; „Alle laden" → `loadAllFlights()` → `?days=0` (Button zeigt während des langen Fetches „Lade Historik…" und ist deaktiviert); ◎-Klick → Track-Modal; Plural-aware: `1 Flug` statt `1 Flüge`
- **EVENTS** — `/api/events`; pro Pilot werden einzelne Flüge aufgelistet (Datum, Dauer, Callsign, Route DEP→ARR, Anzahl Punkte); Segmentierung basiert auf echten VATSIM-Session-Records (Fallback: 30-min-Gap); Karte zeigt alle Flüge aller Piloten gleichzeitig als separate Polylines; Klick auf einen Flug → `highlightEventFlight()` hebt den Track auf der Karte hervor und scrollt per `scrollIntoView` automatisch zur Karte

Design: FriesenFlieger-Blau (`#04080f` Hintergrund, `#2d9cdb` Blau, `#D31141` Vereinsrot).

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
    name      TEXT,
    added_at  TEXT
);

CREATE TABLE flights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cid           INTEGER REFERENCES pilots(cid),
    callsign      TEXT,
    aircraft_short TEXT,
    departure     TEXT,
    arrival       TEXT,
    logon_time    TEXT,
    logoff_time   TEXT,
    duration_min  INTEGER
);

CREATE TABLE live_positions (
    cid           INTEGER PRIMARY KEY,
    callsign      TEXT,
    aircraft      TEXT,
    departure     TEXT,
    arrival       TEXT,
    latitude      REAL,
    longitude     REAL,
    altitude      INTEGER,
    groundspeed   INTEGER,
    heading       INTEGER,
    logon_time    TEXT,
    updated_at    TEXT,
    -- Flugplan-Details (für Modal)
    flight_rules  TEXT,
    aircraft_icao TEXT,
    alternate     TEXT,
    deptime       TEXT,
    cruise_tas    TEXT,
    enroute_time  TEXT,
    fuel_time     TEXT,
    route         TEXT,
    remarks       TEXT
);

CREATE TABLE position_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cid         INTEGER NOT NULL REFERENCES pilots(cid),
    callsign    TEXT,
    latitude    REAL,
    longitude   REAL,
    altitude    INTEGER,
    groundspeed INTEGER,
    heading     INTEGER,
    ts          TEXT NOT NULL
);

-- StatSim-Historik-Cache (24h TTL, lazy per Pilot)
CREATE TABLE statsim_cache (
    statsim_id   INTEGER PRIMARY KEY,
    cid          INTEGER NOT NULL,
    callsign     TEXT,
    departure    TEXT,
    arrival      TEXT,
    aircraft     TEXT,
    logon_time   TEXT,
    logoff_time  TEXT,
    duration_min INTEGER,
    fetched_at   TEXT NOT NULL
);
```
