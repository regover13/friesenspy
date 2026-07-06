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
                           latch_offset_min=5):
    """Eine tatsächlich am Ziel angekommene Fracht-Lieferung OHNE vollen GPS-Track: die
    Connection schließt mit arrival='' (keine verwertbare Ankunftsangabe -- ein reiner
    Flugplan-Text darf unter GPS-only NICHT mehr als Lieferung zählen, #23 Review C2), der
    Live-Ankunfts-Latch (wie ihn `check_live_arrival` beim echten Anflug setzen würde) ist
    der einzige, GPS-gestützte Nachweis der Lieferung. Ersetzt die alten `_add_flight(...dest)`-
    Aufrufe überall dort, wo der Test eine tatsächlich GEFLOGENE, angekommene Lieferung meint
    (nicht bloß einen Flugplan-Eintrag)."""
    callsign = callsign or f"FRS{cid:02d}"
    _add_flight(conn, cid, dep, "", aircraft, logon, duration_min=duration_min, callsign=callsign)
    set_transport_live_arrival(conn, cid, logon, ev_id, _shift(logon, latch_offset_min))
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
            {"name": "Filmrollen", "target_kg": 300, "per_flight_max_kg": 100, "emoji": "🎞️"},
            {"name": "Friesentee", "target_kg": 500, "emoji": "🫖"},
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
        ev = _event(conn)
        _add_delivered_flight(conn, 12, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])  # hin, beladen
        _add_flight(conn, 12, "EDXH", "EDWG", "C172", "2026-07-01T11:00:00Z")  # zurück, leer
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
        ev = _event(conn)
        _add_delivered_flight(conn, 3, "EDWG", "PA28", "2026-07-01T10:00:00Z", ev["id"])  # kein Payload gepflegt
        p = compute_transport_progress(conn, ev, END)
        assert p["total_kg"] == 150.0  # globaler Default
        assert "PA28" in p["unmapped_types"]

    def test_manifest_sequential_fill(self):
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=[
            {"name": "Fischbrötchen", "target_kg": 800},
            {"name": "Friesen Tee", "target_kg": 500},
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
        # Frachtart je beladenem Flug
        by_dep_time = {f["dep_time"]: f for f in p["flights"]}
        assert by_dep_time["2026-07-01T10:00:00Z"]["cargo_name"] == "Fischbrötchen"
        assert by_dep_time["2026-07-01T10:30:00Z"]["cargo_name"] == "Fischbrötchen"
        assert by_dep_time["2026-07-01T11:00:00Z"]["cargo_name"] == "Friesen Tee"

    def test_capped_overflow_not_credited_to_total(self):
        # #63 „Balken lügt nicht": Fracht ohne Manifest-Platz (per_flight_max_kg-Kappung) zählt
        # NICHT als geliefert. tonnage_kg je Flug = tatsächliche Gutschrift, nicht Musterzuladung.
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=[
            {"name": "Inselpost", "target_kg": 1500, "per_flight_max_kg": 50},
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
                assert f["tonnage_kg"] == 50       # belegt (Netto)
                assert f["onboard_kg"] == 550      # an Bord (Musterzuladung) bleibt für „50 / 550 kg"
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

    def test_no_manifest_is_plain_counter(self):
        conn = _make_conn()
        self._seed(conn)
        ev = _event(conn, cargo=None)
        _add_delivered_flight(conn, 12, "EDWG", "C172", "2026-07-01T10:00:00Z", ev["id"])
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

    def test_latch_persists_after_disconnect_without_known_arrival(self):
        """Latch bleibt gültig, wenn die Connection ohne belastbare GPS-/Flugplan-Ankunft endet
        (kein Track, kein gefilter Zielflughafen — 'arr' bleibt leer). Ein GPS-BELEGT
        abweichendes Ziel darf dagegen NIE mehr beladen zählen (Rückflug-Bein-Schutz, s.
        TestReturnLegNotDoubleCounted) — dieser Fall wurde vorher hier fälschlich mitgetestet
        (arrival='EDDH', ein bekanntes, abweichendes Ziel) und ist unter GPS-only bewusst
        korrigiert worden (#23 Task 10)."""
        conn = _make_conn()
        upsert_payload(conn, "C208", payload_kg=550)
        ev = _event(conn)
        _add_open_flight(conn, 9, "EDWG", "", "C208", START)
        set_transport_live_arrival(conn, 9, START, ev["id"], "2026-07-01T10:00:00Z")
        conn.commit()
        # Pilot disconnectet spaeter ohne verwertbare Ankunftsangabe (kein Flugplan-Ziel
        # gefilt, kein GPS-Track) -- die Fracht bleibt trotzdem gezaehlt, weil der Latch
        # bereits existiert und "arr" leer (nicht widersprüchlich) bleibt.
        conn.execute(
            "UPDATE flights SET logoff_time=?, arrival='', duration_min=45, distance_nm=120 "
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

    def test_check_live_arrival_uses_global_radius_regardless_of_event_radius(self):
        """#23: kein Per-Event-Radius mehr — check_live_arrival nutzt immer den globalen
        4-km-Standard (``_BUMMEL_AIRPORT_RADIUS_KM``), auch wenn ``event['radius_km']`` einen
        kleineren Wert trägt. Fixtures analog der alten Override-Probe: EDXH-Koordinaten +
        Offset-Position (0.0315° ≈ 3.5 km, verifiziert per ``haversine`` — innerhalb des
        4-km-Standards, außerhalb eines fiktiven 3-km-Radius)."""
        conn = _make_conn()
        from app.geo import icao_to_coords
        lat, lon = icao_to_coords("EDXH")
        pos3_5km = (lat + 0.0315, lon)             # ~3.5 km nördlich
        ev_small = _event(conn, destination="EDXH", radius_km=3.0)
        ev_default = _event(conn, destination="EDXH")
        events = active_transport_destinations(conn, ev_small["dtstart"])
        check_live_arrival(conn, 111, "2026-07-02T18:00:00Z", pos3_5km[0], pos3_5km[1], 0.0, events)
        latched_small = get_transport_live_arrivals(conn, ev_small["id"])
        latched_default = get_transport_live_arrivals(conn, ev_default["id"])
        # Beide latchen jetzt — event['radius_km']=3.0 wird ignoriert, der globale 4-km-Radius
        # greift überall gleich.
        assert (111, "2026-07-02T18:00:00Z") in latched_small
        assert (111, "2026-07-02T18:00:00Z") in latched_default


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
        # Durchgängig Netto (#63): reserved_kg je Flug ist die reservierbare Menge (was noch ins
        # Manifest passt) — die volle Musterzuladung bleibt separat als onboard_reserved_kg.
        assert p["flights"][0]["reserved_kg"] == 100.0
        assert p["flights"][0]["onboard_reserved_kg"] == 292.0

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

    def test_open_flight_on_ground_is_not_airborne(self):
        """#62-Folgefund (Live 06.07.): ein am Streckenplatz GEPARKTER Pilot (gs 0, nie abgehoben,
        kein offenes GPS-Leg) reserviert zwar schon seine Fracht, gilt aber als „am Start" —
        `airborne` False. `in_air`/Reservierung bleiben unverändert (er zählt weiter als offen)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)  # payload 292
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        _add_open_flight(conn, 210, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        # Zwei Boden-Samples bei gs 0 am Startplatz — nie abgehoben, also kein GPS-Leg.
        _add_pos(conn, 210, "2026-07-02T18:05:00Z", dlat, dlon, 0, alt=delev, callsign="FRS210")
        _add_pos(conn, 210, "2026-07-02T18:06:00Z", dlat, dlon, 0, alt=delev, callsign="FRS210")
        p = compute_transport_progress(conn, ev, "2026-07-02T18:10:00Z")
        f = next(x for x in p["flights"] if x["cid"] == 210)
        assert f["in_air"] is True and f["loaded"] is False    # weiterhin offene Reservierung
        assert f["airborne"] is False                           # aber NICHT „unterwegs"
        assert f["reserved_kg"] == 292.0

    def test_open_flight_airborne_after_takeoff(self):
        """Gegenprobe: sobald der GPS-Leg-Detektor ein offenes (abgehobenes) Leg erkennt, ist der
        Flug „unterwegs" → `airborne` True."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        from app.geo import icao_to_coords, airport_elevation_ft
        dlat, dlon = icao_to_coords("EDWG")
        delev = airport_elevation_ft("EDWG") or 0
        t0 = "2026-07-02T18:05:00Z"
        _add_open_flight(conn, 211, "EDWG", "EDXH", "C172", t0)
        _add_pos(conn, 211, t0, dlat, dlon, 0, alt=delev, callsign="FRS211")
        _add_pos(conn, 211, _shift(t0, 1), dlat, dlon, 12, alt=delev, callsign="FRS211")
        _add_pos(conn, 211, _shift(t0, 4), dlat, dlon, 80, alt=delev + 1200, callsign="FRS211")  # Takeoff, kein Touchdown
        p = compute_transport_progress(conn, ev, _shift(t0, 10))
        f = next(x for x in p["flights"] if x["cid"] == 211)
        assert f["in_air"] is True and f["airborne"] is True

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

    def test_plan_only_fallback_arrival_is_not_a_delivery(self):
        """#23 Review C2: Ein reiner Flugplan-Eintrag (arrival=dest im Flugplan, aber KEIN
        einziger GPS-Track) darf NIE als Lieferung zählen -- weder in
        compute_transport_progress (loaded) noch als Grund, detect_transport_losses die
        Verlust-Prüfung überspringen zu lassen ('Plan-Text-Lieferung ohne Flug')."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn)  # route=EDWG,EDXH, destination=EDXH
        # Reine Connection OHNE jede Position -- canonicalize_legs fällt auf
        # _flightrow_as_flight zurück (gps_arrival=None), arrival kommt nur aus dem Plan.
        _add_flight(conn, 700, "EDWG", "EDXH", "C172", "2026-07-01T18:00:00Z", duration_min=30)

        p = compute_transport_progress(conn, ev, "2026-07-01T20:00:00Z")
        f = _feed_by_callsign(p, "FRS700")
        assert f is not None
        assert f["loaded"] is False and f["tonnage_kg"] == 0.0
        assert p["total_kg"] == 0.0

        # Keine Position vorhanden -> detect_transport_losses erfasst (mangels Beweis) auch
        # keinen Verlust, aber NICHT mehr, weil "arr == dest" es fälschlich als bereits
        # geliefert wertet (das war der Bug) -- 0 ist hier aus dem richtigen Grund korrekt.
        assert detect_transport_losses(conn, ev) == 0
        assert get_transport_losses(conn, ev["id"]) == []

    def test_later_reconnect_latch_does_not_hide_earlier_sunk_loss(self):
        """#23 Review I1: Der Latch-Abgleich in detect_transport_losses darf nur gegen das
        ENDE DER EIGENEN CONNECTION prüfen -- ein Latch einer SPÄTEREN Reconnect-Connection
        derselben cid darf einen früher versunkenen Kutter NICHT verdecken (vorher: end=∞ beim
        Leg-eigenen logoff_time=None -> jeder spätere Latch 'traf')."""
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        cid = 900
        logon1 = "2026-07-01T18:00:00Z"
        # Connection 1: schließt (Disconnect) nach 30 min -- das GPS-Leg selbst registriert
        # NIE eine Landung (über See verschwunden, s. _flown_flight/end_gs=95).
        self._flown_flight(conn, cid, logon1, end_lat=54.05, end_lon=7.7, end_gs=95)
        # Spätere Reconnect-Connection derselben cid, MIT Live-Ankunfts-Latch.
        logon2 = "2026-07-01T19:30:00Z"
        _add_flight(conn, cid, "EDXH", "EDWG", "C172", logon2, duration_min=20)
        set_transport_live_arrival(conn, cid, logon2, ev["id"], _shift(logon2, 5))
        conn.commit()

        n = detect_transport_losses(conn, ev)
        losses = get_transport_losses(conn, ev["id"])
        assert n >= 1
        assert any(l["kind"] == "sunk" for l in losses)

    def test_position_classified_at_destination_is_not_stolen(self, monkeypatch):
        """#23 Review M1: Klassifiziert die reine Positions-Auswertung die letzte bekannte
        Position als 'am Ziel' (end_icao == dest) -- z. B. ein Detektor-Radius-/AGL-Grenzfall,
        bei dem canonicalize_legs selbst dort KEINE Landung erkannt hat (Leg bleibt offen) --
        ist das kein Diebstahl. Das GPS-Leg-Ende bleibt bewusst identisch zur 'sunk'-Fixture
        (54.05/7.7, verifiziert abseits jedes Flugplatzes) -- nur die Klassifikationsfunktion
        wird gepatcht, um den Grenzfall 'Ergebnis == Ziel' deterministisch zu erzwingen."""
        import app.geo as geomod
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 500.0}])
        self._flown_flight(conn, 1100, "2026-07-01T18:05:00Z", end_lat=54.05, end_lon=7.7, end_gs=0)
        # detect_transport_losses importiert nearest_airport_icao lokal aus app.geo -- patchen
        # dort, damit die Klassifikations-Funktion deterministisch "am Ziel" meldet, OHNE den
        # GPS-Leg-Detektor selbst zu beeinflussen (der bleibt unpatched: er erkennt an diesem
        # Punkt weiterhin keine Landung, s. _flown_flight/'sunk'-Fixture).
        monkeypatch.setattr(geomod, "nearest_airport_icao", lambda lat, lon, radius: "EDXH")

        n = detect_transport_losses(conn, ev)
        assert n == 0
        assert get_transport_losses(conn, ev["id"]) == []


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

    def test_live_latch_reconciled_to_gps_flight(self):
        """Latch mit Verbindungs-Logon 09:58 (Session-Start), GPS-Flug/Takeoff aber erst 10:02
        (Taxi-Zeit dazwischen) — Landung EDXH 10:40. Ein naiver ``(cid, lo)``-Vergleich mit
        ``lo`` = GPS-Takeoff (der jetzige ``flight_key``) fände den Latch NICHT (Schlüssel-
        Mismatch) und die Ankunft läge außerhalb der (bewusst auf EDWG verengten) Strecke —
        ohne die Connection-Intervall-Reconcile (``_latch_hits_flight``) bliebe die Fracht
        0 kg, obwohl der Kutter GPS-belegt am Ziel landet."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        conn_logon = "2026-07-01T09:58:00Z"
        # `route` bewusst NUR der Abflugplatz -- ohne Latch würde der Strecken-Filter
        # (arr=EDXH nicht in route_set) die Ankunft verwerfen; der Latch hebt ihn auf.
        ev = _event(conn, route="EDWG", destination="EDXH")
        self._insert_connection(conn, 500, "FRS500", "EDWG", "EDXH", conn_logon,
                                _shift(conn_logon, 44), duration_min=44)
        self._seed_leg(conn, 500, "FRS500", conn_logon, "EDWG")
        landing_ts = self._add_leg_landing(conn, 500, "FRS500", conn_logon, "EDXH", cruise_min=22)
        conn.commit()
        assert landing_ts == "2026-07-01T10:40:00Z"
        set_transport_live_arrival(conn, 500, conn_logon, ev["id"], "2026-07-01T10:35:00Z")
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T11:00:00Z")
        f = _feed_by_callsign(p, "FRS500")
        assert f is not None
        assert f["dep_time"] == "2026-07-01T10:02:00Z"  # GPS-Takeoff, NICHT der Verbindungs-Logon
        assert f["loaded"] is True
        assert p["total_kg"] == 250

    def test_return_leg_not_double_counted(self):
        """Eine Mehrbein-Connection (Hin EDWG→EDXH landet am Ziel, Rück EDXH→EDWG) — der Latch
        (Verbindungs-Logon) überlappt via Connection-Intervall BEIDE Beine, trotzdem darf NUR
        das Hin-Bein beladen sein: ein GPS-belegtes, vom Ziel abweichendes Ankunfts-Bein zählt
        nie, unabhängig vom Latch (sonst zählte die Fracht doppelt)."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn)  # route=EDWG,EDXH, destination=EDXH
        conn_logon = "2026-07-01T09:58:00Z"
        conn_logoff = "2026-07-01T11:35:00Z"
        self._insert_connection(conn, 501, "FRS501", "EDWG", "EDWG", conn_logon, conn_logoff,
                                duration_min=97)
        from app.geo import icao_to_coords
        # Hin: EDWG -> EDXH
        self._seed_leg(conn, 501, "FRS501", conn_logon, "EDWG")
        hin_landing = self._add_leg_landing(conn, 501, "FRS501", conn_logon, "EDXH")
        # Turnaround in EDXH (kurzer Boden-Aufenthalt, dann erneut abheben)
        hlat, hlon = icao_to_coords("EDXH")
        _add_pos(conn, 501, _shift(hin_landing, 3), hlat, hlon, 5, alt=8, callsign="FRS501")
        # Rück: EDXH -> EDWG
        self._seed_leg(conn, 501, "FRS501", _shift(hin_landing, 6), "EDXH")
        self._add_leg_landing(conn, 501, "FRS501", _shift(hin_landing, 6), "EDWG")
        conn.commit()
        # Latch waehrend des Hin-Beins gesetzt (Verbindungs-Logon als Key, Poller-Konvention).
        set_transport_live_arrival(conn, 501, conn_logon, ev["id"], "2026-07-01T10:35:00Z")
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T12:00:00Z")
        legs = [f for f in p["flights"] if f["cid"] == 501]
        assert len(legs) == 2
        hin = next(f for f in legs if f["arr"] == "EDXH")
        rueck = next(f for f in legs if f["arr"] == "EDWG")
        assert hin["loaded"] is True
        assert rueck["loaded"] is False and rueck["tonnage_kg"] == 0.0
        assert p["total_kg"] == 250  # nur einmal gezählt, nicht doppelt

    def test_delivery_requires_route_membership(self):
        """Landung neben dem Ziel (ein bekannter, aber streckenfremder Flughafen), kein Latch
        → 0 kg: weder Strecken-Filter-Bypass noch ``loaded``."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn)  # route=EDWG,EDXH, destination=EDXH
        logon = "2026-07-01T09:58:00Z"
        self._insert_connection(conn, 502, "FRS502", "EDWG", "EDDH", logon,
                                _shift(logon, 60), duration_min=60)
        self._seed_leg(conn, 502, "FRS502", logon, "EDWG")
        self._add_leg_landing(conn, 502, "FRS502", logon, "EDDH")  # Hamburg -- nicht auf der Strecke
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T11:30:00Z")
        assert _feed_by_callsign(p, "FRS502") is None
        assert p["total_kg"] == 0

    def test_open_connection_after_gps_landing_not_double_counted(self):
        """#23 Review C1: Ein Pilot landet GPS-belegt am Ziel, bleibt aber verbunden
        (flights.logoff_time NULL — Live-Befund, s. Fable-Review). canonicalize_legs liefert
        dann SOWOHL die geschlossene GPS-Leg-Zeile (loaded=True, Landung erkannt) ALS AUCH
        (über open_transport_flights, das ausdrücklich logoff_time IS NULL erlaubt) die offene
        Connection-Zeile derselben cid -- ohne den Skip zählt die Fracht doppelt."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn)  # route=EDWG,EDXH, destination=EDXH
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
        """#23 Review C1 (Gegenprobe -- nicht zu breit fixen): ein geschlossenes Zwischenlande-
        Bein (arr != dest, daher NICHT beladen) darf die offene Weiterreise derselben, noch
        verbundenen Connection NICHT unterdrücken -- der Skip greift nur, wenn die Connection
        bereits eine GELADENE Zeile geliefert hat."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, route="EDWG,EDWY,EDXH", destination="EDXH")
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
        zwischenlandung = next(f for f in legs if f["arr"] == "EDWY")
        assert zwischenlandung["loaded"] is False
        assert any(f["in_air"] for f in legs)   # offene Weiterreise bleibt als Reservierung erhalten

    def test_new_leg_after_completed_return_not_shown_as_returning(self):
        """#66 (Live-Fund 06.07., EDWG-EDXP-Test): Lieferung (EDWG->EDXH, geliefert) -> Rückflug
        landet sauber (EDXH->EDWG) -> in DERSELBEN offenen Verbindung startet ein NEUER, davon
        unabhängiger Flug (EDWG->irgendwohin, noch in der Luft). Die alte Heuristik nahm für
        "Rückflug" immer die Erstposition der GESAMTEN Verbindung (EDXH, längst veraltet) und
        zeigte den neuen Flug fälschlich weiter als "Rückflug". Mit dem GPS-Leg-basierten Dep
        (aus dem bereits korrekt erkannten LAUFENDEN Leg) muss der neue Flug stattdessen normal
        als "in der Luft"/reserviert erscheinen -- kein Rückflug mehr."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn)  # route=EDWG,EDXH, destination=EDXH
        conn_logon = "2026-07-01T09:58:00Z"
        self._insert_connection(conn, 700, "FRS700", "EDWG", "EDWG", conn_logon, None,
                                duration_min=97)
        from app.geo import icao_to_coords
        # Leg 1: EDWG -> EDXH (Lieferung, geliefert).
        self._seed_leg(conn, 700, "FRS700", conn_logon, "EDWG")
        hin_landing = self._add_leg_landing(conn, 700, "FRS700", conn_logon, "EDXH")
        hlat, hlon = icao_to_coords("EDXH")
        _add_pos(conn, 700, _shift(hin_landing, 3), hlat, hlon, 5, alt=8, callsign="FRS700")
        # Leg 2: EDXH -> EDWG (echter Rückflug, landet sauber).
        rueck_t0 = _shift(hin_landing, 6)
        self._seed_leg(conn, 700, "FRS700", rueck_t0, "EDXH")
        rueck_landing = self._add_leg_landing(conn, 700, "FRS700", rueck_t0, "EDWG")
        glat, glon = icao_to_coords("EDWG")
        _add_pos(conn, 700, _shift(rueck_landing, 3), glat, glon, 5, alt=6, callsign="FRS700")
        # Leg 3: NEUER Start ab EDWG, noch in der Luft (kein Touchdown vor `now`) -- KEIN
        # Rückflug, ein unabhängiger neuer Flug (in der realen Live-Situation ging es weiter zu
        # einem event-fremden Flugplatz, hier bewusst offen gelassen).
        neu_t0 = _shift(rueck_landing, 6)
        self._seed_leg(conn, 700, "FRS700", neu_t0, "EDWG")
        conn.commit()
        # Aktuelle Live-Position: noch in der Luft (nicht gelandet) -> _returning_pilot_landed
        # darf nicht greifen, unabhängig vom Test.
        conn.execute(
            "INSERT INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
            "VALUES (700, 'FRS700', 53.75, 7.87, 100)"
        )
        conn.commit()

        p = compute_transport_progress(conn, ev, _shift(neu_t0, 10))
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[700]["status"] != "returning"
        assert parts[700]["status"] == "flying"
        legs = [f for f in p["flights"] if f["cid"] == 700]
        assert any(f["in_air"] and not f.get("loaded") for f in legs)   # neuer Flug: Reservierung, kein Rückflug

    def test_multi_leg_loss_attached_once(self):
        """#23 Review I2: eine Mehrbein-Connection mit ZWEI nicht gelieferten Beinen (Hin+Rück,
        keins davon am Ziel) teilt denselben Verbindungs-Logon-Key -- der EINE gelatchte Verlust
        darf lost_kg nur EINMAL anheften, nicht auf jede passende Zeile."""
        conn = _make_conn()
        upsert_payload(conn, "C172", payload_kg=250)
        ev = _event(conn, route="EDWG,EDWY,EDXH", destination="EDXH")
        conn_logon = "2026-07-01T09:58:00Z"
        conn_logoff = "2026-07-01T11:35:00Z"
        self._insert_connection(conn, 1000, "FRS1000", "EDWG", "EDWG", conn_logon, conn_logoff,
                                duration_min=97)
        # Bein 1: EDWG -> EDWY (Zwischenlandung, nicht das Ziel).
        self._seed_leg(conn, 1000, "FRS1000", conn_logon, "EDWG")
        hin_landing = self._add_leg_landing(conn, 1000, "FRS1000", conn_logon, "EDWY")
        from app.geo import icao_to_coords
        wlat, wlon = icao_to_coords("EDWY")
        _add_pos(conn, 1000, _shift(hin_landing, 3), wlat, wlon, 5, alt=8, callsign="FRS1000")
        # Bein 2: EDWY -> EDWG (zurück, ebenfalls nicht das Ziel).
        self._seed_leg(conn, 1000, "FRS1000", _shift(hin_landing, 6), "EDWY")
        self._add_leg_landing(conn, 1000, "FRS1000", _shift(hin_landing, 6), "EDWG")
        conn.commit()

        # EIN Verlust für diese Connection latchen (Poller-Konvention: Verbindungs-Logon-Key).
        record_transport_loss(conn, ev["id"], 1000, conn_logon, "stolen", "C172", "FRS1000",
                              "EDWG", "EDWY", "2026-07-01T12:00:00Z")
        conn.commit()

        p = compute_transport_progress(conn, ev, "2026-07-01T12:30:00Z")
        legs = [f for f in p["flights"] if f["cid"] == 1000]
        assert len(legs) == 2
        assert sum(1 for f in legs if f.get("loss_kind")) == 1   # nur EINE Zeile trägt den Verlust
        assert p["lost_total_kg"] == 250    # nicht 500 (doppelt angeheftet)


class TestParticipants:
    def test_statuses_and_sums(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        # Pilot 400: geliefert (geschlossen am Ziel) + gerade wieder unterwegs (offen, Richtung Ziel)
        # Innerhalb des Event-Fensters (dtstart/dtend = START/END, 2026-07-01) — ein geschlossener
        # Flug wird über canonicalize_flights' end-Filter geladen, anders als offene Flüge/Losses.
        _add_delivered_flight(conn, 400, "EDWG", "C172", "2026-07-01T18:00:00Z", ev["id"], duration_min=25)
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

    def test_returning_pilot_disappears_after_landing_back_on_route(self):
        # #65 (Live-Fund 06.07., EDWG-EDXP-Test): eine als "Rückflug" erkannte Verbindung
        # (dep==destination laut Erstposition) bleibt oft OHNE Disconnect offen, auch nachdem
        # der Pilot wieder auf der Strecke (i. d. R. am Ursprung) gelandet ist -- "Rückflug"
        # blieb dann dauerhaft hängen. Eine aktuelle Live-Position am Boden auf der Strecke
        # muss den Teilnehmer aus der Live-Anzeige verschwinden lassen (fertig, nichts mehr
        # zu berichten), statt ewig "returning" zu zeigen.
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        _add_open_flight(conn, 401, "EDXH", "EDWG", "C172", "2026-07-01T19:05:00Z")
        # Live-Position: am Boden (gs < 2kt) bei EDWG (Streckenflugplatz, Ursprung) -- gelandet.
        conn.execute(
            "INSERT INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
            "VALUES (401, 'FRS401', 53.78278, 7.91389, 0)"
        )
        conn.commit()
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert 401 not in parts   # verschwunden, nicht mehr als "returning" hängen geblieben

    def test_returning_pilot_still_shown_while_still_airborne(self):
        # Gegenprobe: noch in der Luft (gs hoch) -> weiterhin "returning" wie gehabt.
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        _add_open_flight(conn, 401, "EDXH", "EDWG", "C172", "2026-07-01T19:05:00Z")
        conn.execute(
            "INSERT INTO live_positions (cid, callsign, latitude, longitude, groundspeed) "
            "VALUES (401, 'FRS401', 53.75, 7.87, 110)"
        )
        conn.commit()
        p = compute_transport_progress(conn, ev, "2026-07-01T19:30:00Z")
        parts = {x["cid"]: x for x in p["participants"]}
        assert parts[401]["status"] == "returning"

    def test_arrived_status_with_latch(self):
        conn = _make_conn()
        upsert_payload(conn, "C172", mtow_kg=1157, empty_kg=680, fuel_kg=100, crew_kg=85)
        ev = _event(conn, cargo=[{"name": "Inselpost", "target_kg": 1000.0}])
        _add_open_flight(conn, 402, "EDWG", "EDXH", "C172", "2026-07-02T18:05:00Z")
        set_transport_live_arrival(conn, 402, "2026-07-02T18:05:00Z", ev["id"], "2026-07-02T18:30:00Z")
        p = compute_transport_progress(conn, ev, "2026-07-02T19:00:00Z")
        assert p["participants"][0]["status"] == "arrived"

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
