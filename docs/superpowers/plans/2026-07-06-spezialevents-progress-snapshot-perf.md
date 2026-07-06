# Spezial-Events Fortschritt einfrieren + Retention — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (empfohlen) oder superpowers:executing-plans, um diesen Plan Task für Task umzusetzen. Schritte nutzen Checkbox-Syntax (`- [ ]`).

**Goal:** Abgeschlossene Kutter- und Bummel-Events werden bei Abschluss als JSON-Snapshot eingefroren und aus diesem bedient, statt bei jedem Request/Poll teuer über `canonicalize_legs` neu gerechnet zu werden; dazu 365-Tage-Anzeige-Retention auf beiden Listen-Endpoints.

**Architecture:** Gemeinsame Tabelle `progress_snapshot(kind, ref_id, code_version, computed_at, payload_json)`. Endpoints lesen für abgeschlossene Events aus dem Snapshot (versions-gefiltert), rechnen aktive live. Kutter friert der Poller eager beim `summarized_at`-Latch ein; Bummel lazy beim ersten Read nach Reveal (`revealed_at` UND `now >= dtend`). Zeitabhängige/nachlaufende Felder (Status, KI-Quips, Bummel-Metadaten) werden beim Read frisch überlagert. Invalidierung: Event-/Rennen-Bearbeitung (auch leerer Body), globale Payload-Änderung, Kalender-Sync bei echter Wertänderung; global via `_PROGRESS_SNAPSHOT_VERSION`.

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL), pytest.

**Spec:** `docs/superpowers/specs/2026-07-06-spezialevents-progress-snapshot-perf-design.md` (maßgeblich; bei Konflikt gewinnt die Spec).

## Global Constraints

- Beide Spezial-Events (Kutter `transport_events`/`summarized_at`, Bummel `bummel_races`/`revealed_at`) **gleichrangig** behandeln.
- Neue Konstanten in `app/database.py`: `_PROGRESS_SNAPSHOT_VERSION = "1"`, `_DATA_RETENTION_DAYS = 365`.
- `get_progress_snapshot` liefert Payload **nur** bei `code_version == _PROGRESS_SNAPSHOT_VERSION`, parst pro Read frisch aus `payload_json` (nie ein geteiltes veränderliches Dict).
- Bummel gilt nur als abgeschlossen, wenn `revealed_at` gesetzt **und** `now >= dtend`.
- KI-Quips (`summary_quip`, Pro-Flug-`quip`) und Status gehören NICHT zur eingefrorenen Identität → beim Read frisch überlagern.
- Kein Admin-Button, kein Recompute-Endpoint, keine automatische Invalidierung bei custom_airports/StatSim-Nachladen (bleibt eingefroren).
- Retention ist reine **Anzeige**-Grenze: nur öffentliche Listen-Endpoints filtern (`since = now − 365 d`), Poller/Admin `since=None`. NULL-Guard `(dtend IS NULL OR dtend >= ?)`.
- CHANGELOG-Eintrag mit deutschen typografischen Anführungszeichen („ ") — ASCII-`"` bricht das JSON. Version = Minor. Git-Tag `vX.Y.Z`. **Vor `git push origin main` Nutzer-Bestätigung.**
- Docs mitpflegen: `docs/architecture.md`, `docs/api.md`, `README.md`.
- Vor jeder Änderung die betroffene bestehende Funktion LESEN (Zeilennummern der Spec sind Stand 2026-07-06, können driften).

---

### Task 1: Snapshot-Tabelle + Helfer + Versions-Konstante

**Files:**
- Modify: `app/database.py` (DDL-Block `_DDL`; Konstanten oben bei den anderen `_`-Konstanten; Helfer bei den übrigen Transport-Helfern)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces:
  - `_PROGRESS_SNAPSHOT_VERSION: str` (Modul-Konstante, Startwert `"1"`)
  - `get_progress_snapshot(conn, kind: str, ref_id: int) -> dict | None`
  - `write_progress_snapshot(conn, kind: str, ref_id: int, payload: dict, computed_at: str) -> None`
  - `delete_progress_snapshot(conn, kind: str, ref_id: int) -> None`
  - `delete_progress_snapshots(conn, kind: str) -> int`

- [ ] **Step 1: Failing-Tests schreiben** (`tests/test_database.py`)

```python
def test_progress_snapshot_roundtrip():
    conn = _mem_db()  # vorhandenen In-Memory-Fixture-Helfer nutzen; sonst init_db(":memory:")
    from app.database import (
        write_progress_snapshot, get_progress_snapshot, delete_progress_snapshot,
    )
    payload = {"total_kg": 1234.5, "flights": [{"cid": 1, "callsign": "FRS1"}]}
    write_progress_snapshot(conn, "kutter", 7, payload, "2026-07-06T10:00:00Z")
    got = get_progress_snapshot(conn, "kutter", 7)
    assert got == payload
    # frisch geparst, kein geteiltes Objekt:
    got["total_kg"] = 0
    assert get_progress_snapshot(conn, "kutter", 7)["total_kg"] == 1234.5
    delete_progress_snapshot(conn, "kutter", 7)
    assert get_progress_snapshot(conn, "kutter", 7) is None


def test_snapshot_ignored_when_version_stale():
    conn = _mem_db()
    import app.database as db
    db.write_progress_snapshot(conn, "bummel", 3, {"x": 1}, "2026-07-06T10:00:00Z")
    conn.execute("UPDATE progress_snapshot SET code_version = 'OLD' WHERE kind='bummel' AND ref_id=3")
    assert db.get_progress_snapshot(conn, "bummel", 3) is None


def test_delete_progress_snapshots_by_kind():
    conn = _mem_db()
    import app.database as db
    db.write_progress_snapshot(conn, "kutter", 1, {"a": 1}, "t")
    db.write_progress_snapshot(conn, "kutter", 2, {"a": 2}, "t")
    db.write_progress_snapshot(conn, "bummel", 1, {"b": 1}, "t")
    n = db.delete_progress_snapshots(conn, "kutter")
    assert n == 2
    assert db.get_progress_snapshot(conn, "kutter", 1) is None
    assert db.get_progress_snapshot(conn, "bummel", 1) == {"b": 1}


def test_write_snapshot_strips_conn_logon():
    conn = _mem_db()
    import app.database as db
    payload = {"flights": [{"cid": 1, "_conn_logon": "x"}], "total_kg": 5}
    db.write_progress_snapshot(conn, "kutter", 9, payload, "t")
    got = db.get_progress_snapshot(conn, "kutter", 9)
    assert "_conn_logon" not in got["flights"][0]
```

Falls `_mem_db()` nicht existiert: bestehendes Muster aus `tests/test_database.py` übernehmen (dort wird `init_db` auf temporäre/`:memory:`-DB genutzt).

- [ ] **Step 2: Tests laufen → rot**

Run: `pytest tests/test_database.py -k progress_snapshot -v`
Expected: FAIL (Funktionen/ Tabelle fehlen)

- [ ] **Step 3: Umsetzen** (`app/database.py`)

DDL in `_DDL` ergänzen (bei den anderen `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS progress_snapshot (
    kind         TEXT NOT NULL,
    ref_id       INTEGER NOT NULL,
    code_version TEXT NOT NULL,
    computed_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
```

Konstante (bei den übrigen Modul-Konstanten):

```python
_PROGRESS_SNAPSHOT_VERSION = "1"  # bei JEDER Rechen-Ergebnis-Änderung von compute_transport_progress / compute_bummel_standings / _build_race_view im selben Commit erhöhen → invalidiert alle Snapshots
```

Helfer:

```python
def get_progress_snapshot(conn, kind: str, ref_id: int) -> dict | None:
    row = conn.execute(
        "SELECT payload_json FROM progress_snapshot WHERE kind=? AND ref_id=? AND code_version=?",
        (kind, ref_id, _PROGRESS_SNAPSHOT_VERSION),
    ).fetchone()
    return json.loads(row[0]) if row else None  # frisch geparst je Read


def write_progress_snapshot(conn, kind: str, ref_id: int, payload: dict, computed_at: str) -> None:
    for f in payload.get("flights", []) or []:
        if isinstance(f, dict):
            f.pop("_conn_logon", None)  # interne Markierung nie einfrieren (Sicherung)
    conn.execute(
        "INSERT OR REPLACE INTO progress_snapshot (kind, ref_id, code_version, computed_at, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, ref_id, _PROGRESS_SNAPSHOT_VERSION, computed_at, json.dumps(payload)),
    )


def delete_progress_snapshot(conn, kind: str, ref_id: int) -> None:
    conn.execute("DELETE FROM progress_snapshot WHERE kind=? AND ref_id=?", (kind, ref_id))


def delete_progress_snapshots(conn, kind: str) -> int:
    cur = conn.execute("DELETE FROM progress_snapshot WHERE kind=?", (kind,))
    return cur.rowcount
```

`import json` ist in `database.py` bereits vorhanden — prüfen, sonst ergänzen. Hinweis: `write_progress_snapshot` mutiert `payload` (pop) — das ist ok, weil Aufrufer das Dict danach nicht weiterverwenden (bzw. beim Eager-Freeze ohnehin normalisiert wird, Task 6). Falls ein Aufrufer das Dict weiterbraucht, dort vorher kopieren.

- [ ] **Step 4: Tests laufen → grün**

Run: `pytest tests/test_database.py -k progress_snapshot -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: progress_snapshot-Tabelle + Helfer + Versions-Konstante (#66 Task 1)"
```

---

### Task 2: Retention-Parameter auf den Listen-Funktionen

**Files:**
- Modify: `app/database.py` (`list_transport_events`, `list_bummel_races`)
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `_DATA_RETENTION_DAYS` (hier anlegen, falls noch nicht)
- Produces: `list_transport_events(conn, *, since: str | None = None)`, `list_bummel_races(conn, *, since: str | None = None)` (bestehende Aufrufer ohne `since` bleiben unverändert)

- [ ] **Step 1: Failing-Tests** (`tests/test_database.py`)

```python
def test_list_transport_events_retention():
    conn = _mem_db()
    import app.database as db
    _insert_transport_event(conn, id=1, dtstart="2020-01-01T00:00:00Z", dtend="2020-01-01T02:00:00Z")
    _insert_transport_event(conn, id=2, dtstart="2026-07-06T00:00:00Z", dtend="2026-07-06T02:00:00Z")
    all_ev = db.list_transport_events(conn)
    assert {e["id"] for e in all_ev} == {1, 2}
    recent = db.list_transport_events(conn, since="2025-07-06T00:00:00Z")
    assert {e["id"] for e in recent} == {2}


def test_list_bummel_races_retention():
    conn = _mem_db()
    import app.database as db
    _insert_bummel_race(conn, id=1, dtstart="2020-01-01T00:00:00Z", dtend="2020-01-01T02:00:00Z")
    _insert_bummel_race(conn, id=2, dtstart="2026-07-06T00:00:00Z", dtend="2026-07-06T02:00:00Z")
    recent = db.list_bummel_races(conn, since="2025-07-06T00:00:00Z")
    assert {r["id"] for r in recent} == {2}
```

Insert-Helfer: vorhandene Test-Fabriken nutzen (`create_transport_event`/`upsert_calendar_*` bzw. bestehende `_insert_*`-Helfer in der Testdatei). Falls keine existieren, minimal per `conn.execute("INSERT INTO transport_events (...)")` bzw. `bummel_races` anlegen — Spaltenliste aus dem DDL (`app/database.py`) übernehmen.

- [ ] **Step 2: Rot** — `pytest tests/test_database.py -k retention -v` → FAIL (unerwartetes `since`-Argument)

- [ ] **Step 3: Umsetzen** (`app/database.py`)

Zuerst die Funktionen LESEN. Dann `since`-Klausel ergänzen. Beispiel `list_transport_events`:

```python
def list_transport_events(conn, *, since: str | None = None) -> list[dict]:
    where, params = [], []
    if since:
        where.append("(dtend IS NULL OR dtend >= ?)")
        params.append(since)
    sql = f"SELECT {_TRANSPORT_EVENT_COLS} FROM transport_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY dtstart DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
```

`list_bummel_races` analog (bestehende Sortierung/Spalten beibehalten, nur `since`-WHERE ergänzen). `_DATA_RETENTION_DAYS = 365` als Konstante anlegen (Nutzung erst in Task 4/5).

- [ ] **Step 4: Grün** — `pytest tests/test_database.py -k retention -v` → PASS
- [ ] **Step 5: Full-Suite kurz** — `pytest tests/test_database.py -q` (bestehende Aufrufer ohne `since` müssen grün bleiben)
- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: Retention-since-Filter auf list_transport_events/list_bummel_races (#66 Task 2)"
```

---

### Task 3: `compute_transport_progress` — `skip_open_probe`

**Files:**
- Modify: `app/database.py` (`compute_transport_progress`, ~Zeile 4740)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `compute_transport_progress(conn, event, now, *, callsign_prefix="FRS", radius_km=None, skip_open_probe: bool = False)`

- [ ] **Step 1: Failing-Test** — ein Szenario, in dem ein aktuell offener Strecken-Flug ohne Latch existiert; mit `skip_open_probe=True` erscheint er NICHT im Feed, ohne Flag schon.

```python
def test_compute_skip_open_probe_omits_open_branch():
    conn = _mem_db()
    import app.database as db
    ev = _make_running_kutter_with_open_flight(conn)  # offenes Leg auf der Strecke Richtung Ziel, kein Ankunfts-Latch
    now = "2026-07-06T12:00:00Z"
    with_open = db.compute_transport_progress(conn, ev, now, skip_open_probe=False)
    without = db.compute_transport_progress(conn, ev, now, skip_open_probe=True)
    open_keys = {f["flight_key"] for f in with_open["flights"] if f.get("airborne")}
    assert open_keys  # ohne Flag ist der offene Flug als airborne im Feed
    assert not any(f.get("airborne") for f in without["flights"])  # mit Flag nicht mehr
```

Für das Fixture das Muster bestehender Transport-Tests (`tests/test_database.py` / `tests/test_transport*.py`) wiederverwenden: FRS-`flights`-Zeile mit `logoff_time IS NULL` + `position_history` Richtung Ziel im Event-Fenster.

- [ ] **Step 2: Rot** — `pytest tests/test_database.py -k skip_open_probe -v` → FAIL (unerwartetes Argument)

- [ ] **Step 3: Umsetzen** — `compute_transport_progress` LESEN. Signatur um `skip_open_probe: bool = False` erweitern. Den `open_legs_probe`-Aufruf (~4798) und die `open_transport_flights`-Schleife nur ausführen, wenn `not skip_open_probe`:

```python
    if skip_open_probe:
        current_leg_by_cid = {}
    else:
        open_legs_probe = canonicalize_legs(conn, start=load_start, end=now, callsign_prefix=callsign_prefix)
        current_leg_by_cid = { ... }  # unverändert
    ...
    if not skip_open_probe:
        for f in open_transport_flights(conn, callsign_prefix):
            ...  # gesamter Offen-Zweig unverändert eingerückt
```

Achtung: die Rückgabe-Aggregate (`reserved_total_kg` etc.), die aus dem Offen-Zweig gespeist werden, müssen bei übersprungenem Zweig sauber `0`/leer bleiben — prüfen, dass keine Variable unref bleibt.

- [ ] **Step 4: Grün** — `pytest tests/test_database.py -k skip_open_probe -v` → PASS
- [ ] **Step 5: Regression** — `pytest tests/ -k transport -q`
- [ ] **Step 6: Commit**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: compute_transport_progress skip_open_probe (#66 Task 3)"
```

---

### Task 4: `_frozen_or_compute` + Kutter-Endpoints + Overlays

**Files:**
- Modify: `app/main.py` (neuer Helfer; `/api/transport/events` ~1660, `/api/transport/event/{id}` ~1675, Kutter-Badge ~1735/1780, `GET /api/admin/transport/payloads` ~1893)
- Test: `tests/test_main.py` / `tests/test_admin_api.py`

**Interfaces:**
- Consumes (Task 1/2/3): `get_progress_snapshot`, `write_progress_snapshot`, `compute_transport_progress(..., skip_open_probe=)`, `list_transport_events(since=)`, `_DATA_RETENTION_DAYS`
- Produces:
  - `_frozen_or_compute(conn, kind: str, ref_id: int, *, finished: bool, compute_fn, now: str) -> dict`
  - `_retention_since(now: str) -> str` (now − `_DATA_RETENTION_DAYS` Tage, ISO-Z)
  - `_kutter_progress(conn, ev, now, prefix) -> dict` (wrappt frozen/compute + Overlays)

- [ ] **Step 1: Failing-Tests**

```python
def test_transport_events_uses_snapshot(monkeypatch):
    # summarized-Event mit Snapshot → compute_transport_progress NICHT aufgerufen
    ... setup: 1 summarized Event, write_progress_snapshot mit {"total_kg": 42, ...}
    called = {"n": 0}
    monkeypatch.setattr("app.main.compute_transport_progress", lambda *a, **k: called.__setitem__("n", called["n"]+1) or {})
    resp = client.get("/api/transport/events")
    assert called["n"] == 0
    assert any(e["total_kg"] == 42 for e in resp.json())


def test_kutter_snapshot_overlays_fresh_quips():
    # Snapshot ohne quip; danach summary_quip am Event gesetzt + Flug-quip im Store → Detail zeigt sie
    ...
    assert resp.json()["summary_quip"] == "Feierabend!"
    assert resp.json()["flights"][0]["quip"] == "Guter Flug!"


def test_admin_payloads_unmapped_uses_snapshot(monkeypatch):
    # summarized-Event → payloads-Endpoint ruft compute nicht je Event
    ...
```

- [ ] **Step 2: Rot** — `pytest tests/test_main.py -k "snapshot or overlay" -v` → FAIL

- [ ] **Step 3: Umsetzen** (`app/main.py`)

```python
def _retention_since(now: str) -> str:
    from datetime import datetime, timedelta, timezone
    from app.database import _DATA_RETENTION_DAYS
    dt = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt - timedelta(days=_DATA_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _frozen_or_compute(conn, kind, ref_id, *, finished, compute_fn, now):
    if finished:
        snap = get_progress_snapshot(conn, kind, ref_id)
        if snap is not None:
            return snap
        result = compute_fn()
        write_progress_snapshot(conn, kind, ref_id, result, now)
        conn.commit()
        return result
    return compute_fn()


def _kutter_progress(conn, ev, now, prefix):
    finished = bool(ev.get("summarized_at"))
    progress = _frozen_or_compute(
        conn, "kutter", ev["id"], finished=finished, now=now,
        compute_fn=lambda: compute_transport_progress(
            conn, ev, now, callsign_prefix=prefix, skip_open_probe=finished),
    )
    # frische Überlagerung (nicht eingefroren): summary_quip + Pro-Flug-Quips
    progress = dict(progress)
    progress["summary_quip"] = ev.get("summary_quip")
    quips = get_transport_quips(conn, ev["id"])  # {flight_key: quip}  — echte Signatur beim Umsetzen prüfen
    if quips:
        for f in progress.get("flights", []):
            q = quips.get(f.get("flight_key"))
            if q:
                f["quip"] = q
    return progress
```

`get_transport_quips` bzw. der tatsächliche Quip-Store-Zugriff: beim Umsetzen die vorhandene Funktion suchen (`grep quip app/database.py`) und die echte Signatur/den Schlüssel (flight_key vs. cid:lo) verwenden. Status-Overlay `_transport_status(ev, now)` nur, falls das Feld ausgeliefert wird.

Endpoints umstellen:
- `/api/transport/events`: `list_transport_events(conn, since=_retention_since(now))`, je Event `_transport_event_meta(ev, _kutter_progress(conn, ev, now, prefix))`.
- `/api/transport/event/{id}`: `_kutter_progress(...)` statt direktem `compute_transport_progress`.
- Kutter-Badge-Endpoints (~1735/1780): `_kutter_progress(...)` als Datenquelle für `_kutter_badge_data`.
- `GET /api/admin/transport/payloads`: die Event-Schleife für `unmapped_types` auf `_kutter_progress(...)` umstellen (LESEN, was der Endpoint genau tut — ~1893–1915).

- [ ] **Step 4: Grün** — `pytest tests/test_main.py -k "snapshot or overlay or payloads" -v`
- [ ] **Step 5: Regression** — `pytest tests/ -k "transport" -q`
- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py tests/test_admin_api.py
git commit -m "feat: Kutter-Endpoints lesen aus Snapshot + Quip/Status-Overlay + Retention (#66 Task 4)"
```

---

### Task 5: Bummel-Endpoints — Freeze + Metadaten aus DB-Zeile + Status-Refresh

**Files:**
- Modify: `app/main.py` (`_build_race_view` ~963 unverändert lassen; `/api/bummel/races` ~991, `/api/bummel/race/{id}` ~1012, Bummel-Badge ~1074/1125)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `_frozen_or_compute`, `_retention_since`, `list_bummel_races(since=)`, `get_progress_snapshot`
- Produces: `_bummel_view(conn, race, now, *, force_reveal=False) -> dict` (wrappt frozen/compute + Status-Overlay)

- [ ] **Step 1: Failing-Tests**

```python
def test_bummel_race_lazy_freezes_on_first_read(monkeypatch):
    # revealed_at gesetzt UND now>=dtend → erster GET schreibt Snapshot, zweiter ruft compute nicht mehr
    ...
    assert calls["build_race_view"] == 1  # nach zwei GETs

def test_bummel_force_reveal_before_dtend_not_frozen():
    # revealed_at gesetzt, aber now < dtend → kein Snapshot, immer live
    ...
    assert get_progress_snapshot(conn, "bummel", race_id) is None

def test_bummel_status_refreshed_from_snapshot():
    # Status kommt aus _race_status(race, now), nicht aus payload
    ...

def test_bummel_metadata_from_db_row_not_snapshot():
    # Rennen nach Reveal umbenannt → Liste zeigt neuen Namen trotz altem Snapshot
    ...
```

- [ ] **Step 2: Rot**

- [ ] **Step 3: Umsetzen**

```python
def _bummel_view(conn, race, now, *, force_reveal=False):
    finished = bool(race.get("revealed_at")) and now >= (race.get("dtend") or "")
    view = _frozen_or_compute(
        conn, "bummel", race["id"], finished=finished, now=now,
        compute_fn=lambda: _build_race_view(conn, race, now, force_reveal=force_reveal),
    )
    view = dict(view)
    view["status"] = _race_status(race, now)          # frisch
    view["name"] = race.get("name") or ""              # Metadaten aus DB-Zeile
    view["route"] = race.get("route")
    view["dtstart"] = race.get("dtstart")
    view["dtend"] = race.get("dtend")
    return view
```

- `/api/bummel/races`: `list_bummel_races(conn, since=_retention_since(now))`; je Rennen `_bummel_view(...)` statt direktem `_build_race_view`; die List-Teilmenge (id/name/route/dtstart/dtend/status/participant_count/…) daraus picken.
- `/api/bummel/race/{id}`: `_bummel_view(...)`.
- Bummel-Badge (~1074/1125): `_bummel_view(...)` als Datenquelle.
- `update_bummel_reveals(conn, now, ...)` VOR der Liste bleibt unverändert (Reveal-Latch setzen).
- `force_reveal=True` (Admin-Vorschau, `main.py` ~) NICHT einfrieren: dort weiter direkt `_build_race_view(..., force_reveal=True)` verwenden (nicht über `_bummel_view`), damit die Vorschau nie Snapshots schreibt.

- [ ] **Step 4: Grün** — `pytest tests/test_main.py -k bummel -v`
- [ ] **Step 5: Regression** — `pytest tests/ -k bummel -q`
- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: Bummel-Endpoints Freeze (revealed_at+now>=dtend) + Metadaten/Status frisch + Retention (#66 Task 5)"
```

---

### Task 6: Poller — Eager-Freeze Kutter + Gate + Quip-Fortführung

**Files:**
- Modify: `app/poller.py` (`_check_transport_events`, ~1195–1290)
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `write_progress_snapshot`, `get_progress_snapshot`
- Produces: (keine neue öffentliche API; Verhaltensänderung im Job)

- [ ] **Step 1: Failing-Tests**

```python
def test_poller_writes_kutter_snapshot_on_summarize():
    # dtend erreicht, niemand unterwegs → summarized latcht → Snapshot existiert, in_air/airborne=False
    ...
    snap = get_progress_snapshot(conn, "kutter", ev_id)
    assert snap is not None
    assert all(not f.get("airborne") and not f.get("in_air") for f in snap["flights"])

def test_poller_skips_compute_when_summarized(monkeypatch):
    # Event bereits summarized + Snapshot → compute_transport_progress nicht aufgerufen
    ...

def test_poller_still_generates_quips_after_summarize():
    # Snapshot vorhanden, aber Flug-Quips fehlen → Folge-Poll erzeugt sie (aus Snapshot-flights), ohne compute
    ...
```

- [ ] **Step 2: Rot**

- [ ] **Step 3: Umsetzen** — `_check_transport_events` LESEN. Umbau der Schleife:

```python
for ev in list_transport_events(conn):   # since=None (Poller sieht alles)
    dtstart = ev.get("dtstart") or ""
    if now < dtstart:
        continue
    if ev.get("summarized_at"):
        # abgeschlossen: kein detect_losses / kein teures compute mehr.
        # Nur noch offene Quip-Jobs aus dem Snapshot nachsammeln.
        snap = get_progress_snapshot(conn, "kutter", ev["id"])
        if snap is not None and do_quips:
            _enqueue_missing_quip_jobs(conn, ev, snap, quip_jobs)  # nutzt snap["flights"], KEIN compute
        continue
    # --- nicht abgeschlossen: bisheriger Ablauf ---
    if ev.get("destination"):
        detect_transport_losses(conn, ev, callsign_prefix=self.callsign_prefix)
    progress = compute_transport_progress(conn, ev, now, callsign_prefix=self.callsign_prefix)
    ... started/goal-Latches unverändert ...
    if dtend and now >= dtend and not ev.get("summarized_at") and not transport_anyone_in_progress(...):
        if set_transport_summarized(conn, ev["id"], now):
            # Eager-Freeze: in_air/airborne normalisieren, dann einfrieren
            for f in progress.get("flights", []):
                f["in_air"] = False
                f["airborne"] = False
            write_progress_snapshot(conn, "kutter", ev["id"], progress, now)
            ... bestehende Feierabend-Push/Quip-Logik ...
```

`_enqueue_missing_quip_jobs`: die vorhandene Pro-Flug-Quip-Logik (heute im nicht-summarized-Zweig, ~1266–1282) so refaktorieren, dass sie mit einer gegebenen `flights`-Liste + bereits vorhandenen Quips (`get_transport_quips`) arbeitet und fehlende Jobs an `quip_jobs` hängt (max. 8/Lauf-Kappung erhalten). Beide Zweige (aktiv + summarized) rufen denselben Helfer. Exakte bestehende Quip-Mechanik beim Umsetzen LESEN und wiederverwenden — nicht neu erfinden.

Achtung Reihenfolge: `write_progress_snapshot` NACH `set_transport_summarized`, im selben `if`. Snapshot enthält bewusst noch keine Quips (die überlagert der Endpoint-Read, Task 4).

- [ ] **Step 4: Grün** — `pytest tests/test_poller.py -k "summarize or snapshot or quip" -v`
- [ ] **Step 5: Regression** — `pytest tests/test_poller.py -q`
- [ ] **Step 6: Commit**

```bash
git add app/poller.py tests/test_poller.py
git commit -m "feat: Poller friert Kutter beim Feierabend ein + Gate + Quip-Fortführung (#66 Task 6)"
```

---

### Task 7: Invalidierungs-Hooks

**Files:**
- Modify: `app/main.py` (`admin_update_transport_event` ~1840, `admin_delete_transport_event` ~1881, `/payloads` ~1916, `/default-payload` ~1961, Bummel `/override` ~1597/1621, Rennen-Edit ~1500, `/hide` ~1561, Rennen-Delete ~1518); `app/database.py` (`upsert_calendar_transport_event` ~3935, `upsert_calendar_bummel_race` ~3660)
- Test: `tests/test_admin_api.py`, `tests/test_database.py`

**Interfaces:**
- Consumes: `delete_progress_snapshot`, `delete_progress_snapshots`

- [ ] **Step 1: Failing-Tests**

```python
def test_admin_update_kutter_clears_snapshot():
    # Snapshot vorhanden; POST update (auch mit LEEREM Body) → Snapshot weg
    ...
def test_admin_payload_change_clears_all_kutter_snapshots():
    ...
def test_admin_bummel_override_clears_snapshot():
    ...
def test_calendar_sync_no_value_change_keeps_snapshot():
    # upsert mit identischen Werten → Snapshot bleibt
    ...
def test_calendar_sync_value_change_clears_snapshot():
    # upsert mit geänderter route/dtstart/dtend → Snapshot weg
    ...
```

- [ ] **Step 2: Rot**

- [ ] **Step 3: Umsetzen**
- `admin_update_transport_event`: `delete_progress_snapshot(conn, "kutter", event_id)` **immer** (auch wenn `fields` leer → der `if fields:`-Guard darf den Delete nicht überspringen; Delete VOR/außerhalb des Guards + `conn.commit()`).
- `admin_delete_transport_event`: `delete_progress_snapshot(conn, "kutter", event_id)`.
- `/payloads`, `/default-payload`: `delete_progress_snapshots(conn, "kutter")`.
- Bummel `/override` (setzen+löschen), Rennen-Edit, `/hide`, Rennen-Delete: `delete_progress_snapshot(conn, "bummel", race_id)` (Edit ebenfalls unbedingt).
- `upsert_calendar_transport_event` / `upsert_calendar_bummel_race`: VOR dem `ON CONFLICT`-Update die vorhandene Zeile lesen; nur wenn sich `route`/`dtstart`/`dtend`/`destination` (Kutter) bzw. `route`/`dtstart`/`dtend` (Bummel) tatsächlich ändern, `delete_progress_snapshot(conn, kind, id)` aufrufen. Die betroffene `id` aus der bestehenden Zeile (via `calendar_uid`) ermitteln.

- [ ] **Step 4: Grün** — `pytest tests/test_admin_api.py tests/test_database.py -k "snapshot or clears or calendar_sync" -v`
- [ ] **Step 5: Regression** — `pytest tests/ -k "admin or calendar" -q`
- [ ] **Step 6: Commit**

```bash
git add app/main.py app/database.py tests/test_admin_api.py tests/test_database.py
git commit -m "feat: Snapshot-Invalidierung bei Edit/Payload/Override/Kalender-Wertänderung (#66 Task 7)"
```

---

### Task 8: Docs + CHANGELOG + Version

**Files:**
- Modify: `app/CHANGELOG.json`, `docs/architecture.md`, `docs/api.md`, `README.md`
- (Version wird aus `CHANGELOG[0]` via `app/version.py` abgeleitet — kein separater Bump nötig)

- [ ] **Step 1: CHANGELOG-Eintrag** oben in `app/CHANGELOG.json` (deutsche „ "-Quotes; Version = nächste Minor, z. B. `8.10.0`; **kein** `highlight`):

```json
{
  "version": "8.10.0",
  "date": "2026-07-06",
  "title": "Abgeschlossene Kutter- und Bummel-Events werden eingefroren — Übersicht lädt schneller",
  "items": [
    "Fortschritt/Wertung abgeschlossener Spezial-Events wird beim Abschluss einmal gespeichert (Snapshot) statt bei jedem Aufruf neu gerechnet — die Event- und Bummel-Übersicht öffnet spürbar schneller und wird nicht mehr mit der Zeit träge.",
    "Anzeige der letzten 12 Monate: ältere Einträge werden ausgeblendet (nichts wird gelöscht).",
    "Korrekturen an einem abgeschlossenen Event greifen beim erneuten Speichern im Admin."
  ]
}
```

- [ ] **Step 2: JSON valide?** Run: `python -c "import json; json.load(open('app/CHANGELOG.json'))"` → kein Fehler. Version prüfen: `python -c "from app.version import VERSION; print(VERSION)"` → `8.10.0`.
- [ ] **Step 3: `docs/architecture.md`** — Abschnitt zu `progress_snapshot` (Tabelle, `code_version`/`_PROGRESS_SNAPSHOT_VERSION`, Eager-Freeze Kutter im Poller, Lazy-Freeze Bummel im Endpoint, versions-gefilterter Read + Overlays, Invalidierungspfade, `_DATA_RETENTION_DAYS`-Anzeigegrenze).
- [ ] **Step 4: `docs/api.md`** — Retention-Hinweis bei `/api/transport/events` + `/api/bummel/races` (nur letzte 365 Tage; Admin-Listen ungefiltert). Kein neuer Endpoint.
- [ ] **Step 5: `README.md`** — kurzer Satz: abgeschlossene Spezial-Events sind eingefroren, Korrektur via Admin-Bearbeitung / Versions-Konstante.
- [ ] **Step 6: Gesamte Suite** — Run: `pytest tests/ -q` → grün.
- [ ] **Step 7: Commit**

```bash
git add app/CHANGELOG.json docs/architecture.md docs/api.md README.md
git commit -m "docs: Snapshot-Freeze + Retention dokumentiert, CHANGELOG v8.10.0 (#66 Task 8)"
```

---

## Abschluss (nach allen Tasks — NICHT ohne Nutzer-Bestätigung pushen)

- [ ] `pytest tests/ -v` komplett grün.
- [ ] Finales Whole-Branch-Review (superpowers:requesting-code-review).
- [ ] Git-Tag `v8.10.0`.
- [ ] **Nutzer-Bestätigung einholen**, DANN `git push origin main` (+ `git push origin v8.10.0`).
- [ ] Nach Deploy verifizieren (Spec-Abschnitt „Verifikation"): `/api/transport/events` + `/api/bummel/races` messen (deutlich schneller, wächst nicht mit Alter/Zahl); Snapshots der Bestands-Events da; Event-antippen-Hebel; Retention-Grenze.

## Self-Review-Notiz (writing-plans)

- Spec-Abdeckung geprüft: Snapshot-Tabelle (T1), Retention (T2/T4/T5), skip_open_probe (T3), Kutter-Read+Overlays+payloads (T4), Bummel-Read+Freeze-Bedingung+Metadaten (T5), Poller-Eager+Gate+Quips (T6), Invalidierung inkl. Kalender-Sync + leerer-Body-Hebel (T7), Doku/Version (T8). Alle Fable-Funde 1–10 sind in T3–T7 verankert.
- Typen konsistent: `_frozen_or_compute`, `_kutter_progress`, `_bummel_view`, `get/write/delete_progress_snapshot(s)`, `skip_open_probe`, `since` durchgängig gleich benannt.
- Offene Umsetzungs-Unsicherheit (bewusst): exakte Quip-Store-Funktion/-Schlüssel (`get_transport_quips`?) und die genaue `force_reveal`-Vorschau-Stelle beim Umsetzen im Code verifizieren — deshalb je Task „LESEN"-Hinweis.
