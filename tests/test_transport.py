"""Tests für FriesenKutter — Transportflug-Events, Fracht-Manifest, Zuladungs-Tabelle.

Kern der Wertung (compute_transport_progress): Fracht zählt nur in eine Richtung (Ankunft am
``destination``); Rückflüge sind leer, erscheinen aber im Feed. Das Fracht-Manifest füllt sich
sequenziell nach Abflugzeit; jeder beladene Flug trägt die Frachtart, in die sein Anteil
überwiegend floss. Alle Tests mit In-Memory-DB (:memory:).
"""
from __future__ import annotations

import sqlite3

from app.calendar_sync import parse_route
from app.database import (
    compute_transport_progress,
    create_transport_event,
    get_connection,
    get_payload_map,
    get_transport_event,
    init_db,
    set_transport_cargo,
    upsert_payload,
)

START = "2026-07-01T09:00:00Z"
END = "2026-07-01T23:00:00Z"


def _make_conn() -> sqlite3.Connection:
    init_db(":memory:")
    conn = get_connection(":memory:")
    from app.database import _DDL
    conn.executescript(_DDL)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_session "
        "ON flights(cid, logon_time) WHERE superseded_by IS NULL"
    )
    conn.commit()
    return conn


def _add_flight(conn, cid, dep, arr, aircraft, logon, *, duration_min=30, callsign=None):
    callsign = callsign or f"FRS{cid:02d}"
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, f"Pilot{cid}", START),
    )
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
        "logon_time, logoff_time, duration_min, distance_nm) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, callsign, aircraft, dep, arr, logon, "2026-07-01T22:00:00Z", duration_min, 20.0),
    )
    conn.commit()


def _event(conn, *, route="EDWG,EDXH", destination="EDXH", cargo=None):
    eid = create_transport_event(
        conn, name="Helgoland-Nachschub", route=route, dtstart=START, dtend=END,
        destination=destination, cargo=cargo,
    )
    return get_transport_event(conn, eid)


def _feed_by_callsign(progress, callsign):
    return next((f for f in progress["flights"] if f["callsign"] == callsign), None)


# --- Kalender-Stichwort ----------------------------------------------------

class TestCalendarKeyword:
    def test_friesenkutter_keyword_enables_transport(self):
        route, is_bummel, is_transport = parse_route("EDWG", "FriesenKutter Helgoland EDXH", "")
        assert is_transport is True
        assert is_bummel is False
        assert route == "EDWG,EDXH"

    def test_no_keyword_no_transport(self):
        _, _, is_transport = parse_route("EDWG", "Ausflug nach EDXH", "")
        assert is_transport is False

    def test_keyword_needs_two_airports(self):
        _, _, is_transport = parse_route("", "FriesenKutter EDXH", "")
        assert is_transport is False


# --- Zuladungs-Tabelle -----------------------------------------------------

class TestPayloads:
    def test_payload_derived_from_components(self):
        conn = _make_conn()
        upsert_payload(conn, "be58", mtow_kg=2500, empty_kg=1700, fuel_kg=300, crew_kg=0)
        conn.commit()
        assert get_payload_map(conn)["BE58"] == 500  # 2500-1700-300-0, Typcode normalisiert

    def test_default_crew_is_subtracted(self):
        conn = _make_conn()
        # Ohne crew_kg → Standard-Pilot (85 kg) zählt nicht als Fracht.
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=681, fuel_kg=61)
        conn.commit()
        assert get_payload_map(conn)["C172"] == 330  # 1157-681-61-85

    def test_direct_payload_overrides_components(self):
        conn = _make_conn()
        upsert_payload(conn, "BE58", payload_kg=999, mtow_kg=2500, empty_kg=1700, fuel_kg=300)
        conn.commit()
        assert get_payload_map(conn)["BE58"] == 999


# --- Wertung / Manifest ----------------------------------------------------

class TestProgress:
    def _seed(self, conn):
        upsert_payload(conn, "C172", payload_kg=250)
        upsert_payload(conn, "C208", payload_kg=550)
        conn.commit()

    def test_oneway_return_is_empty(self):
        conn = _make_conn()
        self._seed(conn)
        _add_flight(conn, 12, "EDWG", "EDXH", "C172", "2026-07-01T10:00:00Z")  # hin, beladen
        _add_flight(conn, 12, "EDXH", "EDWG", "C172", "2026-07-01T11:00:00Z")  # zurück, leer
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)

        assert p["flight_count"] == 2 and p["loaded_count"] == 1
        assert p["total_kg"] == 250
        hin = _feed_by_callsign(p, "FRS12")  # neueste oben → das ist der Rückflug
        # es gibt zwei Einträge mit derselben Callsign; explizit über dep prüfen
        loaded = next(f for f in p["flights"] if f["dep"] == "EDWG")
        empty = next(f for f in p["flights"] if f["dep"] == "EDXH")
        assert loaded["loaded"] is True and loaded["tonnage_kg"] == 250
        assert empty["loaded"] is False and empty["tonnage_kg"] == 0.0
        assert empty["cargo_name"] is None

    def test_feed_newest_first(self):
        conn = _make_conn()
        self._seed(conn)
        _add_flight(conn, 12, "EDWG", "EDXH", "C172", "2026-07-01T10:00:00Z")
        _add_flight(conn, 7, "EDWG", "EDXH", "C208", "2026-07-01T10:30:00Z")
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        assert [f["dep_time"] for f in p["flights"]] == [
            "2026-07-01T10:30:00Z", "2026-07-01T10:00:00Z",
        ]

    def test_offroute_flight_excluded(self):
        conn = _make_conn()
        self._seed(conn)
        _add_flight(conn, 12, "EDWG", "EDDH", "C172", "2026-07-01T10:00:00Z")  # Ziel nicht auf Strecke
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        assert p["flight_count"] == 0

    def test_unmapped_type_uses_default_and_is_flagged(self):
        conn = _make_conn()
        self._seed(conn)
        _add_flight(conn, 3, "EDWG", "EDXH", "PA28", "2026-07-01T10:00:00Z")  # kein Payload gepflegt
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        assert p["total_kg"] == 150.0  # globaler Default
        assert "PA28" in p["unmapped_types"]

    def test_manifest_sequential_fill(self):
        conn = _make_conn()
        self._seed(conn)
        # beladene Flüge: 250 + 550 = 800 (füllt Fischbrötchen), dann 150 → Tee
        _add_flight(conn, 12, "EDWG", "EDXH", "C172", "2026-07-01T10:00:00Z")   # 250
        _add_flight(conn, 7, "EDWG", "EDXH", "C208", "2026-07-01T10:30:00Z")    # 550
        _add_flight(conn, 12, "EDXH", "EDWG", "C172", "2026-07-01T10:45:00Z")   # leer (zurück)
        upsert_payload(conn, "PA28", payload_kg=150)
        conn.commit()
        _add_flight(conn, 3, "EDWG", "EDXH", "PA28", "2026-07-01T11:00:00Z")    # 150 → Tee
        ev = _event(conn, cargo=[
            {"name": "Fischbrötchen", "target_kg": 800},
            {"name": "Friesen Tee", "target_kg": 500},
        ])
        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] == 950
        assert p["target_kg"] == 1300
        fisch = next(c for c in p["cargo"] if c["name"] == "Fischbrötchen")
        tee = next(c for c in p["cargo"] if c["name"] == "Friesen Tee")
        assert fisch["delivered_kg"] == 800 and fisch["pct"] == 100.0
        assert tee["delivered_kg"] == 150 and tee["pct"] == 30.0
        # Frachtart je beladenem Flug
        by_dep_time = {f["dep_time"]: f for f in p["flights"]}
        assert by_dep_time["2026-07-01T10:00:00Z"]["cargo_name"] == "Fischbrötchen"
        assert by_dep_time["2026-07-01T10:30:00Z"]["cargo_name"] == "Fischbrötchen"
        assert by_dep_time["2026-07-01T11:00:00Z"]["cargo_name"] == "Friesen Tee"

    def test_no_manifest_is_plain_counter(self):
        conn = _make_conn()
        self._seed(conn)
        _add_flight(conn, 12, "EDWG", "EDXH", "C172", "2026-07-01T10:00:00Z")
        ev = _event(conn, cargo=None)
        p = compute_transport_progress(conn, ev, END)
        assert p["cargo"] == []
        assert p["target_kg"] is None and p["progress_pct"] is None
        assert p["total_kg"] == 250
