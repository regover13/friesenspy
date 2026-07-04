"""Test für den cid-basierten Track-Endpoint (/api/pilots/{cid}/track, #v8.1.0).

Bedient GPS-Legs OHNE flights-Zeile (id=None) — Track rein über cid + Zeitfenster.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.main as main
from app.database import ensure_pilot, get_connection, init_db


def _setup(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(DB_PATH=p, CALLSIGN_PREFIX="FRS", STATSIM_API_KEY=None),
    )
    return p


def _pos(conn, cid, ts, lat, lon, alt, gs):
    conn.execute(
        "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,groundspeed,"
        "heading,ts) VALUES (?,?,?,?,?,?,0,?)",
        (cid, "FRS99", lat, lon, alt, gs, ts),
    )


def test_track_window_returns_positions_without_flights_row(tmp_path, monkeypatch):
    """Kernfall #v8.1.0: ein GPS-Leg ohne flights-id lädt seinen Track trotzdem über cid+Fenster."""
    p = _setup(tmp_path, monkeypatch)
    conn = get_connection(p)
    ensure_pilot(conn, 7001, "Pilot 7001")
    _pos(conn, 7001, "2026-07-02T10:00:00Z", 50.0, 7.0, 300, 0)
    _pos(conn, 7001, "2026-07-02T10:05:00Z", 50.1, 7.1, 2000, 90)
    _pos(conn, 7001, "2026-07-02T10:10:00Z", 50.2, 7.2, 3000, 110)
    # Position AUSSERHALB des Fensters (späterer Flug) — darf NICHT mitkommen.
    _pos(conn, 7001, "2026-07-02T18:00:00Z", 51.0, 8.0, 500, 60)
    conn.commit()
    conn.close()

    res = asyncio.run(main.get_pilot_track_window(
        7001, logon="2026-07-02T10:00:00Z", logoff="2026-07-02T10:10:00Z"
    ))
    assert len(res) == 3
    assert res[0]["ts"] == "2026-07-02T10:00:00Z"
    assert res[-1]["ts"] == "2026-07-02T10:10:00Z"
    assert all(r["ts"] <= "2026-07-02T10:10:00Z" for r in res)


def test_track_window_upper_bound_excludes_later_flight(tmp_path, monkeypatch):
    """Obergrenze (last_pos_ts) begrenzt sauber — kein Übergreifen auf spätere Positionen."""
    p = _setup(tmp_path, monkeypatch)
    conn = get_connection(p)
    ensure_pilot(conn, 7002, "Pilot 7002")
    _pos(conn, 7002, "2026-07-02T10:00:00Z", 50.0, 7.0, 300, 0)
    _pos(conn, 7002, "2026-07-02T10:03:00Z", 50.1, 7.1, 2000, 90)
    _pos(conn, 7002, "2026-07-05T09:00:00Z", 52.0, 9.0, 400, 70)  # Tage später
    conn.commit()
    conn.close()

    res = asyncio.run(main.get_pilot_track_window(
        7002, logon="2026-07-02T10:00:00Z", logoff="2026-07-02T10:03:00Z"
    ))
    assert len(res) == 2
    assert res[-1]["ts"] == "2026-07-02T10:03:00Z"
