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
        callsign_prefix="FRS",
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
        assert poller.callsign_prefix == "FRS"
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
        await asyncio.sleep(0.15)
        assert poller._scheduler is None or not poller._scheduler.running

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self):
        """start() + brief sleep + stop() raises no exception."""
        poller = _make_poller()
        await poller.start()
        await asyncio.sleep(0.05)
        await poller.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        """stop() vor start() sollte keinen Fehler werfen."""
        poller = _make_poller()
        await poller.stop()

    @pytest.mark.asyncio
    async def test_scheduler_has_two_jobs(self):
        poller = _make_poller()
        await poller.start()
        try:
            jobs = poller._scheduler.get_jobs()
            job_ids = {j.id for j in jobs}
            assert "vatsim_poll" in job_ids
            assert "calendar_sync" in job_ids
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
        poller._http_client = AsyncMock()

        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(side_effect=Exception("VATSIM unreachable")),
        ):
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
            await poller._poll_once()

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
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = VatsimPoller(
            db_path=db_file,
            callsign_prefix="FRS",
            poll_interval=60,
        )
        poller._http_client = AsyncMock()

        vatsim_data = {
            "pilots": [
                {
                    "cid": 1234567,
                    "name": "Max Friesen",
                    "callsign": "FRS001",
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

        assert 1234567 in poller._active_flights

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
            callsign_prefix="FRS",
            poll_interval=60,
        )
        poller._http_client = AsyncMock()

        vatsim_online = {
            "pilots": [
                {
                    "cid": 1234567,
                    "name": "Max Friesen",
                    "callsign": "FRS001",
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
        poller.sse_queue.get_nowait()

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
        monkeypatch.setenv("CALLSIGN_PREFIX", "FRS")
        monkeypatch.setenv("DB_PATH", "/tmp/test.db")

        from app.config import get_settings
        get_settings.cache_clear()

        try:
            poller = create_poller()
            assert isinstance(poller, VatsimPoller)
            assert poller.callsign_prefix == "FRS"
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# send_web_push (generisch)
# ---------------------------------------------------------------------------

class TestSendWebPush:
    @pytest.mark.asyncio
    async def test_sends_to_each_subscription(self, tmp_path):
        from app.database import init_db
        from app.poller import send_web_push

        db = str(tmp_path / "t.db")
        init_db(db)
        subs = [
            {"endpoint": "https://x/1", "p256dh": "p1", "auth": "a1"},
            {"endpoint": "https://x/2", "p256dh": "p2", "auth": "a2"},
        ]
        calls = []
        with patch("app.poller.webpush", new=MagicMock(side_effect=lambda **kw: calls.append(kw))):
            await send_web_push("priv", "mailto:x@y.z", db, subs, {"title": "T", "body": "B"})
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_410_deletes_subscription(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        from app.poller import send_web_push
        from pywebpush import WebPushException

        db = str(tmp_path / "t.db")
        init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "https://x/gone", "p", "a")
        conn.commit()
        conn.close()

        resp = MagicMock()
        resp.status_code = 410
        exc = WebPushException("gone")
        exc.response = resp
        subs = [{"endpoint": "https://x/gone", "p256dh": "p", "auth": "a"}]
        with patch("app.poller.webpush", new=MagicMock(side_effect=exc)):
            await send_web_push("priv", "mailto:x@y.z", db, subs, {"title": "T", "body": "B"})

        conn = get_connection(db)
        left = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
        conn.close()
        assert left == 0


# ---------------------------------------------------------------------------
# _poll_teamspeak (TS-Login-Diff)
# ---------------------------------------------------------------------------

class TestPollTeamspeak:
    def _ts_poller(self, db_path):
        return VatsimPoller(
            db_path=db_path, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
            ts_notify_enabled=True, ts_poll_interval=30, ts_rejoin_debounce_sec=900,
        )

    @pytest.mark.asyncio
    async def test_baseline_first_poll_no_push(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
        assert sent == []
        assert poller._ts_last_seen == {"FRS1"}

    @pytest.mark.asyncio
    async def test_new_join_triggers_push(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True, ts_self_frs="FRS9")
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_last_seen = set()  # Baseline überspringen
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)  # create_task laufen lassen
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_debounce_suppresses_rejoin(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        from datetime import datetime, timezone
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True)
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_last_seen = set()
        poller._ts_last_notified["FRS1"] = datetime.now(timezone.utc)  # eben erst benachrichtigt
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert sent == []

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            await poller._poll_teamspeak()  # darf nicht werfen

    @pytest.mark.asyncio
    async def test_fetch_error_first_poll_skips_no_baseline(self, tmp_path):
        """Erst-Poll mit Abruf-Fehler (None): kein Baseline-Freeze, kein Push; der
        nächste erfolgreiche Poll etabliert die echte Baseline (kein False-Positive)."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        sent = []
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=None)), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
        assert poller._ts_last_seen is None
        assert sent == []
        # nächster erfolgreicher Poll: Anwesende werden Baseline, KEIN Push
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller._ts_last_seen == {"FRS1"}
        assert sent == []

    @pytest.mark.asyncio
    async def test_mid_operation_fetch_error_preserves_baseline(self, tmp_path):
        """Transienter Fehler (None) im Betrieb darf _ts_last_seen NICHT zurücksetzen
        (sonst Push-Storm beim Recovery). Kein Push, State unverändert."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        poller._ts_last_seen = {"FRS1"}
        sent = []
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=None)), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller._ts_last_seen == {"FRS1"}
        assert sent == []

    @pytest.mark.asyncio
    async def test_empty_channel_is_valid_baseline(self, tmp_path):
        """Echt leerer Kanal ([]) beim Erst-Poll ist eine gültige (leere) Baseline; der
        erste echte Beitritt danach löst genau einen Push aus (Hauptanwendungsfall)."""
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True)
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        sent = []
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=[])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
        assert poller._ts_last_seen == set()
        assert sent == []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller._ts_last_seen == {"FRS1"}
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_ts_job_registered_when_enabled(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        await poller.start()
        try:
            assert "ts_poll" in {j.id for j in poller._scheduler.get_jobs()}
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_ts_job_absent_when_disabled(self, tmp_path):
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = _make_poller(db_path=db)  # ts_notify_enabled default False
        await poller.start()
        try:
            assert "ts_poll" not in {j.id for j in poller._scheduler.get_jobs()}
        finally:
            await poller.stop()
