"""Tests für ``flight_cache`` (app/database.py) — materialisierte ``canonicalize_legs``-Ergebnisse.

Fixtures analog ``tests/test_canonicalize_legs.py``: reale Plätze EDDK (50.8659, 7.14274,
elev 302) und EDDW (53.0475, 8.78667, elev 14).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.database import (
    _DDL,
    canonicalize_legs,
    ensure_pilot,
    get_cached_flights,
    get_connection,
    init_db,
    rebuild_flight_cache,
)

EDDK = (50.8659, 7.14274)
EDDW = (53.0475, 8.78667)

# (offset_minutes, lat, lon, alt, gs) — derselbe EDDK->EDDW-Track wie in test_canonicalize_legs.py.
_TRACK_OFFSETS = [
    (0, *EDDK, 302, 0),
    (1, *EDDK, 302, 5),
    (2, *EDDK, 1200, 80),
    (20, 52.0, 8.0, 5000, 120),
    (38, 53.0, 8.7, 500, 60),
    (40, *EDDW, 20, 0),
    (44, *EDDW, 20, 0),
]


def _make_conn() -> sqlite3.Connection:
    """In-Memory-Verbindung mit vollständig initialisierten Tabellen (wie test_database.py)."""
    init_db(":memory:")
    conn = get_connection(":memory:")
    conn.executescript(_DDL)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_session "
        "ON flights(cid, logon_time) WHERE superseded_by IS NULL"
    )
    conn.commit()
    return conn


def _insert_flight(conn: sqlite3.Connection, **kw) -> int:
    """Rohe ``flights``-Zeile (Connection) einfügen, id zurückgeben."""
    ensure_pilot(conn, kw["cid"], f"Pilot {kw['cid']}")
    cols = [
        "cid", "callsign", "aircraft_short", "departure", "arrival", "logon_time",
        "logoff_time", "duration_min", "distance_nm", "route", "remarks",
        "cruise_altitude", "cruise_tas", "flight_rules", "aircraft_icao", "alternate",
        "deptime", "enroute_time", "fuel_time", "superseded_by", "block_min",
    ]
    defaults = {
        "aircraft_short": "C172", "departure": "", "arrival": "", "logoff_time": None,
        "duration_min": None, "distance_nm": 0, "route": "", "remarks": "",
        "cruise_altitude": "", "cruise_tas": "", "flight_rules": "", "aircraft_icao": "",
        "alternate": "", "deptime": "", "enroute_time": "", "fuel_time": "",
        "superseded_by": None, "block_min": None,
    }
    row = {**defaults, **kw}
    values = [row[c] for c in cols]
    cur = conn.execute(
        f"INSERT INTO flights ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        values,
    )
    return cur.lastrowid


def _insert_pos(conn: sqlite3.Connection, cid: int, ts: str, lat, lon, alt, gs, callsign="FRS") -> None:
    ensure_pilot(conn, cid, f"Pilot {cid}")
    conn.execute(
        "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,groundspeed,"
        "heading,ts) VALUES (?,?,?,?,?,?,0,?)",
        (cid, callsign, lat, lon, alt, gs, ts),
    )


def _seed_track(conn: sqlite3.Connection, cid: int, callsign: str, start_dt: datetime) -> None:
    """EDDK->EDDW-Track relativ zu ``start_dt`` (echte Uhrzeit statt fixem Testdatum, damit
    das 7-Tage-Inkrementalfenster von rebuild_flight_cache greift)."""
    for off_min, lat, lon, alt, gs in _TRACK_OFFSETS:
        ts = (start_dt + timedelta(minutes=off_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_pos(conn, cid, ts, lat, lon, alt, gs, callsign)


def _seed_fixed_track(conn: sqlite3.Connection, cid: int, callsign: str, base: str = "2026-07-02") -> None:
    """Wie ``_seed_track``, aber mit fixem Kalenderdatum (für Voll-Rebuild-Tests ohne
    Zeitbezug — canonicalize_legs(conn) ohne Fenster deckt jedes Datum ab)."""
    start_dt = datetime.fromisoformat(f"{base}T10:00:00+00:00")
    _seed_track(conn, cid, callsign, start_dt)


class TestCacheMatchesCanonicalizeLegs:
    def test_cache_matches_canonicalize_legs(self):
        conn = _make_conn()
        cid = 5001
        _insert_flight(
            conn, cid=cid, callsign="FRS50", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_fixed_track(conn, cid, "FRS50")
        conn.commit()

        live = canonicalize_legs(conn)
        cached = get_cached_flights(conn)
        conn.close()

        assert live, "erwartete mindestens einen kanonischen Flug"
        assert len(cached) == len(live)

        live_by_key = {(f["cid"], f["logon_time"]): f for f in live}
        cached_by_key = {(f["cid"], f["logon_time"]): f for f in cached}
        assert set(live_by_key) == set(cached_by_key)

        for key, l in live_by_key.items():
            c = cached_by_key[key]
            assert c["departure"] == l["departure"]
            assert c["arrival"] == l["arrival"]
            assert c["distance_nm"] == l["distance_nm"]
            assert c["block_min"] == l["block_min"]

        target = next(f for f in cached if f["cid"] == cid)
        assert target["source"] == "friesenspy"
        assert isinstance(target["connection_closed"], bool)


class TestCacheIdempotent:
    def test_cache_idempotent(self):
        conn = _make_conn()
        cid = 5002
        _insert_flight(
            conn, cid=cid, callsign="FRS51", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_fixed_track(conn, cid, "FRS51")
        conn.commit()

        n1 = rebuild_flight_cache(conn, full=True)
        rows1 = [
            tuple(r) for r in conn.execute(
                "SELECT cid, logon_time, departure, arrival, distance_nm, block_min "
                "FROM flight_cache ORDER BY cid, logon_time"
            ).fetchall()
        ]

        n2 = rebuild_flight_cache(conn, full=True)
        rows2 = [
            tuple(r) for r in conn.execute(
                "SELECT cid, logon_time, departure, arrival, distance_nm, block_min "
                "FROM flight_cache ORDER BY cid, logon_time"
            ).fetchall()
        ]
        conn.close()

        assert n1 == n2
        assert rows1 == rows2
        # UNIQUE(cid, logon_time) darf keine Dubletten zulassen.
        assert len(rows2) == len({(r[0], r[1]) for r in rows2})


class TestIncrementalRefresh:
    def test_incremental_refresh_picks_up_new_flight(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)

        cid_old = 5003
        old_start = now - timedelta(days=2)
        _insert_flight(
            conn, cid=cid_old, callsign="FRS52", departure="EDDK", arrival="EDDW",
            logon_time=(old_start - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            logoff_time=(old_start + timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        _seed_track(conn, cid_old, "FRS52", old_start)
        conn.commit()

        first = get_cached_flights(conn)
        assert any(f["cid"] == cid_old for f in first)

        # computed_at künstlich alt setzen (> 600s) — erzwingt den inkrementellen Refresh-Pfad.
        stale = (now - timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE flight_cache SET computed_at = ?", (stale,))
        conn.commit()

        # Neuer Flug, deutlich unter 7 Tage alt.
        cid_new = 5004
        new_start = now - timedelta(hours=2)
        _insert_flight(
            conn, cid=cid_new, callsign="FRS53", departure="EDDK", arrival="EDDW",
            logon_time=(new_start - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            logoff_time=(new_start + timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        _seed_track(conn, cid_new, "FRS53", new_start)
        conn.commit()

        result = get_cached_flights(conn)
        conn.close()

        assert any(f["cid"] == cid_new for f in result), "neuer Flug fehlt nach inkrementellem Refresh"
        # Der ältere Flug bleibt weiterhin sichtbar (nicht verloren gegangen).
        assert any(f["cid"] == cid_old for f in result)
