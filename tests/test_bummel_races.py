"""Tests für die persistente Bummel-Renn-Verwaltung (bummel_races) + Mitternacht-Default."""
from __future__ import annotations

import sqlite3

import pytest

from app.database import (
    _bummel_anyone_in_progress,
    _effective_dtend,
    bummel_open_starters,
    get_bummel_race,
    get_connection,
    init_db,
    list_bummel_races,
    set_bummel_revealed,
    set_bummel_reveal_suppressed,
    update_bummel_reveals,
    update_bummel_starts,
    upsert_calendar_bummel_race,
)
from app.geo import icao_to_coords


def _add_open_flight(conn, cid, dep_coord, logon, dep_fp="EDWF", gs=0):
    """Offener Flug (logoff NULL) + eine GPS-Startposition am Flugplatz (gs=0 = steht noch)."""
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)", (cid, f"P{cid}", logon)
    )
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
        "logon_time, logoff_time, duration_min, distance_nm, block_min) "
        "VALUES (?, ?, 'C172', ?, 'EDWG', ?, NULL, NULL, NULL, NULL)",
        (cid, f"FRS{cid}", dep_fp, logon),
    )
    conn.execute(
        "INSERT INTO position_history (cid, latitude, longitude, altitude, groundspeed, heading, ts) "
        "VALUES (?, ?, ?, 200, ?, 0, ?)",
        (cid, dep_coord[0], dep_coord[1], gs, logon),
    )
    conn.commit()


def _make_conn() -> sqlite3.Connection:
    init_db(":memory:")
    conn = get_connection(":memory:")
    from app.database import _DDL
    conn.executescript(_DDL)
    conn.commit()
    return conn


class TestEffectiveDtend:
    def test_uses_given_end(self):
        assert _effective_dtend("2026-06-27T18:00:00Z", "2026-06-27T20:00:00Z") == "2026-06-27T20:00:00Z"

    def test_midnight_default_when_empty(self):
        # Fehlt dtend → Mitternacht UTC am Ende des Starttags (Folgetag 00:00:00Z)
        assert _effective_dtend("2026-06-27T18:00:00Z", "") == "2026-06-28T00:00:00Z"

    def test_midnight_default_when_none(self):
        assert _effective_dtend("2026-06-27T18:00:00Z", None) == "2026-06-28T00:00:00Z"


class TestCalendarRaceCrud:
    def test_upsert_get_list_and_reveal(self):
        conn = _make_conn()
        ev = {
            "uid": "bummel_20260627T180000Z",
            "summary": "FriesenFliegerBummel Ostfriesland",
            "route": "EDWF,EDWG,EDWR",
            "dtstart": "2026-06-27T18:00:00Z",
            "dtend": "",  # → Mitternacht-Default
        }
        upsert_calendar_bummel_race(conn, ev)

        races = list_bummel_races(conn)
        assert len(races) == 1
        race = races[0]
        assert race["name"] == "FriesenFliegerBummel Ostfriesland"
        assert race["route"] == "EDWF,EDWG,EDWR"
        assert race["source"] == "calendar"
        assert race["calendar_uid"] == "bummel_20260627T180000Z"
        assert race["dtend"] == "2026-06-28T00:00:00Z"  # Mitternacht-Default angewandt
        assert race["revealed_at"] is None

        # Idempotent: erneutes Upsert legt keine zweite Zeile an
        upsert_calendar_bummel_race(conn, ev)
        assert len(list_bummel_races(conn)) == 1

        rid = race["id"]
        assert get_bummel_race(conn, rid)["name"] == ev["summary"]

        set_bummel_revealed(conn, rid, "2026-06-28T00:05:00Z")
        assert get_bummel_race(conn, rid)["revealed_at"] == "2026-06-28T00:05:00Z"


ROUTE = ["EDWF", "EDWG", "EDWR"]


class TestAnyoneInProgress:
    def test_open_flight_from_route_airport_counts(self):
        conn = _make_conn()
        _add_open_flight(conn, 100, icao_to_coords("EDWF"), "2026-06-27T19:00:00Z")
        assert _bummel_anyone_in_progress(conn, ROUTE, 10) is True

    def test_no_open_flights(self):
        conn = _make_conn()
        assert _bummel_anyone_in_progress(conn, ROUTE, 10) is False

    def test_open_flight_from_other_airport_ignored(self):
        conn = _make_conn()
        _add_open_flight(conn, 100, icao_to_coords("EDDH"), "2026-06-27T19:00:00Z", dep_fp="EDDH")
        assert _bummel_anyone_in_progress(conn, ROUTE, 10) is False

    def test_flight_started_after_cutoff_ignored(self):
        conn = _make_conn()
        _add_open_flight(conn, 100, icao_to_coords("EDWF"), "2026-06-28T00:30:00Z")
        # Nachzügler-Fenster endet 00:00 → späterer Start blockt nicht
        assert _bummel_anyone_in_progress(conn, ROUTE, 10, started_before="2026-06-28T00:00:00Z") is False


class TestRevealLatch:
    def _race(self, conn, dtend):
        upsert_calendar_bummel_race(conn, {
            "uid": "b1", "summary": "Bummel", "route": "EDWF,EDWG,EDWR",
            "dtstart": "2026-06-27T18:00:00Z", "dtend": dtend,
        })
        return list_bummel_races(conn)[0]["id"]

    def test_not_revealed_before_dtend(self):
        conn = _make_conn()
        rid = self._race(conn, "2026-06-27T22:00:00Z")
        update_bummel_reveals(conn, "2026-06-27T20:00:00Z")
        assert get_bummel_race(conn, rid)["revealed_at"] is None

    def test_revealed_after_dtend_when_nobody_in_progress(self):
        conn = _make_conn()
        rid = self._race(conn, "2026-06-27T22:00:00Z")
        update_bummel_reveals(conn, "2026-06-27T22:30:00Z")
        assert get_bummel_race(conn, rid)["revealed_at"] == "2026-06-27T22:30:00Z"

    def test_reveal_deferred_while_someone_in_progress(self):
        conn = _make_conn()
        rid = self._race(conn, "2026-06-27T22:00:00Z")
        _add_open_flight(conn, 100, icao_to_coords("EDWF"), "2026-06-27T21:50:00Z")  # Nachzügler
        update_bummel_reveals(conn, "2026-06-27T22:30:00Z")
        assert get_bummel_race(conn, rid)["revealed_at"] is None

    def test_reveal_is_latching(self):
        conn = _make_conn()
        rid = self._race(conn, "2026-06-27T22:00:00Z")
        update_bummel_reveals(conn, "2026-06-27T22:30:00Z")
        first = get_bummel_race(conn, rid)["revealed_at"]
        # Späterer Lauf darf den Zeitstempel nicht überschreiben
        update_bummel_reveals(conn, "2026-06-27T23:00:00Z")
        assert get_bummel_race(conn, rid)["revealed_at"] == first

    def test_suppressed_race_is_not_auto_revealed(self):
        # „Verbergen" eines abgelaufenen Rennens muss halten: der Auto-Reveal-Job darf
        # ein als verborgen markiertes Rennen NICHT wieder enthüllen.
        conn = _make_conn()
        rid = self._race(conn, "2026-06-27T22:00:00Z")
        set_bummel_reveal_suppressed(conn, rid, True)
        conn.commit()
        update_bummel_reveals(conn, "2026-06-27T22:30:00Z")  # dtend längst vorbei
        assert get_bummel_race(conn, rid)["revealed_at"] is None

    def test_unsuppress_allows_auto_reveal_again(self):
        conn = _make_conn()
        rid = self._race(conn, "2026-06-27T22:00:00Z")
        set_bummel_reveal_suppressed(conn, rid, True)
        set_bummel_reveal_suppressed(conn, rid, False)  # wieder freigegeben
        conn.commit()
        update_bummel_reveals(conn, "2026-06-27T22:30:00Z")
        assert get_bummel_race(conn, rid)["revealed_at"] == "2026-06-27T22:30:00Z"


class TestStartDetection:
    def test_open_starters_moved_flag(self):
        conn = _make_conn()
        _add_open_flight(conn, 100, icao_to_coords("EDWF"), "2026-06-27T19:00:00Z", gs=120)  # bewegt
        _add_open_flight(conn, 200, icao_to_coords("EDWF"), "2026-06-27T19:00:00Z", gs=0)    # steht
        _add_open_flight(conn, 300, icao_to_coords("EDDH"), "2026-06-27T19:00:00Z", dep_fp="EDDH", gs=120)  # nicht Strecke
        starters = bummel_open_starters(conn, ROUTE, 10)
        by_cid = {s["cid"]: s for s in starters}
        assert by_cid[100]["moved"] is True
        assert by_cid[200]["moved"] is False
        assert 300 not in by_cid  # ausserhalb der Strecke

    def test_update_starts_latches_and_returns_callsign(self):
        conn = _make_conn()
        upsert_calendar_bummel_race(conn, {
            "uid": "s1", "summary": "Bummel", "route": "EDWF,EDWG,EDWR",
            "dtstart": "2026-06-27T18:00:00Z", "dtend": "2026-06-27T22:00:00Z",
        })
        rid = list_bummel_races(conn)[0]["id"]
        _add_open_flight(conn, 49, icao_to_coords("EDWF"), "2026-06-27T19:00:00Z", gs=120)
        started = update_bummel_starts(conn, "2026-06-27T19:05:00Z")
        assert started == [(rid, "FRS49")]
        assert get_bummel_race(conn, rid)["started_at"] == "2026-06-27T19:05:00Z"
        # Latch: zweiter Lauf meldet nichts mehr
        assert update_bummel_starts(conn, "2026-06-27T19:10:00Z") == []

    def test_no_start_when_nobody_moved(self):
        conn = _make_conn()
        upsert_calendar_bummel_race(conn, {
            "uid": "s2", "summary": "Bummel", "route": "EDWF,EDWG,EDWR",
            "dtstart": "2026-06-27T18:00:00Z", "dtend": "2026-06-27T22:00:00Z",
        })
        _add_open_flight(conn, 49, icao_to_coords("EDWF"), "2026-06-27T19:00:00Z", gs=0)  # steht nur
        assert update_bummel_starts(conn, "2026-06-27T19:05:00Z") == []
