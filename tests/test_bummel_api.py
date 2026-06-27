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
