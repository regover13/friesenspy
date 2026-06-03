"""Smoke-Tests für app/poller.py.

Tests:
- VatsimPoller kann instanziiert werden
- start() und stop() können aufgerufen werden
- _poll_once exception handling: VATSIM-API-Fehler nicht nach außen
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.poller import VatsimPoller, create_poller


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_poller(db_path: str = ":memory:", **kwargs) -> VatsimPoller:
    return VatsimPoller(
        db_path=db_path,
        cids=[1234567, 7654321],
        poll_interval=60,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestVatsimPollerInstantiation:
    def test_can_instantiate(self):
        poller = _make_poller()
        assert isinstance(poller, VatsimPoller)

    def test_default_attributes(self):
        poller = _make_poller()
        assert poller.db_path == ":memory:"
        assert poller.cids == [1234567, 7654321]
        assert poller.poll_interval == 60
        assert poller.telegram_token == ""
        assert poller.telegram_chat_id == ""
        assert poller._scheduler is None
        assert poller._http_client is None
        assert poller._active_flights == {}
        assert isinstance(poller.sse_queue, asyncio.Queue)

    def test_custom_telegram_params(self):
        poller = _make_poller(telegram_token="tok123", telegram_chat_id="-100abc")
        assert poller.telegram_token == "tok123"
        assert poller.telegram_chat_id == "-100abc"

    def test_sse_queue_is_unbounded(self):
        """asyncio.Queue ohne maxsize-Parameter hat maxsize=0 (unbegrenzt)."""
        poller = _make_poller()
        assert poller.sse_queue.maxsize == 0


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------

class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_scheduler_and_client(self):
        poller = _make_poller()
        await poller.start()
        try:
            assert poller._scheduler is not None
            assert poller._http_client is not None
            assert poller._scheduler.running
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_stop_shuts_down_scheduler(self):
        poller = _make_poller()
        await poller.start()
        await poller.stop()
        # APScheduler shutdown(wait=False) is async — give it a moment to settle
        await asyncio.sleep(0.15)
        assert poller._scheduler is None or not poller._scheduler.running

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self):
        """start() + brief sleep + stop() raises no exception."""
        poller = _make_poller()
        await poller.start()
        await asyncio.sleep(0.05)
        await poller.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        """stop() vor start() sollte keinen Fehler werfen."""
        poller = _make_poller()
        await poller.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_scheduler_has_two_jobs(self):
        poller = _make_poller()
        await poller.start()
        try:
            jobs = poller._scheduler.get_jobs()
            job_ids = {j.id for j in jobs}
            assert "vatsim_poll" in job_ids
            assert "daily_cleanup" in job_ids
        finally:
            await poller.stop()


# ---------------------------------------------------------------------------
# _poll_once exception handling
# ---------------------------------------------------------------------------

class TestPollOnceExceptionHandling:
    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        """Wenn fetch_vatsim_data wirft, soll _poll_once keinen Fehler nach außen werfen."""
        poller = _make_poller()
        # Provide a mock http_client so the assertion in _poll_once passes
        poller._http_client = AsyncMock()

        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(side_effect=Exception("VATSIM unreachable")),
        ):
            # Must not raise
            await poller._poll_once()

    @pytest.mark.asyncio
    async def test_network_error_does_not_propagate(self):
        """httpx.ConnectError soll ebenfalls nicht weitergeworfen werden."""
        import httpx

        poller = _make_poller()
        poller._http_client = AsyncMock()

        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            await poller._poll_once()  # must not raise

    @pytest.mark.asyncio
    async def test_sse_queue_not_updated_on_error(self):
        """Bei einem VATSIM-Fehler wird nichts in die SSE-Queue geschrieben."""
        poller = _make_poller()
        poller._http_client = AsyncMock()

        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await poller._poll_once()

        assert poller.sse_queue.empty()

    @pytest.mark.asyncio
    async def test_poll_once_with_empty_pilots(self, tmp_path):
        """Erfolgreicher Poll ohne Friesen-Piloten online: SSE-Queue bekommt leere Liste."""
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        empty_vatsim = {"pilots": [], "controllers": []}
        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(return_value=empty_vatsim),
        ):
            await poller._poll_once()

        assert not poller.sse_queue.empty()
        event = poller.sse_queue.get_nowait()
        assert event["type"] == "positions"
        assert event["data"] == []

    @pytest.mark.asyncio
    async def test_poll_once_online_pilot_opens_flight(self, tmp_path):
        """Wenn ein Pilot neu online geht, wird ein Flug geöffnet und die SSE-Queue gefüllt."""
        from app.database import init_db, get_connection, get_live_positions

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = VatsimPoller(
            db_path=db_file,
            cids=[1234567],
            poll_interval=60,
        )
        poller._http_client = AsyncMock()

        vatsim_data = {
            "pilots": [
                {
                    "cid": 1234567,
                    "name": "Max Friesen",
                    "callsign": "FFR001",
                    "latitude": 53.6,
                    "longitude": 9.98,
                    "altitude": 35000,
                    "groundspeed": 450,
                    "heading": 180,
                    "logon_time": "2026-06-04T10:00:00Z",
                    "flight_plan": {
                        "aircraft_short": "B738",
                        "departure": "EDDH",
                        "arrival": "EDDF",
                    },
                }
            ]
        }

        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(return_value=vatsim_data),
        ):
            await poller._poll_once()

        # Pilot should now be in _active_flights
        assert 1234567 in poller._active_flights

        # SSE queue should have one event with the live position
        assert not poller.sse_queue.empty()
        event = poller.sse_queue.get_nowait()
        assert event["type"] == "positions"
        assert len(event["data"]) == 1
        assert event["data"][0]["cid"] == 1234567

    @pytest.mark.asyncio
    async def test_poll_once_pilot_goes_offline(self, tmp_path):
        """Pilot der offline geht: Flug geschlossen, live_positions leer."""
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = VatsimPoller(
            db_path=db_file,
            cids=[1234567],
            poll_interval=60,
        )
        poller._http_client = AsyncMock()

        # First poll: pilot is online
        vatsim_online = {
            "pilots": [
                {
                    "cid": 1234567,
                    "name": "Max Friesen",
                    "callsign": "FFR001",
                    "latitude": 53.6,
                    "longitude": 9.98,
                    "altitude": 35000,
                    "groundspeed": 450,
                    "heading": 180,
                    "logon_time": "2026-06-04T10:00:00Z",
                    "flight_plan": {
                        "aircraft_short": "B738",
                        "departure": "EDDH",
                        "arrival": "EDDF",
                    },
                }
            ]
        }
        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(return_value=vatsim_online),
        ):
            await poller._poll_once()

        assert 1234567 in poller._active_flights
        poller.sse_queue.get_nowait()  # discard first event

        # Second poll: pilot gone
        vatsim_offline = {"pilots": []}
        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(return_value=vatsim_offline),
        ):
            await poller._poll_once()

        assert 1234567 not in poller._active_flights

        event = poller.sse_queue.get_nowait()
        assert event["type"] == "positions"
        assert event["data"] == []


# ---------------------------------------------------------------------------
# create_poller factory
# ---------------------------------------------------------------------------

class TestCreatePoller:
    def test_create_poller_returns_instance(self, monkeypatch):
        """create_poller() gibt eine VatsimPoller-Instanz zurück."""
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("FRIESENFLIEGER_CIDS", "1111,2222")
        monkeypatch.setenv("DB_PATH", "/tmp/test.db")

        # Clear lru_cache so fresh settings are loaded
        from app.config import get_settings
        get_settings.cache_clear()

        try:
            poller = create_poller()
            assert isinstance(poller, VatsimPoller)
        finally:
            get_settings.cache_clear()
