"""Tests für die ICAO-/Bummel-Erkennung im Kalender-Parser (app/calendar_sync.py).

parse_route extrahiert alle ICAO-Codes (Reihenfolge erhaltend, dedupliziert) aus LOCATION,
dann SUMMARY → CSV-Strecke, und erkennt einen FriesenFliegerBummel (Stichwort 'bummel' im
SUMMARY UND >= 2 Flugplätze).
"""
from __future__ import annotations

from app.calendar_sync import parse_route, parse_cargo_lines


class TestRouteExtraction:
    def test_collects_all_icaos_from_location_in_order(self):
        route, _, _ = parse_route("EDWF EDWG EDWR", "FriesenFliegerBummel")
        assert route == "EDWF,EDWG,EDWR"

    def test_deduplicates_preserving_order(self):
        route, _, _ = parse_route("EDWF, EDWF, EDWG", "Bummel")
        assert route == "EDWF,EDWG"

    def test_preserves_given_order(self):
        route, _, _ = parse_route("EDWR EDWF", "Bummel")
        assert route == "EDWR,EDWF"

    def test_falls_back_to_summary_when_location_empty(self):
        route, _, _ = parse_route("", "Bummel EDWF nach EDWG")
        assert route == "EDWF,EDWG"

    def test_single_icao_normal_event(self):
        route, _, _ = parse_route("EDDH", "Stammtisch Hamburg")
        assert route == "EDDH"

    def test_no_icao(self):
        route, is_bummel, _ = parse_route("", "Online-Briefing")
        assert route == ""
        assert is_bummel is False

    def test_literal_icao_label_word_excluded_from_route(self):
        """Live-Fund: mehrere 'Montagsflüge'-Termine zeigten 'ICAO,EDVE,EDBH' statt
        'EDVE,EDBH' -- der Kalendertext nutzt 'ICAO' als Label vor den echten Codes, das
        Wort selbst matcht aber zufällig auch die 4-Großbuchstaben-Regel."""
        route, _, _ = parse_route("ICAO: EDVE, EDBH", "Montagsflüge in Deutschland")
        assert route == "EDVE,EDBH"

    def test_icao_stopword_is_case_sensitive_lowercase_not_a_match_anyway(self):
        # "icao" (klein) matcht die Regex ohnehin nicht (nur Großbuchstaben) -- Kontrollfall.
        route, _, _ = parse_route("icao EDVE", "Montagsflüge in Deutschland")
        assert route == "EDVE"


class TestBummelDetection:
    def test_bummel_keyword_plus_two_icaos(self):
        _, is_bummel, _ = parse_route("EDWF EDWG", "FriesenFliegerBummel über die Inseln")
        assert is_bummel is True

    def test_bummel_case_insensitive(self):
        _, is_bummel, _ = parse_route("EDWF EDWG", "großer BUMMEL")
        assert is_bummel is True

    def test_bummel_keyword_but_only_one_icao_is_not_bummel(self):
        _, is_bummel, _ = parse_route("EDWF", "FriesenFliegerBummel")
        assert is_bummel is False

    def test_two_icaos_without_keyword_is_not_bummel(self):
        _, is_bummel, _ = parse_route("EDWF EDWG", "Gruppenflug Nordsee")
        assert is_bummel is False


class TestPlausibility:
    def test_implausibly_far_apart_route_is_not_bummel(self):
        # EDDF (Frankfurt) und KJFK (New York) sind ~3300 nm auseinander → kein Bummel.
        _, is_bummel, _ = parse_route("EDDF KJFK", "FriesenFliegerBummel")
        assert is_bummel is False

    def test_plausible_short_route_stays_bummel(self):
        # EDDH (Hamburg) und EDDB (Berlin) sind ~130 nm auseinander → plausibel.
        _, is_bummel, _ = parse_route("EDDH EDDB", "FriesenFliegerBummel")
        assert is_bummel is True

    def test_route_csv_unchanged_by_plausibility(self):
        route, _, _ = parse_route("EDDF KJFK", "FriesenFliegerBummel")
        assert route == "EDDF,KJFK"


class TestDescription:
    def test_keyword_in_description_activates_bummel(self):
        route, is_bummel, _ = parse_route(
            "", "Gruppenflug", "Diesmal als FriesenFliegerBummel: EDWF EDWG EDWR"
        )
        assert is_bummel is True
        assert route == "EDWF,EDWG,EDWR"

    def test_icaos_collected_from_all_three_in_order(self):
        route, _, _ = parse_route("EDWF", "Bummel EDWG", "Weiter nach EDWR")
        assert route == "EDWF,EDWG,EDWR"

    def test_keyword_in_description_but_one_icao_is_not_bummel(self):
        _, is_bummel, _ = parse_route("EDWF", "Treffen", "kleiner Bummel zum Kaffee")
        assert is_bummel is False


class TestCargoLines:
    def test_parses_comma_separated_items(self):
        lines = parse_cargo_lines("Fracht EDWG: 1000 Krabbenbrötchen, 500 Friesentee")
        assert lines == [
            {"name": "Krabbenbrötchen", "target_kg": 1000.0, "departure": "EDWG"},
            {"name": "Friesentee", "target_kg": 500.0, "departure": "EDWG"},
        ]

    def test_kg_suffix_and_decimal_comma(self):
        lines = parse_cargo_lines("Fracht EDWG: 250,5 kg Filmrollen")
        assert lines == [{"name": "Filmrollen", "target_kg": 250.5, "departure": "EDWG"}]

    def test_no_marker_returns_empty(self):
        assert parse_cargo_lines("Diesmal als FriesenKutter: EDWG EDXH") == []

    def test_only_first_line_after_marker(self):
        lines = parse_cargo_lines("Fracht EDWG: 1000 Krabbenbrötchen\nWeitere Infos hier")
        assert lines == [{"name": "Krabbenbrötchen", "target_kg": 1000.0, "departure": "EDWG"}]

    def test_empty_description(self):
        assert parse_cargo_lines("") == []

    def test_departure_marker_binds_cargo(self):
        lines = parse_cargo_lines("Fracht EDDW: 500 Äpfel, 200 Nüsse")
        assert lines == [
            {"name": "Äpfel", "target_kg": 500.0, "departure": "EDDW"},
            {"name": "Nüsse", "target_kg": 200.0, "departure": "EDDW"},
        ]

    def test_multiple_departure_markers(self):
        lines = parse_cargo_lines("Fracht EDDW: 500 Äpfel\nFracht EDWG: 300 Birnen")
        assert lines == [
            {"name": "Äpfel", "target_kg": 500.0, "departure": "EDDW"},
            {"name": "Birnen", "target_kg": 300.0, "departure": "EDWG"},
        ]

    def test_lowercase_departure_marker_uppercased(self):
        assert parse_cargo_lines("Fracht edwg: 300 Birnen") == [
            {"name": "Birnen", "target_kg": 300.0, "departure": "EDWG"},
        ]

    # --- Entscheidung 6 (Task 11): genau EIN Startplatz je Zeile, sonst abgewiesen ---
    def test_fracht_marker_mit_mehreren_icao_wird_abgewiesen(self):
        """Statt still zu teilen: der Sync verwirft die Zeile (Entscheidung 6)."""
        assert parse_cargo_lines("Fracht EDWG, EDWZ: 500 Fisch") == []

    def test_fracht_marker_ohne_icao_wird_abgewiesen(self):
        assert parse_cargo_lines("Fracht: 500 Fisch") == []

    def test_fracht_marker_mit_einem_icao_bleibt(self):
        assert parse_cargo_lines("Fracht EDWG: 500 Fisch") == [
            {"name": "Fisch", "target_kg": 500.0, "departure": "EDWG"},
        ]

    def test_near_cargo_marker_icao_added_to_route(self):
        # #84: ein naher Marker-Startplatz kommt in die Route, das Ziel bleibt am Ende.
        route, _, is_transport = parse_route(
            "EDWG, EDXH", "FriesenKutter", "Fracht EDWL: 300 Birnen"  # EDWL nah an EDWG
        )
        assert set(route.split(",")) == {"EDWG", "EDWL", "EDXH"}
        assert route.split(",")[-1] == "EDXH"   # Ziel am Ende (für _default_destination)
        assert is_transport is True

    def test_far_cargo_marker_icao_rejected_but_event_survives(self):
        # #84: ein gültiger, aber FERNER Marker-ICAO wird aus der Route verworfen (Distanzfilter) —
        # kippt aber das Event NICHT (Plausibilität nur aus location/summary).
        route, _, is_transport = parse_route(
            "EDWG, EDXH", "FriesenKutter Nachschub", "Fracht KJFK: 300 Bier"  # New York = fern
        )
        assert "KJFK" not in route.split(",")
        assert route == "EDWG,EDXH"
        assert is_transport is True


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


class TestDeleteStaleCalendarEvents:
    def _conn(self):
        import sqlite3

        from app.database import _DDL, get_connection, init_db

        init_db(":memory:")
        conn: sqlite3.Connection = get_connection(":memory:")
        conn.executescript(_DDL)
        conn.commit()
        return conn

    def _seed(self, conn, uid: str, dtstart: str):
        from app.database import upsert_calendar_events

        upsert_calendar_events(conn, [{
            "uid": uid,
            "summary": "Wunschradio",
            "dtstart": dtstart,
            "dtend": dtstart,
            "location": "",
            "route": "",
            "is_bummel": 0,
        }])

    def test_uid_missing_from_active_set_is_removed(self):
        from datetime import datetime, timedelta, timezone

        from app.database import delete_stale_calendar_events, get_calendar_events

        conn = self._conn()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed(conn, "stale_uid", recent)
        conn.commit()

        deleted = delete_stale_calendar_events(conn, active_uids=["some_other_uid"])
        conn.commit()

        assert deleted == 1
        assert get_calendar_events(conn, days_back=365 * 30) == []

    def test_uid_still_in_active_set_is_kept(self):
        from datetime import datetime, timedelta, timezone

        from app.database import delete_stale_calendar_events, get_calendar_events

        conn = self._conn()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed(conn, "kept_uid", recent)
        conn.commit()

        deleted = delete_stale_calendar_events(conn, active_uids=["kept_uid"])
        conn.commit()

        assert deleted == 0
        assert len(get_calendar_events(conn, days_back=365 * 30)) == 1

    def test_event_outside_sync_window_is_not_touched(self):
        from datetime import datetime, timedelta, timezone

        from app.database import delete_stale_calendar_events

        conn = self._conn()
        far_past = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed(conn, "old_uid", far_past)
        conn.commit()

        deleted = delete_stale_calendar_events(conn, active_uids=["some_other_uid"])

        assert deleted == 0

    def test_empty_active_uids_is_a_noop(self):
        from datetime import datetime, timedelta, timezone

        from app.database import delete_stale_calendar_events, get_calendar_events

        conn = self._conn()
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed(conn, "any_uid", recent)
        conn.commit()

        deleted = delete_stale_calendar_events(conn, active_uids=[])

        assert deleted == 0
        assert len(get_calendar_events(conn, days_back=365 * 30)) == 1
