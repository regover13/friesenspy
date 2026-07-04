"""Tests für app/gps_legs.py — reiner GPS-Leg-Detektor, ein synthetischer Track je Edge-Case.

Airport-Auflösung wird über deterministische Fakes injiziert (DB-frei).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.geo import haversine
from app.gps_legs import collapse_same_airport, detect_gps_legs

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
            "complete", "dep_source", "arr_source", "max_altitude", "segment",
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
        # #v8.1.0: Abheben jetzt auch über „gs>50 UND steigend" — bei _ts(45) ist die C172 mit
        # 55 kt durch 400 ft AGL steigend eindeutig in der Luft (früher/genauer als die reine
        # 500-ft-Schwelle, die erst bei _ts(60) griff). Die geschützte Eigenschaft (verankerte
        # Boden-Referenz → ein gradueller Steigflug hebt überhaupt ab, 1 Leg A→B) bleibt.
        assert leg["takeoff_ts"] == _ts(45)

    def test_fast_aircraft_takeoff_triggers_before_500ft(self):
        """Schnelles Flugzeug: gs>50 UND steigend (AGL>100) → Abheben FRÜHER als bei 500 ft."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 0),        # Boden A (prev_alt=100)
            p(30, 52.02, 8.02, 250, 80),     # gs 80 + steigend, AGL 150 (<500) → Abheben HIER
            p(45, 52.05, 8.05, 700, 100),    # AGL 600 (alte Logik hätte erst hier getriggert)
            p(120, 52.7, 8.7, 5000, 150),
            p(240, 53.5, 9.5, 200, 0),       # Landung B
            p(300, 53.5, 9.5, 200, 0),
            p(360, 53.5, 9.5, 200, 0),
            p(450, 53.5, 9.5, 200, 0),       # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["takeoff_ts"] == _ts(30)
        assert legs[0]["dep_icao"] == "EDDA"
        assert legs[0]["arr_icao"] == "EDDB"

    def test_ground_roll_high_gs_no_climb_no_takeoff(self):
        """Startlauf/abgebrochener Start: gs>50 aber Höhe flach (nicht steigend) → KEIN Abheben,
        erst wenn AGL > 500 (kein Geisterflug aus reinem Boden-Speed)."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 5),
            p(30, 52.005, 8.0, 100, 60),     # gs 60, aber alt flach (AGL 0) → KEIN Abheben
            p(45, 52.010, 8.0, 100, 70),     # gs 70, alt flach → KEIN Abheben
            p(60, 52.02, 8.02, 700, 90),     # AGL 600 > 500 → Abheben HIER
            p(120, 52.7, 8.7, 5000, 150),
            p(240, 53.5, 9.5, 200, 0),
            p(300, 53.5, 9.5, 200, 0),
            p(360, 53.5, 9.5, 200, 0),
            p(450, 53.5, 9.5, 200, 0),
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["takeoff_ts"] == _ts(60)

    def test_slow_wilga_takeoff_via_altitude_only(self):
        """Langsame Wilga (<40 kt): gs-Trigger greift nie → Abheben allein über die 500-ft-Höhe."""
        track = [
            p(0, 52.0, 8.0, 100, 0),
            p(15, 52.0, 8.0, 100, 5),
            p(30, 52.005, 8.005, 300, 30),   # gs 30, AGL 200 (<500, gs<50) → noch kein Abheben
            p(45, 52.010, 8.010, 500, 35),   # AGL 400 (<500), gs 35 → noch kein Abheben
            p(60, 52.02, 8.02, 700, 38),     # AGL 600 > 500 → Abheben (nur über Höhe)
            p(120, 52.7, 8.7, 3000, 40),
            p(240, 53.5, 9.5, 200, 0),
            p(300, 53.5, 9.5, 200, 0),
            p(360, 53.5, 9.5, 200, 0),
            p(450, 53.5, 9.5, 200, 0),
        ]
        legs = run(track)
        assert len(legs) == 1
        assert legs[0]["takeoff_ts"] == _ts(60)

    def test_retakeoff_after_fullstop_via_gs_trigger(self):
        """Wieder-Abheben nach Vollstopp am selben Platz über den NEUEN gs+steigend-Trigger
        (unter 500 ft): der prev_alt-Reset bei Landung muss den Trigger sauber neu scharfstellen."""
        track = [
            p(0, 50.0, 7.0, 300, 0),
            p(15, 50.0, 7.0, 300, 0),
            p(30, 50.02, 7.05, 900, 60),    # Abheben 1 (AGL 600 > 500)
            p(90, 50.0, 7.0, 300, 0),       # Aufsetzen X → Leg 1 final, prev_alt=300
            p(120, 50.01, 7.02, 450, 80),   # Wieder-Abheben: gs 80 + steigend, AGL 150 (<500)
            p(180, 50.3, 7.3, 3000, 120),
            p(300, 50.0, 7.0, 300, 0),      # Landung zurück auf X (EDDX)
            p(360, 50.0, 7.0, 300, 0),
            p(420, 50.0, 7.0, 300, 0),
            p(510, 50.0, 7.0, 300, 0),      # Dwell > 180
        ]
        legs = run(track)
        assert len(legs) == 2
        assert legs[0]["takeoff_ts"] == _ts(30)
        assert legs[1]["takeoff_ts"] == _ts(120)   # via gs+steigend, nicht erst bei 500 ft
        assert legs[1]["dep_icao"] == "EDDX" and legs[1]["arr_icao"] == "EDDX"

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
        """Vollstopp mit erneutem Abheben: OHNE Dwell/LANDED-Zwischenzustand sind das zwei
        Roh-Legs X→X (das Zusammenführen zur einen Session macht erst collapse_same_airport,
        Task 2)."""
        track = [
            p(0, 50.0, 7.0, 300, 0),
            p(15, 50.0, 7.0, 300, 0),
            p(30, 50.02, 7.05, 900, 60),    # Abheben
            p(90, 50.0, 7.0, 300, 0),       # Aufsetzen X → Landung SOFORT final (Leg 1)
            p(120, 50.02, 7.05, 900, 60),   # erneutes Abheben (900-300=600>500)
            p(210, 50.0, 7.0, 300, 0),      # erneut Aufsetzen X → Landung final (Leg 2)
            p(270, 50.0, 7.0, 300, 0),
            p(330, 50.0, 7.0, 300, 0),
            p(420, 50.0, 7.0, 300, 0),
        ]
        legs = run(track)
        assert len(legs) == 2
        assert legs[0]["dep_icao"] == "EDDX"
        assert legs[0]["arr_icao"] == "EDDX"
        assert legs[0]["complete"] is True
        assert legs[1]["dep_icao"] == "EDDX"
        assert legs[1]["arr_icao"] == "EDDX"
        assert legs[1]["complete"] is True

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

    def test_immediate_finalize_no_dwell(self):
        """Ohne Dwell: Vollstopp + sofortiges Wieder-Abheben am SELBEN Platz = zwei Roh-Legs."""
        track = [
            p(0, 50.0, 7.0, 300, 0), p(15, 50.0, 7.0, 300, 0),
            p(30, 50.05, 7.05, 900, 60),      # Abheben EDDX
            p(90, 50.0, 7.0, 300, 0),         # Vollstopp EDDX → Landung SOFORT final
            p(105, 50.05, 7.05, 900, 60),     # Wieder-Abheben (früher: Stop-and-Go-Merge)
            p(200, 52.7, 8.7, 5000, 150),
            p(320, 53.5, 9.5, 200, 0),        # Landung EDDB
            p(380, 53.5, 9.5, 200, 0),
        ]
        legs = run(track)
        assert [(l["dep_icao"], l["arr_icao"]) for l in legs] == [("EDDX", "EDDX"), ("EDDX", "EDDB")]
        assert all(l["segment"] == 0 for l in legs)

    def test_segment_index_increments_on_gap(self):
        """Positions-Lücke > 30 min → zweites Segment mit segment == 1."""
        track = [
            p(0, 52.0, 8.0, 100, 0), p(15, 52.0, 8.0, 100, 0),
            p(30, 52.1, 8.05, 700, 60), p(120, 52.7, 8.7, 5000, 150),   # Segment 0, endet airborne
            p(2520, 52.9, 8.9, 5000, 150), p(2600, 53.5, 9.5, 200, 0),  # 40-min-Lücke → Segment 1
            p(2660, 53.5, 9.5, 200, 0), p(2720, 53.5, 9.5, 200, 0),
        ]
        legs = run(track)
        assert legs[0]["segment"] == 0
        assert legs[-1]["segment"] == 1


def _leg(dep, arr, to, ld, seg=0, complete=True, maxalt=1000):
    return {"dep_icao": dep, "arr_icao": arr, "takeoff_ts": to, "landing_ts": ld,
            "complete": complete, "dep_source": "gps" if dep else None,
            "arr_source": "gps" if (arr and complete) else None, "max_altitude": maxalt, "segment": seg}


class TestCollapseSameAirport:
    def test_circuits_at_departure_then_cross_country(self):
        legs = [_leg("EDDK","EDDK","t0","t1"), _leg("EDDK","EDDK","t2","t3"), _leg("EDDK","EDDW","t4","t5")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [("EDDK","EDDW",True)]
        assert out[0]["takeoff_ts"] == "t0" and out[0]["landing_ts"] == "t5"

    def test_real_intermediate_landing_splits(self):
        legs = [_leg("EDPS","EDNX","t0","t1"), _leg("EDNX","EDNX","t2","t3"), _leg("EDNX","EDMA","t4","t5")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDPS","EDNX"), ("EDNX","EDMA")]
        assert out[0]["landing_ts"] == "t1" and out[1]["takeoff_ts"] == "t2"

    def test_pure_circuits(self):
        legs = [_leg("EDDX","EDDX","t0","t1"), _leg("EDDX","EDDX","t2","t3")]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [("EDDX","EDDX",True)]
        assert out[0]["landing_ts"] == "t3"

    def test_open_leg_stays_open(self):
        legs = [_leg("EDDK","EDDK","t0","t1"), _leg("EDDK",None,"t2",None, complete=False)]
        out = collapse_same_airport(legs)
        assert out == [{"dep_icao":"EDDK","arr_icao":None,"takeoff_ts":"t0","landing_ts":None,
                        "complete":False,"dep_source":"gps","arr_source":None,"max_altitude":1000}]

    def test_segment_boundary_does_not_merge_same_airport(self):
        legs = [_leg("EDDK","EDDK","t0","t1",seg=0), _leg("EDDK","EDDW","t9","t10",seg=1)]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDK","EDDK"), ("EDDK","EDDW")]

    def test_spawn_in_air_dep_none(self):
        out = collapse_same_airport([_leg(None,"EDDB","t0","t1")])
        assert (out[0]["dep_icao"], out[0]["arr_icao"]) == (None, "EDDB")

    def test_empty(self):
        assert collapse_same_airport([]) == []

    # --- Dwell-basierte X→X-Trennung (#v8.1.0, echte ISO-Zeiten) --------------------------
    def test_pause_splits_circuit_and_cross_country(self):
        """Reiner-Fall: Platzrunde X→X, ~41 min Bodenpause, dann X→Y → ZWEI Flüge."""
        legs = [
            _leg("EDWG", "EDWG", "2026-07-01T17:12:28Z", "2026-07-01T17:37:43Z"),
            _leg("EDWG", "EDXH", "2026-07-01T18:19:08Z", "2026-07-01T18:37:38Z"),
        ]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [
            ("EDWG", "EDWG", True), ("EDWG", "EDXH", True)]
        assert out[0]["takeoff_ts"] == "2026-07-01T17:12:28Z"
        assert out[0]["landing_ts"] == "2026-07-01T17:37:43Z"
        assert out[1]["takeoff_ts"] == "2026-07-01T18:19:08Z"
        assert out[1]["landing_ts"] == "2026-07-01T18:37:38Z"

    def test_stop_and_go_short_gap_merges(self):
        """X→X mit 60 s bis zum nächsten Start (echter Stop-and-Go) → EIN Flug X→Y."""
        legs = [
            _leg("EDDK", "EDDK", "2026-07-01T10:00:00Z", "2026-07-01T10:20:00Z"),
            _leg("EDDK", "EDDW", "2026-07-01T10:21:00Z", "2026-07-01T10:50:00Z"),
        ]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDK", "EDDW")]
        assert out[0]["takeoff_ts"] == "2026-07-01T10:00:00Z"
        assert out[0]["landing_ts"] == "2026-07-01T10:50:00Z"

    def test_stop_and_go_series_merges(self):
        """Serie kurzer Stop-and-Go (X→X, X→X, X→Y, alle Lücken klein) → EIN Flug X→Y."""
        legs = [
            _leg("EDDX", "EDDX", "2026-07-01T08:00:00Z", "2026-07-01T08:10:00Z"),
            _leg("EDDX", "EDDX", "2026-07-01T08:11:00Z", "2026-07-01T08:20:00Z"),
            _leg("EDDX", "EDDB", "2026-07-01T08:21:30Z", "2026-07-01T08:55:00Z"),
        ]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDX", "EDDB")]
        assert out[0]["takeoff_ts"] == "2026-07-01T08:00:00Z"

    def test_stop_and_go_boundary_exactly_threshold_merges(self):
        """Gap == genau _GPS_STOP_AND_GO_MAX_SEC (300 s) → noch Stop-and-Go (Schwelle inklusiv)."""
        legs = [
            _leg("EDDK", "EDDK", "2026-07-01T10:00:00Z", "2026-07-01T10:20:00Z"),
            _leg("EDDK", "EDDW", "2026-07-01T10:25:00Z", "2026-07-01T10:50:00Z"),  # +300 s
        ]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDK", "EDDW")]

    def test_stop_and_go_boundary_one_second_over_splits(self):
        """Gap == 301 s (eine Sekunde über der Schwelle) → Split in zwei Flüge."""
        legs = [
            _leg("EDDK", "EDDK", "2026-07-01T10:00:00Z", "2026-07-01T10:20:00Z"),
            _leg("EDDK", "EDDW", "2026-07-01T10:25:01Z", "2026-07-01T10:50:00Z"),  # +301 s
        ]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"]) for f in out] == [("EDDK", "EDDK"), ("EDDK", "EDDW")]

    def test_pause_then_pause_two_circuits_split(self):
        """Zwei X→X mit langer Pause dazwischen → ZWEI X→X-Flüge (jeder eigener Flug)."""
        legs = [
            _leg("EDDX", "EDDX", "2026-07-01T08:00:00Z", "2026-07-01T08:10:00Z"),
            _leg("EDDX", "EDDX", "2026-07-01T09:30:00Z", "2026-07-01T09:45:00Z"),
        ]
        out = collapse_same_airport(legs)
        assert [(f["dep_icao"], f["arr_icao"], f["complete"]) for f in out] == [
            ("EDDX", "EDDX", True), ("EDDX", "EDDX", True)]
        assert out[0]["landing_ts"] == "2026-07-01T08:10:00Z"
        assert out[1]["takeoff_ts"] == "2026-07-01T09:30:00Z"
