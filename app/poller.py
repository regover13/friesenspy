"""VatsimPoller — APScheduler-basierter Hintergrundprozess für FriesenSpy.

Ruft VATSIM-Daten ab, verwaltet eine Flug-State-Machine für Friesen-Piloten
und publiziert Live-Positions-Updates in eine asyncio.Queue für SSE-Clients.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from pywebpush import webpush, WebPushException
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
    cid_for_callsign,
    get_ts_consent,
    get_ts_push_subscriptions,
    last_known_aircraft,
    load_prefile_sigs,
    open_flight,
    remove_live_position,
    save_position_history,
    save_prefile_sigs,
    update_flight_plan,
    upsert_live_position,
    upsert_statsim_flights,
    active_transport_destinations,
    check_live_arrival,
)
from app.vatsim import fetch_vatsim_data, filter_friesen_pilots, pilot_to_position
from app.alerts import format_online_message, send_telegram_alert
from app.statsim import fetch_pilot_flights
from app.teamspeak import fetch_channel_clients, parse_channel_ids

logger = logging.getLogger(__name__)

# Beim Start bereits präsente FRS bekommen diesen (sehr hohen) Streak-Wert, damit sie die
# Verweildauer-Schwelle nie exakt treffen und somit keine Baseline-Notification auslösen.
_TS_BASELINE_STREAK = 1_000_000

# Max. Anzahl gepufferter SSE-Updates pro Client. Nur der jüngste Stand zählt; bei einem
# gedrosselten/hängenden Client wird der älteste verworfen (Drop-Oldest), statt unbegrenzt
# zu wachsen — deckelt zugleich den Rückstau, der einen Hintergrund-Tab beim Wiederöffnen flutet.
_SSE_QUEUE_MAXSIZE = 50


async def _load_statsim_history(cid: int, api_key: str, db_path: str) -> None:
    """Lädt 365-Tage-History von StatSim für einen neu erkannten Piloten."""
    try:
        async with httpx.AsyncClient() as client:
            flights = await fetch_pilot_flights(client, cid, api_key, days=365)
        for f in flights:
            f["cid"] = cid
        conn = get_connection(db_path)
        try:
            upsert_statsim_flights(conn, flights)
            conn.commit()
            # Frisch geladene StatSim-Historie kann verwaiste eigene Tracks decken (A1-Schaden)
            # → sofort rekonstruieren, nicht erst beim nächsten Container-Start.
            try:
                from app.database import reconstruct_orphaned_flights
                if reconstruct_orphaned_flights(conn, cids=[cid]):
                    conn.commit()
            except Exception:
                logger.exception("Track-Rekonstruktion nach StatSim-Load fehlgeschlagen")
        finally:
            conn.close()
        logger.info("StatSim history loaded for new pilot CID %s (%d flights)", cid, len(flights))
    except Exception as e:
        logger.warning("StatSim history load failed for CID %s: %s", cid, type(e).__name__)


async def send_web_push(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    subscriptions: list[dict],
    payload: dict,
    label: str = "WebPush",
) -> None:
    """Ein Payload-Dict an eine fertige Subscription-Liste senden.

    Generischer Kern: Retry (1×), 410-Endpoint-Cleanup, Silent-Fail-Logging.
    Wird von der VATSIM- und der TS-Seite gemeinsam genutzt.
    """
    import json as _json

    if not subscriptions:
        return
    data = _json.dumps(payload)
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
                logger.info("%s sent OK: %s", label, sub["endpoint"][:40])
                sent = True
                break
            except WebPushException as exc:
                resp = getattr(exc, "response", None)
                sc = getattr(resp, "status_code", None)
                if sc == 410:
                    to_delete.append(sub["endpoint"])
                    break
                if sc == 403 and resp is not None and "do not correspond" in (getattr(resp, "text", "") or ""):
                    # Subscription mit alten VAPID-Keys angelegt → mit aktuellen Keys nie zustellbar.
                    # Aufräumen wie bei 410; der Client re-registriert beim nächsten Besuch.
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
            logger.warning("%s failed: %s cause=%s args=%s", label, sc, cause, args)

    if to_delete:
        # In try/except, weil send_web_push als fire-and-forget create_task läuft: ein
        # Cleanup-Fehler (z. B. DB kurz nicht erreichbar) darf keine "Task exception was
        # never retrieved"-Warnung erzeugen.
        try:
            conn = get_connection(db_path)
            try:
                for endpoint in to_delete:
                    delete_push_subscription(conn, endpoint)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("%s: Endpoint-Cleanup fehlgeschlagen", label)


async def send_web_push_notifications(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    pilot: dict,
) -> None:
    """Push-Notification an alle passenden Subscriptions senden."""
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
    conn = get_connection(db_path)
    try:
        subscriptions = get_push_subscriptions_for_pilot(conn, cid)
    finally:
        conn.close()

    logger.info("WebPush: %s online, %d subscription(s)", callsign, len(subscriptions))
    await send_web_push(
        vapid_private_key, vapid_contact_email, db_path,
        subscriptions, payload, label=f"WebPush[{callsign}]",
    )


async def send_prefile_push_notifications(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    prefile: dict,
) -> None:
    """Push-Notification für neu eingereichten Flugplan an abonnierte Nutzer."""
    import json as _json

    import re as _re
    cid = prefile.get("cid")
    callsign = prefile.get("callsign", "?")
    fp = prefile.get("flight_plan") or {}
    dep = fp.get("departure") or "?"
    arr = fp.get("arrival") or "?"
    aircraft = fp.get("aircraft_short") or fp.get("aircraft") or ""
    deptime = fp.get("deptime") or ""
    remarks = fp.get("remarks") or ""

    dof_m = _re.search(r'DOF/(\d{2})(\d{2})(\d{2})', remarks)
    if dof_m:
        date_str = f"{dof_m.group(3)}.{dof_m.group(2)}.20{dof_m.group(1)}"
    else:
        date_str = ""
    time_str = f"{deptime[:2]}:{deptime[2:]} UTC" if len(deptime) == 4 else ""
    when = " · ".join(filter(None, [date_str, time_str]))

    payload = {
        "title": f"{callsign} hat Flugplan eingereicht 📋",
        "body": f"{dep} → {arr}" + (f" · {when}" if when else "") + (f" · {aircraft}" if aircraft else ""),
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
            logger.info("PrefilePush sent OK: %s", sub["endpoint"][:40])
        except WebPushException as exc:
            resp = getattr(exc, "response", None)
            sc = getattr(resp, "status_code", None)
            body_text = getattr(resp, "text", "")[:200] if resp else ""
            if sc == 410 or (sc == 403 and "do not correspond" in body_text):
                # 410 = abgemeldet; 403 mit VAPID-Mismatch = alte Keys → beides aufräumen.
                to_delete.append(sub["endpoint"])
            else:
                logger.warning("PrefilePush failed for %s: HTTP %s — %s", callsign, sc, body_text)
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
        vatsim_rejoin_debounce_sec: int = 900,
        ts_notify_enabled: bool = False,
        ts_host: str = "127.0.0.1",
        ts_query_port: int = 10011,
        ts_query_user: str = "",
        ts_query_pass: str = "",
        ts_server_id: int = 1,
        ts_notify_channel_id: int = 0,
        ts_exclude_channel_ids: frozenset[int] = frozenset(),
        ts_min_dwell_polls: int = 1,
        ts_poll_interval: int = 30,
        ts_rejoin_debounce_sec: int = 900,
    ) -> None:
        self.db_path = db_path
        self.callsign_prefix = callsign_prefix
        self.poll_interval = poll_interval
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.vapid_private_key = vapid_private_key
        self.vapid_contact_email = vapid_contact_email
        self.vatsim_rejoin_debounce_sec = vatsim_rejoin_debounce_sec
        self.ts_notify_enabled = ts_notify_enabled
        self.ts_host = ts_host
        self.ts_query_port = ts_query_port
        self.ts_query_user = ts_query_user
        self.ts_query_pass = ts_query_pass
        self.ts_server_id = ts_server_id
        self.ts_notify_channel_id = ts_notify_channel_id
        self.ts_exclude_channel_ids = ts_exclude_channel_ids
        self.ts_min_dwell_polls = ts_min_dwell_polls
        self.ts_poll_interval = ts_poll_interval
        self.ts_rejoin_debounce_sec = ts_rejoin_debounce_sec
        self._scheduler: AsyncIOScheduler | None = None
        self._http_client: httpx.AsyncClient | None = None
        # State: cid → {"id": flight_id, "dep": departure, "arr": arrival}
        self._active_flights: dict[int, dict] = {}
        # SSE: jede aktive Client-Verbindung registriert ihre EIGENE Queue; broadcast_sse()
        # verteilt jedes Update an alle. (Eine geteilte Queue lieferte jede Nachricht nur an
        # EINEN Consumer → nicht alle Clients bekamen Updates.)
        self._sse_subscribers: set[asyncio.Queue] = set()
        # Vollständige Prefile-Daten für die API (Liste von Dicts)
        self.last_prefiles: list = []
        # cid → (deptime, departure, arrival) für Änderungserkennung — None = erster Poll
        self._prefile_sigs: dict | None = None
        # cid → Zeitpunkt der letzten Online-Benachrichtigung (Debounce gegen vPilot-Reconnects).
        self._online_last_notified: dict[int, datetime] = {}
        # TS-Login: FRS → Anzahl konsekutiver Polls, in denen die FRS präsent war.
        # None = vor dem ersten erfolgreichen Poll (Baseline noch nicht gesetzt).
        # Beim Start präsente FRS werden mit _TS_BASELINE_STREAK markiert (lösen nie aus).
        self._ts_streak: dict[str, int] | None = None
        # FRS → Zeitpunkt der letzten Benachrichtigung (Debounce gegen Re-Joins).
        self._ts_last_notified: dict[str, datetime] = {}
        # Letzter TS-Client-Snapshot für die Live-Anzeige (FRS-getaggte Clients).
        self.ts_clients: list[dict] = []
        # Typcodes, für die in dieser Prozess-Lebensdauer bereits eine Auto-Recherche lief —
        # verhindert Wiederholungen/Kosten.
        self._payload_research_attempted: set[str] = set()
        # cid → (aircraft_short, aircraft_icao) aus früheren Flügen — Typ-Fallback für
        # Piloten ohne Flugplan (der Feed führt den Typ nur im flight_plan). Prozess-Cache,
        # damit nicht jeder Poll die flights-Tabelle abfragt.
        self._last_type_cache: dict[int, tuple[str, str]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """HTTP-Client + Scheduler starten."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        # Prefile-Signaturen aus DB laden → Neustart verpasst keine Änderungen mehr
        conn = get_connection(self.db_path)
        try:
            self._prefile_sigs = load_prefile_sigs(conn)
        except Exception:
            logger.exception("Fehler beim Laden der Prefile-Signaturen aus DB")
            self._prefile_sigs = None
        finally:
            conn.close()
        logger.info("Prefile-Signaturen geladen: %d Einträge", len(self._prefile_sigs or {}))
        # Rehydration: offene Flüge aus der DB in den In-Memory-State laden, damit ein
        # Container-Neustart laufende Flüge adoptiert (kein Reopen-Duplikat, kein Zombie).
        # init_db() hat zuvor konsolidiert → ≤ 1 offener Flug je cid.
        conn = get_connection(self.db_path)
        try:
            for r in conn.execute(
                "SELECT cid, id, departure, arrival FROM flights "
                "WHERE logoff_time IS NULL AND superseded_by IS NULL"
            ).fetchall():
                self._active_flights[r["cid"]] = {
                    "id": r["id"], "dep": r["departure"] or "", "arr": r["arrival"] or "",
                }
        except Exception:
            logger.exception("Fehler bei der Rehydration offener Flüge")
        finally:
            conn.close()
        logger.info("Rehydration: %d offene Flüge adoptiert", len(self._active_flights))
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
        # Bummel-Enthüllung regelmäßig prüfen (dtend erreicht + niemand mehr unterwegs)
        self._scheduler.add_job(
            self._check_bummel_reveals,
            "interval",
            seconds=60,
            id="bummel_reveal_check",
        )
        # FriesenKutter: Start/Ziel/Feierabend-Pushs latchen
        self._scheduler.add_job(
            self._check_transport_events,
            "interval",
            seconds=60,
            id="transport_event_check",
        )
        # Event-Erinnerung (~1 h vor Beginn) regelmäßig prüfen
        self._scheduler.add_job(
            self._check_event_reminders,
            "interval",
            minutes=5,
            id="event_reminder_check",
        )
        if self.ts_notify_enabled:
            # Job läuft für die Live-Anzeige unabhängig von VAPID; Push-Versand ist in
            # _poll_teamspeak separat durch vapid_private_key gegated.
            self._scheduler.add_job(
                self._poll_teamspeak,
                "interval",
                seconds=self.ts_poll_interval,
                id="ts_poll",
            )
            logger.info("TS-Überwachung aktiv (Kanal %d, %ds)",
                        self.ts_notify_channel_id, self.ts_poll_interval)
            if not self.vapid_private_key:
                logger.warning(
                    "TS_NOTIFY_ENABLED=true, aber kein VAPID_PRIVATE_KEY gesetzt → "
                    "Live-Anzeige aktiv, aber keine TS-Push-Benachrichtigungen."
                )
            if self.ts_notify_channel_id == 0:
                logger.warning(
                    "TS_NOTIFY_CHANNEL_ID=0 → serverweites FRS-Tracking "
                    "(kein Kanal-Filter). Falls unbeabsichtigt, Zielkanal-ID setzen."
                )
        self._scheduler.start()

    async def stop(self) -> None:
        """Scheduler + HTTP-Client sauber beenden."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._http_client:
            await self._http_client.aclose()

    # ------------------------------------------------------------------
    # SSE-Broadcast (Per-Client-Fan-out)
    # ------------------------------------------------------------------

    def subscribe_sse(self) -> asyncio.Queue:
        """Registriert eine neue Client-Queue und gibt sie zurück."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_SSE_QUEUE_MAXSIZE)
        self._sse_subscribers.add(q)
        return q

    def unsubscribe_sse(self, q: asyncio.Queue) -> None:
        """Deregistriert eine Client-Queue (idempotent)."""
        self._sse_subscribers.discard(q)

    def broadcast_sse(self, message: dict) -> None:
        """Verteilt ein Update an alle aktiven SSE-Clients (non-blocking).

        Iteriert über einen Snapshot; der Loop ist synchron (kein await), läuft also nicht
        mit subscribe/unsubscribe verschachtelt (Single-Event-Loop). Bei voller Client-Queue
        wird der älteste Eintrag verworfen und der neueste eingesetzt (Drop-Oldest).
        """
        for q in list(self._sse_subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(message)
                except Exception:
                    pass

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
           - Live-Ankunft (FriesenKutter) → check_live_arrival je Pilot gegen laufende Events
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
            if self._prefile_sigs is None:
                # Erster Poll nach Start — Baseline setzen, keine Notifications
                new_prefiles = []
            else:
                new_prefiles = [
                    p for cid, p in current_map.items()
                    if cid not in self._prefile_sigs
                    or _prefile_sig(p) != self._prefile_sigs[cid]
                ]
            self._prefile_sigs = {cid: _prefile_sig(p) for cid, p in current_map.items()}
            self.last_prefiles = current_prefiles
            # Signaturen in DB persistieren (Neustart-Robustheit)
            sig_conn = get_connection(self.db_path)
            try:
                save_prefile_sigs(sig_conn, self._prefile_sigs)
                sig_conn.commit()
            except Exception:
                logger.exception("Fehler beim Speichern der Prefile-Signaturen")
            finally:
                sig_conn.close()

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
                # Typ-Fallback ohne Flugplan (vatsim-radar-Prinzip): der öffentliche Feed
                # führt den Flugzeugtyp NUR im flight_plan. Ohne Plan nehmen wir das
                # Prefile des Piloten bzw. sein zuletzt gefiltes Muster aus früheren
                # Flügen — damit funktionieren Anzeige und Kutter-Zuladung auch ohne Plan.
                for cid, pos in current.items():
                    if pos.get("aircraft_short"):
                        continue
                    fp = (current_map.get(cid) or {}).get("flight_plan") or {}
                    short = fp.get("aircraft_short") or (fp.get("aircraft") or "").split("/")[0]
                    icao = fp.get("aircraft_icao") or short
                    if not short:
                        cached = self._last_type_cache.get(cid)
                        if cached is None:
                            cached = last_known_aircraft(conn, cid)
                            self._last_type_cache[cid] = cached
                        short, icao = cached
                    if short:
                        pos["aircraft"] = pos["aircraft_short"] = short
                        pos["aircraft_icao"] = icao or short

                # 2a. Newly online pilots
                for cid in newly_online:
                    pos = current[cid]
                    is_new_pilot = ensure_pilot(conn, cid, pos["name"])
                    if is_new_pilot and get_settings().STATSIM_API_KEY:
                        asyncio.create_task(
                            _load_statsim_history(cid, get_settings().STATSIM_API_KEY, self.db_path)
                        )
                        logger.info("Neuer Pilot CID %s — StatSim 365-Tage-Load gestartet", cid)
                    flight_id = open_flight(
                        conn,
                        cid,
                        pos["callsign"],
                        pos["aircraft_short"],
                        pos["departure"],
                        pos["arrival"],
                        pos["logon_time"],
                        route=pos.get("route", ""),
                        remarks=pos.get("remarks", ""),
                        cruise_altitude=pos.get("cruise_altitude", ""),
                        cruise_tas=pos.get("cruise_tas", ""),
                        flight_rules=pos.get("flight_rules", ""),
                        aircraft_icao=pos.get("aircraft_icao", ""),
                        alternate=pos.get("alternate", ""),
                        deptime=pos.get("deptime", ""),
                        enroute_time=pos.get("enroute_time", ""),
                        fuel_time=pos.get("fuel_time", ""),
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
                    self._active_flights[cid] = {
                        "id": flight_id,
                        "dep": pos["departure"] or "",
                        "arr": pos["arrival"] or "",
                    }

                    # Reconnect-Debounce: ging dieser Pilot innerhalb des Fensters schon einmal
                    # online (vPilot-Reconnect), keine erneute Benachrichtigung. State/DB oben
                    # läuft unabhängig weiter — nur das Versenden wird gedämpft.
                    notify_now = datetime.now(timezone.utc)
                    last_notified = self._online_last_notified.get(cid)
                    is_rejoin = (
                        last_notified is not None
                        and (notify_now - last_notified).total_seconds() < self.vatsim_rejoin_debounce_sec
                    )
                    if is_rejoin:
                        logger.info("Online-Reconnect CID %s innerhalb Debounce → keine Benachrichtigung", cid)
                    else:
                        self._online_last_notified[cid] = notify_now

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
                    # Flugplan-Änderung prüfen
                    entry = self._active_flights[cid]
                    new_dep = pos.get("departure") or ""
                    new_arr = pos.get("arrival") or ""
                    old_dep, old_arr = entry["dep"], entry["arr"]
                    if (new_dep or new_arr) and (new_dep != old_dep or new_arr != old_arr):
                        if not (old_dep or old_arr) or new_dep == old_dep:
                            # Kein alter Plan ODER gleicher Abflughafen (Planänderung am SELBEN Leg
                            # — z. B. ARR/Route korrigiert) → Plan im laufenden Flug aktualisieren,
                            # kein Split. Eine Connection bleibt ein Flug.
                            update_flight_plan(
                                conn, entry["id"], new_dep, new_arr,
                                route=pos.get("route", ""),
                                remarks=pos.get("remarks", ""),
                                cruise_altitude=pos.get("cruise_altitude", ""),
                                cruise_tas=pos.get("cruise_tas", ""),
                                flight_rules=pos.get("flight_rules", ""),
                                aircraft_icao=pos.get("aircraft_icao", ""),
                                alternate=pos.get("alternate", ""),
                            )
                            entry["dep"], entry["arr"] = new_dep, new_arr
                            logger.info("Flugplan aktualisiert CID %s: %s→%s", cid, new_dep, new_arr)
                        else:
                            # Abflughafen GEÄNDERT → echtes neues Leg (Pilot gelandet, neu gefiled,
                            # selbe VATSIM-Verbindung). Altes Segment schließen, neues mit
                            # eindeutiger Mikrosekunden-logon_time öffnen — kollidiert nie mit dem
                            # partiellen Unique-Index, sodass beide Legs erhalten bleiben.
                            now_close = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            now_logon = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                            close_flight(conn, entry["id"], now_close)
                            new_id = open_flight(
                                conn, cid, pos["callsign"],
                                pos.get("aircraft_short", ""), new_dep, new_arr, now_logon,
                                route=pos.get("route", ""),
                                remarks=pos.get("remarks", ""),
                                cruise_altitude=pos.get("cruise_altitude", ""),
                                cruise_tas=pos.get("cruise_tas", ""),
                                flight_rules=pos.get("flight_rules", ""),
                                aircraft_icao=pos.get("aircraft_icao", ""),
                                alternate=pos.get("alternate", ""),
                            )
                            self._active_flights[cid] = {"id": new_id, "dep": new_dep, "arr": new_arr}
                            logger.info(
                                "Neues Leg CID %s: %s→%s → %s→%s",
                                cid, old_dep, old_arr, new_dep, new_arr,
                            )

                # 2c. Live-Ankunft prüfen (FriesenKutter, ohne Disconnect) — läuft im selben
                # Poll-Takt mit, kein eigener Timer. Nutzt dieselben Live-Positionen, die 2a/2b
                # gerade aktualisiert haben.
                now_check = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                active_events = active_transport_destinations(conn, now_check)
                if active_events:
                    for cid in current_cids:
                        pos = current[cid]
                        check_live_arrival(
                            conn, cid, pos["logon_time"], pos["latitude"], pos["longitude"],
                            pos["groundspeed"], active_events,
                        )

                # 2d. Pilots who went offline
                # Logoff = letzter echter Beleg (letzte gespeicherte Position dieses Fluges),
                # nicht die Wanduhr. Der Pilot verschwand diesen Poll; zuletzt gesehen wurde er
                # beim vorigen Poll → kein Über-Zählen, keine Inflation.
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for cid in went_offline:
                    flight_id = self._active_flights[cid]["id"]
                    row = conn.execute(
                        "SELECT logon_time FROM flights WHERE id = ?", (flight_id,)
                    ).fetchone()
                    last_pos = None
                    if row is not None:
                        last_pos = conn.execute(
                            "SELECT MAX(ts) FROM position_history WHERE cid = ? AND ts >= ?",
                            (cid, row[0]),
                        ).fetchone()[0]
                    close_flight(conn, flight_id, last_pos or now_str)
                    remove_live_position(conn, cid)
                    del self._active_flights[cid]

                conn.commit()

                # 3. Push SSE update
                live_positions = get_live_positions(conn)

                # Neu gesehene Flugzeugtypen: Zuladung automatisch recherchieren + vorbefüllen
                # (Admin kann die Werte jederzeit überschreiben; source='llm' kennzeichnet sie).
                from app.database import get_payload_map, normalize_type_code
                known_types = set(get_payload_map(conn).keys())
                new_codes = []
                for pos in current.values():
                    code = normalize_type_code(pos.get("aircraft_icao") or pos.get("aircraft_short"))
                    if code and code not in known_types and code not in self._payload_research_attempted:
                        self._payload_research_attempted.add(code)
                        new_codes.append(code)
            finally:
                conn.close()

            self.broadcast_sse({"type": "positions", "data": live_positions})

            # Auto-Recherche für neu gesehene Typcodes im Hintergrund anstoßen (nur mit Key)
            if new_codes:
                from app import llm
                if llm.is_configured():
                    for code in new_codes:
                        asyncio.create_task(self._auto_research_payload(code))

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

    async def _poll_teamspeak(self) -> None:
        """TS-ServerQuery pollen, neue FRS-Beitritte → WebPush. Exceptions nur loggen."""
        try:
            clients = await fetch_channel_clients(
                host=self.ts_host,
                port=self.ts_query_port,
                user=self.ts_query_user,
                password=self.ts_query_pass,
                server_id=self.ts_server_id,
                channel_id=self.ts_notify_channel_id,
                exclude_channel_ids=self.ts_exclude_channel_ids,
            )
            if clients is None:
                # ServerQuery nicht erreichbar / Login-Fehler → Poll überspringen, State
                # unangetastet lassen. Ein leeres [] dagegen ist ein echt leerer Kanal und
                # ein gültiger Zustand zum Diffen — nur None heißt "nicht abrufbar".
                # Snapshot NICHT leeren: letzter Stand bleibt für die Anzeige stehen.
                return
            # Snapshot für die Live-Anzeige (FRS-getaggte Clients) — vor der Streak-/Notify-
            # Logik und vor dem Baseline-return, damit die Anzeige auch beim ersten Poll und
            # im reinen Display-Modus (ohne VAPID) Daten hat.
            self.ts_clients = clients
            # Anzeige ist unabhängig von Push: ohne VAPID keine Benachrichtigung, Snapshot steht.
            if not self.vapid_private_key:
                return
            current = {c["frs"] for c in clients}
            nick_by_frs = {c["frs"]: c["nick"] for c in clients}

            if self._ts_streak is None:
                # Erster erfolgreicher Poll nach Start — Baseline setzen (auch ein leerer
                # Kanal ist gültig). Präsente FRS bekommen einen hohen Streak, sodass sie die
                # Verweildauer-Schwelle nie treffen → keine Baseline-Notification.
                self._ts_streak = {frs: _TS_BASELINE_STREAK for frs in current}
                return

            # Verweildauer-Bestätigung: Streak je präsenter FRS hochzählen; abwesende FRS
            # fallen aus dem Dict (Streak-Reset). Benachrichtigt wird genau in dem Poll, in
            # dem der Streak die Schwelle (min_dwell_polls + 1) erstmals erreicht — wer vorher
            # wieder weg ist ("kurz reingeschaut"), erreicht sie nie.
            threshold = self.ts_min_dwell_polls + 1
            new_streak: dict[str, int] = {}
            confirmed: list[str] = []
            for frs in current:
                n = self._ts_streak.get(frs, 0) + 1
                new_streak[frs] = n
                if n == threshold:
                    confirmed.append(frs)
            self._ts_streak = new_streak
            if not confirmed:
                return

            now = datetime.now(timezone.utc)
            for frs in confirmed:
                last = self._ts_last_notified.get(frs)
                if last and (now - last).total_seconds() < self.ts_rejoin_debounce_sec:
                    continue
                self._ts_last_notified[frs] = now

                conn = get_connection(self.db_path)
                try:
                    consent = get_ts_consent(conn, frs)
                    if consent and consent.get("visibility") == "nobody":
                        recipients = []  # Subjekt-Privacy: gar nicht über diese FRS melden
                    else:
                        cid = cid_for_callsign(conn, frs)
                        recipients = get_ts_push_subscriptions(conn, cid)
                finally:
                    conn.close()

                if not recipients:
                    continue

                nick = nick_by_frs.get(frs, frs)
                payload = {
                    "title": f"🎧 {nick} ist im TeamSpeak",
                    "body": "FriesenFlieger TeamSpeak",
                    "url": "/",
                }
                asyncio.create_task(
                    send_web_push(
                        self.vapid_private_key,
                        self.vapid_contact_email,
                        self.db_path,
                        recipients,
                        payload,
                        label=f"TSPush[{frs}]",
                    )
                )
        except Exception:
            logger.exception("Error in _poll_teamspeak")

    # ------------------------------------------------------------------
    # Calendar sync
    # ------------------------------------------------------------------

    async def _sync_calendar(self) -> None:
        """FriesenFlieger Google-Kalender laden und in DB speichern.

        Erkannte Bummel-Events (``is_bummel``) werden zusätzlich als persistente Rennen
        (``bummel_races``) angelegt/aktualisiert — Basis für Verdeckung/Enthüllung.
        """
        try:
            from app.calendar_sync import fetch_and_parse_ical
            from app.database import (
                upsert_calendar_events,
                upsert_calendar_bummel_race,
                upsert_calendar_transport_event,
            )
            assert self._http_client is not None
            events = await fetch_and_parse_ical(self._http_client)
            if events:
                conn = get_connection(self.db_path)
                try:
                    upsert_calendar_events(conn, events)
                    for ev in events:
                        if ev.get("is_bummel"):
                            upsert_calendar_bummel_race(conn, ev)
                        if ev.get("is_transport"):
                            upsert_calendar_transport_event(conn, ev)
                    conn.commit()
                finally:
                    conn.close()
                logger.info("Calendar sync: %d events gespeichert", len(events))
        except Exception:
            logger.exception("Error in _sync_calendar")

    # ------------------------------------------------------------------
    # Bummel-Enthüllung (Latch)
    # ------------------------------------------------------------------

    async def _check_bummel_reveals(self) -> None:
        """Periodisch: Renn-Start erkennen (erste Blockzeit → Start-Push) und Enthüllung latchen
        (dtend erreicht + niemand mehr unterwegs → Reveal-Push). Beides einmal je Rennen."""
        try:
            from datetime import datetime, timezone
            from app.database import (
                update_bummel_reveals, update_bummel_starts,
                get_bummel_race, get_push_subscriptions_for_events,
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(self.db_path)
            try:
                started = update_bummel_starts(conn, now, callsign_prefix=self.callsign_prefix)
                revealed = update_bummel_reveals(conn, now, callsign_prefix=self.callsign_prefix)
                # Push-Payloads sammeln, solange die Verbindung offen ist (push_enabled je Rennen)
                pushes: list[dict] = []
                for rid, callsign in started:
                    race = get_bummel_race(conn, rid)
                    if race and race.get("push_enabled"):
                        pushes.append({"title": race.get("name") or "FriesenFliegerBummel",
                                       "body": f"{callsign} hat den Bummel gestartet!", "url": "/"})
                for rid in revealed:
                    race = get_bummel_race(conn, rid)
                    if race and race.get("push_enabled"):
                        pushes.append({"title": race.get("name") or "FriesenFliegerBummel",
                                       "body": "Die Bummel-Ergebnisse sind da! 🏁", "url": "/"})
                subscriptions = get_push_subscriptions_for_events(conn) if pushes else []
            finally:
                conn.close()
            if started:
                logger.info("Bummel gestartet: %s", started)
            if revealed:
                logger.info("Bummel enthüllt: Rennen %s", revealed)
            if pushes and subscriptions and self.vapid_private_key:
                for payload in pushes:
                    asyncio.create_task(send_web_push(
                        self.vapid_private_key, self.vapid_contact_email, self.db_path,
                        subscriptions, payload, label="Bummel",
                    ))
        except Exception:
            logger.exception("Error in _check_bummel_reveals")

    async def _check_transport_events(self) -> None:
        """Periodisch: FriesenKutter-Events latchen — Start (erster Flug), Ziel (Manifest voll)
        und Feierabend (dtend erreicht). Jeweils einmal je Event ein Push an die Events-Abonnenten."""
        try:
            from datetime import datetime, timezone
            from app import llm
            from app.database import (
                list_transport_events, compute_transport_progress,
                set_transport_started, set_transport_goal_reached, set_transport_summarized,
                set_transport_summary_quip, transport_quips_enabled,
                event_summary_context, flight_quip_context,
                get_push_subscriptions_for_events, transport_event_started,
                transport_anyone_in_progress, detect_transport_losses,
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(self.db_path)
            pushes: list[dict] = []
            quip_jobs: list[tuple] = []
            try:
                do_quips = transport_quips_enabled(conn) and llm.is_configured()
                for ev in list_transport_events(conn):
                    dtstart = ev.get("dtstart") or ""
                    dtend = ev.get("dtend") or ""
                    if now < dtstart:
                        continue  # noch nicht gestartet
                    name = ev.get("name") or "FriesenKutter"
                    push_on = bool(ev.get("push_enabled"))
                    if ev.get("destination"):
                        detect_transport_losses(conn, ev, callsign_prefix=self.callsign_prefix)
                    progress = compute_transport_progress(
                        conn, ev, now, callsign_prefix=self.callsign_prefix
                    )
                    if not ev.get("started_at") and (
                        progress["flight_count"] > 0
                        or transport_event_started(conn, ev, self.callsign_prefix)
                    ):
                        if set_transport_started(conn, ev["id"], now) and push_on:
                            pushes.append({"title": name,
                                           "body": "Der FriesenKutter läuft — Fracht wird geladen! 📦",
                                           "url": "/"})
                    target = progress["target_kg"]
                    if target and not ev.get("goal_reached_at") and progress["total_kg"] >= target:
                        if set_transport_goal_reached(conn, ev["id"], now) and push_on:
                            pushes.append({"title": name,
                                           "body": "Fracht komplett — Ziel erreicht! 🎯", "url": "/"})
                    # Feierabend erst, wenn kein Nachzügler mehr unterwegs ist (Flug vor dtend
                    # gestartet, noch offen, ohne Ankunfts-Latch) — sonst entstünde die
                    # Zusammenfassung mit einem noch nicht finalen Ergebnis (Task #13).
                    if dtend and now >= dtend and not ev.get("summarized_at") \
                            and not transport_anyone_in_progress(
                                conn, ev, started_before=dtend,
                                callsign_prefix=self.callsign_prefix,
                            ):
                        if set_transport_summarized(conn, ev["id"], now):
                            tons = round(progress["total_kg"] / 1000, 2)
                            body = f"Feierabend: {progress['loaded_count']} Frachtflüge, {tons} t bewegt ✅"
                            if do_quips:
                                summary = await asyncio.to_thread(
                                    llm.event_summary, event_summary_context(ev, progress)
                                )
                                if summary:
                                    set_transport_summary_quip(conn, ev["id"], summary)
                                    body = summary
                            if push_on:
                                pushes.append({"title": name, "body": body, "url": "/"})
                    # Pro-Flug-Sprüche für neue beladene Flüge ohne Cache sammeln (später async erzeugen).
                    if do_quips:
                        for f in progress["flights"]:
                            if f.get("loaded") and not f.get("quip"):
                                quip_jobs.append((ev["id"], f["flight_key"], flight_quip_context(f, progress)))
                conn.commit()
                subscriptions = get_push_subscriptions_for_events(conn) if pushes else []
            finally:
                conn.close()
            if pushes and subscriptions and self.vapid_private_key:
                for payload in pushes:
                    asyncio.create_task(send_web_push(
                        self.vapid_private_key, self.vapid_contact_email, self.db_path,
                        subscriptions, payload, label="FriesenKutter",
                    ))
            # Max. 8 Sprüche je Lauf (Burst-Bremse); jeder in eigener Aufgabe (nicht blockierend).
            for eid, fkey, ctx in quip_jobs[:8]:
                asyncio.create_task(self._gen_flight_quip(eid, fkey, ctx))
        except Exception:
            logger.exception("Error in _check_transport_events")

    async def _gen_flight_quip(self, event_id: int, flight_key: str, context: dict) -> None:
        """Einen Flug-Spruch erzeugen (Sonnet 5, im Thread) und cachen. Silent-Fail."""
        try:
            from app import llm
            from app.database import set_transport_quip
            text = await asyncio.to_thread(llm.flight_quip, context)
            if not text:
                return
            conn = get_connection(self.db_path)
            try:
                set_transport_quip(conn, event_id, flight_key, text)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("Error in _gen_flight_quip")

    async def _auto_research_payload(self, type_code: str) -> None:
        """Zuladung eines neu gesehenen Flugzeugtyps automatisch recherchieren und
        vorbefüllen (source='llm'). Läuft im Hintergrund, Silent-Fail — der Admin kann
        die Werte jederzeit überschreiben; manuell gepflegte Typen werden nie angefasst."""
        try:
            from app import llm
            from app.database import get_payload_map, upsert_payload
            s = await asyncio.to_thread(llm.suggest_aircraft_payload, type_code)
            if not s:
                logger.info("Auto-Zuladung: keine Daten für %s gefunden", type_code)
                return
            conn = get_connection(self.db_path)
            try:
                if type_code in get_payload_map(conn):
                    return  # inzwischen (manuell) gepflegt → nicht überschreiben
                upsert_payload(
                    conn, type_code,
                    mtow_kg=s.get("mtow_kg"), empty_kg=s.get("empty_kg"),
                    fuel_kg=s.get("fuel_kg", s.get("fuel_full_kg")),
                    crew_kg=s.get("crew_kg"), source="llm",
                    make_model=s.get("make_model"),
                )
                conn.commit()
            finally:
                conn.close()
            logger.info("Auto-Zuladung vorbefüllt: %s (%s)", type_code, s.get("make_model"))
        except Exception:
            logger.exception("Error in _auto_research_payload (%s)", type_code)

    async def _check_event_reminders(self) -> None:
        """Periodisch (~5 min): FriesenEvents, die in ~1 h beginnen, einmalig per Push erinnern.
        Empfänger sind die Events-Abonnenten (notify_events). Latchend via event_reminders_sent."""
        try:
            from datetime import datetime, timezone
            from app.database import (
                events_due_for_reminder, mark_event_reminded,
                get_push_subscriptions_for_events,
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(self.db_path)
            try:
                due = events_due_for_reminder(conn, now, lead_min=60)
                subscriptions = get_push_subscriptions_for_events(conn) if due else []
                for ev in due:
                    mark_event_reminded(conn, ev["uid"], now)  # latchen, auch ohne Empfänger
                conn.commit()
            finally:
                conn.close()
            if due:
                logger.info("Event-Erinnerung fällig: %s", [e["uid"] for e in due])
            if due and subscriptions and self.vapid_private_key:
                for ev in due:
                    payload = {
                        "title": "FriesenEvent",
                        "body": f"🗓 In etwa 1 Std: {ev.get('summary') or 'FriesenEvent'}",
                        "url": "/",
                    }
                    asyncio.create_task(send_web_push(
                        self.vapid_private_key, self.vapid_contact_email, self.db_path,
                        subscriptions, payload, label="Event-Erinnerung",
                    ))
        except Exception:
            logger.exception("Error in _check_event_reminders")

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
        vatsim_rejoin_debounce_sec=settings.VATSIM_REJOIN_DEBOUNCE_SEC,
        ts_notify_enabled=settings.TS_NOTIFY_ENABLED,
        ts_host=settings.TS_HOST,
        ts_query_port=settings.TS_QUERY_PORT,
        ts_query_user=settings.TS_QUERY_USER,
        ts_query_pass=settings.TS_QUERY_PASS,
        ts_server_id=settings.TS_SERVER_ID,
        ts_notify_channel_id=settings.TS_NOTIFY_CHANNEL_ID,
        ts_exclude_channel_ids=parse_channel_ids(settings.TS_EXCLUDE_CHANNEL_IDS),
        ts_min_dwell_polls=settings.TS_MIN_DWELL_POLLS,
        ts_poll_interval=settings.TS_POLL_INTERVAL,
        ts_rejoin_debounce_sec=settings.TS_REJOIN_DEBOUNCE_SEC,
    )
