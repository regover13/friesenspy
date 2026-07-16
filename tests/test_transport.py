"""Tests für FriesenKutter — Transportflug-Events, Fracht-Manifest, Zuladungs-Tabelle.

Kern der Wertung (compute_transport_progress): Fracht zählt nur in eine Richtung (Ankunft am
``destination``); Rückflüge sind leer, erscheinen aber im Feed. Das Fracht-Manifest füllt sich
sequenziell nach Abflugzeit; jeder beladene Flug trägt die Frachtart, in die sein Anteil
überwiegend floss. Alle Tests mit In-Memory-DB (:memory:).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
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
    open_transport_flights,
    transport_event_started,
    set_transport_summarized,
    set_transport_push_enabled,
    transport_events_due_for_reminder,
    mark_event_reminded,
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


def _add_delivered_flight(conn, cid, dep, aircraft, logon, ev_id, *, duration_min=30, callsign=None,
                          latch_offset_min=5, destination="EDXH"):
    """Eine tatsächlich am Ziel angekommene Fracht-Lieferung — jetzt mit echtem GPS-Track.

    Früher: Connection + Live-Ankunfts-Latch (der Latch WAR der Nachweis). Der Latch ist weg;
    die Lieferung ist genau dann eine, wenn der Detektor die Landung am Ziel sieht. ``ev_id`` und
    ``latch_offset_min`` bleiben für die Aufrufer-Verträglichkeit erhalten und werden ignoriert.
    """
    from app.geo import icao_to_coords, airport_elevation_ft
    callsign = callsign or f"FRS{cid:02d}"
    dlat, dlon = icao_to_coords(dep)
    delev = airport_elevation_ft(dep) or 0
    alat, alon = icao_to_coords(destination)
    aelev = airport_elevation_ft(destination) or 0
    _add_flight(conn, cid, dep, destination, aircraft, logon, duration_min=duration_min,
                callsign=callsign)
    _add_pos(conn, cid, logon, dlat, dlon, 0, alt=delev, callsign=callsign)
    _add_pos(conn, cid, _shift(logon, 2), dlat, dlon, 80, alt=delev + 1200, callsign=callsign)
    _add_pos(conn, cid, _shift(logon, duration_min // 2), (dlat + alat) / 2, (dlon + alon) / 2,
             120, alt=4000, callsign=callsign)
    _add_pos(conn, cid, _shift(logon, duration_min - 2), alat, alon, 60, alt=aelev + 400,
             callsign=callsign)
    _add_pos(conn, cid, _shift(logon, duration_min), alat, alon, 0, alt=aelev, callsign=callsign)
    conn.commit()


def _event(conn, *, route="EDWG,EDXH", destination="EDXH", cargo=None, radius_km=None):
    eid = create_transport_event(
        conn, name="Helgoland-Nachschub", route=route, dtstart=START, dtend=END,
        destination=destination, cargo=cargo, radius_km=radius_km,
    )
    return get_transport_event(conn, eid)


def _feed_by_callsign(progress, callsign):
    return next((f for f in progress["flights"] if f["callsign"] == callsign), None)


def _add_pos(conn, cid, ts, lat, lon, gs, *, alt=None, callsign=None):
    # callsign MUSS gesetzt sein (FRS-Praefix) -- canonicalize_legs/_positions_for_cid filtert
    # Positionen ohne passendes Callsign sonst komplett heraus (#23 GPS-only); ohne jede
    # passende Position faellt der Flug auf den Connection-Fallback zurueck (kein GPS-Leg).
    callsign = callsign or f"FRS{cid:02d}"
    conn.execute(
        "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, callsign, lat, lon, alt, gs, ts),
    )
    conn.commit()


def _set_live_pos(conn, cid, lat, lon, gs, *, callsign=None):
    """Aktuelle Live-Position setzen (live_positions) — Quelle für _current_pos / Boden-Beladung."""
    callsign = callsign or f"FRS{cid:02d}"
    conn.execute(
        "INSERT OR REPLACE INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
        "VALUES (?, ?, ?, ?, ?)",
        (cid, callsign, lat, lon, gs),
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

    def test_infinite_values_never_persisted(self):
        # #64: ein Phantom-Typcode (z.B. Buchstabendreher AS65→SA65) lieferte über den
        # KI-Vorschlag inf/nan-Werte, die dann die ganze Zuladungs-Liste beim JSON-Encoding
        # sprengten (500 „Lade Zuladungen…" hängt). upsert_payload muss inf/nan zu None kappen,
        # NIE roh in die DB schreiben.
        conn = _make_conn()
        upsert_payload(conn, "SA65", mtow_kg=4000, empty_kg=float("-inf"), fuel_kg=510)
        conn.commit()
        from app.database import list_aircraft_payloads
        import json
        rows = list_aircraft_payloads(conn)
        row = next(r for r in rows if r["type_code"] == "SA65")
        assert row["empty_kg"] is None       # nie roh gespeichert
        json.dumps(rows)                     # muss ohne ValueError durchlaufen


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
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 300, "per_flight_max_kg": 100, "emoji": "🎞️", "departure": "EDWG"},
            {"name": "Friesentee", "target_kg": 500, "emoji": "🫖", "departure": "EDWG"},
        ])
        _add_delivered_flight(conn, 7, "EDWG", "C208", "2026-07-01T10:00:00Z", ev["id"])
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


class TestCalendarSyncSnapshotInvalidation:
    """#66 Task 7: `upsert_calendar_transport_event` läuft bei JEDEM Kalender-Sync — ein
    eingefrorener Snapshot darf deshalb nur bei tatsächlicher Wertänderung (route/dtstart/
    dtend/destination) verworfen werden, nicht bei jedem (identischen) Re-Sync."""

    def _cal_ev(self, **overrides):
        ev = {
            "uid": "kutter_sync_1", "summary": "FriesenKutter Helgoland", "route": "EDWG,EDXH",
            "dtstart": START, "dtend": END, "cargo": [],
        }
        ev.update(overrides)
        return ev

    def test_calendar_sync_no_value_change_keeps_snapshot(self):
        from app.database import get_progress_snapshot, write_progress_snapshot
        conn = _make_conn()
        upsert_calendar_transport_event(conn, self._cal_ev())
        conn.commit()
        eid = conn.execute("SELECT id FROM transport_events WHERE calendar_uid='kutter_sync_1'").fetchone()[0]
        write_progress_snapshot(conn, "kutter", eid, {"total_kg": 99.0}, "t")
        conn.commit()

        # Identischer Re-Sync (gleiche route/dtstart/dtend/destination) → Snapshot bleibt.
        upsert_calendar_transport_event(conn, self._cal_ev())
        conn.commit()

        assert get_progress_snapshot(conn, "kutter", eid) == {"total_kg": 99.0}

    def test_calendar_sync_value_change_clears_snapshot(self):
        from app.database import get_progress_snapshot, write_progress_snapshot
        conn = _make_conn()
        upsert_calendar_transport_event(conn, self._cal_ev())
        conn.commit()
        eid = conn.execute("SELECT id FROM transport_events WHERE calendar_uid='kutter_sync_1'").fetchone()[0]
        write_progress_snapshot(conn, "kutter", eid, {"total_kg": 99.0}, "t")
        conn.commit()

        # Geänderte Strecke im Kalender → echte Wertänderung → Snapshot muss weg.
        upsert_calendar_transport_event(conn, self._cal_ev(route="EDWG,EDWO,EDXH"))
        conn.commit()

        assert get_progress_snapshot(conn, "kutter", eid) is None


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

    def test_clear_transport_quips_removes_all_and_resets_summary(self):
        from app.database import clear_transport_quips, set_transport_summary_quip
        conn = _make_conn()
        ev = _event(conn)
        set_transport_quip(conn, ev["id"], "1:a", "alt")
        set_transport_quip(conn, ev["id"], "2:b", "auch alt")
        set_transport_summary_quip(conn, ev["id"], "Tagesend-Spruch")
        set_transport_quip(conn, 999, "9:z", "Fremd-Event")   # anderes Event bleibt unberührt
        conn.commit()
        cleared = clear_transport_quips(conn, ev["id"])
        conn.commit()
        assert cleared == 2
        assert get_transport_quips(conn, ev["id"]) == {}
        assert get_transport_quips(conn, 999) == {"9:z": "Fremd-Event"}
        row = conn.execute("SELECT summary_quip FROM transport_events WHERE id=?", (ev["id"],)).fetchone()
        assert row["summary_quip"] is None


# --- Wertung / Manifest ----------------------------------------------------

class TestProgress:
    def _seed(self, conn):
        upsert_payload(conn, "C172", payload_kg=250)
        upsert_payload(conn, "C208", payload_kg=550)
        conn.commit()

    def test_oneway_return_is_empty(self):
        conn = _make_conn()
        self._seed(conn)
        # target == Musterzuladung: der Hinflug räumt den EDWG-Stapel leer, damit der Rückflug
        # beim Landen dort nichts mehr aufnimmt (sonst „returned" statt leer).
        ev = _event(conn, cargo=[{"name": "Fracht", "target_kg": 250, "departure": "EDWG"}])
        _add_delivered_flight(conn, 12, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])  # hin, beladen -> EDXH
        # Rückflug EDXH -> EDWG als ECHTES GPS-Leg (ohne Track kein Kutter-Flug): landet am
        # (nun leeren) Ladeplatz EDWG, lädt nichts, liefert nichts -> leer.
        _add_delivered_flight(conn, 12, "EDXH", "C172", "2026-07-01T11:00:00Z", ev["id"], destination="EDWG")
        p = compute_transport_progress(conn, ev, END)

        assert p["flight_count"] == 2 and p["loaded_count"] == 1
        assert p["total_kg"] == 250
        # es gibt zwei Einträge mit derselben Callsign; explizit über dep prüfen
        loaded = next(f for f in p["flights"] if f["dep"] == "EDWG")
        empty = next(f for f in p["flights"] if f["dep"] == "EDXH")
        assert loaded["loaded"] is True and loaded["tonnage_kg"] == 250
        assert empty["loaded"] is False and empty["tonnage_kg"] == 0.0
        assert empty["cargo_name"] is None

    def test_feed_newest_first(self):
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn)
        # Echte GPS-Lieferungen (dep_time = GPS-Takeoff); der spätere Abflug muss oben stehen.
        _add_delivered_flight(conn, 12, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])
        _add_delivered_flight(conn, 7, "EDWG", "C208", "2026-07-01T10:30:00Z", ev["id"])
        p = compute_transport_progress(conn, ev, END)
        dep_times = [f["dep_time"] for f in p["flights"]]
        assert dep_times == sorted(dep_times, reverse=True)          # neueste oben
        assert p["flights"][0]["cid"] == 7 and p["flights"][1]["cid"] == 12

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
        # Stapel-Modell: Ware liegt an genau einem Ladeplatz (departure) — EDWG ist der Ladeplatz.
        ev = _event(conn, cargo=[{"name": "Fracht", "target_kg": 500, "departure": "EDWG"}])
        _add_delivered_flight(conn, 3, "EDWG", "PA28", "2026-07-01T10:00:00Z", ev["id"])  # kein Payload gepflegt
        p = compute_transport_progress(conn, ev, END)
        assert p["total_kg"] == 150.0  # globaler Default
        assert "PA28" in p["unmapped_types"]

    def test_manifest_sequential_fill(self):
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=[
            {"name": "Fischbrötchen", "target_kg": 800, "departure": "EDWG"},
            {"name": "Friesen Tee", "target_kg": 500, "departure": "EDWG"},
        ])
        # beladene Flüge: 250 + 550 = 800 (füllt Fischbrötchen), dann 150 → Tee
        _add_delivered_flight(conn, 12, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])   # 250
        _add_delivered_flight(conn, 7, "EDWG", "C208", "2026-07-01T10:30:00Z", ev["id"])    # 550
        _add_flight(conn, 12, "EDXH", "EDWG", "C172", "2026-07-01T10:45:00Z")   # leer (zurück)
        upsert_payload(conn, "PA28", payload_kg=150)
        conn.commit()
        _add_delivered_flight(conn, 3, "EDWG", "PA28", "2026-07-01T11:00:00Z", ev["id"])    # 150 → Tee
        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] == 950
        assert p["target_kg"] == 1300
        fisch = next(c for c in p["cargo"] if c["name"] == "Fischbrötchen")
        tee = next(c for c in p["cargo"] if c["name"] == "Friesen Tee")
        assert fisch["delivered_kg"] == 800 and fisch["pct"] == 100.0
        assert tee["delivered_kg"] == 150 and tee["pct"] == 30.0
        # Frachtart je beladenem Flug (dep_time ist jetzt der GPS-Takeoff — über cid prüfen)
        by_cid = {f["cid"]: f for f in p["flights"] if f["loaded"]}
        assert by_cid[12]["cargo_name"] == "Fischbrötchen"   # 250, erster am EDWG-Stapel
        assert by_cid[7]["cargo_name"] == "Fischbrötchen"    # 550, füllt Fisch voll
        assert by_cid[3]["cargo_name"] == "Friesen Tee"      # 150, Fisch leer -> Tee

    def test_capped_overflow_not_credited_to_total(self):
        # #63 „Balken lügt nicht": Fracht ohne Manifest-Platz (per_flight_max_kg-Kappung) zählt
        # NICHT als geliefert. tonnage_kg je Flug = tatsächliche Gutschrift, nicht Musterzuladung.
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=[
            {"name": "Inselpost", "target_kg": 1500, "per_flight_max_kg": 50, "departure": "EDWG"},
        ])
        _add_delivered_flight(conn, 12, "EDWG", "C208", "2026-07-01T10:00:00Z", ev["id"])  # Muster 550
        _add_delivered_flight(conn, 7, "EDWG", "C208", "2026-07-01T10:30:00Z", ev["id"])   # Muster 550
        p = compute_transport_progress(conn, ev, END)

        # Jeder Flug trägt nur 50 kg ins Manifest, die restlichen 500 verpuffen (keine weitere
        # Frachtart) — der Gesamtwert bleibt 100, NICHT 1100 (die Summe der Musterzuladungen).
        assert p["total_kg"] == 100
        post = next(c for c in p["cargo"] if c["name"] == "Inselpost")
        assert post["delivered_kg"] == 100
        for f in p["flights"]:
            if f["loaded"]:
                assert f["tonnage_kg"] == 50       # belegt (Netto) — Gutschrift ins Manifest
                assert f["onboard_kg"] == 50       # Stapel-Modell: geliefert == an Bord (nur Event-Fracht)
        # Konsistenz-Invariante: Σ Flug-Gutschriften == total_kg == Σ delivered.
        assert sum(f["tonnage_kg"] for f in p["flights"] if f["loaded"]) == p["total_kg"]
        assert p["total_kg"] == sum(c["delivered_kg"] for c in p["cargo"])

    def test_cargo_exposes_per_flight_max_kg(self):
        # #63: per_flight_max_kg im API-Response fürs Kappungs-Badge in der Legende.
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=[
            {"name": "Inselpost", "target_kg": 1500, "per_flight_max_kg": 50},
            {"name": "Lebensmittel", "target_kg": 500},
        ])
        p = compute_transport_progress(conn, ev, END)
        post = next(c for c in p["cargo"] if c["name"] == "Inselpost")
        leb = next(c for c in p["cargo"] if c["name"] == "Lebensmittel")
        assert post["per_flight_max_kg"] == 50
        assert leb["per_flight_max_kg"] is None

    # TODO(ask-user): Soll ein Kutter-Event OHNE Manifest (cargo=None) weiterhin als einfacher
    # Zähler zählen (jede Lieferung = volle Musterzuladung, hier 250)? Das Stapel-Modell liefert
    # 0, weil ohne Manifest keine Ware auf einem Stapel liegt (Entscheidung 6 streicht den
    # geteilten Topf; Events verlangen jetzt per Validierung ein Cargo). Der Wert 250 ist die
    # alte Plain-Counter-Semantik — bewusst NICHT auf 0 „repariert", bis geklärt ist, ob
    # manifestlose Events überhaupt noch gewertet werden sollen. Bleibt bis dahin rot.
    def test_no_manifest_delivers_nothing(self):
        """Ohne Manifest liegt keine Ware auf einem Stapel — es gibt nichts zu liefern (0 kg).
        Der fruehere 'einfacher Zaehler'-Modus (jede Lieferung = voller Payload) entfaellt
        bewusst (Nutzer-Entscheidung 16.07.: war nie gewollt). Ladung ist ein Bestand; kein
        Manifest = kein Bestand."""
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=None)
        _add_delivered_flight(conn, 12, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])
        p = compute_transport_progress(conn, ev, END)
        assert p["cargo"] == []
        assert p["target_kg"] is None and p["progress_pct"] is None
        assert p["total_kg"] == 0.0


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

    def test_true_and_progress_shows_open_flight_unloaded(self):
        """Flug in der Luft, noch kein Disconnect -> compute_transport_progress zeigt das
        erkannte GPS-Leg bereits im Feed, aber unbeladen (0 kg, ohne Manifest keine Ware);
        transport_event_started feuert unabhängig davon schon beim Abflug (flugplan-tolerant)."""
        conn = _make_conn()
        ev = _event(conn)
        # Echtes, abgehobenes GPS-Leg ab EDWG (Takeoff, noch keine Landung) — ohne Track kein Flug.
        from app.geo import icao_to_coords, airport_elevation_ft
        la, lo = icao_to_coords("EDWG")
        ea = airport_elevation_ft("EDWG") or 0
        _add_open_flight(conn, 61, "EDWG", "", "C208", START)
        _add_pos(conn, 61, START, la, lo, 0, alt=ea, callsign="FRS61")
        _add_pos(conn, 61, _shift(START, 1), la, lo, 12, alt=ea, callsign="FRS61")
        _add_pos(conn, 61, _shift(START, 4), la, lo, 80, alt=ea + 1200, callsign="FRS61")
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:15:00Z")
        assert progress["flight_count"] == 1
        f = _feed_by_callsign(progress, "FRS61")
        assert f is not None
        assert f["loaded"] is False
        assert f["tonnage_kg"] == 0
        assert transport_event_started(conn, ev) is True


class TestLiveArrivalInProgress:
    # Der Live-Ankunfts-Latch ist entfallen (Stapel-Modell: die Landung am Ziel liefert selbst,
    # der Logout mit Ware an Bord stiehlt/versenkt). Die früheren Latch-Fixtures wurden ersatzlos
    # gelöscht (mit-Latch-zählt-sofort, geparkt-mit-spuriosem-Latch, Latch-persists,
    # Coload-über-Latch) bzw. leben in TestReservation/TestStapelProgress als GPS-Track-Szenarien
    # weiter. Was ohne Latch bleibt: ein offener Flug liefert (noch) 0 kg.
    def test_open_flight_in_air_shows_zero_kg(self):
        """Ohne Manifest keine Ware — ein abgehobenes GPS-Leg ist im Feed sichtbar, aber
        unbeladen (0 kg geliefert), solange es nicht am Ziel gelandet ist."""
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        ev = _event(conn)
        from app.geo import icao_to_coords, airport_elevation_ft
        la, lo = icao_to_coords("EDWG")
        ea = airport_elevation_ft("EDWG") or 0
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        _add_pos(conn, 9, START, la, lo, 0, alt=ea, callsign="FRS09")
        _add_pos(conn, 9, _shift(START, 1), la, lo, 12, alt=ea, callsign="FRS09")
        _add_pos(conn, 9, _shift(START, 4), la, lo, 80, alt=ea + 1200, callsign="FRS09")
        p = compute_transport_progress(conn, ev, _shift(START, 10))
        f = _feed_by_callsign(p, "FRS09")
        assert f is not None
        assert f["loaded"] is False
        assert f["tonnage_kg"] == 0

    def test_open_flight_departing_from_destination_is_excluded(self):
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        _add_open_flight(conn, 9, "EDXH", "", "C208", START)  # startet BEREITS am Ziel
        ev = _event(conn)
        p = compute_transport_progress(conn, ev, END)
        assert _feed_by_callsign(p, "FRS09") is None


# --- Feierabend wartet auf Nachzügler (Task #13) ----------------------------

class TestAnyoneInProgress:
    """transport_anyone_in_progress: die Feierabend-Zusammenfassung darf erst entstehen,
    wenn kein Pilot mehr für das Event unterwegs ist (analog Bummel-Reveal).

    Das Kriterium ist seit dem Stapel-Modell „trägt jemand Ware?" (Entscheidung 10), nicht mehr
    „gibt es einen offenen Flug auf der Strecke". Der positive Fall (beladener Pilot verzögert)
    und der leere-Pilot-Fall stehen jetzt als GPS-Track-Szenarien in TestStapelProgress
    (test_ein_beladener_pilot_haelt_den_feierabend_auf / ..._nicht_auf). Hier bleiben die
    Negativfälle, die weiterhin False ergeben müssen — der Grund ist jetzt „keine Ware an Bord"."""

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


# --- Erkennungs-Umkreis: DB-Spalte bleibt, wirkt aber nirgends mehr per-Event (#23) ----------
#
# Der Per-Event-/Per-Rennen-Radius wurde ersatzlos gestrichen: es gilt überall der globale
# 4-km-Standard (``_BUMMEL_AIRPORT_RADIUS_KM``). ``transport_events.radius_km`` bleibt als
# Spalte bestehen (Drop erst in Task 12), wird aber nicht mehr gelesen/geschrieben.

class TestEventRadius:
    def test_radius_column_roundtrip(self):
        """Reine DB-Spalten-Probe (Speichern/Lesen) — die Spalte existiert weiter, hat aber
        keinen funktionalen Effekt mehr (s. Klassen-Docstring)."""
        conn = _make_conn()
        ev = _event(conn, radius_km=3.0)          # _event reicht radius_km an create_transport_event durch
        assert ev["radius_km"] == 3.0
        ev2 = _event(conn)                        # ohne Angabe → NULL
        assert ev2["radius_km"] is None

    # test_check_live_arrival_uses_global_radius_regardless_of_event_radius: ersatzlos gelöscht —
    # check_live_arrival / active_transport_destinations / get_transport_live_arrivals sind mit dem
    # Latch-Rückbau entfallen (Spec „Zu löschen"). Die Landungserkennung sitzt jetzt im Detektor.


# --- Fracht-Reservierung ----------------------------------------------------

class TestReservation:
    def test_open_flight_reserves_payload(self):
        """Offener Flug, der am Ladeplatz steht: 0 kg geliefert, aber die Bordladung (= Reservierung)
        stammt aus dem Stapel dieses Platzes."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)  # payload 292
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-01T18:05:00Z")
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        _set_live_pos(conn, 200, la, lo, 0)          # steht am Ladeplatz EDWG -> lädt vom Stapel
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 200)
        assert f["in_air"] is True and f["loaded"] is False
        assert f["tonnage_kg"] == 0.0 and f["reserved_kg"] == 292.0
        assert p["reserved_total_kg"] == 292.0
        assert p["cargo"][0]["reserved_kg"] == 292.0
        assert p["cargo"][0]["delivered_kg"] == 0.0      # Fortschritt unverändert

    def test_reservation_capped_by_remaining_target(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 100.0, "departure": "EDWG"}])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-01T18:05:00Z")
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        _set_live_pos(conn, 200, la, lo, 0)
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        assert p["cargo"][0]["reserved_kg"] == 100.0     # der Stapel hat nur 100 -> mehr geht nicht
        assert p["reserved_total_kg"] == 100.0
        # Durchgängig Netto (#63): reserved_kg je Flug ist die tatsächliche Bordladung (was der
        # Stapel hergab) — die volle Musterzuladung bleibt separat als onboard_reserved_kg.
        assert p["flights"][0]["reserved_kg"] == 100.0
        assert p["flights"][0]["onboard_reserved_kg"] == 292.0

    def test_reservation_respects_per_flight_cap_and_coload(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0, "departure": "EDWG"},
            {"name": "Friesentee", "target_kg": 500.0, "departure": "EDWG"},
        ])
        _add_open_flight(conn, 200, "EDWG", "EDXH", "C172", "2026-07-01T18:05:00Z")
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        _set_live_pos(conn, 200, la, lo, 0)
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        assert p["cargo"][0]["reserved_kg"] == 100.0     # Kappung pro Flug
        assert p["cargo"][1]["reserved_kg"] == 192.0     # Co-Load-Rest

    def test_reserved_flight_shows_cargo_lines(self):
        """Der Live-Tab-Block zeigt, was ein Flug geladen hat — volle Bordladung
        (Manifest-Reihenfolge, pro-Flug-Kappung)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0, "departure": "EDWG"},
            {"name": "Friesentee", "target_kg": 500.0, "departure": "EDWG"},
        ])
        _add_open_flight(conn, 205, "EDWG", "EDXH", "C172", "2026-07-01T18:05:00Z")
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        _set_live_pos(conn, 205, la, lo, 0)
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 205)
        assert f["in_air"] is True and f["loaded"] is False
        lines = {l["name"]: l["kg"] for l in f["cargo_lines"]}
        assert lines == {"Filmrollen": 100.0, "Friesentee": 192.0}

    def test_open_flight_on_ground_is_not_airborne(self):
        """#62-Folgefund (Live 06.07.): ein am Ladeplatz GEPARKTER Pilot (gs 0, nie abgehoben,
        kein offenes GPS-Leg) trägt zwar schon seine Fracht (aus dem Stapel), gilt aber als „am
        Start" — `airborne` False. `in_air`/Bordladung bleiben (er zählt weiter als offen)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)  # payload 292
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        _add_open_flight(conn, 210, "EDWG", "EDXH", "C172", "2026-07-01T18:05:00Z")
        # Zwei Boden-Samples bei gs 0 am Ladeplatz — nie abgehoben, also kein GPS-Leg.
        _add_pos(conn, 210, "2026-07-01T18:05:00Z", dlat, dlon, 0, alt=delev, callsign="FRS210")
        _add_pos(conn, 210, "2026-07-01T18:06:00Z", dlat, dlon, 0, alt=delev, callsign="FRS210")
        p = compute_transport_progress(conn, ev, "2026-07-01T18:10:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 210)
        assert f["in_air"] is True and f["loaded"] is False    # weiterhin offen, mit Bordladung
        assert f["airborne"] is False                           # aber NICHT „unterwegs"
        assert f["reserved_kg"] == 292.0

    def test_open_flight_airborne_after_takeoff(self):
        """Gegenprobe: sobald der GPS-Leg-Detektor ein offenes (abgehobenes) Leg erkennt, ist der
        Flug „unterwegs" → `airborne` True. Er hat beim Login am Ladeplatz geladen und trägt die
        Ware jetzt in der Luft."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        t0 = "2026-07-01T18:05:00Z"
        _add_open_flight(conn, 211, "EDWG", "EDXH", "C172", t0)
        _add_pos(conn, 211, t0, dlat, dlon, 0, alt=delev, callsign="FRS211")
        _add_pos(conn, 211, _shift(t0, 1), dlat, dlon, 12, alt=delev, callsign="FRS211")
        _add_pos(conn, 211, _shift(t0, 4), dlat, dlon, 80, alt=delev + 1200, callsign="FRS211")  # Takeoff, kein Touchdown
        p = compute_transport_progress(conn, ev, _shift(t0, 10))
        f = next(x for x in p["flights"] if x["cid"] == 211 and x["in_air"])
        assert f["in_air"] is True and f["airborne"] is True
        assert f["reserved_kg"] == 292.0

    # test_skip_open_probe_omits_open_branch: ersatzlos gelöscht — `skip_open_probe` wird seit dem
    # Stapel-Modell ignoriert (compute_transport_progress-Docstring): der zweite canonicalize_legs-
    # Aufruf ist weg (nur noch einer), und ein Freeze kann eine in_air-Zeile nicht mehr einfrieren,
    # weil eingefroren erst wird, wenn niemand mehr Ware trägt. Es gibt nichts wegzufiltern.

    def test_open_flight_after_event_end_excluded(self):
        """Live-Fund 06.07.: ein erst NACH dtend eingeloggter Flug eines Streckenplatzes darf nicht
        mehr im (beendeten) Event auftauchen — sonst leckt jeder gerade fliegende EDWG-Abflieger in
        jedes ältere Event mit demselben Startplatz."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])  # läuft START..END (01.07.)
        _add_open_flight(conn, 220, "EDWG", "EDXH", "C172", "2026-07-02T10:00:00Z")  # NACH END
        p = compute_transport_progress(conn, ev, "2026-07-02T10:30:00Z")  # now weit nach dtend
        assert not any(f["cid"] == 220 for f in p["flights"])

    def test_open_flight_within_window_still_shown_after_dtend(self):
        """Gegenprobe: ein WÄHREND des Fensters gestarteter offener Flug bleibt, auch wenn now nach
        dtend liegt — er gehört zum Event (nur echte Nachzügler fliegen raus)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        _add_open_flight(conn, 221, "EDWG", "EDXH", "C172", "2026-07-01T20:00:00Z")  # innerhalb START..END
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        _set_live_pos(conn, 221, la, lo, 0)          # steht am Ladeplatz, trägt Ware -> bleibt sichtbar
        p = compute_transport_progress(conn, ev, "2026-07-02T10:30:00Z")
        assert any(f["cid"] == 221 for f in p["flights"])

    def test_landing_at_destination_converts_reservation_to_delivered(self):
        """Früher hob der Live-Ankunfts-Latch die Reservierung in eine Lieferung; jetzt tut es die
        GPS-Landung am Ziel selbst: aus der Bordladung wird geliefert, reserved fällt auf 0."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        _add_delivered_flight(conn, 200, "EDWG", "C172", "2026-07-01T18:05:00Z", ev["id"])  # EDWG -> EDXH, landet
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 200)
        assert f["loaded"] is True and f["tonnage_kg"] == 292.0 and f["reserved_kg"] == 0.0
        assert p["cargo"][0]["delivered_kg"] == 292.0
        assert p["reserved_total_kg"] == 0.0             # kein Doppelzählen


# --- Fracht je Startplatz (#15 Sub-Projekt B) ------------------------------

class TestCargoPerDeparture:
    def test_departure_roundtrip(self):
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDDW,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Äpfel", "target_kg": 500, "departure": "EDDW"},
                   {"name": "Birnen", "target_kg": 300, "departure": "EDWG"}],
        )
        by = {c["name"]: c for c in get_transport_cargo(conn, eid)}
        assert by["Äpfel"]["departure"] == "EDDW"
        assert by["Birnen"]["departure"] == "EDWG"

    def test_departure_normalized(self):
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Äpfel", "target_kg": 500, "departure": "edwg "}],
        )
        assert get_transport_cargo(conn, eid)[0]["departure"] == "EDWG"

    def test_departure_kept_and_route_derived(self):
        # #84: kein „streckenfremd → geteilt" mehr — die Route wird aus den Startplätzen ABGELEITET.
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", dtstart=START, dtend=END, destination="EDXH",  # keine route übergeben
            cargo=[{"name": "Äpfel", "target_kg": 500, "departure": "EDDW"}],
        )
        assert get_transport_cargo(conn, eid)[0]["departure"] == "EDDW"
        assert set(get_transport_event(conn, eid)["route"].split(",")) == {"EDDW", "EDXH"}

    def test_departure_equal_destination_becomes_shared(self):
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Äpfel", "target_kg": 500, "departure": "EDXH"}],  # == Ziel → tote Zeile verhindert
        )
        assert get_transport_cargo(conn, eid)[0]["departure"] is None

    def test_no_departure_is_shared_null(self):
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Äpfel", "target_kg": 500}],
        )
        assert get_transport_cargo(conn, eid)[0]["departure"] is None

    def test_update_rederives_route_from_cargo(self):
        # #84: nach einem Cargo-Update wird die Route frisch aus den Startplätzen + Ziel abgeleitet.
        from app.database import update_transport_event
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Alt", "target_kg": 100, "departure": "EDWG"}],
        )
        update_transport_event(
            conn, eid, cargo=[{"name": "Neu", "target_kg": 100, "departure": "EDDW"}],
        )
        assert get_transport_cargo(conn, eid)[0]["departure"] == "EDDW"
        assert set(get_transport_event(conn, eid)["route"].split(",")) == {"EDDW", "EDXH"}


class TestCoLoadPerDeparture:
    def _ev(self, conn):
        upsert_payload(conn, "C172", payload_kg=250)
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDDW,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Äpfel", "target_kg": 500, "departure": "EDDW"},
                   {"name": "Birnen", "target_kg": 300, "departure": "EDWG"}],
        )
        return get_transport_event(conn, eid)

    def test_delivery_fills_only_its_origin(self):
        conn = _make_conn()
        ev = self._ev(conn)
        _add_delivered_flight(conn, 800, "EDDW", "C172", "2026-07-01T10:00:00Z", ev["id"])
        _add_delivered_flight(conn, 801, "EDWG", "C172", "2026-07-01T10:05:00Z", ev["id"])
        p = compute_transport_progress(conn, ev, "2026-07-01T12:00:00Z")
        cargo = {c["name"]: c for c in p["cargo"]}
        assert cargo["Äpfel"]["delivered_kg"] == 250.0
        assert cargo["Birnen"]["delivered_kg"] == 250.0
        assert p["total_kg"] == 500.0
        fa = next(f for f in p["flights"] if f["cid"] == 800)
        fb = next(f for f in p["flights"] if f["cid"] == 801)
        assert [l["name"] for l in fa["cargo_lines"]] == ["Äpfel"]   # EDDW → nur Äpfel
        assert [l["name"] for l in fb["cargo_lines"]] == ["Birnen"]  # EDWG → nur Birnen

    # test_latch_fallback_unknown_dep_fills_all: ersatzlos gelöscht — der „unbekannter Abflug →
    # füllt alle Zeilen"-Fallback (S3b) erzeugte Ware aus dem Nichts. Im Stapel-Modell liegt jede
    # Frachtart an genau einem Ladeplatz; ohne erkannten Ladeplatz nimmt der Flieger schlicht nichts
    # mit (Entscheidung 6, „Ohne GPS-Track keine Lieferung").

    # test_legacy_all_null_unchanged: ersatzlos gelöscht — der „geteilte Topf" (departure IS NULL)
    # entfällt mit Entscheidung 6. Eine Frachtart ohne Ladeplatz liegt auf keinem Stapel.

    def test_reservation_respects_origin(self):
        conn = _make_conn()
        ev = self._ev(conn)
        _add_open_flight(conn, 804, "EDWG", "EDXH", "C172", "2026-07-01T10:00:00Z")
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        _set_live_pos(conn, 804, la, lo, 0)              # steht am EDWG-Stapel (Birnen liegen dort)
        p = compute_transport_progress(conn, ev, "2026-07-01T10:30:00Z")
        cargo = {c["name"]: c for c in p["cargo"]}
        assert cargo["Birnen"]["reserved_kg"] == 250.0   # EDWG-Stapel → nur Birnen an Bord
        assert cargo["Äpfel"]["reserved_kg"] == 0.0      # Äpfel liegen in EDDW

    def test_cargo_response_exposes_departure(self):
        conn = _make_conn()
        ev = self._ev(conn)
        p = compute_transport_progress(conn, ev, "2026-07-01T12:00:00Z")
        cargo = {c["name"]: c for c in p["cargo"]}
        assert cargo["Äpfel"]["departure"] == "EDDW"
        assert cargo["Birnen"]["departure"] == "EDWG"


class TestZeilenStattStrecke:
    def test_normalize_icao_list(self):
        from app.database import _normalize_icao_list
        assert _normalize_icao_list("eddw, edwg") == "EDDW,EDWG"
        assert _normalize_icao_list("EDWG, EDDW") == "EDDW,EDWG"        # stabil sortiert
        assert _normalize_icao_list("EDDW, EDDW") == "EDDW"            # dedup
        assert _normalize_icao_list("EDDW/EDWG") == "EDDW/EDWG"        # NICHT an '/' verstümmelt
        assert _normalize_icao_list("") is None and _normalize_icao_list(None) is None
        assert _normalize_icao_list("EDWG,EDXH", exclude="EDXH") == "EDWG"  # Ziel entfernt
        assert _normalize_icao_list(["EDWG", "eddw"]) == "EDDW,EDWG"        # Liste-Eingabe

    def test_derive_route(self):
        from app.database import _derive_route
        cargo = [{"departure": "EDDW"}, {"departure": "EDWG,EDXP"}]
        assert _derive_route(cargo, "EDXH") == "EDDW,EDWG,EDXH,EDXP"    # Vereinigung + Ziel, sortiert
        # geteilte (NULL) Zeile → existing_route als Sicherheitsnetz (kein Kollaps auf {Ziel})
        assert _derive_route([{"departure": None}], "EDXH", existing_route="EDWG,EDXH") == "EDWG,EDXH"

    # test_multi_departure_both_start_places_load: ersatzlos gelöscht — eine Frachtart an mehreren
    # Startplätzen (CSV im departure-Feld) entfällt mit Entscheidung 6 („genau ein Platz pro
    # Frachtart; für dieselbe Ware an mehreren Plätzen mehrere Zeilen anlegen"). Die reine
    # Route-Ableitung aus dem departure-Feld deckt test_derive_route ab.

    def test_flight_from_unlisted_place_does_not_load(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        eid = create_transport_event(
            conn, name="X", route="EDDW,EDWG,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Äpfel", "target_kg": 1000, "departure": "EDDW"}],  # nur EDDW
        )
        ev = get_transport_event(conn, eid)
        _add_delivered_flight(conn, 902, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])  # EDWG ≠ EDDW
        p = compute_transport_progress(conn, ev, "2026-07-01T12:00:00Z")
        f = next(f for f in p["flights"] if f["cid"] == 902)
        assert f["tonnage_kg"] == 0.0                                   # EDWG lädt Äpfel nicht

    def test_migration_backfill_logic(self):
        from app.database import _normalize_icao_list
        conn = _make_conn()
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Alt", "target_kg": 100}],  # departure NULL (geteilt, Alt-Modell)
        )
        assert get_transport_cargo(conn, eid)[0]["departure"] is None
        ev = get_transport_event(conn, eid)
        deps = _normalize_icao_list(ev["route"], exclude=ev["destination"])   # Backfill-Kern
        conn.execute("UPDATE transport_cargo SET departure = ? WHERE event_id = ? AND departure IS NULL",
                     (deps, eid))
        assert get_transport_cargo(conn, eid)[0]["departure"] == "EDWG"       # Startplatz zugewiesen

    def test_init_db_backfill_over_existing_event_does_not_crash(self, tmp_path):
        # Regression v8.14.0 (Live-Fund): der Backfill in init_db lief über Tupel-Zeilen (keine
        # sqlite3.Row) — `_r["route"]` crashte den App-Start bei bestehenden Events. Hier wird der
        # ECHTE init_db-Pfad über ein vorhandenes Event mit NULL-Cargo ausgeführt.
        p = str(tmp_path / "backfill.db")
        init_db(p)
        conn = get_connection(p)
        eid = create_transport_event(
            conn, name="X", route="EDWG,EDXH", dtstart=START, dtend=END, destination="EDXH",
            cargo=[{"name": "Alt", "target_kg": 100}],  # departure NULL
        )
        conn.commit(); conn.close()
        init_db(p)  # Backfill läuft über das bestehende Event — darf NICHT crashen
        conn = get_connection(p)
        dep = get_transport_cargo(conn, eid)[0]["departure"]
        conn.close()
        assert dep == "EDWG"


# --- Fracht-Verluste: Kutter versunken, geklaut, zurückgebracht -------------

class TestCargoLosses:
    def _flown_flight(self, conn, cid, logon, *, end_lat, end_lon, end_gs, arrival="EDXH", end_alt=None):
        """Geschlossene Connection ab EDWG Richtung Ziel mit einem echten, GPS-erkennbaren
        Abflug (Taxi + Steigflug über die 500-ft-AGL-Schwelle, s. app/gps_legs.py) und einer
        konfigurierbaren Endposition/-höhe/-geschwindigkeit. Eine Landung zählt für den
        Detektor nur, wenn die Endposition innerhalb des Erkennungsradius EINES bekannten
        Flugplatzes UND unter der Boden-AGL-Schwelle liegt — sonst bleibt das GPS-Leg trotz
        bereits geschlossener Connection (``_add_flight`` setzt ``logoff_time`` fest) technisch
        offen (kein Touchdown erkannt): genau der 'sunk'-Fall, ein abseits jedes Flugplatzes
        verschwundener Kutter. ``end_alt`` default: erdnah (50 ft) bei ``end_gs < 2``
        (Landeversuch), sonst Reiseflughöhe (weiterhin in der Luft)."""
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        if end_alt is None:
            end_alt = 50 if (end_gs is not None and end_gs < 2) else 3000
        _add_flight(conn, cid, "EDWG", arrival, "C172", logon, duration_min=30)
        _add_pos(conn, cid, logon, dlat, dlon, 0, alt=delev)                     # Start am Platz
        _add_pos(conn, cid, _shift(logon, 1), dlat, dlon, 12, alt=delev)         # Rollen
        _add_pos(conn, cid, _shift(logon, 3), dlat, dlon, 80, alt=delev + 1200)  # Steigflug
        _add_pos(conn, cid, _shift(logon, 15), dlat + 0.2, dlon, 120, alt=4500)  # Reiseflug
        _add_pos(conn, cid, _shift(logon, 28), end_lat, end_lon, end_gs, alt=end_alt)  # Ende

    def test_sunk_when_vanished_airborne(self):
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        # Lädt am EDWG-Stapel, hebt ab, verschwindet über See (kein Touchdown) -> Logout in der Luft.
        self._flown_flight(conn, 300, "2026-07-01T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 300)
        assert f["loss_kind"] == "sunk" and f["loaded"] is False and f["tonnage_kg"] == 0.0
        assert p["lost_total_kg"] == 292.0 and p["total_kg"] == 0.0
        assert p["cargo"][0]["delivered_kg"] == 0.0      # Menge bleibt offen
        assert len(p["losses"]) == 1 and p["losses"][0]["loss_kind"] == "sunk"

    def test_stolen_when_landed_elsewhere(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        wlat, wlon = icao_to_coords("EDWY")                 # Norderney — nicht auf der Route
        self._flown_flight(conn, 301, "2026-07-01T18:05:00Z", end_lat=wlat, end_lon=wlon, end_gs=0)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 301)
        assert f["loss_kind"] == "stolen" and f["loaded"] is False
        assert p["lost_total_kg"] == 292.0 and p["total_kg"] == 0.0

    def test_returned_home_is_no_loss(self):
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        dlat, dlon = icao_to_coords("EDWG")
        self._flown_flight(conn, 302, "2026-07-01T18:05:00Z", end_lat=dlat, end_lon=dlon, end_gs=0, arrival="EDWG")
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 302)
        assert f["loss_kind"] == "returned"
        assert p["lost_total_kg"] == 0.0                    # zurückgebracht ≠ verloren

    def test_returned_at_route_waypoint_not_stolen(self):
        """Bug X (#15A): Logout an einem Strecken-Wegpunkt ≠ Abflugplatz ist 'returned'
        (kg-neutral), NICHT 'stolen'. Nur Plätze AUSSERHALB der Strecke werden geklaut."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, route="EDWG,EDXP,EDXH", destination="EDXH",
                    cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        xlat, xlon = icao_to_coords("EDXP")   # Wegpunkt: ≠ Abflug EDWG, ≠ Ziel EDXH
        self._flown_flight(conn, 310, "2026-07-01T18:05:00Z",
                           end_lat=xlat, end_lon=xlon, end_gs=0, arrival="EDXP")
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 310)
        assert f["loss_kind"] == "returned"
        assert p["lost_total_kg"] == 0.0                    # Wegpunkt-Rückgabe ≠ Verlust

    def test_loss_kg_is_net_event_cargo_not_full_payload(self):
        """Live-Fund 06.07.: die VERLORENE Menge ist die tatsächlich mitgeführte EVENT-Fracht
        (Σ der pro-Flug-gekappten Frachtart-Anteile = cargo_lines), NICHT die volle Musterzuladung.
        Szenario wie der Baltrum-Klau: 500 kg Musterzuladung, aber nur 120+40=160 kg passen als
        Event-Fracht an Bord (Pro-Flug-Kappung) → 160 kg verloren, nicht 500 (früher: Brutto)."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[
            {"name": "Sonnenschirme", "target_kg": 960.0, "per_flight_max_kg": 120.0, "departure": "EDWG"},
            {"name": "Strandkörbe", "target_kg": 400.0, "per_flight_max_kg": 40.0, "departure": "EDWG"},
        ])
        upsert_payload(conn, "C172", payload_kg=500)  # deutlich mehr als 120+40
        wlat, wlon = icao_to_coords("EDWY")           # Norderney — nicht auf der Route → stolen
        self._flown_flight(conn, 303, "2026-07-01T18:05:00Z", end_lat=wlat, end_lon=wlon, end_gs=0)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 303)
        assert f["loss_kind"] == "stolen"
        assert f["lost_kg"] == 160.0                        # Netto (120+40), NICHT die 500 Brutto
        assert p["lost_total_kg"] == 160.0
        lines = {l["name"]: l["kg"] for l in f["cargo_lines"]}
        assert lines == {"Sonnenschirme": 120.0, "Strandkörbe": 40.0}
        assert round(sum(l["kg"] for l in f["cargo_lines"]), 1) == f["lost_kg"]  # Summe konsistent

    def test_sunk_loss_kg_is_also_net(self):
        """Gegenprobe zum Klau-Fall: das Netto gilt genauso fürs Versenken (gleicher Code-Zweig)."""
        conn = _make_conn()
        ev = _event(conn, cargo=[
            {"name": "Sonnenschirme", "target_kg": 960.0, "per_flight_max_kg": 120.0, "departure": "EDWG"},
            {"name": "Strandkörbe", "target_kg": 400.0, "per_flight_max_kg": 40.0, "departure": "EDWG"},
        ])
        upsert_payload(conn, "C172", payload_kg=500)
        # abseits jedes Flugplatzes verschwunden (end_gs hoch, kein Touchdown) → sunk
        self._flown_flight(conn, 304, "2026-07-01T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 304)
        assert f["loss_kind"] == "sunk"
        assert f["lost_kg"] == 160.0 and p["lost_total_kg"] == 160.0

    # test_detection_is_idempotent_and_skips_delivered: ersatzlos gelöscht — detect_transport_losses
    # ist entfallen. Der Idempotenz-Begriff ist gegenstandslos: compute_transport_progress ist eine
    # reine Ableitung (kein Schreiben in transport_cargo_losses). Dass eine Landung am Ziel liefert
    # statt zu verlieren, deckt test_sunk_when_vanished_airborne / die Lieferungs-Tests ab.

    def test_no_track_no_loss(self):
        """Keine Position = keine Aussage: ein Flug ohne jeden GPS-Track (z. B. StatSim-
        rekonstruiert oder reine Flugplan-Zeile) gilt nicht als versunken — ohne erkannten
        Ladeplatz nimmt er nichts mit, also kann nichts verloren gehen."""
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        _add_flight(conn, 306, "EDWG", "EDWL", "C172", "2026-07-01T18:05:00Z", duration_min=25)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        assert p["losses"] == [] and p["lost_total_kg"] == 0.0

    def test_loss_shows_cargo_lines(self):
        """Die Verlust-Zeile zeigt, WAS über Bord ging — Co-Load-Verteilung wie bei
        einem beladenen Flug (Nutzer-Wunsch 02.07.: 'x Krabbenbrötchen, x Schafe |
        Kutter versunken')."""
        conn = _make_conn()
        ev = _event(conn, cargo=[
            {"name": "Filmrollen", "target_kg": 500.0, "per_flight_max_kg": 100.0, "departure": "EDWG"},
            {"name": "Friesentee", "target_kg": 500.0, "departure": "EDWG"},
        ])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        # Vorher liefert jemand — die Verlust-Aufschlüsselung zeigt trotzdem die VOLLE
        # Bordladung (Restkapazität ist egal: die Ladung ist weg, nicht im Manifest).
        from app.geo import icao_to_coords
        alat, alon = icao_to_coords("EDXH")
        self._flown_flight(conn, 308, "2026-07-01T17:30:00Z", end_lat=alat, end_lon=alon, end_gs=0)
        self._flown_flight(conn, 307, "2026-07-01T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 307)
        assert f["loss_kind"] == "sunk"
        lines = {l["name"]: l["kg"] for l in f["cargo_lines"]}
        assert lines == {"Filmrollen": 100.0, "Friesentee": 192.0}

    # -- #7/#8: Verlust netto gegen den Pool, verlorene Ware dauerhaft raus --------------------

    def test_stolen_capped_by_remaining_after_delivery(self):
        """#7: die verlorene Menge ist auf den zum dep_time noch offenen Rest (target − delivered)
        gedeckelt, NICHT auf das volle Frachtziel. Payload 300, Ziel 500: ein früherer Flug liefert
        300, ein späterer Klau kann nur die restlichen 200 mitgenommen haben (früher: 300 brutto)."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Krabben", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", payload_kg=300)
        alat, alon = icao_to_coords("EDXH")
        self._flown_flight(conn, 100, "2026-07-01T17:30:00Z", end_lat=alat, end_lon=alon, end_gs=0)  # liefert 300
        wlat, wlon = icao_to_coords("EDWY")
        self._flown_flight(conn, 101, "2026-07-01T18:05:00Z", end_lat=wlat, end_lon=wlon, end_gs=0)  # klaut den Rest
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        b = next(x for x in p["flights"] if x["cid"] == 101)
        assert b["loss_kind"] == "stolen"
        assert b["lost_kg"] == 200.0                 # netto Rest (500−300), NICHT 300 brutto
        assert p["cargo"][0]["delivered_kg"] == 300.0
        assert p["cargo"][0]["lost_kg"] == 200.0     # #7/#8: neues Feld je Frachtart

    def test_lost_cargo_removed_from_reservable_pool(self):
        """#8: nach einem Verlust ist die verlorene Ware für spätere Flüge NICHT mehr verfügbar
        (der Stapel ist leer). Ziel 500, 300 geliefert + 200 geklaut = Stapel leer → ein danach am
        Ladeplatz stehender offener Flug lädt 0 (vorher bot er die Ware erneut an)."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Krabben", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", payload_kg=300)
        alat, alon = icao_to_coords("EDXH")
        self._flown_flight(conn, 100, "2026-07-01T17:30:00Z", end_lat=alat, end_lon=alon, end_gs=0)
        wlat, wlon = icao_to_coords("EDWY")
        self._flown_flight(conn, 101, "2026-07-01T18:05:00Z", end_lat=wlat, end_lon=wlon, end_gs=0)
        _add_open_flight(conn, 102, "EDWG", "EDXH", "C172", "2026-07-01T18:30:00Z")
        glat, glon = icao_to_coords("EDWG")
        _set_live_pos(conn, 102, glat, glon, 0)      # steht am (nun leeren) EDWG-Stapel
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        cargo = p["cargo"][0]
        assert cargo["delivered_kg"] == 300.0 and cargo["lost_kg"] == 200.0
        assert p["reserved_total_kg"] == 0.0         # Stapel leer (300+200=500) → nichts mehr zu laden

    def test_returned_does_not_consume_pool(self):
        """'returned' (Ware heil an einem Streckenplatz abgestellt) verbraucht den Stapel NICHT —
        lost_kg=0, und ein späterer Flug, der dort steht, kann die Ware weiter voll aufnehmen."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        ev = _event(conn, cargo=[{"name": "Krabben", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", payload_kg=300)
        glat, glon = icao_to_coords("EDWG")          # Rückkehr an Streckenplatz EDWG (≠ Ziel) → returned
        self._flown_flight(conn, 100, "2026-07-01T17:30:00Z", end_lat=glat, end_lon=glon, end_gs=0)
        _add_open_flight(conn, 102, "EDWG", "EDXH", "C172", "2026-07-01T18:30:00Z")
        _set_live_pos(conn, 102, glat, glon, 0)      # steht am EDWG-Stapel (Ware wieder da)
        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        r = next(x for x in p["flights"] if x["cid"] == 100)
        assert r["loss_kind"] == "returned"
        assert p["cargo"][0]["lost_kg"] == 0.0       # kein Verlust
        o = next(x for x in p["flights"] if x["cid"] == 102)
        assert o["reserved_kg"] == 300.0             # voller Payload wieder aufgenommen

    def test_no_loss_for_flight_after_event_window(self):
        """Ein Streckenflug lange nach dtend darf keinem alten Event als Verlust angelastet
        werden (Final-Review-Blocker: Alt-Events sammelten sonst fortlaufend Fremd-Verluste)."""
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        # dtend = 2026-07-01T23:00:00Z — dieser Flug liegt einen Tag danach.
        self._flown_flight(conn, 305, "2026-07-03T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=95)
        p = compute_transport_progress(conn, ev, "2026-07-03T20:00:00Z")
        assert p["losses"] == [] and p["lost_total_kg"] == 0.0

    def test_plan_only_fallback_arrival_is_not_a_delivery(self):
        """#23 Review C2: Ein reiner Flugplan-Eintrag (arrival=dest im Flugplan, aber KEIN
        einziger GPS-Track) darf NIE als Lieferung zählen — die Fallback-Leg-Zeile ohne Track ist
        kein Kutter-Flug (Entscheidung 8), und mangels Beweis auch kein Verlust."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn)  # route=EDWG,EDXH, destination=EDXH
        # Reine Connection OHNE jede Position -- canonicalize_legs fällt auf
        # _flightrow_as_flight zurück (gps_arrival=None), arrival kommt nur aus dem Plan.
        _add_flight(conn, 700, "EDWG", "EDXH", "C172", "2026-07-01T18:00:00Z", duration_min=30)

        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        # Ohne jeden Track ist die Fallback-Zeile gar kein Kutter-Flug (Entscheidung 8) — sie
        # taucht nicht im Feed auf und zählt nichts.
        assert _feed_by_callsign(p, "FRS700") is None
        assert p["total_kg"] == 0.0
        # Ohne Track auch kein Verlust — 'arr == dest' aus dem Plan wertet nichts als geliefert.
        assert p["losses"] == [] and p["lost_total_kg"] == 0.0

    # test_later_reconnect_latch_does_not_hide_earlier_sunk_loss: ersatzlos gelöscht — der Latch und
    # die connectionsweite Latch-Kopplung (detect_transport_losses) sind entfallen. Im Stapel-Modell
    # ist jede Session eigenständig: der frühere Sunk steht in `movements`, eine spätere Reconnect-
    # Session kann ihn gar nicht mehr verdecken. (Der Sunk-Fall selbst: test_sunk_when_vanished_airborne.)

    # test_position_classified_at_destination_is_not_stolen: ersatzlos gelöscht — die eigene
    # Positions-Klassifikation von detect_transport_losses (nearest_airport_icao + _LANDED_MAX_GS_KT)
    # ist entfallen. Ob am Ziel geliefert wurde, entscheidet jetzt allein der GPS-Leg-Detektor
    # (Landung am Ziel = Lieferung), es gibt keine zweite, patchbare Klassifikation mehr.


# --- GPS-Flüge + Latch-/Loss-Reconcile über das Connection-Intervall (#23 Task 10) ----------
#
# canonicalize_legs liefert je Flug den GPS-Takeoff als `logon_time` (Flug-Identität/flight_key)
# — der Poller latcht Live-Ankünfte aber weiterhin unter dem VERBINDUNGS-Logon (`flights.logon_time`,
# der Session-Start, meist ein paar Minuten VOR dem Takeoff wegen Taxi-Zeit). Diese Tests bauen
# echte, per Höhe/Groundspeed erkennbare Tracks (Muster wie tests/test_canonicalize_legs.py) statt
# der alten 2-3-Punkt-Tracks, die unter GPS-only keine Landung ergeben (s. Task-Brief #23).

class TestGPSLegReconcile:
    def _seed_leg(self, conn, cid, callsign, t0, dep_icao, *, arr_landing=True):
        """Ein reales, GPS-erkennbares Leg ab ``dep_icao`` (Taxi 0–1 min, Steigflug über die
        500-ft-AGL-Schwelle bei ``t0+4min`` — GPS-Takeoff). Ohne Endpunkt hier: Aufrufer hängt
        Reiseflug/Landung selbst an (Verkettung für Mehrbein-Connections)."""
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords(dep_icao)
        delev = airport_elevation_ft(dep_icao) or 0
        _add_pos(conn, cid, t0, dlat, dlon, 0, alt=delev, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 1), dlat, dlon, 12, alt=delev, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 4), dlat, dlon, 80, alt=delev + 1200, callsign=callsign)  # Takeoff

    def _add_leg_landing(self, conn, cid, callsign, t0, arr_icao, *, cruise_min=18, gs=0, alt=None):
        """Reiseflug + Landeanflug + Touchdown an ``arr_icao`` (relativ zum Leg-``t0``, s.
        ``_seed_leg``). Gibt den Touchdown-``ts`` zurück (für Verkettung)."""
        from app.geo import icao_to_coords, airport_elevation_ft
        alat, alon = icao_to_coords(arr_icao)
        aelev = airport_elevation_ft(arr_icao) or 0
        if alt is None:
            alt = aelev
        _add_pos(conn, cid, _shift(t0, cruise_min), 54.0, 7.9, 120, alt=4000, callsign=callsign)
        landing_ts = _shift(t0, cruise_min + 20)
        _add_pos(conn, cid, _shift(t0, cruise_min + 18), alat, alon, 40, alt=500, callsign=callsign)
        _add_pos(conn, cid, landing_ts, alat, alon, gs, alt=alt, callsign=callsign)
        return landing_ts

    def _insert_connection(self, conn, cid, callsign, dep, arr, logon, logoff, *, duration_min=60):
        conn.execute(
            "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
            (cid, f"Pilot{cid}", START),
        )
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
            "logon_time, logoff_time, duration_min, distance_nm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, callsign, "C172", dep, arr, logon, logoff, duration_min, 20.0),
        )
        conn.commit()

    # Der Live-Ankunfts-Latch und seine Connection-Intervall-Reconcile sind entfallen. Die Fälle,
    # deren EINZIGER Zweck die Latch-/`arrived`-Demotion war, wurden ersatzlos gelöscht:
    #   test_second_delivery_run_shows_enroute_not_arrived  (Status „angekommen" gibt es nicht mehr)
    #   test_new_leg_after_completed_return_not_shown_as_returning  (Status „returning" heißt jetzt „dabei")
    #   test_new_leg_after_delivery_not_stuck_on_arrived  (Latch ans Leg binden — kein Latch mehr)
    #   test_stale_incomplete_open_leg_does_not_keep_arrived  (Leg-Auswahl für die Latch-Demotion)
    # Was bleibt, sind die Aussagen über ECHTES GPS-Verhalten (Doppelzählung, Ziel-Membership,
    # Verlust nur einmal anheften) — hier ohne Latch, mit den GPS-Tracks als alleinigem Beweis.

    def test_gps_takeoff_is_the_feed_key(self):
        """Die Feed-Zeile trägt den GPS-Takeoff (10:02) als dep_time, nicht den Verbindungs-Logon
        (09:58, Taxi-Zeit davor). Die Landung am Ziel EDXH liefert selbst — ohne Latch, ohne dass
        EDXH auf der (bewusst auf EDWG verengten) Route liegen müsste."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        conn_logon = "2026-07-01T09:58:00Z"
        ev = _event(conn, route="EDWG", destination="EDXH",
                    cargo=[{"name": "Fracht", "target_kg": 500, "departure": "EDWG"}])
        self._insert_connection(conn, 500, "FRS500", "EDWG", "EDXH", conn_logon,
                                _shift(conn_logon, 44), duration_min=44)
        self._seed_leg(conn, 500, "FRS500", conn_logon, "EDWG")
        landing_ts = self._add_leg_landing(conn, 500, "FRS500", conn_logon, "EDXH", cruise_min=22)
        conn.commit()
        assert landing_ts == "2026-07-01T10:40:00Z"

        p = compute_transport_progress(conn, ev, "2026-07-01T11:00:00Z")
        f = _feed_by_callsign(p, "FRS500")
        assert f is not None
        assert f["dep_time"] == "2026-07-01T10:02:00Z"  # GPS-Takeoff, NICHT der Verbindungs-Logon
        assert f["loaded"] is True
        assert p["total_kg"] == 250

    def test_return_leg_not_double_counted(self):
        """Eine Mehrbein-Connection (Hin EDWG→EDXH landet am Ziel, Rück EDXH→EDWG): NUR das
        Hin-Bein ist beladen. Ein GPS-belegtes, vom Ziel abweichendes Ankunfts-Bein liefert nie
        (sonst zählte die Fracht doppelt)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, cargo=[{"name": "Fracht", "target_kg": 500, "departure": "EDWG"}])
        conn_logon = "2026-07-01T09:58:00Z"
        conn_logoff = "2026-07-01T11:35:00Z"
        self._insert_connection(conn, 501, "FRS501", "EDWG", "EDWG", conn_logon, conn_logoff,
                                duration_min=97)
        from app.geo import icao_to_coords
        # Hin: EDWG -> EDXH (liefert am Ziel)
        self._seed_leg(conn, 501, "FRS501", conn_logon, "EDWG")
        hin_landing = self._add_leg_landing(conn, 501, "FRS501", conn_logon, "EDXH")
        # Turnaround in EDXH (kurzer Boden-Aufenthalt, dann erneut abheben)
        hlat, hlon = icao_to_coords("EDXH")
        _add_pos(conn, 501, _shift(hin_landing, 3), hlat, hlon, 5, alt=8, callsign="FRS501")
        # Rück: EDXH -> EDWG (leer)
        self._seed_leg(conn, 501, "FRS501", _shift(hin_landing, 6), "EDXH")
        self._add_leg_landing(conn, 501, "FRS501", _shift(hin_landing, 6), "EDWG")
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T12:00:00Z")
        legs = [f for f in p["flights"] if f["cid"] == 501]
        assert len(legs) == 2
        hin = next(f for f in legs if f["arr"] == "EDXH")
        rueck = next(f for f in legs if f["arr"] == "EDWG")
        assert hin["loaded"] is True
        assert rueck["loaded"] is False and rueck["tonnage_kg"] == 0.0
        assert p["total_kg"] == 250  # nur einmal gezählt, nicht doppelt

    def test_landing_off_destination_delivers_nothing(self):
        """Landung neben dem Ziel (ein bekannter, aber streckenfremder Flughafen) liefert 0 kg:
        nur die Landung AM ZIEL liefert. Wer die Fracht anderswo abstellt, hat sie nicht geliefert —
        beim Logout am fremden Platz ist sie geklaut."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, cargo=[{"name": "Fracht", "target_kg": 500, "departure": "EDWG"}])
        logon = "2026-07-01T09:58:00Z"
        self._insert_connection(conn, 502, "FRS502", "EDWG", "EDDH", logon,
                                _shift(logon, 60), duration_min=60)
        self._seed_leg(conn, 502, "FRS502", logon, "EDWG")
        self._add_leg_landing(conn, 502, "FRS502", logon, "EDDH")  # Hamburg -- nicht auf der Strecke
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T11:30:00Z")
        f = _feed_by_callsign(p, "FRS502")
        assert f is not None and f["loaded"] is False        # gelandet, aber NICHT geliefert
        assert p["total_kg"] == 0
        assert f["loss_kind"] == "stolen"                    # am fremden EDDH ausgeloggt -> geklaut

    def test_open_connection_after_gps_landing_not_double_counted(self):
        """#23 Review C1: Ein Pilot landet GPS-belegt am Ziel, bleibt aber verbunden
        (flights.logoff_time NULL). Es entsteht GENAU EINE gelieferte Feed-Zeile (das gelandete
        Leg) — der Offen-Zweig fügt keine zweite hinzu, weil nach der Lieferung nichts mehr an
        Bord ist."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, cargo=[{"name": "Fracht", "target_kg": 500, "departure": "EDWG"}])
        logon = "2026-07-01T09:58:00Z"
        _add_open_flight(conn, 600, "EDWG", "", "C172", logon, callsign="FRS600")
        self._seed_leg(conn, 600, "FRS600", logon, "EDWG")
        self._add_leg_landing(conn, 600, "FRS600", logon, "EDXH")
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T11:00:00Z")
        legs = [f for f in p["flights"] if f["cid"] == 600]
        assert len(legs) == 1                 # nicht die geschlossene UND die offene Zeile
        assert legs[0]["loaded"] is True
        assert p["total_kg"] == 250            # genau einmal, nicht doppelt (500)

    def test_open_connection_intermediate_leg_keeps_in_air_reservation(self):
        """Eine offene Weiterreise nach einer Zwischenlandung bleibt als Reservierung sichtbar:
        der Pilot lädt am EDWG-Stapel, landet zwischendurch (nicht am Ziel, Ware bleibt an Bord),
        hebt wieder ab — die Bordladung (Reservierung) geht nicht verloren."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, route="EDWG,EDWY,EDXH", destination="EDXH",
                    cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        t0 = "2026-07-01T09:58:00Z"
        _add_open_flight(conn, 601, "EDWG", "", "C172", t0, callsign="FRS601")
        # Bein 1: EDWG -> EDWY, geschlossen gelandet (echte Zwischenlandung, kein Ziel).
        self._seed_leg(conn, 601, "FRS601", t0, "EDWG")
        landing_ts = self._add_leg_landing(conn, 601, "FRS601", t0, "EDWY", cruise_min=18)
        # Bein 2: erneuter Start ab EDWY, noch in der Luft (kein Touchdown vor `now`).
        t1 = _shift(landing_ts, 5)
        self._seed_leg(conn, 601, "FRS601", t1, "EDWY")
        conn.commit()

        p = compute_transport_progress(conn, ev, _shift(t1, 10))
        legs = [f for f in p["flights"] if f["cid"] == 601]
        # Die offene Weiterreise trägt die Ware weiter (Reservierung), nichts geliefert/verloren.
        underway = next(f for f in legs if f["in_air"])
        assert underway["airborne"] is True and underway["loaded"] is False
        assert underway["reserved_kg"] == 250.0
        assert p["reserved_total_kg"] == 250.0 and p["total_kg"] == 0.0

    def test_intermediate_landing_parked_keeps_reservation(self):
        """Zwischenlandung an einem Wegpunkt (Verbindung offen, danach GEPARKT, kein zweiter
        Start): der Pilot trägt seine am EDWG geladene Ware weiter — sie bleibt reserviert, nichts
        geliefert/verloren, bis er weiterfliegt oder ausloggt."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, route="EDWG,EDWY,EDXH", destination="EDXH",
                    cargo=[{"name": "Inselpost", "target_kg": 500.0, "departure": "EDWG"}])
        from app.geo import icao_to_coords, airport_elevation_ft
        t0 = "2026-07-01T09:58:00Z"
        _add_open_flight(conn, 610, "EDWG", "EDXH", "C172", t0, callsign="FRS610")
        self._seed_leg(conn, 610, "FRS610", t0, "EDWG")
        landing_ts = self._add_leg_landing(conn, 610, "FRS610", t0, "EDWY", cruise_min=18)
        wlat, wlon = icao_to_coords("EDWY")
        welev = airport_elevation_ft("EDWY") or 0
        # Geparkt am Wegpunkt (gs 0), noch verbunden — kein zweiter Start.
        _add_pos(conn, 610, _shift(landing_ts, 5), wlat, wlon, 0, alt=welev, callsign="FRS610")
        conn.commit()

        p = compute_transport_progress(conn, ev, _shift(landing_ts, 15))
        legs = [f for f in p["flights"] if f["cid"] == 610]
        # Die (offene) Reservierungs-Zeile trägt die volle Bordladung, geparkt am Wegpunkt.
        res = next(f for f in legs if f["in_air"])
        assert res["loaded"] is False and res["reserved_kg"] == 250.0
        assert res["airborne"] is False                # geparkt am Wegpunkt (gs 0)
        assert p["reserved_total_kg"] == 250.0 and p["total_kg"] == 0.0

    def test_multi_leg_loss_attached_once(self):
        """Eine Mehrbein-Connection mit ZWEI nicht gelieferten Beinen (keins am Ziel) und einem
        Logout am fremden Platz: der Verlust wird nur EINMAL angeheftet — lost_total ist die
        einmalige Bordladung (250), nicht das Doppelte."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, route="EDWG,EDWY,EDXH", destination="EDXH",
                    cargo=[{"name": "Fracht", "target_kg": 500, "departure": "EDWG"}])
        conn_logon = "2026-07-01T09:58:00Z"
        conn_logoff = "2026-07-01T11:35:00Z"
        self._insert_connection(conn, 1000, "FRS1000", "EDWG", "EDDH", conn_logon, conn_logoff,
                                duration_min=97)
        from app.geo import icao_to_coords
        # Bein 1: EDWG -> EDWY (Zwischenlandung auf der Strecke, nicht das Ziel).
        self._seed_leg(conn, 1000, "FRS1000", conn_logon, "EDWG")
        hin_landing = self._add_leg_landing(conn, 1000, "FRS1000", conn_logon, "EDWY")
        wlat, wlon = icao_to_coords("EDWY")
        _add_pos(conn, 1000, _shift(hin_landing, 3), wlat, wlon, 5, alt=8, callsign="FRS1000")
        # Bein 2: EDWY -> EDDH (fremder Platz, nicht das Ziel). Logout dort -> gestohlen.
        self._seed_leg(conn, 1000, "FRS1000", _shift(hin_landing, 6), "EDWY")
        self._add_leg_landing(conn, 1000, "FRS1000", _shift(hin_landing, 6), "EDDH")
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T12:30:00Z")
        legs = [f for f in p["flights"] if f["cid"] == 1000]
        assert len(legs) == 2                                    # beide Beine sichtbar
        assert sum(1 for f in legs if f.get("loss_kind")) == 1   # nur EINE Zeile trägt den Verlust
        assert p["lost_total_kg"] == 250    # nicht 500 (doppelt angeheftet)


class TestParticipants:
    def _takeoff_leg(self, conn, cid, dep, t0, callsign):
        """Ein abgehobenes GPS-Leg (Takeoff, keine Landung) — der Pilot ist danach in der Luft."""
        from app.geo import icao_to_coords, airport_elevation_ft
        la, lo = icao_to_coords(dep)
        ea = airport_elevation_ft(dep) or 0
        _add_pos(conn, cid, t0, la, lo, 0, alt=ea, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 1), la, lo, 12, alt=ea, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 4), la, lo, 80, alt=ea + 1200, callsign=callsign)

    def test_statuses_and_sums(self):
        """Die Status-Werte des Stapel-Modells: 'dabei' (leer, ausgeloggt/unterwegs), 'loaded'
        (steht beladen am Ladeplatz), 'flying' (trägt Ware in der Luft)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)  # 292
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0, "departure": "EDWG"}])
        from app.geo import icao_to_coords
        la, lo = icao_to_coords("EDWG")
        # Pilot 400: liefert (geschlossen am Ziel), loggt danach aus -> delivered 292, leer -> 'dabei'.
        _add_delivered_flight(conn, 400, "EDWG", "C172", "2026-07-01T18:00:00Z", ev["id"], duration_min=25)
        # Pilot 401: steht beladen am Ladeplatz EDWG (Live-Position) -> 'loaded', reserviert 292.
        _add_open_flight(conn, 401, "EDWG", "EDXH", "C172", "2026-07-01T19:05:00Z")
        _set_live_pos(conn, 401, la, lo, 0)
        # Pilot 402: hat am EDWG geladen und ist jetzt in der Luft -> 'flying', reserviert 292.
        _add_open_flight(conn, 402, "EDWG", "EDXH", "C172", "2026-07-01T19:06:00Z")
        self._takeoff_leg(conn, 402, "EDWG", "2026-07-01T19:06:00Z", "FRS402")
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[400]["status"] == "dabei" and parts[400]["delivered_kg"] == 292.0
        assert parts[400]["reserved_kg"] == 0.0 and parts[400]["callsign"] == "FRS400"
        assert parts[401]["status"] == "loaded" and parts[401]["reserved_kg"] == 292.0
        assert parts[401]["callsign"] == "FRS401" and parts[401]["aircraft"] == "C172"
        assert parts[402]["status"] == "flying" and parts[402]["reserved_kg"] == 292.0
        assert p["total_kg"] == 292.0 and p["reserved_total_kg"] == 584.0  # zwei tragen je 292

    def test_returning_pilot_at_pickup_shows_loading_not_returning(self):
        # #65 + #5 (GPS-only Boden-Beladung): eine als "Rückflug" erkannte Verbindung bleibt oft
        # OHNE Disconnect offen. Steht der Pilot am Boden an einem ABHOLPLATZ (hier EDWG), lädt er
        # dort vom Stapel (bereit für die nächste Runde) — die aktuelle GPS-Position gewinnt. Der
        # ursprüngliche #65-Bug ("hängt ewig als returning") bleibt behoben: 'returning' gibt es
        # nicht mehr; er ist ein normaler ladender Flug am Abholplatz.
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0, "departure": "EDWG"}])
        _add_open_flight(conn, 401, "EDXH", "EDWG", "C172", "2026-07-01T19:05:00Z")
        # Live-Position: am Boden (gs < 2kt) bei EDWG (Abholplatz).
        conn.execute(
            "INSERT INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
            "VALUES (401, 'FRS401', 53.78278, 7.91389, 0)"
        )
        conn.commit()
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[401]["status"] == "loaded"     # lädt am Abholplatz, NICHT „returning"
        # #5: als ladend am Abholplatz sichtbar (aktuelle Position EDWG gewinnt, nicht Plan-EDXH).
        f = _feed_by_callsign(p, "FRS401")
        assert f is not None
        assert f["dep"] == "EDWG"
        assert f["airborne"] is False
        assert f["loaded"] is False

    def test_returning_pilot_still_shown_while_still_airborne(self):
        # Der frühere „returning"-Status heißt jetzt 'dabei' und bleibt sichtbar: leer in der Luft,
        # zuletzt am teilnehmenden Platz EDXH abgehoben (Entscheidung 14).
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0, "departure": "EDWG"}])
        _add_open_flight(conn, 401, "EDXH", "EDWG", "C172", "2026-07-01T19:05:00Z")
        # Leer ab EDXH (Ziel, teilnehmend) abgehoben, noch in der Luft (kein Touchdown).
        self._takeoff_leg(conn, 401, "EDXH", "2026-07-01T19:05:00Z", "FRS401")
        conn.execute(
            "INSERT INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
            "VALUES (401, 'FRS401', 53.75, 7.87, 110)"
        )
        conn.commit()
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[401]["status"] == "dabei" and parts[401]["visible"] is True

    def test_delivered_pilot_has_no_arrived_status(self):
        """`arrived` ist entfallen (Task 10): eine Lieferung ist eine Tatsache im Balken, kein
        Zustand. Ein Pilot, der geliefert hat und ausgeloggt ist, zählt seine 292 kg — sein Status
        ist NICHT mehr „angekommen"."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0, "departure": "EDWG"}])
        _add_delivered_flight(conn, 402, "EDWG", "C172", "2026-07-01T18:05:00Z", ev["id"])
        p = compute_transport_progress(conn, ev, "2026-07-01T19:00:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[402]["delivered_kg"] == 292.0
        assert parts[402]["status"] != "arrived"
        assert not any(x["status"] == "arrived" for x in p["participants"])

    def test_aircraft_normalized_to_type_code(self):
        # Rohes ICAO-Flugplanfeld (Typ + Ausrüstungssuffix) muss als reiner Typcode erscheinen —
        # sonst steht in Live-Tabelle und Forum-Badge z. B. "AS65/L-SDGY/S" statt "AS65".
        conn = _make_conn()
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        _add_flight(conn, 403, "EDWG", "EDXH", "AS65/L-SDGY/S", "2026-07-01T18:00:00Z", duration_min=25)
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        assert {x["cid"]: x for x in p["participants"]}[403]["aircraft"] == "AS65"


class TestLossQuipContext:
    def test_flight_context_carries_kutter_versunken(self):
        f = {"cid": 1, "name": "Klaus Test", "callsign": "FRS22", "dep": "EDWG", "arr": "—",
             "loaded": False, "loss_kind": "sunk", "lost_kg": 292.0,
             "distance_nm": 0, "block_min": 0, "cargo_lines": []}
        ctx = flight_quip_context(f, {"flights": [f]})
        assert "Kutter versunken" in ctx["verlust"]

    def test_loss_context_tonnage_matches_carried_cargo_not_zero(self):
        # #67 (Live-Fund 06.07.): tonnage_kg ist bei einem Verlust IMMER 0 (netto nichts
        # geliefert) -- die Zuladung im Spruch-Kontext muss trotzdem die tatsächlich an Bord
        # gewesene Fracht zeigen (aus cargo_lines), sonst widerspricht sich der Spruch selbst
        # ("220 kg Sonnenschirme/Krabbenbrötchen an Bord ... Zuladung 0 Kilo").
        f = {"cid": 1, "name": "Tobias", "callsign": "FRS49", "dep": "EDWG", "arr": "EDWL",
             "loaded": False, "tonnage_kg": 0.0, "loss_kind": "stolen", "lost_kg": 290.0,
             "distance_nm": 0, "block_min": 0,
             "cargo_lines": [{"name": "Sonnenschirme", "emoji": "⛱️", "kg": 120.0},
                             {"name": "Krabbenbrötchen", "emoji": "🦐", "kg": 100.0}]}
        ctx = flight_quip_context(f, {"flights": [f]})
        assert ctx["tonnage_kg"] == 220     # Summe der Bordladung, NICHT 0
        assert "⛱️ Sonnenschirme" in ctx["cargo"][0]

    def test_summary_context_lists_losses(self):
        prog = {"flights": [], "cargo": [], "route": ["EDWG", "EDXH"], "destination": "EDXH",
                "total_kg": 0, "loaded_count": 0, "lost_total_kg": 292.0,
                "losses": [{"name": "Klaus Test", "callsign": "FRS22", "loss_kind": "sunk",
                            "lost_kg": 292.0, "cid": 1}]}
        ctx = event_summary_context({"name": "Test"}, prog)
        assert ctx["lost_total_kg"] == 292.0 and any("Kutter versunken" in v for v in ctx["verluste"])

    def test_summary_context_pickups_exclude_destination(self):
        # #12/Live-Fund: keine irreführende Routen-Kette mehr — Ziel als Anker, Abholplätze (Route
        # ohne Ziel) getrennt, damit die KI keine „Runde A-B-C-D" erfindet.
        prog = {"flights": [], "cargo": [], "route": ["EDWG", "EDWL", "EDXH", "EDXP"],
                "destination": "EDWG", "total_kg": 0, "loaded_count": 0}
        ctx = event_summary_context({"name": "Test"}, prog)
        assert ctx["destination"] == "EDWG"
        assert ctx["pickups"] == ["EDWL", "EDXH", "EDXP"]   # Ziel NICHT in den Abholplätzen
        assert "route" not in ctx                            # keine Ketten-Route mehr im Kontext


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

    def test_team_kg_with_target(self):
        # #64 (v8.8.1): Badge zeigt die Gesamt-Tonnage des TEAMS, nicht nur des Piloten.
        from app.badge import _fmt_team_kg
        assert _fmt_team_kg(1610.0, 2810.0) == "1610 / 2810 kg Team"

    def test_team_kg_without_target(self):
        from app.badge import _fmt_team_kg
        assert _fmt_team_kg(950.0, None) == "950 kg Team"

    def test_team_kg_missing_defaults_to_zero(self):
        from app.badge import _fmt_team_kg
        assert _fmt_team_kg(None, None) == "0 kg Team"

    def test_render_returns_png_without_loss(self):
        from app.badge import render_kutter_badge
        png = render_kutter_badge({
            "callsign": "FRS49", "name": "Tobias", "aircraft": "C172",
            "delivered_kg": 292, "stolen_kg": 0, "sunk_kg": 0,
            "team_total_kg": 1610.0, "team_target_kg": 2810.0,
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

    def test_ascii_fold_umlauts(self):
        # Der Pillow-Default-Font kann keine Umlaute — vor dem Zeichnen nach ASCII falten.
        from app.badge import _ascii
        assert _ascii("Jörg über Sylt") == "Joerg ueber Sylt"
        assert _ascii("Größe Straße Öl") == "Groesse Strasse Oel"
        assert _ascii("Café résumé") == "Cafe resume"
        assert _ascii("") == "" and _ascii(None) == ""

    def test_render_with_umlaut_event(self):
        from app.badge import render_kutter_badge
        png = render_kutter_badge({
            "callsign": "FRS49", "aircraft": "PA24", "delivered_kg": 200,
            "event": "Material für die Offshore-Anlagen", "date": "02.07.2026",
        })
        assert png[:8] == _PNG_MAGIC


class TestKutterCreateValidation:
    """#84: Manuelles Event verlangt Ziel + Manifest mit Startplätzen; Route wird abgeleitet."""
    SECRET = "s3cr3t"
    PW = "test-admin-pw"

    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "kutter_val.db")
        init_db(p)
        monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=self.SECRET, ADMIN_PASSWORD=self.PW,
            VAPID_PRIVATE_KEY="vapid", VAPID_CONTACT_EMAIL="mailto:test"))
        return TestClient(main.app), p

    def _post(self, client, body):
        client.cookies.update({ADMIN_COOKIE: make_admin_token(self.SECRET, self.PW)})
        return client.post("/api/admin/transport/events", json=body)

    def test_requires_destination(self, tmp_path, monkeypatch):
        client, _ = self._app(tmp_path, monkeypatch)
        r = self._post(client, {"dtstart": START,
                                "cargo": [{"name": "A", "target_kg": 100, "departure": "EDWG"}]})
        assert r.status_code == 400

    def test_requires_cargo(self, tmp_path, monkeypatch):
        client, _ = self._app(tmp_path, monkeypatch)
        r = self._post(client, {"dtstart": START, "destination": "EDXH", "cargo": []})
        assert r.status_code == 400

    def test_requires_start_place_per_cargo(self, tmp_path, monkeypatch):
        client, _ = self._app(tmp_path, monkeypatch)
        r = self._post(client, {"dtstart": START, "destination": "EDXH",
                                "cargo": [{"name": "A", "target_kg": 100}]})  # kein Startplatz
        assert r.status_code == 400

    def test_rejects_multiple_destinations(self, tmp_path, monkeypatch):
        client, _ = self._app(tmp_path, monkeypatch)
        r = self._post(client, {"dtstart": START, "destination": "EDXH, EDWY",  # zwei Ziele
                                "cargo": [{"name": "A", "target_kg": 100, "departure": "EDWG"}]})
        assert r.status_code == 400

    def test_valid_create_derives_route(self, tmp_path, monkeypatch):
        client, dbp = self._app(tmp_path, monkeypatch)
        r = self._post(client, {"dtstart": START, "destination": "EDXH",
                                "cargo": [{"name": "Äpfel", "target_kg": 500, "departure": "EDWG"}]})
        assert r.status_code == 200
        conn = get_connection(dbp)
        ev = get_transport_event(conn, r.json()["id"])
        conn.close()
        assert set(ev["route"].split(",")) == {"EDWG", "EDXH"}

    def test_airports_check_endpoint(self, tmp_path, monkeypatch):
        # #77: unbekannte ICAOs werden gemeldet, bekannte nicht.
        client, _ = self._app(tmp_path, monkeypatch)
        r = client.get("/api/airports/check?codes=EDWG, edxh, EDZZ")
        assert r.status_code == 200
        unknown = r.json()["unknown"]
        assert "EDZZ" in unknown and "EDWG" not in unknown and "EDXH" not in unknown

    def test_airports_search_endpoint(self, tmp_path, monkeypatch):
        # #77-Erweiterung: Präfix-Suche fürs Autocomplete.
        client, _ = self._app(tmp_path, monkeypatch)
        r = client.get("/api/airports/search?q=edw")
        assert r.status_code == 200
        codes = [x["icao"] for x in r.json()["results"]]
        assert "EDWG" in codes and all(c.startswith("EDW") for c in codes)
        assert client.get("/api/airports/search?q=").json()["results"] == []


class TestKutterBadgeEndpoints:
    """Integrationstests der Badge-Endpoints (Muster: tests/test_admin_api.py -- Fake-Settings +
    Admin-Cookie via make_admin_token). TestClient ohne `with`-Block, damit `lifespan` (Poller-
    Start) NICHT anläuft (kein Netzwerkzugriff waehrend der Tests)."""

    SECRET = "s3cr3t"
    PW = "test-admin-pw"

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

    def test_badge_data_includes_team_total(self, tmp_path, monkeypatch):
        # #64 (v8.8.1): das Badge feiert die TEAM-Leistung, nicht nur den eigenen Anteil.
        ev = {"name": "Test", "dtstart": "2026-07-01T18:00:00Z"}
        progress = {
            "participants": [{"cid": 500, "callsign": "FRS500", "aircraft": "C172", "delivered_kg": 250.0}],
            "losses": [],
            "total_kg": 1610.0,
            "target_kg": 2810.0,
        }
        d = main._kutter_badge_data(progress, ev, 500)
        assert d["delivered_kg"] == 250.0       # eigener Anteil bleibt erhalten
        assert d["team_total_kg"] == 1610.0     # Gesamt-Team-Leistung neu dazu
        assert d["team_target_kg"] == 2810.0

    def test_admin_endpoint_requires_auth(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        ev = self._seeded_event(db)
        res = client.get(f"/api/admin/transport/events/{ev['id']}/badge/500.png")
        assert res.status_code == 401


class TestTransportPushEnabled:
    """set_transport_push_enabled (DB) + POST /api/admin/transport/events/{id}/push --
    Analogon zu set_bummel_push_enabled / admin_toggle_push."""

    SECRET = "s3cr3t"
    PW = "test-admin-pw"

    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "kutter_push.db")
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

    def test_set_push_enabled_roundtrip(self):
        conn = _make_conn()
        ev = _event(conn)
        assert ev["push_enabled"] == 1  # Default an

        set_transport_push_enabled(conn, ev["id"], False)
        conn.commit()
        assert get_transport_event(conn, ev["id"])["push_enabled"] == 0

        set_transport_push_enabled(conn, ev["id"], True)
        conn.commit()
        assert get_transport_event(conn, ev["id"])["push_enabled"] == 1

    def test_toggle_push_endpoint_disable(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        ev = _event(conn)
        conn.commit()
        conn.close()
        client.cookies.update(self._admin_cookies())

        res = client.post(f"/api/admin/transport/events/{ev['id']}/push", json={"enabled": False})
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

        conn = get_connection(db)
        assert get_transport_event(conn, ev["id"])["push_enabled"] == 0
        conn.close()

    def test_toggle_push_endpoint_enable(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        ev = _event(conn)
        set_transport_push_enabled(conn, ev["id"], False)
        conn.commit()
        conn.close()
        client.cookies.update(self._admin_cookies())

        res = client.post(f"/api/admin/transport/events/{ev['id']}/push", json={"enabled": True})
        assert res.status_code == 200

        conn = get_connection(db)
        assert get_transport_event(conn, ev["id"])["push_enabled"] == 1
        conn.close()

    def test_toggle_push_endpoint_requires_auth(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        ev = _event(conn)
        conn.commit()
        conn.close()

        res = client.post(f"/api/admin/transport/events/{ev['id']}/push", json={"enabled": False})
        assert res.status_code == 401


# --- Status-Flags (Task 3, #25) --------------------------------------------

def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestTransportStatus:
    """_transport_status (Analogon _race_status, main.py:844) + status-Feld in
    GET /api/admin/transport/events (main.py:1656)."""

    SECRET = "s3cr3t"
    PW = "test-admin-pw"

    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "kutter_status.db")
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

    def test_scheduled_before_dtstart(self):
        assert main._transport_status({"dtstart": START, "dtend": END}, "2026-07-01T08:00:00Z") == "scheduled"

    def test_running_between_dtstart_and_dtend(self):
        assert main._transport_status({"dtstart": START, "dtend": END}, "2026-07-01T12:00:00Z") == "running"

    def test_waiting_after_dtend_without_summary(self):
        assert main._transport_status({"dtstart": START, "dtend": END}, "2026-07-02T00:00:00Z") == "waiting"

    def test_done_overrides_when_summarized_even_before_dtstart(self):
        ev = {"dtstart": START, "dtend": END, "summarized_at": "2026-07-01T23:05:00Z"}
        assert main._transport_status(ev, "2026-07-01T00:00:00Z") == "done"

    def test_endpoint_returns_status_per_event(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        conn = get_connection(db)
        now = datetime.now(timezone.utc)
        scheduled_id = create_transport_event(
            conn, name="Geplant", route="EDWG,EDXH", destination="EDXH",
            dtstart=_iso(now + timedelta(hours=2)), dtend=_iso(now + timedelta(hours=4)),
        )
        running_id = create_transport_event(
            conn, name="Laeuft", route="EDWG,EDXH", destination="EDXH",
            dtstart=_iso(now - timedelta(hours=1)), dtend=_iso(now + timedelta(hours=1)),
        )
        done_id = create_transport_event(
            conn, name="Fertig", route="EDWG,EDXH", destination="EDXH",
            dtstart=_iso(now - timedelta(hours=5)), dtend=_iso(now - timedelta(hours=3)),
        )
        set_transport_summarized(conn, done_id, _iso(now - timedelta(hours=2)))
        conn.commit()
        conn.close()

        client.cookies.update(self._admin_cookies())
        res = client.get("/api/admin/transport/events")
        assert res.status_code == 200
        by_id = {ev["id"]: ev["status"] for ev in res.json()}
        assert by_id[scheduled_id] == "scheduled"
        assert by_id[running_id] == "running"
        assert by_id[done_id] == "done"


# --- transport_events_due_for_reminder (Task 4, #24) -----------------------

class TestTransportEventsDueForReminder:
    def test_manual_event_due_then_dedup_after_mark(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)
        eid = create_transport_event(
            conn, name="Helgoland-Nachschub", route="EDWG,EDXH", destination="EDXH",
            dtstart=_iso(now + timedelta(minutes=30)), dtend=None,
        )
        conn.commit()

        due = transport_events_due_for_reminder(conn, _iso(now), lead_min=60)
        assert [k["id"] for k in due] == [eid]

        mark_event_reminded(conn, f"kutter:{eid}", _iso(now))
        conn.commit()
        assert transport_events_due_for_reminder(conn, _iso(now), lead_min=60) == []

    def test_push_disabled_excluded(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)
        eid = create_transport_event(
            conn, name="Helgoland-Nachschub", route="EDWG,EDXH", destination="EDXH",
            dtstart=_iso(now + timedelta(minutes=30)), dtend=None,
        )
        set_transport_push_enabled(conn, eid, False)
        conn.commit()
        assert transport_events_due_for_reminder(conn, _iso(now), lead_min=60) == []

    def test_outside_window_excluded(self):
        conn = _make_conn()
        now = datetime.now(timezone.utc)
        create_transport_event(
            conn, name="Helgoland-Nachschub", route="EDWG,EDXH", destination="EDXH",
            dtstart=_iso(now + timedelta(minutes=90)), dtend=None,  # außerhalb 60-min-Fenster
        )
        assert transport_events_due_for_reminder(conn, _iso(now), lead_min=60) == []


# --- Snapshot-Read + Overlays (#66 Task 4) ----------------------------------

class TestKutterSnapshotEndpoints:
    """`_frozen_or_compute`/`_kutter_progress`: abgeschlossene Events werden aus dem Snapshot
    bedient (kein `compute_transport_progress`-Aufruf mehr), KI-Sprüche werden trotzdem frisch
    überlagert (sie entstehen erst NACH dem Latch, s. Spec §3)."""

    SECRET = "s3cr3t"
    PW = "test-admin-pw"

    _BASE_SNAPSHOT = {
        "route": ["EDWG", "EDXH"], "destination": "EDXH", "flights": [],
        "cargo": [], "total_kg": 42.0, "flight_count": 0, "loaded_count": 0,
        "target_kg": None, "progress_pct": None, "reserved_total_kg": 0.0,
        "unmapped_types": [], "summary_quip": None, "losses": [], "lost_total_kg": 0.0,
        "participants": [],
    }

    def _app(self, tmp_path, monkeypatch):
        p = str(tmp_path / "kutter_snapshot.db")
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

    def _summarized_event_with_snapshot(self, db_path, *, payload=None):
        from app.database import write_progress_snapshot
        conn = get_connection(db_path)
        ev = _event(conn)
        set_transport_summarized(conn, ev["id"], "2026-07-01T23:00:00Z")
        conn.commit()
        snap = dict(payload or self._BASE_SNAPSHOT)
        write_progress_snapshot(conn, "kutter", ev["id"], snap, "2026-07-01T23:00:01Z")
        conn.commit()
        conn.close()
        return ev

    def _spy_compute(self, monkeypatch, called):
        monkeypatch.setattr(
            main, "compute_transport_progress",
            lambda *a, **k: called.__setitem__("n", called["n"] + 1) or dict(self._BASE_SNAPSHOT),
        )

    def test_transport_events_uses_snapshot(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        self._summarized_event_with_snapshot(db)
        called = {"n": 0}
        self._spy_compute(monkeypatch, called)

        res = client.get("/api/transport/events")

        assert res.status_code == 200
        assert called["n"] == 0
        assert any(e["total_kg"] == 42.0 for e in res.json())

    def test_kutter_snapshot_overlays_fresh_quips(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        flight_key = "500:2026-07-01T18:00:00Z"
        payload = dict(self._BASE_SNAPSHOT, flights=[
            {"cid": 500, "callsign": "FRS500", "flight_key": flight_key, "quip": None,
             "loaded": True, "tonnage_kg": 250.0, "dep_time": "2026-07-01T18:00:00Z"},
        ])
        ev = self._summarized_event_with_snapshot(db, payload=payload)

        from app.database import set_transport_summary_quip
        conn = get_connection(db)
        set_transport_summary_quip(conn, ev["id"], "Feierabend!")
        set_transport_quip(conn, ev["id"], flight_key, "Guter Flug!")
        conn.commit()
        conn.close()

        res = client.get(f"/api/transport/event/{ev['id']}")

        assert res.status_code == 200
        body = res.json()
        assert body["summary_quip"] == "Feierabend!"
        assert body["flights"][0]["quip"] == "Guter Flug!"

    def test_admin_payloads_unmapped_uses_snapshot(self, tmp_path, monkeypatch):
        client, db = self._app(tmp_path, monkeypatch)
        payload = dict(self._BASE_SNAPSHOT, unmapped_types=["PA28"])
        self._summarized_event_with_snapshot(db, payload=payload)
        called = {"n": 0}
        self._spy_compute(monkeypatch, called)
        client.cookies.update(self._admin_cookies())

        res = client.get("/api/admin/transport/payloads")

        assert res.status_code == 200
        assert called["n"] == 0
        assert res.json()["unmapped_types"] == ["PA28"]


class TestGroundLoading:
    """#5: geparkt am Abholplatz -> sichtbar als ladend, dep aus AKTUELLER Live-Position."""

    def _load_event(self, conn):
        return _event(
            conn, route="EDXH,EDWG", destination="EDWG",
            cargo=[{"name": "Filmrollen", "target_kg": 200, "emoji": "🎞️", "departure": "EDXH"}],
        )

    def test_parked_at_pickup_shows_loading_from_live_pos_not_plan(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        # Flugplan bewusst FALSCH/veraltet (EDXP->EDWK), real steht der Pilot in EDXH:
        _add_open_flight(conn, 61, "EDXP", "EDWK", "C208", START)
        lat, lon = icao_to_coords("EDXH")
        _set_live_pos(conn, 61, lat, lon, 0)  # am Boden in EDXH
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        f = _feed_by_callsign(progress, "FRS61")
        assert f is not None
        assert f["dep"] == "EDXH"          # Live-Position gewinnt, nicht der Plan (EDXP)
        assert f["airborne"] is False
        assert f["loaded"] is False
        assert f["reserved_kg"] > 0

    def test_parked_at_destination_not_loading(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 62, "EDXH", "EDWG", "C208", START)
        lat, lon = icao_to_coords("EDWG")  # am ZIEL geparkt
        _set_live_pos(conn, 62, lat, lon, 0)
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        assert _feed_by_callsign(progress, "FRS62") is None

    def test_parked_off_route_invisible(self):
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 63, "EDXH", "EDWG", "C208", START)
        lat, lon = icao_to_coords("EDDF")  # weit weg von jedem Streckenplatz
        _set_live_pos(conn, 63, lat, lon, 0)
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        assert _feed_by_callsign(progress, "FRS63") is None

    def test_airborne_over_pickup_does_not_ground_load(self):
        """Der Boden-Ladezweig darf nur bei gs < Boden-Schwelle greifen: ein Pilot, dessen
        Live-Position ihn mit gs 120 ÜBER dem Abholplatz zeigt, ist NICHT am Boden — er lädt dort
        nichts (keine Phantom-Reservierung) und erscheint mangels erkanntem GPS-Leg gar nicht als
        ladend im Feed."""
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 64, "EDXH", "EDWG", "C208", START)
        lat, lon = icao_to_coords("EDXH")
        _set_live_pos(conn, 64, lat, lon, 120)  # in der Luft -> Boden-Zweig darf nicht greifen
        progress = compute_transport_progress(conn, ev, "2026-07-01T09:05:00Z")
        # Kein Boden-Ladevorgang -> keine Ware an Bord -> keine Feed-Zeile (er lädt gerade nicht).
        assert _feed_by_callsign(progress, "FRS64") is None
        assert progress["reserved_total_kg"] == 0.0

    # test_no_live_position_falls_back_to_plan: ersatzlos gelöscht — der Plan-Notnagel
    # (Sichtbarkeit/Beladung ohne jede Position) entfällt mit Entscheidung 8 („Ohne GPS-Track
    # keine Lieferung"). Ohne Live-Position und ohne GPS-Leg gibt es keinen Ladeort und keinen
    # Kutter-Flug. Der Boden-Ladefall MIT Live-Position bleibt (test_parked_at_pickup_...).


# --- Task 6: Adapter — aus Legs und Sessions wird eine Ereignisliste -------

class TestStackInputs:
    """Der Adapter: aus Legs + Sessions wird eine chronologische Ereignisliste."""

    def _load_event(self, conn):
        upsert_payload(conn, "C208", payload_kg=1000)
        conn.commit()
        return _event(conn, route="EDWG,EDXH", destination="EDXH",
                      cargo=[{"name": "Fisch", "target_kg": 800, "departure": "EDWG"}])

    def test_session_ohne_leg_ergibt_login_am_platz_aus_der_live_position(self):
        from app.database import _stack_inputs
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_open_flight(conn, 61, "EDXP", "EDWK", "C208", START)   # Flugplan bewusst falsch
        lat, lon = icao_to_coords("EDWG")
        _set_live_pos(conn, 61, lat, lon, 0)                        # real steht er in EDWG

        inp = _stack_inputs(conn, ev, _shift(START, 5))

        assert inp["destination"] == "EDXH"
        assert inp["loading_airports"] == {"EDWG"}
        assert [e["kind"] for e in inp["events"]] == ["login"]
        assert inp["events"][0]["airport"] == "EDWG"   # Live-Position gewinnt, nicht der Plan
        assert inp["events"][0]["capacity_kg"] == 1000.0
        assert len(inp["sessions"]) == 1               # für den Feed (Task 8)

    def test_leg_ergibt_takeoff_und_landing_mit_gps_orten(self):
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=40)
        _add_pos(conn, 12, START, dlat, dlon, 0, alt=delev)
        _add_pos(conn, 12, _shift(START, 2), dlat, dlon, 80, alt=delev + 1200)   # Takeoff
        _add_pos(conn, 12, _shift(START, 20), 54.0, 7.9, 120, alt=4000)
        _add_pos(conn, 12, _shift(START, 38), alat, alon, 40, alt=aelev + 400)
        _add_pos(conn, 12, _shift(START, 40), alat, alon, 0, alt=aelev)          # Touchdown

        inp = _stack_inputs(conn, ev, END)

        kinds = [e["kind"] for e in inp["events"]]
        assert kinds == ["login", "takeoff", "landing", "logout"]
        assert inp["events"][0]["airport"] == "EDWG"   # Login-Ort aus gps_departure des Legs
        assert inp["events"][2]["airport"] == "EDXH"   # Landung aus gps_arrival
        assert 12 in inp["legs_by_cid"]                # für den Feed (Task 8)

    def test_bei_gleicher_zeit_gilt_der_logout_zuerst(self):
        """Spec: er beendet die Tour — eine Landung im selben Moment kann nichts mehr abliefern."""
        from app.database import _sort_stack_events
        same = "2026-07-01T10:00:00Z"
        events = [
            {"ts": same, "kind": "landing", "cid": 1, "airport": "EDXH", "capacity_kg": 0},
            {"ts": same, "kind": "logout", "cid": 1, "airport": None, "capacity_kg": 0},
        ]
        assert [e["kind"] for e in _sort_stack_events(events)] == ["logout", "landing"]

    def test_manifest_kommt_in_ladereihenfolge(self):
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = _event(conn, route="EDWG,EDXH", destination="EDXH", cargo=[
            {"name": "Zuerst", "target_kg": 100, "departure": "EDWG"},
            {"name": "Danach", "target_kg": 200, "departure": "EDWG"},
        ])
        inp = _stack_inputs(conn, ev, END)

        assert [c["name"] for c in inp["manifest"]] == ["Zuerst", "Danach"]

    def test_refile_split_ist_kein_logout(self):
        """Fable-Review 16.07. (BLOCKER): Der Poller splittet eine LAUFENDE Verbindung, sobald
        der Flugplan mit geändertem Abflugplatz refiled wird (poller.py:832) — close_flight +
        open_flight. Wer unterwegs den Rückflug filed, bekäme so ein logoff_time in der Luft
        und seine Fracht würde durch eine reine Flugplan-Aenderung versenkt (#23-Verstoß).
        """
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        # Session 1: bis 09:30:00 (Poller schließt sie beim Refile)
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=30)
        # Session 2: 09:30:00.123456 — Mikrosekunden = Split-Signatur des Pollers
        conn.execute(
            "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time) "
            "VALUES (12, 'FRS12', 'C208', 'EDXH', 'EDWG', ?)",
            ("2026-07-01T09:30:00.123456Z",),
        )
        conn.commit()

        inp = _stack_inputs(conn, ev, END)

        # EINE Verbindung: kein logout dazwischen, nur der (noch offene) Rest.
        assert [e["kind"] for e in inp["events"]].count("logout") == 0
        assert [e["kind"] for e in inp["events"]].count("login") == 1
        assert len(inp["sessions"]) == 1
        assert inp["sessions"][0]["logoff_time"] is None   # verkettet -> die Session läuft

    def test_echter_logout_bleibt_ein_logout(self):
        """Gegenprobe zu S8 (Nutzer-Fund, flights.id 357/358): 2:54 min Lücke = echter Logout,
        keine Verkettung. Sonst würde der Fix den Fall kaputtmachen, den er schützen soll."""
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=30)   # bis 09:30
        _add_open_flight(conn, 12, "EDWG", "EDXH", "C208", "2026-07-01T09:32:54Z")

        inp = _stack_inputs(conn, ev, END)

        assert [e["kind"] for e in inp["events"]].count("logout") == 1
        assert len(inp["sessions"]) == 2

    def test_leg_nach_dtend_geht_nicht_verloren(self):
        """Fable-Review 16.07. (BLOCKER): canonicalize_legs filtert takeoff > end
        (database.py:2573). Mit end=min(now,dtend) könnte die Ware eines nach dtend
        gestarteten Fluges NIE ankommen — Widerspruch zu Entscheidung 10.

        Entscheidend ist die Lage des TAKEOFFS: `_in_window` filtert ausschließlich über
        `logon_time` (= takeoff_ts des Legs), und `_positions_for_cid` fenstert `end` bewusst
        gar nicht. Der Takeoff muss also NACH dtend liegen, sonst prüft der Test nichts (die
        erste Fassung legte ihn mit 22:57 davor und blieb unter genau der Mutation grün, gegen
        die sie schützen sollte). Der LOGIN muss zugleich VOR dtend liegen, sonst fällt die
        Session aus _transport_sessions (dort filtert `logon_time <= end`).
        """
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)          # dtend = END = 23:00
        login = "2026-07-01T22:55:00Z"      # Login VOR dtend ...
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", login, duration_min=40)
        _add_pos(conn, 12, login, dlat, dlon, 0, alt=delev)                        # 22:55 steht
        _add_pos(conn, 12, _shift(login, 10), dlat, dlon, 80, alt=delev + 1200)    # 23:05 Takeoff
        _add_pos(conn, 12, _shift(login, 20), 54.0, 7.9, 120, alt=4000)            # 23:15
        _add_pos(conn, 12, _shift(login, 38), alat, alon, 40, alt=aelev + 400)     # 23:33
        _add_pos(conn, 12, _shift(login, 40), alat, alon, 0, alt=aelev)            # 23:35 Landung

        inp = _stack_inputs(conn, ev, "2026-07-01T23:40:00Z")

        assert "landing" in [e["kind"] for e in inp["events"]]
        landing = next(e for e in inp["events"] if e["kind"] == "landing")
        assert landing["airport"] == "EDXH"

    def test_logout_im_selben_poll_wie_die_landung_versenkt_die_fracht_nicht(self):
        """Der Normalfall "abgeliefert, Feierabend" — und die Falle dahinter.

        poller.py:891 schliesst den Flug mit last_pos = MAX(ts) aus position_history. Wer
        innerhalb eines Poll-Takts (15 s) nach dem Aufsetzen aussteigt, bekommt deshalb
        logoff_time == landing_ts. Ohne den +1-s-Versatz sortierte der Logout vor die Landung
        (_STACK_EVENT_PRIO), faende position=None vor und versenkte die Ladung.
        """
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        touchdown = _shift(START, 40)
        # logoff_time liegt EXAKT auf dem Touchdown-Sample — genau das schreibt der Poller,
        # wenn der Pilot im selben Poll-Takt aussteigt (last_pos = MAX(ts) = Touchdown).
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=40)
        _add_pos(conn, 12, START, dlat, dlon, 0, alt=delev)
        _add_pos(conn, 12, _shift(START, 2), dlat, dlon, 80, alt=delev + 1200)
        _add_pos(conn, 12, _shift(START, 20), 54.0, 7.9, 120, alt=4000)
        _add_pos(conn, 12, _shift(START, 38), alat, alon, 40, alt=aelev + 400)
        _add_pos(conn, 12, touchdown, alat, alon, 0, alt=aelev)

        inp = _stack_inputs(conn, ev, END)

        # Die Landung MUSS vor dem Logout stehen — sonst versenkt derive_stacks die Ladung,
        # statt sie am Ziel abzuliefern.
        kinds = [e["kind"] for e in inp["events"]]
        assert kinds.index("landing") < kinds.index("logout")
        landing = next(e for e in inp["events"] if e["kind"] == "landing")
        logout = next(e for e in inp["events"] if e["kind"] == "logout")
        assert landing["airport"] == "EDXH"          # am Ziel abgeliefert
        assert landing["ts"] == touchdown            # die Landung bleibt, wo sie war
        assert logout["ts"] > landing["ts"]          # der Logout rueckt hinter sie

    def test_fallback_leg_ohne_gps_erzeugt_keine_flugereignisse(self):
        """#23: Kein GPS = kein Flug. canonicalize_legs hat einen Fallback OHNE GPS
        (_flightrow_as_flight, database.py:2614-2623): erkennt der Detektor für eine cid im
        ganzen Fenster KEIN Leg, wird jede geschlossene Nicht-Ghost-`flights`-Zeile als "Leg"
        ausgegeben — logon_time = Connection-Login, logoff_time = Connection-Logout,
        gps_departure/gps_arrival = None, departure/arrival aus dem FLUGPLAN.

        Würde der Adapter daraus takeoff/landing bauen, erfände er Flugereignisse aus einer
        Flugplan-Zeile (derselbe #23-Verstoß, den der Umbau ausschließen soll). Zugleich muss
        der Login-Ort auf Regel 2 (Live-/Boden-Position) durchfallen, statt an
        gps_departure=None hängenzubleiben — sonst stirbt die Boden-Beladung (#5, v8.22.0)
        still für jede cid mit Fallback-Legs.

        Aufbau = der reale Fall dahinter: Der Pilot steht die ganze Session in EDWG (gs 0, nie
        abgehoben) -> kein GPS-Leg -> Fallback greift. Sein Flugplan behauptet EDXP->EDWK; die
        Zeile trägt distance_nm > 0.5 und ist damit kein Ghost (database.py:1994).
        """
        from app.database import _stack_inputs
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._load_event(conn)
        lat, lon = icao_to_coords("EDWG")
        _add_flight(conn, 62, "EDXP", "EDWK", "C208", START, duration_min=30)
        # Nur Steh-Positionen: kein Abheben -> _gps_flights_for_positions liefert nichts.
        _add_pos(conn, 62, START, lat, lon, 0)
        _add_pos(conn, 62, _shift(START, 10), lat, lon, 0)
        _add_pos(conn, 62, _shift(START, 20), lat, lon, 0)

        inp = _stack_inputs(conn, ev, END)

        kinds = [e["kind"] for e in inp["events"]]
        assert kinds == ["login", "logout"]            # kein erfundener takeoff/landing
        assert inp["events"][0]["airport"] == "EDWG"   # Regel 2, nicht der Flugplan (EDXP)

    def test_leg_ohne_gps_departure_faellt_auf_die_bodenposition_zurueck(self):
        """Regel 2 muss auch dann greifen, wenn die Session ein ECHTES Leg hat, dessen
        Startplatz aber unbekannt ist (`gps_departure = None`).

        Realer Fall: Der Pilot steht um 09:00 in EDWG und lädt. Dann reißt der Positions-Feed
        für > 30 min ab (VPS-/Poller-Hicks) — _split_on_gaps trennt bei dieser Lücke ein neues
        Segment, das INIT-seitig als Spawn-in-der-Luft startet. Weil er dabei 4000 ft über
        Grund ist (>= _GPS_SPAWN_MAX_AGL_FT), bleibt `dep_icao` None (gps_legs.py:185) — das Leg
        ist trotzdem echt (Takeoff 10:00, Landung EDXH 10:30).

        Mit `if real:` (statt `if real and real[0].get("gps_departure")`) übernähme der
        Adapter dieses None als Login-Ort und der Pilot hätte in EDWG NICHTS geladen — die
        Boden-Beladung (#5, v8.22.0) stirbt still. Regel 2 findet ihn über die erste
        Position der Session korrekt in EDWG.
        """
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        _add_flight(conn, 63, "EDWG", "EDXH", "C208", START, duration_min=120)   # bis 11:00
        _add_pos(conn, 63, START, dlat, dlon, 0, alt=delev)                  # 09:00 steht in EDWG
        # >30 min Lücke -> neues Segment, Spawn in der Luft, 4000 ft AGL -> dep_icao = None
        _add_pos(conn, 63, _shift(START, 60), 54.0, 7.9, 120, alt=4000)      # 10:00 Takeoff-ts
        _add_pos(conn, 63, _shift(START, 88), alat, alon, 40, alt=aelev + 400)
        _add_pos(conn, 63, _shift(START, 90), alat, alon, 0, alt=aelev)      # 10:30 Landung EDXH

        inp = _stack_inputs(conn, ev, END)

        takeoff = next(e for e in inp["events"] if e["kind"] == "takeoff")
        assert takeoff["ts"] == _shift(START, 60)      # das Leg ist echt und bleibt erhalten
        landing = next(e for e in inp["events"] if e["kind"] == "landing")
        assert landing["airport"] == "EDXH"
        assert inp["events"][0]["airport"] == "EDWG"   # Login-Ort aus Regel 2, nicht None

    def test_logout_in_der_luft_springt_nicht_zur_spaeteren_landung(self):
        """S8 (Nutzer-Fund, flights.id 357/358, CID 1602713): Logout IN DER LUFT um 09:30,
        Re-Login 09:32:54 — 2:54 min Lücke, also KEINE Verkettung (zwei Sessions). Der
        GPS-Detektor segmentiert erst bei Lücken > 30 min und sieht EIN durchgehendes Leg:
        Takeoff 09:05, Landung 10:00.

        Der +1-s-Versatz des Logouts (gegen die Poll-Takt-Kollision "Landung und Logout im
        selben Sample") darf hier NICHT greifen: `own` begrenzt nur logon_time, nicht
        logoff_time — das Leg landet 30 min NACH dem Logout dieser Session. Sprünge der
        Logout-Zeit auf 10:00:01 rissen den Piloten mitten in Session 2 aus `position`
        (_drop_load + position.pop), _load_standing fände ihn nie wieder und seine Lieferung
        käme mit 0 kg an.
        """
        from app.database import _stack_inputs
        from app.geo import icao_to_coords, airport_elevation_ft
        conn = _make_conn()
        ev = self._load_event(conn)
        lat, lon = icao_to_coords("EDWG")
        elev = airport_elevation_ft("EDWG") or 0
        # Session 1: 09:00 -> 09:30 (Logout in der Luft), Session 2 ab 09:32:54 (offen).
        _add_flight(conn, 12, "EDWG", "EDXH", "C208", START, duration_min=30)
        _add_open_flight(conn, 12, "EDWG", "EDXH", "C208", "2026-07-01T09:32:54Z")
        # EIN durchgehender GPS-Track über beide Sessions: Start EDWG, Landung EDWG (Ladeplatz!).
        _add_pos(conn, 12, START, lat, lon, 0, alt=elev)                       # 09:00 steht
        _add_pos(conn, 12, _shift(START, 5), lat, lon, 80, alt=elev + 1200)    # 09:05 Takeoff
        _add_pos(conn, 12, _shift(START, 30), 54.0, 7.9, 120, alt=4000)        # 09:30 in der Luft
        _add_pos(conn, 12, _shift(START, 35), 54.0, 7.9, 120, alt=4000)        # 09:35 Session 2
        _add_pos(conn, 12, _shift(START, 58), lat, lon, 40, alt=elev + 400)    # 09:58 Anflug
        _add_pos(conn, 12, _shift(START, 60), lat, lon, 0, alt=elev)           # 10:00 Touchdown

        inp = _stack_inputs(conn, ev, END)

        logouts = [e for e in inp["events"] if e["kind"] == "logout"]
        assert len(logouts) == 1                       # Session 2 ist offen
        assert logouts[0]["ts"] == _shift(START, 30)   # 09:30 — bleibt, wo er war

    def test_statsim_leg_erzeugt_eigene_ereignisse(self):
        """Nutzer-Entscheidung 16.07.: StatSim (Backfill bei VPS-Ausfall) zählt wie ein
        normaler Flug — Login am Startplatz, Takeoff, Landung, Logout am Landeort.

        Hinweis: die im Brief genannte Tabelle heißt tatsächlich ``statsim_cache`` (nicht
        ``statsim_flights`` — Vertrag oben nachgesehen, database.py:106); ``duration_min``
        und ``fetched_at`` sind Pflichtfelder der echten Tabelle (WHERE-Filter in
        canonicalize_legs verlangt duration_min > 5, fetched_at ist NOT NULL). Der Track
        in statsim_position_history ist nötig, damit canonicalize_legs ein GPS-Leg erkennt."""
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        self._add_statsim_leg(conn)          # StatSim-Flug OHNE flights-Zeile (Poller lief nicht)

        inp = _stack_inputs(conn, ev, END)
        kinds = [e["kind"] for e in inp["events"]]

        assert kinds == ["login", "takeoff", "landing", "logout"]
        assert inp["events"][0]["airport"] == "EDWG"

    def test_statsim_leg_unter_echter_session_zaehlt_nur_einmal(self):
        """Gegenprobe zu oben — _covered_by_session ist der EINZIGE Schutz gegen
        StatSim/FriesenSpy-Doppelzählung.

        Deckt eine echte VATSIM-Verbindung das StatSim-Leg ab, darf es KEINE zweiten
        login/takeoff/landing-Ereignisse erzeugen. Sonst wird dieselbe Fracht zweimal
        geliefert — und das fällt nicht einmal auf: der Erhaltungssatz bleibt formal intakt,
        weil die Ware doppelt aus dem Ladeplatz-Stapel genommen wird. Der Balken lügt nach oben,
        ohne dass irgendetwas Alarm schlägt.

        Aufbau: Die `flights`-Zeile ist OFFEN und hat keine eigenen Positionen — deshalb baut
        canonicalize_legs aus ihr weder ein GPS-Leg noch ein Fallback-Leg (offene Zeilen sind
        dort ausgenommen, database.py:2615). Ihr Dedup-Intervall bleibt damit leer, das
        StatSim-Leg überlebt canonicalize_legs (genau der "unüberdeckte Rest", den
        _covered_by_session abfangen muss). _transport_sessions sieht die Zeile trotzdem und
        liefert die Session.
        """
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        self._add_statsim_leg(conn)
        _add_open_flight(conn, 12, "EDWG", "EDXH", "C208", START)   # echte Verbindung, deckt ab

        inp = _stack_inputs(conn, ev, END)
        kinds = [e["kind"] for e in inp["events"]]

        assert kinds.count("login") == 1     # NICHT zweimal — sonst doppelte Fracht
        assert kinds.count("takeoff") == 1
        assert kinds.count("landing") == 1

    def test_statsim_zeile_ohne_track_erzeugt_keine_flugereignisse(self):
        """#23 auf der StatSim-Seite — dieselbe Falle wie bei den FriesenSpy-Fallback-Legs.

        Eine statsim_cache-Zeile mit duration_min > 5, aber ohne verwertbaren Track in
        statsim_position_history, fällt in canonicalize_legs auf _flightrow_as_flight zurück
        (database.py:2711). Dieses Fallback-Leg trägt sehr wohl eine statsim_id (:2401) — nur
        kein block_start. Der StatSim-Block darf daraus keinen takeoff (Connection-Login) und
        keine landing (Connection-Logout) erfinden: kein GPS = kein Flug.

        Der Schaden ist heute latent (gps_departure = None verhindert das Laden, und anders als
        auf der FS-Seite gibt es hier gar keine Regel 2, die ihn scharfschalten könnte) — aber
        ein Zweig, der ohne GPS eine Landung behauptet, widerspricht #23 auch dann, wenn gerade
        niemand darauf tritt.
        """
        from app.database import _stack_inputs
        conn = _make_conn()
        ev = self._load_event(conn)
        # statsim_cache-Zeile OHNE statsim_position_history — kein Track, kein GPS-Leg.
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id, cid, callsign, departure, arrival, "
            "aircraft, logon_time, logoff_time, duration_min, fetched_at) VALUES "
            "(9002, 12, 'FRS12', 'EDWG', 'EDXH', 'C208', ?, ?, 30, ?)",
            (START, _shift(START, 30), START),
        )
        conn.commit()

        inp = _stack_inputs(conn, ev, END)

        assert inp["events"] == []     # keine flights-Zeile -> auch kein login/logout

    def _add_statsim_leg(self, conn, *, statsim_id=9001, cid=12):
        """Ein vollständiger StatSim-Flug EDWG->EDXH (09:00 -> 09:30) mit Track.

        Hinweis: die Tabelle heißt statsim_cache (database.py:106); duration_min und
        fetched_at sind Pflichtfelder (canonicalize_legs filtert duration_min > 5).
        """
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        alat, alon = icao_to_coords("EDXH")
        aelev = airport_elevation_ft("EDXH") or 0
        conn.execute(
            "INSERT INTO statsim_cache (statsim_id, cid, callsign, departure, arrival, "
            "aircraft, logon_time, logoff_time, duration_min, fetched_at) VALUES "
            "(?, ?, ?, 'EDWG', 'EDXH', 'C208', ?, ?, 30, ?)",
            (statsim_id, cid, f"FRS{cid:02d}", START, _shift(START, 30), START),
        )
        for lat, lon, alt, gs, minute in [
            (dlat, dlon, delev, 0, 0),                # steht in EDWG
            (dlat, dlon, delev + 1200, 80, 2),        # Takeoff
            (54.0, 7.9, 4000, 120, 15),               # unterwegs
            (alat, alon, aelev + 400, 40, 28),        # Anflug EDXH
            (alat, alon, aelev, 0, 30),               # Touchdown
        ]:
            conn.execute(
                "INSERT INTO statsim_position_history "
                "(statsim_id, latitude, longitude, altitude, groundspeed, heading, ts) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (statsim_id, lat, lon, alt, gs, _shift(START, minute)),
            )
        conn.commit()


class TestStapelProgress:
    """compute_transport_progress auf Basis der Stapel-Ableitung — die Fälle, an denen sich das
    Modell entscheidet (S1-S5 aus scripts/kutter_ladung_szenarien.py, hier mit echten Tracks)."""

    def _leg(self, conn, cid, von, nach, t0, *, dauer=20, callsign=None):
        """Ein GPS-erkennbarer Flug von 'von' nach 'nach'. Vorlage: scripts/kutter_ladung_szenarien.leg()"""
        from app.geo import icao_to_coords, airport_elevation_ft
        callsign = callsign or f"FRS{cid:02d}"
        # position_history.cid ist NOT NULL REFERENCES pilots(cid) — der Pilot muss existieren,
        # bevor Positionen kommen (_leg laeuft vor _add_flight, das den Piloten sonst anlegt).
        conn.execute("INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
                     (cid, f"Pilot{cid}", START))
        la, lo = icao_to_coords(von)
        ea = airport_elevation_ft(von) or 0
        lb, lb2 = icao_to_coords(nach)
        eb = airport_elevation_ft(nach) or 0
        _add_pos(conn, cid, t0, la, lo, 0, alt=ea, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 1), la, lo, 70, alt=ea + 250, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, 2), la, lo, 120, alt=ea + 2500, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, dauer // 2), (la + lb) / 2, (lo + lb2) / 2, 130,
                 alt=3000, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, dauer - 1), lb, lb2, 60, alt=eb + 200, callsign=callsign)
        _add_pos(conn, cid, _shift(t0, dauer), lb, lb2, 0, alt=eb, callsign=callsign)
        return _shift(t0, dauer)

    def _milchmann_event(self, conn):
        upsert_payload(conn, "C208", payload_kg=1000)
        conn.commit()
        return _event(conn, route="EDWG,EDWZ,EDXH", destination="EDXH", cargo=[
            {"name": "Fisch", "target_kg": 800, "departure": "EDWG"},
            {"name": "Tee", "target_kg": 500, "departure": "EDWZ"},
        ])

    def test_s2_milchmann_erste_ladung_bleibt_an_bord(self):
        """HEUTE: 0 Fisch + 500 Tee. Der Startplatz des LETZTEN Beins bestimmt die Fracht."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDWZ", START)
        t2 = self._leg(conn, 1, "EDWZ", "EDXH", _shift(t1, 10))
        # Zwei Legs, EINE Verbindung: Refile-Split am Zwischenplatz (Pilot landet, sitzt, filed neu).
        # Der Poller schließt Leg 1 IM Refile-Moment (poller.py:837) — logoff(Leg1) == logon(Leg2),
        # keine Lücke — sodass _transport_sessions beide wieder zu einer Verbindung verkettet
        # (kein Logout am Zwischenplatz). Eine echte Lücke wäre ein Disconnect+Reconnect.
        _add_flight(conn, 1, "EDWG", "EDWZ", "C208", START, duration_min=30)          # logoff 09:30
        _add_flight(conn, 1, "EDWZ", "EDXH", "C208", _shift(t1, 10), duration_min=20)  # logon 09:30

        p = compute_transport_progress(conn, ev, END)

        fisch = next(c for c in p["cargo"] if c["name"] == "Fisch")
        tee = next(c for c in p["cargo"] if c["name"] == "Tee")
        assert fisch["delivered_kg"] == 800.0
        assert tee["delivered_kg"] == 200.0     # 1000 kg Zuladung - 800 Fisch
        assert p["total_kg"] == 1000.0

    def test_s3_zwischenlandung_fremd_liefert_die_echte_ladung(self):
        """HEUTE: ohne Latch 0 kg, mit Latch 1000 kg (Tee, der nie an Bord war)."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDDW", START)
        t2 = self._leg(conn, 1, "EDDW", "EDXH", _shift(t1, 10))
        # Zwei Legs, EINE Verbindung (Refile-Split am fremden EDDW, KEIN Logout): logoff(Leg1) ==
        # logon(Leg2), keine Lücke → _transport_sessions verkettet zu einer Verbindung, die Ladung
        # bleibt an Bord und wird am Ziel geliefert. Eine echte Lücke wäre ein Disconnect an EDDW —
        # dort läge die Fracht dann unwiederbringlich (stolen, fremder Platz), Ergebnis 0.
        _add_flight(conn, 1, "EDWG", "EDDW", "C208", START, duration_min=30)          # logoff 09:30
        _add_flight(conn, 1, "EDDW", "EDXH", "C208", _shift(t1, 10), duration_min=20)  # logon 09:30

        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] == 800.0           # nur der Fisch, der wirklich an Bord war
        tee = next(c for c in p["cargo"] if c["name"] == "Tee")
        assert tee["delivered_kg"] == 0.0

    def test_s4_logout_am_zweiten_ladeplatz_legt_die_ware_dorthin(self):
        """HEUTE: 'returned' -> zurück in den EDWG-Topf. Die Ware liegt aber in EDWZ."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDWZ", START)
        _add_flight(conn, 1, "EDWG", "EDWZ", "C208", START, duration_min=20)

        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] == 0.0
        loss = next((f for f in p["flights"] if f.get("loss_kind")), None)
        assert loss is not None and loss["loss_kind"] == "returned"
        assert p["lost_total_kg"] == 0.0        # zurückgebracht ist kein Verlust

    def test_die_bordladung_ist_die_reservierung(self):
        """Die Reservierung ist kein eigener Mechanismus mehr: wer lädt, nimmt vom Stapel."""
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        _add_open_flight(conn, 61, "EDWG", "EDXH", "C208", START)
        lat, lon = icao_to_coords("EDWG")
        _set_live_pos(conn, 61, lat, lon, 0)

        p = compute_transport_progress(conn, ev, _shift(START, 5))

        assert p["reserved_total_kg"] == 800.0   # er hat den EDWG-Stapel an Bord
        fisch = next(c for c in p["cargo"] if c["name"] == "Fisch")
        assert fisch["reserved_kg"] == 800.0
        assert fisch["delivered_kg"] == 0.0

    def test_der_erhaltungssatz_gilt_auch_im_api_vertrag(self):
        """geliefert + verloren + reserviert + Rest == Manifest. Der Balken kann nicht lügen."""
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        t1 = self._leg(conn, 1, "EDWG", "EDDW", START)
        _add_flight(conn, 1, "EDWG", "EDDW", "C208", START, duration_min=20)

        p = compute_transport_progress(conn, ev, END)

        assert p["total_kg"] + p["lost_total_kg"] == 800.0   # gestohlen in EDDW
        assert p["lost_total_kg"] == 800.0

    def test_ein_leerer_pilot_haelt_den_feierabend_nicht_auf(self):
        """Entscheidung 10: Es zählt nur, ob jemand Ware trägt — nicht 'offener Flug auf der Strecke'."""
        from app.database import transport_anyone_in_progress
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        # Der Stapel ist leer: ein anderer hat alles geholt und geliefert.
        t1 = self._leg(conn, 1, "EDWG", "EDXH", START)
        _add_flight(conn, 1, "EDWG", "EDXH", "C208", START, duration_min=20)
        t2 = self._leg(conn, 2, "EDWZ", "EDXH", START)
        _add_flight(conn, 2, "EDWZ", "EDXH", "C208", START, duration_min=20)
        # Jetzt loggt ein Dritter am (leeren) EDWG ein und steht dort:
        _add_open_flight(conn, 3, "EDWG", "EDXH", "C208", _shift(START, 60))
        lat, lon = icao_to_coords("EDWG")
        _set_live_pos(conn, 3, lat, lon, 0)

        assert transport_anyone_in_progress(conn, ev, started_before=END) is False

    def test_ein_beladener_pilot_haelt_den_feierabend_auf(self):
        from app.database import transport_anyone_in_progress
        from app.geo import icao_to_coords
        conn = _make_conn()
        ev = self._milchmann_event(conn)
        _add_open_flight(conn, 3, "EDWG", "EDXH", "C208", START)
        lat, lon = icao_to_coords("EDWG")
        _set_live_pos(conn, 3, lat, lon, 0)      # steht am vollen Stapel -> lädt 800 Fisch

        assert transport_anyone_in_progress(conn, ev, started_before=END) is True
