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
    delete_push_subscription,
    ensure_pilot,
    get_connection,
    get_live_positions,
    get_push_subscriptions_for_pilot,
    get_push_subscriptions_for_prefile,
    open_flight,
    remove_live_position,
    save_position_history,
    upsert_live_position,
)
from app.vatsim import fetch_vatsim_data, filter_friesen_pilots, pilot_to_position
from app.alerts import format_online_message, send_telegram_alert

logger = logging.getLogger(__name__)


async def send_web_push_notifications(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    pilot: dict,
) -> None:
    """Push-Notification an alle passenden Subscriptions senden."""
    import json as _json
    from pywebpush import webpush, WebPushException

    cid = pilot.get("cid")
    callsign = pilot.get("callsign", "?")
    dep = pilot.get("departure") or "?"
    arr = pilot.get("arrival") or "?"
    aircraft = pilot.get("aircraft_short") or pilot.get("aircraft") or ""

    payload = {
        "title": f"{callsign} ist online! ✈",
        "body": f"{dep} → {arr}" + (f" · {aircraft}" if aircraft else ""),
        "url": "/",
    }
    data = _json.dumps(payload)
    # vapid_private_key ist ein base64url-kodierter roher EC-Skalar (32 Byte),
    # direkt kompatibel mit py_vapid Vapid02.from_string().
    # Achtung: pywebpush modifiziert das claims-Dict in-place (fügt aud/exp hinzu)
    # → immer ein frisches Dict pro Aufruf erstellen (im Lambda).
    conn = get_connection(db_path)
    try:
        subscriptions = get_push_subscriptions_for_pilot(conn, cid)
    finally:
        conn.close()

    logger.info("WebPush: %s online, %d subscription(s)", callsign, len(subscriptions))

    loop = asyncio.get_event_loop()
    to_delete: list[str] = []

    for sub in subscriptions:
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        sent = False
        last_exc = None
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(5)
            try:
                await loop.run_in_executor(
                    None,
                    lambda s=sub_info: webpush(
                        subscription_info=s,
                        data=data,
                        vapid_private_key=vapid_private_key,
                        vapid_claims={"sub": vapid_contact_email},
                        ttl=3600,
                    ),
                )
                logger.info("WebPush sent OK: %s", sub["endpoint"][:40])
                sent = True
                break
            except WebPushException as exc:
                resp = getattr(exc, "response", None)
                sc = getattr(resp, "status_code", None)
                if sc == 410:
                    to_delete.append(sub["endpoint"])
                    break
                last_exc = exc
            except Exception as exc:
                last_exc = exc
                break
        if not sent and last_exc is not None:
            resp = getattr(last_exc, "response", None)
            sc = getattr(resp, "status_code", "?") if resp else type(last_exc).__name__
            cause = repr(getattr(last_exc, "__cause__", None))[:120]
            args = repr(getattr(last_exc, "args", ()))[:200]
            logger.warning("WebPush failed for %s: %s cause=%s args=%s", callsign, sc, cause, args)

    if to_delete:
        conn2 = get_connection(db_path)
        try:
            for endpoint in to_delete:
                delete_push_subscription(conn2, endpoint)
            conn2.commit()
        finally:
            conn2.close()


async def send_prefile_push_notifications(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    prefile: dict,
) -> None:
    """Push-Notification für neu eingereichten Flugplan an abonnierte Nutzer."""
    import json as _json
    from pywebpush import webpush, WebPushException

    cid = prefile.get("cid")
    callsign = prefile.get("callsign", "?")
    fp = prefile.get("flight_plan") or {}
    dep = fp.get("departure") or "?"
    arr = fp.get("arrival") or "?"
    aircraft = fp.get("aircraft_short") or fp.get("aircraft") or ""

    payload = {
        "title": f"{callsign} hat Flugplan eingereicht 📋",
        "body": f"{dep} → {arr}" + (f" · {aircraft}" if aircraft else ""),
        "url": "/",
    }
    data = _json.dumps(payload)

    conn = get_connection(db_path)
    try:
        subscriptions = get_push_subscriptions_for_prefile(conn, cid)
    finally:
        conn.close()

    if not subscriptions:
        return

    logger.info("PrefilePush: %s eingereicht, %d subscription(s)", callsign, len(subscriptions))

    loop = asyncio.get_event_loop()
    to_delete: list[str] = []

    for sub in subscriptions:
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            await loop.run_in_executor(
                None,
                lambda s=sub_info: webpush(
                    subscription_info=s,
                    data=data,
                    vapid_private_key=vapid_private_key,
                    vapid_claims={"sub": vapid_contact_email},
                    ttl=3600,
                ),
            )
        except WebPushException as exc:
            resp = getattr(exc, "response", None)
            if getattr(resp, "status_code", None) == 410:
                to_delete.append(sub["endpoint"])
        except Exception as exc:
            logger.warning("PrefilePush failed for %s: %r", callsign, exc)

    if to_delete:
        conn2 = get_connection(db_path)
        try:
            for endpoint in to_delete:
                delete_push_subscription(conn2, endpoint)
            conn2.commit()
        finally:
            conn2.close()


class VatsimPoller:
    def __init__(
        self,
        db_path: str,
        callsign_prefix: str = "FRS",
        poll_interval: int = 15,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        vapid_private_key: str = "",
        vapid_contact_email: str = "",
    ) -> None:
        self.db_path = db_path
        self.callsign_prefix = callsign_prefix
        self.poll_interval = poll_interval
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.vapid_private_key = vapid_private_key
        self.vapid_contact_email = vapid_contact_email
        self._scheduler: AsyncIOScheduler | None = None
        self._http_client: httpx.AsyncClient | None = None
        # State: cid → flight_id (offene Flüge)
        self._active_flights: dict[int, int] = {}
        # SSE broadcast queue: asyncio.Queue für Updates
        self.sse_queue: asyncio.Queue = asyncio.Queue()
        # Aktuell eingereichte Flugpläne (VATSIM prefiles) mit FRS*-Callsign
        # cid → (deptime, departure, arrival) — None = erster Poll, keine Notifications
        self.last_prefiles: dict | None = None

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
        # Cleanup deaktiviert — position_history wird dauerhaft behalten
        # self._scheduler.add_job(
        #     self._daily_cleanup,
        #     "cron",
        #     hour=3,
        #     minute=0,
        #     id="daily_cleanup",
        # )
        self._scheduler.add_job(
            self._sync_calendar,
            "interval",
            hours=6,
            id="calendar_sync",
        )
        # Kalender beim Start sofort einmal laden
        self._scheduler.add_job(
            self._sync_calendar,
            "date",
            id="calendar_sync_initial",
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
            online_pilots = filter_friesen_pilots(self.callsign_prefix, vatsim_data)

            # Prefiles mit FRS*-Callsign aus dem Feed speichern
            prefix = self.callsign_prefix.upper()
            current_prefiles = [
                p for p in (vatsim_data.get("prefiles") or [])
                if isinstance(p, dict) and p.get("callsign", "").upper().startswith(prefix)
            ]

            def _prefile_sig(p: dict) -> tuple:
                fp = p.get("flight_plan") or {}
                return (fp.get("deptime", ""), fp.get("departure", ""), fp.get("arrival", ""))

            current_map = {p["cid"]: p for p in current_prefiles if p.get("cid")}
            if self.last_prefiles is None:
                # Erster Poll nach Start — Baseline setzen, keine Notifications
                new_prefiles = []
            else:
                new_prefiles = [
                    p for cid, p in current_map.items()
                    if cid not in self.last_prefiles
                    or _prefile_sig(p) != self.last_prefiles[cid]
                ]
            self.last_prefiles = {cid: _prefile_sig(p) for cid, p in current_map.items()}

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
                        pos.get("flight_rules", ""),
                        pos.get("aircraft_icao", ""),
                        pos.get("alternate", ""),
                        pos.get("deptime", ""),
                        pos.get("cruise_tas", ""),
                        pos.get("enroute_time", ""),
                        pos.get("fuel_time", ""),
                        pos.get("route", ""),
                        pos.get("remarks", ""),
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

                    # Web Push notifications
                    if self.vapid_private_key:
                        asyncio.create_task(
                            send_web_push_notifications(
                                self.vapid_private_key,
                                self.vapid_contact_email,
                                self.db_path,
                                pos,
                            )
                        )

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
                        pos.get("flight_rules", ""),
                        pos.get("aircraft_icao", ""),
                        pos.get("alternate", ""),
                        pos.get("deptime", ""),
                        pos.get("cruise_tas", ""),
                        pos.get("enroute_time", ""),
                        pos.get("fuel_time", ""),
                        pos.get("route", ""),
                        pos.get("remarks", ""),
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

            # 4. Prefile-Benachrichtigungen für neu eingereichte/geänderte Flugpläne
            # Nur wenn Pilot NICHT bereits online ist (Prefile = Ankündigung, kein Duplikat)
            if self.vapid_private_key and new_prefiles:
                for pf in new_prefiles:
                    cid = pf.get("cid")
                    if not cid or cid in self._active_flights:
                        continue
                    asyncio.create_task(
                        send_prefile_push_notifications(
                            self.vapid_private_key,
                            self.vapid_contact_email,
                            self.db_path,
                            pf,
                        )
                    )

        except Exception:
            logger.exception("Error in _poll_once")

    # ------------------------------------------------------------------
    # Calendar sync
    # ------------------------------------------------------------------

    async def _sync_calendar(self) -> None:
        """FriesenFlieger Google-Kalender laden und in DB speichern."""
        try:
            from app.calendar_sync import fetch_and_parse_ical
            from app.database import upsert_calendar_events
            assert self._http_client is not None
            events = await fetch_and_parse_ical(self._http_client)
            if events:
                conn = get_connection(self.db_path)
                try:
                    upsert_calendar_events(conn, events)
                    conn.commit()
                finally:
                    conn.close()
                logger.info("Calendar sync: %d events gespeichert", len(events))
        except Exception:
            logger.exception("Error in _sync_calendar")

    # ------------------------------------------------------------------
    # Daily cleanup
    # ------------------------------------------------------------------

    async def _daily_cleanup(self) -> None:
        """position_history älter als 365 Tage löschen. Exceptions loggen."""
        try:
            conn = get_connection(self.db_path)
            try:
                deleted = cleanup_old_history(conn, days=365)
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
        callsign_prefix=settings.CALLSIGN_PREFIX,
        poll_interval=settings.VATSIM_POLL_INTERVAL,
        telegram_token=settings.TELEGRAM_BOT_TOKEN,
        telegram_chat_id=settings.TELEGRAM_CHAT_ID,
        vapid_private_key=settings.VAPID_PRIVATE_KEY,
        vapid_contact_email=settings.VAPID_CONTACT_EMAIL,
    )
