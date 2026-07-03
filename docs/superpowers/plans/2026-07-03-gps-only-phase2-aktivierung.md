# GPS-only Phase 2 — Aktivierung: Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> oder superpowers:executing-plans, um diesen Plan Task-für-Task umzusetzen. Steps nutzen Checkbox-Syntax.
> Design-Spec: `docs/superpowers/specs/2026-07-03-gps-only-phase2-aktivierung-design.md` (verbindlich).
> **Rev. 2 (Fable-5-Review eingearbeitet):** Finalisierung am Touchdown statt LANDED-Zustand; reine
> Block/Distanz-Helfer (StatSim-Quelle!); `connection_closed` für offene Flüge; Latch-Reconcile über das
> Connection-Intervall; Piloten-Detail behält Fremd-Callsigns; Refile-Split bleibt; Zwischen-Release
> v7.9.5 am GATE; UI-Task für Spec G; Fenster-Lookback; per-Flug-Dedup (Teil-Überlappung).

**Goal:** Statistik, Piloten-Detail, Bummel und Kutter lesen die GPS-erkannten Flüge (aus der
Positionshistorie) statt der Refile-/Disconnect-basierten `canonicalize_flights`.

**Architecture:** Zwei reine Funktionen (`detect_gps_legs` ohne 180-s-Dwell, Finalisierung am Touchdown;
`collapse_same_airport`) bilden aus Positionen die Flüge. Adapter `canonicalize_legs` liefert sie
**formgleich** zu `canonicalize_flights` (FriesenSpy+StatSim, Fallback auf Flugplan-Zeilen ohne Track,
Flugplan-Label Startplatz-primär, per-Flug-Dedup) und wird für die globale Statistik von einer
materialisierten Tabelle `flight_cache` gepuffert. Audit wird auf die collapsed-Sicht umgebaut und als
**Schatten-Release v7.9.5** deployed (GATE mit echten Prod-Zahlen). Danach Konsumenten-Umstellung,
Kutter-Latch-Reconcile, UI (GPS+Plan nebeneinander), Cleanup, **v8.0.0**.

**Tech Stack:** Python 3.11, SQLite (WAL), FastAPI, pytest, airportsdata. stdlib-Muster wie bestehend.

## Global Constraints

- **Landung** = Vollstopp `gs < 2 kt` an einem DB-Platz (10-km-Umkreis, AGL-Guard `< 300 ft`).
  **Kein 180-s-Dwell** — Finalisierung **sofort am Touchdown** (der `LANDED`-Zustand entfällt).
  Off-Airport/kein Platz → keine Landung → Flug „offen".
- **Ein Flug** = Boden-Platz → nächster **anderer** Boden-Platz. Wiederholte Landungen am **selben** Platz
  (Platzrunden) = **eine** Landung dort (collapse). Segment-Grenze (Positions-Lücke > 30 min) trennt immer.
- **Gewertet (KPI/Bummel/Kutter) nur `FRS*`-Callsign.** Das **Piloten-Detail zeigt weiterhin ALLE
  Callsigns des Piloten** (heutiges Verhalten, `callsign_prefix=""`); die „nicht gewertet"-Kennzeichnung
  ist Phase 2b.
- **`canonicalize_legs` MUSS dieselbe Dict-Form liefern wie `canonicalize_flights`** (Konsumenten
  unverändert), plus `gps_departure/gps_arrival/plan_departure/plan_arrival/connection_closed`.
- **`_BLOCK_STAND_MIN_SEC` bleibt** (Block schließt lange Bodenstände aus; behebt #17).
  `block_min ≤ duration_min` muss gewahrt bleiben. Block/Distanz für StatSim-Flüge werden aus den
  **übergebenen Positionen** gerechnet (NIE aus `position_history` per cid — falsche Tabelle!).
- **Offener Flug** (keine Landung) zählt in KPI erst bei **beendeter Verbindung**
  (`connection_closed=True`), nie live während des Flugs.
- **`flights`-Fallback:** Connection ohne verwertbaren Track → `flights`-Zeile als Flug (kein Alt-Flug
  verschwindet). Symmetrisch: StatSim ohne Track → `statsim_cache`-Zeile.
- **Kutter-Latch/Loss** sind auf `(cid, logon_time = VERBINDUNGS-Logon)` gekeyt — der liegt **vor** dem
  Takeoff. Reconcile: das **Connection-Intervall** `[logon, logoff]` muss das Flug-Fenster überlappen
  (NIE „Latch-Logon ∈ [takeoff, landing]" prüfen — das matcht nie).
- **Kutter-Streckenbedingung bleibt**: Lieferung nur wenn `dep` UND `arr` auf `route_set` (`dep ≠ arr`)
  ODER Latch; mit Latch zählt nur das Bein, das am `destination` ankommt (oder offen ist) — nie das
  Rückflug-Bein derselben Verbindung.
- **Refile-Split im Poller BLEIBT** — er erzeugt die `flights`-Zeile je Refile = Label-Zeitachse für die
  Startplatz-primäre Flugplan-Zuordnung (Spec G). Er hat keine Wertungswirkung mehr (Wertung liest GPS).
- **`duration_min`** je Flug = `takeoff→landing` (bewusst; Stunden-KPI schrumpft rückwirkend).
- UI-Standards: Blau (`--green`) nur für Klickbares; breite Tabellen in `.table-scroll`-Wrapper.
- Releases: v7.9.5 (Schatten, nach Task 6) und v8.0.0 (Aktivierung, Task 13). Version =
  `app/CHANGELOG.json[0].version`; Tag + Banner; Docs (README, docs/api.md, docs/architecture.md);
  Deploy Push→main→Actions→GHCR→SSH + Health-Check.

---

## Datei-/Verantwortungs-Struktur

- `app/gps_legs.py` — reiner Detektor. **Modify:** `detect_gps_legs` (Dwell/`LANDED` raus, Touchdown-
  Finalisierung, `segment`-Stempel); **Create:** `collapse_same_airport`.
- `app/database.py` — **Create:** `canonicalize_legs` + Helfer (`_gps_flights_for_positions`,
  `_block_seconds_positions`, `_distance_nm_positions`, `_assign_flightplan`, `_overlaps_any`,
  `_latch_hits_flight`), `flight_cache` (`rebuild_flight_cache`/`get_cached_flights`);
  **Modify:** `get_stats`, `get_stats_activity`, `compute_bummel_standings`, `compute_transport_progress`,
  `detect_transport_losses`, `audit_gps_vs_refile` (+ `_statsim_gps_interpretation` auf collapsed).
- `app/main.py` — **Modify:** `/api/pilots/{cid}/flights` (`:602-673`), `admin_gps_leg_audit` (`:1282-1324`).
- `app/static/index.html` — **Modify:** Piloten-Flugliste (GPS+Plan nebeneinander, Spec G).
- Tests je Task (siehe Tasks).

Reihenfolge: **Detektor → Adapter/Cache → Audit → Schatten-Release+GATE → Konsumenten → UI → Cleanup → v8.0.0.**

---

## Task 1: `detect_gps_legs` — Dwell raus, Finalisierung am Touchdown, `segment`-Stempel

**Files:**
- Modify: `app/gps_legs.py` (`:18` Konstante; `:174-190` AIRBORNE-Touchdown; `:196-235` LANDED-Block +
  Segment-Ende-Finalisierung; Segment-Schleife in `detect_gps_legs`).
- Test: `tests/test_gps_legs.py`.

**Interfaces:**
- Produces: `detect_gps_legs(positions, *, nearest_airport, airport_elev_ft, radius_km=10.0,
  gap_minutes=30)` → `list[dict]`; jeder Leg-Dict zusätzlich `"segment": int` (0-basiert je Zeit-Segment).
  Landung finalisiert **am Touchdown-Sample** (kein `LANDED`-Zustand mehr); jedes erneute Abheben = neuer
  Roh-Leg (normale, verankerte Abhebe-Erkennung ab `ON_GROUND`).

- [ ] **Step 1: Failing Tests**

In `tests/test_gps_legs.py` in `TestDetectGpsLegs` ergänzen (Helfer `p`, `run` vorhanden):

```python
def test_immediate_finalize_no_dwell(self):
    """Ohne Dwell: Vollstopp + sofortiges Wieder-Abheben am SELBEN Platz = zwei Roh-Legs."""
    track = [
        p(0, 50.0, 7.0, 300, 0), p(15, 50.0, 7.0, 300, 0),
        p(30, 50.05, 7.05, 900, 60),      # Abheben EDDX
        p(90, 50.0, 7.0, 300, 0),         # Vollstopp EDDX → Landung SOFORT final
        p(105, 50.05, 7.05, 900, 60),     # Wieder-Abheben (früher: Stop-and-Go-Merge)
        p(200, 52.7, 8.7, 5000, 150),
        p(320, 53.5, 9.5, 200, 0),        # Landung EDDB
        p(380, 53.5, 9.5, 200, 0),
    ]
    legs = run(track)
    assert [(l["dep_icao"], l["arr_icao"]) for l in legs] == [("EDDX", "EDDX"), ("EDDX", "EDDB")]
    assert all(l["segment"] == 0 for l in legs)

def test_segment_index_increments_on_gap(self):
    """Positions-Lücke > 30 min → zweites Segment mit segment == 1."""
    track = [
        p(0, 52.0, 8.0, 100, 0), p(15, 52.0, 8.0, 100, 0),
        p(30, 52.1, 8.05, 700, 60), p(120, 52.7, 8.7, 5000, 150),   # Segment 0, endet airborne
        p(2520, 52.9, 8.9, 5000, 150), p(2600, 53.5, 9.5, 200, 0),  # 40-min-Lücke → Segment 1
        p(2660, 53.5, 9.5, 200, 0), p(2720, 53.5, 9.5, 200, 0),
    ]
    legs = run(track)
    assert legs[0]["segment"] == 0
    assert legs[-1]["segment"] == 1
```

- [ ] **Step 2: Run — FAIL erwartet**

Run: `python -m pytest tests/test_gps_legs.py::TestDetectGpsLegs::test_immediate_finalize_no_dwell tests/test_gps_legs.py::TestDetectGpsLegs::test_segment_index_increments_on_gap -v`
Expected: FAIL (`KeyError: 'segment'`; und Merge-Verhalten des Dwells).

- [ ] **Step 3: Implementieren**

In `app/gps_legs.py`:

1. Segment-Schleife in `detect_gps_legs` ersetzen:

```python
    for seg_index, segment in enumerate(_split_on_gaps(positions, gap_minutes)):
        seg_legs = _detect_segment(segment, nearest_airport, airport_elev_ft, radius_km)
        for leg in seg_legs:
            leg["segment"] = seg_index
        legs.extend(seg_legs)
```

2. Im `AIRBORNE`-Block (`:174-190`) den Touchdown-Kandidaten **sofort finalisieren** — statt
   `state = "LANDED"; land_ts = ts; land_arr = ap; land_ground_ref = alt`:

```python
                    if agl_ok:
                        # Landung SOFORT endgültig (kein Dwell/LANDED): emit + zurück ON_GROUND.
                        land_ts = ts
                        land_arr = ap
                        emit_complete()
                        state = "ON_GROUND"
                        ground_ref_ft = alt
                        dep_icao = ap
                        dep_source = "gps"
                        takeoff_ts = None
                        max_alt = None
                        land_ts = None
                        land_arr = None
```

3. Den **kompletten `LANDED`-Block** (`:196-230`) und die Segment-Ende-Finalisierung
   `if state == "LANDED": emit_complete()` (`:233-235`) **löschen** — der Zustand existiert nicht mehr.
   Ebenso die Variablen `land_ground_ref` und die Konstante `_GPS_ARRIVAL_DWELL_SEC` (`:18`) entfernen
   (vorher `grep -rn "_GPS_ARRIVAL_DWELL" app/ tests/` — Rest-Referenzen mit anpassen).
   **WICHTIG:** kein `re_takeoff`-Sonderpfad mehr — Wieder-Abheben läuft über die normale, verankerte
   `ON_GROUND`-Erkennung (Min-Boden-Referenz). Ein steiler Steig direkt nach Landung darf die Landung
   NICHT mehr verwerfen (genau das war der Fehler der ersten Planfassung).

- [ ] **Step 4: Bestehende Dwell-abhängige Tests anpassen**

`grep -n "Dwell\|dwell\|180\|stop_and_go" tests/test_gps_legs.py`. Neue Erwartung: mehrfache Vollstopps
am selben Platz = **mehrere Roh-Legs** `X→X` (Zusammenführen macht erst `collapse_same_airport`, Task 2).
Betroffen u. a. `test_stop_and_go_merge` (jetzt 2 Legs statt 1), `test_normal_a_to_b`/`test_circuit_x_to_x`
(Dwell-Zeilen im Track unnötig, Assertions ggf. auf Roh-Sicht), `test_heli_hover_over_airport_not_landing`
(unverändert: AGL-Guard verhindert Landung), `test_finalize_landing_on_end` (Landung jetzt am Touchdown-
Sample final — Assertion identisch). Touch-and-Go (nie `gs<2`) bleibt unverändert.

- [ ] **Step 5: Run — alle grün**   `python -m pytest tests/test_gps_legs.py -v`

- [ ] **Step 6: Commit**

```bash
git add app/gps_legs.py tests/test_gps_legs.py
git commit -m "feat(gps-legs): Finalisierung am Touchdown, kein Dwell/LANDED + segment-Stempel (#23)"
```

---

## Task 2: `collapse_same_airport` — Roh-Legs zu Flügen

**Files:** Modify `app/gps_legs.py` (neue Funktion + `_close_ground`); Test `tests/test_gps_legs.py`.

**Interfaces:**
- Consumes: Leg-Dicts aus Task 1 (`dep_icao, arr_icao, takeoff_ts, landing_ts, complete, dep_source,
  arr_source, max_altitude, segment`).
- Produces: `collapse_same_airport(legs: list[dict]) -> list[dict]` — Flug-Dicts mit denselben Keys ohne
  `segment`. Regeln: aufeinanderfolgende Landungen am **selben** Platz → ein Wegpunkt (Runden absorbiert,
  `takeoff_ts` = erstes Abheben des Clusters); **anderer** Platz = neuer Flug; **Segment-Wechsel** schließt
  immer; offener Leg → offener Flug.

- [ ] **Step 1: Failing Tests — alle Spec-Beispiele**

```python
from app.gps_legs import collapse_same_airport

def _leg(dep, arr, to, ld, seg=0, complete=True, maxalt=1000):
    return {"dep_icao": dep, "arr_icao": arr, "takeoff_ts": to, "landing_ts": ld,
            "complete": complete, "dep_source": "gps" if dep else None,
            "arr_source": "gps" if (arr and complete) else None, "max_altitude": maxalt, "segment": seg}

class TestCollapseSameAirport:
    def test_circuits_at_departure_then_cross_country(self):
        legs = [_leg("EDDK","EDDK","t0","t1"), _leg("EDDK","EDDK","t2","t3"), _leg("EDDK","EDDW","t4","t5")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [("EDDK","EDDW",True)]
        assert out[0]["takeoff_ts"] == "t0" and out[0]["landing_ts"] == "t5"

    def test_real_intermediate_landing_splits(self):
        legs = [_leg("EDPS","EDNX","t0","t1"), _leg("EDNX","EDNX","t2","t3"), _leg("EDNX","EDMA","t4","t5")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDPS","EDNX"), ("EDNX","EDMA")]
        assert out[0]["landing_ts"] == "t1" and out[1]["takeoff_ts"] == "t2"

    def test_pure_circuits(self):
        legs = [_leg("EDDX","EDDX","t0","t1"), _leg("EDDX","EDDX","t2","t3")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [("EDDX","EDDX",True)]
        assert out[0]["landing_ts"] == "t3"

    def test_open_leg_stays_open(self):
        legs = [_leg("EDDK","EDDK","t0","t1"), _leg("EDDK",None,"t2",None, complete=False)]
        out = collapse_same_airport(legs)
        assert out == [{"dep_icao":"EDDK","arr_icao":None,"takeoff_ts":"t0","landing_ts":None,
                        "complete":False,"dep_source":"gps","arr_source":None,"max_altitude":1000}]

    def test_segment_boundary_does_not_merge_same_airport(self):
        legs = [_leg("EDDK","EDDK","t0","t1",seg=0), _leg("EDDK","EDDW","t9","t10",seg=1)]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDK","EDDK"), ("EDDK","EDDW")]

    def test_spawn_in_air_dep_none(self):
        out = collapse_same_airport([_leg(None,"EDDB","t0","t1")])
        assert (out[0]["dep_icao"], out[0]["arr_icao"]) == (None, "EDDB")

    def test_empty(self):
        assert collapse_same_airport([]) == []
```

- [ ] **Step 2: Run — FAIL** (`ImportError`).  `python -m pytest tests/test_gps_legs.py::TestCollapseSameAirport -v`

- [ ] **Step 3: Implementieren** (in `app/gps_legs.py`):

```python
def collapse_same_airport(legs: list[dict]) -> list[dict]:
    """Verschmilzt aufeinanderfolgende Roh-Legs am SELBEN Platz zu Flügen (Spec A).
    Ein Flug = Abheben an X → Landung am nächsten ANDEREN Platz (oder offen). Wiederholte
    Landungen am selben Platz zählen als eine Landung. Segment-Wechsel trennt immer."""
    flights: list[dict] = []
    cur: dict | None = None
    cur_seg: int | None = None
    pending_same_landing: str | None = None  # letzte Same-Airport-Landung (falls Flug am Boden endet)

    for leg in legs:
        seg = leg.get("segment", 0)
        if cur is not None and seg != cur_seg:
            _close_ground(flights, cur, pending_same_landing)
            cur = None
            pending_same_landing = None
        if cur is None:
            cur = {
                "dep_icao": leg.get("dep_icao"),
                "dep_source": leg.get("dep_source"),
                "takeoff_ts": leg.get("takeoff_ts"),
                "max_altitude": leg.get("max_altitude"),
            }
            cur_seg = seg
            pending_same_landing = None
        else:
            cur["max_altitude"] = _update_max(cur["max_altitude"], leg.get("max_altitude"))

        arr = leg.get("arr_icao")
        if not leg.get("complete") or arr is None:
            flights.append({**cur, "arr_icao": None, "landing_ts": None,
                            "complete": False, "arr_source": None})
            cur = None
            pending_same_landing = None
            continue
        if arr == cur["dep_icao"]:
            pending_same_landing = leg.get("landing_ts")   # Platzrunde → absorbieren
            continue
        flights.append({**cur, "arr_icao": arr, "landing_ts": leg.get("landing_ts"),
                        "complete": True, "arr_source": leg.get("arr_source")})
        cur = None
        pending_same_landing = None

    if cur is not None:
        _close_ground(flights, cur, pending_same_landing)
    return flights


def _close_ground(flights: list[dict], cur: dict, pending_same_landing: str | None) -> None:
    if pending_same_landing is not None:
        flights.append({**cur, "arr_icao": cur["dep_icao"], "landing_ts": pending_same_landing,
                        "complete": True, "arr_source": "gps"})
    else:
        flights.append({**cur, "arr_icao": None, "landing_ts": None,
                        "complete": False, "arr_source": None})
```

- [ ] **Step 4: Run — PASS**   `python -m pytest tests/test_gps_legs.py -v`
- [ ] **Step 5: Commit**  `git commit -m "feat(gps-legs): collapse_same_airport (#23)"`

---

## Task 3: Reine Block/Distanz-Helfer aus Positionslisten

**Files:** Modify `app/database.py` (`_block_seconds:817-…`, `_gps_distance_nm:779-…` — Logik extrahieren);
Test `tests/test_database.py`.

**Interfaces:**
- Produces: `_block_seconds_positions(positions: list[dict], start_ts: str, end_ts: str) -> int` und
  `_distance_nm_positions(positions: list[dict], start_ts: str, end_ts: str) -> int` — **rein**, arbeiten
  auf einer bereits geladenen ts-sortierten Positionsliste (Keys `latitude, longitude, groundspeed, ts`).
  Die bestehenden `_block_seconds`/`_gps_distance_nm` werden **dünne SQL-Wrapper**, die die Positionen
  laden und die reine Variante rufen — **Logik 1:1 verschieben, nicht neu schreiben** (inkl.
  `_BLOCK_STAND_MIN_SEC`-Stand-Ausschluss, Zeile 851). Grund: StatSim-Flüge liegen in
  `statsim_position_history` — die cid-gebundenen SQL-Helfer wären dort schlicht falsch.

- [ ] **Step 1: Failing Test**

```python
def test_block_seconds_positions_excludes_long_stand():
    # 3 Bewegungsphasen, dazwischen 1 h Stand (>= _BLOCK_STAND_MIN_SEC) → Stand ausgeschlossen.
    pos = (_moving("10:00:00", "10:10:00")          # 10 min Taxi/Flug
           + _standing("10:10:00", "11:10:00")      # 1 h Stand gs=0
           + _moving("11:10:00", "11:20:00"))       # 10 min
    secs = _block_seconds_positions(pos, pos[0]["ts"], pos[-1]["ts"])
    assert secs < 25 * 60                            # deutlich unter Gesamtfenster (80 min)

def test_wrappers_equal_pure(conn_with_track):
    # SQL-Wrapper und reine Variante liefern identisch fuer denselben Track.
    ...
```

(`_moving`/`_standing` als kleine Testhelfer, 15-s-Raster.)

- [ ] **Step 2: Run — FAIL** (`ImportError`).
- [ ] **Step 3:** Schleifenkörper aus `_block_seconds` (ab dem Laden der Rows) in
  `_block_seconds_positions` verschieben; `_block_seconds(conn, cid, lo, hi)` lädt Rows wie bisher und
  delegiert. Analog `_gps_distance_nm` → `_distance_nm_positions` (Haversine-Summe). Keine Verhaltens-
  Änderung für bestehende Aufrufer (bestehende Tests bleiben grün).
- [ ] **Step 4: Run — PASS**  `python -m pytest tests/test_database.py -q`
- [ ] **Step 5: Commit** `refactor(db): reine _block_seconds_positions/_distance_nm_positions (#23)`

---

## Task 4: `canonicalize_legs` — GPS-Flüge formgleich

**Files:** Modify `app/database.py`; Test `tests/test_canonicalize_legs.py` (neu).

**Interfaces:**
- Consumes: `detect_gps_legs`+`collapse_same_airport` (Task 1/2), reine Helfer (Task 3),
  `get_statsim_positions:2608`, `geo.nearest_airport_icao_fast`, `geo.airport_elevation_ft`.
- Produces: `canonicalize_legs(conn, *, cids=None, start=None, end=None, callsign_prefix="FRS")
  -> list[dict]`. `callsign_prefix=""` liefert alle Callsigns (für Piloten-Detail).

**Feld-Vertrag (Pflicht):** jedes Flug-Dict trägt mindestens die `canonicalize_flights`-Keys
(`id, cid, callsign, aircraft, departure, arrival, logon_time, logoff_time, duration_min, distance_nm,
block_min, route, remarks, cruise_altitude, cruise_tas, flight_rules, aircraft_icao, alternate, deptime,
enroute_time, fuel_time, source`) **plus** `gps_departure, gps_arrival, plan_departure, plan_arrival,
connection_closed`. Belegung: `departure=gps_departure` (Fallback: Flugplan), `arrival=gps_arrival`
(leer = offen); `logon_time=takeoff_ts`, `logoff_time=landing_ts` (None = offen);
`duration_min=(landing−takeoff)//60` (offen: bis letzter Positions-ts); `block_min` via
`_block_seconds_positions//60`; `distance_nm` via `_distance_nm_positions`; `plan_*` + Labels
(`route/remarks/aircraft/cruise_*/…`, `id`) vom Startplatz-primär zugeordneten Flugplan (Spec G), sonst
`None`/`""`; `connection_closed` = `logoff_time` der zugeordneten Connection ist gesetzt (StatSim/
Fallback: immer True).

**Ablauf (verbindlich):**
1. **Fenster-Lookback:** Positionen ab `start − 12 h` laden (Flüge, die die `start`-Grenze schneiden,
   nicht als Spawn-Artefakt anreißen); Ergebnis-Flüge filtern auf Überlappung mit `[start, end]`
   (`takeoff_ts ≤ end` und (`landing_ts` fehlt oder `landing_ts ≥ start`)).
2. **FriesenSpy:** `flights`-Zeilen im Fenster (WHERE wie `canonicalize_flights`: `callsign LIKE ?`,
   Zeitfilter; `prefix=""` → alle) → cid-Menge. Je cid: Positionen → `detect_gps_legs` →
   `collapse_same_airport` → Flug-Dicts. **Keine GPS-Flüge trotz Zeilen** → jede Zeile per
   `_flightrow_as_flight` übernehmen (Fallback b).
3. **StatSim:** Zeilen im Fenster (Filter analog). Je Zeile: `get_statsim_positions(statsim_id)` →
   Detektor+Collapse → Flug-Dicts; ohne Track → `_flightrow_as_flight` (Flugplan-Fallback).
4. **Dedup PRO FLUG (nicht pro Session):** ein StatSim-**Flug** wird verworfen, wenn sein Fenster ein
   FriesenSpy-Flug-/Fallback-Intervall desselben cid überlappt (`_overlaps_any`; offene Intervalle:
   `None`-Ende = ∞). **Teil-Überlappung:** StatSim-Flüge außerhalb der FS-Abdeckung (z. B. nach
   FS-Absturz) **überleben**.
5. Sortierung `logon_time` absteigend (wie `canonicalize_flights`).

Neue Helfer (alle in diesem Task, vollständig): `_positions_for_cid(conn, cid, start, end)`,
`_gps_flights_for_positions(positions, *, plan_rows, source)` (rechnet Metriken über die **übergebene**
Liste — Task-3-Helfer), `_assign_flightplan(plan_rows, gps_flight)` (Startplatz-Match primär, Zeit-Nähe
sekundär, sonst `None`), `_flightrow_as_flight(row, source)`, `_overlaps_any(intervals, lo, hi)`
(None-tolerant), `_statsim_plan(row)` (dep/arr/aircraft/callsign aus der `statsim_cache`-Zeile als
Pseudo-Plan-Dict mit `id=None`).

- [ ] **Step 1: Failing Tests** (`tests/test_canonicalize_legs.py`, Fixtures analog
  `TestStatsimGpsAudit._seed`; reale Plätze EDDK/EDDW):
  - `test_form_parity_and_fields` — Key-Obermenge ggü. `canonicalize_flights`; `departure/arrival` = GPS;
    `block_min ≤ duration_min`; `source="friesenspy"`.
  - `test_prefix_empty_includes_foreign` — StatSim-Flug „DFGKC": mit `callsign_prefix=""` enthalten, mit
    `"FRS"` nicht.
  - `test_frs_connection_without_track_falls_back` — `flights`-Zeile ohne Positionen erscheint.
  - `test_statsim_fallback_without_track` — dito StatSim.
  - `test_dedup_partial_overlap_keeps_uncovered_statsim` — FS-Track deckt 10:00–10:30 (offener Flug),
    StatSim hat zwei Flüge 10:05–10:25 und 10:40–11:20 → erster verworfen, **zweiter bleibt**.
  - `test_connection_closed_flag` — offener GPS-Flug: Connection `logoff_time=None` → False;
    Connection beendet → True.
  - `test_plan_assignment_start_airport_primary` — zwei Plan-Zeilen (A→B, dann B→C in der Luft gefiled);
    das B-Bein bekommt den B→C-Plan (`plan_departure="B"`), unabhängig vom Filing-Zeitpunkt; ein Bein
    ohne Match → `plan_departure is None`.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implementieren** gemäß Ablauf oben (Code-Gerüst wie Rev. 1, aber: Metriken aus
  übergebenen Positionen; Dedup pro Flug nach Schritt 3; `connection_closed` aus der per
  `_assign_flightplan`/Zeitüberlappung zugeordneten Connection-Zeile).
- [ ] **Step 4: Run — PASS**  `python -m pytest tests/test_canonicalize_legs.py -v`
- [ ] **Step 5: Commit** `feat(db): canonicalize_legs — formgleich, Fallbacks, per-Flug-Dedup (#23)`

---

## Task 5: Materialisierter `flight_cache` (globale Statistik)

**Files:** Modify `app/database.py` (DDL in `_SCHEMA` + Funktionen); Test `tests/test_flight_cache.py` (neu).

**Interfaces:**
- Produces: `rebuild_flight_cache(conn, *, full: bool = False) -> int` und
  `get_cached_flights(conn, *, start=None, end=None, callsign_prefix="FRS") -> list[dict]`.
- Tabelle `flight_cache`: Spalten = Feld-Vertrag aus Task 4 + `computed_at`; `UNIQUE(cid, logon_time)`.
- **Refresh-Regel (konkret):** `get_cached_flights` → Tabelle leer ⇒ Voll-Rebuild. Sonst: ist
  `MAX(computed_at)` älter als **600 s** ⇒ inkrementeller Refresh: alle Flüge mit
  `takeoff_ts ≥ now − 7 Tage` im Cache löschen und aus `canonicalize_legs(start=now−7d)` neu schreiben
  (abgeschlossene ältere Flüge bleiben unangetastet). Nur **globale Statistik** nutzt den Cache;
  Bummel/Kutter/Piloten-Detail rufen `canonicalize_legs` direkt (kleine cid-Mengen).

- [ ] **Step 1: Failing Tests** — `test_cache_matches_canonicalize_legs` (Voll-Rebuild ≙ live),
  `test_cache_idempotent` (2× Rebuild identisch), `test_incremental_refresh_picks_up_new_flight`
  (neuer Track nach erstem Build + `computed_at` künstlich alt ⇒ `get_cached_flights` enthält ihn).
- [ ] **Step 2: Run — FAIL.**  - [ ] **Step 3: Implementieren.**  - [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(db): flight_cache mit inkrementellem Refresh (#23)`

---

## Task 6: Audit auf collapsed-Sicht + Schatten-Release v7.9.5 (GATE)

**Files:** Modify `app/database.py` (`audit_gps_vs_refile:1852` + `_statsim_gps_interpretation`),
`app/main.py` (`admin_gps_leg_audit:1282`; `recompute_gps_legs`-Loop `:1319-1320` entfernen),
`app/CHANGELOG.json`, Docs. Test `tests/test_admin_api.py`, `tests/test_database.py`.

- [ ] **Step 1: Failing Test** — Audit-Kennzahlen kommen aus `canonicalize_legs`: ein Track mit
  Platzrunden zählt als **ein** Flug (collapsed), nicht N Roh-Legs; `401` ohne Admin bleibt; die
  `statsim`-Sektion (`statsim_sample`) klassifiziert ebenfalls collapsed (Platzrunden-Track ⇒ `match`,
  nicht `zwischenlandung`).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** `audit_gps_vs_refile` intern: je `canonicalize_flights`-Connection die überlappenden
  `canonicalize_legs`-Flüge zuordnen → `matches/missing/extra/arr_divergence` daraus.
  `_statsim_gps_interpretation`: nach `detect_gps_legs` zusätzlich `collapse_same_airport`.
  Endpoint: `recompute_gps_legs`-Loop entfernen (Tabelle wird Task 12 entsorgt).
- [ ] **Step 4: Run — PASS** (`python -m pytest tests/test_admin_api.py tests/test_database.py -q`).
- [ ] **Step 5: Schatten-Release v7.9.5.** Changelog-Eintrag (Patch, kein highlight): „GPS-Etappen-Audit
  zeigt jetzt die endgültige Flug-Sicht (Platzrunden zusammengefasst, Landung sofort) — weiterhin ohne
  Wertungswirkung." **Alles bis hier ist wertungsneutral** (Konsumenten unberührt). Branch → main mergen,
  Deploy + Health `== 7.9.5`, Tag `v7.9.5`.
- [ ] **Step 6: Commit/Tag.**

**⏸ GATE (Pflicht-Stopp):** Prod-Audit (`/api/admin/gps-leg-audit?days=365&statsim=500`) mit
**collapsed-Zahlen** sichten — die früheren „95,8 %" galten der Roh-Sicht. Erst nach Freigabe des
Nutzers weiter mit Task 7.

---

## Task 7: Statistik (`get_stats`, `get_stats_activity`)

**Files:** Modify `app/database.py` (`get_stats:1418-1470`, `get_stats_activity:1473-1531`);
Test `tests/test_database.py`.

- [ ] **Step 1: Failing Tests**

```python
def test_get_stats_counts_open_flight_only_after_connection_end(conn_):
    # Ein abgeschlossener GPS-Flug + ein offener Flug:
    #  a) Connection noch offen (flights.logoff_time IS NULL)  -> flight_count == 1
    #  b) Connection beendet                                    -> flight_count == 2
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** `canonicalize_flights(...)`-Aufrufe (Zeile 1430/1489) durch
  `get_cached_flights(conn, start=start, callsign_prefix=callsign_prefix)` ersetzen. KPI-Aggregation:
  Flüge mit `logoff_time is None` **und** `connection_closed=False` überspringen (in-progress);
  offene Flüge mit `connection_closed=True` zählen (Ziel „offen"). Die bestehende
  „Piloten mit nur offenem Flug"-Ergänzung (`:1447-1452`) auf dieselbe Regel umstellen.
  Ergebnis-Keys unverändert.
- [ ] **Step 4: Run — PASS**; Vorher/Nachher-Zahlvergleich `/api/stats` dokumentieren.
- [ ] **Step 5: Commit** `feat(stats): KPI aus GPS-Fluegen (flight_cache) (#23)`

---

## Task 8: Piloten-Detail (`/api/pilots/{cid}/flights`)

**Files:** Modify `app/main.py:602-673`; Test `tests/test_admin_api.py`.

- [ ] **Step 1: Failing Test** — Endpoint liefert GPS-Flüge inkl. Zwischenlandung (A→B→C ⇒ 2 Zeilen);
  Fremd-Callsign-StatSim-Flug des Piloten **bleibt enthalten** (heutiges Verhalten); Felder
  `gps_departure/plan_departure` vorhanden; `X-StatSim-Status`-Header bleibt.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** `canonicalize_flights(conn, cids=[cid], callsign_prefix="", …)` (Zeile 663-669) durch
  `canonicalize_legs(conn, cids=[cid], callsign_prefix="", start=start)` ersetzen —
  **`callsign_prefix=""` beibehalten** (Fremd-Callsigns sichtbar wie heute; „nicht gewertet"-Badge = 2b).
- [ ] **Step 4: Run — PASS.**  - [ ] **Step 5: Commit** `feat(api): Piloten-Detail aus GPS-Fluegen (#23)`

---

## Task 9: Bummel (`compute_bummel_standings`)

**Files:** Modify `app/database.py:2263-2359`; Test `tests/test_bummel.py`.

- [ ] **Step 1: Failing Test — „Frode"-E2E**: FRS-Flug landet am Bummel-Ziel (GPS), Verbindung endet
  normal, kein separater Refile/Disconnect-Trick ⇒ erscheint in `standings["complete"]` mit `block_min`
  aus dem Flug-Fenster.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** Zeile 2328 → `canonicalize_legs(conn, start=load_start, end=end, cids=cids)`.
  GPS-Endpunkt-Korrektur (`:2334-2343`, `_nearest_route_airport`/`_first_pos`/`_last_pos`) entfernen —
  `dep = f["departure"]`, `arr = f["arrival"]` (auf `route_set`-Mitgliedschaft wie bisher prüfen).
  `secs = f["block_min"]*60` bzw. weiterhin `_block_seconds` (identische Quelle). Offener Flug (`arrival`
  leer) fließt nicht als besuchter Platz ein ⇒ Tour ggf. unvollständig (bestehende `visited/missing`-Logik).
- [ ] **Step 4: Run — PASS** (`python -m pytest tests/test_bummel.py tests/test_bummel_races.py -q`);
  Vorher/Nachher-Zahlvergleich.
- [ ] **Step 5: Commit** `feat(bummel): Wertung aus GPS-Fluegen (#23)`

---

## Task 10: Kutter (`compute_transport_progress`, `detect_transport_losses`) + Latch/Loss-Reconcile

**Files:** Modify `app/database.py` (`compute_transport_progress:3560-3702`,
`detect_transport_losses:3387-3415`, neuer Helfer `_latch_hits_flight`); Test `tests/test_transport.py`.

**Reconcile-Regel (verbindlich):** Latch-Key = `(cid, VERBINDUNGS-logon)`; der Verbindungs-Logon liegt
**vor** dem Takeoff. Ein Latch gehört zu einem GPS-Flug, wenn das **Connection-Intervall** des Latches das
Flug-Fenster überlappt:

```python
def _latch_hits_flight(conn, latches: set[tuple[int, str]], cid: int,
                       takeoff_ts: str, landing_ts: str | None) -> bool:
    """True, wenn ein Live-Latch (cid, Verbindungs-Logon) zu diesem GPS-Flug gehört.
    Zuordnung über Überlappung Connection-Intervall [logon, logoff] ↔ Flug-Fenster."""
    end = landing_ts or "9999-12-31T23:59:59Z"
    for c, lo in latches:
        if c != cid or lo > end:
            continue
        row = conn.execute(
            "SELECT logoff_time FROM flights WHERE cid = ? AND logon_time = ?", (cid, lo)
        ).fetchone()
        hi = (row[0] if row and row[0] else "9999-12-31T23:59:59Z")
        if takeoff_ts <= hi:
            return True
    return False
```

- [ ] **Step 1: Failing Tests**
  - `test_live_latch_reconciled_to_gps_flight` — Latch mit Verbindungs-Logon **09:58**, GPS-Flug
    [10:02, 10:40] ⇒ `delivered_kg > 0` (die alte `(cid, lo) in latches`-Prüfung findet nichts).
  - `test_return_leg_not_double_counted` — Mehrbein-Connection Hin (landet am `destination`) + Rück:
    nur das Hin-Bein `loaded` (Regel: Latch **und** (`arr == destination` **oder** Flug offen)).
  - `test_delivery_requires_route_membership` — Landung neben dem Ziel, kein Latch ⇒ 0 kg.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** Zeile 3604 → `canonicalize_legs(...)`. `dep/arr` direkt aus dem Flug
  (`_nearest_airport`-Korrektur `:3621-3624` entfernen). Latch-Prüfungen `:3625` und `:3673` durch
  `_latch_hits_flight(conn, live_arrivals, cid, f["logon_time"], f["logoff_time"])` ersetzen, `loaded`
  zusätzlich an `arr == dest or not arr` binden (Rückflug-Bein zählt nie). Streckenbedingung `:3626`
  unverändert. `detect_transport_losses` (`:3415`) ebenfalls auf `canonicalize_legs` + dieselbe
  Zeitfenster-Zuordnung für vorhandene Loss-Zeilen (`:3700-3702`) umstellen; neue Loss-Zeilen behalten
  den Verbindungs-Logon als Key (Poller schreibt ihn weiter — nur die Lese-Seite reconciled).
- [ ] **Step 4: Run — PASS** (`python -m pytest tests/test_transport.py -q`); Vorher/Nachher.
- [ ] **Step 5: Commit** `feat(kutter): GPS-Fluege + Latch/Loss-Reconcile ueber Connection-Intervall (#23)`

---

## Task 11: UI — GPS-Start→Ziel und Flugplan nebeneinander (Spec G)

**Files:** Modify `app/static/index.html` (Piloten-Flugliste / Track-Zeilen-Rendering);
Test: Sichtprüfung + bestehende API-Tests (Rendering ist Vanilla-JS, kein JS-Testrunner im Repo).

- [ ] **Step 1:** Flug-Zeilen-Rendering der Piloten-Detailansicht anpassen:
  - **Route-Zelle (klickbar, blau)** zeigt `gps_departure→gps_arrival` (Fallback `departure→arrival`);
    offenes Ziel als „offen". Klick öffnet wie bisher den Track — `data-logon/data-logoff` tragen jetzt
    automatisch das Bein-Fenster (`logon_time=takeoff_ts`), der bestehende `?logon=&logoff=`-Mechanismus
    des Track-Endpoints schneidet damit genau das Bein.
  - **Neue „Plan"-Spalte** daneben (reiner Text, NICHT blau): `plan_departure→plan_arrival`, sonst `—`.
  - Tabelle bleibt im `.table-scroll`-Wrapper (mobil scrollbar); keine neuen klickbaren Blau-Elemente.
- [ ] **Step 2:** Lokal `uvicorn app.main:app` + Piloten-Detail mit A→B→C-Testdaten sichten (2 Zeilen,
  Plan-Spalte gefüllt/`—`).
- [ ] **Step 3: Commit** `feat(ui): GPS-Route klickbar + Plan-Spalte daneben (Spec G) (#23)`

---

## Task 12: Cleanup — toter Detektor-Speicher (Refile-Split BLEIBT)

**Files:** Modify `app/database.py` (`recompute_gps_legs:861` + `gps_legs`-DDL entfernen; zugehörige
Tests), `app/main.py` (Import), `docs/`. **NICHT anfassen:** Refile-Split im Poller (erzeugt die
Label-Zeitachse für Spec G), `_BLOCK_STAND_MIN_SEC`, `merge_fragmented_flights`.

- [ ] **Step 1:** `grep -rn "recompute_gps_legs\|gps_legs" app/ tests/ docs/` — alle Referenzen erfassen.
- [ ] **Step 2:** `recompute_gps_legs` + `gps_legs`-DDL + zugehörige Tests entfernen (`flight_cache` ist
  der Ersatz); `DROP TABLE IF EXISTS gps_legs` in die Migrationsliste. Docs-Referenzen bereinigen.
- [ ] **Step 3: Run** `python -m pytest tests/ -q` — alles grün.
- [ ] **Step 4: Commit** `refactor: gps_legs-Rohspeicher entfernt, flight_cache ist Ersatz (#23)`

---

## Task 13: Docs, Changelog v8.0.0, Deploy

- [ ] **Step 1:** `app/CHANGELOG.json` oben **v8.0.0** (Major/highlight): „GPS-Erkennung aktiv — Flüge,
  Ziele und Blockzeiten kommen jetzt überall aus dem echten Flugweg (Statistik, Bummel, Kutter);
  Zwischenlandungen zählen als eigene Flüge, Platzrunden nicht mehrfach; der Flugplan ist nur noch
  Beschriftung." Docs: `docs/architecture.md` (`canonicalize_legs`, `collapse_same_airport`,
  `flight_cache`, Latch-Reconcile, Semantik-Änderungen g), `docs/api.md` (Piloten-Detail-Felder,
  Audit), `README.md`.
- [ ] **Step 2: Run** `python -m pytest tests/ -q` grün; `python -c "from app.version import VERSION; print(VERSION)"` == `8.0.0`.
- [ ] **Step 3: Deploy** Branch → main → `gh run watch <id> --exit-status --interval 20` → Prod-Health
  `curl .../api/frontend-config` == `8.0.0` → Tag `v8.0.0`.
- [ ] **Step 4: Verifikation nach Deploy:** A→B→C = 2 Flüge sichtbar; Platzrunde = 1 Flug; „Frode"
  gewertet ohne Disconnect; Kutter-Lieferung via Latch trotz Verbindungs-Logon-Key; Piloten-Detail zeigt
  GPS+Plan-Spalten; Fremd-Callsigns weiter sichtbar.

---

## Nicht in diesem Plan (Phase 2b)

- **„Nicht gewertet"-Kennzeichnung** für Fremd-Callsign-Flüge im Piloten-Detail (Anzeige bleibt in
  Phase 2 erhalten, nur die Markierung fehlt noch).
- **Proaktive StatSim-Track-Beschaffung je Import** (Phase 2 nutzt den periodischen Bulk-Backfill).

## Verifikation (Self-Check des Plans)

1. `python -m pytest tests/ -v` je Task grün; zwei Releases (v7.9.5 Schatten am GATE, v8.0.0 Aktivierung).
2. Spec-Abdeckung: A→Task 1/2; a(Block)→Task 3; B/C→Task 4/5; G→Task 4 (`_assign_flightplan`) + Task 11
   (UI); Audit/GATE(d)→Task 6; D→Task 7–10; c(Reconcile)→Task 10; b(Fallback)→Task 4;
   g(Semantik)→Task 4/7; Teil-Überlappung→Task 4; Cleanup→Task 12; Release→Task 13.
3. SDD-Modell-Matrix: Implementer Task 1/2/3 Sonnet (reine Funktionen, Code im Plan), Task 4–13 Sonnet;
   **Task-Reviews Task 4 und Task 10 auf dem fähigsten Modell (Fable 5)**, übrige Reviews Sonnet;
   **finaler Whole-Branch-Review Fable 5**. Ledger `.superpowers/sdd/progress.md`.
