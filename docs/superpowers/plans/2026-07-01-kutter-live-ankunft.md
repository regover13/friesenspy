# FriesenKutter: Fracht zählen ohne Disconnect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FriesenKutter-Fracht zählt, sobald ein FRS-Pilot erkennbar am Boden im Zielradius ist — auch wenn er nicht disconnectet.

**Architecture:** Ein neuer, dauerhafter Latch (`transport_live_arrivals`) wird im bestehenden VATSIM-Poll-Takt geschrieben, sobald ein noch offener FRS-Flug innerhalb 10 km um das `destination`-ICAO eines laufenden Kutter-Events auf < 2 kt abgebremst hat. `compute_transport_progress` vereinheitlicht seine `loaded`-Bedingung (GPS-Endposition ODER Latch) und nimmt zusätzlich aktuell offene Flüge in den Feed auf. Eine Flugsession ist strukturell immer entweder offen oder geschlossen — daher keine Doppelzählung.

**Tech Stack:** Python 3.11, SQLite (stdlib `sqlite3`), FastAPI/APScheduler (bestehend), pytest + pytest-asyncio.

## Global Constraints

- Groundspeed-Schwelle „am Boden": **`< _BLOCK_GS_KT`** (2 kt) — dieselbe Konstante wie die bestehende Blockzeit-Erkennung (`app/database.py:704`), nicht neu einführen.
- Radius um den Zielflugplatz: **`_BUMMEL_AIRPORT_RADIUS_KM`** (10 km, `app/database.py:1383`) — wiederverwenden.
- Scope: **nur FriesenKutter**. Der FriesenFliegerBummel ist explizit NICHT Teil dieses Plans.
- Ein Latch-Eintrag ist **permanent** — kein Löschen, kein Zurücksetzen, keine Rückabwicklung nach späterem Disconnect woanders.
- Spec: `docs/superpowers/specs/2026-07-01-kutter-live-ankunft-design.md`.

---

### Task 1: DB-Schema + Latch-/Query-Helfer

**Files:**
- Modify: `app/database.py:210-218` (neue Tabelle in `_DDL` einfügen)
- Modify: `app/database.py:2572-2575` (neue Funktionen vor `compute_transport_progress` einfügen)
- Test: `tests/test_transport.py`

**Interfaces:**
- Produces:
  - `set_transport_live_arrival(conn: sqlite3.Connection, cid: int, logon_time: str, event_id: int, arrived_at: str) -> None`
  - `get_transport_live_arrivals(conn: sqlite3.Connection, event_id: int) -> set[tuple[int, str]]`
  - `active_transport_destinations(conn: sqlite3.Connection, now: str) -> list[dict]` — je Eintrag `{"id": int, "destination": str}`
  - `open_transport_flights(conn: sqlite3.Connection, callsign_prefix: str = "FRS") -> list[dict]` — je Eintrag `{"cid", "callsign", "aircraft", "aircraft_icao", "departure", "arrival", "logon_time"}`

- [ ] **Step 1: Failing Tests schreiben**

Öffne `tests/test_transport.py` und füge am Ende der Datei (nach der letzten Testklasse) an:

```python
class TestLiveArrivalLatch:
    def test_set_and_get_roundtrip(self):
        conn = _make_conn()
        ev = _event(conn)
        set_transport_live_arrival(conn, 42, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}

    def test_insert_or_ignore_is_idempotent(self):
        conn = _make_conn()
        ev = _event(conn)
        set_transport_live_arrival(conn, 42, START, ev["id"], "2026-07-01T10:00:00Z")
        set_transport_live_arrival(conn, 42, START, ev["id"], "2026-07-01T11:00:00Z")
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}

    def test_get_scoped_to_event(self):
        conn = _make_conn()
        ev1 = _event(conn)
        ev2 = create_transport_event(
            conn, name="Anderes Event", route="EDWF,EDWR", dtstart=START, dtend=END,
        )
        set_transport_live_arrival(conn, 42, START, ev1["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        assert get_transport_live_arrivals(conn, ev2) == set()

    def test_active_transport_destinations_filters_by_time_window(self):
        conn = _make_conn()
        ev = _event(conn)  # dtstart=START, dtend=END (siehe _event-Helfer)
        active = active_transport_destinations(conn, "2026-07-01T12:00:00Z")  # innerhalb [START,END]
        assert active == [{"id": ev["id"], "destination": "EDXH"}]
        assert active_transport_destinations(conn, "2026-06-01T00:00:00Z") == []  # vor dtstart
        assert active_transport_destinations(conn, "2026-08-01T00:00:00Z") == []  # nach dtend

    def test_open_transport_flights_excludes_closed_and_wrong_prefix(self):
        conn = _make_conn()
        _add_flight(conn, 1, "EDWG", "EDXH", "C172", START)  # geschlossen (logoff gesetzt)
        _add_open_flight(conn, 2, "EDWG", "", "C208", START)  # offen, FRS
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, logon_time) "
            "VALUES (3, 'DLH123', 'A320', 'EDDF', ?)", (START,),
        )  # offen, aber KEIN FRS-Callsign
        conn.commit()
        open_flights = open_transport_flights(conn)
        assert {f["cid"] for f in open_flights} == {2}
```

Ergänze außerdem den Import-Block ganz oben in `tests/test_transport.py`:

```python
from app.database import (
    compute_transport_progress,
    create_transport_event,
    get_connection,
    get_payload_map,
    get_transport_event,
    init_db,
    set_transport_cargo,
    upsert_payload,
    list_cargo_catalog,
    upsert_cargo_catalog,
    delete_cargo_catalog,
    seed_cargo_catalog,
    set_transport_quip,
    get_transport_quips,
    transport_quips_enabled,
    flight_quip_context,
    event_summary_context,
    set_app_setting,
    upsert_calendar_transport_event,
    get_transport_cargo,
    set_transport_live_arrival,
    get_transport_live_arrivals,
    active_transport_destinations,
    open_transport_flights,
)
```

Und einen `_add_open_flight`-Test-Helfer direkt nach `_add_flight` (siehe bestehende Definition rund um Zeile 52-64):

```python
def _add_open_flight(conn, cid, dep, arr, aircraft, logon, *, callsign=None):
    callsign = callsign or f"FRS{cid:02d}"
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, f"Pilot{cid}", START),
    )
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cid, callsign, aircraft, dep, arr, logon),
    )
    conn.commit()
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen (Funktionen existieren noch nicht)**

```bash
cd "D:/User/Tobias/OneDrive/Claude/FriesenSpy"
python -m pytest tests/test_transport.py::TestLiveArrivalLatch -v
```
Erwartet: `ImportError` bzw. `NameError` — die Funktionen sind noch nicht implementiert.

- [ ] **Step 3: Tabelle zu `_DDL` hinzufügen**

In `app/database.py`, direkt nach dem `transport_quips`-Block (Zeilen 210-217) und vor `aircraft_payloads`:

```python
CREATE TABLE IF NOT EXISTS transport_quips (
    event_id   INTEGER NOT NULL,
    flight_key TEXT NOT NULL,            -- "{cid}:{logon_time}" (stabil)
    quip       TEXT,
    created_at TEXT,
    PRIMARY KEY(event_id, flight_key)
);

CREATE TABLE IF NOT EXISTS transport_live_arrivals (
    cid         INTEGER NOT NULL,
    logon_time  TEXT NOT NULL,
    event_id    INTEGER NOT NULL,
    arrived_at  TEXT NOT NULL,
    PRIMARY KEY (cid, logon_time, event_id)
);

CREATE TABLE IF NOT EXISTS aircraft_payloads (
```

(Ersetze den `old_string` beim Edit mit dem kompletten `transport_quips`-Block bis `CREATE TABLE IF NOT EXISTS aircraft_payloads (`, wie oben gezeigt, damit die Einfügestelle eindeutig ist.)

- [ ] **Step 4: Helfer-Funktionen implementieren**

In `app/database.py`, direkt nach `set_transport_summarized` (Zeile 2572) und vor `def compute_transport_progress(` (Zeile 2575) einfügen:

```python
def set_transport_live_arrival(
    conn: sqlite3.Connection, cid: int, logon_time: str, event_id: int, arrived_at: str
) -> None:
    """Live-Ankunft dauerhaft latchen — einmal geschrieben, nie zurückgenommen."""
    conn.execute(
        "INSERT OR IGNORE INTO transport_live_arrivals (cid, logon_time, event_id, arrived_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, logon_time, event_id, arrived_at),
    )


def get_transport_live_arrivals(conn: sqlite3.Connection, event_id: int) -> set[tuple[int, str]]:
    """{(cid, logon_time)} mit Live-Ankunfts-Latch für dieses Event."""
    rows = conn.execute(
        "SELECT cid, logon_time FROM transport_live_arrivals WHERE event_id = ?", (event_id,)
    ).fetchall()
    return {(r["cid"], r["logon_time"]) for r in rows}


def active_transport_destinations(conn: sqlite3.Connection, now: str) -> list[dict]:
    """Aktuell laufende FriesenKutter-Events (dtstart <= now <= dtend) mit gesetztem Ziel."""
    rows = conn.execute(
        "SELECT id, destination FROM transport_events "
        "WHERE dtstart <= ? AND dtend >= ? AND destination IS NOT NULL AND destination != ''",
        (now, now),
    ).fetchall()
    return [{"id": r["id"], "destination": r["destination"]} for r in rows]


def open_transport_flights(conn: sqlite3.Connection, callsign_prefix: str = "FRS") -> list[dict]:
    """Aktuell offene (noch verbundene) FRS-Flüge — Basis für Live-Ankunft ohne Disconnect."""
    rows = conn.execute(
        "SELECT cid, callsign, aircraft_short AS aircraft, aircraft_icao, departure, arrival, logon_time "
        "FROM flights WHERE logoff_time IS NULL AND superseded_by IS NULL AND callsign LIKE ?",
        (callsign_prefix + "%",),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Tests laufen lassen — müssen bestehen**

```bash
python -m pytest tests/test_transport.py::TestLiveArrivalLatch -v
```
Erwartet: `5 passed`.

- [ ] **Step 6: Ganze Suite + Commit**

```bash
python -m pytest -q
git add app/database.py tests/test_transport.py
git commit -m "feat(kutter): DB-Latch transport_live_arrivals + Query-Helfer"
```
Erwartet: alle Tests grün (vorherige Anzahl + 5 neue).

---

### Task 2: Erkennungsfunktion `check_live_arrival`

**Files:**
- Modify: `app/database.py` (neue Funktion, direkt nach `open_transport_flights` aus Task 1)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `set_transport_live_arrival(conn, cid, logon_time, event_id, arrived_at)` (Task 1)
- Produces: `check_live_arrival(conn: sqlite3.Connection, cid: int, logon_time: str, latitude: float, longitude: float, groundspeed: float, events: list[dict], *, radius_km: float | None = None) -> None` — `events` ist die Liste aus `active_transport_destinations()` (Task 1), wird NICHT selbst nachgeladen (Aufrufer lädt einmal pro Poll, nicht pro Pilot).

- [ ] **Step 1: Failing Tests schreiben**

An `tests/test_transport.py` anhängen:

```python
class TestCheckLiveArrival:
    def _events(self, event_id, dest="EDXH"):
        return [{"id": event_id, "destination": dest}]

    def test_within_radius_and_slow_latches(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 1.5, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}

    def test_within_radius_but_too_fast_does_not_latch(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 120.0, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == set()

    def test_outside_radius_does_not_latch(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDDF")  # Frankfurt, weit weg von EDXH
        check_live_arrival(conn, 42, START, lat, lon, 0.0, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == set()

    def test_no_active_events_does_not_latch(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 0.0, [])
        conn.commit()
        assert get_transport_live_arrivals(conn, 999) == set()

    def test_idempotent_repeated_check(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 1.0, self._events(ev["id"]))
        check_live_arrival(conn, 42, START, lat, lon, 1.0, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}
```

Ergänze `check_live_arrival` im Import-Block von `tests/test_transport.py` (gleiche Stelle wie in Task 1).

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

```bash
python -m pytest tests/test_transport.py::TestCheckLiveArrival -v
```
Erwartet: `NameError: name 'check_live_arrival' is not defined`.

- [ ] **Step 3: Funktion implementieren**

In `app/database.py`, direkt nach `open_transport_flights` (aus Task 1) einfügen:

```python
def check_live_arrival(
    conn: sqlite3.Connection,
    cid: int,
    logon_time: str,
    latitude: float,
    longitude: float,
    groundspeed: float,
    events: list[dict],
    *,
    radius_km: float | None = None,
) -> None:
    """Prüft eine aktuelle Live-Position gegen bereits geladene, laufende FriesenKutter-Ziele
    (``events``, aus :func:`active_transport_destinations`) und latcht einen Treffer dauerhaft
    (``transport_live_arrivals``) — 'am Boden' (``groundspeed < _BLOCK_GS_KT``) und im Umkreis
    (``radius_km``, Default ``_BUMMEL_AIRPORT_RADIUS_KM``) um ``destination``. Kein
    Rückgängigmachen; ``events`` wird NICHT selbst nachgeladen (Aufrufer lädt einmal pro Poll)."""
    if groundspeed is None or groundspeed >= _BLOCK_GS_KT:
        return
    from app.geo import haversine, icao_to_coords
    radius = radius_km or _BUMMEL_AIRPORT_RADIUS_KM
    now = _now_utc()
    for ev in events:
        dest = normalize_type_code(ev.get("destination"))
        coords = icao_to_coords(dest) if dest else None
        if not coords:
            continue
        if haversine(latitude, longitude, coords[0], coords[1]) <= radius:
            set_transport_live_arrival(conn, cid, logon_time, ev["id"], now)
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

```bash
python -m pytest tests/test_transport.py::TestCheckLiveArrival -v
```
Erwartet: `5 passed`.

- [ ] **Step 5: Ganze Suite + Commit**

```bash
python -m pytest -q
git add app/database.py tests/test_transport.py
git commit -m "feat(kutter): Live-Ankunfts-Erkennung (Radius + Boden-Geschwindigkeit)"
```

---

### Task 3: Poller-Integration (ohne neuen Timer)

**Files:**
- Modify: `app/poller.py:17-37` (Import-Block)
- Modify: `app/poller.py:748-750` (Hook zwischen 2b und 2c einfügen)
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `active_transport_destinations(conn, now)`, `check_live_arrival(conn, cid, logon_time, latitude, longitude, groundspeed, events)` (Task 1+2)
- Produces: Kein neues Interface — reine Verdrahtung im bestehenden `_poll_once`.

- [ ] **Step 1: Failing Test schreiben**

An `tests/test_poller.py` anhängen (gleiche Datei, nach der letzten Klasse):

```python
class TestKutterLiveArrivalHook:
    @pytest.mark.asyncio
    async def test_poll_once_latches_live_arrival_without_disconnect(self, tmp_path):
        """Ein FRS-Pilot, der langsam (< 2 kt) im Zielradius eines laufenden Kutter-Events ist,
        wird SOFORT gelatcht -- ohne dass er disconnecten muss."""
        from app.database import (
            init_db, get_connection, create_transport_event, get_transport_live_arrivals,
        )
        from app.geo import icao_to_coords

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = get_connection(db_file)
        event_id = create_transport_event(
            conn, name="Testkutter", route="EDWG,EDXH", destination="EDXH",
            dtstart="2020-01-01T00:00:00Z", dtend="2030-01-01T00:00:00Z",
        )
        conn.commit()
        conn.close()

        lat, lon = icao_to_coords("EDXH")

        poller = VatsimPoller(db_path=db_file, callsign_prefix="FRS", poll_interval=60)
        poller._http_client = AsyncMock()
        poller.subscribe_sse()

        vatsim_data = {
            "pilots": [{
                "cid": 555,
                "name": "Ludger Friesen",
                "callsign": "FRS55",
                "latitude": lat,
                "longitude": lon,
                "altitude": 0,
                "groundspeed": 1,
                "heading": 90,
                "logon_time": "2026-07-01T09:00:00Z",
                "flight_plan": {
                    "aircraft_short": "C208", "departure": "EDWG", "arrival": "EDXH",
                },
            }]
        }
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=vatsim_data)):
            await poller._poll_once()

        conn = get_connection(db_file)
        try:
            latches = get_transport_live_arrivals(conn, event_id)
        finally:
            conn.close()
        assert (555, "2026-07-01T09:00:00Z") in latches

    @pytest.mark.asyncio
    async def test_poll_once_no_active_event_no_latch(self, tmp_path):
        """Ohne laufendes Kutter-Event wird nichts gelatcht (kein Fehler, kein Latch)."""
        from app.database import init_db, get_connection
        from app.geo import icao_to_coords

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        lat, lon = icao_to_coords("EDXH")
        poller = VatsimPoller(db_path=db_file, callsign_prefix="FRS", poll_interval=60)
        poller._http_client = AsyncMock()
        poller.subscribe_sse()

        vatsim_data = {
            "pilots": [{
                "cid": 555, "name": "Ludger Friesen", "callsign": "FRS55",
                "latitude": lat, "longitude": lon, "altitude": 0, "groundspeed": 1, "heading": 90,
                "logon_time": "2026-07-01T09:00:00Z",
                "flight_plan": {"aircraft_short": "C208", "departure": "EDWG", "arrival": "EDXH"},
            }]
        }
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=vatsim_data)):
            await poller._poll_once()  # darf NICHT werfen

        conn = get_connection(db_file)
        try:
            row = conn.execute("SELECT COUNT(*) FROM transport_live_arrivals").fetchone()
        finally:
            conn.close()
        assert row[0] == 0
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

```bash
python -m pytest tests/test_poller.py::TestKutterLiveArrivalHook -v
```
Erwartet: `AssertionError` (kein Latch, weil der Hook noch nicht existiert) — der zweite Test
(`test_poll_once_no_active_event_no_latch`) besteht bereits zufällig (nichts passiert), das ist
für diesen Schritt in Ordnung; entscheidend ist, dass der erste Test fehlschlägt.

- [ ] **Step 3: Import-Block erweitern**

In `app/poller.py`, im bestehenden `from app.database import (...)`-Block (Zeilen 17-37):

```python
from app.database import (
    cleanup_old_history,
    close_flight,
    delete_push_subscription,
    ensure_pilot,
    get_connection,
    get_live_positions,
    get_push_subscriptions_for_pilot,
    get_push_subscriptions_for_prefile,
    cid_for_callsign,
    get_ts_consent,
    get_ts_push_subscriptions,
    load_prefile_sigs,
    open_flight,
    remove_live_position,
    save_position_history,
    save_prefile_sigs,
    update_flight_plan,
    upsert_live_position,
    upsert_statsim_flights,
    active_transport_destinations,
    check_live_arrival,
)
```

- [ ] **Step 4: Hook zwischen 2b (still_online) und 2c (went_offline) einfügen**

In `app/poller.py`, nach dem Ende der `still_online`-Schleife (Zeile 748, `)` schließt das
`logger.info("Neues Leg CID %s: ...")`) und vor dem Kommentar `# 2c. Pilots who went offline`
(Zeile 750) einfügen:

```python
                            )

                # 2c. Live-Ankunft prüfen (FriesenKutter, ohne Disconnect) — läuft im selben
                # Poll-Takt mit, kein eigener Timer. Nutzt dieselben Live-Positionen, die 2a/2b
                # gerade aktualisiert haben.
                now_check = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                active_events = active_transport_destinations(conn, now_check)
                if active_events:
                    for cid in current_cids:
                        pos = current[cid]
                        check_live_arrival(
                            conn, cid, pos["logon_time"], pos["latitude"], pos["longitude"],
                            pos["groundspeed"], active_events,
                        )

                # 2d. Pilots who went offline
```

(Der alte Kommentar `# 2c. Pilots who went offline` wird dabei zu `# 2d. Pilots who went offline`
umbenannt — sonst bleibt die Zeile darunter unverändert.)

- [ ] **Step 5: Docstring von `_poll_once` aktualisieren**

Im Docstring von `_poll_once` (Zeile 486-499) die Nummerierung ergänzen:

```python
    async def _poll_once(self) -> None:
        """Hauptlogik: VATSIM abfragen, State-Machine ausführen.

        State-Machine:
        1. VATSIM-Daten abrufen → filter_friesen_pilots
        2. Aktuell online CIDs mit _active_flights vergleichen:
           - Neu online  → ensure_pilot, open_flight, upsert_live_position,
                           save_position_history, Telegram-Alert senden
           - Noch online → upsert_live_position, save_position_history
           - Live-Ankunft (FriesenKutter) → check_live_arrival je Pilot gegen laufende Events
           - Offline     → close_flight, remove_live_position,
                           _active_flights[cid] entfernen
        3. SSE-Queue: get_live_positions() → {"type": "positions", "data": [...]}
        4. Exceptions → logging.exception, NICHT weiterwerfen
        """
```

- [ ] **Step 6: Tests laufen lassen — müssen bestehen**

```bash
python -m pytest tests/test_poller.py::TestKutterLiveArrivalHook -v
```
Erwartet: `2 passed`.

- [ ] **Step 7: Ganze Suite + Commit**

```bash
python -m pytest -q
git add app/poller.py tests/test_poller.py
git commit -m "feat(kutter): Live-Ankunfts-Pruefung in den VATSIM-Poll-Takt verdrahten"
```

---

### Task 4: `compute_transport_progress` — Latch auswerten + offene Flüge im Feed

**Files:**
- Modify: `app/database.py:2593-2644` (`compute_transport_progress`)
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `get_transport_live_arrivals(conn, event_id)`, `open_transport_flights(conn, callsign_prefix)` (Task 1)
- Produces: `compute_transport_progress()` liefert jetzt auch aktuell offene Flüge im `flights`-Feed (mit `loaded=False`/`tonnage_kg=0` bis der Latch greift); Feld-Struktur je Flug bleibt unverändert (`dep_time, cid, callsign, aircraft, dep, arr, tonnage_kg, loaded, flight_key, distance_nm, block_min, name, cargo_name, cargo_lines, quip`).

- [ ] **Step 1: Failing Tests schreiben**

An `tests/test_transport.py` anhängen:

```python
class TestLiveArrivalInProgress:
    def test_open_flight_without_latch_shows_zero_kg(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        f = _feed_by_callsign(p, "FRS09")
        assert f is not None
        assert f["loaded"] is False
        assert f["tonnage_kg"] == 0

    def test_open_flight_with_latch_counts_immediately(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        ev = _event(conn)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        p = compute_transport_progress(conn, ev, END)
        f = _feed_by_callsign(p, "FRS09")
        assert f["loaded"] is True
        assert f["tonnage_kg"] == 550

    def test_latch_persists_after_disconnect_elsewhere(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        ev = _event(conn)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        # Pilot disconnectet spaeter ganz woanders (Ziel ausserhalb der Strecke) -- die Fracht
        # bleibt trotzdem gezaehlt, weil der Latch bereits existiert.
        conn.execute(
            "UPDATE flights SET logoff_time=?, arrival='EDDH', duration_min=45, distance_nm=120 "
            "WHERE cid=9",
            (END,),
        )
        conn.commit()
        p = compute_transport_progress(conn, ev, END)
        f = _feed_by_callsign(p, "FRS09")
        assert f is not None
        assert f["loaded"] is True
        assert f["tonnage_kg"] == 550

    def test_open_flight_departing_from_destination_is_excluded(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDXH", "", "C208", START)  # startet BEREITS am Ziel
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        assert _feed_by_callsign(p, "FRS09") is None

    def test_open_flight_participates_in_coload_fill(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 300, "per_flight_max_kg": 100, "emoji": "🎞️"},
            {"name": "Friesentee", "target_kg": 500, "emoji": "🫖"},
        ])
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        p = compute_transport_progress(conn, ev, END)
        film = next(c for c in p["cargo"] if c["name"] == "Filmrollen")
        tee = next(c for c in p["cargo"] if c["name"] == "Friesentee")
        assert film["delivered_kg"] == 100
        assert tee["delivered_kg"] == 450
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

```bash
python -m pytest tests/test_transport.py::TestLiveArrivalInProgress -v
```
Erwartet: alle 5 Tests schlagen fehl (offene Flüge tauchen noch nicht im Feed auf; `_feed_by_callsign(p, "FRS09")` ist `None`).

- [ ] **Step 3: `loaded`-Bedingung für geschlossene Flüge vereinheitlichen**

In `app/database.py`, im bestehenden Closed-Flights-Loop von `compute_transport_progress`, den
Block ersetzen:

Alt (Zeilen ~2607-2625):
```python
    dest = normalize_type_code(event.get("destination"))

    # Netzwerk-Flüge sammeln (dep & arr auf der Strecke, dep≠arr). „Beladen" = Ankunft am Ziel;
    # Rückflüge (und Bein-zu-Bein ohne Ziel) sind leer (0 kg), erscheinen aber im Feed.
    network: list[dict] = []
    unmapped: set[str] = set()
    for f in flights:
        cid = f.get("cid")
        if cid is None:
            continue
        lo = f.get("logon_time") or ""
        lf = f.get("logoff_time") or "9999-12-31T23:59:59Z"
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("departure"))
        arr = _nearest_airport(coords_map, _last_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("arrival"))
        if dep not in route_set or arr not in route_set or dep == arr:
            continue
        loaded = bool(dest) and arr == dest
```

Neu:
```python
    dest = normalize_type_code(event.get("destination"))
    live_arrivals = get_transport_live_arrivals(conn, int(event["id"]))

    # Netzwerk-Flüge sammeln (dep & arr auf der Strecke, dep≠arr). „Beladen" = Ankunft am Ziel
    # ODER ein Live-Ankunfts-Latch existiert (Fracht ohne Disconnect erkannt) — ein Latch hebt
    # den Strecken-Filter auf, da die Fracht dann unabhängig vom finalen Disconnect-Ort zählt.
    network: list[dict] = []
    unmapped: set[str] = set()
    for f in flights:
        cid = f.get("cid")
        if cid is None:
            continue
        lo = f.get("logon_time") or ""
        lf = f.get("logoff_time") or "9999-12-31T23:59:59Z"
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("departure"))
        arr = _nearest_airport(coords_map, _last_pos(conn, int(cid), lo, lf), radius) \
            or normalize_type_code(f.get("arrival"))
        has_latch = (cid, lo) in live_arrivals
        if not has_latch and (dep not in route_set or arr not in route_set or dep == arr):
            continue
        loaded = bool(dest) and (arr == dest or has_latch)
```

- [ ] **Step 4: Offene Flüge nach dem Closed-Flights-Loop einfügen**

Direkt nach dem Ende des Closed-Flights-Loops (nach dem `network.append({...})`-Block, Zeilen
~2630-2642) und vor `network.sort(key=lambda x: x["dep_time"])` (Zeile 2644) einfügen:

```python
    # Aktuell offene Flüge (noch verbunden) — bisher komplett ignoriert, da canonicalize_flights
    # logoff_time IS NOT NULL verlangt. Zählen ab dem Live-Ankunfts-Latch, ohne Disconnect.
    for f in open_transport_flights(conn, callsign_prefix):
        cid = f.get("cid")
        if cid is None:
            continue
        lo = f.get("logon_time") or ""
        if lo < start:
            continue
        dep = _nearest_airport(coords_map, _first_pos(conn, int(cid), lo, now), radius) \
            or normalize_type_code(f.get("departure"))
        if dep not in route_set or dep == dest:
            continue
        loaded = bool(dest) and (cid, lo) in live_arrivals
        type_code = normalize_type_code(f.get("aircraft_icao")) or normalize_type_code(f.get("aircraft"))
        if loaded and type_code and type_code not in payload_map:
            unmapped.add(type_code)
        tonnage = round(payload_map.get(type_code, default_kg), 1) if loaded else 0.0
        network.append({
            "dep_time": lo,
            "cid": cid,
            "callsign": f.get("callsign") or "",
            "aircraft": f.get("aircraft") or type_code,
            "dep": dep,
            "arr": dest,
            "tonnage_kg": tonnage,
            "loaded": loaded,
            "flight_key": f"{cid}:{lo}",
            "distance_nm": 0,
            "block_min": 0,
        })
```

- [ ] **Step 5: Tests laufen lassen — müssen bestehen**

```bash
python -m pytest tests/test_transport.py::TestLiveArrivalInProgress -v
```
Erwartet: `5 passed`.

- [ ] **Step 6: Ganze Suite + Commit**

```bash
python -m pytest -q
git add app/database.py tests/test_transport.py
git commit -m "feat(kutter): compute_transport_progress zaehlt Fracht ohne Disconnect"
```

---

### Task 5: Docs, Changelog, Version, Deploy

**Files:**
- Modify: `app/CHANGELOG.json` (neuer Eintrag oben)
- Modify: `README.md` (FriesenKutter-Abschnitt ergänzen)
- Modify: `docs/api.md` (Hinweis zur Live-Ankunft)
- Modify: `docs/architecture.md` (`compute_transport_progress`-Beschreibung aktualisieren)

**Interfaces:**
- Consumes: alle vorherigen Tasks (Feature vollständig implementiert und getestet).
- Produces: deploytes Release, keine neuen Code-Interfaces.

- [ ] **Step 1: Version prüfen und Changelog-Eintrag hinzufügen**

`app/CHANGELOG.json` öffnen, aktuelle Top-Version ansehen:

```bash
python -c "import json; print(json.load(open('app/CHANGELOG.json', encoding='utf-8'))[0]['version'])"
```

Neuen Eintrag ganz oben in der JSON-Liste einfügen (Minor-Bump, z. B. `7.3.0` — exakte Zahl von
der oben ausgegebenen aktuellen Version ableiten, +0.1.0):

```json
  {
    "version": "7.3.0",
    "date": "2026-07-01",
    "title": "FriesenKutter: Fracht zählt ohne Disconnect",
    "items": [
      "📍 Fracht zählt jetzt, sobald du erkennbar am Boden (< 2 kt) im Zielradius bist — kein Disconnect mehr nötig. Einmal erkannt, bleibt es auch dann gezählt, wenn du weiterfliegst oder woanders disconnectest."
    ]
  },
```

- [ ] **Step 2: README.md ergänzen**

Im FriesenKutter-Abschnitt von `README.md` (nach dem Absatz über den Frachtart-Katalog) ergänzen:

```markdown
- **Ohne Disconnect zählen:** Fracht wird bereits erfasst, sobald du erkennbar am Boden (< 2 kt Geschwindigkeit) im 10-km-Umkreis um das Ziel bist — du musst nicht disconnecten. Einmal erkannt, bleibt die Fracht dauerhaft gezählt, auch wenn du danach weiterfliegst.
```

- [ ] **Step 3: docs/api.md ergänzen**

In `docs/api.md`, im Abschnitt zu `GET /api/transport/event/{id}` (bzw. direkt darunter) ergänzen:

```markdown
> **Ohne Disconnect (Live-Ankunft):** Ein noch offener (verbundener) Flug erscheint im Feed,
> sobald sein Start auf der Strecke liegt; sobald er innerhalb 10 km um `destination` auf
> < 2 kt abbremst, wird er sofort als beladen gezählt (`transport_live_arrivals`) — unabhängig
> vom späteren Disconnect-Ort. Kein Zurücksetzen.
```

- [ ] **Step 4: docs/architecture.md ergänzen**

Im Abschnitt zu `compute_transport_progress` in `docs/architecture.md` (der lange Absatz, der mit
„**FriesenKutter-Fortschritt (`compute_transport_progress`)**." beginnt) am Ende ergänzen:

```markdown
 Seit Live-Ankunft ohne Disconnect: die `loaded`-Bedingung ist zusätzlich wahr, wenn ein Eintrag
in `transport_live_arrivals` existiert (`(cid, logon_time)` — gesetzt vom Poller via
`check_live_arrival`, sobald ein noch offener Flug innerhalb `_BUMMEL_AIRPORT_RADIUS_KM` um
`destination` auf `< _BLOCK_GS_KT` abbremst); dieser Latch hebt auch den Strecken-Filter auf,
sodass die Fracht selbst dann gezählt bleibt, wenn der Pilot später weit außerhalb der Strecke
disconnectet. Zusätzlich werden aktuell offene Flüge (`open_transport_flights`) mit Start auf der
Strecke in den Feed aufgenommen (0 kg bis der Latch greift) — bisher wurden sie komplett
ignoriert, da `canonicalize_flights` einen abgeschlossenen Flug voraussetzt.
```

- [ ] **Step 5: Volle Suite + Deploy**

```bash
python -m pytest -q
git add app/CHANGELOG.json README.md docs/api.md docs/architecture.md
git commit -m "docs(kutter): Live-Ankunft ohne Disconnect dokumentiert (vX.Y.Z)"
git tag -a vX.Y.Z -m "FriesenKutter: Fracht zaehlt ohne Disconnect"
git push origin main
git push origin vX.Y.Z
```
(`vX.Y.Z` durch die in Step 1 gewählte Version ersetzen.)

- [ ] **Step 6: Deploy abwarten + VPS verifizieren**

```bash
gh run list --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch <RUN_ID> --exit-status
ssh -i ~/.ssh/tsbot_server root@167.86.127.129 \
  'curl -s http://127.0.0.1:8091/health; sqlite3 /opt/friesenspy/data/friesenspy.db \
   "SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"transport_live_arrivals\";"'
```
Erwartet: `{"status":"ok"}` und `transport_live_arrivals` als vorhandene Tabelle.

---

## Self-Review (bereits durchgeführt)

- **Spec-Abdeckung:** Tabelle (Task 1), Erkennung im Poll-Takt (Task 2+3), vereinheitlichte
  `loaded`-Bedingung + offene Flüge im Feed (Task 4), Deploy (Task 5) — alle Spec-Abschnitte
  abgedeckt.
- **Platzhalter-Scan:** keine TBD/TODO; `vX.Y.Z` in Task 5 ist bewusst ein abzuleitender Wert
  (aus dem tatsächlichen Changelog-Stand zum Ausführungszeitpunkt), kein Platzhalter für fehlenden
  Code.
- **Typ-/Signatur-Konsistenz:** `check_live_arrival(events: list[dict])` (Task 2) passt zur
  Rückgabe von `active_transport_destinations()` (Task 1); `open_transport_flights()`-Feldnamen
  (`cid, callsign, aircraft, aircraft_icao, departure, arrival, logon_time`) stimmen mit der
  Verwendung in Task 4 überein.
