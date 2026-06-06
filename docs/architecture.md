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

Pflichtfelder: `SECRET_KEY`. Optional: `STATSIM_API_KEY` für historische Flugdaten, `OPENAIP_API_KEY` für OpenAIP-Overlay im Frontend, `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_CONTACT_EMAIL` für Web Push Notifications.

### `app/vatsim.py`

- `fetch_vatsim_data(client)` — HTTP GET auf die VATSIM Data API, gibt geparsten JSON-Dict zurück.
- `filter_friesen_pilots(callsign_prefix, vatsim_data)` — filtert Piloten-Liste nach Callsign-Prefix (case-insensitiv).
- `pilot_to_position(pilot)` — normalisiert rohe VATSIM-Daten in ein flaches Dict mit 22 Feldern, inkl. aller `flight_plan`-Details (flight_rules, aircraft_icao, route, remarks, …).

### `app/statsim.py`

StatSim API-Client für historische Flugdaten.

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

`merge_fragmented_flights(flights, gap_minutes=5)` — bereinigt kurze VATSIM-Disconnects in der Flughistorie: zwei aufeinanderfolgende Einträge gleichen Callsigns werden zusammengeführt wenn (a) genau einer keinen Flugplan hat oder (b) beide denselben DEP+ARR haben, und der Zeitabstand ≤ 5 Minuten beträgt.

**Ghost-Flight-Filter:** Flüge mit `duration_min ≤ 5` werden in allen Ausgaben ignoriert — in `/api/pilots/{cid}/flights` (nach Merge), im Events-Endpoint und in `get_stats` (JOIN + Subquery). Kurze Fragmente, die durch Merge zu einem längeren Flug zusammengeführt werden, bleiben erhalten.

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

Endpoints: `/api/live`, `/api/stats`, `/api/pilots/{cid}/flights`, `/api/pilots/{cid}/live-track`, `/api/flights/{id}/track`, `/api/flights/statsim/{id}/track`, `/api/events`, `/api/sse`.

`/api/pilots/{cid}/flights` antwortet **sofort** mit FriesenSpy-Daten + gecachten StatSim-Daten. StatSim-Update läuft als FastAPI `BackgroundTask`: normaler Aufruf → letzter 31-Tage-Chunk; `days=0` → volle 365 Tage (Force-Refresh). Status-Tracking via `_statsim_updating` und `_full_history_fetching` (In-Memory-Sets) verhindert parallele Doppel-Fetches. Response-Header `X-StatSim-Status: fresh | updating | no-key`.

`/api/pilots/{cid}/live-track` gibt `position_history` des aktuell offenen Fluges zurück (logoff_time IS NULL). Wird vom Frontend beim ersten ◎-Klick geladen; danach wächst der Track mit jedem SSE-Update.

### `app/static/index.html`

Single-File-SPA ohne Build-Step. Vier Tabs:

- **LIVE** — EventSource(`/api/sse`) mit Reconnect; Callsign-Klick → Flugplan-Modal; ◎-Klick → `switchToMapAndCenter()`
- **KARTE** — Leaflet.js; Marker mit Heading-Rotation; Double-RAF-Init beim Tab-Wechsel; Live-Track-Polyline pro Pilot (`liveTrackPoints`/`liveTrackLines`): beim ersten ◎-Klick oder Map-Init via `/api/pilots/{cid}/live-track` geladen, danach per SSE-Update erweitert; Track wird entfernt wenn Pilot offline geht
- **STATISTIKEN** — `/api/stats?days=N`; KPI-Box oben (Piloten, Flüge, Stunden, Ø/Tag, Aktivster Pilot, Ø Flugdauer — klickbar); Liniendiagramm via `/api/stats/activity?days=N` (Piloten/Flüge/Stunden/Ø Flugdauer, täglich für ≤93 Tage mit Wochentag-Labels, monatlich für 365 Tage, Dual-Y-Achse); Callsign + Pilot + geloggte Flüge (FS + ST) + letzter Flug; Pilot-Klick → `openPilotFlights()` → `/api/pilots/{cid}/flights?days=N` (sofort aus Cache, StatSim im Hintergrund); Badge „⟳ StatSim wird aktualisiert…" wenn `X-StatSim-Status: updating`; Auto-Refresh nach 10s; „Alle Flüge laden (letztes Jahr)" → `?days=0` (365-Tage-Force-Refresh); ◎-Klick → Track-Modal; ⎘ Teilen in Drill-Down und Track-Modal
- **EVENTS** — `/api/events`; Layout: Karte oben (560px, OFM), Pilotenliste darunter; pro Pilot werden einzelne Flüge aufgelistet; Segmentierung basiert auf echten VATSIM-Session-Records (Fallback: 30-min-Gap); Karte zeigt alle Tracks aller Piloten gleichzeitig; Klick auf Flug → `highlightEventFlight()` hebt Track hervor, „↺ Alle Tracks"-Button setzt zurück; Callsign klicken → Flugdetail-Modal; ⎘ Teilen; `searchEvents()` behandelt `datetime-local` direkt als UTC

**URL Deep-Linking** via `location.hash` (URLSearchParams): Tab, Pilot-CID, Zeitraum (days=), Track-ID/Source, Callsign (fp=), Events-Filter (icao/radius/start/end) werden im Hash gespeichert → Seite neu laden öffnet den gleichen Zustand. `initFromUrl()` wird beim Seitenstart nach `fetchLiveInitial()` ausgeführt; re-aktiviert den korrekten Tab am Ende aller Async-Operationen (Race-Condition-Schutz).

**Karten-Layer**: OpenFlightMap (OFM) als Standard auf allen Leaflet-Instanzen (Live/Karte, Track-Modal, Events). Fünf Basislayer via `L.control.layers()`: OFM (native Tiles Zoom 6–11, `minZoom:6`), OpenTopoMap (OSM+SRTM, Zoom bis 17), Satellit (ESRI World Imagery), Light (CartoDB Positron), Dark (CartoDB Dark Matter). **OpenAIP-Overlay**: Checkbox für Luftraum/Flugplätze/Navaids — wird nur angezeigt wenn `OPENAIP_API_KEY` gesetzt; Key wird via `/api/frontend-config` an das Frontend übergeben und per `_makeAIPOverlay()` als separater Tile-Layer eingebunden. **Auto-Switch** (`_setupOFMAutoSwitch`): Solange OFM aktiv ist, wechselt die Karte bei Zoom < 7 oder Zoom > 12 automatisch auf Satellit und zurück im OFM-Bereich (Zoom 7–12). Manueller Wechsel zu einem Nicht-OFM-Layer deaktiviert den Auto-Switch; manuell zurück zu OFM reaktiviert ihn. `initLiveMap()` ist async und awaitet `_configPromise` (den `/api/frontend-config`-Fetch) um Race Conditions beim OpenAIP-Key-Laden zu vermeiden.

**Web Push Notifications**: Bell-Icon 🔔 im Header — sichtbar wenn `VAPID_PUBLIC_KEY` gesetzt. Klick öffnet Panel mit Toggle + Pilot-Filter. `_registerServiceWorker()` registriert `sw.js` und lädt bestehende Push-Subscription. `_subscribePush()` fragt Notification-Erlaubnis, abonniert via `pushManager.subscribe()` und postet Subscription an `/api/push/subscribe`. Service Worker (`app/static/sw.js`) empfängt `push`-Events und zeigt Notifications im Hintergrund — auch bei geschlossenem Browser. Auf iOS (nicht-PWA) erscheint eine Installations-Anleitung ("⬆ → Zum Home-Bildschirm"). Auf Android/Desktop feuert `beforeinstallprompt` → "Als App installieren"-Button. Pilot-Filter (Alle / bestimmte CIDs) wird serverseitig in `push_subscriptions.pilot_filter` (JSON) gespeichert. **Pilot-Filter-UX**: Bei "Alle Friesen" sind alle Checkboxen checked + disabled (visuell ausgegraut, nicht änderbar). Bei "Nur bestimmte Piloten" werden Checkboxen aktiviert; beim Umschalten von "select" → "all" wird der aktuelle Zustand in `_notifCustomFilter` (in-memory) gemerkt, sodass bei erneutem Wechsel zurück der Stand erhalten bleibt — auch ohne Speichern. Beim ersten Öffnen wird der gespeicherte Filter aus `localStorage` geladen und der Radio-Modus entsprechend wiederhergestellt.

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
