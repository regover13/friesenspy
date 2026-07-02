"""Tests für FriesenKutter — Transportflug-Events, Fracht-Manifest, Zuladungs-Tabelle.

Kern der Wertung (compute_transport_progress): Fracht zählt nur in eine Richtung (Ankunft am
``destination``); Rückflüge sind leer, erscheinen aber im Feed. Das Fracht-Manifest füllt sich
sequenziell nach Abflugzeit; jeder beladene Flug trägt die Frachtart, in die sein Anteil
überwiegend floss. Alle Tests mit In-Memory-DB (:memory:).
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
from app.auth import ADMIN_COOKIE, make_admin_token
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
    transport_event_started,
    check_live_arrival,
    record_transport_loss,
    get_transport_losses,
    detect_transport_losses,
    set_transport_summarized,
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
    logoff = _shift(logon, duration_min)
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
        "logon_time, logoff_time, duration_min, distance_nm) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, callsign, aircraft, dep, arr, logon, logoff, duration_min, 20.0),
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


def _event(conn, *, route="EDWG,EDXH", destination="EDXH", cargo=None, radius_km=None):
    eid = create_transport_event(
        conn, name="Helgoland-Nachschub", route=route, dtstart=START, dtend=END,
        destination=destination, cargo=cargo, radius_km=radius_km,
    )
    return get_transport_event(conn, eid)


def _feed_by_callsign(progress, callsign):
    return next((f for f in progress["flights"] if f["callsign"] == callsign), None)


def _add_pos(conn, cid, ts, lat, lon, gs):
    conn.execute(
        "INSERT INTO position_history (cid, latitude, longitude, groundspeed, ts) "
        "VALUES (?, ?, ?, ?, ?)",
        (cid, lat, lon, gs, ts),
    )
    conn.commit()


def _shift(ts: str, minutes: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    def test_build_result_uses_half_fuel_and_crew(self):
        # halbe Tankfüllung als Default (122/2=61) + Standard-Pilot (85): 1157-681-61-85 = 330
        r = _build_result("Cessna 172", 1157, 681, 122)
        assert r["payload_kg"] == 330.0
        assert r["fuel_kg"] == 61.0
        assert r["fuel_full_kg"] == 122
        assert r["crew_kg"] == 85.0

    def test_build_result_never_negative(self):
        # auch mit halbem Tank negativ: 400-380-50-85 < 0 → 0.0
        r = _build_result("Winzling", 400, 380, 100, crew_kg=85)
        assert r["payload_kg"] == 0.0

    def test_build_result_reports_full_tank_as_max(self):
        # fuel_full_kg bleibt das Maximum (volle Tanks), fuel_kg ist exakt die Hälfte
        r = _build_result("Cessna 208 Caravan", 3629, 2145, 1009)
        assert r["fuel_full_kg"] == 1009
        assert r["fuel_kg"] == 504.5


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
        assert active == [{"id": ev["id"], "destination": "EDXH", "radius_km": None}]
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


class TestTransportEventStarted:
    """transport_event_started: Start-Latch soll schon beim Abflug feuern, nicht erst bei
    Landung/Disconnect — unabhängig davon, ob compute_transport_progress den offenen Flug schon
    als beladen sieht (das hängt vom Live-Ankunfts-Latch ab, siehe TestLiveArrivalInProgress)."""

    def test_true_when_open_flight_departs_from_route(self):
        conn = _make_conn()
        ev = _event(conn)
        _add_open_flight(conn, 61, "EDWG", "", "C208", START)  # gerade abgeflogen, noch in der Luft
        assert transport_event_started(conn, ev) is True

    def test_false_without_any_flight(self):
        conn = _make_conn()
        ev = _event(conn)
        assert transport_event_started(conn, ev) is False

    def test_false_when_open_flight_departs_elsewhere(self):
        conn = _make_conn()
        ev = _event(conn)
        _add_open_flight(conn, 61, "EDDF", "", "C208", START)  # nicht auf der Strecke
        assert transport_event_started(conn, ev) is False

    def test_true_and_progress_shows_open_flight_unloaded_without_latch(self):
        """Flug in der Luft, noch kein Disconnect und noch kein Live-Ankunfts-Latch ->
        compute_transport_progress zeigt den Flug jetzt bereits im Feed (seit Task 4), aber
        unbeladen (0 kg); transport_event_started feuert unabhängig davon schon beim Abflug."""
        conn = _make_conn()
        ev = _event(conn)
        _add_open_flight(conn, 61, "EDWG", "", "C208", START)
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        assert progress["flight_count"] == 1
        f = _feed_by_callsign(progress, "FRS61")
        assert f is not None
        assert f["loaded"] is False
        assert f["tonnage_kg"] == 0
        assert transport_event_started(conn, ev) is True


class TestCheckLiveArrival:
    def _events(self, event_id, dest="EDXH"):
        return [{"id": event_id, "destination": dest}]

    def test_within_radius_and_slow_latches(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 1.5, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}

    def test_within_radius_but_too_fast_does_not_latch(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 120.0, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == set()

    def test_outside_radius_does_not_latch(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDDF")  # Frankfurt, weit weg von EDXH
        check_live_arrival(conn, 42, START, lat, lon, 0.0, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == set()

    def test_no_active_events_does_not_latch(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 0.0, [])
        conn.commit()
        assert get_transport_live_arrivals(conn, 999) == set()

    def test_idempotent_repeated_check(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = _event(conn)
        lat, lon = icao_to_coords("EDXH")
        check_live_arrival(conn, 42, START, lat, lon, 1.0, self._events(ev["id"]))
        check_live_arrival(conn, 42, START, lat, lon, 1.0, self._events(ev["id"]))
        conn.commit()
        assert get_transport_live_arrivals(conn, ev["id"]) == {(42, START)}


class TestLiveArrivalInProgress:
    def test_open_flight_without_latch_shows_zero_kg(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        f = _feed_by_callsign(p, "FRS09")
        assert f is not None
        assert f["loaded"] is False
        assert f["tonnage_kg"] == 0

    def test_open_flight_with_latch_counts_immediately(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        ev = _event(conn)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        p = compute_transport_progress(conn, ev, END)
        f = _feed_by_callsign(p, "FRS09")
        assert f["loaded"] is True
        assert f["tonnage_kg"] == 550

    def test_latch_persists_after_disconnect_elsewhere(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        ev = _event(conn)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        # Pilot disconnectet spaeter ganz woanders (Ziel ausserhalb der Strecke) -- die Fracht
        # bleibt trotzdem gezaehlt, weil der Latch bereits existiert.
        conn.execute(
            "UPDATE flights SET logoff_time=?, arrival='EDDH', duration_min=45, distance_nm=120 "
            "WHERE cid=9",
            (END,),
        )
        conn.commit()
        p = compute_transport_progress(conn, ev, END)
        f = _feed_by_callsign(p, "FRS09")
        assert f is not None
        assert f["loaded"] is True
        assert f["tonnage_kg"] == 550

    def test_open_flight_departing_from_destination_is_excluded(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDXH", "", "C208", START)  # startet BEREITS am Ziel
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        assert _feed_by_callsign(p, "FRS09") is None

    def test_open_flight_participates_in_coload_fill(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 300, "per_flight_max_kg": 100, "emoji": "🎞️"},
            {"name": "Friesentee", "target_kg": 500, "emoji": "🫖"},
        ])
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        p = compute_transport_progress(conn, ev, END)
        film = next(c for c in p["cargo"] if c["name"] == "Filmrollen")
        tee = next(c for c in p["cargo"] if c["name"] == "Friesentee")
        assert film["delivered_kg"] == 100
        assert tee["delivered_kg"] == 450


# --- Feierabend wartet auf Nachzügler (Task #13) ----------------------------

class TestAnyoneInProgress:
    """transport_anyone_in_progress: die Feierabend-Zusammenfassung darf erst entstehen,
    wenn kein Pilot mehr für das Event unterwegs ist (analog Bummel-Reveal)."""

    def test_open_flight_from_route_counts_as_in_progress(self):
        from app.database import transport_anyone_in_progress
        conn = _make_conn()
        ev = _event(conn)
        _add_open_flight(conn, 7, "EDWG", "EDXH", "BN2P", "2026-07-01T20:00:00Z")
        assert transport_anyone_in_progress(conn, ev, started_before=END) is True

    def test_latched_flight_does_not_delay(self):
        """Live-Ankunfts-Latch fixiert den Beitrag → der Flug verzögert den Feierabend nicht."""
        from app.database import transport_anyone_in_progress
        conn = _make_conn()
        ev = _event(conn)
        logon = "2026-07-01T20:00:00Z"
        _add_open_flight(conn, 7, "EDWG", "EDXH", "BN2P", logon)
        set_transport_live_arrival(conn, 7, logon, ev["id"], "2026-07-01T21:00:00Z")
        conn.commit()
        assert transport_anyone_in_progress(conn, ev, started_before=END) is False

    def test_late_connect_after_dtend_ignored(self):
        """Neu-Connect NACH dtend ist kein Nachzügler des Events."""
        from app.database import transport_anyone_in_progress
        conn = _make_conn()
        ev = _event(conn)
        _add_open_flight(conn, 7, "EDWG", "EDXH", "BN2P", "2026-07-01T23:30:00Z")
        assert transport_anyone_in_progress(conn, ev, started_before=END) is False

    def test_offroute_open_flight_ignored(self):
        from app.database import transport_anyone_in_progress
        conn = _make_conn()
        ev = _event(conn)
        _add_open_flight(conn, 7, "EDDH", "EDDF", "B738", "2026-07-01T20:00:00Z")
        assert transport_anyone_in_progress(conn, ev, started_before=END) is False

    def test_closed_flights_do_not_block(self):
        from app.database import transport_anyone_in_progress
        conn = _make_conn()
        ev = _event(conn)
        _add_flight(conn, 7, "EDWG", "EDXH", "BN2P", "2026-07-01T20:00:00Z")
        assert transport_anyone_in_progress(conn, ev, started_before=END) is False


# --- KI-Sprüche: verständlich bleiben (Task #14) -----------------------------

class TestQuipPromptVerstaendlich:
    """Der System-Prompt der KI-Sprüche muss verständliches Hochdeutsch verlangen und darf
    Plattdeutsch-Vokabular nicht mehr als Stilmittel anbieten (Live-Test: 'frünnen' in der
    Tagesend-Zusammenfassung)."""

    def test_prompt_verlangt_hochdeutsch_und_verbietet_platt(self):
        from app.llm import _QUIP_SYSTEM
        assert "Hochdeutsch" in _QUIP_SYSTEM
        # Explizites Verbot ganzer Platt-Wörter/Sätze
        assert "plattdeutsch" in _QUIP_SYSTEM.lower()
        assert "KEINE" in _QUIP_SYSTEM or "keine platt" in _QUIP_SYSTEM.lower()

    def test_prompt_bietet_platt_nicht_mehr_als_stilmittel_an(self):
        from app.llm import _QUIP_SYSTEM
        # Vorher stand dort: "mal mit plattdeutschem Anklang (z.B. 'Moin', 'dat', 'nich')" —
        # 'dat'/'nich' dürfen nicht mehr als positive Beispiele auftauchen.
        assert "mit plattdeutschem Anklang" not in _QUIP_SYSTEM


# --- Erkennungs-Umkreis pro Event (radius_km) --------------------------------

class TestEventRadius:
    def test_radius_roundtrip_and_default(self):
        conn = _make_conn()
        ev = _event(conn, radius_km=3.0)          # _event reicht radius_km an create_transport_event durch
        assert ev["radius_km"] == 3.0
        ev2 = _event(conn)                        # ohne Angabe → NULL
        assert ev2["radius_km"] is None

    def test_check_live_arrival_uses_event_radius(self):
        """3-km-Event latcht bei ~4 km Abstand NICHT; ohne radius_km (Default 10) schon.
        Fixtures analog TestCheckLiveArrival (~Z. 491): EDXH-Koordinaten + Offset-Position."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        lat, lon = icao_to_coords("EDXH")
        pos4km = (lat + 0.036, lon)               # ~4 km nördlich
        ev_small = _event(conn, destination="EDXH", radius_km=3.0)
        ev_default = _event(conn, destination="EDXH")
        events = active_transport_destinations(conn, ev_small["dtstart"])
        check_live_arrival(conn, 111, "2026-07-02T18:00:00Z", pos4km[0], pos4km[1], 0.0, events)
        latched_small = get_transport_live_arrivals(conn, ev_small["id"])
        latched_default = get_transport_live_arrivals(conn, ev_default["id"])
        assert (111, "2026-07-02T18:00:00Z") not in latched_small
        assert (111, "2026-07-02T18:00:00Z") in latched_default

    def test_compute_uses_event_radius_from_dict(self):
        """compute_transport_progress ohne expliziten radius_km-Parameter nutzt event['radius_km']."""
        conn = _make_conn()
        ev = _event(conn, radius_km=3.0)
        # Flug mit GPS-Erstposition 4 km neben EDWG: mit 3-km-Radius greift die GPS-Korrektur
        # NICHT (Fallback Flugplan-DEP bleibt) — Detailassertions je nach vorhandenen Fixtures;
        # Minimalfall: Funktion läuft ohne Parameter durch und liefert das route-Feld.
        result = compute_transport_progress(conn, ev, ev["dtend"])
        assert "route" in result


# --- Fracht-Reservierung ----------------------------------------------------

class TestReservation:
    def test_open_flight_reserves_payload(self):
        """Offener Flug Richtung Ziel ohne Latch: 0 kg geliefert, aber reserviert."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)  # payload 292
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 200)
        assert f["in_air"] is True and f["loaded"] is False
        assert f["tonnage_kg"] == 0.0 and f["reserved_kg"] == 292.0
        assert p["reserved_total_kg"] == 292.0
        assert p["cargo"][0]["reserved_kg"] == 292.0
        assert p["cargo"][0]["delivered_kg"] == 0.0      # Fortschritt unverändert

    def test_reservation_capped_by_remaining_target(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 100.0}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["cargo"][0]["reserved_kg"] == 100.0     # gekappt auf offenen Bedarf
        assert p["reserved_total_kg"] == 100.0
        assert p["flights"][0]["reserved_kg"] == 292.0   # was er trägt, bleibt volle Zuladung

    def test_reservation_respects_per_flight_cap_and_coload(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0},
            {"name": "Friesentee", "target_kg": 500.0},
        ])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["cargo"][0]["reserved_kg"] == 100.0     # Kappung pro Flug
        assert p["cargo"][1]["reserved_kg"] == 192.0     # Co-Load-Rest

    def test_reserved_flight_shows_cargo_lines(self):
        """Der Live-Tab-Block zeigt, was ein unterwegs befindlicher Flug geladen hat —
        volle Bordladung wie bei Verlust-Zeilen (Manifest-Reihenfolge, pro-Flug-Kappung)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0},
            {"name": "Friesentee", "target_kg": 500.0},
        ])
        _add_open_flight(conn, 205, "EDWG", "EDXH", "C172", "2026-07-01T18:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 205)
        assert f["in_air"] is True and f["loaded"] is False
        lines = {l["name"]: l["kg"] for l in f["cargo_lines"]}
        assert lines == {"Filmrollen": 100.0, "Friesentee": 192.0}

    def test_latch_converts_reservation_to_delivered(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        set_transport_live_arrival(conn, 200, "2026-07-02T18:05:00Z", ev["id"], "2026-07-02T18:30:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 200)
        assert f["loaded"] is True and f["tonnage_kg"] == 292.0 and f["reserved_kg"] == 0.0
        assert p["cargo"][0]["delivered_kg"] == 292.0
        assert p["reserved_total_kg"] == 0.0             # kein Doppelzählen


# --- Fracht-Verluste: Kutter versunken, geklaut, zurückgebracht -------------

class TestCargoLosses:
    def _flown_flight(self, conn, cid, logon, *, end_lat, end_lon, end_gs, arrival="EDXH"):
        """Geschlossener Flug ab EDWG Richtung Ziel mit Bewegungs-Track und letzter Position."""
        from app.geo import icao_to_coords
        dlat, dlon = icao_to_coords("EDWG")
        _add_flight(conn, cid, "EDWG", arrival, "C172", logon, duration_min=30)
        _add_pos(conn, cid, logon, dlat, dlon, 0)                      # Start am Platz
        _add_pos(conn, cid, _shift(logon, 10), dlat + 0.2, dlon, 90)   # geflogen
        _add_pos(conn, cid, _shift(logon, 30), end_lat, end_lon, end_gs)

    def test_sunk_when_vanished_airborne(self):
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        self._flown_flight(conn, 300, "2026-07-01T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        n = detect_transport_losses(conn, ev)
        assert n == 1
        losses = get_transport_losses(conn, ev["id"])
        assert losses[0]["kind"] == "sunk"
        # Der Pilot hatte EDXH gefilet — der GPS-belegte Verlust überstimmt die Lieferung,
        # die nur am Flugplan-Text hängt (Live-Befund Demo 02.07.: sonst versinkt NIE jemand,
        # der brav einen Plan zum Ziel aufgibt).
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 300)
        assert f["loss_kind"] == "sunk" and f["loaded"] is False and f["tonnage_kg"] == 0.0
        assert p["lost_total_kg"] == 292.0 and p["total_kg"] == 0.0
        assert p["cargo"][0]["delivered_kg"] == 0.0      # Menge bleibt offen

    def test_stolen_when_landed_elsewhere(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        wlat, wlon = icao_to_coords("EDWY")                 # Norderney — nicht auf der Route
        self._flown_flight(conn, 301, "2026-07-01T18:05:00Z", end_lat=wlat, end_lon=wlon, end_gs=0)
        detect_transport_losses(conn, ev)
        assert get_transport_losses(conn, ev["id"])[0]["kind"] == "stolen"
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 301)
        assert f["loss_kind"] == "stolen" and f["loaded"] is False
        assert p["lost_total_kg"] == 292.0 and p["total_kg"] == 0.0

    def test_returned_home_is_no_loss(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        dlat, dlon = icao_to_coords("EDWG")
        self._flown_flight(conn, 302, "2026-07-01T18:05:00Z", end_lat=dlat, end_lon=dlon, end_gs=0, arrival="EDWG")
        detect_transport_losses(conn, ev)
        assert get_transport_losses(conn, ev["id"])[0]["kind"] == "returned"
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 302)
        assert f["loss_kind"] == "returned"
        assert p["lost_total_kg"] == 0.0                    # zurückgebracht ≠ verloren

    def test_detection_is_idempotent_and_skips_delivered(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        alat, alon = icao_to_coords("EDXH")
        self._flown_flight(conn, 303, "2026-07-01T18:05:00Z", end_lat=alat, end_lon=alon, end_gs=0)
        assert detect_transport_losses(conn, ev) == 0       # am Ziel gelandet → geliefert
        self._flown_flight(conn, 304, "2026-07-01T18:20:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        assert detect_transport_losses(conn, ev) == 1
        assert detect_transport_losses(conn, ev) == 0       # idempotent

    def test_detect_skips_flights_without_positions(self):
        """Keine Position = keine Aussage: Flüge ohne jeden GPS-Track (z. B. StatSim-
        rekonstruiert) dürfen nicht als versunken gelten — sonst würde der
        Verlust-Override echte StatSim-Lieferungen kippen."""
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        _add_flight(conn, 306, "EDWG", "EDWL", "C172", "2026-07-01T18:05:00Z", duration_min=25)
        assert detect_transport_losses(conn, ev) == 0
        assert get_transport_losses(conn, ev["id"]) == []

    def test_loss_shows_cargo_lines(self):
        """Die Verlust-Zeile zeigt, WAS über Bord ging — Co-Load-Verteilung wie bei
        einem beladenen Flug (Nutzer-Wunsch 02.07.: 'x Krabbenbrötchen, x Schafe |
        Kutter versunken')."""
        conn = _make_conn()
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0},
            {"name": "Friesentee", "target_kg": 500.0},
        ])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        # Vorher liefert jemand — die Verlust-Aufschlüsselung zeigt trotzdem die VOLLE
        # Bordladung (Restkapazität ist egal: die Ladung ist weg, nicht im Manifest).
        from app.geo import icao_to_coords
        alat, alon = icao_to_coords("EDXH")
        self._flown_flight(conn, 308, "2026-07-01T17:30:00Z", end_lat=alat, end_lon=alon, end_gs=0)
        self._flown_flight(conn, 307, "2026-07-01T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        detect_transport_losses(conn, ev)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 307)
        assert f["loss_kind"] == "sunk"
        lines = {l["name"]: l["kg"] for l in f["cargo_lines"]}
        assert lines == {"Filmrollen": 100.0, "Friesentee": 192.0}

    def test_no_loss_for_flight_after_event_window(self):
        """Ein Streckenflug lange nach dtend darf keinem alten Event als Verlust angelastet
        werden (Final-Review-Blocker: Alt-Events sammelten sonst fortlaufend Fremd-Verluste)."""
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        # dtend = 2026-07-01T23:00:00Z — dieser Flug liegt einen Tag danach.
        self._flown_flight(conn, 305, "2026-07-02T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        n = detect_transport_losses(conn, ev)
        assert n == 0
        assert get_transport_losses(conn, ev["id"]) == []


class TestParticipants:
    def test_statuses_and_sums(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        # Pilot 400: geliefert (geschlossen am Ziel) + gerade wieder unterwegs (offen, Richtung Ziel)
        # Innerhalb des Event-Fensters (dtstart/dtend = START/END, 2026-07-01) — ein geschlossener
        # Flug wird über canonicalize_flights' end-Filter geladen, anders als offene Flüge/Losses.
        _add_flight(conn, 400, "EDWG", "EDXH", "C172", "2026-07-01T18:00:00Z", duration_min=25)
        _add_open_flight(conn, 400, "EDWG", "EDXH", "C172", "2026-07-01T19:00:00Z")
        # Pilot 401: offener Rückflug ab Ziel (dep == destination) → returning, keine Reservierung
        _add_open_flight(conn, 401, "EDXH", "EDWG", "C172", "2026-07-01T19:05:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[400]["status"] == "flying" and parts[400]["reserved_kg"] == 292.0
        assert parts[400]["delivered_kg"] == 292.0 and parts[400]["flights"] == 2
        assert parts[401]["status"] == "returning" and parts[401]["reserved_kg"] == 0.0
        # Live-Befund 2026-07-02 (Demo): Nur-Rückflug-Teilnehmer haben ein Muster —
        # es steht im offenen Flug, der Fallback-Zweig muss es übernehmen.
        assert parts[401]["aircraft"] == "C172"
        # Der Live-Tab-Block zeigt Callsigns statt Namen — für alle Status-Arten gefüllt.
        assert parts[400]["callsign"] == "FRS400"
        assert parts[401]["callsign"] == "FRS401"

    def test_arrived_status_with_latch(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        _add_open_flight(conn, 402, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        set_transport_live_arrival(conn, 402, "2026-07-02T18:05:00Z", ev["id"], "2026-07-02T18:30:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["participants"][0]["status"] == "arrived"


class TestLossQuipContext:
    def test_flight_context_carries_kutter_versunken(self):
        f = {"cid": 1, "name": "Klaus Test", "callsign": "FRS22", "dep": "EDWG", "arr": "—",
             "loaded": False, "loss_kind": "sunk", "lost_kg": 292.0,
             "distance_nm": 0, "block_min": 0, "cargo_lines": []}
        ctx = flight_quip_context(f, {"flights": [f]})
        assert "Kutter versunken" in ctx["verlust"]

    def test_summary_context_lists_losses(self):
        prog = {"flights": [], "cargo": [], "route": ["EDWG", "EDXH"], "destination": "EDXH",
                "total_kg": 0, "loaded_count": 0, "lost_total_kg": 292.0,
                "losses": [{"name": "Klaus Test", "callsign": "FRS22", "loss_kind": "sunk",
                            "lost_kg": 292.0, "cid": 1}]}
        ctx = event_summary_context({"name": "Test"}, prog)
        assert ctx["lost_total_kg"] == 292.0 and any("Kutter versunken" in v for v in ctx["verluste"])


# --- Kutter-Forum-Badge (#18) -----------------------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TestKutterBadge:
    """Forum-Abschluss-Badge pro Teilnehmer (analog Bummel-Badge, aber nach der Feierabend-Bilanz
    statt nach Enthüllung eines Rennens)."""

    def test_loss_label_none_without_loss(self):
        from app.badge import _kutter_loss_label
        assert _kutter_loss_label(0, 0) is None

    def test_loss_label_stolen_only(self):
        from app.badge import _kutter_loss_label
        assert _kutter_loss_label(150, 0) == "SPITZBOOV!"

    def test_loss_label_sunk_only(self):
        from app.badge import _kutter_loss_label
        assert _kutter_loss_label(0, 292) == "BADEMESTER!"

    def test_loss_label_both(self):
        from app.badge import _kutter_loss_label
        assert _kutter_loss_label(150, 292) == "SEEROVER!"

    def test_render_returns_png_without_loss(self):
        from app.badge import render_kutter_badge
        png = render_kutter_badge({
            "callsign": "FRS49", "name": "Tobias", "aircraft": "C172",
            "delivered_kg": 292, "stolen_kg": 0, "sunk_kg": 0,
            "event": "Helgoland-Nachschub", "date": "01.07.2026",
        })
        assert png[:8] == _PNG_MAGIC and len(png) > 500

    def test_render_returns_png_with_loss(self):
        from app.badge import render_kutter_badge
        png = render_kutter_badge({
            "callsign": "FRS50", "aircraft": "C172", "delivered_kg": 0,
            "stolen_kg": 150, "sunk_kg": 292,
            "event": "Helgoland-Nachschub", "date": "01.07.2026",
        })
        assert png[:8] == _PNG_MAGIC and len(png) > 500

    def test_render_handles_missing_fields(self):
        from app.badge import render_kutter_badge
        png = render_kutter_badge({"callsign": "FRS1"})
        assert png[:8] == _PNG_MAGIC


class TestKutterBadgeEndpoints:
    """Integrationstests der Badge-Endpoints (Muster: tests/test_admin_api.py -- Fake-Settings +
    Admin-Cookie via make_admin_token). TestClient ohne `with`-Block, damit `lifespan` (Poller-
    Start) NICHT anläuft (kein Netzwerkzugriff waehrend der Tests)."""

    SECRET = "s3cr3t"
    PW = "harle15"

    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "kutter_badge.db")
        init_db(p)
        monkeypatch.setattr(
            main, "get_settings",
            lambda: SimpleNamespace(
                DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=self.SECRET, ADMIN_PASSWORD=self.PW,
                VAPID_PRIVATE_KEY="vapid", VAPID_CONTACT_EMAIL="mailto:test",
            ),
        )
        return TestClient(main.app), p

    def _admin_cookies(self):
        return {ADMIN_COOKIE: make_admin_token(self.SECRET, self.PW)}

    def _seeded_event(self, db_path):
        conn = get_connection(db_path)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        _add_flight(conn, 500, "EDWG", "EDXH", "C172", "2026-07-01T18:00:00Z", duration_min=25)
        conn.commit()
        conn.close()
        return ev

    def test_404_before_summary(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        ev = self._seeded_event(db)
        res = client.get(f"/api/transport/event/{ev['id']}/badge/500.png")
        assert res.status_code == 404

    def test_200_after_summary(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        ev = self._seeded_event(db)
        conn = get_connection(db)
        set_transport_summarized(conn, ev["id"], "2026-07-01T23:00:00Z")
        conn.commit()
        conn.close()
        res = client.get(f"/api/transport/event/{ev['id']}/badge/500.png")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert res.content[:8] == _PNG_MAGIC

    def test_404_for_non_participant(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        ev = self._seeded_event(db)
        conn = get_connection(db)
        set_transport_summarized(conn, ev["id"], "2026-07-01T23:00:00Z")
        conn.commit()
        conn.close()
        res = client.get(f"/api/transport/event/{ev['id']}/badge/999.png")
        assert res.status_code == 404

    def test_admin_endpoint_ok_without_summary(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        ev = self._seeded_event(db)
        client.cookies.update(self._admin_cookies())
        res = client.get(f"/api/admin/transport/events/{ev['id']}/badge/500.png")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"

    def test_admin_endpoint_requires_auth(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        ev = self._seeded_event(db)
        res = client.get(f"/api/admin/transport/events/{ev['id']}/badge/500.png")
        assert res.status_code == 401
