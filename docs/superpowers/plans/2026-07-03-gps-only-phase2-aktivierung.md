# GPS-only Phase 2 — Aktivierung: Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> oder superpowers:executing-plans, um diesen Plan Task-für-Task umzusetzen. Steps nutzen Checkbox-Syntax.
> Design-Spec: `docs/superpowers/specs/2026-07-03-gps-only-phase2-aktivierung-design.md` (verbindlich).

**Goal:** Statistik, Piloten-Detail, Bummel und Kutter lesen die GPS-erkannten Flüge (aus der
Positionshistorie, on-demand) statt der Refile-/Disconnect-basierten `canonicalize_flights`.

**Architecture:** Zwei neue reine Funktionen (`detect_gps_legs` ohne 180-s-Dwell; `collapse_same_airport`)
bilden aus Positionen die Flüge. Ein neuer Adapter `canonicalize_legs` liefert sie **formgleich** zu
`canonicalize_flights` (nur `FRS`-Callsign; FriesenSpy+StatSim; Fallback auf die Flugplan-Zeile ohne Track;
Flugplan-Label Startplatz-primär) und wird von einer materialisierten Ergebnistabelle gepuffert. Danach
werden Audit + die vier Konsumenten umgestellt, der Kutter-Latch reconciled, aufgeräumt, `v8.0.0` deployed.

**Tech Stack:** Python 3.11, SQLite (WAL), FastAPI, pytest, airportsdata. stdlib-Muster wie bestehend.

## Global Constraints

- **Landung** = Vollstopp `gs < 2 kt` an einem DB-Platz (10-km-Umkreis, AGL-Guard). **Kein 180-s-Dwell**
  (Landung finalisiert sofort). Off-Airport/kein Platz → keine Landung → Flug „offen".
- **Ein Flug** = Boden-Platz → nächster **anderer** Boden-Platz. Wiederholte Landungen am **selben** Platz
  (Platzrunden) = **eine** Landung dort (collapse), kein Extra-Flug. Segment-Grenze (Positions-Lücke
  > 30 min) trennt **immer**.
- **Gewertet nur `FRS*`-Callsign** (wie heute). Fremd-Callsign-Anzeige = **Phase 2b, NICHT hier**.
- **`canonicalize_legs` MUSS dieselbe Dict-Form liefern wie `canonicalize_flights`** (Konsumenten unverändert).
- **`_BLOCK_STAND_MIN_SEC` bleibt** (Block schließt lange Bodenstände aus — auch bei Same-Airport-Collapse;
  behebt #17). `block_min ≤ duration_min` muss gewahrt bleiben.
- **Offener Flug** zählt erst bei **beendeter Verbindung** (`logoff_time` gesetzt), nie live während des Flugs.
- **`flights`-Fallback**: FriesenSpy-Connection ohne verwertbaren Track → `flights`-Zeile als Flug übernehmen
  (kein Alt-Flug verschwindet). Symmetrisch zum StatSim-Fallback (`statsim_cache`).
- **Kutter-Latch/Loss** (`transport_live_arrivals`, `transport_cargo_losses`) sind auf `(cid, logon_time =
  Verbindungs-Logon)` gekeyt; `canonicalize_legs` setzt `logon_time = takeoff_ts` → **Reconcile per
  cid+Zeitfenster** Pflicht, sonst gehen Live-Ankünfte/Verluste verloren.
- **Kutter-Streckenbedingung bleibt**: Lieferung nur wenn `dep` UND `arr` auf `route_set` (`dep ≠ arr`)
  ODER Latch existiert.
- **`duration_min`** je Flug = `takeoff→landing` (bewusst; Stunden-KPI schrumpft rückwirkend).
- Release je Meilenstein: Version hoch (`app/CHANGELOG.json` oben) + Git-Tag + Auto-Banner; Docs
  (README, docs/api.md, docs/architecture.md) mitpflegen; Deploy Push→main→Actions→GHCR→SSH + Health-Check.
- `VERSION` kommt aus `app/CHANGELOG.json[0].version` (`app/version.py`).

---

## Datei-/Verantwortungs-Struktur

- `app/gps_legs.py` — reiner Detektor. **Modify:** `detect_gps_legs` (Dwell raus, `segment`-Stempel);
  **Create:** `collapse_same_airport`.
- `app/database.py` — **Create:** `canonicalize_legs` + Helfer (`_gps_flights_for_positions`,
  `_assign_flightplan`, `_flights_rows_for_cids`, Result-Cache `rebuild_flight_cache`/`get_cached_flights`);
  **Modify:** `get_stats`, `get_stats_activity`, `compute_bummel_standings`, `compute_transport_progress`,
  `detect_transport_losses`, `audit_gps_vs_refile`.
- `app/main.py` — **Modify:** `/api/pilots/{cid}/flights`, `admin_gps_leg_audit`.
- `tests/…` — je Task ein Testfile (siehe Tasks).

Reihenfolge: **Detektor-Kern → Adapter/Cache → Audit/GATE → Konsumenten → Cleanup → Release.**

---

## Task 1: `detect_gps_legs` — 180-s-Dwell entfernen + `segment`-Stempel

**Files:**
- Modify: `app/gps_legs.py:18` (Konstante), `:130-238` (`_detect_segment` LANDED-Block + Segment-Schleife).
- Test: `tests/test_gps_legs.py` (bestehende Datei — Dwell-abhängige Tests anpassen; neue Tests).

**Interfaces:**
- Consumes: —
- Produces: `detect_gps_legs(positions, *, nearest_airport, airport_elev_ft, radius_km=10.0, gap_minutes=30)`
  → `list[dict]`; jeder Leg-Dict hat zusätzlich `"segment": int` (0-basiert je Zeit-Segment). Landung
  finalisiert **sofort** (kein Dwell); Re-Takeoff = neuer Roh-Leg.

- [ ] **Step 1: Failing test — sofortige Finalisierung + Segment-Stempel**

In `tests/test_gps_legs.py` neuen Test ergänzen (nutzt vorhandene Helfer `p`, `_ts`, `run`, `AIRPORTS`):

```python
def test_immediate_finalize_no_dwell(self):
    """Ohne 180-s-Dwell: Landung + sofortiges Wieder-Abheben (< 180 s) an SELBEM Platz = zwei
    Roh-Legs (X→X, X→…); Segment-Index 0 bei einem lückenlosen Track."""
    track = [
        p(0, 50.0, 7.0, 300, 0), p(15, 50.0, 7.0, 300, 0),
        p(30, 50.05, 7.05, 900, 60),      # Abheben EDDX
        p(90, 50.0, 7.0, 300, 0),         # Landung EDDX
        p(105, 50.05, 7.05, 900, 60),     # < 180 s später wieder ab (früher: Stop-and-Go-Merge)
        p(200, 52.7, 8.7, 5000, 150),     # weg
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
        p(30, 52.1, 8.05, 700, 60), p(120, 52.7, 8.7, 5000, 150),  # Segment 0, endet airborne
        p(2520, 52.9, 8.9, 5000, 150), p(2600, 53.5, 9.5, 200, 0),  # 40-min-Lücke → Segment 1
        p(2660, 53.5, 9.5, 200, 0), p(2720, 53.5, 9.5, 200, 0),
    ]
    legs = run(track)
    assert legs[0]["segment"] == 0
    assert legs[-1]["segment"] == 1
```

- [ ] **Step 2: Run — erwartet FAIL**

Run: `python -m pytest tests/test_gps_legs.py::TestDetectGpsLegs::test_immediate_finalize_no_dwell tests/test_gps_legs.py::TestDetectGpsLegs::test_segment_index_increments_on_gap -v`
Expected: FAIL (`KeyError: 'segment'` bzw. falsche Leg-Aufteilung durch Dwell-Merge).

- [ ] **Step 3: Dwell entfernen + Segment stempeln**

In `app/gps_legs.py`:
1. `detect_gps_legs` (Segment-Schleife): Segment-Index an `_detect_segment` durchreichen und auf jeden Leg stempeln. Ersetze den Schleifenkörper (aktuell `for segment in _split_on_gaps(...): legs.extend(_detect_segment(...))`) durch:

```python
    for seg_index, segment in enumerate(_split_on_gaps(positions, gap_minutes)):
        seg_legs = _detect_segment(segment, nearest_airport, airport_elev_ft, radius_km)
        for leg in seg_legs:
            leg["segment"] = seg_index
        legs.extend(seg_legs)
```

2. Im `LANDED`-Block (`:196-230`) das Dwell-Fenster entfernen: statt „`if elapsed > _GPS_ARRIVAL_DWELL_SEC:` … finalisieren" wird die Landung **sofort** finalisiert. Ersetze den Block ab `# Kein Re-Takeoff:` (Zeile 213–230) durch sofortiges Emit:

```python
            # Kein Re-Takeoff → Ankunft SOFORT endgültig (kein Dwell-Fenster).
            emit_complete()
            state = "ON_GROUND"
            ground_ref_ft = land_ground_ref if land_ground_ref is not None else alt
            dep_icao = land_arr
            dep_source = "gps" if land_arr else None
            takeoff_ts = None
            max_alt = None
            land_ts = None
            land_arr = None
            land_ground_ref = None
            continue
```

Damit wird beim allerersten Sample nach der Landung (kein Steigen) sofort emittet; der `re_takeoff`-Zweig
darüber (`:199-211`) bleibt unverändert (echtes Wieder-Steigen = Stop-and-Go innerhalb desselben Roh-Legs).
Die Konstante `_GPS_ARRIVAL_DWELL_SEC` (Zeile 18) und `_parse_ts`-Nutzung im entfernten Block entfallen —
Konstante löschen, falls nirgends sonst referenziert (`grep _GPS_ARRIVAL_DWELL_SEC app/`).

- [ ] **Step 4: Bestehende Dwell-abhängige Tests anpassen**

`grep -n "180\|Dwell\|stop_and_go\|dwell" tests/test_gps_legs.py`. Betroffen sind u. a.
`test_stop_and_go_merge`, `test_go_around_never_below_2kt`, `test_normal_a_to_b` (Dwell-Kommentare) sowie
alle, die mehrfache Vollstopps am selben Platz als **einen** Leg erwarteten. Neue Erwartung: mehrfache
Vollstopps am selben Platz = **mehrere Roh-Legs** `X→X` (der Collapse in Task 2 führt sie zusammen, nicht
mehr der Detektor). Touch-and-Go (nie `gs<2`) bleibt **unverändert** ein Leg (keine Landung). Passe die
Assertions dieser Tests auf die Roh-Leg-Sicht an (bzw. verschiebe „= ein Flug"-Erwartungen in Task 2).

- [ ] **Step 5: Run — alle grün**

Run: `python -m pytest tests/test_gps_legs.py -v`
Expected: PASS (alle, inkl. der zwei neuen).

- [ ] **Step 6: Commit**

```bash
git add app/gps_legs.py tests/test_gps_legs.py
git commit -m "feat(gps-legs): detect_gps_legs ohne 180s-Dwell + segment-Stempel (#23 Phase 2)"
```

---

## Task 2: `collapse_same_airport` — Roh-Legs zu Flügen verschmelzen

**Files:**
- Modify: `app/gps_legs.py` (neue Funktion + `_close_ground`-Helfer am Dateiende).
- Test: `tests/test_gps_legs.py`.

**Interfaces:**
- Consumes: Leg-Dicts aus `detect_gps_legs` (Keys `dep_icao, arr_icao, takeoff_ts, landing_ts, complete,
  dep_source, arr_source, max_altitude, segment`).
- Produces: `collapse_same_airport(legs: list[dict]) -> list[dict]`. Jeder Flug-Dict:
  `dep_icao, arr_icao, takeoff_ts, landing_ts, complete, dep_source, arr_source, max_altitude`.
  Regeln: aufeinanderfolgende Landungen am **selben** Platz → ein Wegpunkt; **anderer** Platz = neuer Flug;
  **Segment-Wechsel** schließt immer; offener Leg → offener Flug (`arr_icao=None, complete=False`).

- [ ] **Step 1: Failing test — alle Spec-Beispiele**

```python
from app.gps_legs import collapse_same_airport

def _leg(dep, arr, to, ld, seg=0, complete=True, maxalt=1000):
    return {"dep_icao": dep, "arr_icao": arr, "takeoff_ts": to, "landing_ts": ld,
            "complete": complete, "dep_source": "gps" if dep else None,
            "arr_source": "gps" if (arr and complete) else None, "max_altitude": maxalt, "segment": seg}

class TestCollapseSameAirport:
    def test_circuits_at_departure_then_cross_country(self):
        # EDDK-Runden → EDDW  == EDDK→EDDW
        legs = [_leg("EDDK","EDDK","t0","t1"), _leg("EDDK","EDDK","t2","t3"),
                _leg("EDDK","EDDW","t4","t5")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [("EDDK","EDDW",True)]
        assert out[0]["takeoff_ts"] == "t0" and out[0]["landing_ts"] == "t5"

    def test_real_intermediate_landing_splits(self):
        # EDPS → EDNX (mit Runden) → EDMA  == EDPS→EDNX, EDNX→EDMA
        legs = [_leg("EDPS","EDNX","t0","t1"), _leg("EDNX","EDNX","t2","t3"),
                _leg("EDNX","EDMA","t4","t5")]
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
        # Runden EDDK (Segment 0), > 30 min Lücke, dann EDDK→EDDW (Segment 1): ZWEI Flüge
        legs = [_leg("EDDK","EDDK","t0","t1",seg=0), _leg("EDDK","EDDW","t9","t10",seg=1)]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDK","EDDK"), ("EDDK","EDDW")]

    def test_spawn_in_air_dep_none(self):
        legs = [_leg(None,"EDDB","t0","t1")]
        out = collapse_same_airport(legs)
        assert (out[0]["dep_icao"], out[0]["arr_icao"]) == (None, "EDDB")

    def test_empty(self):
        assert collapse_same_airport([]) == []
```

- [ ] **Step 2: Run — FAIL** (`ImportError: cannot import name 'collapse_same_airport'`).

Run: `python -m pytest tests/test_gps_legs.py::TestCollapseSameAirport -v`

- [ ] **Step 3: Implementieren** (in `app/gps_legs.py`):

```python
def collapse_same_airport(legs: list[dict]) -> list[dict]:
    """Verschmilzt aufeinanderfolgende Roh-Legs am SELBEN Platz zu Flügen (siehe Spec A).
    Ein Flug = Abheben an X → Landung am nächsten ANDEREN Platz (oder offen). Wiederholte
    Landungen am selben Platz zählen als eine Landung. Segment-Wechsel trennt immer."""
    flights: list[dict] = []
    cur: dict | None = None
    cur_seg: int | None = None
    pending_same_landing: str | None = None  # letzte Same-Airport-Landung, falls Flug am Boden endet

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

- [ ] **Step 4: Run — PASS**

Run: `python -m pytest tests/test_gps_legs.py -v`  Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/gps_legs.py tests/test_gps_legs.py
git commit -m "feat(gps-legs): collapse_same_airport — Roh-Legs zu Fluegen (#23 Phase 2)"
```

---

## Task 3: `canonicalize_legs` — GPS-Flüge formgleich zu `canonicalize_flights`

**Files:**
- Modify: `app/database.py` (neue Funktionen; nutzt `detect_gps_legs`, `collapse_same_airport`,
  `_block_seconds:817`, `_gps_distance_nm:779`, `get_statsim_positions:2608`, `_dedup_statsim_against_fs:1698`,
  `geo.nearest_airport_icao_fast`, `geo.airport_elevation_ft`).
- Test: `tests/test_canonicalize_legs.py` (neu).

**Interfaces:**
- Consumes: `collapse_same_airport`, `detect_gps_legs` (Task 1/2).
- Produces:
  - `canonicalize_legs(conn, *, cids=None, start=None, end=None, callsign_prefix="FRS") -> list[dict]` —
    **nur `FRS*`-Callsign**, formgleich zu `canonicalize_flights` (siehe Feld-Liste unten).
  - `_gps_flights_for_positions(conn, cid, positions, source) -> list[dict]` (Helfer, rein je Positionsliste).
  - `_assign_flightplan(flights_rows, gps_flight) -> dict | None` (Startplatz-primär, siehe Spec G).

**Feld-Parität (Pflicht):** ein `canonicalize_legs`-Flug-Dict MUSS mindestens dieselben Keys tragen wie
`canonicalize_flights` (FriesenSpy-Zweig): `id, cid, callsign, aircraft, departure, arrival, logon_time,
logoff_time, duration_min, distance_nm, block_min, route, remarks, cruise_altitude, cruise_tas,
flight_rules, aircraft_icao, alternate, deptime, enroute_time, fuel_time, source`. Zusätzlich:
`gps_departure`/`gps_arrival` (die GPS-Endpunkte, für die Anzeige-Spalte G). Belegung:
`departure=gps_departure`, `arrival=gps_arrival` (leer = offen); `logon_time=takeoff_ts`,
`logoff_time=landing_ts`; `route/remarks/cruise_*/…` vom zugeordneten Flugplan (`_assign_flightplan`), sonst
leer/`None`; `id` = die `flights.id` der zugeordneten Connection (oder `None`).

- [ ] **Step 1: Failing test — Parität, FRS-only, Fallback, Dedup**

`tests/test_canonicalize_legs.py` (neu). Nutze `_make_conn` aus `tests/test_database.py`-Muster (In-Memory,
reale Plätze EDDK 50.8659/7.14274, EDDW 53.0475/8.78667). Seed: eine FriesenSpy-`flights`-Zeile + dichter
`position_history`-Track EDDK→EDDW; ein StatSim-Flug ohne Track (nur `statsim_cache`).

```python
def test_form_parity_and_fields(conn_with_fs_track):
    conn = conn_with_fs_track          # FS-Flug EDDK→EDDW mit Track, callsign FRS10
    legs = canonicalize_legs(conn, start="2026-07-01T00:00:00Z", end="2026-07-03T00:00:00Z")
    ref = canonicalize_flights(conn, start="2026-07-01T00:00:00Z", end="2026-07-03T00:00:00Z")
    assert set(k for f in ref for k in f) <= set(k for l in legs for k in l)   # keine Key fehlt
    f = next(l for l in legs if l["callsign"] == "FRS10")
    assert (f["departure"], f["arrival"]) == ("EDDK", "EDDW")
    assert f["logon_time"] and f["logoff_time"]
    assert f["source"] == "friesenspy"
    assert f["block_min"] <= f["duration_min"]

def test_only_frs_scored(conn_with_foreign_statsim):
    # StatSim-Flug callsign "DFGKC" (Friesen-cid) → NICHT in canonicalize_legs
    legs = canonicalize_legs(conn_with_foreign_statsim, start=..., end=...)
    assert all(l["callsign"].upper().startswith("FRS") for l in legs)

def test_frs_connection_without_track_falls_back(conn_fs_no_track):
    # FS-flights-Zeile FRS20 EDDK→EDDW, KEINE position_history → Flugplan-Fallback
    legs = canonicalize_legs(conn_fs_no_track, start=..., end=...)
    assert any(l["callsign"] == "FRS20" and l["departure"] == "EDDK" for l in legs)

def test_statsim_fallback_without_track(conn_statsim_no_track):
    legs = canonicalize_legs(conn_statsim_no_track, start=..., end=...)
    assert any(l["source"] == "statsim" for l in legs)

def test_dedup_friesenspy_wins(conn_fs_and_statsim_same_flight):
    # gleicher cid+Zeit in FS (Track) und StatSim → nur EIN Flug, source friesenspy
    legs = canonicalize_legs(conn_fs_and_statsim_same_flight, start=..., end=...)
    same = [l for l in legs if l["cid"] == TEST_CID]
    assert len(same) == 1 and same[0]["source"] == "friesenspy"
```

(Fixtures als Modul-Helfer schreiben; Track-Seed analog `tests/test_database.py::TestStatsimGpsAudit._seed`.)

- [ ] **Step 2: Run — FAIL** (`ImportError`/`AttributeError`).

- [ ] **Step 3: Implementieren** (`app/database.py`), Kernlogik:

```python
def canonicalize_legs(conn, *, cids=None, start=None, end=None, callsign_prefix="FRS"):
    """GPS-erkannte Flüge, NUR FRS-Callsign, formgleich zu canonicalize_flights (Spec B/C/G)."""
    from app import geo
    prefix_pat = f"{callsign_prefix}%"

    # 1) FriesenSpy-Connections im Fenster (flights-Zeilen = Flugplan-Zeitachse + Fallback).
    fs_rows = _flights_rows_for_cids(conn, cids=cids, prefix_pat=prefix_pat, start=start, end=end)
    fs_by_cid = {}
    for r in fs_rows:
        fs_by_cid.setdefault(r["cid"], []).append(r)

    result = []
    fs_covered = {}   # cid -> list[(takeoff_ts, landing_ts)] für Dedup gegen StatSim

    for cid, rows in fs_by_cid.items():
        positions = _positions_for_cid(conn, cid, start, end)          # position_history, ts-sortiert
        gps_flights = _gps_flights_for_positions(conn, cid, positions, "friesenspy")
        if gps_flights:
            for gf in gps_flights:
                fp = _assign_flightplan(rows, gf)
                result.append(_to_flight_dict(gf, fp, source="friesenspy"))
                fs_covered.setdefault(cid, []).append((gf["logon_time"], gf["logoff_time"]))
        else:
            # Fallback: Connection ohne verwertbaren Track → flights-Zeile(n) als Flug übernehmen.
            for r in rows:
                result.append(_flightrow_as_flight(r, source="friesenspy"))
                fs_covered.setdefault(cid, []).append((r["logon_time"], r["logoff_time"]))

    # 2) StatSim (FRS-Callsign), dedupliziert gegen FS (cid + Zeitüberlappung).
    st_rows = _statsim_rows_for_cids(conn, cids=cids, prefix_pat=prefix_pat, start=start, end=end)
    for r in st_rows:
        if _overlaps_any(fs_covered.get(r["cid"], []), r["logon_time"], r["logoff_time"]):
            continue
        positions = get_statsim_positions(conn, r["statsim_id"])
        gps_flights = _gps_flights_for_positions(conn, r["cid"], positions, "statsim") if positions else []
        if gps_flights:
            for gf in gps_flights:
                result.append(_to_flight_dict(gf, _statsim_plan(r), source="statsim"))
        else:
            result.append(_flightrow_as_flight(r, source="statsim"))   # Flugplan-Fallback

    result.sort(key=lambda x: x.get("logon_time") or "", reverse=True)
    return result
```

Helfer im selben Commit (vollständig ausformulieren):
- `_positions_for_cid(conn, cid, start, end)` — `SELECT latitude, longitude, altitude, groundspeed, ts
  FROM position_history WHERE cid=? AND ts>=? AND ts<=? ORDER BY ts` (start/end optional).
- `_gps_flights_for_positions(conn, cid, positions, source)` — ruft `detect_gps_legs(positions,
  nearest_airport=geo.nearest_airport_icao_fast, airport_elev_ft=geo.airport_elevation_ft,
  radius_km=_BUMMEL_AIRPORT_RADIUS_KM)` + `collapse_same_airport`; je Flug `logon_time=takeoff_ts`,
  `logoff_time=landing_ts`, `duration_min=(landing-takeoff)//60`, `distance_nm=_gps_distance_nm(...)`,
  `block_min=_block_seconds(...)//60` (Fenster `[takeoff, landing]`; offener Flug: Fenster bis letzter ts,
  `logoff_time=None`, `arrival=""`). `gps_departure=dep_icao`, `gps_arrival=arr_icao`.
- `_assign_flightplan(rows, gf)` — Startplatz-primär: der `rows`-Datensatz, dessen `departure` == `gf`
  GPS-dep; sonst zeitlich nächster (`logon_time` am dichtesten an `gf.logon_time`); sonst `None`.
- `_to_flight_dict(gf, fp, source)` — baut das paritätische Dict: GPS-Felder + Labels aus `fp`
  (`route, remarks, aircraft, cruise_*, flight_rules, aircraft_icao, alternate, deptime, enroute_time,
  fuel_time`, `id=fp["id"]`), fehlende Keys mit `None`/`""`/`0`.
- `_flightrow_as_flight(r, source)` — die `flights`- bzw. `statsim_cache`-Zeile als paritätisches Dict
  (departure/arrival aus dem Flugplan, `gps_departure=None`, `gps_arrival=None`).
- `_flights_rows_for_cids` / `_statsim_rows_for_cids` — wie `canonicalize_flights` (dieselben WHERE-Filter,
  `callsign LIKE prefix_pat`, Zeitfenster), liefern die Roh-Zeilen inkl. `id`/`statsim_id`.
- `_overlaps_any(intervals, lo, hi)` — True, wenn `[lo,hi]` eines der `(logon,logoff)`-Intervalle schneidet.

- [ ] **Step 4: Run — PASS**  `python -m pytest tests/test_canonicalize_legs.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_canonicalize_legs.py
git commit -m "feat(db): canonicalize_legs — GPS-Fluege formgleich, FRS-only, Fallbacks, Dedup (#23)"
```

---

## Task 4: Materialisierter Ergebnis-Cache (globale Statistik)

**Files:** Modify `app/database.py` (DDL + `rebuild_flight_cache`/`get_cached_flights`); Test
`tests/test_flight_cache.py` (neu).

**Interfaces:**
- Consumes: `canonicalize_legs` (Task 3).
- Produces: `get_cached_flights(conn, *, start, end, callsign_prefix="FRS") -> list[dict]` (liest den Cache,
  baut ihn bei Bedarf inkrementell). Tabelle `flight_cache` (dieselben Dict-Felder als Spalten +
  `computed_at`; Idempotenz-Key `(cid, logon_time)`).

- [ ] **Step 1: Failing test — Cache liefert identisch zu canonicalize_legs, ist idempotent**

```python
def test_cache_matches_canonicalize_legs(conn_with_fs_track):
    live = canonicalize_legs(conn_with_fs_track, start=S, end=E)
    rebuild_flight_cache(conn_with_fs_track)
    cached = get_cached_flights(conn_with_fs_track, start=S, end=E)
    key = lambda f: (f["cid"], f["logon_time"], f["departure"], f["arrival"])
    assert sorted(map(key, cached)) == sorted(map(key, live))

def test_cache_idempotent(conn_with_fs_track):
    rebuild_flight_cache(conn_with_fs_track)
    a = get_cached_flights(conn_with_fs_track, start=S, end=E)
    rebuild_flight_cache(conn_with_fs_track)
    b = get_cached_flights(conn_with_fs_track, start=S, end=E)
    assert a == b
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implementieren.** DDL `flight_cache` (Spalten = Flug-Dict-Felder, `UNIQUE(cid, logon_time)`;
  `flight_cache` in `_SCHEMA`/Migrationsliste ergänzen). `rebuild_flight_cache(conn, cids=None)`: ruft
  `canonicalize_legs` (ganze bzw. cid-Menge), `DELETE`+`INSERT OR REPLACE` (abgeschlossene Flüge stabil,
  offene/neue neu). `get_cached_flights`: SELECT im Fenster; ist der Cache leer/veraltet für das Fenster,
  einmal `rebuild_flight_cache` (Kaltstart) und erneut lesen. **Nur globale Statistik nutzt den Cache**;
  Event-scoped Aufrufe (Bummel/Kutter/Piloten-Detail, wenige cids) rufen `canonicalize_legs` direkt.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(db): materialisierter flight_cache fuer globale Statistik (#23)`.

---

## Task 5: Audit auf collapsed/no-180s umbauen (GATE)

**Files:** Modify `app/database.py` (`audit_gps_vs_refile:1852`), `app/main.py`
(`admin_gps_leg_audit:1282`, `recompute_gps_legs`-Call `:1320` entfernen). Test `tests/test_admin_api.py`.

**Interfaces:** Consumes `canonicalize_legs`. Produces: das Audit vergleicht `canonicalize_flights`
(heutige Zählung) gegen **`canonicalize_legs`** (collapsed/no-180s — das Aktivierungsverhalten), nicht mehr
gegen die Roh-`gps_legs`-Tabelle.

- [ ] **Step 1: Failing test** — `admin_gps_leg_audit` liefert Kennzahlen aus `canonicalize_legs`; ein Track
  mit Platzrunden zählt als **ein** Flug (collapsed), nicht mehr als N Roh-Legs. `401` ohne Admin bleibt.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** `audit_gps_vs_refile` intern von `gps_legs`-Tabelle auf `canonicalize_legs` umstellen
  (Zuordnung je `canonicalize_flights`-Connection → überlappende `canonicalize_legs`-Flüge; `matches/
  missing/extra/arr_divergence` neu daraus). Im Endpoint den `recompute_gps_legs`-Loop (`:1319-1320`)
  entfernen. `recompute_gps_legs` + `gps_legs`-Tabelle sind danach ungenutzt → als toter Code markiert
  (Entfernung in Task 10).
- [ ] **Step 4: Run — PASS** (`python -m pytest tests/test_admin_api.py -v`).
- [ ] **Step 5: Commit** `refactor(audit): GATE prueft collapsed/no-180s (canonicalize_legs) (#23)`.

**⏸ GATE:** Prod-Audit neu ziehen (`?statsim=N`) → collapsed-Zahlen sichten; Schwellen/Regeln bestätigen,
bevor die Konsumenten umgestellt werden (Tasks 6–9). Die früheren „95,8 %"-Zahlen galten der Roh-Sicht.

---

## Task 6: Statistik umstellen (`get_stats`, `get_stats_activity`)

**Files:** Modify `app/database.py` (`get_stats:1418-1430`, `get_stats_activity:1473-1489`). Test
`tests/test_database.py`.

**Interfaces:** Consumes `get_cached_flights` (Task 4).

- [ ] **Step 1: Failing test — Vorher/Nachher + offene Flüge nur bei beendeter Verbindung**

```python
def test_get_stats_uses_gps_and_excludes_live_open_flight(conn_...):
    # Pilot mit abgeschlossenem GPS-Flug + einem OFFENEN (logoff_time None, in-progress):
    stats = get_stats(conn, days=30)
    row = next(s for s in stats if s["cid"] == CID)
    assert row["flight_count"] == 1   # offener in-progress zaehlt (noch) nicht
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** In `get_stats`/`get_stats_activity` den `canonicalize_flights(...)`-Aufruf (Zeile 1430 /
  1489) durch `get_cached_flights(conn, start=start, callsign_prefix=callsign_prefix)` ersetzen.
  Aggregation: offene Flüge (`logoff_time` None) nur zählen, wenn die **Verbindung beendet** ist — d. h.
  überspringe Flüge mit `logoff_time is None` in der KPI-Aggregation (in-progress). `duration`-Summe nutzt
  `duration_min` (jetzt takeoff→landing). Ergebnis-Keys unverändert (`fs_count/st_count/flight_count/…`).
- [ ] **Step 4: Run — PASS**, plus manueller Vorher/Nachher-Vergleich auf Prod (`/api/stats` alt vs. neu).
- [ ] **Step 5: Commit** `feat(stats): KPI aus GPS-Fluegen (canonicalize_legs/cache) (#23)`.

---

## Task 7: Piloten-Detail umstellen (`/api/pilots/{cid}/flights`)

**Files:** Modify `app/main.py:602-673`. Test `tests/test_admin_api.py` bzw. `tests/test_main.py`.

**Interfaces:** Consumes `canonicalize_legs`.

- [ ] **Step 1: Failing test** — Endpoint liefert die GPS-Flüge des cid inkl. Zwischenlandungen; Felder
  `departure/arrival` = GPS, `route`/`aircraft` als Label; `X-StatSim-Status`-Header bleibt.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** Zeile 663–669 den `canonicalize_flights(conn, cids=[cid], callsign_prefix="", …)`-Aufruf
  durch `canonicalize_legs(conn, cids=[cid], start=start, callsign_prefix=settings.CALLSIGN_PREFIX)`
  ersetzen. **`callsign_prefix` = FRS** (Fremd-Callsign-Anzeige ist Phase 2b, hier NICHT). Rückgabeform
  unverändert (Liste von Flug-Dicts).
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** `feat(api): Piloten-Detail zeigt GPS-Fluege (#23)`.

---

## Task 8: Bummel umstellen (`compute_bummel_standings`)

**Files:** Modify `app/database.py:2263-2359`. Test `tests/test_bummel.py`.

**Interfaces:** Consumes `canonicalize_legs`.

- [ ] **Step 1: Failing test — „Frode"-E2E**

```python
def test_frode_lands_stays_connected_scored_without_disconnect(conn_...):
    # FRS-Flug landet am Bummel-Ziel, logoff_time gesetzt (Verbindung beendet), OHNE separaten Disconnect-
    # Zombie. Erwartung: erscheint in standings["complete"] mit block_min aus dem GPS-Flugfenster.
    res = compute_bummel_standings(conn, route_icaos=["EDDK","EDDW"], start=S, end=E)
    assert any(c["cid"] == FRODE for c in res["complete"])
```

- [ ] **Step 2: Run — FAIL** (heute an Disconnect gebunden / andere Blockzeit).
- [ ] **Step 3:** Zeile 2328 `canonicalize_flights(...)` → `canonicalize_legs(conn, start=load_start,
  end=end, cids=cids)`. Die **GPS-Endpunkt-Korrektur (Zeile 2334–2343, `_nearest_route_airport`/`_first_pos`/
  `_last_pos`)** entfällt — `dep`/`arr` kommen direkt aus dem Flug (`f["departure"]`/`f["arrival"]`). Block:
  weiter `_block_seconds` bzw. `f["block_min"]*60` (bleibt gate-to-gate mit Stand-Ausschluss). Offener Flug
  (`arrival` leer) → Tour bleibt unvollständig (bestehende `visited/missing`-Logik greift). Nested
  `_nearest_route_airport`/`_first_pos`/`_last_pos`-Aufrufe hier entfernen.
- [ ] **Step 4: Run — PASS** (`python -m pytest tests/test_bummel.py -v`), Vorher/Nachher-Zahlvergleich.
- [ ] **Step 5: Commit** `feat(bummel): Wertung aus GPS-Fluegen, Endpunkt-Korrektur entfaellt (#23)`.

---

## Task 9: Kutter umstellen + Latch/Loss-Reconcile

**Files:** Modify `app/database.py` (`compute_transport_progress:3560-3702`, `detect_transport_losses:3387-3415`).
Test `tests/test_transport.py`.

**Interfaces:** Consumes `canonicalize_legs`. **Reconcile:** `transport_live_arrivals` (Key
`(cid, logon_time=Verbindungs-Logon)`) und `transport_cargo_losses` (Key `(event_id, cid, logon_time)`)
müssen dem GPS-Flug (`logon_time=takeoff_ts`) per **cid + Zeitfenster-Überlappung** zugeordnet werden.

- [ ] **Step 1: Failing test — Live-Latch bleibt trotz takeoff_ts-Key**

```python
def test_live_latch_reconciled_to_gps_flight(conn_...):
    # transport_live_arrivals hat (cid, VERBINDUNGS-logon); der GPS-Flug hat logon_time=takeoff_ts != das.
    # Erwartung: loaded=True (Fracht geliefert), Latch wird ueber cid+Zeitfenster zugeordnet.
    prog = compute_transport_progress(conn, event, now)
    assert prog["delivered_kg"] > 0

def test_delivery_requires_route_membership(conn_...):
    # Flug landet NEBEN dem Ziel (nicht auf route_set), kein Latch → keine Lieferung.
    prog = compute_transport_progress(conn, event_spawn_next_to_dest, now)
    assert prog["delivered_kg"] == 0
```

- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3:** Zeile 3604 `canonicalize_flights(...)` → `canonicalize_legs(...)`. `dep/arr` direkt aus dem
  Flug (GPS), die `_nearest_airport`/`_first_pos`/`_last_pos`-Korrektur (3621–3624) entfällt. **Latch-
  Reconcile:** statt `(cid, lo) in live_arrivals` (3625/3673) eine Hilfsfunktion
  `_latch_hits(live_arrivals, cid, takeoff_ts, landing_ts)` — True, wenn ein Latch-`logon_time` desselben
  cid **im Zeitfenster** `[takeoff_ts, landing_ts]` (bzw. der überlappenden Connection) liegt. **Strecken-
  bedingung bleibt** (3626: `dep/arr ∈ route_set`, `dep≠arr`, oder Latch). Analog in `detect_transport_losses`
  (3387–3415) den `canonicalize_flights`-Aufruf ersetzen und die Loss-Zuordnung (`f"{cid}:{logon_time}"`,
  3700–3702) über dieselbe Zeitfenster-Überlappung reconcilen.
- [ ] **Step 4: Run — PASS** (`python -m pytest tests/test_transport.py -v`), Vorher/Nachher.
- [ ] **Step 5: Commit** `feat(kutter): Wertung aus GPS-Fluegen + Latch/Loss-Reconcile (#23)`.

---

## Task 10: Cleanup — Refile-Leg-Split, toter Detektor-Speicher

**Files:** Modify `app/poller.py` (Refile-Leg-Split ~768-794 aus Phase 1 — nur die **Leg-Trennung**, die
Flugplan-Zeile bleibt), `app/database.py` (`recompute_gps_legs`, `gps_legs`-DDL — entfernen oder als
Debug belassen; **`_BLOCK_STAND_MIN_SEC` NICHT anfassen**). Test: bestehende Suites grün halten.

- [ ] **Step 1:** `grep -n "refile\|superseded_by\|gps_legs\|recompute_gps_legs" app/poller.py app/database.py`
  — die durch GPS-Flüge ersetzte Refile-**Leg-Trennung** identifizieren (nicht die Flugplan-Speicherung!).
- [ ] **Step 2:** Refile erzeugt weiterhin eine `flights`-Zeile (Label-Zeitachse, Spec G) — nur die
  Leg-**Zählwirkung** entfällt (kommt jetzt aus GPS). `recompute_gps_legs` + `gps_legs`-Tabelle entfernen
  (durch `flight_cache` ersetzt) **oder** als reines Debug-Artefakt belassen — entscheiden, dokumentieren.
- [ ] **Step 3: Run** `python -m pytest tests/ -q` — **alles grün** (keine Regression).
- [ ] **Step 4: Commit** `refactor: Refile-Leg-Split + toter gps_legs-Speicher entfernt (#23)`.

---

## Task 11: Docs, Changelog v8.0.0, Deploy

- [ ] **Step 1:** `app/CHANGELOG.json` oben neuer Eintrag **v8.0.0** (Major/highlight — Kern-Wahrheit ändert
  sich, ganze Historie rückwirkend neu): „GPS-Etappen-
  Erkennung aktiv — Flüge, Ziele und Blockzeiten kommen aus GPS (Statistik, Bummel, Kutter); Flugplan nur
  noch als Label; Zwischenlandungen zählen." Docs: `docs/architecture.md` (`canonicalize_legs`,
  `collapse_same_airport`, `flight_cache`, Latch-Reconcile), `docs/api.md` (Piloten-Detail/Audit-Änderung),
  `README.md`.
- [ ] **Step 2: Run** `python -m pytest tests/ -q` — grün; `python -c "from app.version import VERSION;
  print(VERSION)"` == `8.0.0`.
- [ ] **Step 3: Deploy** Push→main → `gh run watch <id> --exit-status --interval 20` → Prod-Health
  `curl .../api/frontend-config` == `8.0.0` → Git-Tag `v8.0.0`.
- [ ] **Step 4: Commit/Tag** (Changelog-Commit erzeugt den Deploy; Tag nach Health-Check).

**⏸ Verifikation nach Deploy:** Statistik/Piloten/Bummel/Kutter konsistent (A→B→C = Zwischenlandung
sichtbar; Platzrunde = 1 Flug; „Frode" gewertet ohne Disconnect; Kutter-Lieferung via Latch trotz
takeoff_ts-Key). Prod == 8.0.0.

---

## Nicht in diesem Plan (Phase 2b)

- **Fremd-Callsign-Anzeige** im Piloten-Detail (`scored=False`, cid-Erkennung, UI-Kennzeichnung).
- **Proaktive StatSim-Track-Beschaffung je Import** (Automatik; Phase 2 nutzt den periodischen Bulk-Backfill).

## Verifikation (Self-Check des Plans)

1. `python -m pytest tests/ -v` je Task grün.
2. Spec-Abdeckung: A→Task 1/2; B/C→Task 3/4; G→Task 3 (`_assign_flightplan`); Audit/GATE→Task 5;
   Konsumenten D→Task 6–9; Reconcile c→Task 9; Semantik g→Task 6 (offene Flüge) + Task 3 (`duration`);
   Cleanup→Task 10; Release→Task 11.
3. Nach Freigabe: subagent-driven-development, pro Task frischer Implementer (Task 1/2 reine Funktionen ggf.
   Haiku/Sonnet; Task 3/9 Sonnet; Reviews Sonnet). Ledger `.superpowers/sdd/progress.md`.
