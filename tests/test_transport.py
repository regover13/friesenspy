"""Tests für FriesenKutter — Transportflug-Events, Fracht-Manifest, Zuladungs-Tabelle.

Kern der Wertung (compute_transport_progress): Fracht zählt nur in eine Richtung (Ankunft am
``destination``); Rückflüge sind leer, erscheinen aber im Feed. Das Fracht-Manifest füllt sich
sequenziell nach Abflugzeit; jeder beladene Flug trägt die Frachtart, in die sein Anteil
überwiegend floss. Alle Tests mit In-Memory-DB (:memory:).
"""
from __future__ import annotations

import sqlite3

from app.calendar_sync import parse_route
from app.llm import _build_result
from app.database import (
    compute_transport_progress,
    create_transport_event,
    get_connection,
    get_payload_map,
    get_transport_event,
    init_db,
    set_transport_cargo,
    upsert_payload,
    list_cargo_catalog,
    upsert_cargo_catalog,
    delete_cargo_catalog,
    seed_cargo_catalog,
    set_transport_quip,
    get_transport_quips,
    transport_quips_enabled,
    flight_quip_context,
    event_summary_context,
    set_app_setting,
    upsert_calendar_transport_event,
    get_transport_cargo,
    set_transport_live_arrival,
    get_transport_live_arrivals,
    active_transport_destinations,
    open_transport_flights,
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


def _add_open_flight(conn, cid, dep, arr, aircraft, logon, *, callsign=None):
    callsign = callsign or f"FRS{cid:02d}"
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, f"Pilot{cid}", START),
    )
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cid, callsign, aircraft, dep, arr, logon),
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


class TestLlmResult:
    def test_build_result_subtracts_full_fuel_and_crew(self):
        # volle Tanks (122) + Standard-Pilot (85) abgezogen: 1157-681-122-85 = 269
        r = _build_result("Cessna 172", 1157, 681, 122)
        assert r["payload_kg"] == 269
        assert r["crew_kg"] == 85.0
        assert r["fuel_full_kg"] == 122

    def test_build_result_never_negative(self):
        r = _build_result("Winzling", 400, 380, 100, crew_kg=85)
        assert r["payload_kg"] == 0.0


# --- Phase 2: Co-Load-Kappung, Katalog, Kontext, Sprüche ------------------

class TestCoLoad:
    def test_per_flight_cap_spills_to_next_cargo(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        conn.commit()
        _add_flight(conn, 7, "EDWG", "EDXH", "C208", "2026-07-01T10:00:00Z")
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 300, "per_flight_max_kg": 100, "emoji": "🎞️"},
            {"name": "Friesentee", "target_kg": 500, "emoji": "🫖"},
        ])
        p = compute_transport_progress(conn, ev, END)
        film = next(c for c in p["cargo"] if c["name"] == "Filmrollen")
        tee = next(c for c in p["cargo"] if c["name"] == "Friesentee")
        assert film["delivered_kg"] == 100 and film["emoji"] == "🎞️"   # bei 100 gekappt
        assert tee["delivered_kg"] == 450                               # Rest per Co-Load
        f = p["flights"][0]
        assert f["cargo_name"] == "Friesentee"                          # dominant (450 > 100)
        assert [l["name"] for l in f["cargo_lines"]] == ["Friesentee", "Filmrollen"]


class TestCatalog:
    def test_seed_only_when_empty(self):
        conn = _make_conn()
        assert seed_cargo_catalog(conn) > 0
        n = len(list_cargo_catalog(conn))
        assert n > 0
        assert seed_cargo_catalog(conn) == 0        # nicht erneut seeden
        assert len(list_cargo_catalog(conn)) == n

    def test_crud(self):
        conn = _make_conn()
        upsert_cargo_catalog(conn, name="Testfracht", emoji="🧪", per_flight_max_kg=50)
        conn.commit()
        r = next(x for x in list_cargo_catalog(conn) if x["name"] == "Testfracht")
        assert r["emoji"] == "🧪" and r["per_flight_max_kg"] == 50
        upsert_cargo_catalog(conn, id=r["id"], name="Testfracht", emoji="🔬", per_flight_max_kg=None)
        conn.commit()
        r2 = next(x for x in list_cargo_catalog(conn) if x["id"] == r["id"])
        assert r2["emoji"] == "🔬" and r2["per_flight_max_kg"] is None
        delete_cargo_catalog(conn, r["id"])
        conn.commit()
        assert not any(x["id"] == r["id"] for x in list_cargo_catalog(conn))


class TestQuipContext:
    def test_flight_context(self):
        progress = {"flights": [
            {"cid": 12, "loaded": True, "flight_key": "12:a"},
            {"cid": 12, "loaded": True, "flight_key": "12:b"},
        ]}
        flight = {
            "cid": 12, "name": "Anna Meyer", "callsign": "FRS12", "aircraft": "C172",
            "dep": "EDDH", "arr": "EDDW", "tonnage_kg": 250, "distance_nm": 200, "block_min": 40,
            "cargo_lines": [{"name": "Krabbenbrötchen", "emoji": "🦐", "kg": 250}],
        }
        ctx = flight_quip_context(flight, progress)
        assert ctx["vorname"] == "Anna"
        assert ctx["flights_tonight"] == 2
        assert ctx["speed_kt"] == 300                # 200 / (40/60)
        assert ctx["detour_ratio"] and ctx["detour_ratio"] > 1   # 200 nm ≫ Luftlinie EDDH-EDDW
        assert "🦐 Krabbenbrötchen" in ctx["cargo"][0]

    def test_summary_context(self):
        progress = {
            "flights": [
                {"loaded": True, "name": "Anna Meyer"}, {"loaded": True, "name": "Anna Meyer"},
                {"loaded": True, "name": "Bert"}, {"loaded": False, "name": "Cara"},
            ],
            "total_kg": 1000, "loaded_count": 3,
            "cargo": [{"name": "Krabbenbrötchen", "emoji": "🦐", "delivered_kg": 600, "target_kg": 800}],
            "route": ["EDWG", "EDXH"], "destination": "EDXH",
        }
        ctx = event_summary_context({"name": "Test"}, progress)
        assert ctx["pilots"] == {"Anna": 2, "Bert": 1}
        assert ctx["loaded_count"] == 3


class TestCalendarCargo:
    def _cal_ev(self, **overrides):
        ev = {
            "uid": "abc123", "summary": "FriesenKutter Helgoland", "route": "EDWG,EDXH",
            "dtstart": START, "dtend": END, "cargo": [],
        }
        ev.update(overrides)
        return ev

    def test_resolves_against_catalog_on_first_sync(self):
        conn = _make_conn()
        upsert_cargo_catalog(conn, name="Krabbenbrötchen", emoji="🦐", per_flight_max_kg=None)
        upsert_cargo_catalog(conn, name="Filmrollen", emoji="🎞️", per_flight_max_kg=100)
        conn.commit()
        ev = self._cal_ev(cargo=[
            {"name": "Krabbenbrötchen", "target_kg": 1000.0},
            {"name": "Filmrollen", "target_kg": 300.0},
        ])
        upsert_calendar_transport_event(conn, ev)
        conn.commit()
        eid = conn.execute("SELECT id FROM transport_events WHERE calendar_uid='abc123'").fetchone()[0]
        cargo = get_transport_cargo(conn, eid)
        krabben = next(c for c in cargo if c["name"] == "Krabbenbrötchen")
        film = next(c for c in cargo if c["name"] == "Filmrollen")
        assert krabben["emoji"] == "🦐" and krabben["per_flight_max_kg"] is None
        assert film["emoji"] == "🎞️" and film["per_flight_max_kg"] == 100

    def test_unknown_name_kept_as_freetext(self):
        conn = _make_conn()
        upsert_calendar_transport_event(conn, self._cal_ev(cargo=[{"name": "Mysteriöses Gut", "target_kg": 42.0}]))
        conn.commit()
        eid = conn.execute("SELECT id FROM transport_events WHERE calendar_uid='abc123'").fetchone()[0]
        cargo = get_transport_cargo(conn, eid)
        assert cargo[0]["name"] == "Mysteriöses Gut" and cargo[0]["emoji"] is None

    def test_resync_does_not_overwrite_existing_manifest(self):
        conn = _make_conn()
        upsert_calendar_transport_event(conn, self._cal_ev(cargo=[{"name": "Krabbenbrötchen", "target_kg": 1000.0}]))
        conn.commit()
        eid = conn.execute("SELECT id FROM transport_events WHERE calendar_uid='abc123'").fetchone()[0]
        set_transport_cargo(conn, eid, [{"name": "Vom Admin gepflegt", "target_kg": 5.0}])
        conn.commit()
        # Erneuter Sync mit (ggf. anderer) Fracht-Zeile aus dem Kalender darf das nicht überschreiben.
        upsert_calendar_transport_event(conn, self._cal_ev(cargo=[{"name": "Anderes Gut", "target_kg": 77.0}]))
        conn.commit()
        cargo = get_transport_cargo(conn, eid)
        assert [c["name"] for c in cargo] == ["Vom Admin gepflegt"]

    def test_no_cargo_marker_leaves_manifest_empty(self):
        conn = _make_conn()
        upsert_calendar_transport_event(conn, self._cal_ev(cargo=[]))
        conn.commit()
        eid = conn.execute("SELECT id FROM transport_events WHERE calendar_uid='abc123'").fetchone()[0]
        assert get_transport_cargo(conn, eid) == []


class TestQuipCache:
    def test_toggle_and_cache(self):
        conn = _make_conn()
        assert transport_quips_enabled(conn) is False
        set_app_setting(conn, "transport_quips_enabled", "1")
        conn.commit()
        assert transport_quips_enabled(conn) is True
        set_transport_quip(conn, 5, "12:x", "Moin, dat lööpt!")
        conn.commit()
        assert get_transport_quips(conn, 5) == {"12:x": "Moin, dat lööpt!"}


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


class TestLiveArrivalLatch:
    def test_set_and_get_roundtrip(self):
        conn = _make_conn()
        ev = _event(conn)
        set_transport_live_arrival(conn, 42, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}

    def test_insert_or_ignore_is_idempotent(self):
        conn = _make_conn()
        ev = _event(conn)
        set_transport_live_arrival(conn, 42, START, ev["id"], "2026-07-01T10:00:00Z")
        set_transport_live_arrival(conn, 42, START, ev["id"], "2026-07-01T11:00:00Z")
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}

    def test_get_scoped_to_event(self):
        conn = _make_conn()
        ev1 = _event(conn)
        ev2 = create_transport_event(
            conn, name="Anderes Event", route="EDWF,EDWR", dtstart=START, dtend=END,
        )
        set_transport_live_arrival(conn, 42, START, ev1["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        assert get_transport_live_arrivals(conn, ev2) == set()

    def test_active_transport_destinations_filters_by_time_window(self):
        conn = _make_conn()
        ev = _event(conn)  # dtstart=START, dtend=END (siehe _event-Helfer)
        active = active_transport_destinations(conn, "2026-07-01T12:00:00Z")  # innerhalb [START,END]
        assert active == [{"id": ev["id"], "destination": "EDXH"}]
        assert active_transport_destinations(conn, "2026-06-01T00:00:00Z") == []  # vor dtstart
        assert active_transport_destinations(conn, "2026-08-01T00:00:00Z") == []  # nach dtend

    def test_open_transport_flights_excludes_closed_and_wrong_prefix(self):
        conn = _make_conn()
        _add_flight(conn, 1, "EDWG", "EDXH", "C172", START)  # geschlossen (logoff gesetzt)
        _add_open_flight(conn, 2, "EDWG", "", "C208", START)  # offen, FRS
        conn.execute(
            "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (3, 'Pilot3', ?)", (START,),
        )
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, logon_time) "
            "VALUES (3, 'DLH123', 'A320', 'EDDF', ?)", (START,),
        )  # offen, aber KEIN FRS-Callsign
        conn.commit()
        open_flights = open_transport_flights(conn)
        assert {f["cid"] for f in open_flights} == {2}
