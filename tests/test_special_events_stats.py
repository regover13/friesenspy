"""Wiring-Test für GET /api/stats/special-events — Aggregation über abgeschlossene Spezial-Events."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.main as main
from app.database import (
    get_connection, init_db, create_transport_event, set_transport_summarized,
    write_progress_snapshot, upsert_calendar_bummel_race, list_bummel_races,
    set_bummel_revealed,
)


def _iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _patch(monkeypatch, db):
    monkeypatch.setattr(main, "get_settings",
                        lambda: SimpleNamespace(DB_PATH=db, CALLSIGN_PREFIX="FRS"))


def test_special_events_only_finished_in_window(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, db)
    now = datetime.now(timezone.utc)
    conn = get_connection(db)

    # (a) abgeschlossener Kutter IM Fenster, mit Fracht + Verlusten
    dtend_ok = _iso(now - timedelta(days=2))
    eid = create_transport_event(conn, name="Nachschub", route="EDWG,EDXH",
                                 dtstart=_iso(now - timedelta(days=2, hours=3)),
                                 dtend=dtend_ok, destination="EDXH")
    set_transport_summarized(conn, eid, dtend_ok)
    write_progress_snapshot(conn, "kutter", eid, {
        "flight_count": 3, "total_kg": 900.0,
        "participants": [{"cid": 1}, {"cid": 2}],
        "losses": [{"loss_kind": "sunk", "lost_kg": 200.0}],
        "flights": [], "cargo": [], "route": ["EDWG", "EDXH"], "destination": "EDXH",
        "target_kg": None, "loaded_count": 2,
    }, dtend_ok)

    # (b) abgeschlossener Kutter AUSSERHALB des 30-Tage-Fensters -> zählt nicht
    dtend_old = _iso(now - timedelta(days=200))
    eid2 = create_transport_event(conn, name="Alt", route="EDWG,EDXH",
                                  dtstart=_iso(now - timedelta(days=200, hours=3)),
                                  dtend=dtend_old, destination="EDXH")
    set_transport_summarized(conn, eid2, dtend_old)
    write_progress_snapshot(conn, "kutter", eid2, {
        "flight_count": 9, "total_kg": 5000.0, "participants": [{"cid": 9}],
        "losses": [], "flights": [], "cargo": [], "route": ["EDWG", "EDXH"],
        "destination": "EDXH", "target_kg": None, "loaded_count": 9,
    }, dtend_old)

    # (c) laufender Kutter (kein summarized_at) -> zählt nicht
    create_transport_event(conn, name="Laeuft", route="EDWG,EDXH",
                           dtstart=_iso(now - timedelta(hours=1)),
                           dtend=_iso(now + timedelta(hours=3)), destination="EDXH")
    conn.commit()
    conn.close()

    res = asyncio.run(main.get_special_events_stats(days=30))

    assert res["kutter"]["event_count"] == 1          # nur (a)
    assert res["kutter"]["flights"] == 3
    assert res["kutter"]["participations"] == 2
    assert res["kutter"]["delivered_kg"] == 900.0
    assert res["kutter"]["sunk_kg"] == 200.0 and res["kutter"]["sunk_count"] == 1
    assert res["kutter"]["stolen_count"] == 0
    # Bummel leer -> Nullstruktur
    assert res["bummel"]["race_count"] == 0
    assert res["bummel"]["avg_absolute_min"] is None


def test_special_events_aggregates_finished_bummel(tmp_path, monkeypatch):
    """Symmetrie zum Kutter-Test: ein abgeschlossenes (enthülltes) Bummel-Rennen im Fenster wird
    aus dem Snapshot korrekt aggregiert (race_count/participations/legs/avg)."""
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, db)
    now = datetime.now(timezone.utc)
    dtend = _iso(now - timedelta(days=1))
    conn = get_connection(db)
    upsert_calendar_bummel_race(conn, {
        "uid": "r1", "summary": "FriesenFliegerBummel Ostfriesland",
        "route": "EDWF,EDWG,EDWR",
        "dtstart": _iso(now - timedelta(days=1, hours=4)), "dtend": dtend,
    })
    conn.commit()
    rid = list_bummel_races(conn)[0]["id"]
    set_bummel_revealed(conn, rid, dtend)
    write_progress_snapshot(conn, "bummel", rid, {
        "id": rid, "participant_count": 3, "count": 2, "average_min": 90.0,
        "complete": [{"cid": 1, "leg_count": 3}, {"cid": 2, "leg_count": 3}],
        "incomplete": [{"cid": 3, "leg_count": 1}],
        "route": ["EDWF", "EDWG", "EDWR"],
    }, dtend)
    conn.commit()
    conn.close()

    res = asyncio.run(main.get_special_events_stats(days=365))
    assert res["bummel"]["race_count"] == 1
    assert res["bummel"]["participations"] == 3
    assert res["bummel"]["legs"] == 7            # 3 + 3 + 1 über complete+incomplete
    assert res["bummel"]["avg_absolute_min"] == 90.0
    assert res["kutter"]["event_count"] == 0     # kein Kutter geseedet


def test_special_events_shape(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, db)
    res = asyncio.run(main.get_special_events_stats(days=365))
    assert set(res.keys()) == {"kutter", "bummel"}
    assert set(res["kutter"].keys()) == {
        "event_count", "participations", "flights", "delivered_kg",
        "sunk_kg", "sunk_count", "stolen_kg", "stolen_count"}
    assert set(res["bummel"].keys()) == {
        "race_count", "participations", "legs", "avg_absolute_min"}
