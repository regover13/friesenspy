"""Tests for app/geo.py — haversine distance, airport coords, event pilot filtering."""
from __future__ import annotations

import math

import pytest

from app.geo import (
    airport_elevation_ft,
    filter_event_pilots,
    haversine,
    icao_to_coords,
    nearest_airport_icao,
    nearest_airport_icao_fast,
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


