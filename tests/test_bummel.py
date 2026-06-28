"""Tests für die FriesenFliegerBummel-Wertung (compute_bummel_standings).

Bummel-Regel (bewusst robust): Es gewinnt, wer mit der Summe seiner Gate-to-Gate-Blockzeiten
am dichtesten an der Durchschnittszeit aller kompletten Touren liegt. Eine Tour ist komplett,
wenn der Pilot ALLE Flugplätze der Strecke besucht hat — Reihenfolge und Richtung egal.
Unvollständige Touren werden separat gelistet, niemals still verworfen.

Alle Tests mit In-Memory-DB (:memory:).
"""
from __future__ import annotations

import json
import sqlite3

from app.database import (
    compute_bummel_standings,
    get_connection,
    init_db,
    public_bummel_view,
)
from app.geo import icao_to_coords

START = "2026-06-27T10:00:00Z"
END = "2026-06-27T20:00:00Z"


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


_logon_counter = [0]


def _add_flight(
    conn: sqlite3.Connection,
    cid: int,
    name: str,
    dep: str,
    arr: str,
    block_min: int | None,
    *,
    duration_min: int = 30,
    distance_nm: float = 50.0,
    logon: str | None = None,
    logoff: str | None = None,
    callsign: str = "FRS123",
) -> None:
    """Schreibt einen abgeschlossenen Flug direkt in die flights-Tabelle.

    logon-Zeiten werden automatisch eindeutig gewählt (partieller Unique-Index).
    """
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, name, START),
    )
    if logon is None:
        _logon_counter[0] += 1
        logon = f"2026-06-27T1{_logon_counter[0] % 10}:0{_logon_counter[0] % 6}:00Z"
    if logoff is None:
        logoff = "2026-06-27T19:59:00Z"
    conn.execute(
        "INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
        "logon_time, logoff_time, duration_min, distance_nm, block_min) "
        "VALUES (?, ?, 'C172', ?, ?, ?, ?, ?, ?, ?)",
        (cid, callsign, dep, arr, logon, logoff, duration_min, distance_nm, block_min),
    )
    conn.commit()


def _by_cid(entries: list[dict], cid: int) -> dict | None:
    return next((e for e in entries if e["cid"] == cid), None)


def _add_position(conn, cid, lat, lon, ts, alt=300, gs=0):
    conn.execute(
        "INSERT INTO position_history (cid, latitude, longitude, altitude, groundspeed, heading, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, lat, lon, alt, gs, 0, ts),
    )
    conn.commit()


class TestRanking:
    def test_winner_is_closest_to_average(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        # Anna total 60, Bert total 100, Cara total 80 → Schnitt 80 → Cara gewinnt
        _add_flight(conn, 100, "Anna", "EDWF", "EDWG", 30)
        _add_flight(conn, 100, "Anna", "EDWG", "EDWR", 30)
        _add_flight(conn, 200, "Bert", "EDWF", "EDWG", 50)
        _add_flight(conn, 200, "Bert", "EDWG", "EDWR", 50)
        _add_flight(conn, 300, "Cara", "EDWF", "EDWG", 40)
        _add_flight(conn, 300, "Cara", "EDWG", "EDWR", 40)

        result = compute_bummel_standings(conn, route, START, END)

        assert result["average_min"] == 80
        assert result["count"] == 3
        assert result["incomplete"] == []
        complete = result["complete"]
        assert [e["cid"] for e in complete] == [300, 100, 200]
        assert complete[0]["rank"] == 1
        assert complete[0]["delta"] == 0
        assert complete[0]["total_min"] == 80
        assert _by_cid(complete, 100)["delta"] == 20
        assert _by_cid(complete, 200)["delta"] == 20

    def test_standing_exposes_aircraft_and_leg_count(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        _add_flight(conn, 100, "Anna", "EDWF", "EDWG", 30)
        _add_flight(conn, 100, "Anna", "EDWG", "EDWR", 30)

        result = compute_bummel_standings(conn, route, START, END)
        anna = _by_cid(result["complete"], 100)
        assert anna["aircraft"] == "C172"      # repräsentatives Muster
        assert anna["leg_count"] == 2          # zwei gewertete Beine
        # aircraft steckt auch im einzelnen Bein
        assert anna["legs"][0]["aircraft"] == "C172"

    def test_only_complete_tours_count_toward_average(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        _add_flight(conn, 100, "Anna", "EDWF", "EDWG", 30)
        _add_flight(conn, 100, "Anna", "EDWG", "EDWR", 30)  # total 60, komplett
        _add_flight(conn, 200, "Bert", "EDWF", "EDWG", 50)
        _add_flight(conn, 200, "Bert", "EDWG", "EDWR", 50)  # total 100, komplett
        _add_flight(conn, 300, "Cara", "EDWF", "EDWG", 999)  # unvollständig

        result = compute_bummel_standings(conn, route, START, END)

        assert result["average_min"] == 80  # (60+100)/2 — Cara zählt NICHT
        assert result["count"] == 2
        assert [e["cid"] for e in result["complete"]] == [100, 200]
        assert _by_cid(result["incomplete"], 300) is not None


class TestDirectionAndOrderAgnostic:
    def test_reverse_and_alternate_routing_count_as_complete(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        # Rückwärts geflogen
        _add_flight(conn, 100, "Rosa", "EDWR", "EDWG", 25)
        _add_flight(conn, 100, "Rosa", "EDWG", "EDWF", 25)
        # Alternatives Routing (A→C→B)
        _add_flight(conn, 200, "Alf", "EDWF", "EDWR", 20)
        _add_flight(conn, 200, "Alf", "EDWR", "EDWG", 20)

        result = compute_bummel_standings(conn, route, START, END)

        assert result["incomplete"] == []
        assert result["count"] == 2
        assert _by_cid(result["complete"], 100)["total_min"] == 50
        assert _by_cid(result["complete"], 200)["total_min"] == 40


class TestIncomplete:
    def test_partial_tour_listed_with_missing_airport(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        _add_flight(conn, 100, "Tom", "EDWF", "EDWG", 30)  # nur ein Bein

        result = compute_bummel_standings(conn, route, START, END)

        assert result["complete"] == []
        assert result["count"] == 0
        tom = _by_cid(result["incomplete"], 100)
        assert tom is not None
        assert set(tom["visited"]) == {"EDWF", "EDWG"}
        assert tom["missing"] == ["EDWR"]


class TestTimeMetric:
    def test_block_min_fallback_to_duration_min(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # block_min NULL → duration_min (45) zählt
        _add_flight(conn, 100, "Nina", "EDWF", "EDWG", None, duration_min=45)

        result = compute_bummel_standings(conn, route, START, END)

        nina = _by_cid(result["complete"], 100)
        assert nina is not None
        assert nina["total_min"] == 45

    def test_flights_outside_route_are_ignored(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        # Komplette Tour (zwei Beine), danach Fremdflüge, die NICHT mitzählen.
        # Explizite Zeiten: die Fremdflüge liegen klar NACH dem Tour-Ende.
        _add_flight(conn, 100, "Udo", "EDWF", "EDWG", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:30:00Z")
        _add_flight(conn, 100, "Udo", "EDWG", "EDWR", 30,
                    logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:30:00Z")  # total 60
        # Flug komplett außerhalb der Strecke, nach der Tour — darf NICHT mitzählen
        _add_flight(conn, 100, "Udo", "EDDH", "EDDW", 99, distance_nm=300,
                    logon="2026-06-27T14:00:00Z", logoff="2026-06-27T14:40:00Z")
        # Flug mit nur einem Endpunkt in der Strecke, nach der Tour — darf NICHT mitzählen
        _add_flight(conn, 100, "Udo", "EDWG", "EDDH", 77, distance_nm=200,
                    logon="2026-06-27T15:00:00Z", logoff="2026-06-27T15:40:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        udo = _by_cid(result["complete"], 100)
        assert udo is not None
        assert udo["total_min"] == 60


class TestTourWithStops:
    """Bummel = gemütlich: Zwischenlandungen brechen die Wertung nicht (track-/tour-basiert).

    Eine Tour zählt vom ersten Start an einem Routenplatz bis zum letzten Ziel an einem
    Routenplatz; Zwischenstopps dazwischen sind erlaubt. Gewertet wird die Summe der reinen
    Blockzeiten der Tour-Beine — die Bodenzeit der Zwischenstopps zählt NICHT mit.
    """

    def test_intermediate_stop_counts_as_complete(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # EDWF -> EDDH (Zwischenstopp, nicht auf der Route) -> EDWG.
        # Kein einzelnes Route↔Route-Bein, aber die Tour beginnt an EDWF und endet an EDWG.
        _add_flight(conn, 100, "Stan", "EDWF", "EDDH", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:30:00Z")
        _add_flight(conn, 100, "Stan", "EDDH", "EDWG", 30,
                    logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:30:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        stan = _by_cid(result["complete"], 100)
        assert stan is not None, "Tour mit Zwischenstopp muss komplett sein"
        assert set(stan["visited"]) == {"EDWF", "EDWG"}
        # Summe der reinen Blockzeiten (30+30); die Bodenzeit in EDDH (11:30–13:00) zählt NICHT.
        assert stan["total_min"] == 60

    def test_legs_after_tour_end_are_excluded(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        _add_flight(conn, 100, "Udo", "EDWF", "EDWG", 40,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:40:00Z")
        # Späterer Flug NACH dem Tour-Ende (z. B. Platzrunde) — zählt nicht
        _add_flight(conn, 100, "Udo", "EDWG", "EDDH", 99,
                    logon="2026-06-27T15:00:00Z", logoff="2026-06-27T16:00:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        udo = _by_cid(result["complete"], 100)
        assert udo is not None
        assert udo["total_min"] == 40


class TestEarlyStart:
    """Frühstarter: Flug beginnt vor Event-Start, ist aber im Fenster unterwegs → volle Blockzeit."""

    def test_flight_started_before_window_counts(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # logon 09:40 < START (10:00), logoff 10:20 liegt im Fenster → überlappt
        _add_flight(conn, 600, "Frieda", "EDWF", "EDWG", 40,
                    logon="2026-06-27T09:40:00Z", logoff="2026-06-27T10:20:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        frieda = _by_cid(result["complete"], 600)
        assert frieda is not None, "Frühstarter im Fenster muss gewertet werden"
        assert frieda["total_min"] == 40  # volle Blockzeit, auch der Teil vor 10:00

    def test_pure_pre_event_flight_excluded(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # komplett vor dem Fenster (logoff 09:50 < START 10:00) → keine Überlappung
        _add_flight(conn, 601, "Vera", "EDWF", "EDWG", 30,
                    logon="2026-06-27T08:00:00Z", logoff="2026-06-27T09:50:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        assert _by_cid(result["complete"], 601) is None
        assert _by_cid(result["incomplete"], 601) is None


class TestRadiusParam:
    """Das pro Rennen gesetzte radius_km steuert die GPS-Zuordnung von Start/Ziel."""

    def test_larger_radius_assigns_distant_position(self):
        conn = _make_conn()
        route = ["EDDH", "EDDM"]  # weit auseinander (~600 km) → eindeutige Zuordnung
        h, m = icao_to_coords("EDDH"), icao_to_coords("EDDM")
        assert h and m, "Test-Flugplätze müssen auflösbar sein"
        # Flugplan-Ziel vertippt ("EDXX"); GPS endet ~16 km neben EDDM.
        _add_flight(conn, 700, "Rudi", "EDDH", "EDXX", 60,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T12:00:00Z")
        _add_position(conn, 700, h[0], h[1], "2026-06-27T11:00:00Z")
        _add_position(conn, 700, m[0] + 0.15, m[1], "2026-06-27T12:00:00Z")  # ~16,7 km

        # Default-Radius (10 km): 16 km zu weit → Ziel bleibt der Tippfehler → nicht gewertet
        narrow = compute_bummel_standings(conn, route, START, END)
        assert _by_cid(narrow["complete"], 700) is None
        assert _by_cid(narrow["incomplete"], 700) is None

        # Renn-Radius 50 km: GPS ordnet EDDM zu → komplette Tour
        wide = compute_bummel_standings(conn, route, START, END, radius_km=50)
        rudi = _by_cid(wide["complete"], 700)
        assert rudi is not None, "Mit größerem Radius muss EDDM erkannt werden"
        assert set(rudi["visited"]) == {"EDDH", "EDDM"}
        assert rudi["total_min"] == 60


class TestSecondPrecision:
    """Block-Gesamtzeit bleibt in Minuten, aber der Abstand ist sekundengenau (Tiebreak)."""

    def test_total_sec_from_gps_track(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        f, g = icao_to_coords("EDWF"), icao_to_coords("EDWG")
        # block_min in der DB ist 30, der GPS-Track aber 30:50 lang.
        _add_flight(conn, 800, "Sven", "EDWF", "EDWG", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:31:00Z")
        _add_position(conn, 800, f[0], f[1], "2026-06-27T11:00:00Z", gs=120)
        _add_position(conn, 800, g[0], g[1], "2026-06-27T11:30:50Z", gs=120)

        sven = _by_cid(compute_bummel_standings(conn, route, START, END)["complete"], 800)
        assert sven["total_sec"] == 1850  # 30:50 sekundengenau aus dem Track
        assert sven["total_min"] == 30     # Minuten-Anzeige bleibt

    def test_seconds_break_minute_tie(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        f, g = icao_to_coords("EDWF"), icao_to_coords("EDWG")

        def add(cid, name, last_ts):
            _add_flight(conn, cid, name, "EDWF", "EDWG", 30,
                        logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:40:00Z")
            _add_position(conn, cid, f[0], f[1], "2026-06-27T11:00:00Z", gs=120)
            _add_position(conn, cid, g[0], g[1], last_ts, gs=120)

        add(810, "A", "2026-06-27T11:30:00Z")  # 1800 s
        add(811, "B", "2026-06-27T11:30:40Z")  # 1840 s
        add(812, "C", "2026-06-27T11:30:20Z")  # 1820 s = exakt der Schnitt

        result = compute_bummel_standings(conn, route, START, END)
        # average_sec = (1800+1840+1820)/3 = 1820 → C exakt → Sieger trotz gleicher Minuten
        assert result["complete"][0]["cid"] == 812
        assert result["complete"][0]["delta_sec"] == 0
        assert {e["total_min"] for e in result["complete"]} == {30}  # alle nominell 30 min


class TestPublicView:
    """Fairness-Verdeckung: vor Enthüllung dürfen KEINE Zeiten/Schnitt/Ränge im JSON stehen."""

    def _standings(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        _add_flight(conn, 100, "Anna", "EDWF", "EDWG", 30)
        _add_flight(conn, 100, "Anna", "EDWG", "EDWR", 30)   # komplett
        _add_flight(conn, 500, "Emil", "EDWF", "EDWG", 35)   # unvollständig
        return compute_bummel_standings(conn, route, START, END)

    def test_participant_count_present(self):
        s = self._standings()
        assert s["participant_count"] == 2

    def test_revealed_shows_full(self):
        s = self._standings()
        view = public_bummel_view(s, in_progress=[], revealed=True)
        assert view["revealed"] is True
        assert "average_min" in view
        assert view["complete"][0]["total_min"] == 60
        assert "rank" in view["complete"][0]

    def test_hidden_redacts_all_times(self):
        s = self._standings()
        view = public_bummel_view(s, in_progress=[], revealed=False)
        assert view["revealed"] is False
        # Keine aggregierten Zeit-/Rang-Felder
        for forbidden in ("average_min", "complete", "incomplete", "count"):
            assert forbidden not in view
        # Teilnehmerliste vorhanden, aber ohne Zeit-/Rang-/nm-Felder
        parts = view["participants"]
        assert {p["cid"] for p in parts} == {100, 500}
        blob = json.dumps(view)
        for leak in ("total_min", "block_min", "delta", "rank", "average", "distance"):
            assert leak not in blob, f"Leak: {leak} steht im redigierten JSON"
        anna = _by_cid(parts, 100)
        assert set(anna["visited"]) == {"EDWF", "EDWG", "EDWR"}
        assert anna["aircraft"] == "C172"
        assert anna["leg_count"] == 2


class TestGpsPresence:
    def test_gps_corrects_flightplan_typo(self):
        """GPS erkennt EDWR, obwohl der Flugplan-ARR vertippt ist (Katastrophen-Schutz)."""
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        f, g, r = icao_to_coords("EDWF"), icao_to_coords("EDWG"), icao_to_coords("EDWR")
        assert f and g and r, "Test-Flugplätze müssen auflösbar sein"

        # Bein 1: EDWF→EDWG, Flugplan korrekt, GPS an beiden Enden
        _add_flight(conn, 100, "Eva", "EDWF", "EDWG", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:30:00Z")
        _add_position(conn, 100, f[0], f[1], "2026-06-27T11:00:00Z")
        _add_position(conn, 100, g[0], g[1], "2026-06-27T11:30:00Z")
        # Bein 2: Flugplan-ARR vertippt ("EDXX"), aber GPS landet bei EDWR
        _add_flight(conn, 100, "Eva", "EDWG", "EDXX", 30,
                    logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:30:00Z")
        _add_position(conn, 100, g[0], g[1], "2026-06-27T12:00:00Z")
        _add_position(conn, 100, r[0], r[1], "2026-06-27T12:30:00Z")

        result = compute_bummel_standings(conn, route, START, END)
        eva = _by_cid(result["complete"], 100)
        assert eva is not None, "GPS muss EDWR trotz Flugplan-Tippfehler erkennen"
        assert set(eva["visited"]) == {"EDWF", "EDWG", "EDWR"}
        assert eva["total_min"] == 60
        # Das vertippte Bein wird auf den echten Zielflugplatz korrigiert
        assert any(l["arrival"] == "EDWR" for l in eva["legs"])

    def test_no_gps_falls_back_to_flightplan(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        _add_flight(conn, 200, "Udo", "EDWF", "EDWG", 30)  # keine position_history
        result = compute_bummel_standings(conn, route, START, END)
        assert _by_cid(result["complete"], 200) is not None


class TestFragmentMerge:
    def test_reconnect_fragments_of_one_leg_count_once(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        # Ein Bein EDWF→EDWG als zwei Fragmente (Reconnect, gleicher Flugplan, kleine Lücke).
        # canonicalize_flights/merge_fragmented_flights führt sie zu einem Flug zusammen,
        # block_min wird summiert (20+10=30).
        _add_flight(conn, 100, "Eva", "EDWF", "EDWG", 20,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Eva", "EDWF", "EDWG", 10,
                    logon="2026-06-27T11:21:00Z", logoff="2026-06-27T11:35:00Z")
        _add_flight(conn, 100, "Eva", "EDWG", "EDWR", 30,
                    logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:35:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        eva = _by_cid(result["complete"], 100)
        assert eva is not None
        assert set(eva["visited"]) == {"EDWF", "EDWG", "EDWR"}
        # 30 (gemergtes Bein) + 30 (zweites Bein) = 60
        assert eva["total_min"] == 60
