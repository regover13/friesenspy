"""VatsimPoller — APScheduler-basierter Hintergrundprozess für FriesenSpy.

Ruft VATSIM-Daten ab, verwaltet eine Flug-State-Machine für Friesen-Piloten
und publiziert Live-Positions-Updates in eine asyncio.Queue für SSE-Clients.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.database import (
    cleanup_old_history,
    close_flight,
    ensure_pilot,
    get_connection,
    get_live_positions,
    open_flight,
    remove_live_position,
    save_position_history,
    upsert_live_position,
)
from app.vatsim import fetch_vatsim_data, filter_friesen_pilots, pilot_to_position
from app.alerts import format_online_message, send_telegram_alert
from app.board import fetch_friesen_cids

logger = logging.getLogger(__name__)


class VatsimPoller:
    def __init__(
        self,
        db_path: str,
        cids: list[int],
        poll_interval: int = 15,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        board_url: str = "",
        board_username: str = "",
        board_password: str = "",
    ) -> None:
        self.db_path = db_path
        self.cids = cids
        self.poll_interval = poll_interval
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.board_url = board_url
        self.board_username = board_username
        self.board_password = board_password
        self._scheduler: AsyncIOScheduler | None = None
        self._http_client: httpx.AsyncClient | None = None
        # State: cid → flight_id (offene Flüge)
        self._active_flights: dict[int, int] = {}
        # SSE broadcast queue: asyncio.Queue für Updates
        self.sse_queue: asyncio.Queue = asyncio.Queue()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """HTTP-Client + Scheduler starten."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._poll_once,
            "interval",
            seconds=self.poll_interval,
            id="vatsim_poll",
        )
        self._scheduler.add_job(
            self._daily_cleanup,
            "cron",
            hour=3,
            minute=0,
            id="daily_cleanup",
        )
        self._scheduler.add_job(
            self._refresh_cids_from_board,
            "cron",
            hour=4,
            minute=0,
            id="board_cid_refresh",
        )
        self._scheduler.start()

    async def stop(self) -> None:
        """Scheduler + HTTP-Client sauber beenden."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._http_client:
            await self._http_client.aclose()

    # ------------------------------------------------------------------
    # Core poll loop
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        """Hauptlogik: VATSIM abfragen, State-Machine ausführen.

        State-Machine:
        1. VATSIM-Daten abrufen → filter_friesen_pilots
        2. Aktuell online CIDs mit _active_flights vergleichen:
           - Neu online  → ensure_pilot, open_flight, upsert_live_position,
                           save_position_history, Telegram-Alert senden
           - Noch online → upsert_live_position, save_position_history
           - Offline     → close_flight, remove_live_position,
                           _active_flights[cid] entfernen
        3. SSE-Queue: get_live_positions() → {"type": "positions", "data": [...]}
        4. Exceptions → logging.exception, NICHT weiterwerfen
        """
        try:
            assert self._http_client is not None, "HTTP client not initialised"

            # 1. Fetch + filter
            vatsim_data = await fetch_vatsim_data(self._http_client)
            online_pilots = filter_friesen_pilots(self.cids, vatsim_data)

            # Build lookup: cid → position dict
            current: dict[int, dict] = {
                p["cid"]: p
                for pilot in online_pilots
                for p in [pilot_to_position(pilot)]
                if p["cid"] is not None
            }

            current_cids = set(current.keys())
            active_cids = set(self._active_flights.keys())

            newly_online = current_cids - active_cids
            still_online = current_cids & active_cids
            went_offline = active_cids - current_cids

            conn = get_connection(self.db_path)
            try:
                # 2a. Newly online pilots
                for cid in newly_online:
                    pos = current[cid]
                    ensure_pilot(conn, cid, pos["name"])
                    flight_id = open_flight(
                        conn,
                        cid,
                        pos["callsign"],
                        pos["aircraft_short"],
                        pos["departure"],
                        pos["arrival"],
                        pos["logon_time"],
                    )
                    upsert_live_position(
                        conn,
                        cid,
                        pos["callsign"],
                        pos["aircraft"],
                        pos["departure"],
                        pos["arrival"],
                        pos["latitude"],
                        pos["longitude"],
                        pos["altitude"],
                        pos["groundspeed"],
                        pos["heading"],
                        pos["logon_time"],
                    )
                    save_position_history(
                        conn,
                        cid,
                        pos["callsign"],
                        pos["latitude"],
                        pos["longitude"],
                        pos["altitude"],
                        pos["groundspeed"],
                        pos["heading"],
                    )
                    self._active_flights[cid] = flight_id

                    # Telegram alert (only when token + chat_id configured)
                    if self.telegram_token and self.telegram_chat_id:
                        message = format_online_message(
                            pos["name"],
                            pos["callsign"],
                            pos["departure"],
                            pos["arrival"],
                        )
                        try:
                            await send_telegram_alert(
                                message,
                                self.telegram_token,
                                self.telegram_chat_id,
                                self._http_client,
                            )
                        except Exception:
                            logger.exception("Error sending Telegram alert for cid=%s", cid)

                # 2b. Still online pilots — update position
                for cid in still_online:
                    pos = current[cid]
                    upsert_live_position(
                        conn,
                        cid,
                        pos["callsign"],
                        pos["aircraft"],
                        pos["departure"],
                        pos["arrival"],
                        pos["latitude"],
                        pos["longitude"],
                        pos["altitude"],
                        pos["groundspeed"],
                        pos["heading"],
                        pos["logon_time"],
                    )
                    save_position_history(
                        conn,
                        cid,
                        pos["callsign"],
                        pos["latitude"],
                        pos["longitude"],
                        pos["altitude"],
                        pos["groundspeed"],
                        pos["heading"],
                    )

                # 2c. Pilots who went offline
                logoff_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for cid in went_offline:
                    flight_id = self._active_flights[cid]
                    close_flight(conn, flight_id, logoff_time)
                    remove_live_position(conn, cid)
                    del self._active_flights[cid]

                conn.commit()

                # 3. Push SSE update
                live_positions = get_live_positions(conn)
            finally:
                conn.close()

            self.sse_queue.put_nowait({"type": "positions", "data": live_positions})

        except Exception:
            logger.exception("Error in _poll_once")

    # ------------------------------------------------------------------
    # Board CID refresh (täglich 04:00)
    # ------------------------------------------------------------------

    async def _refresh_cids_from_board(self) -> None:
        """CID-Liste aus FriesenFlieger-Board aktualisieren. Silent fail."""
        if not self.board_username or not self.board_password:
            return
        try:
            fresh_cids = await fetch_friesen_cids(
                self.board_url, self.board_username, self.board_password
            )
            if fresh_cids:
                self.cids = fresh_cids
                logger.info("CID-Liste aktualisiert: %d Piloten", len(fresh_cids))
        except Exception:
            logger.exception("Fehler beim Aktualisieren der CID-Liste")

    # ------------------------------------------------------------------
    # Daily cleanup
    # ------------------------------------------------------------------

    async def _daily_cleanup(self) -> None:
        """position_history älter als 90 Tage löschen. Exceptions loggen."""
        try:
            conn = get_connection(self.db_path)
            try:
                deleted = cleanup_old_history(conn, days=90)
                conn.commit()
            finally:
                conn.close()
            logger.info("Daily cleanup: deleted %d old position_history rows", deleted)
        except Exception:
            logger.exception("Error in _daily_cleanup")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_poller() -> VatsimPoller:
    """Erstellt VatsimPoller aus Settings."""
    settings = get_settings()
    return VatsimPoller(
        db_path=settings.DB_PATH,
        cids=settings.cids,
        poll_interval=settings.VATSIM_POLL_INTERVAL,
        telegram_token=settings.TELEGRAM_BOT_TOKEN,
        telegram_chat_id=settings.TELEGRAM_CHAT_ID,
        board_url=settings.BOARD_URL,
        board_username=settings.BOARD_USERNAME,
        board_password=settings.BOARD_PASSWORD,
    )
