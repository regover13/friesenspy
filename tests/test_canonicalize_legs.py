"""Tests für ``canonicalize_legs`` (app/database.py) — GPS-Pendant zu ``canonicalize_flights``.

Fixtures analog ``TestStatsimGpsAudit._seed`` (tests/test_database.py): reale Plätze
EDDK (50.8659, 7.14274, elev 302) und EDDW (53.0475, 8.78667, elev 14).
"""
from __future__ import annotations

import sqlite3

from app.database import (
    _DDL,
    _flightplan_asof,
    _gps_flights_for_positions,
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
            "block_start", "block_end",
        }
        assert canonical_flights_keys | gps_extra_keys <= set(flight.keys())

        assert flight["source"] == "friesenspy"
        assert flight["gps_departure"] == "EDDK"
        assert flight["gps_arrival"] == "EDDW"
        assert flight["departure"] == "EDDK"
        assert flight["arrival"] == "EDDW"
        # KORREKTUR 1 (#23 Phase 2): block_min (gate-to-gate inkl. Taxi) ist die GRÖSSERE
        # Zeit, duration_min (reine Flugzeit Abheben->Landung) die KLEINERE — exakte Werte
        # ausgerechnet aus _seed_eddk_eddw_track (Taxi 10:00-10:06, Flugzeit 10:06-10:40,
        # PLUS ein Sample 10:44:00 EDDW gs=0, 4 min nach der Landung -- die Verbindung bleibt
        # noch kurz bestehen, bevor die Testdaten enden).
        #
        # "fix/blockzeit-anblock": duration_min bleibt 34 (_air_seconds findet im Track
        # keine Bodenphase -- jedes Sample-Paar zwischen 10:06 und 10:40 liegt entweder mehr
        # als 300 s auseinander oder mehr als 200 m entfernt, s. Kriterien in _air_seconds).
        # block_min steigt von 37 auf 43: _leg_block_seconds zaehlt WANDUHR ab block_from
        # (10:01, erstes Sample mit groundspeed > 2 kt) bis block_end. block_end selbst
        # verlaengert sich ueber die Landung (10:40) hinaus bis zum LETZTEN VERFUEGBAREN
        # Sample (10:44 -- der einzige Stand danach hat nur 1 Sample, viel zu kurz fuer die
        # 600-s-Schwelle einer qualifizierenden Abstell-Standphase, zaehlt aber trotzdem als
        # direkt belegte Standzeit, s. _extend_block_end). 10:01-10:44 = 43 min, keine
        # qualifizierenden Abzuege -> 43 (vorher zaehlte die SESSION-Blockzeit-Formel nur die
        # Summe der Bewegungs-Luecken zwischen Messpunkten, 37 min -- s.
        # `_block_seconds_positions`, die für die Leg-Metrik nicht mehr verwendet wird).
        assert flight["duration_min"] == 34
        assert flight["block_min"] == 43
        assert flight["block_min"] >= flight["duration_min"]

    def test_block_start_is_roll_begin_before_takeoff(self):
        """#62: block_start = Rollbeginn (erstes Taxi-Sample 10:00), NICHT das Abheben
        (logon_time/takeoff_ts 10:06). Das Frontend nutzt block_start als Track-Untergrenze,
        damit Taxi-out + Startlauf sichtbar werden."""
        conn = _make_conn()
        cid = 4302
        _insert_flight(
            conn, cid=cid, callsign="FRS31", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS31")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["logon_time"] == "2026-07-02T10:06:00Z"   # Abheben (takeoff_ts)
        assert flight["block_start"] == "2026-07-02T10:00:00Z"  # Rollbeginn (erstes Taxi-Sample)
        assert flight["block_start"] < flight["logon_time"]


class TestNoAircraftWithoutPlan:
    def test_no_plan_at_all_leaves_aircraft_none(self):
        """Nutzer-Entscheidung 2026-07-05 (#52): last_known_aircraft war zeitlich blind (holte
        den GLOBAL neuesten gefileten Typ, auch aus der Zukunft des Legs -- Fund cid 1273634).
        Der VATSIM-Feed fuehrt ohne Flugplan grundsaetzlich KEINE Typ-Info (live verifiziert).
        Fallback komplett entfernt: GPS-Legs ohne Plan-Match zeigen aircraft=None statt eines
        (moeglicherweise falschen) geratenen Typs -- auch wenn eine aeltere, laengst
        geschlossene Session desselben Piloten einen Typ kennt."""
        conn = _make_conn()
        cid = 4310
        # Aeltere, abgeschlossene Session (weit vor WINDOW) -- darf NICHT mehr als Fallback
        # herangezogen werden (frueher: last_known_aircraft).
        _insert_flight(
            conn, cid=cid, callsign="FRS40", aircraft_short="PA28",
            departure="EDDL", arrival="EDDK",
            logon_time="2026-06-20T08:00:00Z", logoff_time="2026-06-20T08:50:00Z",
        )
        # Aktuelle Session im WINDOW: reiner Connect, noch KEIN Plan gefiled.
        _insert_flight(
            conn, cid=cid, callsign="FRS40", aircraft_short="",
            departure="", arrival="",
            logon_time="2026-07-02T09:00:00Z", logoff_time=None,
        )
        _seed_eddk_eddw_track(conn, cid, "FRS40")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid and f["gps_departure"] == "EDDK")
        assert flight["id"] is None  # kein Plan-Match (Connect ohne Plan zaehlt nicht, Spec)
        assert flight["aircraft"] is None  # #52: kein Vermutungs-Fallback mehr


class TestGpsRescueLiveGuard:
    """#53 in der vollen canonicalize_legs-Pipeline: Landungs-Rettung am Track-Ende, mit dem
    quellenabhängigen Live-Guard (FriesenSpy kann live sein, StatSim ist immer beendet).
    Nutzt EDDK (302 ft) als Zielplatz — Track endet dort airborne mit gs>2 (Cutoff-Fall,
    reale Anker EDMH/EDXF/ETHB/ENVA/LOIK dieser Session)."""

    def _iso(self, dt) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _seed_cutoff_track(self, conn, cid, callsign, base):
        """Abheben EDDK, Reiseflug, dann Rückkehr zu EDDK mit gs=6 (Cutoff VOR der
        gs<2-Landeschwelle) als letzter Punkt — 34 min nach ``base``."""
        from datetime import timedelta
        _insert_pos(conn, cid, self._iso(base), *EDDK, 302, 0, callsign)
        _insert_pos(conn, cid, self._iso(base + timedelta(minutes=1)), *EDDK, 302, 10, callsign)
        _insert_pos(conn, cid, self._iso(base + timedelta(minutes=2)), *EDDK, 1200, 80, callsign)
        _insert_pos(conn, cid, self._iso(base + timedelta(minutes=10)), 52.0, 8.0, 5000, 120, callsign)
        _insert_pos(conn, cid, self._iso(base + timedelta(minutes=34)), *EDDK, 552, 6, callsign)

    def test_friesenspy_recent_open_leg_stays_open_within_live_window(self):
        """Letzter Punkt < 15 min alt (Live-Fenster) → KEINE Rettung, Leg bleibt offen (ein
        gerade laufender Anflug darf nicht fälschlich geschlossen werden)."""
        from datetime import timedelta, timezone as _tz
        from datetime import datetime as _dt
        now = _dt.now(_tz.utc)
        base = now - timedelta(minutes=40)  # letzter Punkt: base+34min = now-6min (< 15 min alt)
        conn = _make_conn()
        cid = 7001
        _insert_flight(
            conn, cid=cid, callsign="FRS70", departure="", arrival="",
            logon_time=self._iso(base), logoff_time=None,
        )
        self._seed_cutoff_track(conn, cid, "FRS70", base)
        conn.commit()

        result = canonicalize_legs(
            conn, callsign_prefix="FRS",
            start=self._iso(now - timedelta(hours=2)), end=self._iso(now + timedelta(hours=1)),
        )
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["gps_arrival"] is None
        assert flight["logoff_time"] is None

    def test_friesenspy_old_open_leg_gets_rescued(self):
        """Letzter Punkt > 15 min alt (außerhalb Live-Fenster) → Rettung greift, Leg wird mit
        korrekten Metriken (landing_ts = letzter Punkt) geschlossen."""
        from datetime import timedelta, timezone as _tz
        from datetime import datetime as _dt
        now = _dt.now(_tz.utc)
        base = now - timedelta(minutes=60)  # letzter Punkt: base+34min = now-26min (> 15 min alt)
        conn = _make_conn()
        cid = 7002
        _insert_flight(
            conn, cid=cid, callsign="FRS71", departure="", arrival="",
            logon_time=self._iso(base), logoff_time=None,
        )
        self._seed_cutoff_track(conn, cid, "FRS71", base)
        conn.commit()

        result = canonicalize_legs(
            conn, callsign_prefix="FRS",
            start=self._iso(now - timedelta(hours=2)), end=self._iso(now + timedelta(hours=1)),
        )
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["gps_arrival"] == "EDDK"
        assert flight["logoff_time"] == self._iso(base + timedelta(minutes=34))
        assert flight["duration_min"] == 32  # Abheben (base+2min) -> Rettung (base+34min)

    def test_statsim_track_end_always_rescues_regardless_of_recency(self):
        """StatSim-Aufzeichnung ist immer beendet (kein Live-Konzept) — Rettung greift auch,
        wenn der letzte Punkt erst wenige Minuten alt ist. statsim_cache.logoff_time ist
        gesetzt (StatSim kennt die Landung selbst), nur die GPS-Positionen erreichen die
        gs<2-Schwelle nicht (realer Anker dieser Session: EDMH/EDXF/ETHB/ENVA/LOIK)."""
        from datetime import timedelta, timezone as _tz
        from datetime import datetime as _dt
        now = _dt.now(_tz.utc)
        base = now - timedelta(minutes=6)  # letzter Trackpunkt liegt bei "now" (< 15 min alt)
        conn = _make_conn()
        cid = 7003
        statsim_id = 900001
        _insert_statsim(
            conn, statsim_id, cid=cid, callsign="FRS72", departure="", arrival="EDDK",
            aircraft="C172", logon_time=self._iso(base), logoff_time=self._iso(now), duration_min=6,
        )
        _insert_statsim_pos(conn, statsim_id, self._iso(base), *EDDK, 302, 0)
        _insert_statsim_pos(conn, statsim_id, self._iso(base + timedelta(minutes=1)), *EDDK, 1200, 80)
        _insert_statsim_pos(conn, statsim_id, self._iso(base + timedelta(minutes=3)), 52.0, 8.0, 5000, 120)
        _insert_statsim_pos(conn, statsim_id, self._iso(now), *EDDK, 552, 6)  # Cutoff, gs=6
        conn.commit()

        result = canonicalize_legs(
            conn, callsign_prefix="FRS",
            start=self._iso(now - timedelta(hours=1)), end=self._iso(now + timedelta(hours=1)),
        )
        conn.close()

        flight = next(f for f in result if f["cid"] == cid and f["source"] == "statsim")
        assert flight["gps_arrival"] == "EDDK"
        assert flight["logoff_time"] == self._iso(now)


class TestStatsimCallsignFallback:
    def test_no_plan_match_falls_back_to_row_callsign(self):
        """UI-Feedback: StatSim-GPS-Legs ohne bekannten GPS-Startplatz (Track spawnt bereits
        fliegend fernab jedes Platzes) zeigten callsign leer, wenn der Zeit-Match nicht
        griff. Seit der zeitbasierten Zuordnung (2026-07-05) matcht dieser Fall zwar meist
        ueber den Plan selbst (plan.get("callsign")), der Fallback bleibt aber als zweite
        Absicherung fuer Faelle ganz ohne Plan-Match wichtig: statsim_position_history hat
        KEINE callsign-Spalte -> callsign_by_ts (Fallback in _gps_flights_for_positions)
        findet dort nie einen Treffer — anders als bei FriesenSpy-Tracks (position_history
        hat callsign). Die statsim_cache-Zeile kennt den Callsign aber laengst
        (row.callsign), analog zum bestehenden Aircraft-Fallback."""
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


class TestFlightplanAsOf:
    """Direkte Unit-Tests für die zeitbasierte Zuordnungsfunktion (Nutzer-Entscheidung
    2026-07-05) — ersetzt die alte, Startplatz-primäre ``TestPlanAssignment`` (beruhte auf
    dem inzwischen entfernten ``_assign_flightplan``)."""

    def test_last_filed_plan_before_ts_wins_regardless_of_airports(self):
        # A->B zuerst gefiled (09:00), B->C SPAETER (09:30) -- unabhaengig vom "passenden"
        # Startplatz gewinnt an jedem ts >= 09:30 die zeitlich letzte Zeile (B->C).
        plan_rows = [
            {"id": 1, "departure": "A", "arrival": "B", "logon_time": "2026-07-02T09:00:00Z"},
            {"id": 2, "departure": "B", "arrival": "C", "logon_time": "2026-07-02T09:30:00Z"},
        ]
        assert _flightplan_asof(plan_rows, "2026-07-02T09:15:00Z")["id"] == 1
        assert _flightplan_asof(plan_rows, "2026-07-02T09:30:00Z")["id"] == 2
        assert _flightplan_asof(plan_rows, "2026-07-02T23:00:00Z")["id"] == 2

    def test_before_first_filing_returns_none(self):
        plan_rows = [
            {"id": 1, "departure": "A", "arrival": "B", "logon_time": "2026-07-02T09:00:00Z"},
        ]
        assert _flightplan_asof(plan_rows, "2026-07-02T08:59:59Z") is None

    def test_empty_connect_row_does_not_count_as_match(self):
        plan_rows = [
            {"id": 1, "departure": "", "arrival": "", "logon_time": "2026-07-02T09:00:00Z"},
        ]
        assert _flightplan_asof(plan_rows, "2026-07-02T10:00:00Z") is None

    def test_empty_row_ignored_when_later_real_plan_exists(self):
        plan_rows = [
            {"id": 1, "departure": "", "arrival": "", "logon_time": "2026-07-02T09:00:00Z"},
            {"id": 2, "departure": "A", "arrival": "B", "logon_time": "2026-07-02T09:05:00Z"},
        ]
        # ts liegt NACH der leeren Zeile, aber nur die leere Zeile ist <= ts -> None.
        assert _flightplan_asof(plan_rows, "2026-07-02T09:02:00Z") is None
        assert _flightplan_asof(plan_rows, "2026-07-02T09:05:00Z")["id"] == 2

    def test_no_plan_rows_returns_none(self):
        assert _flightplan_asof([], "2026-07-02T09:00:00Z") is None

    def test_whitespace_only_fields_count_as_empty(self):
        plan_rows = [
            {"id": 1, "departure": " ", "arrival": "", "logon_time": "2026-07-02T09:00:00Z"},
        ]
        assert _flightplan_asof(plan_rows, "2026-07-02T10:00:00Z") is None

    def test_microsecond_logon_time_does_not_sort_before_second_precision(self):
        """Grund fuer _parse_iso statt String-Vergleich: ein Refile-Split-Zeitstempel mit
        Mikrosekunden (app/poller.py, "%Y-%m-%dT%H:%M:%S.%fZ") liegt real SPAETER als ein
        Sekunden-Zeitstempel derselben Sekunde -- ein lexikographischer String-Vergleich
        wuerde ihn faelschlich als "kleiner" werten (weil "." < "Z" in ASCII) und ihn damit
        in den <= ts-Kandidatenkreis aufnehmen, obwohl er nach ts liegt."""
        plan_rows = [
            {"id": 1, "departure": "A", "arrival": "B", "logon_time": "2026-07-02T10:25:00Z"},
            {"id": 2, "departure": "B", "arrival": "C", "logon_time": "2026-07-02T10:25:00.500000Z"},
        ]
        result = _flightplan_asof(plan_rows, "2026-07-02T10:25:00Z")
        assert result is not None and result["id"] == 1


class TestTimeBasedPlanAssignment:
    """Integrationstests für die zeitbasierte Flugplan-Zuordnung (Nutzer-Entscheidung
    2026-07-05, ersetzt Spec G / Startplatz-primär) durch die volle canonicalize_legs-
    Pipeline."""

    def test_single_plan_covers_intermediate_landing_frs96(self):
        """FRS96: EIN Plan A(EDDK)->C(EDDL) gefiled, GPS erkennt eine Zwischenlandung in
        EDDW (kein Refile) -> BEIDE Legs (EDDK->EDDW und EDDW->EDDL) bekommen denselben
        Plan (vorher bekam das EDDW->EDDL-Leg kein Match, weil dessen GPS-Startplatz EDDW
        nicht zum gefileten Startplatz EDDK passte)."""
        conn = _make_conn()
        cid = 5001
        flight_id = _insert_flight(
            conn, cid=cid, callsign="FRS50", departure="EDDK", arrival="EDDL",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T11:15:00Z",
            route="EDDK DKB EDDL",
        )
        _seed_eddk_eddw_eddl_intermediate_landing_track(conn, cid, "FRS50")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        assert len(fs) == 2
        leg1 = next(f for f in fs if f["gps_departure"] == "EDDK")
        leg2 = next(f for f in fs if f["gps_departure"] == "EDDW")

        for leg in (leg1, leg2):
            assert leg["id"] == flight_id
            assert leg["plan_departure"] == "EDDK"
            assert leg["plan_arrival"] == "EDDL"
            assert leg["route"] == "EDDK DKB EDDL"

    def test_two_real_refiled_plans_stay_exclusive(self):
        """Regressionsschutz: ECHTES Refile mit Start-Wechsel (EDDK->EDDW abgeschlossen bei
        der Landung, danach EDDW->EDDL neu gefiled) -- jedes Leg bekommt weiterhin GENAU
        seinen eigenen Plan (bisheriges korrektes Verhalten bleibt erhalten, weil das zweite
        Filing zeitlich klar NACH der Landung von Leg 1 liegt)."""
        conn = _make_conn()
        cid = 5002
        id_ab = _insert_flight(
            conn, cid=cid, callsign="FRS51", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:40:00Z",
        )
        id_bc = _insert_flight(
            conn, cid=cid, callsign="FRS51", departure="EDDW", arrival="EDDL",
            logon_time="2026-07-02T10:45:00Z", logoff_time=None,
        )
        _seed_eddk_eddw_eddl_intermediate_landing_track(conn, cid, "FRS51")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        leg1 = next(f for f in fs if f["gps_departure"] == "EDDK")
        leg2 = next(f for f in fs if f["gps_departure"] == "EDDW")
        assert leg1["id"] == id_ab
        assert leg2["id"] == id_bc

    def test_premature_refile_before_landing_is_visible(self):
        """Nutzer-Klarstellung: Pilot filed EDDW->EDDL bereits waehrend Leg 1 (EDDK->EDDW)
        noch in der Luft ist (10:25, vor der Landung um 10:40) -- BEWUSST kein Schutz: Leg 1
        bekommt den NEUEN (falsch anmutenden) Plan zugeordnet, sichtbar am Mismatch
        plan_departure=EDDW != gps_departure=EDDK. Klarer Pilotenfehler, darf sichtbar sein."""
        conn = _make_conn()
        cid = 5003
        _insert_flight(
            conn, cid=cid, callsign="FRS52", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:25:00Z",
        )
        id_new = _insert_flight(
            conn, cid=cid, callsign="FRS52", departure="EDDW", arrival="EDDL",
            logon_time="2026-07-02T10:25:05Z", logoff_time=None,
        )
        _seed_eddk_eddw_eddl_intermediate_landing_track(conn, cid, "FRS52")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        leg1 = next(f for f in fs if f["gps_departure"] == "EDDK")
        leg2 = next(f for f in fs if f["gps_departure"] == "EDDW")

        assert leg1["id"] == id_new
        assert leg1["plan_departure"] == "EDDW"  # sichtbarer Mismatch -- akzeptiertes Verhalten
        assert leg1["gps_departure"] == "EDDK"
        assert leg2["id"] == id_new
        assert leg2["plan_departure"] == "EDDW"
        assert leg2["plan_arrival"] == "EDDL"

    def test_pure_connect_without_ever_filing_shows_no_plan(self):
        conn = _make_conn()
        cid = 5004
        _insert_flight(
            conn, cid=cid, callsign="FRS53", departure="", arrival="",
            logon_time="2026-07-02T09:55:00Z", logoff_time=None,
        )
        _seed_eddk_eddw_track(conn, cid, "FRS53")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        flight = next(f for f in result if f["cid"] == cid)
        assert flight["id"] is None
        assert flight["plan_departure"] is None
        assert flight["route"] == ""

    def test_early_leg_before_first_filing_has_no_plan_later_leg_does(self):
        """Spontaner Kurzflug EDDK->EDDW (08:00-08:40) OHNE jeden Plan; erst waehrend des
        Bodenaufenthalts in EDDW wird um 09:00 ERSTMALS ein Plan gefiled (EDDW->EDDK) --
        das fruehe Leg bleibt planlos, das anschliessende Leg (Abflug 09:06) bekommt den
        Plan."""
        conn = _make_conn()
        cid = 5005
        _insert_flight(
            conn, cid=cid, callsign="FRS54", departure="", arrival="",
            logon_time="2026-07-02T07:55:00Z", logoff_time="2026-07-02T08:59:50Z",
        )
        id_return = _insert_flight(
            conn, cid=cid, callsign="FRS54", departure="EDDW", arrival="EDDK",
            logon_time="2026-07-02T09:00:00Z", logoff_time=None,
        )
        for ts, lat, lon, alt, gs in [
            ("2026-07-02T08:00:00Z", *EDDK, 302, 0),
            ("2026-07-02T08:01:00Z", *EDDK, 302, 10),
            ("2026-07-02T08:03:00Z", *EDDK, 302, 12),
            ("2026-07-02T08:05:00Z", *EDDK, 302, 15),
            ("2026-07-02T08:06:00Z", *EDDK, 1200, 80),
            ("2026-07-02T08:20:00Z", 52.0, 8.0, 5000, 120),
            ("2026-07-02T08:38:00Z", 53.0, 8.7, 500, 60),
            ("2026-07-02T08:40:00Z", *EDDW, 20, 0),
            ("2026-07-02T08:48:00Z", *EDDW, 20, 0),
            ("2026-07-02T08:56:00Z", *EDDW, 20, 0),
            ("2026-07-02T09:00:00Z", *EDDW, 20, 0),
            ("2026-07-02T09:06:00Z", *EDDW, 1200, 80),
            ("2026-07-02T09:20:00Z", 52.0, 8.0, 5000, 120),
            ("2026-07-02T09:38:00Z", 51.0, 7.3, 500, 60),
            ("2026-07-02T09:40:00Z", *EDDK, 302, 0),
            ("2026-07-02T09:44:00Z", *EDDK, 302, 0),
        ]:
            _insert_pos(conn, cid, ts, lat, lon, alt, gs, "FRS54")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        assert len(fs) == 2, f"erwartete 2 Legs (EDDK->EDDW, EDDW->EDDK), bekam {len(fs)}"
        early_leg = next(f for f in fs if f["gps_departure"] == "EDDK")
        later_leg = next(f for f in fs if f["gps_departure"] == "EDDW")

        assert early_leg["id"] is None
        assert early_leg["plan_departure"] is None
        assert later_leg["id"] == id_return
        assert later_leg["plan_departure"] == "EDDW"
        assert later_leg["plan_arrival"] == "EDDK"


class TestPlanRowsLookback:
    def test_plan_candidate_closed_shortly_before_narrow_window_start_still_matches(self):
        """Live-Fund 2026-07-05 (FRS61/CID 1031301, Events-Fenster ab 18:00): eine ECHTE,
        laengst geschlossene Connection (logoff kurz nach dem letzten GPS-Sample) verschwand
        aus den Flugplan-Kandidaten eines schmalen Abfragefensters, weil deren logoff_time
        knapp VOR dem Fenster-`start` lag -- _flightplan_asof fand dadurch KEINEN Kandidaten
        mehr fuer das (per GPS weiterhin "offene", weil kein Landing erkannte) Leg und der
        Flugplan blieb leer (Aircraft fiel auf den global letzten bekannten Typ zurueck,
        hier faelschlich SA65 statt des tatsaechlich gefileten EC45).

        Eine ZWEITE, spaetere Connection (Reconnect + Refile, wie im Live-Fund id=257) haelt
        die cid im schmalen Fenster "sichtbar" -- ohne sie wuerde die cid komplett aus
        fs_by_cid herausfallen und das fruehe Leg gar nicht erst berechnet (ein noch
        deutlicheres, aber anderes Symptom als das gemeldete "ohne Flugplan").

        GPS-Track des ersten Legs bricht bewusst OHNE erkannte Landung ab (Positionen enden
        waehrend des Streckenflugs) -- genau das reproduziert "gps_arrival leer trotz laengst
        geschlossener Connection", der Fall, in dem _in_window() das Leg unabhaengig vom
        Fenster durchlaesst (logoff_time im Ergebnis-Dict ist None, weil GPS keine Landung
        sah)."""
        conn = _make_conn()
        cid = 5008
        flight_id = _insert_flight(
            conn, cid=cid, callsign="FRS56", departure="EDDK", arrival="EDDW",
            aircraft_short="EC45",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:35:00Z",
        )
        # Reconnect + Refile Stunden spaeter, gleiche Strecke -- haelt die cid im schmalen
        # Fenster praesent (wie id=257 im Live-Fund), OHNE selbst der Plan-Kandidat fuer das
        # fruehe Leg zu sein (logon liegt NACH dem fruehen Legs-Ende, _flightplan_asof darf
        # diese Zeile also nicht waehlen).
        _insert_flight(
            conn, cid=cid, callsign="FRS56", departure="EDDK", arrival="EDDW",
            aircraft_short="EC45",
            logon_time="2026-07-02T14:30:00Z", logoff_time="2026-07-02T15:10:00Z",
        )
        for ts, lat, lon, alt, gs in [
            ("2026-07-02T10:00:00Z", *EDDK, 302, 0),
            ("2026-07-02T10:01:00Z", *EDDK, 302, 10),
            ("2026-07-02T10:03:00Z", *EDDK, 302, 12),
            ("2026-07-02T10:05:00Z", *EDDK, 302, 15),
            ("2026-07-02T10:06:00Z", *EDDK, 1200, 80),
            ("2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120),
        ]:
            _insert_pos(conn, cid, ts, lat, lon, alt, gs, "FRS56")
        conn.commit()

        # Schmales Fenster ca. 3h40 NACH dem echten logoff (10:35) des fruehen Legs --
        # innerhalb der 12h-Lookback-Grenze, genau wie im Live-Fund (Events-Fenster
        # 18:00-20:00 desselben Tages, Connection-Ende ~15:xx).
        narrow_window = dict(start="2026-07-02T14:00:00Z", end="2026-07-02T16:00:00Z")
        result = canonicalize_legs(conn, callsign_prefix="FRS", **narrow_window)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        early_leg = next(f for f in fs if f["logon_time"] < "2026-07-02T11:00:00Z")
        assert early_leg["gps_arrival"] is None, "Testvorbedingung: GPS darf keine Landung sehen"
        assert early_leg["id"] == flight_id
        assert early_leg["plan_departure"] == "EDDK"
        assert early_leg["plan_arrival"] == "EDDW"
        assert early_leg["aircraft"] == "EC45"

    def test_refile_filed_after_narrow_window_end_still_labels_leg(self):
        """Live-Fund 2026-07-05 (FRS119N/CID 1976702, Events-Fenster bis 20:00) --
        Spiegelfall zum start-seitigen Bug oben: der Pilot flog EDDK->EDDW, landete, und
        feilte beim Start in EDDW mit Startplatz-Wechsel NEU (EDDW->EDDL, anderer Muster
        PA28). Der Refile erzeugt eine neue flights-Zeile, deren logon_time (Poller-Erkennung
        des Startplatz-Wechsels) NACH dem Fenster-`end` liegt. Das zweite GPS-Leg startet
        aber noch VOR `end` -- es ist also im Fenster, sein korrekter Flugplan aber nicht in
        den Kandidaten (fs_where filterte `logon_time <= end`). Folge (buggy): das Leg
        bekam faelschlich den ALTEN Plan EDDK->EDDW (Muster C172) statt EDDW->EDDL (PA28) --
        genau die 'zwei verschiedenen Wahrheiten' zwischen Statistik (kein end) und Events
        (end gesetzt).

        Fix: der end-Oberrand fuer die Plan-Kandidaten bekommt denselben Puffer wie der
        start-Unterrand -- die Leg-Auswahl (`_in_window`) nutzt weiterhin das echte `end`."""
        conn = _make_conn()
        cid = 5009
        _insert_flight(
            conn, cid=cid, callsign="FRS57", departure="EDDK", arrival="EDDW",
            aircraft_short="C172",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:40:00Z",
        )
        # Refile mit Startplatz-Wechsel WAEHREND des zweiten Legs -- logon (Poller-Erkennung)
        # liegt NACH dem schmalen Fenster-end (10:48), das Leg selbst startet aber 10:46.
        id_refile = _insert_flight(
            conn, cid=cid, callsign="FRS57", departure="EDDW", arrival="EDDL",
            aircraft_short="PA28",
            logon_time="2026-07-02T10:50:00Z", logoff_time=None,
        )
        _seed_eddk_eddw_eddl_intermediate_landing_track(conn, cid, "FRS57")
        conn.commit()

        # Fenster endet 10:48: Leg 2 (Takeoff 10:46) ist drin, der Refile (logon 10:50) nicht.
        narrow_window = dict(start="2026-07-02T10:00:00Z", end="2026-07-02T10:48:00Z")
        result = canonicalize_legs(conn, callsign_prefix="FRS", **narrow_window)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        leg2 = next(f for f in fs if f["gps_departure"] == "EDDW")
        assert leg2["gps_arrival"] == "EDDL"
        assert leg2["id"] == id_refile
        assert leg2["plan_departure"] == "EDDW"
        assert leg2["plan_arrival"] == "EDDL"
        assert leg2["aircraft"] == "PA28"


class TestStatsimIdPropagation:
    def test_statsim_id_propagates_across_split_legs(self):
        """StatSim-Pendant zum FRS96-Fix (Live-Fund FRS1116/CID 1637198): eine einzige
        statsim_cache-Zeile (ein statsim_id), GPS-Track mit Zwischenlandung -> BEIDE
        resultierenden Legs bekommen dieselbe statsim_id (vorher bekam nur das erste Leg
        sie, das Folge-Leg hatte statsim_id=None -> toter Track-Button trotz vorhandenem
        Track in statsim_position_history)."""
        conn = _make_conn()
        cid = 5006
        _insert_statsim(
            conn, 9601, cid=cid, callsign="FRS55", departure="EDDK", arrival="EDDL",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T11:15:00Z",
            duration_min=77, aircraft="C172",
        )
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:00:00Z", *EDDK, 302, 0)
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:06:00Z", *EDDK, 1200, 80)
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:20:00Z", 52.0, 8.0, 5000, 120)
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:38:00Z", 53.0, 8.7, 500, 60)
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:40:00Z", *EDDW, 20, 0)  # Touchdown EDDW
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:45:00Z", *EDDW, 20, 0)
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:46:00Z", *EDDW, 1300, 85)
        _insert_statsim_pos(conn, 9601, "2026-07-02T10:50:00Z", 52.0, 7.5, 5000, 140)
        _insert_statsim_pos(conn, 9601, "2026-07-02T11:08:00Z", 51.35, 6.85, 1500, 90)
        _insert_statsim_pos(conn, 9601, "2026-07-02T11:15:00Z", *EDDL, 150, 0)  # Touchdown EDDL
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        st = [f for f in result if f["cid"] == cid and f["source"] == "statsim"]
        assert len(st) == 2
        leg1 = next(f for f in st if f["gps_departure"] == "EDDK")
        leg2 = next(f for f in st if f["gps_departure"] == "EDDW")
        assert leg1["statsim_id"] == 9601
        assert leg2["statsim_id"] == 9601


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
        nicht nur isoliert über _flightplan_asof."""
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


# --- Regression: Reconnect an einem ANDEREN Platz (Track sprang quer über die Karte) ---


class TestReconnectAtOtherAirport:
    def test_block_start_stays_at_own_departure_airport(self):
        """Der Rückwärts-Walk für ``block_start`` darf nicht über einen Reconnect an einem
        ANDEREN Platz hinweglaufen.

        Realfall (Engelhard Hinrichs, 27.07.2026): Leg 1 landet in EDLX, der Pilot verbindet
        sich 29 min später in EDWG neu und fliegt EDWG→EDXH. Weil die Sample-Lücke mit 29 min
        UNTER ``_GPS_LEG_GAP_MINUTES`` (30) liegt und die einzige Schranke des Walks
        ``prev_end`` (= Landungs-ts von Leg 1) war, lief er bis in die Standzeit von Leg 1
        zurück. ``block_start`` zeigte damit auf den 240 km entfernten Vorgänger-Platz — und
        weil das Frontend ``block_start`` als Track-Untergrenze nutzt, begann die gezeichnete
        Linie dort und sprang quer über die Karte zum echten Startplatz.

        Hier nachgestellt mit denselben Abständen: Leg 1 EDDK→EDDW (Landung 10:40, Standzeit
        bis 10:44), 29 min Lücke, Leg 2 ab EDDL (Boden ab 11:13, Abheben 11:18) nach EDDK.
        EDDW→EDDL sind 239 km — dieselbe Größenordnung wie im Realfall.
        """
        conn = _make_conn()
        cid = 4315
        _insert_flight(
            conn, cid=cid, callsign="FRS45", departure="EDDK", arrival="EDDK",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T11:55:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS45")  # Leg 1: EDDK→EDDW, Standzeit bis 10:44
        # 29 min Lücke (10:44 → 11:13) — unter _GPS_LEG_GAP_MINUTES, also DASSELBE Zeit-Segment.
        _insert_pos(conn, cid, "2026-07-02T11:13:00Z", *EDDL, 147, 0, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:15:00Z", *EDDL, 147, 12, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:17:00Z", *EDDL, 147, 15, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:18:00Z", *EDDL, 1200, 80, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:30:00Z", 52.0, 7.5, 5000, 120, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:45:00Z", 51.0, 7.2, 500, 60, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:47:00Z", *EDDK, 302, 0, "FRS45")
        _insert_pos(conn, cid, "2026-07-02T11:50:00Z", *EDDK, 302, 0, "FRS45")
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        fs = [f for f in result if f["cid"] == cid and f["source"] == "friesenspy"]
        assert len(fs) == 2, f"erwartete 2 Legs (EDDK->EDDW, EDDL->EDDK), bekam {len(fs)}"
        leg2 = next(f for f in fs if f["gps_departure"] == "EDDL")

        # Rollbeginn ist das erste Boden-Sample in EDDL (11:13) — NICHT die Standzeit in EDDW.
        assert leg2["block_start"] == "2026-07-02T11:13:00Z", (
            "block_start liegt vor dem Reconnect — der Track begaenne am falschen Platz"
        )


# --- Härtung (#23, Review-Finding zu Task 4c): prev_end-Schranke -----------------------


class TestPrevEndBoundary:
    def test_second_leg_block_min_excludes_first_legs_airborne_time(self):
        """Kern-Regression für die Trennung zweier Legs in der Blockzeit (KORREKTUR #23
        Phase 2, Blockzeit gate-to-gate): bei einer ECHTEN Zwischenlandung (zwei Legs im
        selben Zeit-Segment, Turnaround-Boden-Rollen <= 30 min) darf ``block_start`` des
        ZWEITEN Legs nicht vor das Landungs-Ende des ERSTEN Legs zurückreichen — sonst würde
        die komplette Luftzeit von Leg 1 (Taxi + Steigen + Reise + Sinken, ~34 min)
        fälschlich in die Blockzeit von Leg 2 mit hineingezählt (Doppelzählung).

        Die Schranke sitzt in ``_detect_segment`` (app/gps_legs.py): beim Aufsetzen beginnt
        eine NEUE Boden-/Rollphase (``ground_since_ts = Aufsetz-ts``), die dem Folge-Leg als
        ``taxi_start_ts`` mitgegeben wird. Früher war es stattdessen eine ``prev_end``-Schranke
        um einen Rückwärts-Walk in ``_gps_flights_for_positions`` — die griff bei einem
        Reconnect an einem anderen Platz nicht (s. ``TestReconnectAtOtherAirport``).

        Track (``_seed_eddk_eddw_eddl_intermediate_landing_track``): EDDK→EDDW (10:00-10:40,
        Taxi-out ab 10:00, Airborne 10:06-10:40) → Turnaround in EDDW (10:40-10:46, 6 min,
        <= 30 min) → EDDW→EDDL (Airborne 10:46-11:10).

        Exakter erwarteter ``block_min`` von Leg 2 MIT ``prev_end``-Schranke ("fix/blockzeit-
        anblock": _leg_block_seconds als Wanduhr statt der Summe bewegter Abschnitte, s.
        TestFormParity für die allgemeine Herleitung): ``block_from`` ist der erste
        Bewegungsnachweis NACH der Landung von Leg 1 (10:41:00, erstes Sample mit
        groundspeed > 2 kt im Turnaround — 10:40:00 selbst ist der Touchdown mit gs=0),
        ``block_end`` bleibt bei 11:10 (kein Rollen nach der Landung in EDDL nachweisbar).
        10:41–11:10 = 29 min, keine qualifizierende Abstell-Standphase im Fenster (der
        einzelne gs=0-Ausreißer um 10:43 ist mit 0 s weit unter der 600-s-Schwelle) → 29.

        OHNE die ``prev_end``-Schranke (Neustart der Rollphase beim Aufsetzen) reichte
        ``block_start``/``block_from`` von Leg 2 bis in Leg 1 zurück und risse dessen
        komplette Luftzeit (~34 min zusätzlich) mit in Leg 2s Blockzeit — der Regressionstest
        unten prüft das nicht über eine zweite feste Zahl, sondern strukturell (Zeile
        ``block_min < leg1.duration_min + leg2.duration_min``): jede Vermischung der beiden
        Luftzeiten würde diese Schranke sprengen.
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

        # Exakter Wert — s. Docstring oben für die Herleitung (fix/blockzeit-anblock: 27 -> 29,
        # da block_min jetzt Wanduhr ab dem ersten Bewegungsnachweis zaehlt statt der Summe
        # bewegter Abschnitte).
        assert leg2["duration_min"] == 24
        assert leg2["block_min"] == 29
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


class TestGpsDetectionGaps:
    """v8.6.0: Admin-Prüfliste für Flüge mit fehlendem GPS-Start/-Landung trotz bekanntem
    Flugplan-Wert -- Kandidaten für fehlende custom_airports-Einträge."""

    def _iso(self, dt) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _recent(self, minutes_ago: int) -> str:
        from datetime import datetime, timedelta, timezone
        return self._iso(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))

    def test_lists_missing_departure_and_arrival(self):
        from app.database import list_gps_detection_gaps
        conn = _make_conn()
        cid = 5501
        # Reiner Connect ohne jeden Track -> gps_departure UND gps_arrival fehlen,
        # Plan kennt beide -> "both". distance_nm > 0.5 verhindert die Ghost-Erkennung
        # (_is_ghost_row) fuer kurze Test-Connects.
        _insert_flight(
            conn, cid=cid, callsign="FRS55", departure="EDST", arrival="EDWQ",
            logon_time=self._recent(120), logoff_time=self._recent(90),
            duration_min=30, distance_nm=40.0,
        )
        conn.commit()

        gaps = list_gps_detection_gaps(conn)
        conn.close()

        gap = next(g for g in gaps if g["cid"] == cid)
        assert gap["missing"] == "both"
        assert gap["plan_departure"] == "EDST"
        assert gap["plan_arrival"] == "EDWQ"
        assert gap["gps_departure"] is None
        assert gap["gps_arrival"] is None
        assert gap["pilot_name"] == f"Pilot {cid}"

    def test_excludes_healthy_flights(self):
        """Ein Flug mit vollständigem GPS-Track (Start UND Landung erkannt) taucht nicht auf."""
        from app.database import list_gps_detection_gaps
        conn = _make_conn()
        cid = 5502
        _insert_flight(
            conn, cid=cid, callsign="FRS56", departure="EDDK", arrival="EDDW",
            logon_time="2026-07-02T09:55:00Z", logoff_time="2026-07-02T10:50:00Z",
        )
        _seed_eddk_eddw_track(conn, cid, "FRS56")
        conn.commit()

        gaps = list_gps_detection_gaps(conn)
        conn.close()

        assert not any(g["cid"] == cid for g in gaps)

    def test_open_flight_not_counted_as_missing_arrival(self):
        """Ein noch offener Flug (kein connection_closed) zählt nicht als Landungs-Lücke --
        er ist schlicht noch nicht gelandet, kein Datenfehler."""
        from app.database import list_gps_detection_gaps
        conn = _make_conn()
        cid = 5503
        _insert_flight(
            conn, cid=cid, callsign="FRS57", departure="EDST", arrival="EDWQ",
            logon_time=self._recent(10), logoff_time=None,
            duration_min=10, distance_nm=15.0,
        )
        conn.commit()

        gaps = list_gps_detection_gaps(conn)
        conn.close()

        gap = next((g for g in gaps if g["cid"] == cid), None)
        assert gap is None or gap["missing"] == "departure"

    def test_excludes_dismissed(self):
        from app.database import list_gps_detection_gaps, dismiss_gps_detection_gap
        conn = _make_conn()
        cid = 5504
        logon = self._recent(120)
        _insert_flight(
            conn, cid=cid, callsign="FRS58", departure="EDST", arrival="EDWQ",
            logon_time=logon, logoff_time=self._recent(90),
            duration_min=30, distance_nm=40.0,
        )
        conn.commit()

        gaps_before = list_gps_detection_gaps(conn)
        assert any(g["cid"] == cid for g in gaps_before)

        dismiss_gps_detection_gap(conn, cid, logon)
        conn.commit()

        gaps_after = list_gps_detection_gaps(conn)
        conn.close()
        assert not any(g["cid"] == cid for g in gaps_after)


class TestStatsimMidAirSplitContinuity:
    """`_statsim_rows_continuous` — die Merge-Regel für StatSim-Mid-Air-Splits (Live-Fund
    2026-07-06, KNF04WC). Direkte Unit-Tests auf die Entscheidung, plus ein Integrationstest
    durch canonicalize_legs, der den Geister-Fall (gestartet-nie-gelandet) auflöst.
    """

    def _pos(self, ts, lat, lon, gs):
        return {"ts": ts, "latitude": lat, "longitude": lon, "altitude": 5000, "groundspeed": gs}

    def test_merges_when_both_sides_airborne_small_gap(self):
        from app.database import _statsim_rows_continuous
        row_a = {"departure": "EDDK", "arrival": "EDDL"}
        row_b = {"departure": "EDDK", "arrival": "EDDL"}  # gleicher Plan → Fenster 30 min
        pos_a = [self._pos("2026-07-02T10:10:00Z", 51.0, 7.0, 120),
                 self._pos("2026-07-02T10:15:00Z", 51.1, 6.9, 120)]  # endet airborne
        pos_b = [self._pos("2026-07-02T10:16:00Z", 51.12, 6.88, 120),  # 60 s später, airborne, näher EDDL
                 self._pos("2026-07-02T10:20:00Z", 51.2, 6.82, 100)]
        assert _statsim_rows_continuous(row_a, row_b, pos_a, pos_b) is True

    def test_no_merge_when_b_starts_on_ground(self):
        """Der Fehlmerge-Schutz (Option 3): B beginnt am Boden (Taxi/Startlauf) → ein separater
        neuer Flug, KEIN Mid-Air-Split. Trotz kleiner Zeitlücke und Nähe nicht mergen."""
        from app.database import _statsim_rows_continuous
        row_a = {"departure": "EDDK", "arrival": "EDDL"}
        row_b = {"departure": "EDDK", "arrival": "EDDL"}
        pos_a = [self._pos("2026-07-02T10:10:00Z", 51.0, 7.0, 120),
                 self._pos("2026-07-02T10:15:00Z", 51.1, 6.9, 120)]  # A endet airborne
        pos_b = [self._pos("2026-07-02T10:16:00Z", 51.12, 6.88, 12),  # B startet am Boden (gs 12)
                 self._pos("2026-07-02T10:20:00Z", 51.12, 6.88, 15)]
        assert _statsim_rows_continuous(row_a, row_b, pos_a, pos_b) is False

    def test_no_merge_when_a_ends_on_ground(self):
        """Echte Zwischenlandung: A endet am Boden (gelandet) → abgeschlossen, kein Reconnect."""
        from app.database import _statsim_rows_continuous
        row_a = {"departure": "EDDK", "arrival": "EDDW"}
        row_b = {"departure": "EDDW", "arrival": "EDDL"}
        pos_a = [self._pos("2026-07-02T10:10:00Z", 51.0, 7.0, 120),
                 self._pos("2026-07-02T10:40:00Z", *EDDW, 0)]  # A landet (gs 0)
        pos_b = [self._pos("2026-07-02T10:46:00Z", *EDDW, 85),
                 self._pos("2026-07-02T11:00:00Z", 51.3, 6.8, 120)]
        assert _statsim_rows_continuous(row_a, row_b, pos_a, pos_b) is False

    def test_no_merge_when_gap_exceeds_window(self):
        """Zeitfenster: gleiche Plandaten → 30 min. Eine 40-min-Lücke trennt (kein Reconnect)."""
        from app.database import _statsim_rows_continuous
        row_a = {"departure": "EDDK", "arrival": "EDDL"}
        row_b = {"departure": "EDDK", "arrival": "EDDL"}
        pos_a = [self._pos("2026-07-02T10:00:00Z", 51.0, 7.0, 120),
                 self._pos("2026-07-02T10:15:00Z", 51.1, 6.9, 120)]
        pos_b = [self._pos("2026-07-02T10:55:00Z", 51.12, 6.88, 120),  # 40 min später
                 self._pos("2026-07-02T11:00:00Z", 51.2, 6.82, 100)]
        assert _statsim_rows_continuous(row_a, row_b, pos_a, pos_b) is False

    def test_no_merge_when_b_earlier_than_a(self):
        """Fehlsortierung (unzuverlässige StatSim-logon_time): B liegt real VOR A → gap < 0 →
        nicht mergen (safe fallback aufs Einzel-Verhalten)."""
        from app.database import _statsim_rows_continuous
        row_a = {"departure": "EDDK", "arrival": "EDDL"}
        row_b = {"departure": "EDDK", "arrival": "EDDL"}
        pos_a = [self._pos("2026-07-02T10:16:00Z", 51.12, 6.88, 120)]
        pos_b = [self._pos("2026-07-02T10:10:00Z", 51.0, 7.0, 120)]  # früher als A
        assert _statsim_rows_continuous(row_a, row_b, pos_a, pos_b) is False

    def test_ghost_leg_resolved_by_merge(self):
        """Integration: StatSim schneidet EINEN Flug EDDK→EDDL mitten in der Luft in zwei ids —
        id A endet airborne (kein Landing → Geister-Leg 'EDDK→—'), id B spawnt 60 s später
        airborne und landet EDDL ('—→EDDL'). Nach dem Merge: EIN sauberes Leg EDDK→EDDL,
        kein Geister-Leg mit gps_arrival=None mehr."""
        conn = _make_conn()
        cid = 5700
        # id A: EDDK-Start + Steigflug, Track endet mitten im Reiseflug (kein Touchdown).
        _insert_statsim(
            conn, 9701, cid=cid, callsign="FRS60", departure="EDDK", arrival="EDDL",
            logon_time="2026-07-02T09:58:00Z", logoff_time="2026-07-02T10:15:00Z",
            duration_min=17, aircraft="C172",
        )
        _insert_statsim_pos(conn, 9701, "2026-07-02T10:00:00Z", *EDDK, 302, 0)
        _insert_statsim_pos(conn, 9701, "2026-07-02T10:01:00Z", *EDDK, 302, 15)
        _insert_statsim_pos(conn, 9701, "2026-07-02T10:03:00Z", *EDDK, 1200, 80)
        _insert_statsim_pos(conn, 9701, "2026-07-02T10:10:00Z", 51.0, 7.0, 5000, 120)
        _insert_statsim_pos(conn, 9701, "2026-07-02T10:15:00Z", 51.1, 6.9, 5000, 120)  # endet airborne
        # id B: spawnt 60 s später airborne, sinkt, landet EDDL.
        _insert_statsim(
            conn, 9702, cid=cid, callsign="FRS60", departure="EDDK", arrival="EDDL",
            logon_time="2026-07-02T10:14:00Z", logoff_time="2026-07-02T10:25:00Z",
            duration_min=11, aircraft="C172",
        )
        _insert_statsim_pos(conn, 9702, "2026-07-02T10:16:00Z", 51.12, 6.88, 5000, 120)
        _insert_statsim_pos(conn, 9702, "2026-07-02T10:20:00Z", 51.2, 6.82, 2000, 100)
        _insert_statsim_pos(conn, 9702, "2026-07-02T10:23:00Z", 51.27, 6.78, 500, 60)
        _insert_statsim_pos(conn, 9702, "2026-07-02T10:25:00Z", *EDDL, 150, 0)  # Touchdown EDDL
        conn.commit()

        result = canonicalize_legs(conn, callsign_prefix="FRS", **WINDOW)
        conn.close()

        st = [f for f in result if f["cid"] == cid and f["source"] == "statsim"]
        assert len(st) == 1                          # EIN Leg, kein Geister-Leg
        assert st[0]["gps_departure"] == "EDDK"
        assert st[0]["gps_arrival"] == "EDDL"
        assert not any(f["gps_arrival"] is None for f in st)


class TestDurationLeBlockGuarantee:
    """"fix/blockzeit-anblock": duration_min <= block_min muss IMMER gelten -- das Fenster
    der Flugzeit [takeoff_ts, end_ts] liegt strukturell innerhalb des Blockfensters
    [block_from, block_end], und jede Standphase, die block_min abzieht UND im Flugfenster
    liegt, erfüllt automatisch auch das (lockerere) Kriterium von duration_min. Diese Klasse
    prüft die Garantie an den Rändern, an denen sie am ehesten brechen könnte -- inklusive
    des einen Falls, in dem allein die strukturelle Herleitung NICHT reicht und der Floor
    in `_gps_flights_for_positions` (`block_min = max(block_min, duration_min)`) greift."""

    def test_floor_rescues_guarantee_when_speed_reported_zero_throughout(self):
        """Quelle meldet durchgehend groundspeed=0, obwohl die Position sich klar bewegt
        (StatSim: `p.get("speed", 0)` bei fehlendem Feld, s. app/statsim.py:127). Ohne den
        Floor würde `_leg_block_seconds` das GESAMTE Fenster als EINEN Stand werten (jedes
        Sample gs<=2, die ERSTE Position des Laufs liegt am Abflugplatz -> qualifiziert) und
        komplett abziehen -> block_min=0 trotz positiver Flugzeit (verifiziert: roh, ohne
        Floor, liefert `_leg_block_seconds` hier exakt 0). Der Floor in
        `_gps_flights_for_positions` federt genau das ab."""
        positions = [
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 302,
             "groundspeed": 0, "ts": "2026-07-02T10:00:00Z"},
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 1500,
             "groundspeed": 0, "ts": "2026-07-02T10:06:00Z"},  # Takeoff via AGL-Steigung
            {"latitude": 52.0, "longitude": 8.0, "altitude": 5000,
             "groundspeed": 0, "ts": "2026-07-02T10:20:00Z"},
            {"latitude": 53.0, "longitude": 8.7, "altitude": 500,
             "groundspeed": 0, "ts": "2026-07-02T10:38:00Z"},
            {"latitude": EDDW[0], "longitude": EDDW[1], "altitude": 200,
             "groundspeed": 0, "ts": "2026-07-02T10:44:00Z"},  # Touchdown EDDW
        ]
        out = _gps_flights_for_positions(positions, plan_rows=[], source="statsim")
        assert len(out) == 1
        flight = out[0]
        assert flight["duration_min"] == 38  # reine Wanduhr [10:06, 10:44], keine Bodenphase
        assert flight["block_min"] == flight["duration_min"], (
            "ohne den Floor waere block_min hier 0 -- s. Docstring des Tests"
        )

    def test_open_leg_without_landing_satisfies_guarantee(self):
        """Track reißt airborne ab (kein Touchdown) -- offenes Leg, end_ts kommt aus dem
        letzten belegten Sample vor der nächsten Zeitlücke."""
        positions = [
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 302,
             "groundspeed": 5, "ts": "2026-07-02T10:00:00Z"},
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 1500,
             "groundspeed": 80, "ts": "2026-07-02T10:06:00Z"},
            {"latitude": 52.0, "longitude": 8.0, "altitude": 5000,
             "groundspeed": 90, "ts": "2026-07-02T10:20:00Z"},
            {"latitude": 52.5, "longitude": 8.3, "altitude": 5000,
             "groundspeed": 85, "ts": "2026-07-02T10:25:00Z"},
        ]
        out = _gps_flights_for_positions(positions, plan_rows=[], source="friesenspy")
        assert len(out) == 1
        flight = out[0]
        assert flight["logoff_time"] is None  # tatsächlich offen
        assert flight["duration_min"] <= flight["block_min"]
        assert flight["duration_min"] > 0 and flight["block_min"] > 0

    def test_data_gap_inside_flight_window_satisfies_guarantee(self):
        """Eine 25-min-Datenlücke MITTEN im (noch offenen) Flugfenster -- unter
        _GPS_LEG_GAP_MINUTES (30), bleibt also im selben Segment. Ohne Belege wird an
        keiner Stelle etwas abgezogen (weder Block noch Flugzeit)."""
        positions = [
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 302,
             "groundspeed": 5, "ts": "2026-07-02T10:00:00Z"},
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 1500,
             "groundspeed": 80, "ts": "2026-07-02T10:06:00Z"},
            {"latitude": 52.0, "longitude": 8.0, "altitude": 5000,
             "groundspeed": 90, "ts": "2026-07-02T10:10:00Z"},
            {"latitude": 52.5, "longitude": 8.3, "altitude": 5000,
             "groundspeed": 85, "ts": "2026-07-02T10:35:00Z"},  # 25 min Lücke
        ]
        out = _gps_flights_for_positions(positions, plan_rows=[], source="friesenspy")
        assert len(out) == 1
        flight = out[0]
        assert flight["duration_min"] <= flight["block_min"]

    def test_constant_ground_position_with_intermediate_landing_satisfies_guarantee(self):
        """Realer Fund (Flug 632, Hubschrauber): Außenlandung MITTEN im Flugfenster, danach
        Weiterflug -- Standzeit im Gelände wird von der Flugzeit abgezogen (Kriterium
        Position), von der Blockzeit nicht (Kriterium Flugplatznähe, hier REMOTE). Die
        Garantie muss trotz der divergierenden Kriterien halten."""
        positions = [
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 302,
             "groundspeed": 5, "ts": "2026-07-02T10:00:00Z"},
            {"latitude": EDDK[0], "longitude": EDDK[1], "altitude": 1500,
             "groundspeed": 80, "ts": "2026-07-02T10:06:00Z"},
            {"latitude": REMOTE[0], "longitude": REMOTE[1], "altitude": 250,
             "groundspeed": 0, "ts": "2026-07-02T10:20:00Z"},  # Außenlandung im Gelände
            {"latitude": REMOTE[0], "longitude": REMOTE[1], "altitude": 250,
             "groundspeed": 0, "ts": "2026-07-02T10:35:00Z"},  # 15 min Stand, kein Platz nah
            {"latitude": REMOTE[0], "longitude": REMOTE[1], "altitude": 1200,
             "groundspeed": 70, "ts": "2026-07-02T10:37:00Z"},  # Weiterflug
        ]
        out = _gps_flights_for_positions(positions, plan_rows=[], source="friesenspy")
        assert len(out) == 1
        flight = out[0]
        assert flight["logoff_time"] is None  # nie an einem Platz gelandet -> offen
        assert flight["duration_min"] <= flight["block_min"]
