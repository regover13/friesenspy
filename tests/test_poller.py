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

from app.poller import VatsimPoller, create_poller, _TS_BASELINE_STREAK


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
        assert poller._sse_subscribers == set()

    def test_custom_telegram_params(self):
        poller = _make_poller(telegram_token="tok123", telegram_chat_id="-100abc")
        assert poller.telegram_token == "tok123"
        assert poller.telegram_chat_id == "-100abc"

    def test_subscriber_queue_is_bounded(self):
        """Jede Client-Queue ist beschränkt (Drop-Oldest gegen Rückstau)."""
        from app.poller import _SSE_QUEUE_MAXSIZE
        poller = _make_poller()
        q = poller.subscribe_sse()
        assert q.maxsize == _SSE_QUEUE_MAXSIZE
        assert q in poller._sse_subscribers

    def test_broadcast_reaches_all_subscribers(self):
        """Kern-Fix: jeder registrierte Client bekommt dieselbe Nachricht (nicht nur einer)."""
        poller = _make_poller()
        q1 = poller.subscribe_sse()
        q2 = poller.subscribe_sse()

        msg = {"type": "positions", "data": [{"cid": 1}]}
        poller.broadcast_sse(msg)

        assert q1.get_nowait() == msg
        assert q2.get_nowait() == msg

    def test_unsubscribe_removes_queue(self):
        """Nach unsubscribe_sse bekommt die Queue keine Broadcasts mehr."""
        poller = _make_poller()
        q = poller.subscribe_sse()
        poller.unsubscribe_sse(q)
        assert q not in poller._sse_subscribers

        poller.broadcast_sse({"type": "positions", "data": []})
        assert q.empty()
        # idempotent: erneutes unsubscribe wirft nicht
        poller.unsubscribe_sse(q)

    def test_broadcast_drops_oldest_when_full(self):
        """Bei voller Client-Queue wird der älteste verworfen, der neueste behalten."""
        from app.poller import _SSE_QUEUE_MAXSIZE
        poller = _make_poller()
        q = poller.subscribe_sse()

        for i in range(_SSE_QUEUE_MAXSIZE):
            poller.broadcast_sse({"type": "positions", "data": [{"seq": i}]})
        assert q.full()

        poller.broadcast_sse({"type": "positions", "data": [{"seq": 999}]})
        assert q.qsize() == _SSE_QUEUE_MAXSIZE  # Länge bleibt gedeckelt
        # Ältester (seq=0) wurde verworfen → ältester verbleibender ist seq=1
        assert q.get_nowait()["data"][0]["seq"] == 1
        # Der neueste (seq=999) ist als letzter drin
        items = [q.get_nowait() for _ in range(q.qsize())]
        assert items[-1]["data"][0]["seq"] == 999


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

    @pytest.mark.asyncio
    async def test_scheduler_registers_flight_cache_and_statsim_jobs(self):
        """#23 Phase 2: flight_cache Warm-up (einmalig) + Refresh (5 min) und das
        proaktive StatSim-Track-Nachladen (10 min) müssen nach start() registriert sein."""
        poller = _make_poller()
        await poller.start()
        try:
            job_ids = {j.id for j in poller._scheduler.get_jobs()}
            assert "flight_cache_warmup" in job_ids
            assert "flight_cache_refresh" in job_ids
            assert "statsim_track_fetch" in job_ids
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
    async def test_no_broadcast_on_error(self):
        """Bei einem VATSIM-Fehler wird nichts an die SSE-Clients gebroadcastet."""
        poller = _make_poller()
        poller._http_client = AsyncMock()
        q = poller.subscribe_sse()

        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await poller._poll_once()

        assert q.empty()

    @pytest.mark.asyncio
    async def test_poll_once_with_empty_pilots(self, tmp_path):
        """Erfolgreicher Poll ohne Friesen-Piloten online: SSE-Queue bekommt leere Liste."""
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()
        q = poller.subscribe_sse()

        empty_vatsim = {"pilots": [], "controllers": []}
        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(return_value=empty_vatsim),
        ):
            await poller._poll_once()

        assert not q.empty()
        event = q.get_nowait()
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
        q = poller.subscribe_sse()

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

        assert not q.empty()
        event = q.get_nowait()
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
        q = poller.subscribe_sse()

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
        q.get_nowait()

        vatsim_offline = {"pilots": []}
        with patch(
            "app.poller.fetch_vatsim_data",
            new=AsyncMock(return_value=vatsim_offline),
        ):
            await poller._poll_once()

        assert 1234567 not in poller._active_flights

        event = q.get_nowait()
        assert event["type"] == "positions"
        assert event["data"] == []


# ---------------------------------------------------------------------------
# Feed-Aussetzer: eine Poll-Runde ohne den Piloten darf die Session nicht zerstören
# ---------------------------------------------------------------------------

class TestFeedGlitchReopen:
    """Regression Live-Test 2026-07-01 (Reiner, cid 1031301): ein einzelner VATSIM-Feed-
    Aussetzer schloss den laufenden Flug; beim Wiederauftauchen mit GLEICHER logon_time
    lief die Session gegen die bereits geschlossene flights-Zeile → alle Folgeflüge der
    Session verwaisten (nur position_history lief weiter)."""

    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        # _poll_once liest get_settings() (STATSIM_API_KEY) — minimale gültige Settings.
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _pilot(self, logon_time: str, groundspeed: int = 120) -> dict:
        return {
            "cid": 1031301,
            "name": "Reiner Friese",
            "callsign": "FRS61",
            "latitude": 53.78,
            "longitude": 7.91,
            "altitude": 1200,
            "groundspeed": groundspeed,
            "heading": 90,
            "logon_time": logon_time,
            "flight_plan": {
                "aircraft_short": "BN2P",
                "departure": "EDWG",
                "arrival": "EDXH",
            },
        }

    @staticmethod
    def _logon() -> str:
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    @pytest.mark.asyncio
    async def test_dropout_and_return_reopens_same_flight(self, tmp_path):
        """Poll 1 online → Poll 2 Feed-Aussetzer (Flug wird geschlossen) → Poll 3 wieder da
        (gleiche logon_time): dieselbe flights-Zeile muss wieder OFFEN sein — kein zweiter
        Eintrag, kein Weiterlaufen gegen eine geschlossene Zeile."""
        from app.database import get_connection, init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        online = {"pilots": [self._pilot(self._logon())]}
        glitch = {"pilots": []}

        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=online)):
            await poller._poll_once()
        fid = poller._active_flights[1031301]["id"]

        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=glitch)):
            await poller._poll_once()
        assert 1031301 not in poller._active_flights  # Aussetzer → geschlossen

        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=online)):
            await poller._poll_once()

        assert poller._active_flights[1031301]["id"] == fid  # gleiche Session, gleiche Zeile
        conn = get_connection(db_file)
        try:
            rows = conn.execute(
                "SELECT id, logoff_time FROM flights WHERE cid = 1031301"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["logoff_time"] is None  # wieder offen — Folgeflüge verwaisen nicht

    @pytest.mark.asyncio
    async def test_reopened_flight_closes_over_full_session(self, tmp_path):
        """Nach Aussetzer + Wiederauftauchen: der endgültige Disconnect schließt den Flug
        über die GESAMTE Session (Logoff = letzte Position), nicht über das Aussetzer-Fenster."""
        from app.database import get_connection, init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        online = {"pilots": [self._pilot(self._logon())]}
        offline = {"pilots": []}

        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=online)):
            await poller._poll_once()
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=offline)):
            await poller._poll_once()  # Aussetzer
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=online)):
            await poller._poll_once()  # wieder da → Reopen
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=offline)):
            await poller._poll_once()  # echter Disconnect

        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT logoff_time, duration_min FROM flights WHERE cid = 1031301"
            ).fetchone()
            last_pos = conn.execute(
                "SELECT MAX(ts) FROM position_history WHERE cid = 1031301"
            ).fetchone()[0]
        finally:
            conn.close()
        assert row["logoff_time"] == last_pos  # letzte echte Position, nicht der Aussetzer


# ---------------------------------------------------------------------------
# FriesenKutter: Live-Ankunfts-Latch muss den Schlüssel des OFFENEN Legs treffen,
# nicht den sitzungsweiten Feed-logon_time (Regression #22)
# ---------------------------------------------------------------------------

class TestLegSplitLatchKey:
    """Regression #22: Landet ein Friese zwischendurch und refilet mit GEÄNDERTEM
    Abflugort (selbe VATSIM-Verbindung, also gleichbleibender Feed-``logon_time``), schließt
    der Poller das alte Leg und öffnet ein neues mit frischer Mikrosekunden-``logon_time``
    (app/poller.py, ``self._active_flights[cid]``). Der Live-Ankunfts-Latch
    (``check_live_arrival`` → ``transport_live_arrivals``, PK (cid, logon_time, event_id))
    muss den ``logon_time`` DIESES offenen Legs bekommen — vorher bekam er den
    sitzungsweiten Feed-Wert (= Leg 1), was zu einem Fehl-Latch unter falschem Schlüssel und
    potenzieller Doppelzählung führte."""

    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _pilot(self, logon_time: str, dep: str, arr: str, lat: float, lon: float,
               groundspeed: int) -> dict:
        return {
            "cid": 1031301,
            "name": "Reiner Friese",
            "callsign": "FRS61",
            "latitude": lat,
            "longitude": lon,
            "altitude": 1200,
            "groundspeed": groundspeed,
            "heading": 90,
            "logon_time": logon_time,
            "flight_plan": {
                "aircraft_short": "BN2P",
                "departure": dep,
                "arrival": arr,
            },
        }

    @pytest.mark.asyncio
    async def test_latch_uses_open_leg_logon_time_not_session_logon(self, tmp_path):
        """Poll 1: Leg 1 (EDWG→EDDW), unterwegs. Poll 2: Refile mit geändertem Abflugort
        (EDDW→EDXH) bei UNVERÄNDERTER Feed-logon_time (gleiche VATSIM-Verbindung) → Leg-Split,
        Leg 1 wird geschlossen, Leg 2 bekommt eine neue logon_time. Poll 3: am Ziel EDXH,
        am Boden → Latch feuert. Der Latch-Eintrag muss den logon_time-Wert von Leg 2 tragen,
        nicht den ursprünglichen Session-Wert aus Poll 1/2."""
        from datetime import datetime, timedelta, timezone
        from app.database import (
            get_connection, init_db, create_transport_event, get_transport_event,
            get_transport_live_arrivals, compute_transport_progress,
        )
        from app.geo import icao_to_coords

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dtstart = (now - timedelta(hours=1)).strftime(fmt)
        dtend = (now + timedelta(hours=1)).strftime(fmt)
        # Session-logon_time bleibt über Poll 1+2 gleich — dieselbe VATSIM-Verbindung,
        # nur ein Refile mit geändertem Abflugort (kein Reconnect).
        session_logon = (now - timedelta(minutes=30)).strftime(fmt)

        conn = get_connection(db_file)
        try:
            eid = create_transport_event(
                conn, name="Helgoland-Nachschub", route="EDWG,EDDW,EDXH",
                dtstart=dtstart, dtend=dtend, destination="EDXH",
            )
            conn.commit()
        finally:
            conn.close()

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        # Poll 1: Leg 1, irgendwo unterwegs (weit weg vom Ziel), fliegt noch.
        leg1 = {"pilots": [self._pilot(session_logon, "EDWG", "EDDW", 53.78, 7.91, 120)]}
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=leg1)):
            await poller._poll_once()

        assert 1031301 in poller._active_flights
        leg1_id = poller._active_flights[1031301]["id"]
        assert poller._active_flights[1031301]["logon_time"] == session_logon

        # Poll 2: Refile mit geändertem Abflugort (EDDW statt EDWG) — SELBE Feed-logon_time
        # (session_logon), Position bewusst unverändert (kein GPS-Sprung in diesem Poll,
        # damit die Landung erst in Poll 3 sauber zugeordnet ist). Löst den Leg-Split aus.
        leg2 = {"pilots": [self._pilot(session_logon, "EDDW", "EDXH", 53.78, 7.91, 120)]}
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=leg2)):
            await poller._poll_once()

        leg2_entry = poller._active_flights[1031301]
        leg2_id = leg2_entry["id"]
        leg2_logon = leg2_entry["logon_time"]
        assert leg2_id != leg1_id  # neue flights-Zeile für Leg 2
        assert leg2_logon != session_logon  # eigener (Mikrosekunden-)Schlüssel, nicht der Session-Wert

        conn = get_connection(db_file)
        try:
            open_row = conn.execute(
                "SELECT logon_time FROM flights WHERE id = ?", (leg2_id,)
            ).fetchone()
        finally:
            conn.close()
        assert open_row["logon_time"] == leg2_logon

        # Poll 3: am Ziel EDXH angekommen, am Boden — kein weiterer Plan-Wechsel, derselbe
        # offene Flug (Leg 2) läuft weiter. Der Latch muss jetzt feuern.
        dest_lat, dest_lon = icao_to_coords("EDXH")
        leg2_landed = {"pilots": [self._pilot(session_logon, "EDDW", "EDXH", dest_lat, dest_lon, 0)]}
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=leg2_landed)):
            await poller._poll_once()

        assert poller._active_flights[1031301]["id"] == leg2_id  # kein weiterer Split
        assert poller._active_flights[1031301]["logon_time"] == leg2_logon

        # Kern der Regression: GENAU EIN Latch-Eintrag, und dessen logon_time ist der des
        # aktuell offenen Legs (Leg 2) — NICHT der ursprüngliche Session-/Leg-1-Wert.
        conn = get_connection(db_file)
        try:
            latched = get_transport_live_arrivals(conn, eid)
        finally:
            conn.close()
        assert latched == {(1031301, leg2_logon)}
        assert session_logon not in {lo for (_, lo) in latched}

        # Optional: die Fracht zählt genau einmal als geliefert (kein Doppel-Latch, keine
        # Doppelzählung über den Leg-Split hinweg).
        conn = get_connection(db_file)
        try:
            ev = get_transport_event(conn, eid)
            progress = compute_transport_progress(conn, ev, dtend)
        finally:
            conn.close()
        loaded_frs61 = [f for f in progress["flights"] if f["callsign"] == "FRS61" and f["loaded"]]
        assert len(loaded_frs61) == 1
        assert loaded_frs61[0]["tonnage_kg"] > 0


# ---------------------------------------------------------------------------
# FriesenKutter: Feierabend-Zusammenfassung wartet auf Nachzügler (Task #13)
# ---------------------------------------------------------------------------

class TestTransportSummaryWaitsForLaggards:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _seed(self, db_file):
        """Transport-Event mit abgelaufenem dtend + offener FRS-Flug von der Strecke."""
        from datetime import datetime, timedelta, timezone
        from app.database import create_transport_event, get_connection

        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dtstart = (now - timedelta(hours=3)).strftime(fmt)
        dtend = (now - timedelta(minutes=10)).strftime(fmt)
        logon = (now - timedelta(hours=2)).strftime(fmt)
        conn = get_connection(db_file)
        try:
            eid = create_transport_event(
                conn, name="Helgoland-Nachschub", route="EDWG,EDXH",
                dtstart=dtstart, dtend=dtend, destination="EDXH",
            )
            conn.execute(
                "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (7, 'P', ?)",
                (dtstart,),
            )
            conn.execute(
                "INSERT INTO flights (cid, callsign, departure, arrival, logon_time) "
                "VALUES (7, 'FRS07', 'EDWG', 'EDXH', ?)",
                (logon,),
            )
            conn.commit()
        finally:
            conn.close()
        return eid

    @pytest.mark.asyncio
    async def test_summary_deferred_while_pilot_in_progress(self, tmp_path):
        """dtend erreicht, aber ein Pilot ist noch unterwegs → summarized_at bleibt leer;
        erst wenn niemand mehr fliegt, wird der Feierabend gelatcht (finales Ergebnis)."""
        from datetime import datetime, timezone
        from app.database import get_connection, init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        eid = self._seed(db_file)
        poller = _make_poller(db_path=db_file)

        await poller._check_transport_events()
        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT summarized_at FROM transport_events WHERE id = ?", (eid,)
            ).fetchone()
        finally:
            conn.close()
        assert row["summarized_at"] is None  # Nachzügler fliegt noch → kein Feierabend

        # Nachzügler landet + disconnectet → Flug geschlossen
        conn = get_connection(db_file)
        try:
            conn.execute(
                "UPDATE flights SET logoff_time = ?, duration_min = 60 WHERE cid = 7",
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),),
            )
            conn.commit()
        finally:
            conn.close()

        await poller._check_transport_events()
        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT summarized_at FROM transport_events WHERE id = ?", (eid,)
            ).fetchone()
        finally:
            conn.close()
        assert row["summarized_at"] is not None  # jetzt final → Feierabend gelatcht


# ---------------------------------------------------------------------------
# FriesenKutter: leeres Event pusht keinen Feierabend + kein KI-Aufruf (Task 2)
# ---------------------------------------------------------------------------

class TestTransportSummaryEmptyEventSuppressed:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _poller(self, db_path):
        return VatsimPoller(
            db_path=db_path, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
        )

    def _seed_empty(self, db_file, quips_enabled=False):
        """Transport-Event mit abgelaufenem dtend, aber OHNE jeden Flug (flight_count == 0)."""
        from datetime import datetime, timedelta, timezone
        from app.database import create_transport_event, get_connection, set_app_setting

        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dtstart = (now - timedelta(hours=3)).strftime(fmt)
        dtend = (now - timedelta(minutes=10)).strftime(fmt)
        conn = get_connection(db_file)
        try:
            eid = create_transport_event(
                conn, name="Helgoland-Nachschub", route="EDWG,EDXH",
                dtstart=dtstart, dtend=dtend, destination="EDXH",
            )
            if quips_enabled:
                set_app_setting(conn, "transport_quips_enabled", "1")
            conn.commit()
        finally:
            conn.close()
        return eid

    def _seed_with_flight(self, db_file):
        """Wie TestTransportSummaryWaitsForLaggards._seed, aber Flug bereits geschlossen
        (Feierabend kann sofort latchen, kein Nachzügler-Wait nötig)."""
        from datetime import datetime, timedelta, timezone
        from app.database import create_transport_event, get_connection, set_transport_started

        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        dtstart = (now - timedelta(hours=3)).strftime(fmt)
        dtend = (now - timedelta(minutes=10)).strftime(fmt)
        logon = (now - timedelta(hours=2)).strftime(fmt)
        logoff = (now - timedelta(hours=1)).strftime(fmt)
        conn = get_connection(db_file)
        try:
            eid = create_transport_event(
                conn, name="Helgoland-Nachschub", route="EDWG,EDXH",
                dtstart=dtstart, dtend=dtend, destination="EDXH",
            )
            # Start-Latch schon gesetzt, damit dieser Test isoliert nur den Feierabend-Push
            # prüft (Start-Push bleibt laut Auftrag unverändert und wird hier nicht getestet).
            set_transport_started(conn, eid, dtstart)
            conn.execute(
                "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (7, 'P', ?)",
                (dtstart,),
            )
            conn.execute(
                "INSERT INTO flights (cid, callsign, departure, arrival, logon_time, "
                "logoff_time, duration_min) VALUES (7, 'FRS07', 'EDWG', 'EDXH', ?, ?, 60)",
                (logon, logoff),
            )
            conn.commit()
        finally:
            conn.close()
        return eid

    @pytest.mark.asyncio
    async def test_empty_event_no_push_but_latch_set(self, tmp_path):
        """flight_count == 0 bei dtend: summarized_at wird trotzdem gesetzt (Latch), aber
        es darf KEIN Feierabend-Push verschickt werden."""
        from app.database import init_db, get_connection, upsert_push_subscription

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        eid = self._seed_empty(db_file)
        conn = get_connection(db_file)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_events=True)
        conn.commit(); conn.close()

        poller = self._poller(db_file)
        sent = []
        with patch("app.poller.send_web_push",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._check_transport_events()
            await asyncio.sleep(0)

        assert sent == []  # kein Feierabend-Push für ein leeres Event

        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT summarized_at FROM transport_events WHERE id = ?", (eid,)
            ).fetchone()
        finally:
            conn.close()
        assert row["summarized_at"] is not None  # Latch feuert trotzdem (Event abgeschlossen)

    @pytest.mark.asyncio
    async def test_empty_event_no_llm_call(self, tmp_path):
        """flight_count == 0: selbst bei aktivierten KI-Sprüchen darf event_summary NICHT
        aufgerufen werden (kein bezahlter LLM-Call für ein leeres Event)."""
        from app.database import init_db, get_connection

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        self._seed_empty(db_file, quips_enabled=True)

        poller = self._poller(db_file)
        with patch("app.llm.event_summary") as mock_summary, \
             patch("app.poller.send_web_push", new=AsyncMock()):
            await poller._check_transport_events()
            await asyncio.sleep(0)

        mock_summary.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_with_flight_still_pushes_feierabend(self, tmp_path):
        """Regression: ein Event mit mindestens einem qualifizierenden Flug (flight_count > 0)
        produziert weiterhin den Feierabend-Push wie bisher."""
        from app.database import init_db, get_connection, upsert_push_subscription

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        self._seed_with_flight(db_file)
        conn = get_connection(db_file)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_events=True)
        conn.commit(); conn.close()

        poller = self._poller(db_file)
        sent = []
        with patch("app.poller.send_web_push",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._check_transport_events()
            await asyncio.sleep(0)

        assert len(sent) == 1
        payload = sent[0][4]  # send_web_push(priv, contact, db_path, subscriptions, payload, ...)
        assert "Feierabend" in payload["body"]


# ---------------------------------------------------------------------------
# _check_event_reminders -- 1h-Erinnerung aus drei Quellen (Task 4, #24)
# ---------------------------------------------------------------------------

class TestCheckEventReminders:
    """_check_event_reminders speist sich aus events_due_for_reminder (generisch),
    bummel_races_due_for_reminder und transport_events_due_for_reminder -- je ein Push mit
    quellenspezifischem Titel, latched über synthetische Keys (kein Doppel-Push)."""

    def _poller(self, db_path):
        return VatsimPoller(
            db_path=db_path, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
        )

    @pytest.mark.asyncio
    async def test_sends_for_all_three_sources_with_correct_titles(self, tmp_path):
        from datetime import datetime, timedelta, timezone
        from app.database import (
            init_db, get_connection, upsert_push_subscription, upsert_calendar_events,
            create_bummel_race, create_transport_event,
        )

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        soon = (now + timedelta(minutes=30)).strftime(fmt)

        conn = get_connection(db_file)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_events=True)
        upsert_calendar_events(conn, [{
            "uid": "gen1", "summary": "Stammtisch", "dtstart": soon, "dtend": "",
            "location": "", "route": "", "is_bummel": 0, "is_transport": 0,
        }])
        create_bummel_race(conn, name="Bummel A", route="EDWF,EDWG", dtstart=soon, dtend=None)
        create_transport_event(
            conn, name="Kutter A", route="EDWG,EDXH", destination="EDXH",
            dtstart=soon, dtend=None,
        )
        conn.commit()
        conn.close()

        poller = self._poller(db_file)
        sent = []
        with patch("app.poller.send_web_push",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._check_event_reminders()
            await asyncio.sleep(0)

        assert len(sent) == 3
        payloads = [call[4] for call in sent]
        assert {p["title"] for p in payloads} == {
            "FriesenEvent", "FriesenFliegerBummel", "FriesenKutter",
        }
        assert {p["body"] for p in payloads} == {
            "🗓 In etwa 1 Std: Stammtisch",
            "🗓 In etwa 1 Std: Bummel A",
            "🗓 In etwa 1 Std: Kutter A",
        }

        conn = get_connection(db_file)
        try:
            n = conn.execute("SELECT COUNT(*) c FROM event_reminders_sent").fetchone()["c"]
        finally:
            conn.close()
        assert n == 3  # generisch + bummel:{id} + kutter:{id} je einmal gelatcht

    @pytest.mark.asyncio
    async def test_push_disabled_bummel_and_kutter_excluded(self, tmp_path):
        from datetime import datetime, timedelta, timezone
        from app.database import (
            init_db, get_connection, upsert_push_subscription,
            create_bummel_race, create_transport_event,
            set_bummel_push_enabled, set_transport_push_enabled,
        )

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = get_connection(db_file)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_events=True)
        bid = create_bummel_race(conn, name="Bummel A", route="EDWF,EDWG", dtstart=soon, dtend=None)
        kid = create_transport_event(
            conn, name="Kutter A", route="EDWG,EDXH", destination="EDXH",
            dtstart=soon, dtend=None,
        )
        set_bummel_push_enabled(conn, bid, False)
        set_transport_push_enabled(conn, kid, False)
        conn.commit()
        conn.close()

        poller = self._poller(db_file)
        with patch("app.poller.send_web_push", new=AsyncMock()) as mock_send:
            await poller._check_event_reminders()
            await asyncio.sleep(0)

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_calendar_bummel_not_double_pushed(self, tmp_path):
        """Kalender-Bummel (is_bummel=1 in calendar_events + Objekt in bummel_races) löst genau
        EINEN Push aus, nicht zwei (generisch + Bummel)."""
        from datetime import datetime, timedelta, timezone
        from app.database import (
            init_db, get_connection, upsert_push_subscription, upsert_calendar_events,
            upsert_calendar_bummel_race,
        )

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = get_connection(db_file)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_events=True)
        ev = {"uid": "cal-bummel", "summary": "FFB Juli", "dtstart": soon, "dtend": "",
              "location": "", "route": "EDWF,EDWG", "is_bummel": 1, "is_transport": 0}
        upsert_calendar_events(conn, [ev])
        upsert_calendar_bummel_race(conn, ev)
        conn.commit()
        conn.close()

        poller = self._poller(db_file)
        sent = []
        with patch("app.poller.send_web_push",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._check_event_reminders()
            await asyncio.sleep(0)

        assert len(sent) == 1
        payload = sent[0][4]
        assert payload["title"] == "FriesenFliegerBummel"
        assert payload["body"] == "🗓 In etwa 1 Std: FFB Juli"


# ---------------------------------------------------------------------------
# Auto-Recherche der Zuladung für neu gesehene Typcodes (v7.4.0)
# ---------------------------------------------------------------------------

class TestAutoPayloadResearch:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    SUGGESTION = {"make_model": "PZL-104 Wilga", "mtow_kg": 1300.0, "empty_kg": 900.0,
                  "fuel_full_kg": 140.0, "fuel_kg": 70.0, "crew_kg": 85.0, "payload_kg": 245.0}

    def _pilot(self):
        from datetime import datetime, timedelta, timezone
        logon = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "cid": 777, "name": "Wilga-Pilot", "callsign": "FRS77",
            "latitude": 53.78, "longitude": 7.91, "altitude": 900,
            "groundspeed": 80, "heading": 90, "logon_time": logon,
            "flight_plan": {"aircraft_short": "PZ04", "departure": "EDWG", "arrival": "EDXH"},
        }

    @pytest.mark.asyncio
    async def test_poll_once_schedules_research_for_unknown_type(self, tmp_path):
        from app.database import init_db
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()
        poller._auto_research_payload = AsyncMock()
        data = {"pilots": [self._pilot()]}
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=data)):
            await poller._poll_once()
        poller._auto_research_payload.assert_called_once_with("PZ04")
        # Zweiter Poll: bereits versucht → kein erneuter (teurer) Recherche-Start.
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=data)):
            await poller._poll_once()
        assert poller._auto_research_payload.call_count == 1

    @pytest.mark.asyncio
    async def test_poll_once_skips_known_type(self, tmp_path):
        from app.database import get_connection, init_db, upsert_payload
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        conn = get_connection(db_file)
        try:
            upsert_payload(conn, "PZ04", payload_kg=120)
            conn.commit()
        finally:
            conn.close()
        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()
        poller._auto_research_payload = AsyncMock()
        with patch("app.poller.fetch_vatsim_data",
                   new=AsyncMock(return_value={"pilots": [self._pilot()]})):
            await poller._poll_once()
        poller._auto_research_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_research_upserts_llm_row(self, tmp_path):
        from app.database import get_connection, init_db
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        poller = _make_poller(db_path=db_file)
        with patch("app.llm.suggest_aircraft_payload", return_value=dict(self.SUGGESTION)):
            await poller._auto_research_payload("PZ04")
        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT source, fuel_kg, payload_kg, make_model FROM aircraft_payloads "
                "WHERE type_code = 'PZ04'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["source"] == "llm"
        assert row["fuel_kg"] == 70.0  # halbe Tankfüllung als Default

    @pytest.mark.asyncio
    async def test_auto_research_does_not_overwrite_manual(self, tmp_path):
        from app.database import get_connection, init_db, upsert_payload
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        conn = get_connection(db_file)
        try:
            upsert_payload(conn, "PZ04", payload_kg=123, source="manual")
            conn.commit()
        finally:
            conn.close()
        poller = _make_poller(db_path=db_file)
        with patch("app.llm.suggest_aircraft_payload", return_value=dict(self.SUGGESTION)):
            await poller._auto_research_payload("PZ04")
        conn = get_connection(db_file)
        try:
            row = conn.execute(
                "SELECT source, payload_kg FROM aircraft_payloads WHERE type_code = 'PZ04'"
            ).fetchone()
        finally:
            conn.close()
        assert row["source"] == "manual"
        assert row["payload_kg"] == 123  # manuell gepflegt → nie überschreiben


# ---------------------------------------------------------------------------
# Typ-Fallback ohne Flugplan (vatsim-radar-Prinzip, v7.4.0)
# ---------------------------------------------------------------------------

class TestAircraftTypeFallback:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        from app.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _pilot_no_fp(self, logon: str) -> dict:
        return {
            "cid": 888, "name": "Ohne Plan", "callsign": "FRS88",
            "latitude": 53.78, "longitude": 7.91, "altitude": 800,
            "groundspeed": 75, "heading": 90, "logon_time": logon,
            "flight_plan": None,
        }

    @pytest.mark.asyncio
    async def test_no_history_type_leaves_aircraft_empty(self, tmp_path):
        """#52: Pilot ohne (Live-)Flugplan bekommt KEIN Muster aus früheren Flügen mehr
        untergeschoben (last_known_aircraft war zeitlich blind, s. Fund cid 1273634) — der Typ
        bleibt ehrlich leer, auch wenn eine ältere Session des Piloten einen Typ kennt."""
        from datetime import datetime, timedelta, timezone
        from app.database import get_connection, init_db
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        conn = get_connection(db_file)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (888, 'Ohne Plan', ?)",
                (now.strftime(fmt),),
            )
            conn.execute(
                "INSERT INTO flights (cid,callsign,aircraft_short,aircraft_icao,departure,"
                "arrival,logon_time,logoff_time,duration_min) VALUES "
                "(888,'FRS88','PZ04','PZ04','EDWG','EDXH',?,?,30)",
                ((now - timedelta(days=1)).strftime(fmt),
                 (now - timedelta(days=1, minutes=-30)).strftime(fmt)),
            )
            conn.commit()
        finally:
            conn.close()
        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()
        logon = (now - timedelta(minutes=10)).strftime(fmt)
        with patch("app.poller.fetch_vatsim_data",
                   new=AsyncMock(return_value={"pilots": [self._pilot_no_fp(logon)]})):
            await poller._poll_once()
        conn = get_connection(db_file)
        try:
            flight = conn.execute(
                "SELECT aircraft_short FROM flights WHERE cid=888 AND logoff_time IS NULL"
            ).fetchone()
            live = conn.execute(
                "SELECT aircraft FROM live_positions WHERE cid=888"
            ).fetchone()
        finally:
            conn.close()
        assert flight["aircraft_short"] == ""
        assert live["aircraft"] == ""

    @pytest.mark.asyncio
    async def test_prefile_type_wins_over_history(self, tmp_path):
        """Liegt ein Prefile des Piloten vor, hat dessen Muster Vorrang vor der Historie."""
        from datetime import datetime, timedelta, timezone
        from app.database import get_connection, init_db
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        now = datetime.now(timezone.utc)
        logon = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "pilots": [self._pilot_no_fp(logon)],
            "prefiles": [{"cid": 888, "callsign": "FRS88",
                          "flight_plan": {"aircraft_short": "BN2P",
                                          "departure": "EDWG", "arrival": "EDXH",
                                          "deptime": "1800"}}],
        }
        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=data)):
            await poller._poll_once()
        conn = get_connection(db_file)
        try:
            live = conn.execute("SELECT aircraft FROM live_positions WHERE cid=888").fetchone()
        finally:
            conn.close()
        assert live["aircraft"] == "BN2P"

    @pytest.mark.asyncio
    async def test_later_flight_plan_backfills_aircraft_short_on_same_leg(self, tmp_path):
        """#54: Leg wird OHNE Flugplan eröffnet (aircraft_short bleibt leer). Trifft später
        ein Plan für dieselbe Verbindung ein (kein Split, da old_dep/old_arr leer waren), muss
        update_flight_plan() den Typ jetzt nachtragen (Fund: cid 1031301, flight id 250)."""
        from datetime import datetime, timedelta, timezone
        from app.database import get_connection, init_db
        db_file = str(tmp_path / "t.db")
        init_db(db_file)
        now = datetime.now(timezone.utc)
        logon = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        no_plan = {"pilots": [self._pilot_no_fp(logon)]}
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=no_plan)):
            await poller._poll_once()

        with_plan = {
            "pilots": [{
                "cid": 888, "name": "Ohne Plan", "callsign": "FRS88",
                "latitude": 53.78, "longitude": 7.91, "altitude": 800,
                "groundspeed": 75, "heading": 90, "logon_time": logon,
                "flight_plan": {"aircraft_short": "B105", "departure": "EDVE", "arrival": "EDBH"},
            }],
        }
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=with_plan)):
            await poller._poll_once()

        conn = get_connection(db_file)
        try:
            flight = conn.execute(
                "SELECT aircraft_short FROM flights WHERE cid=888 AND logoff_time IS NULL"
            ).fetchone()
        finally:
            conn.close()
        assert flight["aircraft_short"] == "B105"


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

    @pytest.mark.asyncio
    async def test_403_vapid_mismatch_deletes_subscription(self, tmp_path):
        """403 mit VAPID-Mismatch-Body = veraltete Subscription → aufräumen wie 410."""
        from app.database import init_db, get_connection, upsert_push_subscription
        from app.poller import send_web_push
        from pywebpush import WebPushException

        db = str(tmp_path / "t.db")
        init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "https://x/stale", "p", "a")
        conn.commit()
        conn.close()

        resp = MagicMock()
        resp.status_code = 403
        resp.text = ("the VAPID credentials in the authorization header "
                     "do not correspond to the credentials used to create the subscriptions.")
        exc = WebPushException("forbidden")
        exc.response = resp
        subs = [{"endpoint": "https://x/stale", "p256dh": "p", "auth": "a"}]
        with patch("app.poller.webpush", new=MagicMock(side_effect=exc)):
            await send_web_push("priv", "mailto:x@y.z", db, subs, {"title": "T", "body": "B"})

        conn = get_connection(db)
        left = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
        conn.close()
        assert left == 0

    @pytest.mark.asyncio
    async def test_403_other_body_keeps_subscription(self, tmp_path):
        """Ein 403 mit anderem Body wird NICHT als veraltete Subscription gelöscht."""
        from app.database import init_db, get_connection, upsert_push_subscription
        from app.poller import send_web_push
        from pywebpush import WebPushException

        db = str(tmp_path / "t.db")
        init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "https://x/keep", "p", "a")
        conn.commit()
        conn.close()

        resp = MagicMock()
        resp.status_code = 403
        resp.text = "some other forbidden reason"
        exc = WebPushException("forbidden")
        exc.response = resp
        subs = [{"endpoint": "https://x/keep", "p256dh": "p", "auth": "a"}]
        with patch("app.poller.webpush", new=MagicMock(side_effect=exc)), \
             patch("app.poller.asyncio.sleep", new=AsyncMock()):
            await send_web_push("priv", "mailto:x@y.z", db, subs, {"title": "T", "body": "B"})

        conn = get_connection(db)
        left = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
        conn.close()
        assert left == 1


# ---------------------------------------------------------------------------
# Online-Reconnect-Debounce
# ---------------------------------------------------------------------------

class TestOnlineRejoinDebounce:
    def _vatsim_data(self):
        return {
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

    @pytest.mark.asyncio
    async def test_first_online_notifies(self, tmp_path):
        from app.database import init_db

        db = str(tmp_path / "t.db"); init_db(db)
        poller = VatsimPoller(
            db_path=db, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
            vatsim_rejoin_debounce_sec=900,
        )
        poller._http_client = AsyncMock()
        sent = []
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=self._vatsim_data())), \
             patch("app.poller.send_web_push_notifications",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_once()
            await asyncio.sleep(0)  # create_task laufen lassen
        assert len(sent) == 1
        assert 1234567 in poller._online_last_notified

    @pytest.mark.asyncio
    async def test_reconnect_within_window_suppressed(self, tmp_path):
        from datetime import datetime, timezone
        from app.database import init_db

        db = str(tmp_path / "t.db"); init_db(db)
        poller = VatsimPoller(
            db_path=db, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
            vatsim_rejoin_debounce_sec=900,
        )
        poller._http_client = AsyncMock()
        poller._online_last_notified[1234567] = datetime.now(timezone.utc)  # eben benachrichtigt
        sent = []
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=self._vatsim_data())), \
             patch("app.poller.send_web_push_notifications",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_once()
            await asyncio.sleep(0)
        assert sent == []
        # State-Machine läuft trotzdem: Pilot ist als aktiver Flug erfasst.
        assert 1234567 in poller._active_flights

    @pytest.mark.asyncio
    async def test_reonline_after_window_notifies(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        from app.database import init_db

        db = str(tmp_path / "t.db"); init_db(db)
        poller = VatsimPoller(
            db_path=db, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
            vatsim_rejoin_debounce_sec=900,
        )
        poller._http_client = AsyncMock()
        poller._online_last_notified[1234567] = datetime.now(timezone.utc) - timedelta(seconds=1000)
        sent = []
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=self._vatsim_data())), \
             patch("app.poller.send_web_push_notifications",
                   new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_once()
            await asyncio.sleep(0)
        assert len(sent) == 1


# ---------------------------------------------------------------------------
# _poll_teamspeak (TS-Login-Diff)
# ---------------------------------------------------------------------------

class TestPollTeamspeak:
    def _ts_poller(self, db_path, dwell=0):
        return VatsimPoller(
            db_path=db_path, callsign_prefix="FRS", poll_interval=60,
            vapid_private_key="priv", vapid_contact_email="mailto:x@y.z",
            ts_notify_enabled=True, ts_poll_interval=30, ts_rejoin_debounce_sec=900,
            ts_min_dwell_polls=dwell,
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
        assert poller._ts_streak == {"FRS1": _TS_BASELINE_STREAK}

    @pytest.mark.asyncio
    async def test_new_join_triggers_push(self, tmp_path):
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True)
        conn.commit(); conn.close()
        poller = self._ts_poller(db)  # dwell=0 → sofort
        poller._ts_streak = {}  # Baseline bereits gesetzt (leer)
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
        poller = self._ts_poller(db)  # dwell=0
        poller._ts_streak = {}
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
        assert poller._ts_streak is None
        assert sent == []
        # nächster erfolgreicher Poll: Anwesende werden Baseline, KEIN Push
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller._ts_streak == {"FRS1": _TS_BASELINE_STREAK}
        assert sent == []

    @pytest.mark.asyncio
    async def test_mid_operation_fetch_error_preserves_baseline(self, tmp_path):
        """Transienter Fehler (None) im Betrieb darf _ts_last_seen NICHT zurücksetzen
        (sonst Push-Storm beim Recovery). Kein Push, State unverändert."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        poller._ts_streak = {"FRS1": 5}
        sent = []
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=None)), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller._ts_streak == {"FRS1": 5}
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
        assert poller._ts_streak == {}
        assert sent == []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller._ts_streak == {"FRS1": 1}
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_dwell_requires_second_poll(self, tmp_path):
        """dwell=1: FRS muss beim Folge-Poll noch da sein → Push erst im 2. Poll."""
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True)
        conn.commit(); conn.close()
        poller = self._ts_poller(db, dwell=1)
        poller._ts_streak = {}  # Baseline (leer) gesetzt
        sent = []
        client = [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}]
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=client)), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()        # Poll 1: streak 1 < 2 → kein Push
            await asyncio.sleep(0)
            assert sent == []
            await poller._poll_teamspeak()        # Poll 2: streak 2 == 2 → Push
            await asyncio.sleep(0)
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_brief_visit_no_push(self, tmp_path):
        """dwell=1: kurzes Reinschauen (vor dem Folge-Poll wieder weg) → kein Push."""
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "e1", "p1", "a1", notify_ts=True)
        conn.commit(); conn.close()
        poller = self._ts_poller(db, dwell=1)
        poller._ts_streak = {}
        sent = []
        present = [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}]
        with patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=present)):
                await poller._poll_teamspeak()    # Poll 1: streak 1, kein Push
                await asyncio.sleep(0)
            with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=[])):
                await poller._poll_teamspeak()    # Poll 2: schon wieder weg → Streak-Reset
                await asyncio.sleep(0)
        assert sent == []
        assert "FRS1" not in poller._ts_streak

    @pytest.mark.asyncio
    async def test_ts_respects_pilot_filter_include(self, tmp_path):
        """FRS mit bekannter CID: nur Subs, deren pilot_filter die CID enthält (oder NULL)."""
        from app.database import (init_db, get_connection, upsert_push_subscription,
                                  open_flight, ensure_pilot)
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        ensure_pilot(conn, 111, "Max")
        open_flight(conn, 111, "FRS1", "C172", "EDDW", "EDDH", "2026-06-18T10:00:00Z")
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        upsert_push_subscription(conn, "only999", "p", "a", notify_ts=True, pilot_filter=[999])
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_streak = {}
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert len(sent) == 1
        recipients = sent[0][3]  # (vapid, email, db, recipients, payload)
        assert {r["endpoint"] for r in recipients} == {"all", "only111"}

    @pytest.mark.asyncio
    async def test_ts_unknown_frs_only_all(self, tmp_path):
        """Reine TS-FRS ohne CID: nur pilot_filter NULL bekommt den Push."""
        from app.database import init_db, get_connection, upsert_push_subscription
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_push_subscription(conn, "only111", "p", "a", notify_ts=True, pilot_filter=[111])
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_streak = {}
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS9", "nick": "Gast/FRS9", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert len(sent) == 1
        assert {r["endpoint"] for r in sent[0][3]} == {"all"}

    @pytest.mark.asyncio
    async def test_ts_consent_nobody_suppresses(self, tmp_path):
        from app.database import (init_db, get_connection, upsert_push_subscription,
                                  upsert_ts_consent, open_flight, ensure_pilot)
        db = str(tmp_path / "t.db"); init_db(db)
        conn = get_connection(db)
        ensure_pilot(conn, 111, "Max")
        open_flight(conn, 111, "FRS1", "C172", "EDDW", "EDDH", "2026-06-18T10:00:00Z")
        upsert_push_subscription(conn, "all", "p", "a", notify_ts=True, pilot_filter=None)
        upsert_ts_consent(conn, "FRS1", "nobody", None)
        conn.commit(); conn.close()
        poller = self._ts_poller(db)
        poller._ts_streak = {}
        sent = []
        with patch("app.poller.fetch_channel_clients",
                   new=AsyncMock(return_value=[{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}])), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert sent == []

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

    @pytest.mark.asyncio
    async def test_snapshot_set_on_baseline_poll(self, tmp_path):
        """ts_clients wird auch im ersten (Baseline-)Poll gesetzt — für die Live-Anzeige."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        clients = [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}]
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=clients)), \
             patch("app.poller.send_web_push", new=AsyncMock()):
            await poller._poll_teamspeak()
        assert poller.ts_clients == clients

    @pytest.mark.asyncio
    async def test_snapshot_preserved_on_fetch_error(self, tmp_path):
        """Abruf-Fehler (None) lässt den letzten Snapshot stehen (kein Flackern)."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = self._ts_poller(db)
        poller.ts_clients = [{"frs": "FRS9", "nick": "Old/FRS9", "cid": 0}]
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=None)), \
             patch("app.poller.send_web_push", new=AsyncMock()):
            await poller._poll_teamspeak()
        assert poller.ts_clients == [{"frs": "FRS9", "nick": "Old/FRS9", "cid": 0}]

    @pytest.mark.asyncio
    async def test_display_only_without_vapid_sets_snapshot_no_push(self, tmp_path):
        """Ohne VAPID: Snapshot für die Anzeige, aber keine Push-Tasks (Display-only)."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = VatsimPoller(
            db_path=db, callsign_prefix="FRS", poll_interval=60,
            ts_notify_enabled=True, ts_poll_interval=30,
        )  # kein vapid_private_key
        clients = [{"frs": "FRS1", "nick": "Max/FRS1", "cid": 0}]
        sent = []
        with patch("app.poller.fetch_channel_clients", new=AsyncMock(return_value=clients)), \
             patch("app.poller.send_web_push", new=AsyncMock(side_effect=lambda *a, **k: sent.append(a))):
            await poller._poll_teamspeak()
            await asyncio.sleep(0)
        assert poller.ts_clients == clients
        assert sent == []
        # Streak/Notify-Logik wird im Display-only-Modus gar nicht erst betreten
        assert poller._ts_streak is None

    @pytest.mark.asyncio
    async def test_ts_job_registered_for_display_without_vapid(self, tmp_path):
        """ts_poll-Job läuft für die Live-Anzeige auch ohne VAPID."""
        from app.database import init_db
        db = str(tmp_path / "t.db"); init_db(db)
        poller = VatsimPoller(
            db_path=db, callsign_prefix="FRS", poll_interval=60,
            ts_notify_enabled=True, ts_poll_interval=30,
        )
        await poller.start()
        try:
            assert "ts_poll" in {j.id for j in poller._scheduler.get_jobs()}
        finally:
            await poller.stop()


class TestKutterLiveArrivalHook:
    @pytest.mark.asyncio
    async def test_poll_once_latches_live_arrival_without_disconnect(self, tmp_path):
        """Ein FRS-Pilot, der langsam (< 2 kt) im Zielradius eines laufenden Kutter-Events ist,
        wird SOFORT gelatcht -- ohne dass er disconnecten muss."""
        from app.database import (
            init_db, get_connection, create_transport_event, get_transport_live_arrivals,
        )
        from app.geo import icao_to_coords

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        conn = get_connection(db_file)
        event_id = create_transport_event(
            conn, name="Testkutter", route="EDWG,EDXH", destination="EDXH",
            dtstart="2020-01-01T00:00:00Z", dtend="2030-01-01T00:00:00Z",
        )
        conn.commit()
        conn.close()

        lat, lon = icao_to_coords("EDXH")

        poller = VatsimPoller(db_path=db_file, callsign_prefix="FRS", poll_interval=60)
        poller._http_client = AsyncMock()
        poller.subscribe_sse()

        vatsim_data = {
            "pilots": [{
                "cid": 555,
                "name": "Ludger Friesen",
                "callsign": "FRS55",
                "latitude": lat,
                "longitude": lon,
                "altitude": 0,
                "groundspeed": 1,
                "heading": 90,
                "logon_time": "2026-07-01T09:00:00Z",
                "flight_plan": {
                    "aircraft_short": "C208", "departure": "EDWG", "arrival": "EDXH",
                },
            }]
        }
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=vatsim_data)):
            await poller._poll_once()

        conn = get_connection(db_file)
        try:
            latches = get_transport_live_arrivals(conn, event_id)
        finally:
            conn.close()
        assert (555, "2026-07-01T09:00:00Z") in latches

    @pytest.mark.asyncio
    async def test_poll_once_no_active_event_no_latch(self, tmp_path):
        """Ohne laufendes Kutter-Event wird nichts gelatcht (kein Fehler, kein Latch)."""
        from app.database import init_db, get_connection
        from app.geo import icao_to_coords

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        lat, lon = icao_to_coords("EDXH")
        poller = VatsimPoller(db_path=db_file, callsign_prefix="FRS", poll_interval=60)
        poller._http_client = AsyncMock()
        poller.subscribe_sse()

        vatsim_data = {
            "pilots": [{
                "cid": 555, "name": "Ludger Friesen", "callsign": "FRS55",
                "latitude": lat, "longitude": lon, "altitude": 0, "groundspeed": 1, "heading": 90,
                "logon_time": "2026-07-01T09:00:00Z",
                "flight_plan": {"aircraft_short": "C208", "departure": "EDWG", "arrival": "EDXH"},
            }]
        }
        with patch("app.poller.fetch_vatsim_data", new=AsyncMock(return_value=vatsim_data)):
            await poller._poll_once()  # darf NICHT werfen

        conn = get_connection(db_file)
        try:
            row = conn.execute("SELECT COUNT(*) FROM transport_live_arrivals").fetchone()
        finally:
            conn.close()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# flight_cache Warm-up + Refresh (#23 Phase 2)
# ---------------------------------------------------------------------------

class TestFlightCacheWarmupAndRefresh:
    """_warmup_flight_cache/_refresh_flight_cache: synchroner Rebuild via to_thread,
    darf den Event-Loop nicht blockieren (hier nur die Endwirkung geprüft: flight_cache
    danach befüllt)."""

    def _seed_completed_flight(self, db_file: str) -> None:
        from datetime import datetime, timedelta, timezone
        from app.database import ensure_pilot, open_flight, close_flight, get_connection

        conn = get_connection(db_file)
        try:
            cid = 424242
            ensure_pilot(conn, cid, "Cache Pilot")
            conn.commit()
            start = datetime.now(timezone.utc) - timedelta(hours=2)
            fid = open_flight(
                conn, cid, "FRS77", "C172", "EDDW", "EDDK",
                start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            conn.commit()
            close_flight(
                conn, fid, (start + timedelta(minutes=44)).strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            conn.commit()
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_warmup_populates_flight_cache(self, tmp_path):
        from app.database import init_db, get_connection

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        self._seed_completed_flight(db_file)

        poller = _make_poller(db_path=db_file)
        await poller._warmup_flight_cache()  # darf nicht werfen

        conn = get_connection(db_file)
        try:
            count = conn.execute("SELECT COUNT(*) FROM flight_cache").fetchone()[0]
        finally:
            conn.close()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_refresh_populates_flight_cache(self, tmp_path):
        from app.database import init_db, get_connection

        db_file = str(tmp_path / "test.db")
        init_db(db_file)
        self._seed_completed_flight(db_file)

        poller = _make_poller(db_path=db_file)
        await poller._refresh_flight_cache()  # inkrementell, darf nicht werfen (Cache war leer)

        conn = get_connection(db_file)
        try:
            count = conn.execute("SELECT COUNT(*) FROM flight_cache").fetchone()[0]
        finally:
            conn.close()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_warmup_silent_fail_on_exception(self, tmp_path):
        """Ein Fehler beim Rebuild darf nicht nach außen dringen (App-Start nicht gefährden)."""
        db_file = str(tmp_path / "test.db")
        from app.database import init_db
        init_db(db_file)

        poller = _make_poller(db_path=db_file)
        with patch("app.poller.rebuild_flight_cache", side_effect=RuntimeError("boom")):
            await poller._warmup_flight_cache()  # darf NICHT werfen


# ---------------------------------------------------------------------------
# StatSim: proaktives Track-Nachladen (#23 Phase 2b)
# ---------------------------------------------------------------------------

class TestFetchStatsimTracks:
    """``get_settings`` wird hier direkt gepatcht (statt über Env-Var + lru_cache) — andere
    Testmodule (tests/test_config.py) rufen ``importlib.reload(app.config)`` auf, wonach
    ``app.poller.get_settings`` ein ANDERES Funktionsobjekt referenziert als ein frisch aus
    ``app.config`` importiertes ``get_settings``; ``cache_clear()`` auf Letzterem träfe dann
    nicht den von ``app.poller`` tatsächlich benutzten Cache (Testreihenfolge-abhängiges
    Flake). Direktes Patchen von ``app.poller.get_settings`` umgeht das robust."""

    @pytest.mark.asyncio
    async def test_no_api_key_early_return(self, tmp_path):
        """Ohne STATSIM_API_KEY: sofortiger, stiller Return — kein Crash, kein Fetch."""
        from types import SimpleNamespace
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        fake_settings = SimpleNamespace(STATSIM_API_KEY="", CALLSIGN_PREFIX="FRS")
        with patch("app.poller.get_settings", return_value=fake_settings), patch(
            "app.poller.fetch_flight_track", new=AsyncMock()
        ) as mock_fetch:
            await poller._fetch_statsim_tracks()  # darf nicht werfen

        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetches_uncached_ids_and_saves_positions(self, tmp_path):
        """Mit API-Key: ungecachte StatSim-IDs werden geholt und gespeichert; ein
        fehlschlagender Einzel-Fetch killt den Batch nicht."""
        from types import SimpleNamespace
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        fake_settings = SimpleNamespace(STATSIM_API_KEY="test-statsim-key", CALLSIGN_PREFIX="FRS")
        with patch("app.poller.get_settings", return_value=fake_settings), patch(
            "app.poller.get_uncached_statsim_ids", return_value=[101, 102]
        ), patch(
            "app.poller.fetch_flight_track",
            new=AsyncMock(side_effect=[RuntimeError("boom"), [
                {"latitude": 53.0, "longitude": 8.0, "altitude": 1000,
                 "groundspeed": 90, "heading": 10, "ts": "2026-07-01T10:00:00Z"},
            ]]),
        ), patch("app.poller.save_statsim_positions") as mock_save, patch(
            "app.poller.asyncio.sleep", new=AsyncMock()
        ):
            await poller._fetch_statsim_tracks()  # darf trotz Einzelfehler nicht werfen

        # Nur die zweite (erfolgreiche) ID wurde gespeichert; die erste (Exception) nicht.
        mock_save.assert_called_once()
        assert mock_save.call_args[0][1] == 102

    @pytest.mark.asyncio
    async def test_splits_batch_between_newest_and_oldest(self, tmp_path):
        """#61 (v8.6.1): reine "juengste zuerst"-Sortierung laesst alten Backlog verhungern --
        der Job muss get_uncached_statsim_ids sowohl mit oldest_first=False (juengste) als
        auch oldest_first=True (aelteste) aufrufen und beide Ergebnisse (dedupliziert) holen."""
        from types import SimpleNamespace
        from app.database import init_db

        db_file = str(tmp_path / "test.db")
        init_db(db_file)

        poller = _make_poller(db_path=db_file)
        poller._http_client = AsyncMock()

        def fake_uncached(conn, *, callsign_prefix, limit, oldest_first=False):
            return [999] if oldest_first else [201, 202]

        fake_settings = SimpleNamespace(STATSIM_API_KEY="test-statsim-key", CALLSIGN_PREFIX="FRS")
        with patch("app.poller.get_settings", return_value=fake_settings), patch(
            "app.poller.get_uncached_statsim_ids", side_effect=fake_uncached
        ), patch(
            "app.poller.fetch_flight_track", new=AsyncMock(return_value=[])
        ) as mock_fetch, patch("app.poller.asyncio.sleep", new=AsyncMock()):
            await poller._fetch_statsim_tracks()

        fetched_ids = [call.args[1] for call in mock_fetch.call_args_list]
        assert fetched_ids == [201, 202, 999]  # jüngste zuerst, dann der Backlog-Fund
