"""Tests für app/vatsim.py — VATSIM-API-Client."""
from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock

from app.vatsim import (
    fetch_vatsim_data,
    filter_friesen_pilots,
    pilot_to_position,
    VATSIM_DATA_URL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_vatsim_data() -> dict:
    """Fixture: Typische VATSIM-API-Antwort mit Piloten."""
    return {
        "pilots": [
            {
                "cid": 1234567,
                "name": "Max Mustermann",
                "callsign": "FRS001",
                "latitude": 53.6,
                "longitude": 9.98,
                "altitude": 35000,
                "groundspeed": 450,
                "heading": 180,
                "logon_time": "2024-01-01T10:00:00.000000Z",
                "flight_plan": {
                    "aircraft_short": "B737",
                    "departure": "EDDH",
                    "arrival": "EDDF",
                },
            },
            {
                "cid": 8901234,
                "name": "Erika Beispiel",
                "callsign": "FRS002",
                "latitude": 52.5,
                "longitude": 13.4,
                "altitude": 25000,
                "groundspeed": 400,
                "heading": 270,
                "logon_time": "2024-01-01T11:00:00.000000Z",
                "flight_plan": {
                    "aircraft_short": "A320",
                    "departure": "EDDF",
                    "arrival": "EDDM",
                },
            },
            {
                "cid": 5555555,
                "name": "Unknown Pilot",
                "callsign": "UNK001",
                "latitude": 50.0,
                "longitude": 10.0,
                "altitude": 5000,
                "groundspeed": 100,
                "heading": 45,
                "logon_time": "2024-01-01T12:00:00.000000Z",
                "flight_plan": None,  # Kein Flight Plan eingereicht
            },
        ],
        "controllers": [],
        "servers": [],
    }


@pytest.fixture
def pilot_with_flight_plan() -> dict:
    """Fixture: Pilot mit vollständigem Flight Plan."""
    return {
        "cid": 1234567,
        "name": "Max Mustermann",
        "callsign": "FRS001",
        "latitude": 53.6,
        "longitude": 9.98,
        "altitude": 35000,
        "groundspeed": 450,
        "heading": 180,
        "logon_time": "2024-01-01T10:00:00.000000Z",
        "flight_plan": {
            "aircraft_short": "B737",
            "departure": "EDDH",
            "arrival": "EDDF",
        },
    }


@pytest.fixture
def pilot_without_flight_plan() -> dict:
    """Fixture: Pilot ohne Flight Plan (null)."""
    return {
        "cid": 5555555,
        "name": "Unbewehrter Pilot",
        "callsign": "UNK001",
        "latitude": 50.0,
        "longitude": 10.0,
        "altitude": 5000,
        "groundspeed": 100,
        "heading": 45,
        "logon_time": "2024-01-01T12:00:00.000000Z",
        "flight_plan": None,
    }


# ---------------------------------------------------------------------------
# fetch_vatsim_data
# ---------------------------------------------------------------------------

class TestFetchVatsimData:
    @pytest.mark.asyncio
    async def test_fetch_success(self, sample_vatsim_data):
        """Erfolgreicher Abruf der VATSIM-API."""
        client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock()
        response.json.return_value = sample_vatsim_data
        response.raise_for_status.return_value = None
        client.get.return_value = response

        result = await fetch_vatsim_data(client)

        assert result == sample_vatsim_data
        client.get.assert_called_once_with(VATSIM_DATA_URL)

    @pytest.mark.asyncio
    async def test_fetch_raises_http_error(self):
        """HTTP-Fehler wird weitergeleitet."""
        client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        client.get.return_value = response

        with pytest.raises(httpx.HTTPStatusError):
            await fetch_vatsim_data(client)

    @pytest.mark.asyncio
    async def test_fetch_timeout_error(self):
        """Timeout-Fehler wird weitergeleitet."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.TimeoutException("Connection timeout")

        with pytest.raises(httpx.TimeoutException):
            await fetch_vatsim_data(client)

    @pytest.mark.asyncio
    async def test_fetch_connection_error(self):
        """Connection-Fehler wird weitergeleitet."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            await fetch_vatsim_data(client)

    @pytest.mark.asyncio
    async def test_fetch_returns_dict(self, sample_vatsim_data):
        """Rückgabewert ist immer ein Dict."""
        client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock()
        response.json.return_value = sample_vatsim_data
        response.raise_for_status.return_value = None
        client.get.return_value = response

        result = await fetch_vatsim_data(client)

        assert isinstance(result, dict)
        assert "pilots" in result


# ---------------------------------------------------------------------------
# filter_friesen_pilots
# ---------------------------------------------------------------------------

class TestFilterFriesenPilots:
    def test_filter_exact_match(self, sample_vatsim_data):
        """Piloten exakt nach CID filtern."""
        cids = [1234567, 8901234]
        result = filter_friesen_pilots(cids, sample_vatsim_data)

        assert len(result) == 2
        cids_found = [p["cid"] for p in result]
        assert set(cids_found) == set(cids)

    def test_filter_single_match(self, sample_vatsim_data):
        """Einzelnen Piloten filtern."""
        cids = [1234567]
        result = filter_friesen_pilots(cids, sample_vatsim_data)

        assert len(result) == 1
        assert result[0]["cid"] == 1234567
        assert result[0]["name"] == "Max Mustermann"

    def test_filter_no_matches(self, sample_vatsim_data):
        """Keine Übereinstimmungen — leere Liste."""
        cids = [9999999]
        result = filter_friesen_pilots(cids, sample_vatsim_data)

        assert result == []

    def test_filter_partial_match(self, sample_vatsim_data):
        """Teilmenge der Piloten filtern."""
        cids = [1234567, 9999999]  # Ein Match, ein No-Match
        result = filter_friesen_pilots(cids, sample_vatsim_data)

        assert len(result) == 1
        assert result[0]["cid"] == 1234567

    def test_filter_empty_cids(self, sample_vatsim_data):
        """Leere CID-Liste — keine Matches."""
        cids = []
        result = filter_friesen_pilots(cids, sample_vatsim_data)

        assert result == []

    def test_filter_missing_pilots_key(self):
        """API-Response ohne 'pilots'-Schlüssel."""
        data = {"controllers": [], "servers": []}
        cids = [1234567]
        result = filter_friesen_pilots(cids, data)

        assert result == []

    def test_filter_empty_pilots_list(self):
        """API-Response mit leerer pilots-Liste."""
        data = {"pilots": []}
        cids = [1234567]
        result = filter_friesen_pilots(cids, data)

        assert result == []

    def test_filter_malformed_pilot_object(self):
        """Malformed pilot-Eintrag wird ignoriert."""
        data = {
            "pilots": [
                {"cid": 1234567, "name": "Valid Pilot"},
                "not-a-dict",  # Malformed
                None,  # Invalid
                {"name": "No CID"},  # Missing CID
            ]
        }
        cids = [1234567]
        result = filter_friesen_pilots(cids, data)

        assert len(result) == 1
        assert result[0]["cid"] == 1234567

    def test_filter_pilots_not_list(self):
        """API-Response mit non-list 'pilots'-Wert."""
        data = {"pilots": {"1234567": {}}}  # Dict statt List
        cids = [1234567]
        result = filter_friesen_pilots(cids, data)

        assert result == []

    def test_filter_preserves_pilot_data(self, sample_vatsim_data):
        """Gefilterte Piloten-Daten sind unmodifiziert."""
        cids = [1234567]
        result = filter_friesen_pilots(cids, sample_vatsim_data)

        pilot = result[0]
        assert pilot["cid"] == 1234567
        assert pilot["name"] == "Max Mustermann"
        assert pilot["callsign"] == "FRS001"
        assert pilot["latitude"] == 53.6
        assert pilot["flight_plan"]["aircraft_short"] == "B737"


# ---------------------------------------------------------------------------
# pilot_to_position
# ---------------------------------------------------------------------------

class TestPilotToPosition:
    def test_pilot_with_flight_plan(self, pilot_with_flight_plan):
        """Pilot mit vollständigem Flight Plan."""
        result = pilot_to_position(pilot_with_flight_plan)

        assert result["cid"] == 1234567
        assert result["name"] == "Max Mustermann"
        assert result["callsign"] == "FRS001"
        assert result["aircraft"] == "B737"
        assert result["aircraft_short"] == "B737"
        assert result["departure"] == "EDDH"
        assert result["arrival"] == "EDDF"
        assert result["latitude"] == 53.6
        assert result["longitude"] == 9.98
        assert result["altitude"] == 35000
        assert result["groundspeed"] == 450
        assert result["heading"] == 180
        assert result["logon_time"] == "2024-01-01T10:00:00.000000Z"

    def test_pilot_without_flight_plan(self, pilot_without_flight_plan):
        """Pilot ohne Flight Plan (null)."""
        result = pilot_to_position(pilot_without_flight_plan)

        assert result["cid"] == 5555555
        assert result["name"] == "Unbewehrter Pilot"
        assert result["callsign"] == "UNK001"
        assert result["aircraft"] == ""
        assert result["aircraft_short"] == ""
        assert result["departure"] == ""
        assert result["arrival"] == ""
        assert result["latitude"] == 50.0
        assert result["longitude"] == 10.0
        assert result["altitude"] == 5000
        assert result["groundspeed"] == 100
        assert result["heading"] == 45
        assert result["logon_time"] == "2024-01-01T12:00:00.000000Z"

    def test_aircraft_and_aircraft_short_match(self, pilot_with_flight_plan):
        """aircraft und aircraft_short sind gleich."""
        result = pilot_to_position(pilot_with_flight_plan)

        assert result["aircraft"] == result["aircraft_short"]
        assert result["aircraft"] == "B737"

    def test_missing_fields_default_to_empty_or_zero(self):
        """Fehlende Felder bekommen Standardwerte."""
        pilot = {"cid": 1000, "flight_plan": None}
        result = pilot_to_position(pilot)

        assert result["cid"] == 1000
        assert result["name"] == ""
        assert result["callsign"] == ""
        assert result["aircraft"] == ""
        assert result["departure"] == ""
        assert result["arrival"] == ""
        assert result["latitude"] == 0.0
        assert result["longitude"] == 0.0
        assert result["altitude"] == 0
        assert result["groundspeed"] == 0
        assert result["heading"] == 0
        assert result["logon_time"] == ""

    def test_flight_plan_missing_fields(self):
        """Flight Plan existiert, aber einzelne Felder fehlen."""
        pilot = {
            "cid": 1234567,
            "name": "Partial Pilot",
            "callsign": "TEST001",
            "latitude": 53.0,
            "longitude": 9.0,
            "altitude": 10000,
            "groundspeed": 250,
            "heading": 90,
            "logon_time": "2024-01-01T10:00:00Z",
            "flight_plan": {
                "aircraft_short": "C172",
                # departure, arrival fehlen
            },
        }
        result = pilot_to_position(pilot)

        assert result["aircraft"] == "C172"
        assert result["departure"] == ""
        assert result["arrival"] == ""

    def test_flight_plan_is_dict_check(self):
        """Flight Plan ist vorhanden, aber kein Dict (ungültig)."""
        pilot = {
            "cid": 1234567,
            "name": "Invalid FP Pilot",
            "callsign": "TEST001",
            "latitude": 50.0,
            "longitude": 10.0,
            "altitude": 5000,
            "groundspeed": 100,
            "heading": 0,
            "logon_time": "2024-01-01T10:00:00Z",
            "flight_plan": "invalid",  # String, nicht Dict
        }
        result = pilot_to_position(pilot)

        assert result["aircraft"] == ""
        assert result["departure"] == ""
        assert result["arrival"] == ""

    def test_latitude_longitude_preserved(self):
        """Koordinaten werden korrekt übernommen."""
        pilot = {
            "cid": 1,
            "latitude": -33.8688,
            "longitude": 151.2093,
            "flight_plan": None,
        }
        result = pilot_to_position(pilot)

        assert result["latitude"] == -33.8688
        assert result["longitude"] == 151.2093

    def test_altitude_and_speed_preserved(self):
        """Höhe und Geschwindigkeit werden korrekt übernommen."""
        pilot = {
            "cid": 1,
            "altitude": 41000,
            "groundspeed": 500,
            "heading": 359,
            "flight_plan": None,
        }
        result = pilot_to_position(pilot)

        assert result["altitude"] == 41000
        assert result["groundspeed"] == 500
        assert result["heading"] == 359

    def test_result_keys_are_flat(self, pilot_with_flight_plan):
        """Ergebnis ist ein flaches Dict (keine verschachtelten Objekte)."""
        result = pilot_to_position(pilot_with_flight_plan)

        expected_keys = {
            "cid", "name", "callsign", "aircraft", "aircraft_short",
            "departure", "arrival", "latitude", "longitude", "altitude",
            "groundspeed", "heading", "logon_time",
        }
        assert set(result.keys()) == expected_keys

    def test_all_result_fields_present(self, pilot_with_flight_plan):
        """Alle 13 Felder sind im Ergebnis vorhanden."""
        result = pilot_to_position(pilot_with_flight_plan)

        required_fields = [
            "cid", "name", "callsign", "aircraft", "aircraft_short",
            "departure", "arrival", "latitude", "longitude", "altitude",
            "groundspeed", "heading", "logon_time",
        ]
        for field in required_fields:
            assert field in result, f"Field '{field}' missing"

    def test_empty_flight_plan_dict(self):
        """Flight Plan ist leeres Dict."""
        pilot = {
            "cid": 1,
            "name": "Empty FP",
            "callsign": "EFP001",
            "latitude": 50.0,
            "longitude": 10.0,
            "altitude": 5000,
            "groundspeed": 100,
            "heading": 0,
            "logon_time": "2024-01-01T10:00:00Z",
            "flight_plan": {},  # Leeres Dict
        }
        result = pilot_to_position(pilot)

        assert result["aircraft"] == ""
        assert result["departure"] == ""
        assert result["arrival"] == ""

    def test_integration_sample_data(self, sample_vatsim_data):
        """Integration: Alle Piloten aus sample_vatsim_data verarbeiten."""
        pilots = sample_vatsim_data["pilots"]
        results = [pilot_to_position(p) for p in pilots]

        assert len(results) == 3

        # Max Mustermann — mit Flight Plan
        pos1 = results[0]
        assert pos1["cid"] == 1234567
        assert pos1["aircraft"] == "B737"
        assert pos1["departure"] == "EDDH"

        # Erika Beispiel — mit Flight Plan
        pos2 = results[1]
        assert pos2["cid"] == 8901234
        assert pos2["aircraft"] == "A320"
        assert pos2["departure"] == "EDDF"

        # Unknown Pilot — ohne Flight Plan
        pos3 = results[2]
        assert pos3["cid"] == 5555555
        assert pos3["aircraft"] == ""
        assert pos3["departure"] == ""

    def test_numeric_types(self, pilot_with_flight_plan):
        """Numerische Felder haben korrekte Typen."""
        result = pilot_to_position(pilot_with_flight_plan)

        assert isinstance(result["cid"], int)
        assert isinstance(result["latitude"], float)
        assert isinstance(result["longitude"], float)
        assert isinstance(result["altitude"], int)
        assert isinstance(result["groundspeed"], int)
        assert isinstance(result["heading"], int)

    def test_string_types(self, pilot_with_flight_plan):
        """String-Felder haben korrekte Typen."""
        result = pilot_to_position(pilot_with_flight_plan)

        assert isinstance(result["name"], str)
        assert isinstance(result["callsign"], str)
        assert isinstance(result["aircraft"], str)
        assert isinstance(result["aircraft_short"], str)
        assert isinstance(result["departure"], str)
        assert isinstance(result["arrival"], str)
        assert isinstance(result["logon_time"], str)
