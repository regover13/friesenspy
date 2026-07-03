"""Tests für app/gps_legs.py — reiner GPS-Leg-Detektor, ein synthetischer Track je Edge-Case.

Airport-Auflösung wird über deterministische Fakes injiziert (DB-frei).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.geo import haversine
from app.gps_legs import detect_gps_legs

# Test-Flugplätze: icao -> (lat, lon, elevation_ft)
AIRPORTS = {
    "EDDA": (52.0, 8.0, 100.0),
    "EDDB": (53.5, 9.5, 200.0),
    "EDDC": (55.0, 11.0, 150.0),
    "EDDX": (50.0, 7.0, 300.0),
    # Zwei dicht beieinander liegende Plätze (~5,5 km auseinander):
    "EDDP": (48.0, 11.0, 500.0),
    "EDDQ": (48.05, 11.0, 480.0),
}

_BASE = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def _ts(sec: int) -> str:
    return (_BASE + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def p(sec: int, lat: float, lon: float, alt, gs) -> dict:
    return {"ts": _ts(sec), "latitude": lat, "longitude": lon, "altitude": alt, "groundspeed": gs}


def fake_nearest(lat, lon, max_km):
    best, best_d = None, max_km
    for icao, (alat, alon, _elev) in AIRPORTS.items():
        d = haversine(lat, lon, alat, alon)
        if d <= best_d:
            best, best_d = icao, d
    return best


def fake_elev(icao):
    a = AIRPORTS.get(icao)
    return a[2] if a else None


def run(samples):
    return detect_gps_legs(
        samples,
        nearest_airport=fake_nearest,
        airport_elev_ft=fake_elev,
        radius_km=10.0,
        gap_minutes=30,
    )


class TestDetectGpsLegs:
    def test_normal_a_to_b(self):
        """Normaler Flug A→B: 1 Leg, dep=A, arr=B, complete."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 0),
            p(30, 52.1, 8.05, 700, 60),     # Abheben (700-100=600>500)
            p(120, 52.7, 8.7, 5000, 150),   # Reiseflug
            p(240, 53.4, 9.4, 800, 90),     # Anflug B (noch airborne)
            p(300, 53.5, 9.5, 300, 40),     # Sinkflug nahe B, gs 40 (keine Landung)
            p(330, 53.5, 9.5, 200, 0),      # Aufsetzen B
            p(390, 53.5, 9.5, 200, 0),      # Dwell 60 s
            p(450, 53.5, 9.5, 200, 0),      # Dwell 120 s
            p(540, 53.5, 9.5, 200, 0),      # Dwell 210 s > 180 → endgültig
        ]
        legs = run(track)
        assert len(legs) == 1
        leg = legs[0]
        assert leg["dep_icao"] == "EDDA"
        assert leg["arr_icao"] == "EDDB"
        assert leg["complete"] is True
        assert leg["dep_source"] == "gps"
        assert leg["arr_source"] == "gps"
        assert leg["takeoff_ts"] == _ts(30)
        assert leg["landing_ts"] == _ts(330)
        assert leg["max_altitude"] == 5000
        assert set(leg.keys()) == {
            "dep_icao", "arr_icao", "takeoff_ts", "landing_ts",
            "complete", "dep_source", "arr_source", "max_altitude",
        }

    def test_realistic_gradual_climb(self):
        """Realistischer Steigflug ~170 ft/Sample (C172, ~680 fpm): Boden-Referenz darf
        NICHT mitklettern, sonst hebt kein normal steigendes Flugzeug je ab. 1 Leg A→B."""
        track = [
            p(0, 52.0, 8.0, 100, 0),        # Boden A
            p(15, 52.0, 8.0, 100, 0),       # Boden A
            p(30, 52.01, 8.01, 300, 40),    # Steig +200 (kumuliert 200), nahe A
            p(45, 52.02, 8.02, 500, 55),    # +200 (kumuliert 400, <500), nahe A
            p(60, 52.03, 8.03, 700, 70),    # +200 (kumuliert 600 > 500 → abgehoben), nahe A
            p(75, 52.05, 8.05, 900, 80),    # kein Sample springt je > 500 ft
            p(90, 52.10, 8.10, 1100, 90),
            p(120, 52.30, 8.40, 1500, 120),
            p(150, 52.60, 8.70, 2000, 130), # +500 (nicht > 500)
            p(180, 52.90, 9.00, 2500, 130), # Reiseflug
            p(240, 53.20, 9.30, 1500, 110), # Sinkflug (abwärts, triggert kein Abheben)
            p(270, 53.40, 9.45, 700, 70),
            p(300, 53.5, 9.5, 200, 0),      # Aufsetzen B
            p(360, 53.5, 9.5, 200, 0),
            p(420, 53.5, 9.5, 200, 0),
            p(510, 53.5, 9.5, 200, 0),      # Dwell > 180 → endgültig
        ]
        legs = run(track)
        assert len(legs) == 1
        leg = legs[0]
        assert leg["dep_icao"] == "EDDA"
        assert leg["arr_icao"] == "EDDB"
        assert leg["complete"] is True
        assert leg["takeoff_ts"] == _ts(60)   # erstes Sample mit kumuliertem Anstieg > 500 ft

    def test_two_legs_a_b_c(self):
        """Zwischenlandung ohne Refile: A→B→C = 2 Legs."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 0),
            p(30, 52.1, 8.05, 700, 60),     # Abheben A
            p(120, 52.7, 8.7, 5000, 150),
            p(240, 53.5, 9.5, 200, 0),      # Landung B
            p(300, 53.5, 9.5, 200, 0),
            p(360, 53.5, 9.5, 200, 0),
            p(450, 53.5, 9.5, 200, 0),      # Dwell > 180 → Leg1 endgültig
            p(480, 53.6, 9.6, 900, 60),     # Abheben B (900-200=700>500)
            p(600, 54.3, 10.3, 5000, 150),
            p(720, 55.0, 11.0, 150, 0),     # Landung C
            p(780, 55.0, 11.0, 150, 0),
            p(840, 55.0, 11.0, 150, 0),
            p(930, 55.0, 11.0, 150, 0),     # Dwell > 180 → Leg2 endgültig
        ]
        legs = run(track)
        assert len(legs) == 2
        assert legs[0]["dep_icao"] == "EDDA"
        assert legs[0]["arr_icao"] == "EDDB"
        assert legs[0]["complete"] is True
        assert legs[1]["dep_icao"] == "EDDB"
        assert legs[1]["arr_icao"] == "EDDC"
        assert legs[1]["complete"] is True

    def test_circuit_x_to_x(self):
        """Platzrunde X→X: 1 Leg, dep=X, arr=X."""
        track = [
            p(0, 50.0, 7.0, 300, 0),
            p(15, 50.0, 7.0, 300, 0),
            p(30, 50.05, 7.05, 900, 60),    # Abheben (900-300=600>500)
            p(120, 50.3, 7.3, 4000, 120),
            p(240, 50.0, 7.0, 300, 0),      # Landung X
            p(300, 50.0, 7.0, 300, 0),
            p(360, 50.0, 7.0, 300, 0),
            p(450, 50.0, 7.0, 300, 0),      # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["dep_icao"] == "EDDX"
        assert legs[0]["arr_icao"] == "EDDX"
        assert legs[0]["complete"] is True

    def test_stop_and_go_merge(self):
        """Vollstopp mit erneutem Abheben binnen 180 s → 1 Leg (eine Session)."""
        track = [
            p(0, 50.0, 7.0, 300, 0),
            p(15, 50.0, 7.0, 300, 0),
            p(30, 50.02, 7.05, 900, 60),    # Abheben
            p(90, 50.0, 7.0, 300, 0),       # Aufsetzen X (tentativ)
            p(120, 50.02, 7.05, 900, 60),   # erneutes Abheben (900-300=600>500) binnen 30 s
            p(210, 50.0, 7.0, 300, 0),      # erneut Aufsetzen X
            p(270, 50.0, 7.0, 300, 0),
            p(330, 50.0, 7.0, 300, 0),
            p(420, 50.0, 7.0, 300, 0),      # Dwell > 180 → endgültig
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["dep_icao"] == "EDDX"
        assert legs[0]["arr_icao"] == "EDDX"
        assert legs[0]["complete"] is True

    def test_go_around_never_below_2kt(self):
        """Go-around / Touch-and-Go (gs nie < 2) → keine Fehl-Landung, 1 Leg."""
        track = [
            p(0, 50.0, 7.0, 300, 0),
            p(15, 50.0, 7.0, 300, 0),
            p(30, 50.05, 7.05, 900, 60),    # Abheben
            p(120, 50.3, 7.3, 4000, 120),
            p(200, 50.0, 7.0, 500, 45),     # Low-Pass über X, gs 45 (keine Landung)
            p(260, 50.3, 7.3, 3000, 120),   # Durchstarten
            p(360, 50.05, 7.05, 600, 40),   # erneuter Anflug
            p(420, 50.0, 7.0, 300, 0),      # endgültiges Aufsetzen X
            p(480, 50.0, 7.0, 300, 0),
            p(540, 50.0, 7.0, 300, 0),
            p(620, 50.0, 7.0, 300, 0),      # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["dep_icao"] == "EDDX"
        assert legs[0]["arr_icao"] == "EDDX"
        assert legs[0]["complete"] is True

    def test_spawn_in_air(self):
        """Spawn in der Luft: dep=None, aber Landung wird erkannt."""
        track = [
            p(0, 52.7, 8.7, 5000, 150),     # bereits airborne (gs 150 >= 50)
            p(120, 53.5, 9.5, 200, 0),      # Landung B
            p(180, 53.5, 9.5, 200, 0),
            p(240, 53.5, 9.5, 200, 0),
            p(330, 53.5, 9.5, 200, 0),      # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["dep_icao"] is None
        assert legs[0]["dep_source"] is None
        assert legs[0]["arr_icao"] == "EDDB"
        assert legs[0]["complete"] is True
        assert legs[0]["takeoff_ts"] == _ts(0)

    def test_ghost_never_airborne(self):
        """Nie abgehoben (nur Rollen) → keine Legs."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 10),
            p(30, 52.001, 8.001, 100, 15),
            p(45, 52.0, 8.0, 100, 0),
        ]
        legs = run(track)
        assert legs == []

    def test_heli_hover_over_airport_not_landing(self):
        """Heli-Hover gs<2 aber AGL>300 über Platz → KEINE Landung; Leg bleibt offen."""
        track = [
            p(0, 50.0, 7.0, 300, 0),
            p(15, 50.0, 7.0, 300, 5),
            p(30, 50.02, 7.0, 900, 20),     # Abheben via AGL (langsamer Heli, gs 20)
            p(90, 50.0, 7.0, 1000, 1),      # Hover über EDDX: gs<2 aber AGL=700 → keine Landung
            p(150, 50.0, 7.0, 1000, 0),     # weiter Hover
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["complete"] is False
        assert legs[0]["arr_icao"] is None
        assert legs[0]["dep_icao"] == "EDDX"

    def test_disconnect_mid_air(self):
        """Disconnect in der Luft → 1 unvollständiger Leg (complete=False, arr=None)."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 0),
            p(30, 52.1, 8.05, 700, 60),     # Abheben
            p(120, 52.7, 8.7, 5000, 150),   # Reiseflug, dann Ende (Disconnect)
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["complete"] is False
        assert legs[0]["arr_icao"] is None
        assert legs[0]["arr_source"] is None
        assert legs[0]["landing_ts"] is None
        assert legs[0]["dep_icao"] == "EDDA"

    def test_two_close_airports_nearest_wins(self):
        """Zwei dichte Plätze → der nähere gewinnt als arr."""
        track = [
            p(0, 48.0, 11.0, 500, 0),
            p(15, 48.0, 11.0, 500, 0),
            p(30, 48.05, 11.05, 1300, 60),  # Abheben (1300-500=800>500)
            p(120, 48.5, 11.5, 5000, 120),
            p(240, 48.01, 11.0, 500, 0),    # Landung dichter an EDDP als an EDDQ
            p(300, 48.01, 11.0, 500, 0),
            p(360, 48.01, 11.0, 500, 0),
            p(450, 48.01, 11.0, 500, 0),    # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["arr_icao"] == "EDDP"
        assert legs[0]["complete"] is True

    def test_track_gap_splits_legs(self):
        """Zeitlücke > 30 min teilt in getrennte Legs."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 0),
            p(30, 52.1, 8.05, 700, 60),     # Abheben A, dann Ende von Segment 1
            p(120, 52.7, 8.7, 5000, 150),
            # 40-min-Lücke:
            p(2520, 52.9, 8.9, 5000, 150),  # neues Segment: Spawn-in-Luft
            p(2600, 53.5, 9.5, 200, 0),     # Landung B
            p(2660, 53.5, 9.5, 200, 0),
            p(2720, 53.5, 9.5, 200, 0),
            p(2810, 53.5, 9.5, 200, 0),     # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 2
        # Segment 1 endet airborne → unvollständig:
        assert legs[0]["complete"] is False
        assert legs[0]["dep_icao"] == "EDDA"
        assert legs[0]["arr_icao"] is None
        # Segment 2: Spawn-in-Luft → Landung B:
        assert legs[1]["complete"] is True
        assert legs[1]["dep_icao"] is None
        assert legs[1]["arr_icao"] == "EDDB"

    def test_finalize_landing_on_end(self):
        """Aufsetzen und dann Disconnect (kein Re-Takeoff) → Landung wird endgültig."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 0),
            p(30, 52.1, 8.05, 700, 60),     # Abheben A
            p(120, 52.7, 8.7, 5000, 150),
            p(240, 53.5, 9.5, 200, 0),      # Aufsetzen B, dann Segment-Ende (Disconnect)
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["complete"] is True
        assert legs[0]["arr_icao"] == "EDDB"
        assert legs[0]["landing_ts"] == _ts(240)

    def test_unsorted_input(self):
        """Eingabe muss nicht sortiert sein — intern nach ts sortiert."""
        track = [
            p(330, 53.5, 9.5, 200, 0),
            p(30, 52.1, 8.05, 700, 60),
            p(0, 52.0, 8.0, 100, 0),
            p(240, 53.5, 9.5, 200, 0),
            p(120, 52.7, 8.7, 5000, 150),
            p(390, 53.5, 9.5, 200, 0),
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["dep_icao"] == "EDDA"
        assert legs[0]["arr_icao"] == "EDDB"
        assert legs[0]["complete"] is True

    def test_empty_positions(self):
        assert run([]) == []
