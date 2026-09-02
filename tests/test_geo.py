"""Tests for app/geo.py — haversine distance, airport coords, event pilot filtering."""
from __future__ import annotations

import math

import pytest

from app import geo
from app.geo import (
    airport_elevation_ft,
    airportsdata_coords,
    filter_event_pilots,
    haversine,
    icao_to_coords,
    is_known_in_airportsdata,
    nearest_airport_icao,
    nearest_airport_icao_fast,
    search_airports,
    set_custom_airports,
)


class TestHaversine:
    """Tests for haversine distance calculation."""

    def test_same_point(self):
        """Distance between same point should be 0."""
        dist = haversine(51.0, 7.0, 51.0, 7.0)
        assert dist == pytest.approx(0.0, abs=0.001)

    def test_symmetry(self):
        """Distance should be symmetric: d(A, B) == d(B, A)."""
        dist_ab = haversine(51.0, 7.0, 52.0, 8.0)
        dist_ba = haversine(52.0, 8.0, 51.0, 7.0)
        assert dist_ab == pytest.approx(dist_ba, rel=1e-6)

    def test_eddk_to_eddl(self):
        """EDDK (Cologne) to EDDL (Düsseldorf) should be ~60km."""
        # EDDK: 50.87944, 6.7673
        # EDDL: 51.27083, 6.76472
        dist = haversine(50.87944, 6.7673, 51.27083, 6.76472)
        # Luftlinie ca. 44 km (bestätigt durch externe Tools)
        assert 40 < dist < 50

    def test_eddh_to_eddf(self):
        """EDDH (Hamburg) to EDDF (Frankfurt) should be ~450km."""
        # EDDH: 53.63028, 10.01389
        # EDDF: 50.02556, 8.54281
        dist = haversine(53.63028, 10.01389, 50.02556, 8.54281)
        assert 400 < dist < 500

    def test_equator_distance(self):
        """Test distance along equator (should be simple)."""
        # 1 degree at equator ~ 111.32 km
        dist = haversine(0.0, 0.0, 0.0, 1.0)
        assert dist == pytest.approx(111.32, rel=0.01)

    def test_north_south(self):
        """Test distance along meridian (north-south)."""
        # 1 degree latitude ~ 111 km everywhere
        dist = haversine(0.0, 0.0, 1.0, 0.0)
        assert dist == pytest.approx(111.0, rel=0.01)

    def test_zero_distance(self):
        """Very close points should give very small distance."""
        # 1 meter difference (1/111000 degrees approx)
        dist = haversine(51.0, 7.0, 51.0 + 0.000009, 7.0)
        assert 0 < dist < 0.01


class TestIcaoToCoords:
    """Tests for ICAO code to coordinates lookup."""

    def test_eddk_found(self):
        """EDDK should return valid coordinates."""
        coords = icao_to_coords("EDDK")
        assert coords is not None
        lat, lon = coords
        assert isinstance(lat, float)
        assert isinstance(lon, float)
        # Cologne roughly at 50.866°N, 7.143°E
        assert 50 < lat < 51
        assert 7 < lon < 8

    def test_eddl_found(self):
        """EDDL should return valid coordinates."""
        coords = icao_to_coords("EDDL")
        assert coords is not None
        lat, lon = coords
        # Düsseldorf roughly at 51.271°N, 6.765°E
        assert 51 < lat < 52
        assert 6 < lon < 7

    def test_eddh_found(self):
        """EDDH should return valid coordinates."""
        coords = icao_to_coords("EDDH")
        assert coords is not None
        lat, lon = coords
        # Hamburg roughly at 53.630°N, 9.988°E
        assert 53 < lat < 54
        assert 9 < lon < 10

    def test_unknown_code(self):
        """Unknown ICAO code should return None."""
        coords = icao_to_coords("XXXX")
        assert coords is None

    def test_lowercase_input(self):
        """Lowercase ICAO codes should be converted to uppercase."""
        coords_lower = icao_to_coords("eddk")
        coords_upper = icao_to_coords("EDDK")
        assert coords_lower == coords_upper

    def test_mixed_case_input(self):
        """Mixed case ICAO codes should work."""
        coords = icao_to_coords("EdDk")
        assert coords is not None

    def test_empty_string(self):
        """Empty string should return None."""
        coords = icao_to_coords("")
        assert coords is None

    def test_real_german_airports(self):
        """Test some real German airports."""
        airports = ["EDDF", "EDDB", "EDDS", "EDDM"]
        for icao in airports:
            coords = icao_to_coords(icao)
            # All should exist, all should be in Germany roughly
            assert coords is not None, f"{icao} should exist"
            lat, lon = coords
            assert 47 < lat < 56, f"{icao} latitude should be in Germany"
            assert 5 < lon < 16, f"{icao} longitude should be in Germany"


class TestFilterEventPilots:
    """Tests for event pilot filtering."""

    def test_empty_history(self):
        """Empty position history should return empty result."""
        result = filter_event_pilots([], ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert result == {}

    def test_no_valid_airports(self):
        """No valid airports should return empty result."""
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["XXXX", "YYYY"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert result == {}

    def test_single_pilot_in_radius(self):
        """Pilot near airport should be in result."""
        # Position very close to EDDK (50.88°N, 6.77°E)
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        assert len(result[123]) == 1

    def test_single_pilot_outside_radius(self):
        """Pilot far from airport should not be in result."""
        # Position in Berlin, far from Cologne
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 52.5, "longitude": 13.4, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 not in result

    def test_multiple_pilots_mixed(self):
        """Mix of pilots in and out of radius."""
        rows = [
            # Near EDDK
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            # Near EDDK
            {"cid": 456, "callsign": "TEST2", "latitude": 50.85, "longitude": 6.80, "ts": "2026-01-01T12:30:00Z"},
            # Far away
            {"cid": 789, "callsign": "TEST3", "latitude": 52.5, "longitude": 13.4, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        assert 456 in result
        assert 789 not in result

    def test_multiple_airports(self):
        """Pilot near any of multiple airports should be in result."""
        rows = [
            # Near EDDK
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            # Near EDDL
            {"cid": 456, "callsign": "TEST2", "latitude": 51.27, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            # Far from both
            {"cid": 789, "callsign": "TEST3", "latitude": 52.5, "longitude": 13.4, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK", "EDDL"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        assert 456 in result
        assert 789 not in result

    def test_multiple_airports_one_invalid(self):
        """Invalid airports should be skipped, valid ones used."""
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK", "XXXX", "EDDL"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        # Should still find the pilot because EDDK is valid
        assert 123 in result

    def test_all_positions_returned_not_just_hits(self):
        """All positions of a pilot should be returned, not just the ones in radius."""
        rows = [
            # Position in radius
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            # Same pilot, position outside radius
            {"cid": 123, "callsign": "TEST1", "latitude": 52.5, "longitude": 13.4, "ts": "2026-01-01T13:00:00Z"},
            # Same pilot, position in radius again
            {"cid": 123, "callsign": "TEST1", "latitude": 50.87, "longitude": 6.76, "ts": "2026-01-01T14:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        # All 3 positions should be returned
        assert len(result[123]) == 3

    def test_radius_boundary(self):
        """Test exact radius boundary (should include)."""
        # EDDK is at approximately 50.87944, 6.7673
        # Calculate a point exactly at the given radius distance
        airport_lat, airport_lon = icao_to_coords("EDDK")
        assert airport_lat is not None
        assert airport_lon is not None

        # Calculate a point ~50km away (within 150km radius)
        # Use simple approximation: ~0.45 degrees of latitude ~ 50 km
        test_lat = airport_lat + 0.45
        test_lon = airport_lon
        dist = haversine(airport_lat, airport_lon, test_lat, test_lon)
        assert 45 < dist < 55

        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": test_lat, "longitude": test_lon, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result

    def test_multiple_positions_same_pilot(self):
        """Multiple positions from the same pilot should all be included."""
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 123, "callsign": "TEST1", "latitude": 50.87, "longitude": 6.76, "ts": "2026-01-01T12:15:00Z"},
            {"cid": 123, "callsign": "TEST1", "latitude": 50.86, "longitude": 6.75, "ts": "2026-01-01T12:30:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        assert len(result[123]) == 3

    def test_missing_latitude(self):
        """Rows with missing latitude should be skipped without crashing."""
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 456, "callsign": "TEST2", "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},  # Missing latitude
            {"cid": 789, "callsign": "TEST3", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        # 123 and 789 should be in result, 456 should be skipped
        assert 123 in result
        assert 456 not in result
        assert 789 in result

    def test_missing_longitude(self):
        """Rows with missing longitude should be skipped without crashing."""
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 456, "callsign": "TEST2", "latitude": 50.88, "ts": "2026-01-01T12:00:00Z"},  # Missing longitude
            {"cid": 789, "callsign": "TEST3", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        assert 456 not in result
        assert 789 in result

    def test_missing_cid(self):
        """Rows with missing CID should be skipped without crashing."""
        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            {"callsign": "TEST2", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},  # Missing cid
            {"cid": 789, "callsign": "TEST3", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 150.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert 123 in result
        assert 789 in result
        assert len(result) == 2

    def test_zero_radius(self):
        """Zero radius should only match exactly at airport location (rare)."""
        # This is a boundary test; in practice, pilots will rarely be exactly at airport coords
        airport_lat, airport_lon = icao_to_coords("EDDK")
        assert airport_lat is not None
        assert airport_lon is not None

        rows = [
            {"cid": 123, "callsign": "TEST1", "latitude": airport_lat, "longitude": airport_lon, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 456, "callsign": "TEST2", "latitude": airport_lat + 0.001, "longitude": airport_lon, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 0.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        # Only 123 should be (nearly) in radius, 456 is definitely outside
        assert 123 in result
        assert 456 not in result

    def test_large_radius(self):
        """Large radius should include many pilots."""
        rows = [
            {"cid": 1, "callsign": "TEST1", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 2, "callsign": "TEST2", "latitude": 51.27, "longitude": 6.77, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 3, "callsign": "TEST3", "latitude": 52.0, "longitude": 7.0, "ts": "2026-01-01T12:00:00Z"},
            {"cid": 4, "callsign": "TEST4", "latitude": 55.0, "longitude": 10.0, "ts": "2026-01-01T12:00:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK"], 500.0, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        # First 3 should be within ~500km of EDDK
        assert 1 in result
        assert 2 in result
        assert 3 in result
        # 4 (Hamburg area) might be at edge; test with generous check
        assert len(result) >= 3

    def test_realistic_event_scenario(self):
        """Realistic scenario: Rhein-Event mit EDDK + EDDL, 150km Radius."""
        rows = [
            # Pilot 1: over Cologne (EDDK)
            {"cid": 100001, "callsign": "DLH123", "latitude": 50.88, "longitude": 6.77, "ts": "2026-01-01T10:00:00Z"},
            {"cid": 100001, "callsign": "DLH123", "latitude": 50.90, "longitude": 6.80, "ts": "2026-01-01T10:15:00Z"},
            # Pilot 2: over Düsseldorf (EDDL)
            {"cid": 100002, "callsign": "LH456", "latitude": 51.27, "longitude": 6.77, "ts": "2026-01-01T10:00:00Z"},
            {"cid": 100002, "callsign": "LH456", "latitude": 51.28, "longitude": 6.78, "ts": "2026-01-01T10:15:00Z"},
            # Pilot 3: over Belgium (outside radius)
            {"cid": 100003, "callsign": "BA789", "latitude": 50.0, "longitude": 4.5, "ts": "2026-01-01T10:00:00Z"},
            {"cid": 100003, "callsign": "BA789", "latitude": 50.0, "longitude": 4.5, "ts": "2026-01-01T10:15:00Z"},
        ]
        result = filter_event_pilots(rows, ["EDDK", "EDDL"], 150.0, "2026-01-01T09:00:00Z", "2026-01-01T11:00:00Z")
        assert 100001 in result
        assert 100002 in result
        assert 100003 not in result
        # Each pilot should have 2 positions
        assert len(result[100001]) == 2
        assert len(result[100002]) == 2


class TestNearestAirportFast:
    """nearest_airport_icao_fast muss byte-identisch zu nearest_airport_icao sein."""

    # Streuung aus deutschen Plätzen, Grenzen, offenem Wasser, Antimeridian, Polnähe.
    _COORDS = [
        (50.8659, 7.14274),    # exakt EDDK
        (50.87944, 6.7673),    # nahe Köln
        (51.27083, 6.76472),   # nahe Düsseldorf
        (53.63028, 10.01389),  # Hamburg
        (48.3538, 11.7861),    # München-Gegend
        (52.5, 13.4),          # Berlin
        (0.0, 0.0),            # Golf von Guinea (offenes Wasser)
        (30.0, -40.0),         # Mid-Atlantik
        (-45.0, 170.0),        # Südpazifik / NZ-Gegend
        (64.0, -22.0),         # Island-Gegend
        (1.35, 103.99),        # Singapur-Gegend
        (60.0, 179.9),         # nahe Antimeridian
        (60.0, -179.9),        # nahe Antimeridian (Ostseite)
        (89.0, 25.0),          # Polnähe
    ]
    _RADII = [0.0, 1.0, 5.0, 10.0, 50.0, 150.0]

    def test_matches_linear_scan(self):
        for lat, lon in self._COORDS:
            for r in self._RADII:
                fast = nearest_airport_icao_fast(lat, lon, r)
                slow = nearest_airport_icao(lat, lon, r)
                assert fast == slow, f"mismatch at ({lat},{lon}) r={r}: {fast!r} != {slow!r}"

    def test_finds_eddk(self):
        # Direkt am EDDK, kleiner Radius → EDDK.
        assert nearest_airport_icao_fast(50.8659, 7.14274, 5.0) == "EDDK"

    def test_ocean_returns_none(self):
        # Mitten im Atlantik, kein Platz im Umkreis.
        assert nearest_airport_icao_fast(30.0, -40.0, 50.0) is None

    def test_elevation_eddk_plausible(self):
        elev = airport_elevation_ft("EDDK")
        assert elev is not None
        # EDDK liegt bei ~302 ft.
        assert 200 < elev < 400

    def test_elevation_case_insensitive(self):
        assert airport_elevation_ft("eddk") == airport_elevation_ft("EDDK")

    def test_elevation_unknown_none(self):
        assert airport_elevation_ft("XXXX") is None


class TestCustomAirports:
    """#50: Ergänzungs-Flugplätze (custom_airports) — Plätze, die in airportsdata fehlen,
    werden von geo.py als ZWEITE Quelle konsultiert. ``_CUSTOM_AIRPORTS`` ist Modul-globaler
    State -> autouse-Fixture setzt ihn vor UND nach jedem Test zurück (kein Leck in andere
    Tests dieser oder anderer Testdateien)."""

    @pytest.fixture(autouse=True)
    def _reset_custom_airports(self):
        set_custom_airports([])
        yield
        set_custom_airports([])

    def test_set_custom_airports_replaces_previous_cache(self):
        set_custom_airports([{"icao": "ZZONE", "name": "Eins", "lat": 1.0, "lon": 1.0, "elevation_ft": 100.0}])
        assert icao_to_coords("ZZONE") == (1.0, 1.0)
        set_custom_airports([{"icao": "ZZTWO", "name": "Zwei", "lat": 2.0, "lon": 2.0, "elevation_ft": 200.0}])
        assert icao_to_coords("ZZONE") is None  # alter Eintrag komplett ersetzt, nicht gemergt
        assert icao_to_coords("ZZTWO") == (2.0, 2.0)

    def test_icao_to_coords_and_elevation_resolve_custom_airport(self):
        set_custom_airports([
            {"icao": "ZZTEST", "name": "Test", "lat": 12.3456, "lon": 45.6789, "elevation_ft": 500.0},
        ])
        assert icao_to_coords("ZZTEST") == (12.3456, 45.6789)
        assert icao_to_coords("zztest") == (12.3456, 45.6789)  # case-insensitive
        assert airport_elevation_ft("ZZTEST") == 500.0

    def test_icao_to_coords_custom_airport_unknown_elevation(self):
        set_custom_airports([
            {"icao": "ZZUNK", "name": "Unbekannt", "lat": 12.0, "lon": 45.0, "elevation_ft": None},
        ])
        assert icao_to_coords("ZZUNK") == (12.0, 45.0)
        assert airport_elevation_ft("ZZUNK") is None

    def test_nearest_airport_icao_finds_custom_airport_within_radius(self):
        # Abgelegene Koordinate (Antarktis) -> kein realer Flugplatz in der Naehe.
        set_custom_airports([
            {"icao": "ZZREM", "name": "Remote", "lat": -80.0, "lon": 0.0, "elevation_ft": 50.0},
        ])
        assert nearest_airport_icao(-80.001, 0.001, 1.0) == "ZZREM"

    def test_nearest_airport_icao_fast_finds_custom_airport_within_radius(self):
        set_custom_airports([
            {"icao": "ZZREM", "name": "Remote", "lat": -80.0, "lon": 0.0, "elevation_ft": 50.0},
        ])
        assert nearest_airport_icao_fast(-80.001, 0.001, 1.0) == "ZZREM"

    def test_nearest_airport_prefers_closer_of_both_sources(self):
        # Custom-Platz EXAKT an EDDKs Koordinaten (Distanz 0) -> bei Gleichstand gewinnt Custom
        # (dokumentierte Nachrang-Reihenfolge, s. geo.py-Kommentare).
        eddk_lat, eddk_lon = icao_to_coords("EDDK")
        set_custom_airports([
            {"icao": "ZZCLOSE", "name": "Genau an EDDK", "lat": eddk_lat, "lon": eddk_lon, "elevation_ft": 1.0},
        ])
        assert nearest_airport_icao(eddk_lat, eddk_lon, 5.0) == "ZZCLOSE"
        assert nearest_airport_icao_fast(eddk_lat, eddk_lon, 5.0) == "ZZCLOSE"

    def test_is_known_in_airportsdata_true_for_real_airport(self):
        # Fund dieser Session: EDXU (Huettenbusch) war faelschlich als "fehlend" vermutet
        # worden, steckte aber schon in airportsdata -> Plausipruefung (#50) muss das erkennen.
        assert is_known_in_airportsdata("EDXU") is True
        assert is_known_in_airportsdata("eddk") is True

    def test_is_known_in_airportsdata_false_for_custom_placeholder(self):
        assert is_known_in_airportsdata("ZZSALZ") is False

    def test_airportsdata_coords_ignores_custom_override(self):
        """#78: liefert den REINEN airportsdata-Wert, unbeeinflusst von custom_airports.

        Die Grund-Migration muss unterscheiden, ob ein Override die Koordinate korrigiert
        (EBUL/EBKT) oder sie unveraendert laesst und nur radius_km setzt (EHAM). Dafuer ist
        ``icao_to_coords`` untauglich: es liefert bei einem Override den Custom-Wert, der
        Vergleich waere also immer 0 km und JEDER Override sahe wie ein Radius-Fall aus.
        """
        real = icao_to_coords("EDDK")
        set_custom_airports([
            {"icao": "EDDK", "name": "Override", "lat": 1.0, "lon": 1.0, "elevation_ft": None},
        ])
        assert icao_to_coords("EDDK") == (1.0, 1.0)   # Custom gewinnt (#56)
        assert airportsdata_coords("EDDK") == real    # ... airportsdata bleibt sichtbar
        assert airportsdata_coords("eddk") == real    # case-insensitive wie icao_to_coords

    def test_airportsdata_coords_none_for_unknown_code(self):
        assert airportsdata_coords("ZZSALZ") is None

    def test_custom_overrides_airportsdata_coords_and_elevation(self):
        """#56: airportsdata kann selbst falsche Koordinaten fuehren (Fund: EBUL/Ursel Air
        Base ~15 km daneben) -- ein custom_airports-Eintrag mit demselben Code muss den
        Standard-Wert ueberschreiben, nicht nur bei fehlendem Code einspringen."""
        real_lat, real_lon = icao_to_coords("EDDK")
        real_elev = airport_elevation_ft("EDDK")
        set_custom_airports([
            {"icao": "EDDK", "name": "Override", "lat": 1.0, "lon": 1.0, "elevation_ft": 999.0},
        ])
        assert icao_to_coords("EDDK") == (1.0, 1.0)
        assert icao_to_coords("EDDK") != (real_lat, real_lon)
        assert airport_elevation_ft("EDDK") == 999.0
        assert airport_elevation_ft("EDDK") != real_elev

    def test_nearest_skips_shadowed_airportsdata_entry(self):
        """#56: ein von custom_airports ueberschatteter airportsdata-Code darf bei seiner
        ECHTEN Position nicht mehr gefunden werden -- sonst wuerde die falsche
        airportsdata-Position (z.B. EBUL) weiterhin matchen."""
        real_lat, real_lon = icao_to_coords("EDDK")
        set_custom_airports([
            {"icao": "EDDK", "name": "Override", "lat": -80.0, "lon": 0.0, "elevation_ft": 50.0},
        ])
        # An der ECHTEN airportsdata-Position darf EDDK nicht mehr matchen (uebersprungen).
        assert nearest_airport_icao(real_lat, real_lon, 0.05) is None
        assert nearest_airport_icao_fast(real_lat, real_lon, 0.05) is None
        # An der NEUEN (Custom-)Position matcht EDDK weiterhin.
        assert nearest_airport_icao(-80.001, 0.001, 1.0) == "EDDK"
        assert nearest_airport_icao_fast(-80.001, 0.001, 1.0) == "EDDK"

    def test_radius_km_none_keeps_default_radius_behavior(self):
        """Ohne radius_km-Override verhaelt sich ein custom_airports-Eintrag wie vor #62:
        jenseits des uebergebenen max_km wird er nicht mehr gefunden."""
        set_custom_airports([
            {"icao": "ZZFAR", "name": "Weit weg", "lat": -80.0, "lon": 0.0, "elevation_ft": 10.0},
        ])
        # ~6 km entfernt (0.054 Breitengrad * ~111 km/Grad), aber max_km ist nur 4.
        assert nearest_airport_icao(-80.054, 0.0, 4.0) is None
        assert nearest_airport_icao_fast(-80.054, 0.0, 4.0) is None

    def test_radius_km_override_extends_match_beyond_default_radius(self):
        """#62: ein eigener radius_km erlaubt den Treffer auch jenseits des uebergebenen
        max_km -- fuer Grossflughaefen (z. B. EHAM/Schiphol), deren Abhebepunkt weiter als
        der Standardradius vom Referenzpunkt entfernt liegen kann."""
        set_custom_airports([
            {"icao": "ZZFAR", "name": "Weit weg", "lat": -80.0, "lon": 0.0,
             "elevation_ft": 10.0, "radius_km": 8.0},
        ])
        assert nearest_airport_icao(-80.054, 0.0, 4.0) == "ZZFAR"
        assert nearest_airport_icao_fast(-80.054, 0.0, 4.0) == "ZZFAR"

    def test_radius_km_override_still_prefers_nearer_match(self):
        """Ein grosszuegiger radius_km darf einen tatsaechlich naeheren Treffer nicht
        verdraengen -- 'nearest' bleibt 'nearest', der eigene Radius entscheidet nur ueber
        die Zulassung als Kandidat, nicht ueber den Vorrang."""
        set_custom_airports([
            {"icao": "ZZFAR", "name": "Weit weg", "lat": -80.0, "lon": 0.0,
             "elevation_ft": 10.0, "radius_km": 8.0},  # ~6 km von der Anfrageposition
            {"icao": "ZZNEAR", "name": "Naeher dran", "lat": -80.044, "lon": 0.0,
             "elevation_ft": 5.0},  # ~1.1 km entfernt, kein eigener Radius (Standard reicht)
        ])
        assert nearest_airport_icao(-80.054, 0.0, 4.0) == "ZZNEAR"
        assert nearest_airport_icao_fast(-80.054, 0.0, 4.0) == "ZZNEAR"




class TestSyntheticIataCodes:
    """v10.4.6-Fund: airportsdata fuehrt Plaetze mit IATA-Code, aber ohne eigenes ICAO, unter
    einem Platzhalter-Schluessel ``_`` + IATA (14 Stueck, Version 20260315). Zwei davon
    beschreiben einen Platz, den airportsdata BEREITS unter seinem echten ICAO fuehrt --
    auf exakt identischer Koordinate:

        LFSB / _MLH  EuroAirport Basel-Mulhouse-Freiburg (binational: BSL, MLH, EAP -> ein ICAO)
        UBTT / _LHL  Lachin International

    Bei exaktem Distanz-Gleichstand gewinnt in nearest_airport_icao* durch ``d <= best_d`` der
    SPAETER iterierte Eintrag, und ``_`` (0x5F) sortiert in der CSV hinter alle Buchstaben
    (Einfuege-Index LFSB 15599, _MLH 28420) -- also immer der Platzhalter.

    Beleg: FRS190N (cid 1820730) landete am 2026-07-29 in Basel, Flugplan LSPM->LFSB, die
    Statistik zeigte ``LSPM -> _MLH``. Die Erkennung war geometrisch richtig (gleiche
    Koordinate!), nur der ausgegebene Code war der Platzhalter.
    """

    @pytest.fixture(autouse=True)
    def _reset_custom_airports(self):
        set_custom_airports([])
        yield
        set_custom_airports([])

    def test_prefers_real_icao_over_synthetic_twin(self):
        lat, lon = icao_to_coords("LFSB")
        assert nearest_airport_icao(lat, lon, 4.0) == "LFSB"
        assert nearest_airport_icao_fast(lat, lon, 4.0) == "LFSB"

    def test_prefers_real_icao_for_second_shadowed_twin(self):
        lat, lon = icao_to_coords("UBTT")
        assert nearest_airport_icao(lat, lon, 4.0) == "UBTT"
        assert nearest_airport_icao_fast(lat, lon, 4.0) == "UBTT"

    def test_synthetic_code_without_twin_stays_findable(self):
        """Die uebrigen 12 Platzhalter sind der EINZIGE Datensatz ihres Platzes -- ein
        pauschales Aussortieren aller ``_``-Codes wuerde sie unauffindbar machen."""
        for code in ("_OUK", "_AYM"):
            lat, lon = icao_to_coords(code)
            assert nearest_airport_icao(lat, lon, 1.0) == code
            assert nearest_airport_icao_fast(lat, lon, 1.0) == code

    def test_shadowed_code_still_resolves_to_coords_and_elevation(self):
        """Sieben Altfluege tragen ``_MLH`` in ``flight_cache``; bis zum rebuild muessen
        Karten-Koordinate und Elevation dafuer weiter aufloesbar bleiben."""
        assert icao_to_coords("_MLH") == airportsdata_coords("LFSB")
        assert airport_elevation_ft("_MLH") == airport_elevation_ft("LFSB")

    def test_unshadowed_placeholders_are_far(self):
        """Canary gegen Datenpflege upstream (Fable-Review v10.4.6).

        ``airportsdata`` ist absichtlich nicht gepinnt. Verschiebt eine kuenftige Version die
        Koordinate eines echten Platzes um wenige Meter, ohne den Platzhalter mitzuziehen, faellt
        das Paar aus der Zwillings-Erkennung -- und der Bug waere lautlos zurueck, weil die
        anderen Tests genau auf der gemeinsamen Koordinate pruefen und dort weiterhin gruen sind.

        Dieser Test schlaegt in genau dem Fall an: Jeder NICHT als Zwilling erkannte Platzhalter
        muss weiter als der Detektor-Radius (4 km) vom naechsten echten Platz entfernt liegen.
        Alles dazwischen ist die Grauzone, in der zwei Eintraege denselben Platz beschreiben
        koennten, ohne dass die Schwelle greift.
        """
        airports = geo._airports_icao()
        shadowed = geo._shadowed_codes()
        verdaechtig = []
        for code, a in airports.items():
            if not code.startswith("_") or code in shadowed:
                continue
            naechster, distanz = None, float("inf")
            for anderer, b in airports.items():
                if anderer.startswith("_"):
                    continue
                d = haversine(a["lat"], a["lon"], b["lat"], b["lon"])
                if d < distanz:
                    naechster, distanz = anderer, d
            if distanz <= 4.0:
                verdaechtig.append(f"{code} -> {naechster} ({distanz:.2f} km)")
        assert not verdaechtig, (
            "Platzhalter in der Grauzone 1-4 km: "
            + ", ".join(verdaechtig)
            + " -- _ZWILLING_MAX_KM pruefen (airportsdata-Daten haben sich geaendert)"
        )

    def test_twin_detection_survives_coordinate_drift(self, monkeypatch):
        """Datenunabhaengiger Beleg fuer die Distanzschwelle: ein Zwillingspaar, dessen
        Koordinaten NICHT bitidentisch sind (hier ~50 m auseinander), wird trotzdem erkannt.
        Mit dem urspruenglichen Float-Gleichheits-Vergleich waere dieser Test rot."""
        kunst = {
            "ZQQA": {"icao": "ZQQA", "lat": 47.5896, "lon": 7.52991, "elevation": 885.0},
            "_QQB": {"icao": "_QQB", "lat": 47.59005, "lon": 7.52991, "elevation": 885.0},  # ~50 m
            "_QQC": {"icao": "_QQC", "lat": 10.0, "lon": 10.0, "elevation": 0.0},  # allein
        }
        monkeypatch.setattr(geo, "_AIRPORTS_ICAO", kunst)
        monkeypatch.setattr(geo, "_SHADOWED_CODES", None)
        assert geo._shadowed_codes() == frozenset({"_QQB"})
        # Der echte Code gewinnt jetzt auch, wenn der Landepunkt NAEHER am Platzhalter liegt.
        assert geo.nearest_airport_icao(47.59005, 7.52991, 4.0) == "ZQQA"

    def test_search_liefert_koordinaten_zum_anspringen(self):
        """Das ICAO-Feld auf der Karte springt den Treffer an -- ohne Position ginge das
        nicht, und ein zweiter Abruf je Treffer waere reine Zusatzarbeit."""
        treffer = search_airports("KSPF")
        assert treffer and treffer[0]["icao"] == "KSPF"
        assert round(treffer[0]["lat"], 2) == 44.48
        assert round(treffer[0]["lon"], 2) == -103.79

    def test_search_nimmt_die_korrigierte_position(self, monkeypatch):
        """``custom_airports`` ist seit #56 ein Override, kein Fallback. Ein Platz, den
        airportsdata falsch verortet, darf hier nicht an der alten Stelle bleiben."""
        set_custom_airports([{"icao": "EDDK", "lat": 1.0, "lon": 2.0, "name": "Test"}])
        try:
            treffer = [e for e in search_airports("EDDK") if e["icao"] == "EDDK"]
            assert treffer and treffer[0]["lat"] == 1.0 and treffer[0]["lon"] == 2.0
        finally:
            set_custom_airports([])

    def test_shadowed_codes_not_offered_in_autocomplete(self):
        """Fable-Review v10.4.6: Was die Platzerkennung nie zurueckgibt, darf man sich auch
        nicht in einen Event-Filter klicken koennen. Eigenstaendige Platzhalter bleiben waehlbar."""
        treffer = {e["icao"] for e in search_airports("_M", limit=50)}
        assert "_MLH" not in treffer
        assert "_MUM" in treffer  # Muli Airport -- eigener Platz, kein Zwilling
