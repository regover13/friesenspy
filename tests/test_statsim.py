"""Tests für app/statsim.py."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.statsim import fetch_pilot_flights, fetch_flight_track, _normalize_flight


class TestNormalizeFlight:
    def test_basic_fields(self):
        f = {
            "id": 123, "vatsimid": "1602713", "callsign": "FRS49",
            "departure": "EDKB", "destination": "EDDK", "aircraft": "PA24/L",
            "loggedOn": "2026-06-04T10:00:00+00:00",
            "arrived": "2026-06-04T11:30:00+00:00",
        }
        r = _normalize_flight(f)
        assert r["statsim_id"] == 123
        assert r["callsign"] == "FRS49"
        assert r["departure"] == "EDKB"
        assert r["arrival"] == "EDDK"
        assert r["duration_min"] == 90
        assert r["logon_time"].endswith("Z")
        assert r["logoff_time"].endswith("Z")

    def test_no_arrived(self):
        f = {"id": 1, "callsign": "FRS01", "departure": "EDKB",
             "destination": "", "aircraft": "", "loggedOn": "2026-01-01T10:00:00Z",
             "arrived": None}
        r = _normalize_flight(f)
        assert r["duration_min"] is None
        assert r["logoff_time"] is None

    def test_destination_mapped_to_arrival(self):
        f = {"id": 1, "callsign": "X", "departure": "A",
             "destination": "B", "aircraft": "", "loggedOn": "", "arrived": None}
        r = _normalize_flight(f)
        assert r["arrival"] == "B"

    def test_aircraft_composite_string_shortened_to_icao_type(self):
        # StatSim liefert das rohe Flugplan-Feld (wie VATSIM) — nur der ICAO-Typ vor dem
        # ersten "/" wird übernommen, analog zu aircraft_short bei FriesenSpy-Flügen
        # (app/vatsim.py:76). Sonst zeigen StatSim-Flüge Composite-Strings wie
        # "A320/M-SDE3FGHIRWY/LB1" statt nur "A320".
        f = {"id": 1, "callsign": "X", "departure": "A", "destination": "B",
             "aircraft": "A320/M-SDE3FGHIRWY/LB1", "loggedOn": "", "arrived": None}
        r = _normalize_flight(f)
        assert r["aircraft"] == "A320"

    def test_aircraft_already_short_unchanged(self):
        f = {"id": 1, "callsign": "X", "departure": "A", "destination": "B",
             "aircraft": "C172", "loggedOn": "", "arrived": None}
        r = _normalize_flight(f)
        assert r["aircraft"] == "C172"

    def test_aircraft_empty_stays_empty(self):
        f = {"id": 1, "callsign": "X", "departure": "A", "destination": "B",
             "aircraft": "", "loggedOn": "", "arrived": None}
        r = _normalize_flight(f)
        assert r["aircraft"] == ""


class TestFetchPilotFlights:
    @pytest.mark.asyncio
    async def test_empty_key_returns_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        result = await fetch_pilot_flights(client, 1602713, "", days=10)
        assert result == []
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {"id": 42, "callsign": "FRS49", "departure": "EDKB", "destination": "EDDK",
             "aircraft": "PA24", "loggedOn": "2026-06-04T10:00:00Z", "arrived": "2026-06-04T10:45:00Z"}
        ]
        client.get.return_value = resp
        result = await fetch_pilot_flights(client, 1602713, "key", days=10)
        assert len(result) == 1
        assert result[0]["callsign"] == "FRS49"
        assert result[0]["duration_min"] == 45

    @pytest.mark.asyncio
    async def test_http_error_silent_fail(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.ConnectError("fail")
        result = await fetch_pilot_flights(client, 1, "key", days=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_deduplication(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {"id": 1, "callsign": "A", "departure": "", "destination": "",
             "aircraft": "", "loggedOn": "2026-01-01T00:00:00Z", "arrived": None}
        ]
        client.get.return_value = resp
        # For days=10 we get exactly 1 chunk (≤31 days)
        result = await fetch_pilot_flights(client, 1, "key", days=10)
        assert len(result) == 1


class TestFetchFlightTrack:
    @pytest.mark.asyncio
    async def test_empty_key_returns_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        result = await fetch_flight_track(client, 123, "")
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_track(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "id": 123,
            "positions": [
                {"time": "2026-06-04T10:00:00Z", "latitude": 50.7,
                 "longitude": 7.1, "altitude": 2000, "speed": 110, "heading": 180},
            ]
        }
        client.get.return_value = resp
        result = await fetch_flight_track(client, 123, "key")
        assert len(result) == 1
        assert result[0]["latitude"] == 50.7
        assert result[0]["groundspeed"] == 110

    @pytest.mark.asyncio
    async def test_error_silent_fail(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.TimeoutException("timeout")
        result = await fetch_flight_track(client, 99, "key")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_positions(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"id": 1, "positions": []}
        client.get.return_value = resp
        result = await fetch_flight_track(client, 1, "key")
        assert result == []
