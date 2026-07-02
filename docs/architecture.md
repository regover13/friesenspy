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

### `app/auth.py`

Admin-Authentifizierung per signiertem httponly-Cookie.

- **`ADMIN_PASSWORD`** (aus `config.py`) — leer = Admin-Bereich deaktiviert; gesetzt = Cookie-Login aktiv.
- **Cookie `fs_admin`**: HMAC-SHA256-Signatur über das konfigurierte Passwort, signiert mit `SECRET_KEY` (stdlib `hmac`, kein Session-Store). Ein Passwort- oder Key-Wechsel invalidiert alle bestehenden Cookies sofort, da die Signatur nicht mehr passt.
- **`require_admin`** — FastAPI-Dependency, die das Cookie prüft und bei fehlendem oder ungültigem Cookie `401` zurückwirft. Schützt alle `/api/admin/*`-Endpoints.
- **`POST /api/admin/login`** setzt das Cookie (httponly, SameSite=Strict); **`POST /api/admin/logout`** löscht es; **`GET /api/admin/me`** gibt `{"admin": true}` zurück wenn die Session gültig ist.
- Die Admin-Seite selbst (`/admin` → `app/static/admin.html`) ist eine eigenständige Vanilla-JS-Seite; sie nutzt denselben Login-Flow und kommuniziert ausschließlich über die `/api/admin/*`-Endpoints.

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

SQLite mit WAL-Mode und `PRAGMA foreign_keys=ON`. Zwölf Tabellen:

| Tabelle | Inhalt |
|---------|--------|
| `pilots` | CID + Name; `list_pilots`/`upsert_pilot`/`delete_pilot` für die Admin-Piloten-Verwaltung (`upsert_pilot` aktualisiert den Namen via `ON CONFLICT`, `added_at` bleibt erhalten). Die Tabelle füllt sich auch automatisch aus VATSIM — die Verwaltung dient der Namenspflege, ist **keine** Mitglieder-Allowlist |
| `app_settings` | Generischer Key-Value-Store (`key` PK, `value`, `updated_at`); `get_app_setting`/`set_app_setting`. Schlüssel `banner_version`: `auto` (Default) \| `off` \| konkrete Version — steuert den Startseiten-Hinweis-Banner |
| `flights` | Pro Flug: Callsign, Typ (`aircraft_short`), DEP/ARR, Logon/Logoff, `duration_min` (Online-/Verbindungszeit), `block_min` (Bewegungszeit), `distance_nm` (GPS-Summe via Haversine), `superseded_by` (reversibler Dedup-Verweis), sowie vollständige Flugplan-Felder: `route`, `remarks`, `cruise_altitude`, `cruise_tas`, `flight_rules`, `aircraft_icao`, `alternate`, `deptime`, `enroute_time`, `fuel_time` (ab Aufzeichnungsdatum gefüllt, ältere Einträge NULL) |
| `live_positions` | Aktuelle Position pro CID (UPSERT, maximal 1 Zeile pro CID) |
| `position_history` | Jede einzelne VATSIM-Positions-Update (für Tracks + Events) |
| `calendar_events` | FriesenFlieger Google-Kalender (alle 6h synchronisiert, UID als Primary Key); `route` (CSV aller ICAOs) + `is_bummel` (Flag) für die FriesenFliegerBummel-Erkennung |
| `bummel_races` | Persistente Bummel-Rennen (vom Poller beim Kalender-Sync oder Admin manuell angelegt); `revealed_at` steuert die Fairness-Verdeckung — `NULL` = noch verborgen, Zeitstempel = enthüllt (Latch); `started_at` = Start-Latch (erster Pilot mit Blockzeit an einem Streckenflugplatz, `NULL` = noch kein Start); `push_enabled` steuert Push-Benachrichtigungen je Rennen (1 = an, 0 = aus); `source` ∈ `calendar` | `manual` |
| `bummel_overrides` | Admin-Korrekturen pro Rennen + Pilot (PK `race_id + cid`); `action` ∈ `exclude` \| `disqualify` \| `winner` \| `manual`; bei `manual`: `manual_total_min` ersetzt die gemessene Block-Zeit; Overrides werden durch `apply_bummel_overrides` auf die Wertung angewendet |
| `transport_events` | Persistente FriesenKutter-Transport-Events (Poller beim Kalender-Sync via Stichwort „friesenkutter" oder Admin manuell); `route` (ICAO-CSV), `destination` (Ziel-ICAO — nur Flüge dorthin laden Fracht), Latches `started_at`/`goal_reached_at`/`summarized_at` für die Pushs; `source` ∈ `calendar` \| `manual` |
| `transport_cargo` | Fracht-Manifest je Event (geordnet): `position`, `name` (Frachtart), `target_kg`. Σ `target_kg` = Event-Ziel; leeres Manifest = reiner Zähler |
| `aircraft_payloads` | Zuladung je Flugzeugtyp (Admin-editierbar): `mtow_kg`/`empty_kg`/`fuel_kg` (Tankinhalt; Default: halbe Füllung — der Vorschlag liefert volle Tanks als Maximum fürs Label)/`crew_kg` (Pilot, Default 85, zählt nicht als Fracht) → `payload_kg = max(0, mtow−empty−fuel−crew)`, direkt überschreibbar; `source` ∈ `manual` \| `llm` \| `default`; `make_model` (Klartext von Claude) |
| `cargo_catalog` | Frachtart-Stammdaten (Phase 2): `name`, `emoji`, `per_flight_max_kg` (Obergrenze pro Flug für Co-Load). Beim Manifest wählbar; `set_transport_cargo` speichert Emoji/Max als Snapshot in `transport_cargo`. In `init_db` idempotent geseedet (`seed_cargo_catalog`) |
| `transport_quips` | Cache der lustigen KI-Sprüche je Flug (PK `event_id + flight_key` mit `flight_key = "{cid}:{logon_time}"`). Tagesend-Zusammenfassung liegt in `transport_events.summary_quip` |
| `push_subscriptions` | Browser-Push-Subscriptions (Endpoint, ECDH-Keys, `pilot_filter` als JSON-Array — gilt für Online/Flugplan/TS, `notify_prefiles` Flag, `notify_ts` Flag, `notify_events` Flag; `ts_self_frs` = tote Spalte, nicht mehr genutzt; `created_at` wird bei Re-Abo desselben Endpoints mit aktualisiert) |
| `prefile_sigs` | Letzte bekannte Prefile-Signatur pro CID (`deptime`, `departure`, `arrival`) — wird nach jedem Poll persistiert, damit Container-Neustarts keine Änderungen verpassen |
| `ts_consent` | Subjekt-Einwilligung pro FRS für TS-Login-Sichtbarkeit (`visibility` ∈ `everyone`/`nobody`; `allowlist`-Spalte existiert noch, wird aber nicht mehr ausgewertet) — kein Eintrag = Default `everyone` |
| `event_reminders_sent` | Gesendete Event-Erinnerungen (Latch-Tabelle): `uid` (Kalender-Event-UID als PRIMARY KEY) + `sent_at` — verhindert, dass eine Erinnerung mehrfach versandt wird; idempotent über Container-Neustarts |

Drei Indizes: `idx_ph_cid_ts`, `idx_ph_ts`, `idx_flights_cid`.

**Sessionisierung — `(cid, logon_time)` als Schlüssel.** Eine VATSIM-Verbindung ist eindeutig über `(cid, logon_time)` bestimmt (VATSIM kennt keine Session-ID; `logon_time` ist pro Verbindung stabil). Diese Invariante wird strukturell erzwungen durch einen **partiellen Unique-Index** `idx_flights_session ON flights(cid, logon_time) WHERE superseded_by IS NULL` — pro Verbindung existiert höchstens **ein aktiver** Flug. Die Spalte `superseded_by` (NULL = aktiv, sonst id des Behalt-Records) erlaubt es, Duplikate **reversibel** zu markieren statt zu löschen.

**`open_flight(conn, ..., *, route, remarks, ...)`** — `INSERT … ON CONFLICT(cid, logon_time) WHERE superseded_by IS NULL DO NOTHING`, danach wird die bestehende id zurückgegeben. Ein erneutes Öffnen derselben Verbindung (z. B. nach Container-Neustart) ist damit ein **strukturelles No-Op** — unabhängig vom In-Memory-State.

**`update_flight_plan(conn, flight_id, departure, arrival, *, route, remarks, ...)`** — setzt DEP/ARR und alle erweiterten Flugplan-Felder eines laufenden Fluges nachträglich, wenn der Pilot den Plan nach dem Verbindungsaufbau einreicht oder ändert. Wird ausschließlich vom Poller aufgerufen (Flugplanwechsel-Erkennung in `_poll_once`).

Alle DB-Operationen sind synchron (SQLite ist thread-safe mit WAL). Verbindungen werden pro Request geöffnet und in `finally`-Blöcken geschlossen.

**`merge_fragmented_flights(flights, gap_minutes=5, conn=None)`** — führt zwei aufeinanderfolgende Verbindungen desselben Piloten read-time zu **einem logischen Flug** zusammen (Reconnect-Stitching). Ein vorübergehender Reconnect ist für VATSIM zwei Verbindungen (zwei Zeilen, atomar gespeichert); hier werden sie für Anzeige/Statistik gemergt. Bedingungen:

1. **Gleicher Callsign** (nicht leer)
2. **Flugplan = Hauptsignal** — entweder (a) genau einer der beiden hat keinen Flugplan (no-FP-Reconnect vor Neu-Filen), oder (b) beide haben denselben nicht-leeren DEP+ARR (unterbrochener Flug)
3. **Gap-Fenster nach Flugplan** — same-FP bis **30 Min** (`_RECONNECT_GAP_SAME_FP_MIN`, der gleiche Flugplan trägt die Beweislast), no-FP bis **15 Min** (`_RECONNECT_GAP_NO_FP_MIN`); Toleranz −2 Min für VATSIM-Jitter
4. **Geo-Kontinuität** (`_segments_continuous`, nur mit `conn`): **Distanz-Budget** statt fester Radius — der Abstand zwischen der **letzten Position von Segment 1** und der **ersten Position von Segment 2** darf höchstens `Lückendauer × 600 kt + 10 nm` betragen. Das löst den Fall „Pilot 10 Min ohne Netz, Sim fliegt weiter" (Reconnect taucht stromabwärts auf), weist aber Teleports ab. **Fertig-gelandet-Regel**: ist Segment 1 nachweislich **geflogen** (mind. eine Position ≥ `_FLOWN_MIN_GS_KT` = 60 kt) und endete **am Boden** (letzte Position ≤ `_LANDED_MAX_GS_KT` = 40 kt), ist der Flug abgeschlossen — Segment 2 ist dann ein **neuer Flug**, kein Reconnect, unabhängig vom Landeort. Das verhindert beide Stale-FP-Fälle vom Live-Test 2026-07-01 (FRS102): der Rückflug mit stehengebliebenem Flugplan startet „am Ziel" und passierte die Richtungsprüfung (282+286); und er landet am FP-**Start**, sodass der nächste echte Hinflug wieder als „Fortschritt Richtung Ziel" durchging (286+287). Reine Boden-Segmente (nie geflogen, z. B. Gate-Reconnect vor dem Neu-Filen) mergen weiterhin. Zusätzlich **Richtungsprüfung**: Segment 2 darf nicht deutlich weiter vom Ziel entfernt sein als das Ende von Segment 1. Fallback Merge, wenn keine GPS-Daten vorhanden.

Das gemergde Ergebnis übernimmt logon_time des früheren, logoff_time des späteren Segments; **duration_min wird addiert** (die Disconnect-Lücke zählt nicht mit → keine Inflation); distance_nm wird addiert. Gegenprobe: gleicher Callsign aber **anderer FP** (z. B. Rückleg) → kein Merge, zwei Flüge.

**`backfill_flight_distances(conn)`** — läuft beim Start in `init_db()` einmalig: Berechnet `distance_nm` für abgeschlossene Flüge nach, die noch `0` haben aber `position_history`-Einträge besitzen (Haversine-Summe über alle Positionspunkte im Logon–Logoff-Fenster). Idempotent — bereits berechnete Flüge (`distance_nm > 0`) werden übersprungen. Deckt Flüge ab, die vor Einführung der GPS-Distanzberechnung aufgezeichnet wurden.

**Block-Zeit (`block_min`).** Zusätzlich zur **Online-Zeit** (Verbindungsdauer logon→logoff, `duration_min`) wird die **Block-Zeit** geführt: die **Summe der bewegten Abschnitte** (`groundspeed > _BLOCK_GS_KT`, 2 kt) innerhalb [logon, logoff] aus `position_history` (`_block_minutes()`/`_block_seconds()`, gate-to-gate inkl. Taxi). **Belegte Standphasen** — zusammenhängende Positionen mit `groundspeed ≤ 2 kt` zwischen zwei Bewegungen, ab `_BLOCK_STAND_MIN_SEC` (10 min) — zählen **nicht** mit: so verfälscht eine Zwischenlandung ohne Disconnect die Bummel-Wertung nicht mehr (vorher zählte „erste bis letzte Bewegung" die Standzeit mit). Kürzere Stopps (Rollhalt) bleiben enthalten; Datenlücken **ohne** Stillstands-Beleg (Feed-Aussetzer) zählen weiterhin voll. `close_flight` setzt `block_min` mit; `backfill_block_minutes(conn)` füllt Bestandsflüge in `init_db()` nach; `merge_fragmented_flights` summiert `block_min` der Segmente; `canonicalize_flights` liefert es mit. Block-Zeit ist **FriesenSpy-only** (StatSim/Altflüge ohne dichte GS-Spur → keine Block-Zeit). So lässt sich „angesteckt am Gate" von echter Bewegung trennen.

**`close_stale_flights(conn, max_age_hours=8)`** — Startup-Notnagel: schließt offene Flüge älter als 8 h (echte Waisen, die Rehydration + Live-Close nicht erwischt haben). Als `logoff_time` wird die letzte `position_history` ab `logon_time` verwendet, **gedeckelt auf `MIN(logon_time)` der nächsten Session** desselben Piloten — so kann ein Logoff nie Positionen eines späteren Fluges greifen (das war die Ursache der 139-Min-Zombie-Inflation). Ohne Positionen wird `logon_time` gesetzt (duration=0, ghost-gefiltert).

**`consolidate_flights(conn, *, statsim_correct=True, shrink_margin_min=10)`** — läuft idempotent in `init_db()` **vor** dem Anlegen des partiellen Unique-Index (Reihenfolge zwingend, sonst Constraint-Verletzung) und ist als `scripts/consolidate_flights.py` (mit `--dry-run`) manuell aufrufbar. **Selbst-korrigierend:** zu Beginn werden der Unique-Index gedroppt und `superseded_by` zurückgesetzt — jeder Lauf rechnet von vorn (idempotent), sodass auch früher falsch markierte Flüge wieder auftauchen. Reversibler Cleanup in fünf Schritten: (A) mehrere offene Flüge je cid → nur die **jüngste** (aktuelle Live-Verbindung) offen lassen, ältere offene Flüge als beendete Verbindungen **schließen** (gedeckelter Logoff, kein supersede) — ein Pilot hat nur eine Verbindung gleichzeitig; mehrere offene Zeilen entstehen, wenn ein Disconnect verpasst wurde (z. B. Reconnect über einen Neustart) und sind sequenzielle, keine gleichzeitigen Verbindungen; (B) exakte Duplikate (gleiche cid+logon_time) → Keeper-Priorität **(1) Flug mit echtem Inhalt** (Nicht-Ghost: `distance_nm > 0.5 OR duration_min > 5`), (2) offener Flug, (3) niedrigste id — verhindert, dass ein 0-Min-Ghost mit gleicher logon_time den echten Flug verdrängt; (C) Zombie-Logoffs auf die gedeckelte letzte Position korrigieren (nur wenn das die Dauer um ≥ `shrink_margin_min` verkürzt); (D) StatSim-Backstop: grob unplausible FS-Dauern (> 2× StatSim + 10) auf den StatSim-Wert korrigieren; (E) **Selbstheilung unmöglicher Blockzeiten**: `block_min > duration_min` kann nicht sein → mit dem gespeicherten Fenster neu berechnen. C und D rechnen `block_min` bei jeder Fenster-Korrektur mit (früher blieb dort eine Blockzeit aus dem aufgeblähten Fenster stehen — Ursache von „block 92 > duration 28", Live-Test 2026-07-01). `consolidate_flights` committet **nicht** selbst (Aufrufer committen → ermöglicht Dry-Run via rollback). Rückgängig: `UPDATE flights SET superseded_by = NULL`.

**`reconstruct_orphaned_flights(conn, *, cids=None)`** — läuft in `init_db()` nach `consolidate_flights` **und** (cid-gefiltert) direkt nach jedem StatSim-Refresh (Drill-down-Hintergrund-Fetch in `main.py`, Neu-Pilot-Load im Poller): rekonstruiert flights-Einträge für **verwaiste GPS-Tracks** (A1-Schadensbild). **Anker ist die StatSim-LANDEZEIT** (`arrived` → `logoff_time`): StatSims `loggedOn` ist die Session-Anmeldung und bei mehreren Flügen einer Verbindung für alle gleich — als Flugbeginn unbrauchbar. Kandidat = jede StatSim-Landung mit Strecke, die in **keinem** aktiven FS-Fenster (± `_RECONSTRUCT_COVER_MARGIN_MIN` = 5 min) liegt. Der Flugbeginn wird per Rückwärtssuche im Track bestimmt (letzte belegte Standphase ≥ `_RECONSTRUCT_STAND_SEC` = 5 min vor der Landung trennt das Bein vom vorigen; sonst ab voriger Session, gedeckelt `_RECONSTRUCT_MAX_LOOKBACK_H` = 3 h); Fensterende = Landung + `_RECONSTRUCT_MARGIN_MIN` = 10 min Taxi-in, gedeckelt auf die nächste Session. Nur mit belegter Flugbewegung (≥ 2 Positionen `groundspeed ≥ 40`); Dauer/Distanz/Block aus den **echten Positionsdaten**, Strecke/Callsign/Muster aus StatSim. Idempotent (einmal rekonstruiert deckt die neue Zeile die Landung); läuft nie für offene Sessions; Historie ohne Track bleibt unberührt. **Achtung Schwester-Regel:** `consolidate_flights` Schritt D nimmt aus demselben Grund das `MAX(duration_min)` aller StatSim-Zeilen derselben Anmelde-Minute — die Zeile des ersten Beins würde eine legitime Multi-Leg-Session fälschlich schrumpfen.

**`canonicalize_flights(conn, *, cids, callsign_prefix, start, end, include_statsim)` — die EINZIGE Wahrheit für „echte Flüge".** Liefert eine nach logon_time absteigend sortierte Liste kanonischer Flug-Dicts (Feld `source`: `friesenspy` | `statsim`). Pipeline: aktive FS-Flüge laden (`superseded_by IS NULL`, abgeschlossen) → Reconnect-/Fragment-Merge (`merge_fragmented_flights`) → Ghost-Filter (`distance_nm ≤ 0.5 AND duration_min ≤ 5` verwerfen) → StatSim laden und gegen die kanonische FS-Menge deduplizieren (`_dedup_statsim_against_fs`). **Alle Views rufen diese eine Funktion** — `get_stats`, `get_stats_activity` (aggregieren in Python) sowie der Piloten-Detail-Endpoint und (für die FS-Flüge) der Events-Endpoint. Dadurch sind Flugzahl/Dauer/Piloten über alle Sichten **garantiert identisch** (zuvor gab es fünf divergierende Inline-Implementierungen).

**Ghost-Flight-Filter:** zentral in `canonicalize_flights` (Schritt 2). Verworfen werden (a) Test-Connects (`distance_nm ≤ 0.5 AND duration_min ≤ 5`) und (b) **belegte Steh-Sessions**: keine Strecke, `block_min` 0 und Positionen im Fenster vorhanden — wer verbunden nur herumsteht, hat nicht geflogen, egal wie lange (Live-Test 2026-07-01: 14-min-Session mit stalem FP erschien als 0-nm-„Flug"). Echte Kurzstrecken (z. B. 4 min, 15 nm) bleiben; ältere Flüge **ohne** Positionsdaten bleiben über `duration_min > 5` erhalten (kein Stillstands-Beleg → im Zweifel echter Flug).

**StatSim-Deduplizierung:** an **einer** Stelle (`_dedup_statsim_against_fs`). Ein StatSim-Eintrag wird unterdrückt, wenn (a) sein Logon innerhalb eines FS-Fensters [logon, logoff] liegt, oder (b) gleiche Strecke und FS-Logon bis 10 Min nach StatSim (Flugplanwechsel nach Connect). Distanz/Track/Flugplan bleiben immer FriesenSpy (reicher); StatSim korrigiert nur kaputte FS-Dauern (siehe `consolidate_flights` Schritt D).

**`compute_bummel_standings(conn, route_icaos, start, end, *, cids, radius_km)` — FriesenFliegerBummel-Wertung.** Baut auf `canonicalize_flights` auf (Fragment-Merge/Ghost-Filter geerbt). **Anwesenheit GPS-basiert:** Start/Ziel je Flug werden aus der ersten/letzten Position (`_first_pos`/`_last_pos`) als nächstgelegener Streckenflugplatz im Umkreis `radius_km` (Default `_BUMMEL_AIRPORT_RADIUS_KM` = 10 km; pro Rennen via `bummel_races.radius_km` überschreibbar) bestimmt — der gefilte **Flugplan dient nur als Fallback** ohne GPS-Track (z. B. reine StatSim-Flüge). Dadurch sind Flugplan-Tippfehler irrelevant. ⚠️ Ein zu großer `radius_km` (z. B. 100 km) ordnet Nachbarflugplätze fälschlich der Strecke zu — sinnvoll ist „klar unter dem Abstand zweier Streckenplätze".

**Track-/tour-basiert (Bummel = gemütlich):** Statt jedes Bein einzeln zu prüfen, bildet die Wertung pro Pilot eine zeitlich geordnete **Tour** — vom ersten Bein, dessen Start auf der Strecke liegt, bis zum letzten Bein, dessen Ziel auf der Strecke liegt. **Zwischenlandungen dazwischen sind erlaubt** (z. B. EDPS→EDNX→EDMA) und brechen die Wertung nicht. Gewertete Zeit = Summe `block_min` (Fallback `duration_min`) der Tour-Beine; da `block_min` pro Flug zählt, fällt die **Bodenzeit der Zwischenstopps automatisch raus**. **Frühstarter:** Flüge werden mit Vorlauf `_BUMMEL_EARLY_START_LOOKBACK_H` (12 h) geladen und nach Überlappung mit dem Eventfenster (`logoff_time >= start`) gefiltert — wer vor `start` losfliegt, aber im Fenster unterwegs ist, zählt mit **voller Blockzeit**. **Komplett** = alle Streckenflugplätze in der Tour besucht (Set-Inklusion, Reihenfolge/Richtung egal). Komplette Touren kommen ins Ranking (aufsteigend nach dem Abstand zum Schnitt), unvollständige werden separat mit `visited`/`missing` gelistet — bewusst, damit ein nicht erkanntes Bein sofort sichtbar ist, statt den Piloten still zu verwerfen. Jeder Standing-Eintrag trägt zusätzlich `aircraft` (repräsentatives Muster) und `leg_count`.

**Sekundengenaue Wertung (Gleichstand-Auflösung).** Zusätzlich zur Minuten-Wertung wird pro Bein eine **sekundengenaue Block-Zeit** geführt: `_block_seconds(conn, cid, logon, logoff)` summiert die bewegten Abschnitte aus `position_history` (belegte Standphasen ≥ 10 min ausgenommen; Fallback `minutes * 60`, z. B. StatSim ohne dichten Track) und summiert sich je Pilot zu `total_sec`. Daraus berechnet die Wertung den **signierten** Abstand `delta_sec = round(total_sec − average_sec)` (positiv = über dem Schnitt, negativ = darunter) und sortiert das Ranking sekundengenau mit dem Sortierschlüssel `(abs(delta_sec), total_sec, cid)` — das löst Gleichstände auf, die bei gleicher Minuten-Blockzeit entstünden. Die **Anzeige** von Block-Gesamtzeit und Schnitt bleibt in Minuten; nur der Abstand zum Schnitt wird signiert + sekundengenau gezeigt. Neue Felder pro Eintrag: `total_sec`, `delta_sec`; auf Standings-Ebene zusätzlich `average_sec`. Das parallel weiter berechnete `delta` (gerundete Minuten-Differenz) bleibt nur aus Kompatibilitätsgründen erhalten. Die Sekunden-Felder stehen auf der Whitelist von `public_bummel_view` **nicht** und werden daher vor der Enthüllung nicht durchgereicht (Fairness).

**Fairness-Verdeckung und Enthüllungs-Logik (Bummel-Rennen).**

- **`_effective_dtend(race)`** — gibt `dtend` aus `bummel_races` zurück. Fehlt es im Original-Kalendertermin, hat `upsert_calendar_bummel_race` es beim Anlegen auf Mitternacht UTC des Folgetags (00:00:00Z nach dem Starttag) gesetzt, sodass `_effective_dtend` immer einen gültigen Zeitstempel liefert.

- **`public_bummel_view(conn, race)`** — zentrale Redigierfunktion. Prüft `revealed_at IS NULL`; ist die Enthüllung noch nicht erfolgt, werden aus der Antwort entfernt: Block-/Gesamtzeiten, Durchschnitt, Abstand zum Schnitt, Ranking-Reihenfolge, Lande-/Logoff-Zeit, Online-Dauer, geflogene nm. Sichtbar bleiben: Callsign, Name, Flugzeugtyp, Flugplan (Start/Ziel/Route), Abflugzeit, besuchte/fehlende Flugplätze, Anzahl Beine, wer gerade unterwegs ist. Die Redigierung passiert **serverseitig** — die Zeiten stehen vor Enthüllung nicht mal im JSON.

- **`_bummel_anyone_in_progress(conn, race)`** — prüft, ob noch ein Teilnehmer aktiv unterwegs ist: offener Flug (`logoff_time IS NULL`), der vor `dtend` gestartet hat und dessen Start-Airport zur Strecke gehört.

- **`update_bummel_starts(conn)`** — Start-Latch, ebenfalls vom `bummel_reveal_check`-Job (alle 60 s) aufgerufen. Prüft alle Rennen mit `started_at IS NULL` und `status = running`; setzt `started_at = now()` sobald mindestens ein Teilnehmer eine Blockzeit an einem Streckenflugplatz aufweist (d. h. der erste Pilot hat abgehoben). Einmal gesetzt wird `started_at` nicht zurückgesetzt. Ist `push_enabled = 1`, löst der Job direkt einen `send_web_push`-Broadcast aus — ausschließlich an Subscriptions mit `notify_events = 1` (via `get_push_subscriptions_for_events`) („FRSxx hat den Bummel gestartet!").

- **`update_bummel_reveals(conn)`** — Enthüllungs-Latch, aufgerufen vom Poller-Job `bummel_reveal_check` (alle 60 s). Durchläuft alle Rennen mit `revealed_at IS NULL` **und `reveal_suppressed = 0`** (ein vom Admin manuell verborgenes Rennen wird übersprungen — sonst würde der Job ein bereits abgelaufenes Rennen sofort wieder enthüllen). Enthüllt (setzt `revealed_at = now()`) ein Rennen, sobald **beide** Bedingungen erfüllt sind: (1) `_effective_dtend` ist überschritten, (2) `_bummel_anyone_in_progress` liefert `False`. Ist noch ein Nachzügler in der Luft, wartet der Job weiter (`status = waiting`). **Einmal enthüllt bleibt enthüllt** — der Zeitstempel in `revealed_at` wird nie zurückgesetzt (`set_bummel_revealed`). Ist `push_enabled = 1`, wird bei der Enthüllung ein `send_web_push`-Broadcast ausschließlich an Subscriptions mit `notify_events = 1` (via `get_push_subscriptions_for_events`) versandt. Dasselbe gilt für die manuelle Enthüllung über `POST /api/admin/bummel/races/{id}/reveal` — der Ergebnis-Push wird einmalig und gegated über `push_enabled` an `notify_events`-Abonnenten gesendet.

- **`apply_bummel_overrides(standings, overrides)`** — reine Funktion, wendet die Admin-Overrides aus der `bummel_overrides`-Tabelle auf die berechnete Wertung an. `exclude` entfernt den Piloten vollständig; `disqualify` belässt ihn in der Liste, zieht ihn aber aus Schnitt und Ranking heraus; `winner` setzt Rang 1 erzwungen; `manual` ersetzt `total_min` durch `manual_total_min` und rechnet Schnitt und Ranking neu. Wird von `public_bummel_view` und dem Admin-Preview-Endpoint gleichermaßen aufgerufen — Overrides wirken auf alle öffentlichen Sichten.

**`app/calendar_sync.py` — `parse_route(location, summary, description)`.** Sammelt alle 4-buchstabigen ICAO-Codes aus Ort, Titel und Beschreibung (Reihenfolge erhaltend, dedupliziert) → `route`-CSV. `is_bummel` wird gesetzt, wenn „Bummel" in Titel/Beschreibung steht, die Strecke ≥ 2 Flugplätze hat **und** plausibel ist: `_route_is_plausible` lehnt ab, sobald zwei auflösbare Flugplätze weiter als 600 nm auseinanderliegen (fängt zufällig als ICAO erkannte Wörter ab; reale Bummel-Strecken liegen < 200 nm). `parse_cargo_lines(description)` liest optional eine Fracht-Zeile hinter dem Marker `Fracht:` (kommagetrennt mit Leerzeichen, um Dezimalkommas nicht zu zerreißen) → `[{name, target_kg}]`. `upsert_calendar_transport_event` gleicht diese Namen beim **erstmaligen** Anlegen gegen `cargo_catalog` ab (Emoji/Kappung) und befüllt das Manifest; existiert bereits eines (z. B. vom Admin gepflegt), bleibt es bei erneutem Sync unangetastet.

**FriesenKutter-Fortschritt (`compute_transport_progress`).** Baut wie der Bummel auf `canonicalize_flights` auf. Ein Flug ist Feed-relevant, wenn Start UND Ziel (GPS-korrigiert via `_nearest_airport`, Flugplan als Fallback) in der Streckenmenge liegen (dep≠arr). **Beladen** ist nur, wer am `destination` ankommt; Rückflüge zählen 0 kg, erscheinen aber im Feed. Beladene Flüge füllen das Fracht-Manifest nach Abflugzeit per **Co-Load**: jeder Flug verteilt seine Zuladung in Manifest-Reihenfolge über die noch nicht vollen Frachtarten, je Frachtart gekappt durch `per_flight_max_kg`; der Rest fließt in die nächste Frachtart (ein Flug kann mehrere Frachtarten tragen → `flights[].cargo_lines`). Zuladung je Typ aus `aircraft_payloads` (Fallback: `transport_default_payload_kg` aus `app_settings`). Der Feed wird absteigend (neueste oben) zurückgegeben, mit gecachtem KI-Spruch je Flug (`transport_quips`) und `summary_quip`. Der Poller-Job `transport_event_check` latcht Start/Ziel/Feierabend, sendet je einmal einen Push, erzeugt (falls aktiviert) Flug-Sprüche im Hintergrund (`asyncio.to_thread`) und beim Feierabend die Tagesend-Zusammenfassung. **Der Feierabend-Latch wartet auf Nachzügler** (`transport_anyone_in_progress`, analog `_bummel_anyone_in_progress` beim Reveal): ist `dtend` erreicht, aber noch ein offener FRS-Flug mit Start auf der Strecke unterwegs (vor `dtend` begonnen, ohne Live-Ankunfts-Latch — ein Latch fixiert den Beitrag bereits), wird die Zusammenfassung verschoben, bis das Ergebnis final ist. Seit Live-Ankunft ohne Disconnect: die `loaded`-Bedingung ist zusätzlich wahr, wenn ein Eintrag in `transport_live_arrivals` existiert (`(cid, logon_time)` — gesetzt vom Poller via `check_live_arrival`, sobald ein noch offener Flug innerhalb `_BUMMEL_AIRPORT_RADIUS_KM` um `destination` auf `< _BLOCK_GS_KT` abbremst); dieser Latch hebt auch den Strecken-Filter auf, sodass die Fracht selbst dann gezählt bleibt, wenn der Pilot später weit außerhalb der Strecke disconnectet. Zusätzlich werden aktuell offene Flüge (`open_transport_flights`) mit Start auf der Strecke in den Feed aufgenommen (0 kg bis der Latch greift) — bisher wurden sie komplett ignoriert, da `canonicalize_flights` einen abgeschlossenen Flug voraussetzt.

### `app/llm.py`

Schlanke Claude-API-Anbindung (offizielles `anthropic`-SDK) mit **Silent-Fail**: `suggest_aircraft_payload(type_code)` (Modell `claude-haiku-4-5` seit v7.4.2, ~4 ct/Recherche; Haiku lehnt den `effort`-Parameter ab — `output_config` nur mit `format`) **recherchiert per Web-Search** (serverseitiges `web_search`-Tool, `max_uses=3`) die dokumentierten Handbuch-/POH-Werte und liefert sie als Structured Output (`output_config.format`, Server-Tool-Loop über `pause_turn`). **Bewusst die Basis-Tool-Variante `web_search_20250305` + Streaming + `max_retries=0`** (v7.4.1): das neuere `web_search_20260209` (Dynamic Filtering) ließ das Modell die Suchergebnisse in `code_execution`-Runden à 30–95 s nachbearbeiten — ein PZ04-Request lief >9 min und riss den 120-s-Client-Timeout, dessen stille SDK-Retries jeden abgebrochenen Versuch trotzdem voll bezahlten (Live-Messung 2026-07-02: 185 Web-Suchen/6,4 M Input-Tokens ≈ 14 $ in zwei Tagen; mit Basis-Tool: 16 s, ~0,07 $ pro Recherche). Rückgabe: make_model, MTOW, Leergewicht, volle Tanks als Maximum (`fuel_full_kg`) + halbe Füllung als Default (`fuel_kg`), Crew (85 kg) und die abgeleitete Zuladung `max(0, mtow−empty−fuel_halb−crew)`. Die reine Rechnung steckt in `_build_result` (testbar ohne API). Ohne `ANTHROPIC_API_KEY` (mit TSBot geteilt) oder ohne `anthropic`-Paket → `None`, der Rest bleibt manuell pflegbar. Dauer ~30 s (Web-Recherche). **Lustige KI-Sprüche (Phase 2):** `flight_quip(context)` und `event_summary(context)` — Sonnet 5 ohne Web-Search (Denken aus, effort low, ~4–8 s), Persona „Bordfunker im Friesen-Humor". Der Kontext (Vorname, Fleiß, Tempo, Umweg) kommt aus `database.flight_quip_context`/`event_summary_context` (rein, testbar).

### `app/poller.py`

`VatsimPoller` kapselt:
- **APScheduler `AsyncIOScheduler`** mit bis zu sechs aktiven Jobs: `vatsim_poll` (interval, 15s), `calendar_sync` (interval, 6h — lädt FriesenFlieger-Google-Kalender), `calendar_sync_initial` (date, einmalig beim Start), `bummel_reveal_check` (interval, 60s — ruft `update_bummel_starts` (Start-Latch + Start-Push) und `update_bummel_reveals` (Enthüllungs-Latch + Enthüllungs-Push) auf; beide Pushs nur an `notify_events`-Abonnenten via `get_push_subscriptions_for_events`), `event_reminder_check` (interval, 5min — ruft `events_due_for_reminder` auf, sendet für jedes fällige Event einmalig einen Push an `get_push_subscriptions_for_events` und latcht via `mark_event_reminded`), sowie optional `ts_poll` (interval, `TS_POLL_INTERVAL`s) wenn `TS_NOTIFY_ENABLED=true`. Der `ts_poll`-Job ist **von VAPID entkoppelt** — er läuft für die Live-Anzeige auch ohne VAPID; ohne VAPID werden lediglich keine TS-Push-Benachrichtigungen versandt. `daily_cleanup` ist deaktiviert — `position_history` wird dauerhaft behalten.
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

**Typ-Fallback ohne Flugplan** (vatsim-radar-Prinzip): der öffentliche Feed führt den Flugzeugtyp nur im `flight_plan`. Piloten ohne Plan bekommen ihr Muster aus dem **Prefile** (falls vorhanden) bzw. aus dem **zuletzt gefilten Flugplan** derselben cid (`last_known_aircraft`, Prozess-Cache `_last_type_cache`) — Anzeige und Kutter-Zuladung funktionieren damit ohne Plan. Zusätzlich stößt der Poller für **neu gesehene, ungepflegte Typcodes** automatisch die Zuladungs-Recherche an (`_auto_research_payload`, `source='llm'`, einmal je Prozess-Lebensdauer; manuell gepflegte Typen werden nie überschrieben).

**Feed-Aussetzer-Robustheit:** Fehlt ein Pilot für eine Poll-Runde im VATSIM-Feed (Feed-Glitch), greift `went_offline` → `close_flight`. Taucht er in der nächsten Runde mit **derselben `logon_time`** wieder auf, beweist das, dass die Verbindung nie abriss — `open_flight` **re-öffnet** dann die geschlossene Zeile (`logoff_time = NULL`, duration/distance/block werden beim echten Close neu berechnet), statt gegen eine geschlossene Zeile weiterzulaufen. Ohne dieses Reopen verwaisten alle Folgeflüge der Session (nur `position_history` lief weiter — Live-Test 2026-07-01, cid 1031301).

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
- `get_push_subscriptions_for_events(conn)` — Gibt alle Push-Subscriptions mit `notify_events = 1` zurück (ohne Pilot-Filter, da Event-Erinnerungen und Bummel-Benachrichtigungen pilot-unabhängig sind). Wird vom Poller für `event_reminder_check` sowie für Bummel-Start- und Enthüllungs-Push genutzt.
- `get_push_subscription_by_endpoint(conn, endpoint)` — Gibt genau **eine** Subscription anhand ihres Endpoints zurück (oder `None`). Genutzt vom Admin-Test-Push (`POST /api/admin/push/test`), um ausschließlich ans eigene Gerät zu senden.
- `get_all_push_subscriptions(conn)` — alle Subscriptions ungefiltert; genutzt vom Admin-Broadcast (`POST /api/admin/push/broadcast`, `audience = all`).
- `events_due_for_reminder(conn)` — Gibt alle Kalender-Events zurück, deren `dtstart` im Fenster `(jetzt, jetzt+60min]` liegt und für die in `event_reminders_sent` noch kein Eintrag existiert. Vergangene Events werden nicht mehr zurückgegeben.
- `mark_event_reminded(conn, uid)` — Schreibt einen Eintrag in `event_reminders_sent` (`uid` + `sent_at = now()`). `INSERT OR IGNORE` — idempotenter Latch.
- Subjekt-Privacy bleibt über `ts_consent` (`everyone`/`nobody`) in `_poll_teamspeak` vorgeschaltet.

### `app/badge.py`

Serverseitiges Badge-Rendering mit **Pillow** für Forensignaturen nach einem FriesenFliegerBummel. Beide Badges sind **rund (256 px)** mit transparenten Rändern und nutzen die FriesenFlieger-Markenhintergründe aus `app/static/badge/` (`winner_bg.png` / `medal_bg.png` — Flugzeug, ostfriesische Inselkette, Vereinsfarben aus dem Repaint-Kit). Der Text wird zentriert in die ruhigen Zonen gelegt, strikt in der FF-Palette (Navy `#191D53`, Hellblau `#8FBFF1`, Rot `#8A1B1B`, Orange `#D75F28`).

- **`render_winner_badge(d: dict)`** — Sieger-Badge „Absoluter Durchschnitt!" (helle Kuppel, dunkle Schrift) mit Callsign, Name, Flugzeugmuster, Block-Gesamtzeit und Abstand zum Schnitt; **Event-Name als Überschrift** (unter der Inselkette) und **Datum**; Fußzeile „friesenflieger.de".
- **`render_medal(d: dict)`** — Medaille „Voll daneben!" (navy Kern, helle Schrift) für alle anderen Teilnehmer (auch unvollständige), mit Flugzeugmuster, **Event-Name** und **Datum** sowie (bei kompletter Tour) dem Abstand zum Schnitt; Fußzeile „friesenflieger.de".

Beide Badges tragen jetzt **Event-Name und Datum** (zuvor hatte der Sieger-Badge kein Datum). Der Abstand zum Schnitt wird signiert + sekundengenau über `_fmt_signed_delta(sec)` formatiert (z. B. „+1:23 zum Schnitt", bei `0` „punktgenau", `None` → leer). `_badge_entry_data` (`app/main.py`) liefert dafür zusätzlich `event` (Renn-Name aus `race.name`) und `delta_sec`.

Beide Funktionen nutzen `ImageFont.load_default(size=…)` (Pillow ≥ 10) — keine gebündelten Schriftdateien, keine zusätzlichen apt-Pakete nötig. Fehlt ein Hintergrund-PNG, wird auf eine schlichte gezeichnete Scheibe zurückgefallen (Tests/lokal bleiben grün). Abhängigkeit: **`pillow>=10.0`** in `requirements.txt`.

**Badge-Endpoint (`GET /api/bummel/race/{race_id}/badge/{cid}.png` in `app/main.py`):** Prüft, ob das Rennen enthüllt ist (`revealed_at IS NOT NULL`) und ob die CID Teilnehmer ist — andernfalls `404` (kein Leak vor der Enthüllung). Rang 1 → `render_winner_badge`, alle anderen → `render_medal`.

**Cache-Strategie (ETag statt fixem max-age).** Aus den ergebnisrelevanten Feldern (`revealed_at`, Sieger-Flag, `total_min`, `delta_sec`, `aircraft`, `callsign`, `event`) wird ein MD5-Hash (`key`) gebildet, der zweierlei dient: (a) als Datei-Cache-Schlüssel — das PNG liegt unter `data/badges/<race_id>_<cid>_<key>.png` — und (b) als `ETag`. Antwort-Header sind jetzt **`Cache-Control: no-cache` + `ETag`** (vorher `Cache-Control: public, max-age=86400`). Schickt der Client ein passendes `If-None-Match`, antwortet der Server mit `304 Not Modified` (kein erneuter Download). Ändert sich der Sieger (z. B. durch Admin-Override oder Wertungsänderung), ändert sich der Hash → ETag → Browser/Forum holen sofort ein frisches Bild statt eines bis zu einen Tag veralteten. Das behebt den Bug, dass ein alter Gewinner-Badge nach einer Wertungsänderung hängenblieb. `Content-Type: image/png`.

### `app/alerts.py`

Telegram-Alert beim "Online gehen" eines Piloten. Alle VATSIM-Felder werden mit `html.escape()` sanitized bevor sie in den `parse_mode=HTML` Telegram-Body eingebettet werden. Fehler werden nur als `type(e).__name__` geloggt (kein Full-Exception-String, der den Token in der Telegram-API-URL exponieren würde).

### `app/main.py`

FastAPI mit `lifespan`-Kontext-Manager (startup: DB init + Poller start; shutdown: Poller stop).

Endpoints: `/api/live`, `/api/prefiles`, `/api/stats`, `/api/stats/activity`, `/api/pilots/{cid}/flights`, `/api/pilots/{cid}/live-track`, `/api/flights/{id}/track`, `/api/flights/statsim/{id}/track`, `/api/events`, `/api/calendar/events`, `/api/bummel/races`, `/api/bummel/race/{id}`, `/api/bummel/active`, `/api/bummel/race/{race_id}/badge/{cid}.png` (Badge-PNG via `app/badge.py`, Reveal-Gating + `data/badges/`-Cache), `/admin` (statische `admin.html`), `/api/admin/login`, `/api/admin/logout`, `/api/admin/me`, `/api/admin/bummel/races` (GET/POST + Unterrouten für einzelne Rennen inkl. reveal/hide/push/override/preview — alle via `require_admin`-Dependency geschützt), `/api/admin/bummel/races/{race_id}/badge/{cid}.png` (Badge-Vorschau ohne Reveal-Gate), `/api/admin/banner` (GET/POST), `/api/admin/push/test`, `/api/admin/push/broadcast`, `/api/admin/pilots` (GET/POST), `/api/admin/pilots/{cid}` (DELETE), `/widget`, `/api/sse`.

**Hinweis-Banner-Mechanik:** `_resolve_banner_version(selected)` löst die in `app_settings['banner_version']` gespeicherte Admin-Auswahl auf eine konkrete Changelog-Version (oder `None` = kein Banner) auf: `off` → `None`, eine konkrete Version → diese (falls in `CHANGELOG` vorhanden, sonst `None`), `auto`/leer → neuester Eintrag mit `highlight: true` (Fallback: neuester Eintrag). `GET /api/frontend-config` liefert das Ergebnis im Feld `banner_version`. `GET /api/admin/banner` gibt die aktuelle Auswahl + alle Changelog-Einträge (`version`, `date`, `title`, `highlight`) zurück; `POST /api/admin/banner` schreibt die Auswahl via `set_app_setting`.

**Neue Admin-Endpoints (alle `require_admin`):**
- `GET /api/admin/bummel/races/{race_id}/badge/{cid}.png` — Badge-Vorschau eines Teilnehmers ohne Reveal-Gate (`_build_race_view(..., force_reveal=True)` + `_badge_entry_data`/`_render_badge`); immer frisch gerendert, `Cache-Control: no-store`. `404` wenn Rennen/Teilnehmer fehlt.
- `POST /api/admin/push/test` — sendet eine Test-Notification über `send_web_push` nur an die per `endpoint` adressierte Subscription (`get_push_subscription_by_endpoint`). Unbekannter Endpoint → `404`, kein VAPID → `400`.
- `POST /api/admin/push/broadcast` — freie Nachricht (`title`, `body`) an `audience = all` (`get_all_push_subscriptions`) oder `events` (`get_push_subscriptions_for_events`); Antwort enthält `sent` (Empfängerzahl).
- `GET/POST /api/admin/pilots` + `DELETE /api/admin/pilots/{cid}` — Piloten-Verwaltung über `list_pilots`/`upsert_pilot`/`delete_pilot`.

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

**URL Deep-Linking** via `location.hash` (URLSearchParams): Tab, Pilot-CID, Zeitraum (days=), Track-ID/Source, Callsign (fp=), Events-Filter (icao/radius/start/end), Flugdetail-Modal (`fld=<logon_time>`), **Bummel-Rennen (`bummel=<race_id>`)** werden im Hash gespeichert → Seite neu laden öffnet den gleichen Zustand. `openFlightDetailModal()` schreibt `fld=logon_time` in den Hash; `closeFldModal()` entfernt es. `openBummel()` schreibt `tab=events&bummel=<race_id>` (Deep-Link auf ein konkretes Rennen); der „⎘ Teilen"-Button oben rechts im Bummel-Panel-Header nutzt denselben `copyShareUrl()` wie alle anderen Views (Clipboard-Copy von `location.href`). `initFromUrl()` wird beim Seitenstart nach `fetchLiveInitial()` ausgeführt; beim `bummel=`-Param lädt es `/api/bummel/races`, findet das Rennen per `id` und ruft `openBummel()` (über den `_raceId`-Pfad) auf; re-aktiviert den korrekten Tab am Ende aller Async-Operationen (Race-Condition-Schutz).

**Karten-Layer**: OpenFlightMap (OFM) als Standard auf allen Leaflet-Instanzen (Live/Karte, Track-Modal, Events). Fünf Basislayer via `L.control.layers()`: OFM (native Tiles Zoom 6–11, `minZoom:6`), OpenTopoMap (OSM+SRTM, Zoom bis 17), Satellit (ESRI World Imagery), Light (CartoDB Positron), Dark (CartoDB Dark Matter). **OpenAIP-Overlay**: Checkbox für Luftraum/Flugplätze/Navaids — wird nur angezeigt wenn `OPENAIP_API_KEY` gesetzt; Key wird via `/api/frontend-config` an das Frontend übergeben und per `_makeAIPOverlay()` als separater Tile-Layer eingebunden. **Auto-Switch** (`_setupOFMAutoSwitch`): Solange OFM aktiv ist, wechselt die Karte bei Zoom < 7 oder Zoom > 12 automatisch auf Satellit und zurück im OFM-Bereich (Zoom 7–12). Manueller Wechsel zu einem Nicht-OFM-Layer deaktiviert den Auto-Switch; manuell zurück zu OFM reaktiviert ihn. `initLiveMap()`, `renderEventsMap()` und der Track-Modal-Init awaiten `_configPromise` (den `/api/frontend-config`-Fetch) um Race Conditions beim OpenAIP-Key-Laden zu vermeiden.

**Web Push Notifications**: Bell-Icon 🔔 im Header — sichtbar wenn `VAPID_PUBLIC_KEY` gesetzt. Klick öffnet Panel mit Toggle + Pilot-Filter. `_registerServiceWorker()` registriert `sw.js` und lädt bestehende Push-Subscription. `_subscribePush()` fragt Notification-Erlaubnis, abonniert via `pushManager.subscribe()` und postet Subscription an `/api/push/subscribe`. Service Worker (`app/static/sw.js`) empfängt `push`-Events und zeigt Notifications im Hintergrund — auch bei geschlossenem Browser. **PWA-Installation**: Web-App-Manifest (`app/static/manifest.webmanifest`, via `<link rel="manifest">`; MIME `application/manifest+json` in `main.py` registriert) + Icons (`icon-192/512`, `icon-maskable-512`, `apple-touch-icon`, erzeugt mit `generate_icons.py`) machen die SPA installierbar. Ein sichtbarer, schließbarer **Install-Banner** (`#install-banner`, oberhalb der Tab-Nav) weist darauf hin: `_maybeShowInstallBanner()` zeigt ihn nur, wenn nicht bereits `display-mode: standalone` und nicht in `localStorage` (`fs_install_dismissed`) weggeklickt. Auf Android/Desktop feuert `beforeinstallprompt` → Button öffnet den nativen Dialog (`prompt()`); auf iOS-Safari zeigt der Banner die manuelle Anleitung ("Teilen ⬆ → Zum Home-Bildschirm"). `appinstalled` blendet den Banner aus. Der alte "Als App installieren"-Button im Push-Panel bleibt zusätzlich erhalten. Pilot-Filter (Alle / bestimmte CIDs) wird serverseitig in `push_subscriptions.pilot_filter` (JSON) gespeichert. **Pilot-Filter-UX**: Bei "Alle Friesen" sind alle Checkboxen checked + disabled (visuell ausgegraut, nicht änderbar). Bei "Nur bestimmte Piloten" werden Checkboxen aktiviert; beim Umschalten von "select" → "all" wird der aktuelle Zustand in `_notifCustomFilter` (in-memory) gemerkt, sodass bei erneutem Wechsel zurück der Stand erhalten bleibt — auch ohne Speichern. Beim ersten Öffnen wird der gespeicherte Filter aus `localStorage` geladen und der Radio-Modus entsprechend wiederhergestellt. **„Push zurücksetzen"**: deabonniert, deregistriert alle SW-Registrierungen und lädt neu — erzwingt frischen FCM/APNs/WNS-Token (nötig bei `permanently-removed.invalid`-Endpoints). **Endpoint-Validierung**: `/api/push/subscribe` lehnt `permanently-removed.invalid`-Endpoints mit HTTP 400 ab. **VAPID-Keys**: `VAPID_PRIVATE_KEY` muss als raw base64url-kodierter EC-Skalar (32 Byte, 43 Zeichen, kein PEM) in config.env stehen — generiert mit `generate_vapid.py`. pywebpush mutiert das `claims`-Dict in-place (fügt `aud`/`exp` hinzu) → pro Push ein frisches Dict erstellen. WNS erfordert `ttl=3600` (TTL=0 wird von WNS abgelehnt). Bei transientem Fehler (z.B. APNs 4xx) wird einmal nach 5 Sekunden wiederholt.

**Versionierung & Changelog**: Single Source of Truth ist die Repo-Datei `app/CHANGELOG.json`
(neueste Version zuerst; je Eintrag `version`, `date`, `title`, `items`). `app/version.py` liest
sie ein und stellt `VERSION` (= `CHANGELOG[0].version`) und `CHANGELOG` bereit; `/api/frontend-config`
liefert beides ans Frontend. Im Header zeigt `#app-version` die kleine Versionsnummer (Klick →
Versionsverlauf-Modal `#changelog-modal`, wiederverwendet die `.fp-modal-*`-Klassen). `#changelog-banner`
(Basis-Styling vom Install-Banner) zeigt die Neuerungen **einmal pro Version**. Welcher Eintrag
Banner ist, bestimmt jetzt der **Server**: `_initVersionUI(cfg.version, cfg.changelog, cfg.banner_version)`
reicht das Feld `banner_version` aus `/api/frontend-config` an `_maybeShowChangelogBanner()` weiter — ist
es `null`, erscheint **kein** Banner; sonst der Eintrag dieser Version. Das Seen-Gating pro App-Version
bleibt: das Banner erscheint nur, wenn `localStorage['fs_changelog_seen'] !== version`; ✕ oder das Öffnen
des Verlaufs setzt den Key auf die aktuelle Version. Die Banner-Auswahl (`auto`/`off`/Version) steuert der
Admin über `/api/admin/banner`. **Release-Workflow:** bei signifikanten Änderungen einen neuen Eintrag oben
in `app/CHANGELOG.json` einfügen — mit `highlight: true` erscheint er bei `banner_version = auto` automatisch
als Banner bei allen Nutzern.

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
    uid       TEXT PRIMARY KEY,
    summary   TEXT,
    dtstart   TEXT,
    dtend     TEXT,
    location  TEXT,
    route     TEXT,        -- CSV aller ICAOs der Strecke (FriesenFliegerBummel)
    is_bummel INTEGER DEFAULT 0
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
    notify_events  INTEGER DEFAULT 0,   -- 1 = Event-Erinnerungen + Bummel-Start/Ergebnis-Push
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

-- Persistente FriesenFliegerBummel-Rennen (vom Poller beim Kalender-Sync oder Admin manuell angelegt)
CREATE TABLE bummel_races (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    route        TEXT NOT NULL,          -- CSV der Strecken-ICAOs, z. B. "EDWF,EDWG,EDWR"
    dtstart      TEXT NOT NULL,          -- ISO8601 UTC — Termin-Beginn aus dem Kalender
    dtend        TEXT NOT NULL,          -- ISO8601 UTC — effektiver Renn-Endtermin:
                                         --   aus Kalender übernommen; fehlt dtend im Termin
                                         --   → Mitternacht UTC des Folgetags (_effective_dtend)
    radius_km    REAL DEFAULT 10.0,      -- Anwesenheitsradius je Streckenflugplatz
    source       TEXT DEFAULT 'calendar', -- 'calendar' | 'manual'
    calendar_uid TEXT UNIQUE,            -- UID aus calendar_events (NULL für manuelle Einträge)
    revealed_at  TEXT DEFAULT NULL,      -- NULL = Ergebnisse noch verborgen;
                                         -- Zeitstempel = Enthüllungs-Latch (einmal gesetzt, nie zurückgesetzt)
    started_at   TEXT DEFAULT NULL,      -- NULL = noch kein Start;
                                         -- Zeitstempel = Start-Latch (erster Pilot mit Blockzeit, nie zurückgesetzt)
    push_enabled INTEGER DEFAULT 1,      -- 1 = Start- und Enthüllungs-Push aktiv; 0 = deaktiviert
    reveal_suppressed INTEGER DEFAULT 0, -- 1 = manuell verborgen, übersteuert den Auto-Reveal
    created_at   TEXT NOT NULL
);

-- Admin-Korrekturen pro Rennen + Pilot (PK race_id + cid)
CREATE TABLE bummel_overrides (
    race_id          INTEGER NOT NULL REFERENCES bummel_races(id) ON DELETE CASCADE,
    cid              INTEGER NOT NULL,
    action           TEXT NOT NULL,      -- exclude | disqualify | winner | manual
    manual_total_min INTEGER DEFAULT NULL, -- Manuelle Block-Zeit in Minuten (nur bei action = 'manual')
    note             TEXT,               -- Optionale interne Notiz
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (race_id, cid)
);

-- Event-Erinnerungen (Latch: einmal gesendet, nie erneut)
CREATE TABLE event_reminders_sent (
    uid      TEXT PRIMARY KEY,   -- Kalender-Event-UID (aus calendar_events.uid)
    sent_at  TEXT NOT NULL       -- ISO8601 UTC
);

-- Generischer Key-Value-Store (App-Einstellungen, z. B. banner_version)
CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
```
