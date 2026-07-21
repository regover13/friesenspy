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
from datetime import datetime, timedelta, timezone

from app.database import (
    compute_bummel_standings,
    get_connection,
    init_db,
    public_bummel_view,
)
from app.geo import airport_elevation_ft, icao_to_coords

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


_UNSET = object()


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
    logoff: str | None = _UNSET,
    callsign: str = "FRS123",
) -> None:
    """Schreibt eine Connection direkt in die flights-Tabelle.

    logon-Zeiten werden automatisch eindeutig gewählt (partieller Unique-Index). ``logoff``
    ohne Angabe bekommt einen Default-Zeitstempel (abgeschlossene Connection); explizit
    ``logoff=None`` übergeben lässt ``logoff_time`` NULL (Connection bleibt offen — z. B.
    „Frode", der nach der GPS-Landung nicht disconnected).
    """
    conn.execute(
        "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (?, ?, ?)",
        (cid, name, START),
    )
    if logon is None:
        _logon_counter[0] += 1
        logon = f"2026-06-27T1{_logon_counter[0] % 10}:0{_logon_counter[0] % 6}:00Z"
    if logoff is _UNSET:
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


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _fmt_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_realistic_track(
    conn: sqlite3.Connection,
    cid: int,
    dep_icao: str,
    arr_icao: str,
    start_ts: str,
    *,
    flight_min: int = 30,
    callsign: str = "FRS123",
) -> str:
    """Schreibt einen echten GPS-Track dep->arr in ``position_history`` — Muster wie
    ``tests/test_canonicalize_legs.py::_seed_eddk_eddw_track`` (ON_GROUND -> Steigflug ->
    Reiseflug -> Sinkflug -> Aufsetzen -> ON_GROUND), damit ``detect_gps_legs`` Start/Ziel
    tatsächlich erkennt (ein simpler 2-Punkt-Track ohne Höhen-/Speed-Änderung löst unter dem
    GPS-only-Detektor KEINEN Start/keine Landung aus).

    Gibt den ISO-Zeitpunkt des letzten geschriebenen Samples zurück.
    """
    dep = icao_to_coords(dep_icao)
    arr = icao_to_coords(arr_icao)
    assert dep and arr, f"Test-Flugplätze müssen auflösbar sein ({dep_icao}/{arr_icao})"
    dep_elev = airport_elevation_ft(dep_icao) or 0
    arr_elev = airport_elevation_ft(arr_icao) or 0
    t0 = _parse_iso(start_ts)
    mid_min = max(3, round(flight_min * 0.45))
    desc_min = max(mid_min + 1, flight_min - 6)
    touchdown_min = max(desc_min + 1, flight_min - 4)
    end_min = flight_min
    mid_lat = (dep[0] + arr[0]) / 2
    mid_lon = (dep[1] + arr[1]) / 2
    points = [
        (0, dep[0], dep[1], dep_elev, 0),
        (1, dep[0], dep[1], dep_elev, 5),
        (2, dep[0], dep[1], dep_elev + 900, 80),
        (mid_min, mid_lat, mid_lon, 5000, 120),
        (desc_min, arr[0], arr[1], arr_elev + 500, 60),
        (touchdown_min, arr[0], arr[1], arr_elev, 0),
    ]
    points.append((end_min, arr[0], arr[1], arr_elev, 0))
    last_ts = start_ts
    for off_min, lat, lon, alt, gs in points:
        ts = _fmt_iso(t0 + timedelta(minutes=off_min))
        last_ts = ts
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, "
            "groundspeed, heading, ts) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (cid, callsign, lat, lon, alt, gs, ts),
        )
    conn.commit()
    return last_ts


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
        assert anna["leg_count"] == 2          # zwei gewertete Legs
        # aircraft steckt auch im einzelnen Leg
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
    def test_reverse_complete_but_alternate_routing_incomplete(self):
        """Kanten-Modell: Rückwärts fliegen ist komplett (Richtung egal), ABER ein alternatives
        Routing über einen ANDEREN Streckenplatz (A→C→B) zerlegt die Etappe A–B → unvollständig
        (B1). Das ist die bewusste Abkehr vom alten Knoten-Modell."""
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        # Rückwärts geflogen (C→B→A) — deckt dieselben ungerichteten Kanten → komplett.
        _add_flight(conn, 100, "Rosa", "EDWR", "EDWG", 25)
        _add_flight(conn, 100, "Rosa", "EDWG", "EDWF", 25)
        # Alternatives Routing (A→C→B): Etappe EDWF–EDWG wird nie direkt geflogen.
        _add_flight(conn, 200, "Alf", "EDWF", "EDWR", 20)
        _add_flight(conn, 200, "Alf", "EDWR", "EDWG", 20)

        result = compute_bummel_standings(conn, route, START, END)

        rosa = _by_cid(result["complete"], 100)
        assert rosa is not None and rosa["total_min"] == 50
        alf = _by_cid(result["incomplete"], 200)
        assert alf is not None, "A→C→B fliegt EDWF–EDWG nie direkt → unvollständig"
        assert _edge("EDWF", "EDWG") in alf["missing"]


class TestIncomplete:
    def test_partial_tour_listed_with_missing_airport(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        _add_flight(conn, 100, "Tom", "EDWF", "EDWG", 30)  # nur ein Leg

        result = compute_bummel_standings(conn, route, START, END)

        assert result["complete"] == []
        assert result["count"] == 0
        tom = _by_cid(result["incomplete"], 100)
        assert tom is not None
        assert set(tom["visited"]) == {_edge("EDWF", "EDWG")}
        assert tom["missing"] == [_edge("EDWG", "EDWR")]


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
        # Komplette Tour (zwei Legs), danach Fremdflüge, die NICHT mitzählen.
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
    Blockzeiten der Tour-Legs — die Bodenzeit der Zwischenstopps zählt NICHT mit.
    """

    def test_intermediate_stop_counts_as_complete(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # EDWF -> EDDH (Zwischenstopp, nicht auf der Route) -> EDWG.
        # Kein einzelnes Route↔Route-Leg, aber die Tour beginnt an EDWF und endet an EDWG.
        _add_flight(conn, 100, "Stan", "EDWF", "EDDH", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:30:00Z")
        _add_flight(conn, 100, "Stan", "EDDH", "EDWG", 30,
                    logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:30:00Z")

        result = compute_bummel_standings(conn, route, START, END)

        stan = _by_cid(result["complete"], 100)
        assert stan is not None, "Tour mit Zwischenstopp muss komplett sein"
        assert set(stan["visited"]) == {_edge("EDWF", "EDWG")}
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
    """GPS-only Phase 2 (#23): die Endpunkt-Erkennung liegt jetzt vollständig bei
    ``canonicalize_legs`` (fester Radius ``_BUMMEL_AIRPORT_RADIUS_KM`` im Leg-Detektor selbst).
    Das race-eigene ``radius_km`` wirkt daher NICHT mehr auf die Wertung — es bleibt nur als
    Parameter für Aufrufer-Kompatibilität (``main.py`` reicht weiterhin ``race["radius_km"]``
    durch) erhalten, ist aber ein No-Op."""

    def test_radius_km_no_longer_affects_standings(self):
        conn = _make_conn()
        route = ["EDDH", "EDDM"]  # weit auseinander (~600 km) → eindeutige Zuordnung
        _add_flight(conn, 700, "Rudi", "EDDH", "EDDM", 60,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T12:00:00Z")
        _add_realistic_track(conn, 700, "EDDH", "EDDM", "2026-06-27T11:00:00Z",
                              flight_min=60, callsign="FRS123")

        default = compute_bummel_standings(conn, route, START, END)
        wide = compute_bummel_standings(conn, route, START, END, radius_km=50)

        # radius_km ist ein No-Op: identisches Ergebnis mit und ohne das Argument.
        rudi_default = _by_cid(default["complete"], 700)
        rudi_wide = _by_cid(wide["complete"], 700)
        assert rudi_default is not None
        assert rudi_wide is not None
        assert rudi_default["total_min"] == rudi_wide["total_min"]
        assert set(rudi_default["visited"]) == {_edge("EDDH", "EDDM")}


class TestBlockTimeSource:
    """GPS-only Phase 2 (#23): die Block-Zeit kommt jetzt ausschließlich aus ``block_min`` von
    ``canonicalize_legs`` (pro Leg aus der richtigen Positionsquelle gerechnet — position_history
    für FS, statsim_position_history für StatSim). ``total_sec`` ist dadurch bewusst nur noch
    minutengenau (Vielfaches von 60) statt wie zuvor sekundengenau aus einem cid-gebundenen
    ``position_history``-Zugriff, der für StatSim/offene Legs falsch war."""

    def test_total_sec_is_block_min_times_sixty(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        _add_flight(conn, 800, "Sven", "EDWF", "EDWG", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:31:00Z")
        _add_realistic_track(conn, 800, "EDWF", "EDWG", "2026-06-27T11:00:00Z",
                              flight_min=30, callsign="FRS123")

        sven = _by_cid(compute_bummel_standings(conn, route, START, END)["complete"], 800)
        assert sven is not None
        assert sven["total_sec"] == sven["total_min"] * 60
        assert sven["total_sec"] % 60 == 0

    def test_ties_broken_by_cid_when_block_min_equal(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]

        def add(cid, name):
            _add_flight(conn, cid, name, "EDWF", "EDWG", 30,
                        logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:40:00Z")

        # Kein GPS-Track: fallback auf das block_min der Connection (30 bei allen) —
        # ohne Sekunden-Feinauflösung entscheidet der finale cid-Tiebreak.
        add(812, "C")
        add(810, "A")
        add(811, "B")

        result = compute_bummel_standings(conn, route, START, END)
        assert {e["total_min"] for e in result["complete"]} == {30}
        assert {e["total_sec"] for e in result["complete"]} == {1800}
        assert [e["cid"] for e in result["complete"]] == [810, 811, 812]


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
        assert set(anna["visited"]) == {_edge("EDWF", "EDWG"), _edge("EDWG", "EDWR")}
        assert anna["aircraft"] == "C172"
        assert anna["leg_count"] == 2


class TestGpsPresence:
    def test_gps_corrects_flightplan_typo(self):
        """GPS erkennt EDWR, obwohl der Flugplan-ARR vertippt ist (Katastrophen-Schutz)."""
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]

        # Leg 1: EDWF→EDWG, Flugplan korrekt, echter GPS-Track an beiden Enden.
        _add_flight(conn, 100, "Eva", "EDWF", "EDWG", 30,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:30:00Z")
        _add_realistic_track(conn, 100, "EDWF", "EDWG", "2026-06-27T11:00:00Z",
                              flight_min=30, callsign="FRS123")
        # Leg 2: Flugplan-ARR vertippt ("EDXX"), aber der echte GPS-Track landet bei EDWR.
        _add_flight(conn, 100, "Eva", "EDWG", "EDXX", 30,
                    logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:30:00Z")
        _add_realistic_track(conn, 100, "EDWG", "EDWR", "2026-06-27T12:00:00Z",
                              flight_min=30, callsign="FRS123")

        result = compute_bummel_standings(conn, route, START, END)
        eva = _by_cid(result["complete"], 100)
        assert eva is not None, "GPS muss EDWR trotz Flugplan-Tippfehler erkennen"
        assert set(eva["visited"]) == {_edge("EDWF", "EDWG"), _edge("EDWG", "EDWR")}
        # Das vertippte Leg wird auf den echten Zielflugplatz korrigiert
        assert any(l["arrival"] == "EDWR" for l in eva["legs"])

    def test_no_gps_falls_back_to_flightplan(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        _add_flight(conn, 200, "Udo", "EDWF", "EDWG", 30)  # keine position_history
        result = compute_bummel_standings(conn, route, START, END)
        assert _by_cid(result["complete"], 200) is not None


class TestFrodeGpsLandingWithoutDisconnect:
    """Regression #23: „Frode" verschwand früher aus der Wertung, weil sein Flug bis zum
    Disconnect offen blieb (``canonicalize_flights`` wartet auf die Connection-``logoff_time``).
    Unter GPS-only (``canonicalize_legs``) wird die Landung direkt am Track erkannt — die
    Connection selbst bleibt bewusst offen (``logoff_time IS NULL`` in ``flights``, kein
    separater Refile/Disconnect-Trick), der Pilot ist im Spiel noch verbunden."""

    def test_gps_landing_counts_even_though_connection_stays_open(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # Connection bleibt technisch offen — Frode disconnected NICHT nach der Landung.
        _add_flight(conn, 900, "Frode", "EDWF", "EDWG", None,
                    logon="2026-06-27T11:00:00Z", logoff=None)
        _add_realistic_track(conn, 900, "EDWF", "EDWG", "2026-06-27T11:00:00Z",
                              flight_min=30, callsign="FRS123")

        result = compute_bummel_standings(conn, route, START, END)

        frode = _by_cid(result["complete"], 900)
        assert frode is not None, "GPS-Landung muss trotz offener Connection zählen"
        assert set(frode["visited"]) == {_edge("EDWF", "EDWG")}
        assert frode["total_min"] > 0
        assert frode["total_sec"] == frode["total_min"] * 60


class TestZwischenlandungGpsTrack:
    """Zwischenlandung mit echtem GPS-Track (nicht nur Flugplan-Fallback wie
    ``TestTourWithStops``): A -> Zwischenstopp (nicht auf der Route) -> B als eine Tour; die
    Bodenzeit am Zwischenstopp zählt nicht in die Blockzeit."""

    def test_intermediate_stop_via_gps_track_counts_as_complete_tour(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # EDWF -> EDDH (Zwischenstopp, nicht auf der Route) -> EDWG, je echter GPS-Track.
        _add_flight(conn, 950, "Stan", "EDWF", "EDDH", None,
                    logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:30:00Z")
        _add_realistic_track(conn, 950, "EDWF", "EDDH", "2026-06-27T11:00:00Z",
                              flight_min=30, callsign="FRS123")
        _add_flight(conn, 950, "Stan", "EDDH", "EDWG", None,
                    logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:30:00Z")
        _add_realistic_track(conn, 950, "EDDH", "EDWG", "2026-06-27T13:00:00Z",
                              flight_min=30, callsign="FRS123")

        result = compute_bummel_standings(conn, route, START, END)

        stan = _by_cid(result["complete"], 950)
        assert stan is not None, "Tour mit echtem GPS-Zwischenstopp muss komplett sein"
        assert set(stan["visited"]) == {_edge("EDWF", "EDWG")}
        assert stan["leg_count"] == 2
        # Reine Summe der beiden Block-Zeiten; die Bodenzeit in EDDH (11:xx–13:00) zählt NICHT.
        assert stan["total_sec"] == stan["legs"][0]["seconds"] + stan["legs"][1]["seconds"]


class TestFragmentMerge:
    def test_reconnect_fragments_of_one_leg_count_once(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR"]
        # Ein Leg EDWF→EDWG als zwei Fragmente (Reconnect, gleicher Flugplan, kleine Lücke).
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
        assert set(eva["visited"]) == {_edge("EDWF", "EDWG"), _edge("EDWG", "EDWR")}
        # 30 (gemergtes Leg) + 30 (zweites Leg) = 60
        assert eva["total_min"] == 60


def _edge(a: str, b: str) -> str:
    """Erwartete Kanten-Darstellung (ungerichtet, sortiert) — Spiegel der Implementierung."""
    x, y = sorted((a, b))
    return f"{x} ↔ {y}"


class TestHiddenOrderNoRankLeak:
    """Fairness: im VERDECKTEN Zustand darf die Teilnehmer-REIHENFOLGE das Ranking nicht verraten.
    `standings["complete"]` ist rang-sortiert (Nähe zum Schnitt) — würde man sie so durchreichen,
    liest man die Platzierung aus der Ordnung ab, obwohl Zeiten/Delta/Rang redigiert sind."""

    def test_hidden_participants_neutral_order_revealed_keeps_rank(self):
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        # avg(60,40,50)=50 → FRS555 (=50) Rang 1; FRS111/FRS999 je 10 weg (Tie → cid).
        _add_flight(conn, 100, "Zeb", "EDWF", "EDWG", 60, callsign="FRS999")
        _add_flight(conn, 200, "Amy", "EDWF", "EDWG", 40, callsign="FRS111")
        _add_flight(conn, 300, "Mimi", "EDWF", "EDWG", 50, callsign="FRS555")
        s = compute_bummel_standings(conn, route, START, END)
        assert [e["callsign"] for e in s["complete"]] == ["FRS555", "FRS111", "FRS999"]  # Rang

        hidden = public_bummel_view(s, in_progress=[], revealed=False)
        order = [p["callsign"] for p in hidden["participants"]]
        assert order == ["FRS111", "FRS555", "FRS999"]   # neutral (Callsign), NICHT Rang-Ordnung

        revealed = public_bummel_view(s, in_progress=[], revealed=True)
        assert revealed["complete"][0]["callsign"] == "FRS555"   # enthüllt weiter rang-sortiert


class TestRoundCourseEdges:
    """Kanten-basierte Wertung (Spec 2026-07-21): Route = geordnete Plätze-Kette mit Wiederholung
    → Pflicht-Etappen (ungerichtete Kanten-Multimenge). Komplett = jede Etappe geflogen. Der
    Rückweg eines Rundkurses ist eine eigene Pflicht-Etappe."""

    RING = ["EDWF", "EDWG", "EDWR", "EDWF"]   # Rundkurs A→B→C→A

    def test_full_round_is_complete(self):
        conn = _make_conn()
        _add_flight(conn, 100, "Ringo", "EDWF", "EDWG", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Ringo", "EDWG", "EDWR", 20, logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:20:00Z")
        _add_flight(conn, 100, "Ringo", "EDWR", "EDWF", 20, logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:20:00Z")
        result = compute_bummel_standings(conn, self.RING, START, END)
        ringo = _by_cid(result["complete"], 100)
        assert ringo is not None
        assert ringo["missing"] == []
        assert ringo["total_min"] == 60

    def test_round_without_return_is_incomplete(self):
        # KERNFALL gegen das alte Knoten-Modell: alle drei Plätze besucht, aber NICHT zurück.
        conn = _make_conn()
        _add_flight(conn, 100, "Nora", "EDWF", "EDWG", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Nora", "EDWG", "EDWR", 20, logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:20:00Z")
        result = compute_bummel_standings(conn, self.RING, START, END)
        assert _by_cid(result["complete"], 100) is None
        nora = _by_cid(result["incomplete"], 100)
        assert nora is not None
        assert nora["missing"] == [_edge("EDWR", "EDWF")]   # der Rückweg fehlt

    def test_reverse_round_is_complete(self):
        # Richtung egal: Dreieck andersherum deckt dieselben ungerichteten Kanten.
        conn = _make_conn()
        _add_flight(conn, 100, "Rev", "EDWF", "EDWR", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Rev", "EDWR", "EDWG", 20, logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:20:00Z")
        _add_flight(conn, 100, "Rev", "EDWG", "EDWF", 20, logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:20:00Z")
        result = compute_bummel_standings(conn, self.RING, START, END)
        assert _by_cid(result["complete"], 100) is not None

    def test_offroute_stop_still_completes_edge(self):
        # Weg erlaubt: Off-Route-Zwischenstopp EDDH innerhalb einer Etappe zerlegt sie NICHT.
        conn = _make_conn()
        route = ["EDWF", "EDWG"]
        _add_flight(conn, 100, "Ossi", "EDWF", "EDDH", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Ossi", "EDDH", "EDWG", 20, logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:20:00Z")
        result = compute_bummel_standings(conn, route, START, END)
        ossi = _by_cid(result["complete"], 100)
        assert ossi is not None
        assert ossi["visited"] == [_edge("EDWF", "EDWG")]

    def test_route_airport_as_stop_breaks_edge(self):
        # B1: ein ANDERER Streckenplatz als Zwischenstopp zerlegt die Etappe.
        # route offen A,B,C,D; Pilot A→C→B→C→D: A–B nie direkt → unvollständig.
        conn = _make_conn()
        route = ["EDWF", "EDWG", "EDWR", "EDWI"]
        _add_flight(conn, 100, "Break", "EDWF", "EDWR", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Break", "EDWR", "EDWG", 20, logon="2026-06-27T12:00:00Z", logoff="2026-06-27T12:20:00Z")
        _add_flight(conn, 100, "Break", "EDWG", "EDWR", 20, logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:20:00Z")
        _add_flight(conn, 100, "Break", "EDWR", "EDWI", 20, logon="2026-06-27T14:00:00Z", logoff="2026-06-27T14:20:00Z")
        result = compute_bummel_standings(conn, route, START, END)
        brk = _by_cid(result["incomplete"], 100)
        assert brk is not None
        assert _edge("EDWF", "EDWG") in brk["missing"]

    def test_gap_between_legs_no_phantom_edge(self):
        # A1: Lücke zwischen Legs (arr≠dep des Folgelegs) bildet KEINE Kante.
        # Ring A,B,C,A; Pilot A→B, dann (Lücke) C→A. B–C nie geflogen → unvollständig.
        conn = _make_conn()
        _add_flight(conn, 100, "Gap", "EDWF", "EDWG", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        _add_flight(conn, 100, "Gap", "EDWR", "EDWF", 20, logon="2026-06-27T13:00:00Z", logoff="2026-06-27T13:20:00Z")
        result = compute_bummel_standings(conn, self.RING, START, END)
        assert _by_cid(result["complete"], 100) is None
        gap = _by_cid(result["incomplete"], 100)
        assert gap is not None
        assert _edge("EDWG", "EDWR") in gap["missing"]

    def test_display_route_keeps_repeat(self):
        # Anzeige-Route roh (mit Wiederholung), nicht dedupliziert.
        conn = _make_conn()
        result = compute_bummel_standings(conn, self.RING, START, END)
        assert result["route"] == ["EDWF", "EDWG", "EDWR", "EDWF"]

    def test_consecutive_duplicate_sanitized(self):
        # A2: aufeinanderfolgende Duplikate raus → keine unerfüllbare Selbstkante.
        conn = _make_conn()
        _add_flight(conn, 100, "San", "EDWF", "EDWG", 20, logon="2026-06-27T11:00:00Z", logoff="2026-06-27T11:20:00Z")
        result = compute_bummel_standings(conn, ["EDWF", "EDWF", "EDWG"], START, END)
        assert result["route"] == ["EDWF", "EDWG"]
        assert _by_cid(result["complete"], 100) is not None   # A→B erfüllt einzige Etappe
