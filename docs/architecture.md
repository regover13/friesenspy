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
- `pilot_to_position(pilot)` — normalisiert rohe VATSIM-Daten in ein flaches Dict mit 23 Feldern, inkl. aller `flight_plan`-Details (flight_rules, aircraft_icao, cruise_altitude, cruise_tas, route, remarks, …). **`aircraft_short`-Fallback**: VATSIM liefert `flight_plan.aircraft_short` nicht immer zuverlässig; wenn das Feld leer ist, wird es aus dem vollen `aircraft`-String (z.B. `"S22T/L-SDGRY/S"`) durch Split am ersten `"/"` abgeleitet.

### `app/statsim.py`

StatSim API-Client für historische Flugdaten.

- `fetch_pilot_flights(client, cid, api_key, days)` — paginierte Abfrage in ≤31-Tage-Chunks. Fehlerhafte Chunks werden einzeln übersprungen (kein Abbruch der Gesamtabfrage). Timeout: 30s. Silent fail → []. Normalisiert Felder: `statsim_id`, `callsign`, `departure`, `arrival`, `aircraft`, `logon_time`, `logoff_time`, `duration_min`.
- `fetch_flight_track(client, statsim_id, api_key)` — GPS-Track eines einzelnen Fluges. Silent fail → [].

StatSim API: `https://api.statsim.net`, Auth: `X-API-Key` Header, max. 31 Tage pro Query.

### `app/database.py`

SQLite mit WAL-Mode und `PRAGMA foreign_keys=ON`. Sieben Tabellen:

| Tabelle | Inhalt |
|---------|--------|
| `pilots` | CID + Name (INSERT OR IGNORE — niemals überschrieben) |
| `flights` | Pro Flug: Callsign, Typ (`aircraft_short`), DEP/ARR, Logon/Logoff, Dauer, `distance_nm` (GPS-Summe via Haversine), sowie vollständige Flugplan-Felder: `route`, `remarks`, `cruise_altitude`, `cruise_tas`, `flight_rules`, `aircraft_icao`, `alternate`, `deptime`, `enroute_time`, `fuel_time` (ab Aufzeichnungsdatum gefüllt, ältere Einträge NULL) |
| `live_positions` | Aktuelle Position pro CID (UPSERT, maximal 1 Zeile pro CID) |
| `position_history` | Jede einzelne VATSIM-Positions-Update (für Tracks + Events) |
| `calendar_events` | FriesenFlieger Google-Kalender (alle 6h synchronisiert, UID als Primary Key) |
| `push_subscriptions` | Browser-Push-Subscriptions (Endpoint, ECDH-Keys, `pilot_filter` als JSON-Array, `notify_prefiles` Flag) |
| `prefile_sigs` | Letzte bekannte Prefile-Signatur pro CID (`deptime`, `departure`, `arrival`) — wird nach jedem Poll persistiert, damit Container-Neustarts keine Änderungen verpassen |

Drei Indizes: `idx_ph_cid_ts`, `idx_ph_ts`, `idx_flights_cid`.

**`open_flight(conn, ..., *, route, remarks, cruise_altitude, cruise_tas, flight_rules, aircraft_icao, alternate, deptime, enroute_time, fuel_time)`** — speichert beim Eröffnen eines Fluges neben den Pflichtfeldern alle verfügbaren Flugplan-Felder (Keyword-only-Args mit Default `""`). **Duplikat-Schutz**: Existiert bereits ein offener Eintrag mit gleicher `(cid, logon_time)` und `logoff_time IS NULL`, wird dessen ID zurückgegeben ohne INSERT — verhindert Phantom-Einträge bei Container-Neustarts während Piloten online sind.

**`update_flight_plan(conn, flight_id, departure, arrival, *, route, remarks, ...)`** — setzt DEP/ARR und alle erweiterten Flugplan-Felder eines laufenden Fluges nachträglich, wenn der Pilot den Plan nach dem Verbindungsaufbau einreicht oder ändert. Wird ausschließlich vom Poller aufgerufen (Flugplanwechsel-Erkennung in `_poll_once`).

Alle DB-Operationen sind synchron (SQLite ist thread-safe mit WAL). Verbindungen werden pro Request geöffnet und in `finally`-Blöcken geschlossen.

**`merge_fragmented_flights(flights, gap_minutes=5, conn=None)`** — bereinigt kurze VATSIM-Disconnects in der Flughistorie. Zwei aufeinanderfolgende Einträge gleichen Callsigns werden zu einem zusammengeführt, wenn alle vier Bedingungen erfüllt sind:

1. **Gleicher Callsign** (nicht leer)
2. **Flugplan-Bedingung** — entweder (a) genau einer der beiden Einträge hat keinen Flugplan (leerer DEP+ARR), oder (b) beide haben denselben nicht-leeren DEP+ARR
3. **Zeitabstand** ≤ 5 Minuten (Toleranz −2 Min für Überlappungen durch VATSIM-Jitter)
4. **Geo-Check für no-FP-Merges** (nur wenn `conn` übergeben wird): Die erste GPS-Position des no-FP-Fragments in `position_history` muss innerhalb von **10 km** des DEP-Airports des Folgeflugs liegen (`_GEO_MERGE_KM = 10.0`, Haversine via `geo.py`, Airport-Koordinaten via `airportsdata`). Fallback auf Merge wenn keine GPS-Daten oder unbekannter ICAO-Code.

Der Geo-Check unterscheidet:
- **Pilot steht am GAT ohne Flugplan** (kein DEP/ARR), gibt Flugplan auf, reconnect → erste Position ≈ DEP-Airport → Merge ✓
- **Pilot fliegt ohne Flugplan von A nach B**, landet, reconnect mit FP für B→C → erste Position ≈ A (Startflughafen), DEP von B→C ist B → Distanz A–B > 10 km → kein Merge ✓
- **Gleicher DEP+ARR-Fall** (z.B. kurzer Verbindungsabbruch mid-flight mit identischem Flugplan) → kein Geo-Check nötig, Flugplan ist eindeutig ✓

Das gemergde Ergebnis übernimmt logon_time des früheren, logoff_time des späteren Fragments; duration_min wird addiert.

Für den Chart (`get_stats_activity`) werden no-FP-Fragment-IDs via `_nofp_fragment_ids()` Python-seitig vorberechnet (SQL kann kein Haversine). Same-FP-Merges bleiben SQL-seitig (`NOT EXISTS`-Subquery).

**`backfill_flight_distances(conn)`** — läuft beim Start in `init_db()` einmalig: Berechnet `distance_nm` für abgeschlossene Flüge nach, die noch `0` haben aber `position_history`-Einträge besitzen (Haversine-Summe über alle Positionspunkte im Logon–Logoff-Fenster). Idempotent — bereits berechnete Flüge (`distance_nm > 0`) werden übersprungen. Deckt Flüge ab, die vor Einführung der GPS-Distanzberechnung aufgezeichnet wurden.

**`close_stale_flights(conn, max_age_hours=8)`** — läuft beim Start nach `backfill_flight_distances()`: Schließt alle offenen Flüge (`logoff_time IS NULL`) die älter als 8 Stunden sind — sogenannte Zombie-Flüge. Entsteht wenn der Poller beim Disconnect eines Piloten nicht lief (Container-Neustart, Downtime). Als `logoff_time` wird der letzte `position_history`-Eintrag für diesen Piloten ab `logon_time` verwendet; bei reinen Test-Connects ohne Positionen wird `logon_time` selbst gesetzt (duration=0, ghost-gefiltert). Danach läuft `backfill_flight_distances` implizit über den nächsten Startup — die frisch geschlossenen Flüge bekommen ihre `distance_nm` beim folgenden Neustart nachberechnet.

**Ghost-Flight-Filter:** Flüge ohne erkennbare Bewegung werden in allen Ausgaben ignoriert. Kriterium: `distance_nm ≤ 0.5 AND duration_min ≤ 5` — d.h. ein Flug erscheint, wenn er mindestens ~1 km zurückgelegt hat **oder** länger als 5 Minuten dauerte. Damit werden Test-Connects (Groundspeed=0, distance=0, duration<5) herausgefiltert, echte Kurzstrecken (z.B. 4 min, 15 nm) bleiben sichtbar. Ältere Flüge ohne berechnete `distance_nm` (vor Einführung der Haversine-Berechnung) bleiben über `duration_min > 5` erhalten. Der Filter gilt in `get_stats`, `get_stats_activity` und `_nofp_fragment_ids()`. Kurze Fragmente, die durch Merge zu einem längeren Flug zusammengeführt werden, bleiben erhalten.

**StatSim-Deduplizierung:** StatSim-Einträge, die denselben Piloten und dieselbe Abflugminute (`substr(logon_time,1,16)`) wie ein FriesenSpy-Flug abdecken, werden in `get_stats` (`st_count` via `NOT EXISTS`) und `get_stats_activity` (alle 3 StatSim-Queries) nicht doppelt gezählt. Dies verhindert, dass Flüge, die FriesenSpy selbst aufgezeichnet hat und die StatSim ebenfalls kennt, im Chart und in der Pilotenliste zweifach erscheinen.

### `app/poller.py`

`VatsimPoller` kapselt:
- **APScheduler `AsyncIOScheduler`** mit drei aktiven Jobs: `vatsim_poll` (interval, 15s), `calendar_sync` (interval, 6h — lädt FriesenFlieger-Google-Kalender), `calendar_sync_initial` (date, einmalig beim Start). `daily_cleanup` ist deaktiviert — `position_history` wird dauerhaft behalten.
- **`_active_flights: dict[int, dict]`** — In-Memory State: CID → `{"id": flight_id, "dep": departure, "arr": arrival}`. Überlebt nicht einen Container-Neustart (Flüge die beim Restart offen sind, bleiben in der DB offen ohne Logoff-Zeit).
- **`sse_queue: asyncio.Queue`** — Jeder SSE-Client hat eine eigene Verbindung zum selben Queue-Objekt. `put_nowait` blockiert nicht.
- **`last_prefiles: list`** — aktuell eingereichte VATSIM-Prefile-Pläne mit FRS*-Callsign (In-Memory, aus dem letzten Poll-Zyklus)
- **`_prefile_sigs: dict | None`** — CID → `(deptime, departure, arrival)` für Änderungserkennung. Wird beim Start aus `prefile_sigs`-DB-Tabelle geladen (nicht `None`) und nach jedem Poll gespeichert. Beim allerersten Start ohne DB-Einträge ist die Dict leer — keine Spam-Notifications. Container-Neustarts verpassen dadurch keine Prefile-Änderungen mehr.

**Prefile Push-Notification-Logik:**
- `_prefile_sig(p)` → `(deptime, departure, arrival)` — Änderungssignatur
- Neuer oder geänderter Prefile → `asyncio.create_task(send_prefile_push_notifications(...))`
- Unterdrückt wenn CID bereits in `_active_flights` (Pilot online — kein Prefile-Alert nötig)
- Nur an Subscriptions mit `notify_prefiles = 1` (Filter in `get_push_subscriptions_for_prefile`)

Die Flug-State-Machine in `_poll_once`:

```
CIDs jetzt online: {A, B, C}
CIDs vorher aktiv: {B, C, D}

newly_online  = {A}       → open_flight, Alert
still_online  = {B, C}    → update position + Flugplan-Check
went_offline  = {D}       → close_flight
```

**Flugplan-Änderungserkennung** (für `still_online`-Piloten): Pro Poll wird der aktuelle DEP/ARR aus dem VATSIM-Feed mit dem in `_active_flights` gespeicherten verglichen. Bei Abweichung:
- **Kein alter Plan → neuer Plan**: `update_flight_plan()` setzt DEP/ARR und alle Flugplan-Felder (Route, Remarks, Altitude, TAS, Flight Rules, Aircraft ICAO, Alternate, Off Block, Enroute, Fuel) im laufenden Flug-Record nach.
- **Alter Plan → anderer Plan**: laufenden Flug sofort schließen (`close_flight`), neues Segment öffnen (`open_flight`) mit allen Feldern des neuen Plans. Behandelt Fälle wie Zwischenstopps oder Planänderung nach dem Start.

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

Endpoints: `/api/live`, `/api/prefiles`, `/api/stats`, `/api/stats/activity`, `/api/pilots/{cid}/flights`, `/api/pilots/{cid}/live-track`, `/api/flights/{id}/track`, `/api/flights/statsim/{id}/track`, `/api/events`, `/api/calendar/events`, `/widget`, `/api/sse`.

`/api/pilots/{cid}/flights` antwortet **sofort** mit FriesenSpy-Daten + gecachten StatSim-Daten. StatSim-Update läuft als FastAPI `BackgroundTask`: normaler Aufruf → letzter 31-Tage-Chunk; `days=0` → volle 365 Tage (Force-Refresh). Status-Tracking via `_statsim_updating` und `_full_history_fetching` (In-Memory-Sets) verhindert parallele Doppel-Fetches. Response-Header `X-StatSim-Status: fresh | updating | no-key`.

`/api/pilots/{cid}/live-track` gibt `position_history` des aktuell offenen Fluges zurück (logoff_time IS NULL). Wird vom Frontend beim ersten ◎-Klick geladen; danach wächst der Track mit jedem SSE-Update.

`/api/flights/{id}/track` akzeptiert optionale `logon`/`logoff`-Query-Params, die die DB-Zeitstempel überschreiben. Notwendig nach `merge_fragmented_flights`, wenn die DB noch die alten Zeiten der Ursprungsfragmente enthält.

`/api/events` liefert neben FriesenSpy-Piloten auch einen **StatSim-Fallback**: Piloten aus `statsim_cache` die per DEP/ARR-Match im Zeitfenster gefunden werden, aber keine `position_history` haben, werden mit `source: "statsim"` und `positions: []` angehängt. **Aktive Flüge eingeschlossen**: Die SQL-Abfrage schließt Flüge mit `logoff_time IS NULL` ein (Pilot noch online) — ohne diese Bedingung würden gerade fliegende Friesen im Events-Fenster fehlen. **Dauer/Strecke on-the-fly**: Für aktive Flüge werden `duration_min` (Sekunden seit `logon_time` bis `now()`) und `distance_nm` (Haversine-Summe der `position_history` ab `logon_time`) im Endpoint berechnet, da `close_flight()` noch nicht gelaufen ist. **Ghost-Filter** überprüft nur abgeschlossene Flüge (`logoff_time IS NOT NULL`) — aktive Flüge werden nie herausgefiltert. **Deduplizierung**: Bevor `merge_fragmented_flights()` läuft, werden DB-Duplikate mit gleicher `(logon_time, departure, arrival)` per Python-Set entfernt (entsteht durch Container-Neustarts vor dem Duplikat-Schutz-Fix). **Merge-Fix**: Die DB-Abfrage holt Flüge bis `end + 12h`, um alle Fragmente eines zusammengehörigen Fluges zu laden; nach `merge_fragmented_flights()` wird auf `logon_time <= end` zurückgefiltert. FriesenSpy-Flüge geben alle vollständigen Flugplan-Felder zurück (`route`, `remarks`, `cruise_altitude`, `cruise_tas`, `flight_rules`, `aircraft_icao`, `alternate`, `deptime`, `enroute_time`, `fuel_time`).

### `app/static/index.html`

Single-File-SPA ohne Build-Step. Vier Tabs:

**Layer-Präferenz:** `_saveLayerPref(key)` / `_loadLayerPref()` / `_getPreferredLayer(layers)` — speichert den zuletzt manuell gewählten Basis-Layer (Schlüssel `friesenspy_layer`) in `localStorage`. Alle drei Karten (Live, Track-Modal, Events) initialisieren mit dem gespeicherten Layer. OFM-Auto-Switch ist nur aktiv wenn OFM die gespeicherte Präferenz ist; manuell zurück zu OFM → Auto-Switch reaktiviert sich.

**OpenAIP-Overlay-Präferenz:** `_saveAIPPref(on)` / `_loadAIPPref()` / `_setupAIPPref(map, aipLayer)` — speichert ob das OpenAIP-Overlay aktiv war (Schlüssel `friesenspy_aip`, Wert `'1'`/`'0'`) in `localStorage`. Alle drei Karten rufen `_setupAIPPref` nach dem Layer-Control-Init auf: restauriert den gespeicherten Zustand und registriert `overlayadd`/`overlayremove`-Listener zum Speichern bei Änderung.

- **LIVE** — EventSource(`/api/sse`) mit Reconnect; **Flugplan-Zelle (DEP→ARR) anklicken** → Flugplan-Modal (vollständige Live-Daten); ◎-Klick → `switchToMapAndCenter()`
- **KARTE** — Leaflet.js; Marker mit Heading-Rotation; Double-RAF-Init beim Tab-Wechsel; Live-Track-Polyline pro Pilot (`liveTrackPoints`/`liveTrackLines`): beim ersten ◎-Klick oder Map-Init via `/api/pilots/{cid}/live-track` geladen, danach per SSE-Update erweitert; Track wird entfernt wenn Pilot offline geht
- **STATISTIKEN** — `/api/stats?days=N`; KPI-Box oben (Piloten, Flüge, Stunden, Ø/Tag, Aktivster Pilot, Ø Flugdauer — klickbar); Liniendiagramm via `/api/stats/activity?days=N` (Piloten/Flüge/Stunden/Ø Flugdauer, täglich für ≤93 Tage mit Wochentag-Labels, monatlich für 365 Tage, Dual-Y-Achse); Callsign + Pilot + geloggte Flüge (FS + ST) + letzter Flug; Pilot-Klick → `openPilotFlights()` → `/api/pilots/{cid}/flights?days=N` (sofort aus Cache, StatSim im Hintergrund); Badge „⟳ StatSim wird aktualisiert…" wenn `X-StatSim-Status: updating`; Auto-Refresh nach 10s; „Alle Flüge laden (letztes Jahr)" → `?days=0` (365-Tage-Force-Refresh); **Flugplan-Zelle (DEP→ARR) anklicken** → `openFlightDetailModal()` — zeigt dieselben Felder wie das Live-Flugplan-Modal (Flight Rules, Aircraft, DEP, ARR, Alternate, Off Block UTC, Altitude, TAS, Enroute, Fuel Endurance, Route, Remarks) plus historisch-spezifische Felder (Datum UTC, Dauer, Strecke, Quelle); optionale Felder ausgeblendet wenn leer; ◎-Klick → Track-Modal; ⎘ Teilen in Drill-Down und Track-Modal
- **EVENTS** — `/api/events`; Layout: Karte oben (560px, OFM), Pilotenliste darunter; pro Pilot werden einzelne Flüge aufgelistet; Segmentierung basiert auf echten VATSIM-Session-Records (Fallback: 30-min-Gap); Karte zeigt alle Tracks aller Piloten gleichzeitig; Klick auf Flug → `highlightEventFlight()` hebt Track hervor, „↺ Alle Tracks"-Button setzt zurück; **Flugplan-Zelle (DEP→ARR) anklicken** → `openFlightDetailModal()` mit allen verfügbaren Feldern; optionale Felder und Abschnitte ausgeblendet wenn leer; ⎘ Teilen; `searchEvents()` behandelt `datetime-local` direkt als UTC

**URL Deep-Linking** via `location.hash` (URLSearchParams): Tab, Pilot-CID, Zeitraum (days=), Track-ID/Source, Callsign (fp=), Events-Filter (icao/radius/start/end) werden im Hash gespeichert → Seite neu laden öffnet den gleichen Zustand. `initFromUrl()` wird beim Seitenstart nach `fetchLiveInitial()` ausgeführt; re-aktiviert den korrekten Tab am Ende aller Async-Operationen (Race-Condition-Schutz).

**Karten-Layer**: OpenFlightMap (OFM) als Standard auf allen Leaflet-Instanzen (Live/Karte, Track-Modal, Events). Fünf Basislayer via `L.control.layers()`: OFM (native Tiles Zoom 6–11, `minZoom:6`), OpenTopoMap (OSM+SRTM, Zoom bis 17), Satellit (ESRI World Imagery), Light (CartoDB Positron), Dark (CartoDB Dark Matter). **OpenAIP-Overlay**: Checkbox für Luftraum/Flugplätze/Navaids — wird nur angezeigt wenn `OPENAIP_API_KEY` gesetzt; Key wird via `/api/frontend-config` an das Frontend übergeben und per `_makeAIPOverlay()` als separater Tile-Layer eingebunden. **Auto-Switch** (`_setupOFMAutoSwitch`): Solange OFM aktiv ist, wechselt die Karte bei Zoom < 7 oder Zoom > 12 automatisch auf Satellit und zurück im OFM-Bereich (Zoom 7–12). Manueller Wechsel zu einem Nicht-OFM-Layer deaktiviert den Auto-Switch; manuell zurück zu OFM reaktiviert ihn. `initLiveMap()`, `renderEventsMap()` und der Track-Modal-Init awaiten `_configPromise` (den `/api/frontend-config`-Fetch) um Race Conditions beim OpenAIP-Key-Laden zu vermeiden.

**Web Push Notifications**: Bell-Icon 🔔 im Header — sichtbar wenn `VAPID_PUBLIC_KEY` gesetzt. Klick öffnet Panel mit Toggle + Pilot-Filter. `_registerServiceWorker()` registriert `sw.js` und lädt bestehende Push-Subscription. `_subscribePush()` fragt Notification-Erlaubnis, abonniert via `pushManager.subscribe()` und postet Subscription an `/api/push/subscribe`. Service Worker (`app/static/sw.js`) empfängt `push`-Events und zeigt Notifications im Hintergrund — auch bei geschlossenem Browser. Auf iOS (nicht-PWA) erscheint eine Installations-Anleitung ("⬆ → Zum Home-Bildschirm"). Auf Android/Desktop feuert `beforeinstallprompt` → "Als App installieren"-Button. Pilot-Filter (Alle / bestimmte CIDs) wird serverseitig in `push_subscriptions.pilot_filter` (JSON) gespeichert. **Pilot-Filter-UX**: Bei "Alle Friesen" sind alle Checkboxen checked + disabled (visuell ausgegraut, nicht änderbar). Bei "Nur bestimmte Piloten" werden Checkboxen aktiviert; beim Umschalten von "select" → "all" wird der aktuelle Zustand in `_notifCustomFilter` (in-memory) gemerkt, sodass bei erneutem Wechsel zurück der Stand erhalten bleibt — auch ohne Speichern. Beim ersten Öffnen wird der gespeicherte Filter aus `localStorage` geladen und der Radio-Modus entsprechend wiederhergestellt. **„Push zurücksetzen"**: deabonniert, deregistriert alle SW-Registrierungen und lädt neu — erzwingt frischen FCM/APNs/WNS-Token (nötig bei `permanently-removed.invalid`-Endpoints). **Endpoint-Validierung**: `/api/push/subscribe` lehnt `permanently-removed.invalid`-Endpoints mit HTTP 400 ab. **VAPID-Keys**: `VAPID_PRIVATE_KEY` muss als raw base64url-kodierter EC-Skalar (32 Byte, 43 Zeichen, kein PEM) in config.env stehen — generiert mit `generate_vapid.py`. pywebpush mutiert das `claims`-Dict in-place (fügt `aud`/`exp` hinzu) → pro Push ein frisches Dict erstellen. WNS erfordert `ttl=3600` (TTL=0 wird von WNS abgelehnt). Bei transientem Fehler (z.B. APNs 4xx) wird einmal nach 5 Sekunden wiederholt.

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

-- FriesenFlieger Google-Kalender (alle 6h synchronisiert)
CREATE TABLE calendar_events (
    uid      TEXT PRIMARY KEY,
    summary  TEXT,
    dtstart  TEXT,
    dtend    TEXT,
    location TEXT
);

-- Browser-Push-Subscriptions für Web Push Notifications
CREATE TABLE push_subscriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT UNIQUE NOT NULL,
    p256dh         TEXT NOT NULL,
    auth           TEXT NOT NULL,
    pilot_filter   TEXT DEFAULT NULL,    -- JSON-Array von CIDs oder NULL = alle
    notify_prefiles INTEGER DEFAULT 0,  -- 1 = auch Prefile-Änderungen benachrichtigen
    created_at     TEXT NOT NULL
);

-- Letzte Prefile-Signaturen pro CID (persistiert für Neustart-Robustheit)
CREATE TABLE prefile_sigs (
    cid       INTEGER PRIMARY KEY,
    deptime   TEXT,
    departure TEXT,
    arrival   TEXT,
    saved_at  TEXT
);
```
