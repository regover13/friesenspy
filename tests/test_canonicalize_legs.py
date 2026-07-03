"""Tests für ``canonicalize_legs`` (app/database.py) — GPS-Pendant zu ``canonicalize_flights``.

Fixtures analog ``TestStatsimGpsAudit._seed`` (tests/test_database.py): reale Plätze
EDDK (50.8659, 7.14274, elev 302) und EDDW (53.0475, 8.78667, elev 14).
"""
from __future__ import annotations

import sqlite3

from app.database import (
    _DDL,
    _assign_flightplan,
    canonicalize_legs,
    ensure_pilot,
    get_connection,
    init_db,
)

EDDK = (50.8659, 7.14274)
EDDW = (53.0475, 8.78667)
# Fernab jedes Flugplatzes (Nordsee) — Detektor findet dort nie einen Platz im 10-km-Radius.
REMOTE = (55.0, 2.0)


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


def _insert_statsim(conn: sqlite3.Connection, statsim_id: int, **kw) -> None:
    defaults = {
        "cid": 0, "callsign": "", "departure": "", "arrival": "", "aircraft": "C172",
        "logon_time": "", "logoff_time": None, "duration_min": 0, "fetched_at": "x",
    }
    row = {**defaults, **kw}
    conn.execute(
        "INSERT INTO statsim_cache (statsim_id,cid,callsign,departure,arrival,aircraft,"
        "logon_time,logoff_time,duration_min,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (statsim_id, row["cid"], row["callsign"], row["departure"], row["arrival"],
         row["aircraft"], row["logon_time"], row["logoff_time"], row["duration_min"],
         row["fetched_at"]),
    )


def _insert_statsim_pos(conn: sqlite3.Connection, statsim_id: int, ts: str, lat, lon, alt, gs) -> None:
    conn.execute(
        "INSERT INTO statsim_position_history (statsim_id,latitude,longitude,altitude,"
        "groundspeed,heading,ts) VALUES (?,?,?,?,?,0,?)",
        (statsim_id, lat, lon, alt, gs, ts),
    )


def _insert_pos(conn: sqlite3.Connection, cid: int, ts: str, lat, lon, alt, gs, callsign="FRS") -> None:
    ensure_pilot(conn, cid, f"Pilot {cid}")
    conn.execute(
        "INSERT INTO position_history (cid,callsign,latitude,longitude,altitude,groundspeed,"
        "heading,ts) VALUES (?,?,?,?,?,?,0,?)",
        (cid, callsign, lat, lon, alt, gs, ts),
    )


def _seed_eddk_eddw_track(conn: sqlite3.Connection, cid: int, callsign: str) -> None:
    """Realer EDDK→EDDW-Flug (wie TestStatsimGpsAudit._seed), 10:00–10:44 UTC."""
    _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 5, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:02:00Z", *EDDK, 1200, 80, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:40:00Z", *EDDW, 20, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:44:00Z", *EDDW, 20, 0, callsign)


WINDOW = dict(start="2026-07-01T00:00:00Z", end="2026-07-03T00:00:00Z")


class TestFormParity:
    def test_form_parity_and_fields(self):
        conn = _make_conn()
        cid = 4301
        _insert_flight(
            conn, cid=cid, callsign="FRS30", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS30")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        assert result, "erwartete mindestens einen kanonischen Flug"
        flight = next(f for f in result if f["cid"] == cid)

        canonical_flights_keys = {
            "id", "cid", "callsign", "aircraft", "departure", "arrival", "logon_time",
            "logoff_time", "duration_min", "distance_nm", "block_min", "route", "remarks",
            "cruise_altitude", "cruise_tas", "flight_rules", "aircraft_icao", "alternate",
            "deptime", "enroute_time", "fuel_time", "source",
        }
        gps_extra_keys = {
            "gps_departure", "gps_arrival", "plan_departure", "plan_arrival", "connection_closed",
        }
        assert canonical_flights_keys | gps_extra_keys <= set(flight.keys())

        assert flight["source"] == "friesenspy"
        assert flight["gps_departure"] == "EDDK"
        assert flight["gps_arrival"] == "EDDW"
        assert flight["departure"] == "EDDK"
        assert flight["arrival"] == "EDDW"
        assert flight["block_min"] <= flight["duration_min"]


class TestPrefixFilter:
    def test_prefix_empty_includes_foreign(self):
        conn = _make_conn()
        cid = 4302
        _insert_statsim(
            conn, 9301, cid=cid, callsign="DFGKC", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=52,
        )
        conn.commit()

        all_result = canonicalize_legs(conn, callsign_prefix="", **WINDOW)
        frs_result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        assert any(f["callsign"] == "DFGKC" for f in all_result)
        assert not any(f["callsign"] == "DFGKC" for f in frs_result)


class TestFallbacks:
    def test_frs_connection_without_track_falls_back(self):
        conn = _make_conn()
        cid = 4303
        _insert_flight(
            conn, cid=cid, callsign="FRS31", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=55, distance_nm=210, block_min=50,
        )
        # Bewusst KEINE position_history-Zeilen für diese cid.
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["source"] == "friesenspy"
        assert flight["departure"] == "EDDK"
        assert flight["arrival"] == "EDDW"
        assert flight["logon_time"] == "2026-07-02T09:55:00Z"
        assert flight["logoff_time"] == "2026-07-02T10:50:00Z"
        assert flight["gps_departure"] is None
        assert flight["gps_arrival"] is None
        assert flight["connection_closed"] is True

    def test_statsim_fallback_without_track(self):
        conn = _make_conn()
        cid = 4304
        _insert_statsim(
            conn, 9302, cid=cid, callsign="FRS32", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=52,
        )
        # Bewusst KEINE statsim_position_history-Zeilen.
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid and f["source"] == "statsim")
        assert flight["departure"] == "EDDK"
        assert flight["arrival"] == "EDDW"
        assert flight["gps_departure"] is None
        assert flight["gps_arrival"] is None
        assert flight["connection_closed"] is True


class TestDedup:
    def test_dedup_partial_overlap_keeps_uncovered_statsim(self):
        conn = _make_conn()
        cid = 4305
        # FriesenSpy-Connection bleibt offen (Absturz-Szenario: kein Disconnect erfasst).
        _insert_flight(
            conn, cid=cid, callsign="FRS33", departure="", arrival="",
            logon_time="2026-07-02T09:00:00Z", logoff_time=None,
        )
        # Track: spawnt bereits fliegend fernab jedes Platzes, bricht bei 10:30 ab (kein Landing).
        for sec, ts in enumerate(
            ["2026-07-02T10:00:00Z", "2026-07-02T10:10:00Z",
             "2026-07-02T10:20:00Z", "2026-07-02T10:30:00Z"]
        ):
            _insert_pos(conn, cid, ts, *REMOTE, 3000, 120, "FRS33")

        # Zwei StatSim-Flüge derselben cid: einer innerhalb der FS-Abdeckung (verworfen),
        # einer danach (überlebt — FS hat dafür keine Belege mehr).
        _insert_statsim(
            conn, 9401, cid=cid, callsign="FRS33", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T10:05:00Z", logoff_time="2026-07-02T10:25:00Z",
            duration_min=20,
        )
        _insert_statsim(
            conn, 9402, cid=cid, callsign="FRS33", departure="EDDW", arrival="EDDK",
            logon_time="2026-07-02T10:40:00Z", logoff_time="2026-07-02T11:20:00Z",
            duration_min=40,
        )
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        st_logons = {f["logon_time"] for f in result if f["source"] == "statsim" and f["cid"] == cid}
        assert "2026-07-02T10:05:00Z" not in st_logons
        assert "2026-07-02T10:40:00Z" in st_logons


class TestConnectionClosedFlag:
    def test_connection_closed_flag(self):
        conn = _make_conn()
        cid_open, cid_closed = 4306, 4307

        _insert_flight(
            conn, cid=cid_open, callsign="FRS34", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time=None,
        )
        _seed_eddk_eddw_track(conn, cid_open, "FRS34")

        _insert_flight(
            conn, cid=cid_closed, callsign="FRS35", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid_closed, "FRS35")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        f_open = next(f for f in result if f["cid"] == cid_open)
        f_closed = next(f for f in result if f["cid"] == cid_closed)
        assert f_open["connection_closed"] is False
        assert f_closed["connection_closed"] is True


class TestPlanAssignment:
    def test_plan_assignment_start_airport_primary(self):
        # Zwei Plan-Zeilen: A→B (zuerst gefiled), B→C (ZEITLICH FRÜHER logon_time als A→B —
        # beweist, dass die Zuordnung rein über den Startplatz läuft, nicht über Zeit-Reihenfolge).
        plan_rows = [
            {"id": 1, "departure": "A", "arrival": "B", "logon_time": "2026-07-02T10:10:00Z"},
            {"id": 2, "departure": "B", "arrival": "C", "logon_time": "2026-07-02T09:00:00Z"},
        ]
        leg_ab = {"dep_icao": "A", "arr_icao": "B", "takeoff_ts": "2026-07-02T10:00:00Z"}
        leg_bc = {"dep_icao": "B", "arr_icao": "C", "takeoff_ts": "2026-07-02T10:30:00Z"}
        leg_no_match = {"dep_icao": "C", "arr_icao": "D", "takeoff_ts": "2026-07-02T11:00:00Z"}

        assigned_ab = _assign_flightplan(plan_rows, leg_ab)
        assigned_bc = _assign_flightplan(plan_rows, leg_bc)
        assigned_none = _assign_flightplan(plan_rows, leg_no_match)

        assert assigned_ab is not None and assigned_ab["departure"] == "A"
        assert assigned_bc is not None and assigned_bc["departure"] == "B"
        assert assigned_none is None
