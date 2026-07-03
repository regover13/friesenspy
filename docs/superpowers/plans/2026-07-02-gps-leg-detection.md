# #23 — GPS-only Flug-/Leg-Erkennung (eine Wahrheit für Statistik, Bummel, Kutter)

> Konsolidierter Umsetzungsplan (Plan-Modus). Ist-Zustand + Szene-Recherche + Design vom
> Plan-Agenten verifiziert. Alle Nutzer-Entscheidungen eingearbeitet. Bereit für Freigabe.

## Kontext / Problem

Flüge/Ankünfte werden in manchen Wertungen erst gezählt, wenn der Pilot vom Netzwerk **trennt**
(logoff), und Etappen werden nur beim **Refile** (Flugplan-Abflugwechsel) getrennt. Beides ist
fragil: „Frode" verschwand aus der Test-Bummel-Wertung, weil sein Flug noch offen war; und eine
Zwischenlandung **ohne** Refile erzeugt heute keine eigene Etappe. Ziel: Flüge/Etappen **rein aus
GPS** erkennen (Landung = am Boden am Flugplatz), zentral für **Statistik, Bummel UND Kutter**.
Der Flugplan wird reines Beiwerk (Anzeige-Labels + Route/Remarks); Typecodes sind bereits
flugplan-frei (#11).

## Verifizierter Ist-Zustand (Datei:Zeile)

**Positions-Infrastruktur:** Poll alle 15 s (`VATSIM_POLL_INTERVAL`, config.py:17). `position_history`
(append-only) DDL database.py:86-96: `latitude, longitude, altitude(ft MSL), groundspeed(kt),
heading, ts`; Index `(cid, ts)` → Range-Scan je Pilot billig. **Kein `on_ground`-Feld** vom Feed.
`airportsdata` liefert `elevation` (ft) je Platz → AGL = `altitude − elevation` verfügbar.

**Geo (geo.py):** `haversine` (21-51), `icao_to_coords` (54-74), `nearest_airport_icao` (186-203,
28k-Linearscan mit bbox-Vorfilter — nicht für Poll-Takt), `segment_into_flights` (146, Gap-Split).
Schnell: `_nearest_airport(coords_map,…)` database.py:1718. `_first_pos`/`_last_pos` db:1392/1404.
Schwellen: `_BLOCK_GS_KT=2` (db:777), `_LANDED_MAX_GS_KT=40`, `_FLOWN_MIN_GS_KT=60` (db:1388/89) —
**bestehende** Konstanten; unser Detektor nutzt fürs Abheben **AGL primär + gs>50 sekundär**, NICHT die 60.

**Zentraler Flaschenhals — die gemeinsame Funktion existiert schon:** `canonicalize_flights`
(db:1580, Filter `superseded_by IS NULL, logoff_time IS NOT NULL`) ist „die EINZIGE Wahrheit". **5
Konsumenten** nutzen sie: `get_stats` (db:1262), `get_stats_activity` (1317), /api/pilots/{cid}/flights
(main:598), `compute_bummel_standings` (1870), `compute_transport_progress` (3133). Sie liest
gespeicherte Spalten `duration_min/distance_nm/block_min` (nur von `close_flight` db:723-755 gefüllt).

**Schlüssel-Einsicht (macht es einfacher):** Die Konsumenten korrigieren `dep`/`arr` **heute schon**
per GPS je flights-Zeile (Bummel `_nearest_route_airport(_first_pos/_last_pos)` db:1949-50; Transport
analog). Was ihnen fehlt: eine Verbindung **ohne Refile in mehrere Etappen** zerlegen. Der einzige
Leg-Splitter heute ist der Refile-Split (poller.py:768-794, hängt am Flugplan). **Genau die
Intra-Connection-Zwischenlandung ist der ganze Mehrwert — nicht die dep/arr-Korrektur (existiert).**

**State-Machine (poller.py):** `newly_online = current_cids − active_cids` (570); Flüge nur für
`newly_online` geöffnet (597/605). Startup-Rehydration offener Flüge (380-390); Offline→`close_flight`
(568-572, 813-831). `close_stale_flights` (8 h) nur bei init_db (db:627/440). Kutter-Latch
`transport_live_arrivals` (cid, logon_time, event_id) db:219; `check_live_arrival` db:3048, Poll
poller.py:808 mit `leg_logon = _active_flights[cid]["logon_time"]` (807).

**StatSim:** `canonicalize_flights` mischt FriesenSpy + StatSim (source-Feld); Backfill bei neuem Piloten.

**Zombie/close_stale (geklärt):** Downtime-Disconnect wird bereits sauber behandelt (Rehydration +
nächster-Poll-Close). `close_stale_flights` bleibt schlanker Notnagel — **kein Job nötig**.

## Szene-Recherche (Web) — bestätigt den Weg

VATSIM-Feed hat **kein** on-ground-Flag (vatsim.dev). **VATSIM Radar** (aktivstes Open-Source-Tool)
macht exakt GPS-only Phase-Detection: State-Machine bis `arrGate`, setzt Ankunft live bei
Groundspeed < Schwelle + Umkreis um Platz, **ohne** Flugplan-Abhängigkeit — **direkte Blaupause**.
15 s Poll ist korrekt: Feed **regeneriert alle 15 s** (vatsim.dev „Re-generates every 15 seconds"),
**kein** Rate-Limit dokumentiert, altes `reload`-Feld (Minuten) ist **deprecated**. `VATSIM_POLL_INTERVAL=15`
bleibt — nicht verlängern (macht Live-Ankunft nur träger), nicht verkürzen (sinnlos).

## Design-Entscheidungen (Nutzer, 2026-07-02)

1. **Voll GPS-only:** Legs aus GPS-Landung/-Start; Flugplan nur Anzeige/Route. Kein Refile/Disconnect.
2. **Landung nur an einem Platz, `< 2 kt`:** Touch-and-Go/Go-around zählt nicht (bleibt schnell).
   **Außenlandung/Absturz abseits eines Platzes wird NICHT als Landung/Ankunft gewertet** (per GPS
   nicht von einem Absturz unterscheidbar) — lieber eine echte Feldlandung verpassen als einen Absturz
   als Ankunft zählen.
3. **Platzrunde X→X ist ein Flug:** Echtheit = „war abgehoben" (**AGL-Anstieg > 500 ft primär**,
   gs>50 nur sekundär — NICHT 60), NICHT Luftlinie.
   „Eine Session = ein Flug": Vollstopp mit erneutem Abheben binnen `_GPS_ARRIVAL_DWELL` (180 s) =
   dieselbe Session/ein Leg (A→B→C an verschiedenen Plätzen bleibt 3 Legs).
4. **close_stale_flights bleibt** wie es ist. **15 s Poll bleibt.**
5. **Schatten zuerst:** erst parallel erfassen (null Live-Risiko) + Audit-Vergleich, dann aktivieren.

## Design — GPS-Leg-Detektor (Plan-Agent verifiziert)

Drei Bausteine, „alles über eine Funktion":

**(A) `detect_gps_legs(positions, *, nearest_airport, airport_elev_ft, radius_km=10, gap_minutes=30)`**
— REINE Funktion über eine ts-sortierte Positionsliste je cid (vorsegmentiert nach Zeitlücken).
Zustände `ON_GROUND → AIRBORNE → LANDED` (→ zurück ON_GROUND für Folge-Leg):
- **Airborne/Takeoff (HÖHEN-zentriert — Pflicht für STOL/Heli):** Leitsignal ist der **AGL-Anstieg**
  über `_GPS_AIR_AGL_FT (500)` gegenüber dem Boden-Ausgangspunkt. Groundspeed nur **sekundärer Helfer**
  (`_GPS_FLYING_GS_KT=50`, NICHT 60). Grund: eine Wilga fliegt mit ~40 kt (bei Gegenwind noch weniger
  Groundspeed) und „Taxi < 40 kt" vs. „Slow-Flight ~40 kt" sind per gs NICHT trennbar — nur die Höhe
  trennt sie. So wird auch ein langsamer STOL/Heli-Start erkannt. `dep_icao` = nächster Platz am
  letzten Stand-Cluster (`NULL` bei Spawn-in-der-Luft **oder** Start ab Außenlandeplatz).
- **Landung (NUR an einem Platz):** gs `< 2 kt` UND AGL `< _GPS_GROUND_AGL_FT (300)` UND **im 10-km-
  Umkreis eines DB-Platzes** = Landung erkannt (Zeitpunkt = erstes <2-kt-Sample). **Endgültig**, wenn
  danach für `_GPS_ARRIVAL_DWELL (180 s)` NICHT wieder abgehoben wird (Rollen 2–30 kt zählt NICHT, nur
  echtes Steigen). Hebt er im Fenster wieder ab → Stop-and-Go, gleiche Session (kein neuer Leg). Nur bei
  endgültiger Ankunft `arr_icao` gesetzt, `complete=1`.
  **KEIN Platz im Umkreis → KEINE Landung** — gs→0 abseits eines Platzes ist nicht unterscheidbar von
  **Absturz**/Pause/Slew; eine Außenlandung wird bewusst NICHT als Ankunft gewertet (Wettbewerb!).
  Der Leg bleibt dann offen bis zu einer echten Platz-Landung ODER Disconnect (→ `complete=0`, arr=NULL).
- **Platzrunde/Stop-and-Go** ergibt sich direkt aus dem Ankunfts-Fenster: Vollstopp mit erneutem
  Abheben binnen `_GPS_ARRIVAL_DWELL` = derselbe Leg (Session = 1 Flug); A→B→C (verschiedene Plätze) = N Legs.
- Neue Konstanten: `_GPS_FLYING_GS_KT=50` (Helfer, sekundär), `_GPS_GROUND_AGL_FT=300`,
  `_GPS_AIR_AGL_FT=500`, `_GPS_ARRIVAL_DWELL=180 s` (Ankunft endgültig, wenn kein erneutes Abheben).
  **Höhe (AGL) ist das Leitsignal**, Groundspeed sekundär — STOL/Heli-robust. Wiederverwendet:
  `_BLOCK_GS_KT`, `_BUMMEL_AIRPORT_RADIUS_KM`.

Edge Cases: Spawn-in-Luft (`dep=NULL`), Ghost/nie abgehoben (**kein Leg** — ersetzt Ghost-Filter
strukturell), Touch-and-Go/Go-around (nie <2 → keine Landung), **Außenlandung/Absturz** (kein Platz
im Umkreis → **KEINE Landung**; nicht von Absturz trennbar → nie als Ankunft; Leg bleibt incomplete
bis Platz-Landung/Disconnect), **Heli-Hover** (kurz <2 kt in der Luft → Dwell/AGL-Guard verhindert Fehl-Landung),
**langsamer STOL** (AGL-Leitsignal statt gs → nicht als Ghost verworfen), Stall/Hold (AGL-Guard),
Disconnect mid-air (`complete=0`, unvollständig, nicht verwerfen), Zwischenlandung ohne Refile
(N Legs = Kern), Plätze dicht (nearest = min-Distanz), Track-Lücke >30 min (Split).

**(B) Tabelle `gps_legs`** (id, cid, callsign, dep_icao, arr_icao, takeoff_ts, landing_ts, complete,
dep_source, arr_source, distance_nm, block_sec, duration_min, max_altitude, connection_logon,
computed_at; `UNIQUE(cid, takeoff_ts)`). Idempotent: abgeschlossene Legs immutable, nur offener Tail
neu (`DELETE WHERE cid=? AND takeoff_ts >= letztes landing_ts` + Neu-INSERT). `connection_logon`
verknüpft mit der flights-Connection (Label-Reconcile + Kutter-Latch). Wrapper `recompute_gps_legs(conn, cid, since=None)`.

**(C) Adapter `canonicalize_legs(conn, *, cids, start, end)`** — liefert **identische Dict-Form** wie
`canonicalize_flights`, gespeist aus `gps_legs`: `departure=dep_icao` (Fallback Flugplan), `arrival=arr_icao`,
`logon_time=takeoff_ts`, `logoff_time=landing_ts`, `block_min=block_sec//60`; `route/remarks/callsign/
aircraft` vom überlappenden flights-Row geerbt (Flugplan = nur Label). → **Alle 5 Konsumenten
unverändert.** Bummel `_block_seconds(conn, cid, takeoff_ts, landing_ts)` signaturgleich pro Leg-Fenster.

**Perf:** `nearest_airport` nur an Boden-Ereignissen (selten). Neuer Grad-Grid-Bucket-Index in geo.py
(`nearest_airport_icao_fast`) statt 28k-Linearscan. Phase 1 on-demand (kein Poll-Impact).

## Warum das EINFACHER wird (Nutzer-Punkt bestätigt)

Endzustand hat **weniger** bewegliche Teile als heute: die gemeinsame Funktion bleibt
`canonicalize_flights` (Quelle getauscht auf `canonicalize_legs`, identische Dict-Form → Konsumenten
unverändert). **Wegfall/Verschmelzung:** Refile-Leg-Split (poller.py:768-794), die je Konsument
verstreute GPS-dep/arr-Korrektur, `_BLOCK_STAND_MIN_SEC`-Heuristik (Leg-Fenster macht sie überflüssig),
Disconnect-Abhängigkeit. Eine reine Funktion `detect_gps_legs` = eine Wahrheit. Der Schatten-Modus ist
temporäre Parallelität (bewusst, Nutzer-Wunsch), kein bleibender Ballast.

═══════════════════════════════════════════════════════════════════════════
# Umsetzungsplan

> **Für agentische Worker:** SUB-SKILL superpowers:subagent-driven-development, TDD, häufige Commits.

**Tech Stack:** Python 3.11, SQLite (WAL), APScheduler, pytest, airportsdata. stdlib-Muster wie bestehend.

## Global Constraints
- Landung NUR an einem DB-Platz (`< 2 kt` + AGL-Guard + 10 km Umkreis). Kein Platz → KEINE Landung
  (Absturz/Außenlandung nie als Ankunft werten). Touch-and-Go zählt NICHT.
- Airborne/Echtheit HÖHEN-zentriert (AGL-Anstieg > 500 ft), Groundspeed nur sekundär (`_GPS_FLYING_GS_KT=50`;
  STOL/Heli fliegen langsam) — NIE Punkt-zu-Punkt-Distanz (Platzrunde X→X!).
- Phase 1 fasst Live-Pfad/`flights`/State-Machine NICHT an (rein additiv, on-demand).
- `canonicalize_legs` MUSS dieselbe Dict-Form wie `canonicalize_flights` liefern (Konsumenten unverändert).
- StatSim-Zweig erhalten. Kutter-Latch-Key `(cid, logon_time)` → auf `connection_logon` mappen.
- UI-Regeln (Blau nur klickbar; breite Tabellen `.table-scroll`/`.table-wrap` scrollbar) falls UI dazukommt.
- Release je Phase: Version hoch + Git-Tag + Auto-Banner (Minor); Docs (README, docs/api.md,
  docs/architecture.md) mitpflegen; Deploy Push→main→Actions→GHCR→SSH + Health-Check.

═══════════════════════════════════════════════════════════
## PHASE 1 — v7.9.0: Schatten-Erfassung + Audit (NULL Wertungsänderung)
═══════════════════════════════════════════════════════════
Rein additiv. Nichts an Statistik/Bummel/Kutter ändert sich — GPS-Legs werden nur erfasst und im
Admin-Audit gegen die heutigen Refile-flights verglichen.

### Task 1: Reine Funktion `detect_gps_legs` + Airport-Grid-Index
**Files:** Modify `app/geo.py` (Grid-Index + `nearest_airport_icao_fast` + Elevation-Zugriff);
Create `app/gps_legs.py` (oder in database.py) für `detect_gps_legs`; Test `tests/test_gps_legs.py` (neu),
`tests/test_geo.py`.
- Zustandsmaschine wie Design (A). Rein, DB-frei, `nearest_airport`/`airport_elev_ft` injizierbar.
- TDD mit **synthetischen Tracks je Edge-Case:** Normal A→B, 2-Leg A→B→C (Zwischenlandung ohne Refile),
  Platzrunde X→X mit Touch-and-Goes, Stop-and-Go-Merge (mehrere X→X → 1 Leg), Go-around, Spawn-in-Luft,
  Ghost (nie airborne → keine Legs), Stall/Hold (AGL-Guard), Disconnect mid-air (complete=0), Plätze dicht.
- Grid-Index: Tests gegen bekannte Koordinaten/Radien; identische Ergebnisse wie `nearest_airport_icao`.

### Task 2: Tabelle `gps_legs` + `recompute_gps_legs`
**Files:** Modify `app/database.py` (DDL + Migration + Wrapper); Test `tests/test_database.py`.
- DDL wie Design (B), Migrationsliste analog `transport_live_arrivals`. `recompute_gps_legs(conn, cid, since)`
  ruft `detect_gps_legs` über `position_history` und schreibt idempotent.
- TDD: zweimal rechnen → identische Zeilen (Idempotenz); offener Tail mutiert, alte Legs immutable.

### Task 3: Read-only Audit `audit_gps_vs_refile` + Admin-Route
**Files:** Modify `app/database.py` (Audit-Query), `app/main.py` (`GET /api/admin/gps-leg-audit`,
require_admin); Test `tests/test_admin_api.py`.
- Ordnet je `canonicalize_flights`-Flug die überlappenden `gps_legs` zu: `matches`, `extra_gps_legs`
  (Intra-Connection-Zwischenlandungen), `missing_gps_legs` (Track fehlt/Detektor-Miss), `arr_divergence`,
  `incomplete_rate`, `airborne_spawn_rate`. Rein lesend.
- TDD: Fixtures (mit/ohne Leg, am/nicht am Ziel) → korrekte Kennzahlen; 401 ohne Admin.

### Task 4 (Phase 1): Docs/Changelog/Version/Tag/Deploy — Schatten
- Changelog **v7.9.0** (Minor, kein highlight): „GPS-Leg-Erkennung im Schatten erfasst + Admin-Audit
  (noch ohne Wertungswirkung)". Docs: Detektor, `gps_legs`, Audit-Endpoint.
- `pytest tests/ -v` grün → Push main → `gh run watch <id> --exit-status --interval 20` → Prod-Health
  `curl .../api/frontend-config` == 7.9.0 → Tag `v7.9.0`.

**⏸ GATE:** Detektor läuft mit (on-demand, kein Poll-Impact). **Nutzer sichtet das Audit** über echte
Flüge/einen Bummel; Schwellen ggf. justieren. Erst dann Freigabe für Phase 2.

═══════════════════════════════════════════════════════════
## PHASE 2 — v7.10.0: Aktivierung (Konsumenten lesen GPS-Legs)
═══════════════════════════════════════════════════════════
Erst NACH Audit-Freigabe.

### Task 5: Adapter `canonicalize_legs` (formgleich)
**Files:** Modify `app/database.py`; Test `tests/test_database.py`.
- Dict-Form-Parität mit `canonicalize_flights`; Label-Reconcile via `connection_logon`; Leg-Splitting.
- **StatSim-Sicherheitsnetz (PFLICHT):** `canonicalize_legs` MUSS StatSim-Flüge enthalten, auch wenn
  (noch) kein StatSim-Leg existiert — dann über die bestehende Flugplan-/`duration_min`-Zeile
  (`source=statsim`), genau wie heute `canonicalize_flights`. So verschwindet NIE ein StatSim-Flug,
  unabhängig davon, ob Task 5b schon greift. (Wenn ein StatSim-Leg existiert, hat es Vorrang.)
- TDD: Feld-für-Feld-Parität + Leg-Splitting (A→B→C = 3, Platzrunde = 1); StatSim-ohne-Leg bleibt gelistet.

### Task 5b: StatSim-Legs — Detektor auch über `statsim_position_history`
**Kontext/Befund (2026-07-03, verifiziert):** StatSim-Flüge haben dichte GPS-Tracks
(`statsim_position_history`, gleiche Spalten wie `position_history`: lat/lon/altitude/groundspeed/
heading/ts, ~15–26 s Abstand). `detect_gps_legs` läuft darauf UNVERÄNDERT korrekt (Stichprobe 5/5
Legs trafen den Flugplan). StatSim bekommt heute nur deshalb keine Legs, weil `recompute_gps_legs`
ausschließlich `position_history` je `cid` liest — reine Detektor-Reichweite, kein Datenmangel. Ohne
diese Erweiterung fehlten bei der Aktivierung ~1418 StatSim-Flüge (89 % der Historie) in den GPS-Legs.
**Files:** Modify `app/database.py` (`recompute_gps_legs` Quelle erweitern bzw. Geschwister
`recompute_gps_legs_statsim(conn, statsim_id)`; `gps_legs`-Schema um StatSim-Bezug; Migration);
Test `tests/test_database.py`.
- `detect_gps_legs` bleibt **unverändert** (reine Funktion). Nur die Datenbeschaffung liest
  `statsim_position_history` je `statsim_id` statt `position_history` je `cid`.
- Ablage: `gps_legs` braucht einen StatSim-Schlüssel. Im Task entscheiden: (a) neue Spalte
  `statsim_id` (NULL für FriesenSpy) + `UNIQUE(statsim_id, takeoff_ts)`; oder (b) `source`-Kennung.
  `callsign`/Label aus `statsim_cache`.
- **Kein Doppelzählen:** ein Flug ist entweder FriesenSpy- ODER StatSim-Quelle — die bestehende
  `_dedup_statsim_against_fs`-Logik respektieren; StatSim-Legs nur für Flüge, die nicht schon
  FriesenSpy-getrackt sind (FriesenSpy hat Vorrang).
- Idempotent wie FriesenSpy (DELETE ab Grenze + INSERT OR REPLACE).
- TDD: echter/synthetischer StatSim-Track → korrekte Legs (inkl. Zwischenlandung); Idempotenz;
  deduplizierter Fall (kein Doppel-Leg, wenn FriesenSpy denselben Flug trackt).

### Task 6: Konsumenten schrittweise umstellen (je Vorher/Nachher-Zahlvergleich)
**Files:** Modify `app/database.py` (get_stats, get_stats_activity, compute_bummel_standings,
compute_transport_progress), `app/main.py`; Tests `tests/test_database.py`, `test_bummel.py`,
`test_transport.py`, `test_admin_api.py`.
- Reihenfolge Statistik → Piloten-Detail → Bummel → Kutter. Bummel-E2E „Frode": landet am Ziel,
  bleibt verbunden → erscheint mit korrekter Blockzeit (Leg-Fenster), OHNE Disconnect.
- Kutter-Latch `(cid, logon_time)` → `connection_logon`-Reconcile; keine Doppelzählung von Refile-µs-Fragmenten.

### Task 7 (optional, nach Zahlvergleich): Cleanup
- Refile-Split (768-794), verstreute dep/arr-Korrektur, `_BLOCK_STAND_MIN_SEC` entfernen → `flights` =
  1 Zeile/Connection (Live-/Latch-Layer), `gps_legs` = kanonischer Etappen-Layer. **Tiefe wird nach
  Phase-1-Audit entschieden** (voll aufräumen vs. Fallback behalten).

### Task 8: Docs/Changelog v7.10.0 + Tag + Deploy
- Changelog **v7.10.0**: „GPS-Leg-Erkennung aktiv — Etappen aus GPS-Landungen (Statistik, Bummel, Kutter)".
  Docs; Deploy wie Phase 1; Prod == 7.10.0; Tag `v7.10.0`.

## Verifikation
1. `pytest tests/ -v` je Phase grün.
2. Phase 1: Audit zeigt plausible GPS-Legs (hohe Trefferquote, sinnvolle extra/missing); Wertungen
   unverändert ggü. vor dem Release.
3. Phase 2: „gelandet, verbunden" → Pilot in Statistik/Piloten/Bummel/Kutter konsistent; A→B→C = 3
   Etappen; Platzrunde = 1 Flug; Prod 7.10.0.

## Nach Freigabe
subagent-driven-development: pro Task frischer Implementer (Sonnet; reine Funktion Task 1 ggf. Haiku)
+ Task-Review (Sonnet), Abschluss je Phase Whole-Branch-Review (Opus). Ledger `.superpowers/sdd/progress.md`.

**Ausführung: 100 % Cloud-fähig, KEIN SSH nötig.** Code/Tests/Docs = git/GitHub; Deploy automatisch
(Push→Actions→GHCR→SSH macht die CI); `gps_legs`-Migration läuft bei Container-Start selbst; Audit ist
read-only HTTPS-Endpoint. Cloudseitig nur Repo-Push-Rechte + `gh`-Auth nötig. SSH nur optionaler
Debug-Fallback (Prod-DB ansehen / fehlgeschlagene Migration).
