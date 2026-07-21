"""Wiring-Tests für die Bummel-Endpoints (app/main.py) — Renn-basiert + Fairness-Verdeckung.

Ruft die Endpoint-Coroutinen direkt auf (ohne Lifespan/Poller) gegen eine geseedete Temp-DB.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.main as main
from app.database import (
    get_connection,
    get_progress_snapshot,
    init_db,
    list_bummel_races,
    set_bummel_revealed,
    upsert_calendar_bummel_race,
)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _patch_settings(monkeypatch, db):
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(DB_PATH=db, CALLSIGN_PREFIX="FRS"),
    )


def _seed(db, *, dtstart, dtend, with_open=False):
    conn = get_connection(db)
    conn.execute("INSERT INTO pilots (cid, name, added_at) VALUES (100, 'Anna', ?)", (dtstart,))

    def add(cid, dep, arr, block, logon, logoff):
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
            "logon_time, logoff_time, duration_min, distance_nm, block_min) "
            "VALUES (?, ?, 'C172', ?, ?, ?, ?, 30, 50, ?)",
            (cid, f"FRS{cid}", dep, arr, logon, logoff, block),
        )

    base = datetime.fromisoformat(dtstart.replace("Z", "+00:00"))
    add(100, "EDWF", "EDWG", 30, _iso(base + timedelta(minutes=5)), _iso(base + timedelta(minutes=35)))
    add(100, "EDWG", "EDWR", 30, _iso(base + timedelta(minutes=45)), _iso(base + timedelta(minutes=75)))

    if with_open:
        conn.execute("INSERT INTO pilots (cid, name, added_at) VALUES (200, 'Bert', ?)", (dtstart,))
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
            "logon_time, logoff_time, duration_min, distance_nm, block_min) "
            "VALUES (200, 'FRS200', 'C172', 'EDWF', 'EDWG', ?, NULL, NULL, NULL, NULL)",
            (_iso(base + timedelta(minutes=10)),),
        )

    upsert_calendar_bummel_race(conn, {
        "uid": "race1", "summary": "FriesenFliegerBummel Ostfriesland",
        "route": "EDWF,EDWG,EDWR", "dtstart": dtstart, "dtend": dtend,
    })
    conn.commit()
    rid = list_bummel_races(conn)[0]["id"]
    conn.close()
    return rid


def test_active_running_is_redacted(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    _seed(db, dtstart=_iso(now - timedelta(hours=1)), dtend=_iso(now + timedelta(hours=3)), with_open=True)

    view = asyncio.run(main.get_bummel_active())
    assert view is not None
    assert view["status"] == "running"
    assert view["revealed"] is False
    # Teilnehmerliste statt Ranking; KEINE Zeiten/Schnitt im JSON
    assert "participants" in view and "complete" not in view
    blob = json.dumps(view)
    for leak in ("total_min", "block_min", "average", "delta", "rank"):
        assert leak not in blob, f"Leak {leak} in laufendem Rennen"
    # Bert (offener Flug) taucht als unterwegs auf
    assert 200 in {p["cid"] for p in view["in_progress"]}


def test_open_bummel_legs_roundtrip_plan_is_shown(tmp_path, monkeypatch):
    """Rundkurs-Flugplan (dep==arr, beide auf der Strecke) muss als „unterwegs" erscheinen.

    Regression: der frühere `dep != arr`-Filter blendete einen Rundkurs-Plan (z. B. EDKB→EDKB,
    ein Flugplan für die ganze Runde) komplett aus — der Pilot erschien nie „unterwegs",
    obwohl Start UND Ziel auf der Strecke liegen.
    """
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    start = _iso(now - timedelta(hours=1))
    end = _iso(now + timedelta(hours=3))
    conn = get_connection(db)
    conn.execute("INSERT INTO pilots (cid, name, added_at) VALUES (300, 'Rund', ?)", (start,))
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
        "logon_time, logoff_time, duration_min, distance_nm, block_min) "
        "VALUES (300, 'FRS300', 'C172', 'EDWF', 'EDWF', ?, NULL, NULL, NULL, NULL)",
        (_iso(now - timedelta(minutes=30)),),
    )
    conn.commit()
    legs = main._open_bummel_legs(conn, {"EDWF", "EDWG", "EDWR"}, start, end)
    assert 300 in {l["cid"] for l in legs}, "Rundkurs-Plan (dep==arr) muss unterwegs erscheinen"


def test_race_revealed_shows_full(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    rid = _seed(db, dtstart=_iso(now - timedelta(hours=5)), dtend=_iso(now - timedelta(hours=1)))
    # Rennen ist vorbei und niemand unterwegs → Endpoint enthüllt beim Lesen automatisch
    view = asyncio.run(main.get_bummel_race_endpoint(rid))
    assert view["status"] == "revealed"
    assert view["revealed"] is True
    assert "average_min" in view
    assert view["complete"][0]["total_min"] == 60


def test_races_list_has_status_and_count(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    _seed(db, dtstart=_iso(now - timedelta(hours=1)), dtend=_iso(now + timedelta(hours=3)))
    races = asyncio.run(main.get_bummel_races())
    assert len(races) == 1
    assert races[0]["status"] == "running"
    assert races[0]["participant_count"] == 1


def test_active_none_when_no_race(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    assert asyncio.run(main.get_bummel_active()) is None


# ---------------------------------------------------------------------------
# #66 Task 5: Freeze abgeschlossener Rennen (revealed_at + now>=dtend) aus dem
# progress_snapshot, Metadaten aus der DB-Zeile, Status immer frisch.
# ---------------------------------------------------------------------------

def test_bummel_race_lazy_freezes_on_first_read(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=5))
    dtend = _iso(now - timedelta(hours=1))
    rid = _seed(db, dtstart=dtstart, dtend=dtend)
    conn = get_connection(db)
    set_bummel_revealed(conn, rid, dtend)
    conn.commit()
    conn.close()

    calls = {"n": 0}
    orig = main._build_race_view

    def _spy(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(main, "_build_race_view", _spy)

    view1 = asyncio.run(main.get_bummel_race_endpoint(rid))
    view2 = asyncio.run(main.get_bummel_race_endpoint(rid))

    assert view1["status"] == "revealed"
    assert view2["status"] == "revealed"
    assert calls["n"] == 1  # zweiter Read kommt aus dem Snapshot

    conn = get_connection(db)
    snap = get_progress_snapshot(conn, "bummel", rid)
    conn.close()
    assert snap is not None


def test_bummel_force_reveal_before_dtend_not_frozen(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    # dtend liegt noch in der Zukunft — revealed_at aber schon gesetzt (Admin-Override-Fall).
    dtstart = _iso(now - timedelta(hours=1))
    dtend = _iso(now + timedelta(hours=3))
    rid = _seed(db, dtstart=dtstart, dtend=dtend)
    conn = get_connection(db)
    set_bummel_revealed(conn, rid, _iso(now))
    conn.commit()
    conn.close()

    view = asyncio.run(main.get_bummel_race_endpoint(rid))

    assert view["revealed"] is True  # bereits enthüllt (Override)
    conn = get_connection(db)
    snap = get_progress_snapshot(conn, "bummel", rid)
    conn.close()
    assert snap is None  # aber NICHT eingefroren, weil now < dtend


def test_bummel_status_refreshed_from_snapshot(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=5))
    dtend = _iso(now - timedelta(hours=1))
    rid = _seed(db, dtstart=dtstart, dtend=dtend)
    conn = get_connection(db)
    set_bummel_revealed(conn, rid, dtend)
    conn.commit()
    conn.close()

    # Erster Read friert ein (Snapshot enthält status="revealed" wie berechnet).
    asyncio.run(main.get_bummel_race_endpoint(rid))
    conn = get_connection(db)
    snap = get_progress_snapshot(conn, "bummel", rid)
    conn.close()
    assert snap is not None
    # Snapshot manuell mit einem veralteten/falschen Status verfälschen.
    conn = get_connection(db)
    import json as _json
    conn.execute(
        "UPDATE progress_snapshot SET payload_json = ? WHERE kind='bummel' AND ref_id=?",
        (_json.dumps(dict(snap, status="scheduled")), rid),
    )
    conn.commit()
    conn.close()

    view = asyncio.run(main.get_bummel_race_endpoint(rid))
    assert view["status"] == "revealed"  # frisch aus _race_status, nicht aus dem (verfälschten) Snapshot


def test_bummel_metadata_from_db_row_not_snapshot(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch_settings(monkeypatch, db)
    now = datetime.now(timezone.utc)
    dtstart = _iso(now - timedelta(hours=5))
    dtend = _iso(now - timedelta(hours=1))
    rid = _seed(db, dtstart=dtstart, dtend=dtend)
    conn = get_connection(db)
    set_bummel_revealed(conn, rid, dtend)
    conn.commit()
    conn.close()

    # Erster Read friert ein.
    asyncio.run(main.get_bummel_race_endpoint(rid))

    # Rennen nach der Enthüllung umbenannt.
    conn = get_connection(db)
    conn.execute("UPDATE bummel_races SET name = ? WHERE id = ?", ("Neuer Name", rid))
    conn.commit()
    conn.close()

    detail = asyncio.run(main.get_bummel_race_endpoint(rid))
    assert detail["name"] == "Neuer Name"
    # #66 Review-Fund 1: `route` MUSS ein Array bleiben (public_bummel_view liefert [ICAO,…]);
    # ein Überlagern mit dem DB-CSV-String bräche `route.join(...)` im Frontend.
    assert isinstance(detail["route"], list)

    races = asyncio.run(main.get_bummel_races())
    assert races[0]["name"] == "Neuer Name"
    assert isinstance(races[0]["route"], list)
