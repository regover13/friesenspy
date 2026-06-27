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

Pflichtfelder: `SECRET_KEY`. Optional: `STATSIM_API_KEY` für historische Flugdaten, `OPENAIP_API_KEY` für OpenAIP-Overlay im Frontend, `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_CONTACT_EMAIL` für Web Push Notifications, `LOG_LEVEL` (Default `INFO`).

**Logging:** `configure_logging(LOG_LEVEL)` wird beim Lifespan-Startup aufgerufen und installiert via `logging.basicConfig(..., force=True)` einen Handler am Root-Logger. Ohne das hat der Root-Logger unter uvicorn keinen Handler, sodass Pythons Last-Resort-Handler nur `WARNING`+ ausgibt und App-`INFO`-Logs (z. B. `PrefilePush … sent OK`) verschluckt würden. Ungültiges Level → Fallback `INFO`.

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
| `flights` | Pro Flug: Callsign, Typ (`aircraft_short`), DEP/ARR, Logon/Logoff, `duration_min` (Online-/Verbindungszeit), `block_min` (Bewegungszeit), `distance_nm` (GPS-Summe via Haversine), `superseded_by` (reversibler Dedup-Verweis), sowie vollständige Flugplan-Felder: `route`, `remarks`, `cruise_altitude`, `cruise_tas`, `flight_rules`, `aircraft_icao`, `alternate`, `deptime`, `enroute_time`, `fuel_time` (ab Aufzeichnungsdatum gefüllt, ältere Einträge NULL) |
| `live_positions` | Aktuelle Position pro CID (UPSERT, maximal 1 Zeile pro CID) |
| `position_history` | Jede einzelne VATSIM-Positions-Update (für Tracks + Events) |
| `calendar_events` | FriesenFlieger Google-Kalender (alle 6h synchronisiert, UID als Primary Key) |
| `push_subscriptions` | Browser-Push-Subscriptions (Endpoint, ECDH-Keys, `pilot_filter` als JSON-Array — gilt für Online/Flugplan/TS, `notify_prefiles` Flag, `notify_ts` Flag; `ts_self_frs` = tote Spalte, nicht mehr genutzt; `created_at` wird bei Re-Abo desselben Endpoints mit aktualisiert) |
| `prefile_sigs` | Letzte bekannte Prefile-Signatur pro CID (`deptime`, `departure`, `arrival`) — wird nach jedem Poll persistiert, damit Container-Neustarts keine Änderungen verpassen |
| `ts_consent` | Subjekt-Einwilligung pro FRS für TS-Login-Sichtbarkeit (`visibility` ∈ `everyone`/`nobody`; `allowlist`-Spalte existiert noch, wird aber nicht mehr ausgewertet) — kein Eintrag = Default `everyone` |

Drei Indizes: `idx_ph_cid_ts`, `idx_ph_ts`, `idx_flights_cid`.

**Sessionisierung — `(cid, logon_time)` als Schlüssel.** Eine VATSIM-Verbindung ist eindeutig über `(cid, logon_time)` bestimmt (VATSIM kennt keine Session-ID; `logon_time` ist pro Verbindung stabil). Diese Invariante wird strukturell erzwungen durch einen **partiellen Unique-Index** `idx_flights_session ON flights(cid, logon_time) WHERE superseded_by IS NULL` — pro Verbindung existiert höchstens **ein aktiver** Flug. Die Spalte `superseded_by` (NULL = aktiv, sonst id des Behalt-Records) erlaubt es, Duplikate **reversibel** zu markieren statt zu löschen.

**`open_flight(conn, ..., *, route, remarks, ...)`** — `INSERT … ON CONFLICT(cid, logon_time) WHERE superseded_by IS NULL DO NOTHING`, danach wird die bestehende id zurückgegeben. Ein erneutes Öffnen derselben Verbindung (z. B. nach Container-Neustart) ist damit ein **strukturelles No-Op** — unabhängig vom In-Memory-State.

**`update_flight_plan(conn, flight_id, departure, arrival, *, route, remarks, ...)`** — setzt DEP/ARR und alle erweiterten Flugplan-Felder eines laufenden Fluges nachträglich, wenn der Pilot den Plan nach dem Verbindungsaufbau einreicht oder ändert. Wird ausschließlich vom Poller aufgerufen (Flugplanwechsel-Erkennung in `_poll_once`).

Alle DB-Operationen sind synchron (SQLite ist thread-safe mit WAL). Verbindungen werden pro Request geöffnet und in `finally`-Blöcken geschlossen.

**`merge_fragmented_flights(flights, gap_minutes=5, conn=None)`** — führt zwei aufeinanderfolgende Verbindungen desselben Piloten read-time zu **einem logischen Flug** zusammen (Reconnect-Stitching). Ein vorübergehender Reconnect ist für VATSIM zwei Verbindungen (zwei Zeilen, atomar gespeichert); hier werden sie für Anzeige/Statistik gemergt. Bedingungen:

1. **Gleicher Callsign** (nicht leer)
2. **Flugplan = Hauptsignal** — entweder (a) genau einer der beiden hat keinen Flugplan (no-FP-Reconnect vor Neu-Filen), oder (b) beide haben denselben nicht-leeren DEP+ARR (unterbrochener Flug)
3. **Gap-Fenster nach Flugplan** — same-FP bis **30 Min** (`_RECONNECT_GAP_SAME_FP_MIN`, der gleiche Flugplan trägt die Beweislast), no-FP bis **15 Min** (`_RECONNECT_GAP_NO_FP_MIN`); Toleranz −2 Min für VATSIM-Jitter
4. **Geo-Kontinuität** (`_segments_continuous`, nur mit `conn`): **Distanz-Budget** statt fester Radius — der Abstand zwischen der **letzten Position von Segment 1** und der **ersten Position von Segment 2** darf höchstens `Lückendauer × 600 kt + 10 nm` betragen. Das löst den Fall „Pilot 10 Min ohne Netz, Sim fliegt weiter" (Reconnect taucht stromabwärts auf), weist aber Teleports ab. Zusätzlich **Richtungsprüfung**: Segment 2 darf nicht deutlich weiter vom Ziel entfernt sein als das Ende von Segment 1. Fallback Merge, wenn keine GPS-Daten vorhanden.

Das gemergde Ergebnis übernimmt logon_time des früheren, logoff_time des späteren Segments; **duration_min wird addiert** (die Disconnect-Lücke zählt nicht mit → keine Inflation); distance_nm wird addiert. Gegenprobe: gleicher Callsign aber **anderer FP** (z. B. Rückleg) → kein Merge, zwei Flüge.

**`backfill_flight_distances(conn)`** — läuft beim Start in `init_db()` einmalig: Berechnet `distance_nm` für abgeschlossene Flüge nach, die noch `0` haben aber `position_history`-Einträge besitzen (Haversine-Summe über alle Positionspunkte im Logon–Logoff-Fenster). Idempotent — bereits berechnete Flüge (`distance_nm > 0`) werden übersprungen. Deckt Flüge ab, die vor Einführung der GPS-Distanzberechnung aufgezeichnet wurden.

**Block-Zeit (`block_min`).** Zusätzlich zur **Online-Zeit** (Verbindungsdauer logon→logoff, `duration_min`) wird die **Block-Zeit** geführt: die Spanne von der ersten bis zur letzten Bewegung (`groundspeed > _BLOCK_GS_KT`, 2 kt) innerhalb [logon, logoff] aus `position_history` (`_block_minutes()`, gate-to-gate inkl. Taxi). `close_flight` setzt `block_min` mit; `backfill_block_minutes(conn)` füllt Bestandsflüge in `init_db()` nach; `merge_fragmented_flights` summiert `block_min` der Segmente; `canonicalize_flights` liefert es mit. Block-Zeit ist **FriesenSpy-only** (StatSim/Altflüge ohne dichte GS-Spur → keine Block-Zeit). So lässt sich „angesteckt am Gate" von echter Bewegung trennen.

**`close_stale_flights(conn, max_age_hours=8)`** — Startup-Notnagel: schließt offene Flüge älter als 8 h (echte Waisen, die Rehydration + Live-Close nicht erwischt haben). Als `logoff_time` wird die letzte `position_history` ab `logon_time` verwendet, **gedeckelt auf `MIN(logon_time)` der nächsten Session** desselben Piloten — so kann ein Logoff nie Positionen eines späteren Fluges greifen (das war die Ursache der 139-Min-Zombie-Inflation). Ohne Positionen wird `logon_time` gesetzt (duration=0, ghost-gefiltert).

**`consolidate_flights(conn, *, statsim_correct=True, shrink_margin_min=10)`** — läuft idempotent in `init_db()` **vor** dem Anlegen des partiellen Unique-Index (Reihenfolge zwingend, sonst Constraint-Verletzung) und ist als `scripts/consolidate_flights.py` (mit `--dry-run`) manuell aufrufbar. **Selbst-korrigierend:** zu Beginn werden der Unique-Index gedroppt und `superseded_by` zurückgesetzt — jeder Lauf rechnet von vorn (idempotent), sodass auch früher falsch markierte Flüge wieder auftauchen. Reversibler Cleanup in vier Schritten: (A) mehrere offene Flüge je cid → nur die **jüngste** (aktuelle Live-Verbindung) offen lassen, ältere offene Flüge als beendete Verbindungen **schließen** (gedeckelter Logoff, kein supersede) — ein Pilot hat nur eine Verbindung gleichzeitig; mehrere offene Zeilen entstehen, wenn ein Disconnect verpasst wurde (z. B. Reconnect über einen Neustart) und sind sequenzielle, keine gleichzeitigen Verbindungen; (B) exakte Duplikate (gleiche cid+logon_time) → Keeper-Priorität **(1) Flug mit echtem Inhalt** (Nicht-Ghost: `distance_nm > 0.5 OR duration_min > 5`), (2) offener Flug, (3) niedrigste id — verhindert, dass ein 0-Min-Ghost mit gleicher logon_time den echten Flug verdrängt; (C) Zombie-Logoffs auf die gedeckelte letzte Position korrigieren (nur wenn das die Dauer um ≥ `shrink_margin_min` verkürzt); (D) StatSim-Backstop: grob unplausible FS-Dauern (> 2× StatSim + 10) auf den StatSim-Wert korrigieren. `consolidate_flights` committet **nicht** selbst (Aufrufer committen → ermöglicht Dry-Run via rollback). Rückgängig: `UPDATE flights SET superseded_by = NULL`.

**`canonicalize_flights(conn, *, cids, callsign_prefix, start, end, include_statsim)` — die EINZIGE Wahrheit für „echte Flüge".** Liefert eine nach logon_time absteigend sortierte Liste kanonischer Flug-Dicts (Feld `source`: `friesenspy` | `statsim`). Pipeline: aktive FS-Flüge laden (`superseded_by IS NULL`, abgeschlossen) → Reconnect-/Fragment-Merge (`merge_fragmented_flights`) → Ghost-Filter (`distance_nm ≤ 0.5 AND duration_min ≤ 5` verwerfen) → StatSim laden und gegen die kanonische FS-Menge deduplizieren (`_dedup_statsim_against_fs`). **Alle Views rufen diese eine Funktion** — `get_stats`, `get_stats_activity` (aggregieren in Python) sowie der Piloten-Detail-Endpoint und (für die FS-Flüge) der Events-Endpoint. Dadurch sind Flugzahl/Dauer/Piloten über alle Sichten **garantiert identisch** (zuvor gab es fünf divergierende Inline-Implementierungen).

**Ghost-Flight-Filter:** zentral in `canonicalize_flights` (Schritt 2). Kriterium `distance_nm ≤ 0.5 AND duration_min ≤ 5` filtert Test-Connects; echte Kurzstrecken (z. B. 4 min, 15 nm) bleiben. Ältere Flüge ohne `distance_nm` bleiben über `duration_min > 5` erhalten.

**StatSim-Deduplizierung:** an **einer** Stelle (`_dedup_statsim_against_fs`). Ein StatSim-Eintrag wird unterdrückt, wenn (a) sein Logon innerhalb eines FS-Fensters [logon, logoff] liegt, oder (b) gleiche Strecke und FS-Logon bis 10 Min nach StatSim (Flugplanwechsel nach Connect). Distanz/Track/Flugplan bleiben immer FriesenSpy (reicher); StatSim korrigiert nur kaputte FS-Dauern (siehe `consolidate_flights` Schritt D).

### `app/poller.py`

`VatsimPoller` kapselt:
- **APScheduler `AsyncIOScheduler`** mit bis zu vier aktiven Jobs: `vatsim_poll` (interval, 15s), `calendar_sync` (interval, 6h — lädt FriesenFlieger-Google-Kalender), `calendar_sync_initial` (date, einmalig beim Start), sowie optional `ts_poll` (interval, `TS_POLL_INTERVAL`s) wenn `TS_NOTIFY_ENABLED=true`. Der `ts_poll`-Job ist **von VAPID entkoppelt** — er läuft für die Live-Anzeige auch ohne VAPID; ohne VAPID werden lediglich keine TS-Push-Benachrichtigungen versandt. `daily_cleanup` ist deaktiviert — `position_history` wird dauerhaft behalten.
- **`_active_flights: dict[int, dict]`** — In-Memory State: CID → `{"id": flight_id, "dep": departure, "arr": arrival}`. Wird beim Start in `PollerService.start()` aus der DB **rehydriert** (alle offenen Flüge `logoff_time IS NULL AND superseded_by IS NULL`), sodass ein Container-Neustart laufende Flüge adoptiert: Pilot noch online → `still_online` (kein neuer Flug); inzwischen offline → `went_offline` → korrekt geschlossen (kein Zombie). **Flugende:** Beim Offline-Gehen wird als `logoff_time` die letzte gespeicherte Position verwendet (nicht die Wanduhr). **Flugplanwechsel ohne Disconnect:** gleicher Abflughafen → `update_flight_plan` (selbes Leg); **geänderter** Abflughafen → echtes neues Leg (Pilot gelandet, neu gefiled) → altes Segment schließen, neues mit eindeutiger Mikrosekunden-`logon_time` öffnen (kollidiert nie mit dem Unique-Index).
- **`_sse_subscribers: set[asyncio.Queue]` (Per-Client-Fan-out)** — Jede SSE-Verbindung registriert über `subscribe_sse()` ihre **eigene** beschränkte Queue (`_SSE_QUEUE_MAXSIZE=50`) und deregistriert sie beim Disconnect über `unsubscribe_sse()` (im `finally` des Generators). `broadcast_sse(msg)` verteilt jedes Update an **alle** Queues (Iteration über Snapshot, `put_nowait`, non-blocking); bei voller Queue wird der älteste Eintrag verworfen (Drop-Oldest). So bekommt **jeder** Client jedes Update — früher teilten sich alle Clients **eine** Queue, sodass jede Nachricht nur **einen** Consumer erreichte. Der maxsize-Deckel begrenzt zugleich den serverseitigen Rückstau für einen gedrosselten Hintergrund-Tab.
- **`last_prefiles: list`** — aktuell eingereichte VATSIM-Prefile-Pläne mit FRS*-Callsign (In-Memory, aus dem letzten Poll-Zyklus)
- **`ts_clients: list[dict]`** — letzter TS-Poll-Snapshot der FRS-getaggten Clients (intern `{frs, nick, cid}`), In-Memory. Speist `/api/teamspeak` (Live-Tab-Panel) und den `/widget`-Zähler — **nach außen wird bewusst nur `frs` ausgegeben** (Klarnamen/Nick-Zusätze bleiben serverseitig). Bleibt bei `None`-Abruf (TS nicht erreichbar) unverändert.
- **`_prefile_sigs: dict | None`** — CID → `(deptime, departure, arrival)` für Änderungserkennung. Wird beim Start aus `prefile_sigs`-DB-Tabelle geladen (nicht `None`) und nach jedem Poll gespeichert. Beim allerersten Start ohne DB-Einträge ist die Dict leer — keine Spam-Notifications. Container-Neustarts verpassen dadurch keine Prefile-Änderungen mehr.

**`send_web_push(vapid_private_key, vapid_contact_email, db_path, subscriptions, payload, label)`** — generischer WebPush-Kern, der von VATSIM-Online- und TS-Notifications gemeinsam genutzt wird. Führt für jede Subscription einen Send-Versuch aus (1× Retry nach 5 s), loggt Fehler, löscht 410-Endpoints aus der DB — **sowie 403-Endpoints mit VAPID-Mismatch-Body** (`"do not correspond"`, d. h. mit alten VAPID-Keys angelegte, nie zustellbare Subscriptions; Client re-registriert beim nächsten Besuch). Derselbe 403-Cleanup gilt im Inline-Loop von `send_prefile_push_notifications`.

**`_poll_teamspeak()`** — TS-Job (Live-Anzeige + Verweildauer-/Streak-Benachrichtigung):
1. `fetch_channel_clients` aufrufen → `None` bei Fehler (Poll überspringen, **Snapshot bleibt erhalten**); `[]` ist ein gültig leerer Kanal
1a. Erfolgreicher Abruf → `self.ts_clients = clients` (Anzeige-Snapshot, **vor** der Notify-Logik). Ist kein VAPID gesetzt, endet der Poll hier (reiner Display-Modus, keine Benachrichtigung)
2. Erster erfolgreicher Poll: Baseline — präsente FRS in `_ts_streak` mit `_TS_BASELINE_STREAK` (sehr hoch) markieren, sodass sie die Schwelle nie treffen → keine Notifications
3. Präsenz-Streak: je präsenter FRS `_ts_streak[frs] += 1`; abwesende FRS fallen aus dem Dict (Reset). Bestätigt = Streak erreicht erstmals `TS_MIN_DWELL_POLLS + 1` → erst dann Kandidat. Kurzes „Reinschauen" (vor dem Folge-Poll weg) erreicht die Schwelle nie.
4. Pro bestätigter FRS: Debounce prüfen (`_ts_last_notified`, `TS_REJOIN_DEBOUNCE_SEC`); Subjekt-Privacy `get_ts_consent(frs)` (`visibility == 'nobody'` → keine Empfänger); sonst `cid_for_callsign(frs)` und `get_ts_push_subscriptions(conn, cid)` (notify_ts=1, gefiltert über denselben `pilot_filter` wie Online/Flugplan; `cid is None` → nur „Alle"-Subs); `send_web_push` als asyncio-Task starten

**Prefile Push-Notification-Logik:**
- `_prefile_sig(p)` → `(deptime, departure, arrival)` — Änderungssignatur
- Neuer oder geänderter Prefile → `asyncio.create_task(send_prefile_push_notifications(...))`
- Unterdrückt wenn CID bereits in `_active_flights` (Pilot online — kein Prefile-Alert nötig)
- Nur an Subscriptions mit `notify_prefiles = 1` (Filter in `get_push_subscriptions_for_prefile`)
- **Nicht rückwirkend:** Ein Push entsteht nur in dem Poll, in dem der Prefile neu auftaucht oder
  sich die Signatur ändert. Ein bereits vorhandener Prefile löst beim nachträglichen Abonnieren
  keine Benachrichtigung aus.

Die Flug-State-Machine in `_poll_once`:

```
CIDs jetzt online: {A, B, C}
CIDs vorher aktiv: {B, C, D}

newly_online  = {A}       → open_flight, Alert
still_online  = {B, C}    → update position + Flugplan-Check
went_offline  = {D}       → close_flight
```

**Online-Reconnect-Debounce:** Im `newly_online`-Zweig wird die Benachrichtigung (Telegram + WebPush) nur ausgelöst, wenn der Pilot nicht innerhalb von `VATSIM_REJOIN_DEBOUNCE_SEC` (Default 900 s) zuletzt schon gemeldet wurde (`_online_last_notified[cid]`). So erzeugt ein vPilot-Reconnect (offline → kurz darauf wieder `newly_online`) keinen zweiten „ist online!"-Ping. DB-/State-Logik (`open_flight`, `upsert_live_position`, `_active_flights`) läuft unabhängig weiter — nur das Versenden wird gedämpft.

**Flugplan-Änderungserkennung** (für `still_online`-Piloten): Pro Poll wird der aktuelle DEP/ARR aus dem VATSIM-Feed mit dem in `_active_flights` gespeicherten verglichen. Bei Abweichung:
- **Kein alter Plan → neuer Plan**: `update_flight_plan()` setzt DEP/ARR und alle Flugplan-Felder (Route, Remarks, Altitude, TAS, Flight Rules, Aircraft ICAO, Alternate, Off Block, Enroute, Fuel) im laufenden Flug-Record nach.
- **Alter Plan → anderer Plan**: laufenden Flug sofort schließen (`close_flight`), neues Segment öffnen (`open_flight`) mit allen Feldern des neuen Plans. Behandelt Fälle wie Zwischenstopps oder Planänderung nach dem Start.

Ein einziges `conn.commit()` am Ende — kein partieller Schreibzustand möglich.

### `app/geo.py`

- `haversine(lat1, lon1, lat2, lon2)` — Großkreis-Abstand in km
- `icao_to_coords(icao)` — ICAO → (lat, lon) via `airportsdata`-Package (keine Netzwerk-Anfrage, statische Daten)
- `filter_event_pilots(rows, icao_list, radius_km, start_utc, end_utc)` — filtert `position_history`-Zeilen auf Piloten die im Zeitfenster innerhalb von `radius_km` um einen der ICAOs waren
- `segment_into_flights(positions, flights_rows)` — gruppiert Positionen anhand echter VATSIM-Session-Records aus der `flights`-Tabelle; jedes Segment erhält `callsign`, `departure`, `arrival`, `aircraft` aus dem passenden `flights`-Eintrag. Fallback auf Zeitlücken-Segmentierung (30-min-Gap) wenn kein `flights`-Eintrag für eine Position gefunden wird (z.B. Altdaten vor FriesenSpy-Start)

### `app/teamspeak.py`

TeamSpeak-ServerQuery-Client für die TS-Login-Benachrichtigung (Phase 1). Baut pro Poll eine kurzlebige ServerQuery-Verbindung auf (kein dauerhafter Event-Thread, kein TS-Client-Prozess).

- `parse_frs(nick)` — extrahiert die FRS-Nummer aus einem TS-Nickname via Regex (`FRS[\s_-]*(\d+N?)`; optionale Trennzeichen zwischen `FRS` und Zahl, sodass auch `FRS 144`/`FRS-144` erkannt werden; einziges erlaubtes Suffix ist das optionale `N`, z. B. `FRS13N`). Der Tag wird **normalisiert ohne Trennzeichen** zurückgegeben (`FRS 144` → `FRS144`), oder `None` wenn kein FRS-Tag gefunden wird. Portiert aus TSBot.
- `_parse_clientlist(clients, channel_id)` — filtert die rohe ts3-clientlist: nur echte Clients (`client_type == "0"`), nur im Zielkanal (channel_id 0 = ganzer Server), nur Clients mit FRS-Tag. Gibt `[{frs, nick, cid}]` zurück.
- `fetch_channel_clients(*, host, port, user, password, server_id, channel_id)` — async Wrapper: führt `_fetch_clients_sync` (login → use → clientlist → close) per `run_in_executor` aus. Gibt `None` bei Fehler zurück (kein Crash), damit der Caller zwischen nicht-erreichbarem Server (`None`) und echtem leeren Kanal (`[]`) unterscheiden kann.

### Empfänger-Auswahl (einheitlich, `app/database.py`)

Online, Flugplan und TS nutzen denselben empfängerseitigen `pilot_filter` (CID-Liste je Subscription; `NULL` = alle). Selbst-Ausschluss = eigenen CID weglassen (Modus „Nur bestimmte"). Es gibt kein separates `recipients_for`/`ts_self_frs` mehr.

- `cid_for_callsign(conn, callsign)` — mappt eine FRS/Callsign (z. B. `FRS49`) auf die CID (Quelle: `live_positions` → jüngster `flights` → `statsim_cache`), oder `None` für reine TS-Leute ohne VATSIM-Flug.
- `get_ts_push_subscriptions(conn, cid)` — TS-Opt-in-Subscriptions (`notify_ts = 1`), gefiltert über `pilot_filter` (NULL = alle; sonst nur wenn `cid` enthalten; `cid is None` → nur NULL-Filter). Spiegelt die Logik von `get_push_subscriptions_for_pilot`.
- Subjekt-Privacy bleibt über `ts_consent` (`everyone`/`nobody`) in `_poll_teamspeak` vorgeschaltet.

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
- **STATISTIKEN** — `/api/stats?days=N`; KPI-Box oben (Piloten, Flüge, Stunden, Ø/Tag, Aktivster Pilot, Ø Flugdauer — klickbar); Liniendiagramm via `/api/stats/activity?days=N` (Piloten/Flüge/Stunden/Ø Flugdauer, täglich für ≤93 Tage mit Wochentag-Labels, monatlich für 365 Tage, Dual-Y-Achse); Callsign + Pilot + geloggte Flüge (FS + ST) + letzter Flug; Pilot-Klick → `openPilotFlights()` → `/api/pilots/{cid}/flights?days=N` (sofort aus Cache, StatSim im Hintergrund); Badge „⟳ StatSim wird aktualisiert…" wenn `X-StatSim-Status: updating`; Auto-Refresh nach 10s; „Alle Flüge laden (letztes Jahr)" → `?days=0` (365-Tage-Force-Refresh); **Flugplan-Zelle (DEP→ARR) anklicken** → `openFlightDetailModal()` — zeigt dieselben Felder wie das Live-Flugplan-Modal (Flight Rules, Aircraft, DEP, ARR, Alternate, Off Block UTC, Altitude, TAS, Enroute, Fuel Endurance, Route, Remarks) plus historisch-spezifische Felder (Datum UTC, Dauer, Strecke, Quelle); optionale Felder ausgeblendet wenn leer; ◎-Klick → Track-Modal; ⎘ Teilen in Drill-Down, Track-Modal und Flugdetail-Modal
- **EVENTS** — `/api/events`; Layout: Karte oben (560px, OFM), Pilotenliste darunter; pro Pilot werden einzelne Flüge aufgelistet; Segmentierung basiert auf echten VATSIM-Session-Records (Fallback: 30-min-Gap); Karte zeigt alle Tracks aller Piloten gleichzeitig; Klick auf Flug → `highlightEventFlight()` hebt Track hervor, „↺ Alle Tracks"-Button setzt zurück; **Flugplan-Zelle (DEP→ARR) anklicken** → `openFlightDetailModal()` mit allen verfügbaren Feldern; optionale Felder und Abschnitte ausgeblendet wenn leer; ⎘ Teilen (Event-Suche + offenes Flugdetail-Modal); `searchEvents()` behandelt `datetime-local` direkt als UTC

**Client-Polling & Rate-Limiting**: `/api/prefiles` und `/api/teamspeak` werden auf **eigenem, festem Takt** gepollt (`setInterval` 60 s bzw. 30 s) — bewusst **nicht** mehr an den SSE-`positions`-Handler gekoppelt. Grund: Browser drosseln Hintergrund-Tabs und puffern eingehende SSE-Frames; beim Wiederöffnen werden hunderte gepufferte `positions`-Frames auf einmal an `onmessage` zugestellt. Solange dort je Frame ein `/api/prefiles`+`/api/teamspeak`-**Paar** ausgelöst wurde, erzeugte ein einziger Vordergrund-Wechsel ~900 HTTP-Requests in Sekunden → 429-Sturm → „Fehler beim Laden". Der SSE-Handler rendert jetzt nur noch lokal (Tabelle/Karte), ohne zusätzliche Fetches. `/api/live` läuft als unabhängiger 15-s-Fallback (iOS/PWA). Bei einem 429 zeigen `fetchAndRenderPrefiles`/`fetchAndRenderTeamspeak`/`fetchStats` **keinen** harten Fehler mehr, sondern behalten den letzten Stand (Stats: ein automatischer Retry nach 1,5 s). nginx limitiert **nur `/api/`** (`zone friesenspy_limit`, `rate=120r/m`, `burst=60 nodelay`, `limit_req_status 429`); `/api/sse` ist ausgenommen (längster Prefix), SPA-Shell/statische Assets/PWA-Icons sind **nicht** limitiert, damit der Asset-Schwall beim Laden den Burst nicht sprengt. Historie: `rate=30r/m, burst=10` für `location /` verursachte verbreitete 429 (teils als „Fehler 409" gemeldet); 30→120 r/m half live/stats, aber das prefiles+teamspeak-Paar erst die Entkopplung oben (27.06.2026).

**URL Deep-Linking** via `location.hash` (URLSearchParams): Tab, Pilot-CID, Zeitraum (days=), Track-ID/Source, Callsign (fp=), Events-Filter (icao/radius/start/end), Flugdetail-Modal (`fld=<logon_time>`) werden im Hash gespeichert → Seite neu laden öffnet den gleichen Zustand. `openFlightDetailModal()` schreibt `fld=logon_time` in den Hash; `closeFldModal()` entfernt es. `initFromUrl()` wird beim Seitenstart nach `fetchLiveInitial()` ausgeführt; re-aktiviert den korrekten Tab am Ende aller Async-Operationen (Race-Condition-Schutz).

**Karten-Layer**: OpenFlightMap (OFM) als Standard auf allen Leaflet-Instanzen (Live/Karte, Track-Modal, Events). Fünf Basislayer via `L.control.layers()`: OFM (native Tiles Zoom 6–11, `minZoom:6`), OpenTopoMap (OSM+SRTM, Zoom bis 17), Satellit (ESRI World Imagery), Light (CartoDB Positron), Dark (CartoDB Dark Matter). **OpenAIP-Overlay**: Checkbox für Luftraum/Flugplätze/Navaids — wird nur angezeigt wenn `OPENAIP_API_KEY` gesetzt; Key wird via `/api/frontend-config` an das Frontend übergeben und per `_makeAIPOverlay()` als separater Tile-Layer eingebunden. **Auto-Switch** (`_setupOFMAutoSwitch`): Solange OFM aktiv ist, wechselt die Karte bei Zoom < 7 oder Zoom > 12 automatisch auf Satellit und zurück im OFM-Bereich (Zoom 7–12). Manueller Wechsel zu einem Nicht-OFM-Layer deaktiviert den Auto-Switch; manuell zurück zu OFM reaktiviert ihn. `initLiveMap()`, `renderEventsMap()` und der Track-Modal-Init awaiten `_configPromise` (den `/api/frontend-config`-Fetch) um Race Conditions beim OpenAIP-Key-Laden zu vermeiden.

**Web Push Notifications**: Bell-Icon 🔔 im Header — sichtbar wenn `VAPID_PUBLIC_KEY` gesetzt. Klick öffnet Panel mit Toggle + Pilot-Filter. `_registerServiceWorker()` registriert `sw.js` und lädt bestehende Push-Subscription. `_subscribePush()` fragt Notification-Erlaubnis, abonniert via `pushManager.subscribe()` und postet Subscription an `/api/push/subscribe`. Service Worker (`app/static/sw.js`) empfängt `push`-Events und zeigt Notifications im Hintergrund — auch bei geschlossenem Browser. **PWA-Installation**: Web-App-Manifest (`app/static/manifest.webmanifest`, via `<link rel="manifest">`; MIME `application/manifest+json` in `main.py` registriert) + Icons (`icon-192/512`, `icon-maskable-512`, `apple-touch-icon`, erzeugt mit `generate_icons.py`) machen die SPA installierbar. Ein sichtbarer, schließbarer **Install-Banner** (`#install-banner`, oberhalb der Tab-Nav) weist darauf hin: `_maybeShowInstallBanner()` zeigt ihn nur, wenn nicht bereits `display-mode: standalone` und nicht in `localStorage` (`fs_install_dismissed`) weggeklickt. Auf Android/Desktop feuert `beforeinstallprompt` → Button öffnet den nativen Dialog (`prompt()`); auf iOS-Safari zeigt der Banner die manuelle Anleitung ("Teilen ⬆ → Zum Home-Bildschirm"). `appinstalled` blendet den Banner aus. Der alte "Als App installieren"-Button im Push-Panel bleibt zusätzlich erhalten. Pilot-Filter (Alle / bestimmte CIDs) wird serverseitig in `push_subscriptions.pilot_filter` (JSON) gespeichert. **Pilot-Filter-UX**: Bei "Alle Friesen" sind alle Checkboxen checked + disabled (visuell ausgegraut, nicht änderbar). Bei "Nur bestimmte Piloten" werden Checkboxen aktiviert; beim Umschalten von "select" → "all" wird der aktuelle Zustand in `_notifCustomFilter` (in-memory) gemerkt, sodass bei erneutem Wechsel zurück der Stand erhalten bleibt — auch ohne Speichern. Beim ersten Öffnen wird der gespeicherte Filter aus `localStorage` geladen und der Radio-Modus entsprechend wiederhergestellt. **„Push zurücksetzen"**: deabonniert, deregistriert alle SW-Registrierungen und lädt neu — erzwingt frischen FCM/APNs/WNS-Token (nötig bei `permanently-removed.invalid`-Endpoints). **Endpoint-Validierung**: `/api/push/subscribe` lehnt `permanently-removed.invalid`-Endpoints mit HTTP 400 ab. **VAPID-Keys**: `VAPID_PRIVATE_KEY` muss als raw base64url-kodierter EC-Skalar (32 Byte, 43 Zeichen, kein PEM) in config.env stehen — generiert mit `generate_vapid.py`. pywebpush mutiert das `claims`-Dict in-place (fügt `aud`/`exp` hinzu) → pro Push ein frisches Dict erstellen. WNS erfordert `ttl=3600` (TTL=0 wird von WNS abgelehnt). Bei transientem Fehler (z.B. APNs 4xx) wird einmal nach 5 Sekunden wiederholt.

**Versionierung & Changelog**: Single Source of Truth ist die Repo-Datei `app/CHANGELOG.json`
(neueste Version zuerst; je Eintrag `version`, `date`, `title`, `items`). `app/version.py` liest
sie ein und stellt `VERSION` (= `CHANGELOG[0].version`) und `CHANGELOG` bereit; `/api/frontend-config`
liefert beides ans Frontend. Im Header zeigt `#app-version` die kleine Versionsnummer (Klick →
Versionsverlauf-Modal `#changelog-modal`, wiederverwendet die `.fp-modal-*`-Klassen). `#changelog-banner`
(Basis-Styling vom Install-Banner) zeigt die Neuerungen der aktuellen Version **einmal pro Version**:
es erscheint nur, wenn `localStorage['fs_changelog_seen'] !== version`; ✕ oder das Öffnen des Verlaufs
setzt den Key auf die aktuelle Version. **Release-Workflow:** bei signifikanten Änderungen einen neuen
Eintrag oben in `app/CHANGELOG.json` einfügen — das Banner erscheint dann automatisch bei allen Nutzern.

Design: FriesenFlieger-Blau (`#04080f` Hintergrund, `#2d9cdb` Blau, `#D31141` Vereinsrot).

## Datenfluss SSE

```
Browser                     FastAPI                  VatsimPoller
   │                           │                          │
   │─── GET /api/sse ──────────►│── subscribe_sse() ──────►│  (eigene Queue registriert)
   │                           │                          │
   │                           │◄─── queue.get() ─────────│
   │                           │     (wartet bis Event)   │
   │                           │                          │
   │                           │    (15s später)          │
   │                           │    VATSIM poll ──────────►│
   │                           │                          │─ State-Machine
   │                           │                          │─ SQLite commit
   │                           │◄─ broadcast_sse({...}) ──│  (put_nowait je Client-Queue)
   │                           │                          │
   │◄── data: {...}\n\n ────────│                          │
   │  (Disconnect → unsubscribe_sse() im finally)         │
```

## Datenfluss TS-Login-Benachrichtigung (Phase 1)

```
TeamSpeak-Server (port 10011)
        │
        ▼  alle TS_POLL_INTERVAL Sekunden (Default: 30s)
  _poll_teamspeak (APScheduler Job: ts_poll)
        │
        ├─► fetch_channel_clients (ts3 ServerQuery, kurzlebige Verbindung)
        │         None  → Poll überspringen (Server nicht erreichbar, Snapshot bleibt)
        │         []    → gültiger leerer Kanal (Baseline oder Diff)
        │         [...]  → FRS-Clients im Kanal
        │
        ├─► self.ts_clients = clients  (Anzeige-Snapshot)
        │         → /api/teamspeak (Live-Tab-Panel) + /widget-Zähler; nach außen nur frs
        │         → ohne VAPID endet der Poll hier (reiner Display-Modus, keine Pushes)
        │
        ├─► Präsenz-Streak (_ts_streak)
        │         Erster Poll → Baseline (präsente FRS = _TS_BASELINE_STREAK), keine Notifications
        │         je präsenter FRS: streak += 1; abwesende fallen raus
        │         bestätigt = streak erreicht erstmals TS_MIN_DWELL_POLLS + 1
        │
        ├─► Pro bestätigter FRS:
        │         Debounce-Check (_ts_last_notified, TS_REJOIN_DEBOUNCE_SEC)
        │         get_ts_consent(frs) → visibility == 'nobody' ? keine Empfänger
        │         cid_for_callsign(frs) → CID (oder None bei reinen TS-Leuten)
        │         get_ts_push_subscriptions(conn, cid) → notify_ts=1 ∩ pilot_filter
        │
        └─► send_web_push(recipients, payload)
                  Payload: {"title": "🎧 <nick> ist im TeamSpeak", "body": "FriesenFlieger TeamSpeak"}
```

**Consent-Modell (Phase 1):** Admin setzt Einträge in `ts_consent` via `manage_ts_consent.py`. Kein Eintrag = Default `everyone`. Phase 2 (noch nicht implementiert) soll Consent aus einem Forumsprofil-Flag synchronisieren.

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
    notify_ts      INTEGER DEFAULT 0,   -- 1 = TS-Login-Benachrichtigungen erwünscht
    ts_self_frs    TEXT,                -- tote Spalte (nicht mehr genutzt; Selbst-Ausschluss via pilot_filter)
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

-- TS-Login-Einwilligung pro FRS (Phase 1: Admin-gesetzt via manage_ts_consent.py)
CREATE TABLE ts_consent (
    frs        TEXT PRIMARY KEY,
    visibility TEXT DEFAULT 'everyone',  -- everyone | nobody (ausgewertet); allowlist nicht mehr genutzt
    allowlist  TEXT,                     -- tote Spalte (nicht mehr ausgewertet)
    updated_at TEXT
);
```
