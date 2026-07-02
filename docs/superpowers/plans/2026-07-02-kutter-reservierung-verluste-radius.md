# FriesenKutter v7.5.0 — Reservierung, Verluste, Umkreis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gestartete Piloten erscheinen sofort mit Ladung (Reservierung im Ziel-Balken + Teilnehmerliste), nie angekommene Fracht geht erzählbar verloren („🌊 Kutter versunken" / „🏴‍☠️ geklaut" / „↩️ zurückgebracht"), und der Erkennungs-Radius ist pro Event konfigurierbar.

**Architecture:** Alles hängt an `compute_transport_progress` (app/database.py) — Reservierung und Teilnehmer sind reine Berechnung ohne DB-State; Verluste bekommen eine kleine Latch-Tabelle (`transport_cargo_losses`), die der 60-s-Poller-Job (`_check_transport_events`) idempotent füllt. Frontend rendert alles in `_kutterDetailBody` (index.html). Spec: `docs/superpowers/specs/2026-07-02-kutter-reservierung-verluste-radius-design.md`.

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL), pytest; Vanilla-JS-SPA.

## Global Constraints

- Version **v7.5.0** (Minor): neuer Eintrag OBEN in `app/CHANGELOG.json`, KEIN `highlight`-Flag; Git-Tag `v7.5.0` nach dem Push.
- Anzeige-Text für versunkene Fracht überall EXAKT **„🌊 Kutter versunken"** (Feed, Teilnehmerliste, Bilanz, KI-Kontext) — nie „versunken" ohne „Kutter".
- Fortschritt läuft nie rückwärts: `tonnage_kg`/`delivered` ändern sich durch Reservierung NICHT; Reservierung ist rein rechnerisch (kein DB-State).
- Gewichte (Reservierung, Tonnage, Verlust-kg) werden bei JEDER Berechnung frisch aus `aircraft_payloads` gezogen — nirgends kg snapshotten, nur `type_code` speichern.
- Neue Tabellen im Frontend IMMER in `.table-scroll`-Wrapper (stehende Mobile-Regel, CLAUDE.md).
- `radius_km`: NULL = Default `_BUMMEL_AIRPORT_RADIUS_KM` (10.0); gültige Werte 0.5–50 km, sonst HTTP 400.
- Alle Tests in `tests/test_transport.py`; volle Suite muss grün bleiben (Basis: 540 Tests).
- Verlust-Arten (`kind`): `'returned'` (Landung am Abflugplatz, KEIN Verlust), `'stolen'` (Landung an anderem Platz ≠ Ziel ≠ Start), `'sunk'` (unterwegs verschwunden / abseits jedes Platzes).
- Ein Flug ist entweder geliefert (Latch/GPS-Ankunft), zurückgebracht oder verloren — nie doppelt.

**Bestehende Bausteine (nicht neu erfinden):** `open_transport_flights` (db:2905), `transport_live_arrivals`-Latch (db:2880–2892), Co-Load-Füllung (db:3129–3156), `get_payload_map`/`transport_default_payload_kg`, `_first_pos`/`_last_pos`/`_nearest_airport`, `_TRANSPORT_MIGRATIONS` (db:335), `_LANDED_MAX_GS_KT` (Fertig-gelandet-Regel), Test-Helfer `_event`/`_add_flight`/`_add_open_flight` (tests/test_transport.py).

---

### Task 1: radius_km pro Event (DB + CRUD + Verdrahtung + Admin-Formular)

**Files:**
- Modify: `app/database.py` (DDL ~174, `_TRANSPORT_MIGRATIONS` ~335, `_TRANSPORT_EVENT_COLS` ~2536, `create_transport_event` ~2616, `_UPDATABLE_TRANSPORT_FIELDS` ~2641, `active_transport_destinations` ~2895, `check_live_arrival` ~2915, `transport_anyone_in_progress` ~2962, `compute_transport_progress` ~3027)
- Modify: `app/main.py` (`admin_create_transport_event` ~1544, `admin_update_transport_event` ~1569)
- Modify: `app/static/admin.html` (Formular ~820–831, Submit ~2018–2036, `keEdit` ~2066)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `_BUMMEL_AIRPORT_RADIUS_KM = 10.0` (db:1684), bestehende `radius_km`-Parameter.
- Produces: `transport_events.radius_km REAL` (NULL=Default); alle Radius-Funktionen lesen den Event-Radius selbst aus dem Event-Dict: Priorität `radius_km-Parameter > event["radius_km"] > _BUMMEL_AIRPORT_RADIUS_KM`. `active_transport_destinations` liefert `{"id", "destination", "radius_km"}`.

- [ ] **Step 1: Fehlschlagende Tests schreiben** (in `tests/test_transport.py`, neue Klasse; Helfer `_event`/`_make_conn` existieren — `_event` ggf. um `radius_km`-Durchreichung erweitern):

```python
class TestEventRadius:
    def test_radius_roundtrip_and_default(self):
        conn = _make_conn()
        ev = _event(conn, radius_km=3.0)          # _event reicht radius_km an create_transport_event durch
        assert ev["radius_km"] == 3.0
        ev2 = _event(conn)                        # ohne Angabe → NULL
        assert ev2["radius_km"] is None

    def test_check_live_arrival_uses_event_radius(self):
        """3-km-Event latcht bei ~4 km Abstand NICHT; ohne radius_km (Default 10) schon.
        Fixtures analog TestCheckLiveArrival (~Z. 491): EDXH-Koordinaten + Offset-Position."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        lat, lon = icao_to_coords("EDXH")
        pos4km = (lat + 0.036, lon)               # ~4 km nördlich
        ev_small = _event(conn, destination="EDXH", radius_km=3.0)
        ev_default = _event(conn, destination="EDXH")
        events = active_transport_destinations(conn, ev_small["dtstart"])
        check_live_arrival(conn, 111, "2026-07-02T18:00:00Z", pos4km[0], pos4km[1], 0.0, events)
        latched_small = get_transport_live_arrivals(conn, ev_small["id"])
        latched_default = get_transport_live_arrivals(conn, ev_default["id"])
        assert (111, "2026-07-02T18:00:00Z") not in latched_small
        assert (111, "2026-07-02T18:00:00Z") in latched_default

    def test_compute_uses_event_radius_from_dict(self):
        """compute_transport_progress ohne expliziten radius_km-Parameter nutzt event['radius_km']."""
        conn = _make_conn()
        ev = _event(conn, radius_km=3.0)
        # Flug mit GPS-Erstposition 4 km neben EDWG: mit 3-km-Radius greift die GPS-Korrektur
        # NICHT (Fallback Flugplan-DEP bleibt) — Detailassertions je nach vorhandenen Fixtures;
        # Minimalfall: Funktion läuft ohne Parameter durch und liefert das route-Feld.
        result = compute_transport_progress(conn, ev, ev["dtend"])
        assert "route" in result
```

- [ ] **Step 2: Tests laufen lassen** — `python -m pytest tests/test_transport.py::TestEventRadius -v` → FAIL (Spalte/Verhalten fehlt).

- [ ] **Step 3: Implementieren**

`app/database.py`:
1. DDL (~Z. 188, vor `created_at`): neue Zeile `radius_km       REAL,                 -- Erkennungs-Umkreis km; NULL = Default 10` im CREATE von `transport_events`.
2. `_TRANSPORT_MIGRATIONS` ergänzen: `"ALTER TABLE transport_events ADD COLUMN radius_km REAL",` (Kommentar: Umkreis pro Event, kurze Strecken wie Wangerooge↔Harle).
3. `_TRANSPORT_EVENT_COLS`: `radius_km` in die Spaltenliste aufnehmen.
4. `create_transport_event`: Keyword-Param `radius_km: float | None = None`, in INSERT-Spalten/Values aufnehmen.
5. `_UPDATABLE_TRANSPORT_FIELDS`: `"radius_km"` ergänzen.
6. `active_transport_destinations`: SELECT + Rückgabe um `radius_km` erweitern:

```python
    rows = conn.execute(
        "SELECT id, destination, radius_km FROM transport_events "
        "WHERE dtstart <= ? AND dtend >= ? AND destination IS NOT NULL AND destination != ''",
        (now, now),
    ).fetchall()
    return [{"id": r["id"], "destination": r["destination"], "radius_km": r["radius_km"]} for r in rows]
```

7. `check_live_arrival`: Radius je Event im Loop (Docstring anpassen):

```python
    for ev in events:
        dest = normalize_type_code(ev.get("destination"))
        coords = icao_to_coords(dest) if dest else None
        if not coords:
            continue
        radius = radius_km or ev.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM
        if haversine(latitude, longitude, coords[0], coords[1]) <= radius:
            set_transport_live_arrival(conn, cid, logon_time, ev["id"], now)
```
(die Zeile `radius = radius_km or _BUMMEL_AIRPORT_RADIUS_KM` vor dem Loop entfällt)

8. `compute_transport_progress` (~Z. 3027) und `transport_anyone_in_progress` (~Z. 2984): jeweils
   `radius = radius_km or event.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM` — Poller/Endpoints brauchen dann KEINE Änderung.

`app/main.py` — Validierungshelfer (bei den anderen `_`-Helfern nahe `_normalize_route` platzieren) + beide Endpoints:

```python
def _parse_radius_km(body: dict):
    """radius_km aus dem Request-Body: fehlt → 'keine Änderung'; ''/None → NULL; sonst 0.5–50."""
    if "radius_km" not in body:
        return ...  # Ellipsis als Sentinel „nicht übergeben"
    v = body.get("radius_km")
    if v in (None, ""):
        return None
    try:
        r = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="radius_km muss eine Zahl sein")
    if not (0.5 <= r <= 50):
        raise HTTPException(status_code=400, detail="radius_km muss zwischen 0.5 und 50 liegen")
    return r
```
- `admin_create_transport_event`: `radius = _parse_radius_km(body)` → `create_transport_event(..., radius_km=None if radius is ... else radius)`.
- `admin_update_transport_event`: `radius = _parse_radius_km(body)`; `if radius is not ...: fields["radius_km"] = radius`.

`app/static/admin.html`:
- Formular nach dem `ke-dest`-Feld (~Z. 823):

```html
                  <div class="form-group">
                    <label for="ke-radius">Umkreis (km, leer = 10)</label>
                    <input type="number" id="ke-radius" min="0.5" max="50" step="0.5" placeholder="10" />
                  </div>
```
- Submit-Handler (~Z. 2026): nach dem `body`-Aufbau `const radius = document.getElementById('ke-radius').value; body.radius_km = radius ? parseFloat(radius) : null;`
- `keEdit` (~Z. 2073): `document.getElementById('ke-radius').value = ev.radius_km ?? '';`
- Event-Kachel-Anzeige (~Z. 2057): hinter `Ziel …` ergänzen: `+ (ev.radius_km ? ' · Umkreis ' + ev.radius_km + ' km' : '')`.

- [ ] **Step 4: Tests laufen lassen** — `python -m pytest tests/test_transport.py -v` → alle grün (inkl. Bestand).
- [ ] **Step 5: Commit** — `git add app/database.py app/main.py app/static/admin.html tests/test_transport.py && git commit -m "feat(kutter): Erkennungs-Umkreis pro Event konfigurierbar (radius_km)"`

---

### Task 2: Fracht-Reservierung im Backend

**Files:**
- Modify: `app/database.py` (`compute_transport_progress`: Open-Flights-Loop ~3079–3107, Füll-Pass ~3121–3175, Rückgabe ~3180)
- Modify: `app/main.py` (`_transport_event_meta` ~1482)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `payload_map`/`default_kg` (bereits geladen ~3028), Co-Load-Muster (~3129).
- Produces: Feed-Einträge offener Flüge tragen `"in_air": True` und (ohne Latch) `"reserved_kg": <payload>`; geschlossene Einträge `"in_air": False`, `"reserved_kg": 0.0`. `cargo_out[i]["reserved_kg"]`, Ergebnis-Key `"reserved_total_kg"` (Summe der ins Manifest passenden Reservierungen). `_transport_event_meta` reicht `reserved_total_kg` durch.

- [ ] **Step 1: Fehlschlagende Tests schreiben**:

```python
class TestReservation:
    def test_open_flight_reserves_payload(self):
        """Offener Flug Richtung Ziel ohne Latch: 0 kg geliefert, aber reserviert."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)  # payload 292
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 200)
        assert f["in_air"] is True and f["loaded"] is False
        assert f["tonnage_kg"] == 0.0 and f["reserved_kg"] == 292.0
        assert p["reserved_total_kg"] == 292.0
        assert p["cargo"][0]["reserved_kg"] == 292.0
        assert p["cargo"][0]["delivered_kg"] == 0.0      # Fortschritt unverändert

    def test_reservation_capped_by_remaining_target(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 100.0}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["cargo"][0]["reserved_kg"] == 100.0     # gekappt auf offenen Bedarf
        assert p["reserved_total_kg"] == 100.0
        assert p["flights"][0]["reserved_kg"] == 292.0   # was er trägt, bleibt volle Zuladung

    def test_reservation_respects_per_flight_cap_and_coload(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0},
            {"name": "Friesentee", "target_kg": 500.0},
        ])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["cargo"][0]["reserved_kg"] == 100.0     # Kappung pro Flug
        assert p["cargo"][1]["reserved_kg"] == 192.0     # Co-Load-Rest

    def test_latch_converts_reservation_to_delivered(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        set_transport_live_arrival(conn, 200, "2026-07-02T18:05:00Z", ev["id"], "2026-07-02T18:30:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 200)
        assert f["loaded"] is True and f["tonnage_kg"] == 292.0 and f["reserved_kg"] == 0.0
        assert p["cargo"][0]["delivered_kg"] == 292.0
        assert p["reserved_total_kg"] == 0.0             # kein Doppelzählen
```
(`upsert_payload`-Signatur ggf. an die echte anpassen — existiert bereits in database.py.)

- [ ] **Step 2: Tests laufen lassen** → FAIL (`in_air`/`reserved_kg` fehlen).

- [ ] **Step 3: Implementieren** in `compute_transport_progress`:

1. Geschlossene Einträge (~Z. 3063): Dict um `"in_air": False, "reserved_kg": 0.0` ergänzen.
2. Offene Einträge (~Z. 3094): vor dem `network.append`:

```python
        tonnage = round(payload_map.get(type_code, default_kg), 1) if loaded else 0.0
        reserved = 0.0 if loaded else round(payload_map.get(type_code, default_kg), 1)
        if not loaded and type_code and type_code not in payload_map:
            unmapped.add(type_code)   # reservierte Typen dem Admin ebenfalls melden
```
   und im Dict `"in_air": True, "reserved_kg": reserved,` (bestehende `if loaded and …`-unmapped-Zeile bleibt).
3. Reservierungs-Füll-Pass NACH der bestehenden Co-Load-Schleife (~nach Z. 3156) — dieselbe Logik, eigener Topf `reserved_alloc`, damit `delivered` unangetastet bleibt:

```python
    # Reservierungen (offene Flüge Richtung Ziel, noch ohne Latch) in die Rest-Kapazität
    # verteilen — gleiche Co-Load-Regeln, aber getrennt von `delivered`: der Fortschritt
    # läuft nie rückwärts, die Reservierung verschwindet mit dem Flug.
    reserved_alloc = [0.0] * len(cargo)
    for q in network:
        r = q.get("reserved_kg") or 0.0
        if q["loaded"] or r <= 1e-9:
            continue
        remaining = r
        for i, c in enumerate(cargo):
            if remaining <= 1e-9:
                break
            space = cargo_targets[i] - delivered[i] - reserved_alloc[i]
            if space <= 1e-9:
                continue
            cap = c.get("per_flight_max_kg")
            cap = cap if (cap is not None and cap > 0) else _INF
            add = min(remaining, cap, space)
            if add <= 1e-9:
                continue
            reserved_alloc[i] += add
            remaining -= add
```
4. `cargo_out`-Einträge um `"reserved_kg": round(reserved_alloc[i], 1)` ergänzen; Rückgabe-Dict um `"reserved_total_kg": round(sum(reserved_alloc), 1)`.
5. `app/main.py` `_transport_event_meta`: `"reserved_total_kg": progress.get("reserved_total_kg", 0.0),` ergänzen.
6. Docstring von `compute_transport_progress` um die Reservierung ergänzen (2–3 Sätze: ab Sichtbarkeit der Verbindung, rein rechnerisch, kg live aus `aircraft_payloads`).

- [ ] **Step 4: Tests laufen lassen** — volle Datei grün: `python -m pytest tests/test_transport.py -v`.
- [ ] **Step 5: Commit** — `git commit -m "feat(kutter): gestartete Piloten reservieren ihre Zuladung im Manifest"`

---

### Task 3: Fracht-Verluste (Erkennung, Persistenz, Feed-Integration)

**Files:**
- Modify: `app/geo.py` (neue Funktion am Ende)
- Modify: `app/database.py` (DDL neue Tabelle nach `transport_live_arrivals`-CREATE, neue Funktionen nach `get_transport_live_arrivals` ~2892, `compute_transport_progress`-Integration)
- Modify: `app/poller.py` (`_check_transport_events` ~1060)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `_LANDED_MAX_GS_KT` (existiert, Fertig-gelandet-Regel), `canonicalize_flights`, `_first_pos`, `_nearest_airport`, `_BUMMEL_EARLY_START_LOOKBACK_H`, `get_transport_live_arrivals`.
- Produces: `geo.nearest_airport_icao(lat, lon, max_km) -> str | None`; Tabelle `transport_cargo_losses`; `record_transport_loss(conn, event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at)`; `get_transport_losses(conn, event_id) -> list[dict]`; `detect_transport_losses(conn, event, *, callsign_prefix="FRS") -> int`; compute-Ergebnis: Feed-Einträge mit `"loss_kind"` (`'returned'|'stolen'|'sunk'`, sonst fehlend/None) und `"lost_kg"`, Ergebnis-Keys `"losses"` (Liste) + `"lost_total_kg"`.

- [ ] **Step 1: Fehlschlagende Tests schreiben** (Positionen via bestehendem Positions-Helfer der Testdatei einfügen — es gibt dort bereits INSERTs in `position_history`; ggf. kleinen Helfer `_add_pos(conn, cid, ts, lat, lon, gs)` anlegen):

```python
class TestCargoLosses:
    def _flown_flight(self, conn, cid, logon, *, end_lat, end_lon, end_gs, arrival="EDXH"):
        """Geschlossener Flug ab EDWG Richtung Ziel mit Bewegungs-Track und letzter Position."""
        from app.geo import icao_to_coords
        dlat, dlon = icao_to_coords("EDWG")
        _add_flight(conn, cid, "EDWG", arrival, "C172", logon, duration_min=30)
        _add_pos(conn, cid, logon, dlat, dlon, 0)                      # Start am Platz
        _add_pos(conn, cid, _shift(logon, 10), dlat + 0.2, dlon, 90)   # geflogen
        _add_pos(conn, cid, _shift(logon, 30), end_lat, end_lon, end_gs)

    def test_sunk_when_vanished_airborne(self):
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        self._flown_flight(conn, 300, "2026-07-02T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        n = detect_transport_losses(conn, ev)
        assert n == 1
        losses = get_transport_losses(conn, ev["id"])
        assert losses[0]["kind"] == "sunk"
        p = compute_transport_progress(conn, ev, "2026-07-02T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 300)
        assert f["loss_kind"] == "sunk" and f["loaded"] is False
        assert p["lost_total_kg"] == 292.0
        assert p["cargo"][0]["delivered_kg"] == 0.0      # Menge bleibt offen

    def test_stolen_when_landed_elsewhere(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        wlat, wlon = icao_to_coords("EDWY")                 # Norderney — nicht auf der Route
        self._flown_flight(conn, 301, "2026-07-02T18:05:00Z", end_lat=wlat, end_lon=wlon, end_gs=0)
        detect_transport_losses(conn, ev)
        assert get_transport_losses(conn, ev["id"])[0]["kind"] == "stolen"
        p = compute_transport_progress(conn, ev, "2026-07-02T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 301)
        assert f["loss_kind"] == "stolen"                   # synthetischer Feed-Eintrag
        assert p["lost_total_kg"] == 292.0

    def test_returned_home_is_no_loss(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        dlat, dlon = icao_to_coords("EDWG")
        self._flown_flight(conn, 302, "2026-07-02T18:05:00Z", end_lat=dlat, end_lon=dlon, end_gs=0, arrival="EDWG")
        detect_transport_losses(conn, ev)
        assert get_transport_losses(conn, ev["id"])[0]["kind"] == "returned"
        p = compute_transport_progress(conn, ev, "2026-07-02T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 302)
        assert f["loss_kind"] == "returned"
        assert p["lost_total_kg"] == 0.0                    # zurückgebracht ≠ verloren

    def test_detection_is_idempotent_and_skips_delivered(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        alat, alon = icao_to_coords("EDXH")
        self._flown_flight(conn, 303, "2026-07-02T18:05:00Z", end_lat=alat, end_lon=alon, end_gs=0)
        assert detect_transport_losses(conn, ev) == 0       # am Ziel gelandet → geliefert
        self._flown_flight(conn, 304, "2026-07-02T18:20:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        assert detect_transport_losses(conn, ev) == 1
        assert detect_transport_losses(conn, ev) == 0       # idempotent
```

- [ ] **Step 2: Tests laufen lassen** → FAIL (Funktionen fehlen).

- [ ] **Step 3: Implementieren**

`app/geo.py` (am Dateiende):

```python
def nearest_airport_icao(lat: float, lon: float, max_km: float) -> str | None:
    """ICAO des nächstgelegenen Flugplatzes im Umkreis ``max_km`` — sonst None.

    Linearer Scan über die airportsdata-Datenbank (~28k Einträge) mit grobem
    Bounding-Box-Vorfilter; gedacht für seltene Ereignisse (Verlust-Klassifikation),
    nicht für den Poll-Takt.
    """
    best, best_d = None, max_km
    box = max_km / 111.0 + 0.01  # Grad-Näherung
    for icao, a in _airports_icao().items():
        alat, alon = a.get("lat"), a.get("lon")
        if alat is None or alon is None or abs(alat - lat) > box:
            continue
        d = haversine(lat, lon, alat, alon)
        if d <= best_d:
            best, best_d = icao, d
    return best
```

`app/database.py` — DDL (direkt nach dem `transport_live_arrivals`-CREATE im `_DDL`-Block):

```sql
CREATE TABLE IF NOT EXISTS transport_cargo_losses (
    event_id   INTEGER NOT NULL,          -- REFERENCES transport_events(id)
    cid        INTEGER NOT NULL,
    logon_time TEXT NOT NULL,             -- Session des verlorenen Flugs (flight_key = cid:logon)
    kind       TEXT NOT NULL,             -- 'returned' | 'stolen' | 'sunk'
    type_code  TEXT,                      -- Muster; kg werden IMMER live aus aircraft_payloads gerechnet
    callsign   TEXT,
    dep        TEXT,                      -- Abflugplatz (fürs Feed-Rendering)
    end_icao   TEXT,                      -- Landeplatz bei 'returned'/'stolen'; NULL bei 'sunk'
    lost_at    TEXT,
    PRIMARY KEY(event_id, cid, logon_time)
);
```

Funktionen (nach `get_transport_live_arrivals`):

```python
def record_transport_loss(conn, event_id, cid, logon_time, kind, type_code,
                          callsign, dep, end_icao, lost_at) -> None:
    """Fracht-Verlust latchen (idempotent via PK). kind: 'returned'|'stolen'|'sunk'."""
    conn.execute(
        "INSERT OR IGNORE INTO transport_cargo_losses "
        "(event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at),
    )


def get_transport_losses(conn, event_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, cid, logon_time, kind, type_code, callsign, dep, end_icao, lost_at "
        "FROM transport_cargo_losses WHERE event_id = ? ORDER BY lost_at",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def detect_transport_losses(conn, event: dict, *, callsign_prefix: str = "FRS") -> int:
    """Neue Fracht-Verluste eines Events erkennen und latchen (idempotent, Poll-Takt-tauglich).

    Kandidat = abgeschlossener Flug, der Richtung Ziel gestartet war (GPS-Erstposition auf der
    Strecke, Fallback Flugplan-DEP; dep ≠ destination), ohne Live-Ankunfts-Latch und ohne
    GPS-Ankunft am Ziel. Klassifikation per letzter Position:
    am Boden am Abflugplatz → 'returned' · am Boden an anderem Platz → 'stolen' ·
    sonst (in der Luft verschwunden / abseits jedes Platzes) → 'sunk' (Kutter versunken).
    """
    from app.geo import icao_to_coords, nearest_airport_icao
    dest = normalize_type_code(event.get("destination"))
    route_set = {c for c in (normalize_type_code(x) for x in (event.get("route") or "").split(",")) if c}
    if not dest or not route_set:
        return 0
    radius = event.get("radius_km") or _BUMMEL_AIRPORT_RADIUS_KM
    coords_map = {icao: icao_to_coords(icao) for icao in route_set}
    start = event.get("dtstart") or ""
    now = _now_utc()
    latched = get_transport_live_arrivals(conn, int(event["id"]))
    existing = {(l["cid"], l["logon_time"]) for l in get_transport_losses(conn, int(event["id"]))}
    load_start = _shift_iso(start, hours=-_BUMMEL_EARLY_START_LOOKBACK_H)
    new = 0
    for f in canonicalize_flights(conn, start=load_start, end=now, callsign_prefix=callsign_prefix):
        cid, lo = f.get("cid"), f.get("logon_time") or ""
        lf = f.get("logoff_time") or ""
        if cid is None or not lf or lf < start:
            continue
        if (cid, lo) in latched or (cid, lo) in existing:
            continue
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("departure"))
        if dep not in route_set or dep == dest:
            continue  # war nie mit Fracht Richtung Ziel unterwegs
        arr = _nearest_airport(coords_map, _last_pos(conn, int(cid), lo, lf), radius)
        if arr == dest:
            continue  # GPS-Ankunft am Ziel → geliefert (compute zählt das als loaded)
        row = conn.execute(
            "SELECT latitude, longitude, groundspeed FROM position_history "
            "WHERE cid = ? AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (cid, lo, lf),
        ).fetchone()
        kind, end_icao = "sunk", None
        if row is not None and row["groundspeed"] is not None \
                and row["groundspeed"] <= _LANDED_MAX_GS_KT:
            end_icao = nearest_airport_icao(row["latitude"], row["longitude"], radius)
            if end_icao == dep:
                kind = "returned"
            elif end_icao:
                kind = "stolen"
        type_code = normalize_type_code(f.get("aircraft_icao")) or normalize_type_code(f.get("aircraft"))
        record_transport_loss(conn, int(event["id"]), int(cid), lo, kind, type_code,
                              f.get("callsign") or "", dep, end_icao, now)
        new += 1
    return new
```

`compute_transport_progress`-Integration (nach dem Open-Flights-Loop ~Z. 3107, VOR `network.sort`):

```python
    # Fracht-Verluste anheften: Feed-Zeilen bekommen loss_kind; Verlust-Flüge, die der
    # Strecken-Filter oben verworfen hat (woanders gelandet, dep==arr), erscheinen als
    # eigener Eintrag. kg IMMER live aus aircraft_payloads (type_code, kein Snapshot).
    losses = get_transport_losses(conn, int(event["id"]))
    seen_keys = {q["flight_key"] for q in network}
    loss_by_key: dict[str, dict] = {f"{l['cid']}:{l['logon_time']}": l for l in losses}
    for q in network:
        l = loss_by_key.get(q["flight_key"])
        if l and not q["loaded"]:
            q["loss_kind"] = l["kind"]
            q["lost_kg"] = round(payload_map.get(normalize_type_code(l.get("type_code")), default_kg), 1) \
                if l["kind"] in ("stolen", "sunk") else 0.0
    for key, l in loss_by_key.items():
        if key in seen_keys:
            continue
        tc = normalize_type_code(l.get("type_code"))
        lost = round(payload_map.get(tc, default_kg), 1) if l["kind"] in ("stolen", "sunk") else 0.0
        network.append({
            "dep_time": l["logon_time"], "cid": l["cid"], "callsign": l.get("callsign") or "",
            "aircraft": tc, "dep": l.get("dep") or "", "arr": l.get("end_icao") or "—",
            "tonnage_kg": 0.0, "loaded": False, "in_air": False, "reserved_kg": 0.0,
            "flight_key": key, "distance_nm": 0, "block_min": 0,
            "loss_kind": l["kind"], "lost_kg": lost,
        })
```
Rückgabe-Dict ergänzen:

```python
        "losses": [q for q in network if q.get("loss_kind")],
        "lost_total_kg": round(sum(q.get("lost_kg") or 0.0 for q in network), 1),
```
(Hinweis: Einträge ohne Verlust haben kein `loss_kind`/`lost_kg` — das Frontend prüft mit `f.loss_kind`. Ein Eintrag, der geliefert ist (`loaded=True`), bekommt NIE ein `loss_kind` — geliefert gewinnt.)

`app/poller.py` `_check_transport_events`: Import um `detect_transport_losses` erweitern und im Event-Loop VOR dem `compute_transport_progress`-Aufruf (~Z. 1067):

```python
                    if ev.get("destination"):
                        detect_transport_losses(conn, ev, callsign_prefix=self.callsign_prefix)
```

- [ ] **Step 4: Tests laufen lassen** — volle Suite: `python -m pytest tests/ -v` → grün.
- [ ] **Step 5: Commit** — `git commit -m "feat(kutter): Fracht-Verluste — Kutter versunken, geklaut, zurückgebracht"`

---

### Task 4: Teilnehmerliste + KI-Kontext für Verluste

**Files:**
- Modify: `app/database.py` (`compute_transport_progress` Teilnehmer-Aggregation; `flight_quip_context` ~2793; `event_summary_context` ~2833)
- Modify: `app/llm.py` (`_QUIP_SYSTEM`-Prompt)
- Modify: `app/poller.py` (`quip_jobs`-Sammlung ~1104)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: Feed-Einträge mit `in_air`/`reserved_kg`/`loss_kind`/`lost_kg` (Task 2+3); `open_transport_flights`.
- Produces: compute-Ergebnis-Key `"participants"`: Liste `{cid, name, aircraft, flights, delivered_kg, reserved_kg, lost_kg, status}`, `status ∈ {"flying","arrived","returning","done"}`, sortiert nach `delivered_kg` absteigend, dann Name. `flight_quip_context` liefert zusätzlich `"verlust"` (String oder None); `event_summary_context` zusätzlich `"verluste"` (Liste Strings) + `"lost_total_kg"`.

- [ ] **Step 1: Fehlschlagende Tests schreiben**:

```python
class TestParticipants:
    def test_statuses_and_sums(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        # Pilot 400: geliefert (geschlossen am Ziel) + gerade wieder unterwegs (offen, Richtung Ziel)
        _add_flight(conn, 400, "EDWG", "EDXH", "C172", "2026-07-02T18:00:00Z", duration_min=25)
        _add_open_flight(conn, 400, "EDWG", "EDXH", "C172", "2026-07-02T19:00:00Z")
        # Pilot 401: offener Rückflug ab Ziel (dep == destination) → returning, keine Reservierung
        _add_open_flight(conn, 401, "EDXH", "EDWG", "C172", "2026-07-02T19:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[400]["status"] == "flying" and parts[400]["reserved_kg"] == 292.0
        assert parts[400]["delivered_kg"] == 292.0 and parts[400]["flights"] == 2
        assert parts[401]["status"] == "returning" and parts[401]["reserved_kg"] == 0.0

    def test_arrived_status_with_latch(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        _add_open_flight(conn, 402, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        set_transport_live_arrival(conn, 402, "2026-07-02T18:05:00Z", ev["id"], "2026-07-02T18:30:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["participants"][0]["status"] == "arrived"


class TestLossQuipContext:
    def test_flight_context_carries_kutter_versunken(self):
        f = {"cid": 1, "name": "Klaus Test", "callsign": "FRS22", "dep": "EDWG", "arr": "—",
             "loaded": False, "loss_kind": "sunk", "lost_kg": 292.0,
             "distance_nm": 0, "block_min": 0, "cargo_lines": []}
        ctx = flight_quip_context(f, {"flights": [f]})
        assert "Kutter versunken" in ctx["verlust"]

    def test_summary_context_lists_losses(self):
        prog = {"flights": [], "cargo": [], "route": ["EDWG", "EDXH"], "destination": "EDXH",
                "total_kg": 0, "loaded_count": 0, "lost_total_kg": 292.0,
                "losses": [{"name": "Klaus Test", "callsign": "FRS22", "loss_kind": "sunk",
                            "lost_kg": 292.0, "cid": 1}]}
        ctx = event_summary_context({"name": "Test"}, prog)
        assert ctx["lost_total_kg"] == 292.0 and any("Kutter versunken" in v for v in ctx["verluste"])
```

- [ ] **Step 2: Tests laufen lassen** → FAIL.

- [ ] **Step 3: Implementieren**

1. `compute_transport_progress`: Im Open-Flights-Loop den bisherigen Skip `if dep not in route_set or dep == dest: continue` erweitern — Rückflieger merken:

```python
        if dep not in route_set or dep == dest:
            if dep == dest:
                returning_cids.add(int(cid))
            continue
```
   (`returning_cids: set[int] = set()` vor dem Loop initialisieren.)
2. Teilnehmer-Aggregation nach den Füll-Pässen (vor der Rückgabe):

```python
    # Teilnehmerliste (Bummel-Analogie): eine Zeile pro Pilot mit Summen + Live-Status.
    parts: dict[int, dict] = {}
    for q in network:
        p = parts.setdefault(int(q["cid"]), {
            "cid": int(q["cid"]), "name": q.get("name") or "", "aircraft": q.get("aircraft") or "",
            "flights": 0, "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "status": "done",
        })
        p["flights"] += 1
        if q.get("aircraft"):
            p["aircraft"] = q["aircraft"]
        if q.get("name"):
            p["name"] = q["name"]
        p["delivered_kg"] += q["tonnage_kg"]
        p["lost_kg"] += q.get("lost_kg") or 0.0
        if q.get("in_air"):
            p["status"] = "arrived" if q["loaded"] else "flying"
            if not q["loaded"]:
                p["reserved_kg"] += q.get("reserved_kg") or 0.0
    for rc in returning_cids:
        if rc in parts and parts[rc]["status"] == "done":
            parts[rc]["status"] = "returning"
        elif rc not in parts:
            parts[rc] = {"cid": rc, "name": names.get(rc, ""), "aircraft": "", "flights": 0,
                         "delivered_kg": 0.0, "reserved_kg": 0.0, "lost_kg": 0.0, "status": "returning"}
    participants = sorted(parts.values(), key=lambda x: (-x["delivered_kg"], x["name"]))
    for p in participants:
        p["delivered_kg"] = round(p["delivered_kg"], 1)
        p["reserved_kg"] = round(p["reserved_kg"], 1)
        p["lost_kg"] = round(p["lost_kg"], 1)
```
   Rückgabe: `"participants": participants,`. (Die Namens-Abfrage `names` muss VOR der Aggregation stehen — sie steht bereits vor den Füll-Pässen; `returning_cids` in die `cids`-Menge der Namens-Abfrage aufnehmen: `cids = {q["cid"] for q in network} | returning_cids`.)
3. `flight_quip_context`: nach dem bestehenden Kontextaufbau ergänzen:

```python
    loss_kind = flight.get("loss_kind")
    verlust = None
    if loss_kind == "sunk":
        verlust = f"Kutter versunken — {round(flight.get('lost_kg') or 0)} kg Fracht verloren"
    elif loss_kind == "stolen":
        verlust = (f"am falschen Ort gelandet ({flight.get('arr')}) — "
                   f"{round(flight.get('lost_kg') or 0)} kg Fracht geklaut")
    elif loss_kind == "returned":
        verlust = "umgedreht und Fracht heil zurückgebracht"
```
   und `"verlust": verlust` ins Rückgabe-Dict.
4. `event_summary_context`: ergänzen:

```python
        "lost_total_kg": progress.get("lost_total_kg", 0.0),
        "verluste": [
            (f"{(l.get('name') or l.get('callsign') or '?').split()[0]}: "
             + ("Kutter versunken" if l.get("loss_kind") == "sunk"
                else "Fracht geklaut" if l.get("loss_kind") == "stolen"
                else "Fracht zurückgebracht")
             + f" ({round(l.get('lost_kg') or 0)} kg)")
            for l in progress.get("losses", [])
        ],
```
5. `app/llm.py` `_QUIP_SYSTEM`: eine Zeile ergänzen (Wortlaut sinngemäß, an den bestehenden Stil anpassen): *„Steht im Kontext ein 'verlust': mach dich gutmütig darüber lustig. Ein versunkener Kutter heißt IMMER 'Kutter versunken' — nie der Pilot, immer der Kutter geht unter."*
6. `app/poller.py` (~Z. 1104): Verlust-Flüge bekommen ebenfalls Sprüche:

```python
                        for f in progress["flights"]:
                            if (f.get("loaded") or f.get("loss_kind") in ("stolen", "sunk")) \
                                    and not f.get("quip"):
                                quip_jobs.append((ev["id"], f["flight_key"], flight_quip_context(f, progress)))
```

- [ ] **Step 4: Tests laufen lassen** — volle Suite grün.
- [ ] **Step 5: Commit** — `git commit -m "feat(kutter): Teilnehmerliste mit Live-Status + Verlust-Spott im KI-Kontext"`

---

### Task 5: Frontend — Balken-Segment, Header, Teilnehmerliste, Feed-Status

**Files:**
- Modify: `app/static/index.html` (CSS ~387–397; `_kCargoLabel` ~4290; `_kutterDetailBody` ~4304)

**Interfaces:**
- Consumes: API-Felder aus Task 2–4: `flights[].in_air/reserved_kg/loss_kind/lost_kg`, `cargo[].reserved_kg`, `reserved_total_kg`, `lost_total_kg`, `participants`.
- Produces: reine Anzeige; keine neuen JS-Schnittstellen.

- [ ] **Step 1: CSS ergänzen** (im Block bei ~Z. 387):

```css
    .kutter-seg > i.kseg-res { opacity: .5; background-image: repeating-linear-gradient(45deg, transparent 0 4px, rgba(255,255,255,.35) 4px 8px); }
    .kutter-feed td.kf-res { color: #9fc9e8; text-align: right; font-style: italic; }
    .kutter-loss { color: #e8a9a0; }
```

- [ ] **Step 2: `_kutterDetailBody` umbauen** — kompletter neuer Funktions-Body (ersetzt Z. 4304–4337; `_kLossLabel` neu davor):

```javascript
function _kLossLabel(kind) {
  return kind === 'sunk' ? '🌊 Kutter versunken'
       : kind === 'stolen' ? '🏴‍☠️ geklaut'
       : kind === 'returned' ? '↩️ zurückgebracht' : '';
}

function _kutterDetailBody(d) {
  const summary = d.summary_quip
    ? '<div class="kutter-summary">🦐 ' + _kesc(d.summary_quip) + '</div>' : '';
  let bar = '';
  if (d.cargo && d.cargo.length) {
    const totalTarget = d.cargo.reduce((s, c) => s + c.target_kg, 0) || 1;
    const segs = d.cargo.map((c, i) => {
      const pct = Math.min(100, c.pct);
      const resPct = c.target_kg > 0 ? Math.min(100 - pct, 100 * (c.reserved_kg || 0) / c.target_kg) : 0;
      const res = resPct > 0
        ? '<i class="kseg-res" style="left:' + pct.toFixed(1) + '%;width:' + resPct.toFixed(1)
          + '%;background-color:' + _kColor(i) + '"></i>' : '';
      return '<div class="kutter-seg" style="width:' + (100 * c.target_kg / totalTarget).toFixed(2)
        + '%"><i style="width:' + pct.toFixed(1) + '%;background:' + _kColor(i) + '"></i>' + res + '</div>';
    }).join('');
    const legend = d.cargo.map((c, i) => {
      const mark = c.emoji ? c.emoji + ' '
        : '<span class="kl-dot" style="background:' + _kColor(i) + '"></span>';
      const res = (c.reserved_kg || 0) > 0 ? ' (+' + _kfmtT(c.reserved_kg) + ' ✈️)' : '';
      return '<span>' + mark + _kesc(c.name) + ' ' + _kfmtT(c.delivered_kg) + ' / ' + _kfmtT(c.target_kg) + res + '</span>';
    }).join('');
    bar = '<div class="kutter-bar">' + segs + '</div><div class="kutter-legend">' + legend + '</div>';
  }
  const goal = d.target_kg ? ' / ' + _kfmtT(d.target_kg) : '';
  const pct = d.progress_pct != null ? ' · ' + Math.min(100, Math.round(d.progress_pct)) + '%' : '';
  const open = d.target_kg ? Math.max(0, d.target_kg - d.total_kg) : null;
  const inAir = d.reserved_total_kg || 0;
  const openTxt = open != null
    ? ' — offen: ' + _kfmtT(open) + (inAir > 0 ? ', davon ' + _kfmtT(inAir) + ' unterwegs ✈️' : '') : '';
  const lostTxt = (d.lost_total_kg || 0) > 0
    ? ' <span class="kutter-loss">💀 ' + _kfmtT(d.lost_total_kg) + ' verloren</span>' : '';
  const header = '<div class="kutter-total">📦 ' + _kfmtT(d.total_kg) + goal + pct
    + ' — ' + (d.loaded_count || 0) + ' Frachtflüge (' + (d.flight_count || 0) + ' gesamt)'
    + openTxt + lostTxt + '</div>';
  let parts = '';
  if (d.participants && d.participants.length) {
    const prow = d.participants.map(p => {
      const st = p.status === 'flying' ? '✈️ unterwegs mit ' + _kfmtT(p.reserved_kg)
        : p.status === 'arrived' ? '✅ angekommen'
        : p.status === 'returning' ? '↩️ Rückflug'
        : 'fertig';
      const lost = (p.lost_kg || 0) > 0
        ? ' <span class="kutter-loss">💀 ' + _kfmtT(p.lost_kg) + '</span>' : '';
      return '<tr><td>' + _kesc(p.name || ('CID ' + p.cid)) + '</td><td class="mono">' + _kesc(p.aircraft || '—')
        + '</td><td class="mono">' + p.flights + '</td><td class="kf-kg">' + _kfmtT(p.delivered_kg)
        + '</td><td>' + st + lost + '</td></tr>';
    }).join('');
    parts = '<div class="table-scroll"><table class="kutter-feed"><thead><tr><th>Pilot</th><th>Muster</th>'
      + '<th>Flüge</th><th>geliefert</th><th>Status</th></tr></thead><tbody>' + prow + '</tbody></table></div>';
  }
  const rows = (d.flights || []).map(f => {
    const t = (f.dep_time || '').slice(11, 16);
    const kg = f.loaded ? '<td class="kf-kg">' + Math.round(f.tonnage_kg) + ' kg</td>'
      : f.loss_kind ? '<td class="kf-empty kutter-loss">' + (f.lost_kg ? Math.round(f.lost_kg) + ' kg' : '—') + '</td>'
      : f.in_air ? '<td class="kf-res">~' + Math.round(f.reserved_kg || 0) + ' kg ✈️</td>'
      : '<td class="kf-empty">leer</td>';
    return '<tr><td>' + t + '</td><td>' + _kesc(f.callsign) + '</td><td>' + _kesc(f.aircraft || '')
      + '</td><td>' + _kesc(f.dep) + '→' + _kesc(f.arr) + '</td>' + kg + _kCargoLabel(f) + '</tr>';
  }).join('');
  const feed = '<div class="table-scroll"><table class="kutter-feed"><thead><tr><th>Zeit</th><th>Callsign</th><th>Muster</th>'
    + '<th>Strecke</th><th>Fracht</th><th>Ladung</th></tr></thead><tbody>'
    + (rows || '<tr><td colspan="6" style="color:var(--text-label)">Noch keine Flüge.</td></tr>')
    + '</tbody></table></div>';
  return summary + header + bar + parts + feed;
}
```

- [ ] **Step 3: `_kCargoLabel` anpassen** (Z. 4290–4302) — Verlust/Unterwegs statt pauschal „zurück":

```javascript
function _kCargoLabel(f) {
  if (f.loss_kind) {
    const quip = f.quip ? '<span class="kutter-quip">💬 ' + _kesc(f.quip) + '</span>' : '';
    return '<td class="kutter-loss">' + _kLossLabel(f.loss_kind) + quip + '</td>';
  }
  if (!f.loaded) return f.in_air ? '<td class="kf-empty">unterwegs zum Ziel</td>'
                                 : '<td class="kf-empty">zurück</td>';
  const lines = f.cargo_lines || [];
  let label;
  if (lines.length) {
    label = lines.map(l => (l.emoji ? l.emoji + ' ' : '') + _kesc(l.name)
      + (lines.length > 1 ? ' (' + Math.round(l.kg) + ')' : '')).join(' + ');
  } else {
    label = _kesc(f.cargo_name || '');
  }
  const quip = f.quip ? '<span class="kutter-quip">💬 ' + _kesc(f.quip) + '</span>' : '';
  return '<td>' + label + quip + '</td>';
}
```

- [ ] **Step 4: Bummel-Parität in der Event-Liste + Panel-Umschaltung** (Live-Befund 02.07., vier Punkte):

1. **KUTTER-Badge** — `renderFriesenEvents` (~Z. 2665): neben dem Bummel-Badge ergänzen:

```javascript
    const badge = ev.is_bummel ? '<span class="bummel-badge">🏁 BUMMEL</span>'
      : ev.is_transport ? '<span class="bummel-badge">🦐 KUTTER</span>' : '';
    const icaoCell = (ev.is_bummel || ev.is_transport) && ev.route
      ? ev.route.replace(/,/g, ' → ') : (ev.location || '—');
```

2. **Manuelle Kutter-Events in die Liste mischen** — in `fetchFriesenEvents` (~Z. 2615–2633) analog zum Bummel-Merge einen zweiten Block ergänzen (Fehler tolerieren):

```javascript
    try {
      const kuttersRes = await fetch('/api/transport/events');
      const kutters = await kuttersRes.json();
      manualEvents = manualEvents.concat((kutters || [])
        .filter(k => k.source === 'manual')
        .map(k => ({
          summary: k.name,
          dtstart: k.dtstart,
          dtend: k.dtend,
          route: k.route || '',
          location: '',
          is_transport: 1,
          _kutterId: k.id,
          _manual: true,
        })));
    } catch (_) { /* ignorieren */ }
```
   Klick-Handler (~Z. 2680): `else if (ev.is_transport) ev._kutterId ? openKutterDetail(ev._kutterId) : openKutter(ev);`

3. **Karte + Piloten für den Zeitraum wie beim Bummel** — `openKutterDetail` (~Z. 4349–4359) darf `events-results` NICHT mehr verstecken; stattdessen wie `openBummel` die normale Event-Suche für Strecke + Zeitraum anstoßen. Die Zeile `document.getElementById('events-results').classList.add('hidden');` ersetzen durch (Muster aus `openBummel` übernehmen — dort werden die Suchfelder aus `ev.route`/`dtstart`/`dtend` befüllt und `searchEvents()` aufgerufen; beim Kutter kommen `route`/`dtstart`/`dtend` aus dem Detail-Response von `/api/transport/event/{id}`, der in `_refreshKutterDetail` ohnehin geladen wird):

```javascript
  // Wie beim Bummel: darunter die normale Event-Ansicht (Karte + Piloten des Zeitraums).
  const d = _lastKutterDetail;  // von _refreshKutterDetail gesetzt
  if (d && d.route && d.route.length) {
    document.getElementById('event-icao').value = d.route.join(',');
    if (d.dtstart) document.getElementById('event-start').value = isoToLocalInput(d.dtstart);
    if (d.dtend) document.getElementById('event-end').value = isoToLocalInput(d.dtend);
    searchEvents();
  }
```
   (`_lastKutterDetail` als Modul-Variable in `_refreshKutterDetail` setzen. Die exakten Feld-IDs
   und die Datums-Konvertierung aus `openBummel` übernehmen — NICHT raten, sondern den
   `openBummel`-Block als Vorlage kopieren und anpassen. Falls `openBummel` einen Kontext-Flag wie
   `_activeBummel` setzt, damit `searchEvents` nicht wegscrollt: gleiches Muster für den Kutter.)

4. **Panel-Umschaltung in BEIDE Richtungen** — `openBummel` (~Z. 2718) blendet künftig das
   Kutter-Panel aus und stoppt dessen Timer; `openKutterDetail` blendet umgekehrt das
   Bummel-Panel aus:

```javascript
  // in openBummel, direkt am Anfang:
  document.getElementById('kutter-results').classList.add('hidden');
  clearInterval(_kutterPollTimer);
  _kutterOpenId = null;
  // in openKutterDetail, direkt am Anfang:
  document.getElementById('bummel-results').classList.add('hidden');
  _activeBummel = null; _activeBummelId = null;
```
   (Bummel-Timer analog stoppen, falls `openBummel` einen Poll-Timer setzt — nachsehen.)

- [ ] **Step 5: Smoke-Test** — `python -m pytest tests/ -q` (Backend unverändert grün); lokal `uvicorn app.main:app` starten und prüfen: Kutter-Klick → Kutter-Panel + darunter Karte/Piloten; Bummel-Klick danach → Kutter-Panel weg, Bummel da; manuelles Kutter-Event erscheint mit 🦐-Badge in der Liste; Browser-Konsole ohne Fehler.
- [ ] **Step 6: Commit** — `git commit -m "feat(kutter): Live-Ansicht — unterwegs-Segment, Teilnehmerliste, Verlust-Status, Bummel-Parität"`

---

### Task 6: Docs, Changelog v7.5.0, Deploy + Live-Verifikation

**Files:**
- Modify: `app/CHANGELOG.json` (neuer Eintrag OBEN), `README.md`, `docs/api.md`, `docs/architecture.md`

**Interfaces:** — (Abschluss-Task)

- [ ] **Step 1: Changelog** — neuer Eintrag oben (Version aus `app/version.py` ergibt sich automatisch):

```json
  {
    "version": "7.5.0",
    "date": "2026-07-02",
    "title": "FriesenKutter: Reservierung, Teilnehmerliste & verlorene Fracht",
    "items": [
      "✈️ Wer startet, reserviert: Sobald ein Pilot Richtung Ziel unterwegs ist, erscheint seine Zuladung als helles Segment im Ziel-Balken und die offene Menge zeigt »davon X kg unterwegs« — schon beim Rollen, nicht erst bei Ankunft.",
      "👥 Neue Teilnehmerliste in der Kutter-Ansicht: wer fliegt gerade mit wie viel Fracht, wer ist angekommen, wer auf dem Rückflug — mit Summen pro Pilot wie beim Bummel.",
      "🌊 Verlorene Fracht: Wer sein Ziel nie erreicht, verliert die Ladung — »Kutter versunken« (unterwegs verschwunden) oder »geklaut« (am falschen Ort gelandet); wer umkehrt und zu Hause landet, bringt sie ehrlich zurück. Verluste erscheinen im Feed, in der Bilanz (»💀 X kg verloren«) und die Bord-KI spottet dazu.",
      "📏 Erkennungs-Umkreis pro Event einstellbar (Standard 10 km) — für kurze Strecken wie Wangerooge↔Harle."
    ]
  },
```

- [ ] **Step 2: Docs nachziehen**
  - `docs/api.md`: `GET /api/transport/event/{id}` — neue Felder `flights[].in_air/reserved_kg/loss_kind/lost_kg`, `cargo[].reserved_kg`, `participants`, `reserved_total_kg`, `lost_total_kg`; Admin-POSTs: `radius_km` (0.5–50, leer = 10 km).
  - `docs/architecture.md`: Abschnitt `compute_transport_progress` um Reservierungs-Pass, Teilnehmer-Aggregation, `transport_cargo_losses` + `detect_transport_losses` (Poller, 60 s, idempotent) und per-Event-Radius ergänzen (3–6 Sätze).
  - `README.md`: Feature-Liste um einen Kutter-Satz ergänzen (Reservierung + Verluste + Radius), falls dort Features aufgezählt sind.

- [ ] **Step 3: Volle Suite + Commit + Push**

```bash
python -m pytest tests/ -v          # erwartet: alles grün
git add app/CHANGELOG.json README.md docs/api.md docs/architecture.md
git commit -m "docs(kutter): v7.5.0 — Reservierung, Teilnehmer, Verluste, Umkreis"
git push origin main
```

- [ ] **Step 4: Deploy verifizieren**

```bash
gh run watch $(gh run list --repo regover13/friesenspy --limit 1 --json databaseId --jq '.[0].databaseId') --repo regover13/friesenspy --exit-status --interval 20
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 "curl -s http://127.0.0.1:8091/api/frontend-config" | python -c "import json,sys; print(json.load(sys.stdin)['version'])"
# erwartet: 7.5.0
```

- [ ] **Step 5: Tag**

```bash
git tag -a v7.5.0 -m v7.5.0 && git push origin v7.5.0
```

---

## Verifikation (End-to-End, nach Task 6)

1. Prod: Admin → Test-Event mit `radius_km` anlegen/ändern → Wert erscheint in Kachel + GET-APIs.
2. Beim nächsten Live-Flug: Balken zeigt gestreiftes „unterwegs"-Segment ab dem Rollen; Teilnehmerliste führt den Piloten mit „✈️ unterwegs mit X kg"; nach Latch: Segment wird fest, Status „✅ angekommen".
3. Disconnect unterwegs provozieren (oder Alt-Fall abwarten): Feed-Zeile „🌊 Kutter versunken", Header „💀 X kg verloren", Feierabend-Spruch erwähnt den Verlust.
4. Smartphone: neue Teilnehmer-Tabelle scrollt horizontal statt zu quetschen.
