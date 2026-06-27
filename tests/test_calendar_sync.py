"""Tests für die ICAO-/Bummel-Erkennung im Kalender-Parser (app/calendar_sync.py).

parse_route extrahiert alle ICAO-Codes (Reihenfolge erhaltend, dedupliziert) aus LOCATION,
dann SUMMARY → CSV-Strecke, und erkennt einen FriesenFliegerBummel (Stichwort 'bummel' im
SUMMARY UND >= 2 Flugplätze).
"""
from __future__ import annotations

from app.calendar_sync import parse_route


class TestRouteExtraction:
    def test_collects_all_icaos_from_location_in_order(self):
        route, _ = parse_route("EDWF EDWG EDWR", "FriesenFliegerBummel")
        assert route == "EDWF,EDWG,EDWR"

    def test_deduplicates_preserving_order(self):
        route, _ = parse_route("EDWF, EDWF, EDWG", "Bummel")
        assert route == "EDWF,EDWG"

    def test_preserves_given_order(self):
        route, _ = parse_route("EDWR EDWF", "Bummel")
        assert route == "EDWR,EDWF"

    def test_falls_back_to_summary_when_location_empty(self):
        route, _ = parse_route("", "Bummel EDWF nach EDWG")
        assert route == "EDWF,EDWG"

    def test_single_icao_normal_event(self):
        route, _ = parse_route("EDDH", "Stammtisch Hamburg")
        assert route == "EDDH"

    def test_no_icao(self):
        route, is_bummel = parse_route("", "Online-Briefing")
        assert route == ""
        assert is_bummel is False


class TestBummelDetection:
    def test_bummel_keyword_plus_two_icaos(self):
        _, is_bummel = parse_route("EDWF EDWG", "FriesenFliegerBummel über die Inseln")
        assert is_bummel is True

    def test_bummel_case_insensitive(self):
        _, is_bummel = parse_route("EDWF EDWG", "großer BUMMEL")
        assert is_bummel is True

    def test_bummel_keyword_but_only_one_icao_is_not_bummel(self):
        _, is_bummel = parse_route("EDWF", "FriesenFliegerBummel")
        assert is_bummel is False

    def test_two_icaos_without_keyword_is_not_bummel(self):
        _, is_bummel = parse_route("EDWF EDWG", "Gruppenflug Nordsee")
        assert is_bummel is False


class TestPlausibility:
    def test_implausibly_far_apart_route_is_not_bummel(self):
        # EDDF (Frankfurt) und KJFK (New York) sind ~3300 nm auseinander → kein Bummel.
        _, is_bummel = parse_route("EDDF KJFK", "FriesenFliegerBummel")
        assert is_bummel is False

    def test_plausible_short_route_stays_bummel(self):
        # EDDH (Hamburg) und EDDB (Berlin) sind ~130 nm auseinander → plausibel.
        _, is_bummel = parse_route("EDDH EDDB", "FriesenFliegerBummel")
        assert is_bummel is True

    def test_route_csv_unchanged_by_plausibility(self):
        route, _ = parse_route("EDDF KJFK", "FriesenFliegerBummel")
        assert route == "EDDF,KJFK"


class TestDescription:
    def test_keyword_in_description_activates_bummel(self):
        route, is_bummel = parse_route(
            "", "Gruppenflug", "Diesmal als FriesenFliegerBummel: EDWF EDWG EDWR"
        )
        assert is_bummel is True
        assert route == "EDWF,EDWG,EDWR"

    def test_icaos_collected_from_all_three_in_order(self):
        route, _ = parse_route("EDWF", "Bummel EDWG", "Weiter nach EDWR")
        assert route == "EDWF,EDWG,EDWR"

    def test_keyword_in_description_but_one_icao_is_not_bummel(self):
        _, is_bummel = parse_route("EDWF", "Treffen", "kleiner Bummel zum Kaffee")
        assert is_bummel is False


class TestDbRoundtrip:
    def test_route_and_is_bummel_persist(self):
        import sqlite3

        from app.database import (
            get_calendar_events,
            get_connection,
            init_db,
            upsert_calendar_events,
        )

        init_db(":memory:")
        conn: sqlite3.Connection = get_connection(":memory:")
        from app.database import _DDL
        conn.executescript(_DDL)
        conn.commit()

        # dtstart in der Vergangenheit, damit get_calendar_events (dtstart <= now) es liefert
        upsert_calendar_events(conn, [{
            "uid": "x_20200101T100000Z",
            "summary": "FriesenFliegerBummel",
            "dtstart": "2020-01-01T10:00:00Z",
            "dtend": "2020-01-01T18:00:00Z",
            "location": "EDWF",
            "route": "EDWF,EDWG,EDWR",
            "is_bummel": 1,
        }])
        events = get_calendar_events(conn, days_back=365 * 30)
        assert len(events) == 1
        assert events[0]["route"] == "EDWF,EDWG,EDWR"
        assert events[0]["is_bummel"] == 1
