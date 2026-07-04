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
EDDL = (51.2895, 6.76678)  # Düsseldorf, elev 147 ft — dritter Platz für die prev_end-Regression.
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
    """Realer EDDK→EDDW-Flug (wie TestStatsimGpsAudit._seed), 10:00–10:44 UTC.

    Enthält einen erkennbaren Taxi-out (10:00–10:05, Boden-Rollen mit gs 10-15 kt VOR dem
    Steigflug um 10:06) — deckt KORREKTUR 1 (#23 Phase 2, Blockzeit gate-to-gate inkl. Taxi)
    ab: Abheben (``takeoff_ts``) erst bei 10:06, ``block_min`` muss die Taxi-Minuten davor
    (10:00-10:06) mit einschließen, ``duration_min`` (reine Flugzeit) NICHT.
    """
    _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 10, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:03:00Z", *EDDK, 302, 12, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:05:00Z", *EDDK, 302, 15, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:06:00Z", *EDDK, 1200, 80, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:40:00Z", *EDDW, 20, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:44:00Z", *EDDW, 20, 0, callsign)


def _seed_eddk_eddw_eddl_intermediate_landing_track(conn: sqlite3.Connection, cid: int, callsign: str) -> None:
    """Echte Zwischenlandung: EDDK→EDDW→EDDL, EIN zusammenhängendes Zeit-Segment (alle
    Sample-Lücken <= 30 min, s. ``_GPS_LEG_GAP_MINUTES``), Turnaround am Boden in EDDW
    (10:40-10:46, 6 min) — deckt die ``prev_end``-Schranke in ``_gps_flights_for_positions``
    ab (Test unten).
    """
    # --- Leg 1: EDDK -> EDDW (Taxi-out 10:00-10:06, Flug 10:06-10:40) ------------------
    _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 10, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:03:00Z", *EDDK, 302, 12, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:05:00Z", *EDDK, 302, 15, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:06:00Z", *EDDK, 1200, 80, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:40:00Z", *EDDW, 20, 0, callsign)  # Touchdown EDDW
    # --- Turnaround EDDW: Rollen zum Stand, kurzer Halt, Rollen zum Start (6 min) ------
    _insert_pos(conn, cid, "2026-07-02T10:41:00Z", *EDDW, 20, 5, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:43:00Z", *EDDW, 20, 0, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:45:00Z", *EDDW, 20, 8, callsign)
    # --- Leg 2: EDDW -> EDDL (Abheben 10:46, Landung 11:10) ----------------------------
    _insert_pos(conn, cid, "2026-07-02T10:46:00Z", *EDDW, 1300, 85, callsign)
    _insert_pos(conn, cid, "2026-07-02T10:50:00Z", 52.0, 7.5, 5000, 140, callsign)
    _insert_pos(conn, cid, "2026-07-02T11:00:00Z", 51.6, 7.0, 5000, 140, callsign)
    _insert_pos(conn, cid, "2026-07-02T11:08:00Z", 51.35, 6.85, 1500, 90, callsign)
    _insert_pos(conn, cid, "2026-07-02T11:10:00Z", *EDDL, 150, 0, callsign)  # Touchdown EDDL


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
        # KORREKTUR 1 (#23 Phase 2): block_min (gate-to-gate inkl. Taxi) ist die GRÖSSERE
        # Zeit, duration_min (reine Flugzeit Abheben->Landung) die KLEINERE — exakte Werte
        # ausgerechnet aus _seed_eddk_eddw_track (Taxi 10:00-10:06, Flugzeit 10:06-10:40).
        assert flight["duration_min"] == 34
        assert flight["block_min"] == 37
        assert flight["block_min"] >= flight["duration_min"]


class TestAircraftFallback:
    def test_no_plan_match_falls_back_to_last_known_aircraft(self):
        """UI-Feedback 2026-07-04: GPS-Legs ohne Plan-Match (Startplatz weicht vom Flugplan
        ab) zeigten Aircraft leer, obwohl der #11-Fallback (last_known_aircraft) existiert.
        Die gespeicherte Connection-Zeile selbst zaehlt als "zuletzt bekanntes Muster"."""
        conn = _make_conn()
        cid = 4310
        _insert_flight(
            conn, cid=cid, callsign="FRS40", aircraft_short="PA28",
            departure="ZZZZ", arrival="ZZZZ",
            logon_time="2026-07-02T09:00:00Z", logoff_time="2026-07-02T09:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS40")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid and f["gps_departure"] == "EDDK")
        assert flight["id"] is None  # kein Plan-Match (Startplatz ZZZZ != EDDK)
        assert flight["aircraft"] == "PA28"


class TestStatsimCallsignFallback:
    def test_no_plan_match_falls_back_to_row_callsign(self):
        """UI-Feedback: StatSim-GPS-Legs ohne Plan-Match (Track spawnt bereits fliegend fernab
        jedes Platzes -> dep_icao unbekannt -> _assign_flightplan liefert None) zeigten
        callsign leer. statsim_position_history hat KEINE callsign-Spalte -> callsign_by_ts
        (Fallback in _gps_flights_for_positions) findet dort nie einen Treffer — anders als
        bei FriesenSpy-Tracks (position_history hat callsign). Die statsim_cache-Zeile kennt
        den Callsign aber längst (row.callsign), analog zum bestehenden Aircraft-Fallback."""
        conn = _make_conn()
        cid = 4321
        _insert_statsim(
            conn, 9501, cid=cid, callsign="DLH123", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T10:35:00Z",
            duration_min=37, aircraft="C172",
        )
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:00:00Z", *REMOTE, 3000, 120)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:10:00Z", 53.5, 6.0, 2500, 110)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:20:00Z", 53.2, 7.5, 1000, 90)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:28:00Z", 53.06, 8.7, 200, 40)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:30:00Z", *EDDW, 14, 0)
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["gps_departure"] is None  # kein Platz beim Start erkannt (Spawn-in-Luft)
        assert flight["gps_arrival"] == "EDDW"
        assert flight["callsign"] == "DLH123"


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
        for ts in ["2026-07-02T10:00:00Z", "2026-07-02T10:10:00Z",
                   "2026-07-02T10:20:00Z", "2026-07-02T10:30:00Z"]:
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


# --- Risiko-Review-Regressionstests (Fix 1-6, #23) ------------------------------------

MID = (51.5, 7.5)  # ~40 nm von EDDK, außerhalb jedes Flugplatz-Radius (10 km).


class TestCappedOpenFlightWindow:
    def test_open_flight_isolated_from_followup_session(self):
        """FIX 1: ein offener Flug (Absturz) darf NICHT bis in eine spätere, eigene Session
        derselben cid hineinreichen (Gap > 30 min trennt in ein neues Segment/einen neuen
        Flug) — sonst Doppelzählung inkl. Haversine-Sprung Crash→Respawn."""
        conn = _make_conn()
        cid = 4308
        _insert_flight(
            conn, cid=cid, callsign="FRS38", departure="", arrival="",
            logon_time="2026-07-02T09:55:00Z", logoff_time=None,
        )
        # Segment 1: EDDK-Start, Absturz mitten im Flug (~10:30) — KEIN Landing.
        for ts, lat, lon, alt, gs in [
            ("2026-07-02T10:00:00Z", *EDDK, 302, 0),
            ("2026-07-02T10:01:00Z", *EDDK, 302, 5),
            ("2026-07-02T10:02:00Z", *EDDK, 1200, 80),
            ("2026-07-02T10:15:00Z", *MID, 5000, 120),
            ("2026-07-02T10:30:00Z", *MID, 5000, 120),
        ]:
            _insert_pos(conn, cid, ts, lat, lon, alt, gs, "FRS38")
        # > 30 min Gap → neues Segment: Respawn fernab bei EDDW, voller EDDW→EDDK-Flug
        # (eigener Flug derselben cid — genau das Doppelzählungs-Risiko aus FIX 1).
        for ts, lat, lon, alt, gs in [
            ("2026-07-02T12:00:00Z", *EDDW, 14, 0),
            ("2026-07-02T12:01:00Z", *EDDW, 14, 5),
            ("2026-07-02T12:02:00Z", *EDDW, 1200, 80),
            ("2026-07-02T12:20:00Z", 52.0, 8.0, 5000, 120),
            ("2026-07-02T12:38:00Z", 51.5, 7.6, 800, 90),
            ("2026-07-02T12:40:00Z", *EDDK, 310, 0),
            ("2026-07-02T12:44:00Z", *EDDK, 310, 0),
        ]:
            _insert_pos(conn, cid, ts, lat, lon, alt, gs, "FRS38")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        assert len(fs) == 2, f"erwartete 2 Flüge (offen + Folgeflug), bekam {len(fs)}"
        open_flight = next(f for f in fs if f["logoff_time"] is None)
        followup = next(f for f in fs if f["logoff_time"] is not None)

        # Segment 1 (offen) darf NICHT bis ans Ende von Segment 2 reichen (Absturz ~10:30,
        # nicht bis 12:44).
        assert open_flight["duration_min"] < 40, (
            f"duration_min sollte nur Segment 1 umfassen, war {open_flight['duration_min']}"
        )
        assert open_flight["distance_nm"] < 100, (
            "distance_nm sollte den Crash→Respawn-Sprung NICHT enthalten, war "
            f"{open_flight['distance_nm']}"
        )
        # FIX 1 + 3 (Metrik-Konsistenz am offenen Flug).
        assert open_flight["duration_min"] > 0
        assert open_flight["block_min"] > 0
        # KORREKTUR 1 (#23 Phase 2): block_min (gate-to-gate inkl. Taxi vor dem Abheben um
        # 10:02) ist >= duration_min (reine Flugzeit ab Abheben) — NICHT umgekehrt.
        assert open_flight["block_min"] >= open_flight["duration_min"]

        # Folgeflug bleibt unbeeinflusst als eigener, vollständiger Flug erkennbar.
        assert followup["gps_departure"] == "EDDW"
        assert followup["gps_arrival"] == "EDDK"


class TestArrivalNoPlanFallback:
    def test_crashed_flight_keeps_arrival_empty_despite_filed_destination(self):
        """FIX 2: arrival = gps_arrival, KEIN Flugplan-Fallback. Ein abgestürzter/offener
        Flug mit gefiletem Ziel darf nicht wie gelandet aussehen."""
        conn = _make_conn()
        cid = 4309
        _insert_flight(
            conn, cid=cid, callsign="FRS39", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time=None,
        )
        for ts, lat, lon, alt, gs in [
            ("2026-07-02T10:00:00Z", *EDDK, 302, 0),
            ("2026-07-02T10:01:00Z", *EDDK, 302, 5),
            ("2026-07-02T10:02:00Z", *EDDK, 1200, 80),
            ("2026-07-02T10:15:00Z", *MID, 5000, 120),
            ("2026-07-02T10:30:00Z", *MID, 5000, 120),
        ]:
            _insert_pos(conn, cid, ts, lat, lon, alt, gs, "FRS39")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["gps_departure"] == "EDDK"
        assert not flight["gps_arrival"]
        assert not flight["arrival"], "arrival darf NICHT auf das geplante Ziel zurückfallen"
        assert flight["logoff_time"] is None
        # Plan-Ziel bleibt separat sichtbar (nur nicht als arrival).
        assert flight["plan_arrival"] == "EDDW"


class TestPlanLabelsThroughPipeline:
    def test_plan_labels_assigned_through_full_pipeline(self):
        """Deckt die in Task 4 offen gelassene Test-Lücke (e): Plan-Labels (route/
        plan_departure/id) müssen durch die VOLLE canonicalize_legs-Pipeline befüllt werden,
        nicht nur isoliert über _assign_flightplan."""
        conn = _make_conn()
        cid = 4310
        flight_id = _insert_flight(
            conn, cid=cid, callsign="FRS40", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
            route="EDDK DKB EDDW", remarks="Testflug",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS40")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["id"] == flight_id
        assert flight["plan_departure"] == "EDDK"
        assert flight["route"] == "EDDK DKB EDDW"


class TestCrashDedupSurvival:
    def test_statsim_survives_after_crash_no_followup(self):
        """FIX 1 + 3 + 6: FS-Track offen 10:00-10:30 (Absturz, KEIN Folgeflug) darf einen
        StatSim-Flug im FS-dunklen Fenster danach nicht durch ein (fälschlich) unbegrenztes
        Dedup-Intervall verschlucken."""
        conn = _make_conn()
        cid = 4311
        _insert_flight(
            conn, cid=cid, callsign="FRS41", departure="", arrival="",
            logon_time="2026-07-02T09:00:00Z", logoff_time=None,
        )
        for ts in ["2026-07-02T10:00:00Z", "2026-07-02T10:10:00Z",
                   "2026-07-02T10:20:00Z", "2026-07-02T10:30:00Z"]:
            _insert_pos(conn, cid, ts, *REMOTE, 3000, 120, "FRS41")
        _insert_statsim(
            conn, 9403, cid=cid, callsign="FRS41", departure="EDDW", arrival="EDDK",
            logon_time="2026-07-02T10:40:00Z", logoff_time="2026-07-02T11:20:00Z",
            duration_min=40,
        )
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        st_logons = {f["logon_time"] for f in result if f["source"] == "statsim" and f["cid"] == cid}
        assert "2026-07-02T10:40:00Z" in st_logons


# --- KORREKTUR 2 (#23 Phase 2): radius_km einstellbar durchreichen ---------------------

# ~8 km nördlich von EDDW (53.0475, 8.78667) — verifiziert (siehe Task-Report): mit 6 km
# Radius findet nearest_airport_icao_fast dort KEINEN Platz, mit 20 km Radius EDDW.
OFF_EDDW_8KM = (53.119572072072074, 8.78667)


class TestRadiusKmParameter:
    def test_radius_km_controls_arrival_detection(self):
        """Derselbe Track (Touchdown-Kandidat ~8 km von EDDW entfernt) wird je nach
        ``radius_km`` als Landung an EDDW erkannt oder nicht — belegt, dass der Parameter
        bis zu ``detect_gps_legs`` durchgereicht wird (nicht nur akzeptiert und ignoriert)."""
        conn = _make_conn()
        cid = 4312
        _insert_flight(
            conn, cid=cid, callsign="FRS42", departure="", arrival="",
            logon_time="2026-07-02T09:55:00Z", logoff_time=None,
        )
        _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, "FRS42")
        _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 5, "FRS42")
        _insert_pos(conn, cid, "2026-07-02T10:02:00Z", *EDDK, 1200, 80, "FRS42")
        _insert_pos(conn, cid, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120, "FRS42")
        # Touchdown-Kandidat (Vollstopp) ~8 km von EDDW entfernt, niedrige Höhe (AGL-Guard
        # erfüllt, sobald ein Platz im Umkreis gefunden wird).
        _insert_pos(conn, cid, "2026-07-02T10:38:00Z", *OFF_EDDW_8KM, 50, 0, "FRS42")
        conn.commit()

        small_radius = canonicalize_legs(
            conn, callsign_prefix="FRS", radius_km=6.0, **WINDOW
        )
        large_radius = canonicalize_legs(
            conn, callsign_prefix="FRS", radius_km=20.0, **WINDOW
        )
        conn.close()

        f_small = next(f for f in small_radius if f["cid"] == cid)
        f_large = next(f for f in large_radius if f["cid"] == cid)

        # Kleiner Radius: EDDW liegt außerhalb → keine Landung erkannt (offener Flug).
        assert f_small["gps_arrival"] is None
        assert f_small["logoff_time"] is None

        # Größerer Radius: EDDW liegt innerhalb → Landung erkannt.
        assert f_large["gps_arrival"] == "EDDW"
        assert f_large["logoff_time"] == "2026-07-02T10:38:00Z"

    def test_radius_km_none_keeps_default_behaviour(self):
        """Ohne ``radius_km`` (None) bleibt das Default-Verhalten (10 km,
        ``_BUMMEL_AIRPORT_RADIUS_KM``) unverändert — deckungsgleich mit dem realen
        EDDK→EDDW-Track aus ``_seed_eddk_eddw_track`` (exakte Platz-Koordinaten, weit
        innerhalb jedes plausiblen Radius)."""
        conn = _make_conn()
        cid = 4313
        _insert_flight(
            conn, cid=cid, callsign="FRS43", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS43")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["gps_departure"] == "EDDK"
        assert flight["gps_arrival"] == "EDDW"


# --- Härtung (#23, Review-Finding zu Task 4c): prev_end-Schranke -----------------------


class TestPrevEndBoundary:
    def test_second_leg_block_min_excludes_first_legs_airborne_time(self):
        """Kern-Regression für die ``prev_end``-Schranke in ``_gps_flights_for_positions``
        (KORREKTUR #23 Phase 2, Blockzeit gate-to-gate): bei einer ECHTEN Zwischenlandung
        (zwei Legs im selben Zeit-Segment, Turnaround-Boden-Rollen <= 30 min) darf der
        Rückwärts-Walk für ``block_start`` des ZWEITEN Legs nicht vor das Landungs-Ende des
        ERSTEN Legs zurücklaufen — sonst würde die komplette Luftzeit von Leg 1 (Taxi +
        Steigen + Reise + Sinken, ~34 min) fälschlich in die Blockzeit von Leg 2
        mit hineingezählt (Doppelzählung).

        Track (``_seed_eddk_eddw_eddl_intermediate_landing_track``): EDDK→EDDW (10:00-10:40,
        Taxi-out ab 10:00, Airborne 10:06-10:40) → Turnaround in EDDW (10:40-10:46, 6 min,
        <= 30 min) → EDDW→EDDL (Airborne 10:46-11:10).

        Exakter erwarteter ``block_min`` von Leg 2 MIT ``prev_end``-Schranke: 27 (1620 s) —
        die Blockzeit-Summe (s. ``_block_seconds_positions``) beginnt frühestens am
        Landungs-ts von Leg 1 (10:40:00, = ``prev_end``) und deckt NUR den eigenen Turnaround
        (10:40-10:46) + die eigene Airborne-Zeit (10:46-11:10) ab.

        OHNE die ``prev_end``-Schranke würde der Rückwärts-Walk (Sample-Lücken hier überall
        <= 18 min, also nie > ``_GPS_LEG_GAP_MINUTES``) ungebremst bis zum allerersten
        Taxi-Sample von Leg 1 (10:00:00) zurücklaufen und ``block_min`` auf 67 (4020 s)
        aufblähen — Leg 1s komplette Luftzeit (~34 min zusätzlich) wäre dann in Leg 2s
        Blockzeit enthalten. Der Test würde also brechen (67 statt 27), wenn jemand die
        Schranke entfernt — genau das soll er verhindern.
        """
        conn = _make_conn()
        cid = 4314
        _insert_flight(
            conn, cid=cid, callsign="FRS44", departure="EDDK", arrival="EDDL",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T11:15:00Z",
        )
        _seed_eddk_eddw_eddl_intermediate_landing_track(conn, cid, "FRS44")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        assert len(fs) == 2, f"erwartete 2 Legs (EDDK->EDDW, EDDW->EDDL), bekam {len(fs)}"
        leg1 = next(f for f in fs if f["gps_departure"] == "EDDK")
        leg2 = next(f for f in fs if f["gps_departure"] == "EDDW")

        assert leg1["gps_arrival"] == "EDDW"
        assert leg2["gps_arrival"] == "EDDL"

        # Exakter Wert — bricht messbar (67 statt 27), sobald die prev_end-Schranke entfernt
        # wird (s. Docstring oben für die Herleitung beider Zahlen).
        assert leg2["duration_min"] == 24
        assert leg2["block_min"] == 27
        assert leg2["block_min"] < leg1["duration_min"] + leg2["duration_min"], (
            "block_min von Leg 2 enthaelt vermutlich (Teile) der Luftzeit von Leg 1 "
            "-- die prev_end-Schranke greift nicht mehr"
        )


# --- FIX 1 (Whole-Branch-Review #23): statsim_id im Feld-Vertrag ------------------------
# Die UI waehlt die Track-Button-ID via
# `f.source === 'friesenspy' ? f.id : f.statsim_id` (app/static/index.html) -- fehlt
# `statsim_id` im StatSim-Zweig, ist der Track-Button fuer JEDEN StatSim-Flug tot
# (`undefined`). Deckt alle drei Erzeugungspfade ab: GPS-Track (StatSim + FriesenSpy) und
# den Connection-Fallback OHNE Track (StatSim + FriesenSpy).

class TestStatsimIdField:
    def test_statsim_with_track_carries_statsim_id(self):
        """StatSim-Flug MIT erkanntem GPS-Track: statsim_id muss die ID der statsim_cache-
        Zeile tragen (Track-Button-Ziel in der UI)."""
        conn = _make_conn()
        cid = 4315
        _insert_statsim(
            conn, 9501, cid=cid, callsign="FRS45", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=44,
        )
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:00:00Z", *EDDK, 302, 0)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:06:00Z", *EDDK, 1200, 80)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60)
        _insert_statsim_pos(conn, 9501, "2026-07-02T10:40:00Z", *EDDW, 20, 0)
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid and f["source"] == "statsim")
        assert flight["gps_departure"] == "EDDK", "Test-Vorbedingung: Track muss erkannt werden"
        assert flight["statsim_id"] == 9501

    def test_statsim_fallback_without_track_carries_statsim_id(self):
        """StatSim-Fallback OHNE Track (kein erkanntes Leg): statsim_id muss trotzdem
        gesetzt sein -- kommt hier aus `_flightrow_as_flight`, nicht aus dem GPS-Zweig."""
        conn = _make_conn()
        cid = 4316
        _insert_statsim(
            conn, 9502, cid=cid, callsign="FRS46", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=52,
        )
        # Bewusst KEINE statsim_position_history-Zeilen -> Fallback-Pfad.
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid and f["source"] == "statsim")
        assert flight["statsim_id"] == 9502

    def test_friesenspy_flight_statsim_id_is_none(self):
        """FriesenSpy-Flug (mit UND ohne Track) hat kein statsim_id -- Key muss dennoch
        existieren (Symmetrie im Feld-Vertrag) und None sein."""
        conn = _make_conn()
        cid_track, cid_fallback = 4317, 4318
        _insert_flight(
            conn, cid=cid_track, callsign="FRS47", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid_track, "FRS47")
        _insert_flight(
            conn, cid=cid_fallback, callsign="FRS48", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=55, distance_nm=210, block_min=50,
        )
        # Bewusst KEINE position_history-Zeilen fuer cid_fallback -> Fallback-Pfad
        # (duration_min/distance_nm > Ghost-Schwelle, s. `_is_ghost_row`).
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight_track = next(f for f in result if f["cid"] == cid_track)
        flight_fallback = next(f for f in result if f["cid"] == cid_fallback)
        assert "statsim_id" in flight_track and flight_track["statsim_id"] is None
        assert "statsim_id" in flight_fallback and flight_fallback["statsim_id"] is None


class TestLastPosTsField:
    def test_closed_gps_leg_last_pos_ts_is_landing(self):
        """Geschlossener GPS-Flug: last_pos_ts = letzte belegte Position (hier = Landung EDDW)."""
        conn = _make_conn()
        cid = 4400
        _insert_flight(
            conn, cid=cid, callsign="FRS60", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS60")
        conn.commit()
        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()
        f = next(x for x in result if x["cid"] == cid)
        assert "last_pos_ts" in f
        # Ende des Legs = Touchdown EDDW (10:40); die Taxi-Dwell-Positionen danach (10:44)
        # gehören nicht mehr zum Flug-Leg.
        assert f["last_pos_ts"] == "2026-07-02T10:40:00Z"

    def test_open_leg_last_pos_ts_not_none_and_before_now(self):
        """Offener Leg (kein logoff): last_pos_ts trägt die letzte GPS-Position, NICHT None/now —
        so kann das Frontend „läuft" auf Frische prüfen und der Track endet an der letzten Position."""
        conn = _make_conn()
        cid = 4401
        # Offene Connection (logoff_time=None), Track endet mitten in der Luft (Disconnect).
        _insert_flight(
            conn, cid=cid, callsign="FRS61", departure="EDDK", arrival="",
            logon_time="2026-07-02T09:55:00Z", logoff_time=None,
        )
        _insert_pos(conn, cid, "2026-07-02T10:00:00Z", *EDDK, 302, 0, "FRS61")
        _insert_pos(conn, cid, "2026-07-02T10:01:00Z", *EDDK, 302, 12, "FRS61")
        _insert_pos(conn, cid, "2026-07-02T10:06:00Z", *EDDK, 1200, 80, "FRS61")
        _insert_pos(conn, cid, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120, "FRS61")  # letzte Pos, airborne
        conn.commit()
        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()
        f = next(x for x in result if x["cid"] == cid)
        assert f["logoff_time"] is None          # offen
        assert f["last_pos_ts"] == "2026-07-02T10:20:00Z"  # letzte Position, nicht None

    def test_fallback_flight_last_pos_ts_is_logoff(self):
        """Trackloser Fallback-Flug: last_pos_ts = logoff_time der Connection."""
        conn = _make_conn()
        cid = 4402
        _insert_flight(
            conn, cid=cid, callsign="FRS62", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
            duration_min=55, distance_nm=210, block_min=50,
        )
        # keine position_history -> Fallback
        conn.commit()
        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()
        f = next(x for x in result if x["cid"] == cid)
        assert f["last_pos_ts"] == "2026-07-02T10:50:00Z"
