"""VatsimPoller — APScheduler-basierter Hintergrundprozess für FriesenSpy.

Ruft VATSIM-Daten ab, verwaltet eine Flug-State-Machine für Friesen-Piloten
und publiziert Live-Positions-Updates in eine asyncio.Queue für SSE-Clients.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from pywebpush import webpush, WebPushException
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.database import (
    cleanup_old_history,
    close_flight,
    delete_push_subscription,
    record_push_delivery,
    ensure_pilot,
    get_connection,
    get_inactive_cids,
    get_live_positions,
    get_push_subscriptions_for_pilot,
    get_push_subscriptions_for_prefile,
    get_uncached_statsim_ids,
    cid_for_callsign_authoritative,
    get_pilot_visibility,
    get_ts_push_subscriptions,
    visible_recipients,
    load_prefile_sigs,
    normalize_type_code,
    open_flight,
    _parse_iso,
    rebuild_flight_cache,
    remove_live_position,
    save_position_history,
    save_prefile_sigs,
    save_statsim_positions,
    update_flight_plan,
    upsert_live_position,
    upsert_statsim_flights,
)
from app.vatsim import (
    fetch_vatsim_data,
    filter_friesen_pilots,
    pilot_to_position,
    snapshot_other_traffic,
)
from app.alerts import format_online_message, send_telegram_alert
from app.statsim import fetch_flight_track, fetch_pilot_flights
from app.teamspeak import fetch_channel_clients, parse_channel_ids
from app import vrp

logger = logging.getLogger(__name__)


def _lead_phrase(dtstart: str, now: str) -> str:
    """Restzeit bis ``dtstart`` als gestufter Erinnerungs-Text (#2). Rein, testbar.

    Der Erinnerungs-Job feuert, sobald ``dtstart`` im 60-min-Fenster liegt — normal ~55-60 min
    vorher, bei einem knapp vor Beginn angelegten Event aber sofort. Statt eines harten
    „In etwa 1 Std" formuliert dieser Helfer die tatsächliche Restzeit gestuft:
    > 45 min → „In etwa 1 Std" · 10-45 min → „In etwa X min" (X auf 5 gerundet) · < 10 min →
    „In wenigen Minuten"."""
    mins = (_parse_iso(dtstart) - _parse_iso(now)).total_seconds() / 60
    if mins > 45:
        return "In etwa 1 Std"
    if mins >= 10:
        return f"In etwa {int(round(mins / 5) * 5)} min"
    return "In wenigen Minuten"


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
    ok_endpoints: list[str] = []
    fail_endpoints: dict[str, str] = {}

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
                ok_endpoints.append(sub["endpoint"])
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
            fail_endpoints[sub["endpoint"]] = str(sc)

    if to_delete or ok_endpoints or fail_endpoints:
        # In try/except, weil send_web_push als fire-and-forget create_task läuft: ein
        # DB-Fehler (z. B. DB kurz nicht erreichbar) darf keine "Task exception was
        # never retrieved"-Warnung erzeugen. Erfolg/Fehler-Diagnose ist unkritisch.
        try:
            conn = get_connection(db_path)
            try:
                for endpoint in to_delete:
                    delete_push_subscription(conn, endpoint)
                record_push_delivery(conn, ok_endpoints, fail_endpoints)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("%s: Endpoint-Cleanup/Diagnose fehlgeschlagen", label)


# ---------------------------------------------------------------------------
# Nutzlasten der Benachrichtigungen — EINE Formulierung je Kategorie
# ---------------------------------------------------------------------------
# Web-Push (Browser) und Sim-Benachrichtigung (MSFS-Kniebrett) sind zwei Anzeigeflächen
# für dieselbe Meldung. Ihre Texte werden deshalb hier gebaut und nicht an jeder
# Auslöse-Stelle neu formuliert — sonst laufen die beiden Kanäle über die Zeit auseinander.

def payload_online(pilot: dict) -> dict:
    """„FRS61 ist online" — Nutzlast für einen Piloten, der gerade online gegangen ist."""
    callsign = pilot.get("callsign", "?")
    dep = pilot.get("departure") or "?"
    arr = pilot.get("arrival") or "?"
    aircraft = pilot.get("aircraft_short") or pilot.get("aircraft") or ""
    return {
        "title": f"{callsign} ist online! ✈",
        "body": f"{dep} → {arr}" + (f" · {aircraft}" if aircraft else ""),
        "url": "/",
    }


def payload_prefile(prefile: dict) -> dict:
    """„FRS61 hat Flugplan eingereicht" — Nutzlast für einen neu eingereichten Flugplan."""
    import re as _re
    callsign = prefile.get("callsign", "?")
    fp = prefile.get("flight_plan") or {}
    dep = fp.get("departure") or "?"
    arr = fp.get("arrival") or "?"
    aircraft = fp.get("aircraft_short") or fp.get("aircraft") or ""
    deptime = fp.get("deptime") or ""
    remarks = fp.get("remarks") or ""

    dof_m = _re.search(r'DOF/(\d{2})(\d{2})(\d{2})', remarks)
    date_str = f"{dof_m.group(3)}.{dof_m.group(2)}.20{dof_m.group(1)}" if dof_m else ""
    time_str = f"{deptime[:2]}:{deptime[2:]} UTC" if len(deptime) == 4 else ""
    when = " · ".join(filter(None, [date_str, time_str]))

    return {
        "title": f"{callsign} hat Flugplan eingereicht 📋",
        "body": f"{dep} → {arr}" + (f" · {when}" if when else "") + (f" · {aircraft}" if aircraft else ""),
        "url": "/",
    }


def payload_ts(nick: str) -> dict:
    """„Micha ist im TeamSpeak" — Nutzlast für einen bestätigten TeamSpeak-Beitritt."""
    return {
        "title": f"🎧 {nick} ist im TeamSpeak",
        "body": "FriesenFlieger TeamSpeak",
        "url": "/",
    }


async def send_web_push_notifications(
    vapid_private_key: str,
    vapid_contact_email: str,
    db_path: str,
    pilot: dict,
) -> None:
    """Push-Notification an alle passenden Subscriptions senden."""
    cid = pilot.get("cid")
    callsign = pilot.get("callsign", "?")
    payload = payload_online(pilot)
    conn = get_connection(db_path)
    try:
        subscriptions = get_push_subscriptions_for_pilot(conn, cid)
        subscriptions = visible_recipients(conn, cid, subscriptions, "online")  # Subjekt-Sichtbarkeit
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

    cid = prefile.get("cid")
    callsign = prefile.get("callsign", "?")
    data = _json.dumps(payload_prefile(prefile))

    conn = get_connection(db_path)
    try:
        subscriptions = get_push_subscriptions_for_prefile(conn, cid)
        subscriptions = visible_recipients(conn, cid, subscriptions, "prefile")  # Subjekt-Sichtbarkeit
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


# Die Daten ändern sich in Monaten, nicht in Minuten (ein Meldepunkt ist eine
# AIP-Veröffentlichung). 30 Tage sind der Kompromiss zwischen „aktuell genug" und „die API
# sieht uns praktisch nie".
VRP_MAX_ALTER_TAGE = 30


def _vrp_faellig(stand: str) -> bool:
    """Ist der abgelegte Bestand älter als VRP_MAX_ALTER_TAGE?

    Ein unlesbares oder fehlendes Datum gilt als fällig — lieber einmal zu viel geholt als ein
    Bestand, der stillschweigend vergreist.
    """
    try:
        gesetzt = datetime.fromisoformat(stand)
    except (TypeError, ValueError):
        return True
    if gesetzt.tzinfo is None:
        gesetzt = gesetzt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - gesetzt).days >= VRP_MAX_ALTER_TAGE


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
        openaip_api_key: str = "",
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
        self.openaip_api_key = openaip_api_key
        self._scheduler: AsyncIOScheduler | None = None
        self._http_client: httpx.AsyncClient | None = None
        # State: cid → {"id": flight_id, "dep": departure, "arr": arrival}
        self._active_flights: dict[int, dict] = {}
        # Momentaufnahme des GESAMTEN Feeds für die Verkehrsanzeige (/api/traffic).
        # Nur im Speicher: Fremdverkehr wird nicht historisiert -- er ist reine Anzeige, und
        # eine Historie über ~1000 Flugzeuge im 15-Sekunden-Takt wäre in Tagen größer als
        # alles andere in dieser Datenbank zusammen.
        # Öffentlich benannt (kein Unterstrich) wie last_prefiles und ts_clients -- alles,
        # was die API aus dem Poller liest, ist in diesem Projekt öffentlich.
        self.traffic_snapshot: list[dict] = []
        self.traffic_snapshot_ts: float = 0.0
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
        self._PAYLOAD_RESEARCH_LIMIT = 5   # Muster je Nachlese-Lauf (~4 ct und ~30 s je Stück)
        # NUR die Laufzeit einer einzelnen Recherche, kein Ergebnisgedächtnis: der DB-Zustand
        # (payload_research) entsteht erst NACH dem Ergebnis, die Recherche dauert aber 30 s bis
        # 300 s. In dieser Lücke sähe jeder weitere Poll (alle 15 s) das Muster als „nie
        # versucht" und startete eine zweite, ebenfalls bezahlte Recherche für denselben Code
        # (gemessen: 4 Polls → 4 parallele Läufe). Bewusst NICHT der alte
        # _payload_research_attempted-Bug: hier fliegt der Code im finally immer wieder heraus,
        # ein Fehlschlag überlebt weder den Aufruf noch einen Neustart.
        self._payload_research_inflight: set[str] = set()
        self._AIRCRAFT_INFO_LIMIT = 8      # Muster je Nachlese-Lauf
        self._photo_dir = Path(self.db_path).parent / "aircraft-photos"
        # Zweites, unabhängiges In-Flight-Set — gleiche Gefahrenklasse wie oben, andere
        # Gegenstelle (Wikipedia/Commons statt der LLM-API). aircraft_types.fetch_state entsteht
        # erst NACH der HTTP-Auflösung, und zwei Auslöser greifen unabhängig voneinander auf
        # dasselbe Muster zu:
        #   1. Der Live-Auslöser hängt an den `new_codes` des Poll-Durchlaufs. Deren Kriterium
        #      ist der Zustand in `payload_research` (Plan A), NICHT in `aircraft_types` —
        #      solange dort noch kein Endzustand steht, bleibt der Code über viele Polls
        #      (alle 15 s) in `new_codes` und stiesse jedes Mal eine neue Auflösung an.
        #   2. Der 10-Minuten-Job wählt nach `aircraft_types.fetch_state`; ein Code, dessen
        #      Live-Auflösung gerade läuft, steht dort noch auf 'neu' und gilt weiter als fällig.
        # Wie oben: nur die Laufzeit, kein Ergebnisgedächtnis — im finally fliegt der Code
        # immer wieder heraus.
        self._aircraft_info_inflight: set[str] = set()

    @staticmethod
    def _now() -> datetime:
        """Aktuelle Zeit — als Methode, damit Tests sie kontrollieren können."""
        return datetime.now(timezone.utc)

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
        self._register_jobs()
        self._scheduler.start()

    def _register_jobs(self) -> None:
        """Alle Scheduler-Jobs registrieren (getrennt von start(), damit testbar)."""
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
        # EIN Job fuer beide Kartentypen -- die Automatik ist zurueckgebaut (31.08.2026),
        # der Job vergleicht nur noch Hashes und meldet Aenderungen. Zwei Jobs, die dieselbe
        # Quelle abfragen, waren eine Folge der zwei getrennten Tabellen (aip_charts /
        # aip_ground_charts); die gibt es seit dem Rueckbau nicht mehr.
        #
        # `next_run_time` ist nicht schmueckend: Ohne die Angabe plant APScheduler den
        # ERSTEN Lauf eine Woche nach dem Anmelden, und angemeldet wird bei jedem
        # Containerstart neu. Zwischen zwei Deploys liegt hier selten eine Woche -- der
        # Vorgaengerjob hat von seiner Einfuehrung bis zum 31.08.2026 kein einziges Mal
        # gearbeitet. Belegt am Bestand: Von 446 Karten trug keine ein geprueft_am nach
        # dem 25.08.
        #
        # Ob dann WIRKLICH gearbeitet wird, entscheidet der Merker in job_laeufe -- nicht
        # dieser Zeitpunkt. Sonst waere aus dem Wochenjob ein Deploy-Job geworden.
        # Zehn Minuten Verzug, damit der Start nicht mit dem flight_cache-Warmlauf
        # zusammenfaellt.
        self._scheduler.add_job(
            self._aip_hash_pruefen, "interval", weeks=1, id="aip_hash_pruefen",
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        # Muster-Infos: einmalig kurz nach Start, danach regelmäßig die fälligen.
        self._scheduler.add_job(
            self._resolve_due_aircraft_types, "date", id="aircraft_info_initial",
        )
        self._scheduler.add_job(
            self._resolve_due_aircraft_types, "interval", minutes=10,
            id="aircraft_info_retry",
        )
        # Event-Erinnerung (~1 h vor Beginn) regelmäßig prüfen
        self._scheduler.add_job(
            self._check_event_reminders,
            "interval",
            minutes=5,
            id="event_reminder_check",
        )
        # flight_cache (#23 Phase 2): einmaliger Warm-up kurz nach Start (voller Rebuild,
        # ~5,5 s — via to_thread, damit der erste /api/stats nach Deploy nicht synchron
        # blockiert), danach periodischer inkrementeller Refresh (~0,5 s).
        self._scheduler.add_job(
            self._warmup_flight_cache,
            "date",
            id="flight_cache_warmup",
        )
        self._scheduler.add_job(
            self._refresh_flight_cache,
            "interval",
            minutes=5,
            id="flight_cache_refresh",
        )
        # StatSim (#23 Phase 2b): proaktives Nachladen der GPS-Tracks neuer StatSim-Flüge
        # (kleine Batches, gedrosselt) — kein Voll-Backfill, der bleibt Admin-Aktion.
        self._scheduler.add_job(
            self._fetch_statsim_tracks,
            "interval",
            minutes=10,
            id="statsim_track_fetch",
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
        # Zuladungs-Nachlese (Teil 8): einmalig kurz nach Start den Altbestand angehen …
        self._scheduler.add_job(
            self._research_due_payloads,
            "date",
            id="payload_research_initial",
        )
        # … und danach regelmäßig die fälligen Wiederholungen. OHNE diesen Job ist der
        # Backoff aus is_retry_due() reine Dekoration: der Live-Auslöser reagiert nur auf NEU
        # gesehene Muster, ein 'fehler' bliebe bis zum nächsten Container-Neubau liegen.
        self._scheduler.add_job(
            self._research_due_payloads,
            "interval",
            minutes=5,
            id="payload_research_retry",
        )
        # Meldepunkte (VRP): einmal kurz nach Start prüfen, danach täglich. Geholt wird nur,
        # wenn der abgelegte Bestand fehlt oder älter als VRP_MAX_ALTER_TAGE ist — der
        # tägliche Lauf ist also fast immer ein Blick auf ein Datum, kein Abruf.
        # Nicht im Lifespan: Der Weltbestand geht über mehrere Seiten und hat beim ersten Lauf
        # am 17.08.2026 rund 23 Sekunden gedauert; das gehört nicht zwischen Start und erste
        # Antwort.
        self._scheduler.add_job(
            self._refresh_vrp,
            "date",
            id="vrp_initial",
        )
        self._scheduler.add_job(
            self._refresh_vrp,
            "interval",
            hours=24,
            id="vrp_refresh",
        )

    async def _refresh_vrp(self) -> None:
        """Meldepunkte holen, ablegen und in den Speicher schwenken — wenn fällig.

        Silent fail wie bei den Telegram-Alerts: Kommt OpenAIP nicht, bleibt der bisherige
        Bestand stehen (beim allerersten Mal: keine Ebene). Nichts daran ist es wert, den
        Scheduler oder gar den Start zu gefährden.
        """
        if not self.openaip_api_key:
            return
        alt = vrp.bestand()
        if alt.punkte and not _vrp_faellig(alt.stand):
            return
        try:
            punkte = await vrp.abrufen(self.openaip_api_key)
        except Exception as exc:
            logger.warning("Meldepunkte: Abruf fehlgeschlagen (%r) — Ebene bleibt, wie sie war", exc)
            return
        if not punkte:
            logger.warning("Meldepunkte: Abruf lieferte nichts — Bestand unverändert")
            return
        stand = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            vrp.speichern(vrp.pfad_fuer(self.db_path), punkte, stand)
        except OSError as exc:
            # Schreiben ist der Bonus, nicht der Zweck: Der Bestand steht auch ohne Datei —
            # er müsste nach einem Neustart nur erneut geholt werden.
            logger.warning("Meldepunkte: Ablage nicht schreibbar (%r)", exc)
        vrp.bestand_setzen(vrp.VrpBestand(punkte=punkte, stand=stand))
        logger.info("Meldepunkte geladen: %d Punkte (Stand %s)", len(punkte), stand)

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

    def broadcast_notify(self, service: str, subject_cid: int | None, payload: dict,
                         nur_cid: int | None = None) -> None:
        """Eine Benachrichtigung in den SSE-Strom legen (Anzeigefläche: MSFS-Kniebrett).

        ``service`` ∈ {'online','prefile','ts','events'} — dieselben Namen wie in
        ``VISIBILITY_SERVICES``, damit die Subjekt-Sichtbarkeit ohne Übersetzung greift.
        ``subject_cid`` ist die CID des Piloten, ÜBER den benachrichtigt wird (None bei
        Event-Meldungen, die keine Person betreffen).

        Hier wird bewusst NICHT gefiltert: der Broadcast kennt seine Empfänger nicht. Wer die
        Meldung sehen darf, entscheidet der SSE-Endpoint pro Verbindung
        (``app/main.py`` → ``is_visible_to``) — vorher verlässt sie den Server nicht.

        ``nur_cid`` schränkt die Zustellung auf eine einzige CID ein (Test-Meldung aus dem
        Admin: die soll niemanden sonst im Cockpit erreichen). Das Feld wird vom Endpoint vor
        dem Senden entfernt.
        """
        nachricht = {
            "type": "notify",
            "service": service,
            "subject_cid": subject_cid,
            "title": payload.get("title", ""),
            "body": payload.get("body", ""),
            "url": payload.get("url", "/"),
        }
        if nur_cid is not None:
            nachricht["nur_cid"] = int(nur_cid)
        self.broadcast_sse(nachricht)
        # Ohne diese Zeile ist von aussen nicht zu sehen, ob eine Meldung ueberhaupt entstand
        # und ob jemand zugehoert hat -- genau die Frage beim ersten Sim-Test (14.08.2026).
        logger.info("Notify[%s] subject=%s -> %d SSE-Abonnent(en)",
                    service, subject_cid, len(self._sse_subscribers))

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

            # Vor jeder weiteren Verarbeitung: Der Feed ist hier vollständig in der Hand,
            # später nicht mehr. Kostet einen Durchlauf über ~1000 Einträge alle 15 s.
            self.traffic_snapshot = snapshot_other_traffic(self.callsign_prefix, vatsim_data)
            self.traffic_snapshot_ts = time.time()

            excl_conn = get_connection(self.db_path)
            try:
                excluded_cids = get_inactive_cids(excl_conn)
            finally:
                excl_conn.close()
            online_pilots = filter_friesen_pilots(
                self.callsign_prefix, vatsim_data, excluded_cids=excluded_cids
            )

            # Prefiles mit FRS*-Callsign aus dem Feed speichern (dieselbe Ausnahmeliste wie oben --
            # eine per Admin-Checkbox ausgeschlossene CID soll auch nicht als Prefile auftauchen).
            prefix = self.callsign_prefix.upper()
            current_prefiles = [
                p for p in (vatsim_data.get("prefiles") or [])
                if isinstance(p, dict) and p.get("callsign", "").upper().startswith(prefix)
                and p.get("cid") not in excluded_cids
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
                # Typ-Fallback ohne Live-Flugplan (vatsim-radar-Prinzip): der öffentliche Feed
                # führt den Flugzeugtyp NUR im flight_plan. Ohne Live-Plan nehmen wir das
                # Prefile des Piloten (falls vorhanden) — damit funktionieren Anzeige und
                # Kutter-Zuladung auch ohne Live-Plan. #52: KEIN Fallback mehr auf frühere
                # eigene Flüge (last_known_aircraft war zeitlich blind — lieferte teils den
                # GLOBAL neuesten gefileten Typ, auch aus der Zukunft des aktuellen Legs; der
                # VATSIM-Feed führt ohne Flugplan grundsätzlich KEINE Typ-Info). Ohne
                # Plan/Prefile bleibt der Typ ehrlich leer statt geraten.
                for cid, pos in current.items():
                    if not pos.get("aircraft_short"):
                        fp = (current_map.get(cid) or {}).get("flight_plan") or {}
                        short = fp.get("aircraft_short") or (fp.get("aircraft") or "").split("/")[0]
                        icao = fp.get("aircraft_icao") or short
                        if short:
                            pos["aircraft"] = pos["aircraft_short"] = short
                            pos["aircraft_icao"] = icao or short
                    # #51: aircraft_short/aircraft_icao IMMER normalisieren — Composite-Strings
                    # ("AS65/L-SDGY/S") kommen manchmal schon roh im aircraft_short-Feld des
                    # VATSIM-Feeds selbst an (nicht nur im zusammengesetzten aircraft-Feld).
                    # Zentral hier, damit alle nachgelagerten Schreiber (open_flight,
                    # update_flight_plan, Refile-Split) automatisch einen sauberen Typ bekommen.
                    if pos.get("aircraft_short"):
                        pos["aircraft_short"] = pos["aircraft"] = normalize_type_code(pos["aircraft_short"])
                    if pos.get("aircraft_icao"):
                        pos["aircraft_icao"] = normalize_type_code(pos["aircraft_icao"])

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
                        # logon_time des AKTUELLEN Legs — der Live-Ankunfts-Latch muss denselben
                        # Schlüssel treffen, den die flights-Zeile dieses Legs trägt (nicht den
                        # sitzungsweiten Feed-Wert, der bei einem Leg-Split veraltet).
                        "logon_time": pos["logon_time"],
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

                        # Subjekt-Sichtbarkeit: nur bei 'everyone' (oder kein Eintrag) den
                        # öffentlichen Telegram-Kanal bespielen — 'nobody'/'allowlist' → kein
                        # Kanal-Alert (Broadcast kann keine Allowlist bedienen; F6).
                        _vis = get_pilot_visibility(conn, cid)
                        _tg_allowed = (not _vis) or _vis["mode"] == "everyone" \
                            or ("online" not in _vis["services"])

                        # Telegram alert (only when token + chat_id configured)
                        if self.telegram_token and self.telegram_chat_id and _tg_allowed:
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

                        # Sim-Benachrichtigung fürs Kniebrett — bewusst außerhalb der
                        # VAPID-Bedingung: sie hängt nicht am Web-Push. Aber INNERHALB des
                        # Rejoin-Debounce, sonst meldet jeder vPilot-Reconnect ins Cockpit.
                        self.broadcast_notify("online", cid, payload_online(pos))

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
                                aircraft_short=pos.get("aircraft_short", ""),
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
                            self._active_flights[cid] = {
                                "id": new_id, "dep": new_dep, "arr": new_arr,
                                "logon_time": now_logon,  # neues Leg → neuer Latch-Schlüssel
                            }
                            logger.info(
                                "Neues Leg CID %s: %s→%s → %s→%s",
                                cid, old_dep, old_arr, new_dep, new_arr,
                            )

                # 2c. (entfallen mit dem Latch-Rückbau) Die Live-Ankunft am Ziel erkennt der
                # GPS-Leg-Detektor jetzt selbst, sofort beim Touchdown — kein separater
                # check_live_arrival-Latch mehr nötig (Stapel-Modell, Entscheidung 10).

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
                # Der Versuchszustand steht in payload_research, NICHT in einem Set im
                # Prozessgedächtnis — sonst überlebt ein Fehlschlag den Neustart als "erledigt"
                # (AP32-Fall 2026-07-30).
                from app.database import get_payload_map, get_payload_research, is_retry_due
                known_types = set(get_payload_map(conn).keys())
                jetzt = self._now()
                new_codes = []
                for pos in current.values():
                    code = normalize_type_code(pos.get("aircraft_icao") or pos.get("aircraft_short"))
                    if not code or code in known_types or code in new_codes:
                        continue
                    st = get_payload_research(conn, code)
                    if st is None or is_retry_due(st["state"], st["attempts"],
                                                  st["checked_at"], jetzt):
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
                # Muster-Infos für dieselben neu gesehenen Codes — bewusst NICHT hinter dem
                # LLM-Key-Gate: Wikipedia/Commons brauchen keinen Key. Dass derselbe Code hier
                # über viele Polls hintereinander auftaucht (das Kriterium für new_codes ist der
                # Zustand in payload_research, nicht in aircraft_types), fängt der
                # In-Flight-Guard in _resolve_aircraft_type ab.
                # Wichtig zur Gleichzeitigkeit: `new_codes` enthält per Konstruktion nur Codes
                # OHNE aircraft_payloads-Zeile — der Name, den die Auflösung braucht, entsteht
                # also erst durch die eben gestartete Recherche der Zeile darüber. Dass die
                # Auflösung deshalb praktisch immer „noch kein Name" vorfindet, ist eingeplant:
                # sie kehrt dann OHNE Zustandsschreibung zurück (Rev. 3, C2) und der Code kommt
                # über den 10-Minuten-Job wieder, sobald der Name da ist.
                for code in new_codes:
                    asyncio.create_task(self._resolve_aircraft_type(code))

            # 4. Prefile-Benachrichtigungen für neu eingereichte/geänderte Flugpläne
            # Nur wenn Pilot NICHT bereits online ist (Prefile = Ankündigung, kein Duplikat)
            for pf in new_prefiles:
                cid = pf.get("cid")
                if not cid or cid in self._active_flights:
                    continue
                # Sim-Benachrichtigung unabhängig von VAPID (s. broadcast_notify)
                self.broadcast_notify("prefile", cid, payload_prefile(pf))
                if self.vapid_private_key:
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
                    subject_cid = cid_for_callsign_authoritative(conn, frs)
                    recipients = get_ts_push_subscriptions(conn, subject_cid)
                    recipients = visible_recipients(conn, subject_cid, recipients, "ts")
                finally:
                    conn.close()

                nick = nick_by_frs.get(frs, frs)
                payload = payload_ts(nick)

                # Sim-Benachrichtigung fürs Kniebrett — VOR der Empfänger-Prüfung: `recipients`
                # sind die Web-Push-Abos, und ohne die soll das Cockpit trotzdem etwas sehen.
                self.broadcast_notify("ts", subject_cid, payload)

                if not recipients:
                    continue

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
                delete_stale_calendar_events,
            )
            assert self._http_client is not None
            events = await fetch_and_parse_ical(self._http_client)
            if events:
                conn = get_connection(self.db_path)
                try:
                    upsert_calendar_events(conn, events)
                    deleted = delete_stale_calendar_events(conn, [ev["uid"] for ev in events])
                    for ev in events:
                        if ev.get("is_bummel"):
                            upsert_calendar_bummel_race(conn, ev)
                        if ev.get("is_transport"):
                            upsert_calendar_transport_event(conn, ev)
                    conn.commit()
                finally:
                    conn.close()
                logger.info(
                    "Calendar sync: %d events gespeichert, %d veraltete entfernt",
                    len(events), deleted,
                )
        except Exception:
            logger.exception("Error in _sync_calendar")

    # ------------------------------------------------------------------
    # flight_cache Warm-up + Refresh (#23 Phase 2)
    # ------------------------------------------------------------------

    @staticmethod
    def _rebuild_flight_cache_sync(db_path: str, *, full: bool) -> int:
        """Verbindung öffnen, Rebuild ausführen, Verbindung schließen — alles im selben
        Thread (sqlite3-Connections sind an ihren Erzeuger-Thread gebunden; ``conn`` darf
        NICHT auf dem Event-Loop-Thread erzeugt und dann in ``to_thread`` benutzt werden)."""
        conn = get_connection(db_path)
        try:
            return rebuild_flight_cache(conn, full=full)
        finally:
            conn.close()

    async def _warmup_flight_cache(self) -> None:
        """Einmaliger voller Rebuild von ``flight_cache`` kurz nach App-Start (~5,5 s).

        Läuft via ``asyncio.to_thread``, damit der synchrone Rebuild NICHT den Event-Loop
        blockiert (sonst würde er den Poll und alle anderen Jobs für die Dauer anhalten).
        Silent fail — ein fehlgeschlagener Warm-up darf den App-Start nicht gefährden;
        ``get_cached_flights`` würde sonst beim ersten Request lazy nachziehen.
        """
        try:
            n = await asyncio.to_thread(self._rebuild_flight_cache_sync, self.db_path, full=True)
            logger.info("flight_cache Warm-up: %d Flüge materialisiert", n)
        except Exception:
            logger.exception("Error in _warmup_flight_cache")

    async def _aip_hash_pruefen(self) -> None:
        """AIP-Kartenblaetter: nur noch Hashes vergleichen, nichts rechnen.

        Ueber ``asyncio.to_thread`` wie der Vorgaenger -- 556 Abrufe mit Hoeflichkeitspause
        blockierten sonst den Event-Loop fuer Minuten (SSE, 15-Sekunden-Poll, jede andere
        Anfrage stuenden derweil still).

        Silent fail: Ein misslungener Durchgang darf den Dienst nicht gefaehrden. Es geht
        nichts verloren -- beim naechsten Lauf steht dasselbe neue Blatt noch da.
        """
        from app.database import get_connection, job_erledigt, job_faellig

        # Der Merker macht "woechentlich" wirklich woechentlich. Ohne ihn liefe der Job
        # zehn Minuten nach JEDEM Containerstart -- bei zwoelf Deploys an einem Tag waeren
        # das zwoelf Vollcrawls von aip.dfs.de mit 556 Seitenabrufen je Durchgang.
        conn = get_connection(self.db_path)
        try:
            if not job_faellig(conn, "aip_hash_pruefen", 7 * 24 * 3600):
                logger.debug("AIP-Karten: noch nicht faellig, uebersprungen")
                return
        finally:
            conn.close()
        try:
            from scripts.aip_bestand import melden
            ergebnis = await asyncio.to_thread(melden)
            conn = get_connection(self.db_path)
            try:
                job_erledigt(conn, "aip_hash_pruefen")
                conn.commit()
            finally:
                conn.close()
            logger.info("AIP-Karten geprueft: %d, zur Pruefung vorgelegt: %d (%s)",
                        ergebnis["gesamt"], len(ergebnis["geaendert"]),
                        ergebnis["zaehler"])
            if ergebnis["geaendert"]:
                # Ohne diese Meldung bleibt jedes offene Kniebrett auf dem alten Stand: Die
                # EFB-App wird beim Zuklappen nur schlafen gelegt und laedt innerhalb einer
                # Sim-Sitzung nie neu. Betrifft hier zwar nur die Admin-Ansicht, nicht das
                # Panel -- dasselbe SSE-Ereignis bedient beide.
                self.broadcast_sse({"type": "aip_charts"})
        except Exception:
            logger.exception("Error in _aip_hash_pruefen")

    async def _refresh_flight_cache(self) -> None:
        """Periodischer inkrementeller Refresh von ``flight_cache`` (~0,5 s, letzte Tage).

        Ebenfalls via ``asyncio.to_thread`` — auch der inkrementelle Rebuild ist synchroner
        DB-Zugriff und soll den Event-Loop nicht blockieren.
        """
        try:
            n = await asyncio.to_thread(self._rebuild_flight_cache_sync, self.db_path, full=False)
            logger.debug("flight_cache Refresh: %d Flüge materialisiert", n)
        except Exception:
            logger.exception("Error in _refresh_flight_cache")

    # ------------------------------------------------------------------
    # StatSim: proaktives Track-Nachladen (#23 Phase 2b)
    # ------------------------------------------------------------------

    async def _fetch_statsim_tracks(self) -> None:
        """Holt GPS-Tracks für ungecachte StatSim-Flüge nach — je zur Hälfte jüngste UND
        älteste zuerst.

        Kleine Batches (20/Lauf), gedrosselt (~0,3 s je Abruf) — kein Voll-Backfill (der
        bleibt eine Admin-Aktion, ``/api/admin/statsim-backfill``). Eine fehlschlagende
        Flug-ID darf den Rest des Batches nicht verhindern. Silent skip ohne API-Key.

        ``callsign_prefix=""`` (nicht ``self.callsign_prefix``): GPS-Track-Verarbeitung soll
        für JEDEN Flug eines bekannten Piloten gleich ablaufen, unabhängig vom Callsign — der
        Präfix entscheidet nur über die Wertung (Statistik/Bummel/Kutter), nicht darüber, ob
        ein Track nachgeladen wird. Sonst bleiben Fremd-Callsign-Flüge bekannter Piloten
        (z. B. bei einer anderen virtuellen Airline) dauerhaft ohne GPS-Split.

        **Halb-und-halb-Split (v8.6.1, #61-Fund):** reine „jüngste zuerst"-Sortierung lässt
        alten Backlog verhungern — solange laufend neue ungecachte Flüge importiert werden
        (31-Tage-Refresh, neue Piloten), ist praktisch immer ein jüngerer Flug an der Reihe,
        ein Flug von vor Monaten kommt so NIE dran (Fund: Flüge aus 01/2025 nach >1 Monat
        immer noch ohne Track). Je die Hälfte des Batches jüngste/älteste zuerst garantiert,
        dass der Backlog stetig schrumpft, ohne die Aktualität frischer Flüge zu opfern.
        """
        settings = get_settings()
        if not settings.STATSIM_API_KEY:
            return
        try:
            conn = get_connection(self.db_path)
            try:
                half = 10
                recent_ids = get_uncached_statsim_ids(conn, callsign_prefix="", limit=half)
                old_ids = get_uncached_statsim_ids(
                    conn, callsign_prefix="", limit=half, oldest_first=True
                )
                seen: set[int] = set()
                ids: list[int] = []
                for sid in recent_ids + old_ids:
                    if sid not in seen:
                        seen.add(sid)
                        ids.append(sid)
                if not ids:
                    return
                assert self._http_client is not None
                fetched = 0
                for sid in ids:
                    try:
                        positions = await fetch_flight_track(
                            self._http_client, sid, settings.STATSIM_API_KEY
                        )
                        if positions:
                            save_statsim_positions(conn, sid, positions)
                            # SOFORT committen, nicht erst nach der Schleife. Der erste Schreib-
                            # zugriff oeffnet eine Transaktion und haelt damit die SQLite-Schreib-
                            # sperre; ohne diesen commit steht sie ueber den GESAMTEN Batch --
                            # 20 HTTP-Abrufe plus je 0,3 s Drosselung. Am 04.09.2026 waren das
                            # 2 min 43 s, in denen JEDER andere Schreiber nach 5 s (Pythons
                            # Default-Timeout) "database is locked" bekam: _poll_once, die
                            # Prefile-Signaturen und PUT /api/prefs (500 fuer echte Nutzer).
                            # Vorher fiel es nie auf, weil "0/20 neu gecacht" gar nicht schreibt.
                            conn.commit()
                            fetched += 1
                    except Exception:
                        logger.warning(
                            "StatSim Track-Nachladen fehlgeschlagen für Flug %s", sid
                        )
                    await asyncio.sleep(0.3)
                conn.commit()
                logger.info(
                    "StatSim Track-Nachladen: %d/%d Flüge neu gecacht", fetched, len(ids)
                )
            finally:
                conn.close()
        except Exception:
            logger.exception("Error in _fetch_statsim_tracks")

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
            for payload in pushes:
                self.broadcast_notify("events", None, payload)
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
        und Feierabend (dtend erreicht). Jeweils einmal je Event ein Push an die Events-Abonnenten.

        Abgeschlossene Events (``summarized_at`` gesetzt) werden NICHT mehr neu gerechnet — ihre
        Wertung ist final und liegt als Snapshot vor (``progress_snapshot``, #66). Der Poller
        springt für sie direkt zur Quip-Nachsammlung (Fable-Fund 1: die KI-Sprüche entstehen erst
        NACH dem Latch, das Gate darf sie nicht abwürgen); der Endpoint-Read überlagert sie
        ohnehin frisch (``app/main.py``), der Snapshot selbst muss dafür nicht neu geschrieben
        werden."""
        try:
            from datetime import datetime, timezone
            from app import llm
            from app.database import (
                list_transport_events, compute_transport_progress,
                set_transport_started, set_transport_goal_reached, set_transport_summarized,
                set_transport_summary_quip, transport_quips_enabled,
                event_summary_context, flight_quip_context, get_transport_quips,
                get_push_subscriptions_for_events, transport_event_started,
                transport_anyone_in_progress,
                get_progress_snapshot, write_progress_snapshot,
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(self.db_path)
            pushes: list[dict] = []
            quip_jobs: list[tuple] = []

            def collect_quip_jobs(ev: dict, progress: dict) -> None:
                """Fehlende Pro-Flug-Quip-Jobs aus ``progress['flights']`` sammeln und an
                ``quip_jobs`` anhängen. Prüft gegen den AKTUELLEN Quip-Store
                (``get_transport_quips``), NICHT gegen ein evtl. vorhandenes ``quip``-Feld in
                ``progress`` selbst — bei einem eingefrorenen Snapshot wird dieses Feld nie
                nachträglich aktualisiert, ein reiner Feld-Check würde also bei jedem Poll
                dieselben (inzwischen evtl. längst erzeugten) Sprüche erneut anfordern. Von
                BEIDEN Zweigen (aktiv + bereits abgeschlossen/summarized) genutzt, damit die
                Logik nicht dupliziert/divergiert (#66 Task 6)."""
                existing = get_transport_quips(conn, ev["id"])
                for f in progress.get("flights", []):
                    if (f.get("loaded") or f.get("loss_kind") in ("stolen", "sunk")) \
                            and not existing.get(f.get("flight_key")):
                        quip_jobs.append((ev["id"], f["flight_key"], flight_quip_context(f, progress)))

            try:
                do_quips = transport_quips_enabled(conn) and llm.is_configured()
                for ev in list_transport_events(conn):
                    dtstart = ev.get("dtstart") or ""
                    dtend = ev.get("dtend") or ""
                    if now < dtstart:
                        continue  # noch nicht gestartet
                    name = ev.get("name") or "FriesenKutter"
                    push_on = bool(ev.get("push_enabled"))
                    if ev.get("summarized_at"):
                        # Abgeschlossen: Wertung ist final (Snapshot) — kein detect_losses, kein
                        # teures compute mehr (der Endpoint bedient aus dem Snapshot). Nur noch
                        # offene Pro-Flug-Quips nachsammeln, gespeist aus dem billigen
                        # Snapshot-Read (KEIN erneutes compute_transport_progress).
                        if do_quips:
                            snap = get_progress_snapshot(conn, "kutter", ev["id"])
                            if snap is not None:
                                collect_quip_jobs(ev, snap)
                                # Abschlussspruch nachziehen, falls er fehlt (#69): der Latch-Block
                                # unten erzeugt summary_quip nur EINMAL beim Feierabend-Übergang;
                                # nach „Sprüche neu" (clear_transport_quips setzt ihn auf NULL) ist
                                # dieser Zweig hier per early continue der EINZIGE Weg zurück. Nur
                                # bei echter Aktivität (flight_count>0) — kein bezahlter LLM-Call
                                # für ein leeres Event. Kontext aus dem Snapshot, kein Recompute.
                                if not ev.get("summary_quip") and snap.get("flight_count", 0) > 0:
                                    summary = await asyncio.to_thread(
                                        llm.event_summary, event_summary_context(ev, snap)
                                    )
                                    if summary:
                                        set_transport_summary_quip(conn, ev["id"], summary)
                        continue
                    # --- nicht abgeschlossen: bisheriger Ablauf unverändert ---
                    # (detect_transport_losses entfällt: Verluste stehen jetzt in den movements
                    # und fließen über losses[]/lost_total_kg direkt aus compute_transport_progress.)
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
                    delivered = progress["total_kg"]
                    lost = progress.get("lost_total_kg") or 0.0
                    # Aufgelöst = jedes kg ist geliefert ODER unwiederbringlich verloren
                    # (geklaut/versenkt). Dann liegt nichts mehr auf einem Ladeplatz und nichts ist
                    # mehr unterwegs — das Ziel ist erreicht, soweit es je erreichbar war. Der reine
                    # `geliefert >= Ziel`-Latch verpasste „der Rest ging unterwegs verloren"
                    # (#237-Live-Fund 20.07.: 3350 geliefert + 310 verloren = 3660 Ziel → der Kutter
                    # war fertig, feuerte aber nie „komplett", weil geliefert < Ziel blieb).
                    if target and not ev.get("goal_reached_at") and delivered + lost >= target:
                        if set_transport_goal_reached(conn, ev["id"], now) and push_on:
                            if delivered >= target:
                                body = "Fracht komplett — Ziel erreicht! 🎯"
                            else:
                                body = (f"Kutter abgeschlossen — {round(delivered)} kg angekommen, "
                                        f"{round(lost)} kg unterwegs verloren 💀")
                            pushes.append({"title": name, "body": body, "url": "/"})
                    # Feierabend erst, wenn kein Nachzügler mehr unterwegs ist (Flug vor dtend
                    # gestartet, noch offen, ohne Ankunfts-Latch) — sonst entstünde die
                    # Zusammenfassung mit einem noch nicht finalen Ergebnis (Task #13).
                    # dtend >= dtstart: ein Enddatum VOR dem Start (Tippfehler in der Vergangenheit)
                    # erfüllte `now >= dtend` sofort und fror das Event Sekunden nach Start ein
                    # (Fund 20.07.2026, #238). Solche unsinnigen Fenster nie als „beendet" werten.
                    if dtend and now >= dtend and dtend >= (ev.get("dtstart") or "") \
                            and not transport_anyone_in_progress(
                                conn, ev, started_before=dtend,
                                callsign_prefix=self.callsign_prefix,
                            ):
                        if set_transport_summarized(conn, ev["id"], now):
                            # Eager-Freeze (#66): den FINALEN Fortschritt einmal mit
                            # skip_open_probe=True rechnen und einfrieren — exakt identisch zum
                            # späteren Lazy-Recompute des Endpoints. So bleibt KEIN
                            # Offen-Zweig-Artefakt hängen (reserved_*, participants-Status
                            # „unterwegs", flight_count) — ein reines in_air/airborne-Normalisieren
                            # hätte diese Felder übersehen (Review-Fund 2). Quips fehlen hier
                            # bewusst noch (entstehen erst danach) — der Endpoint-Read überlagert
                            # sie frisch, der Snapshot muss dafür nicht neu geschrieben werden.
                            frozen = compute_transport_progress(
                                conn, ev, now, callsign_prefix=self.callsign_prefix,
                                skip_open_probe=True,
                            )
                            write_progress_snapshot(conn, "kutter", ev["id"], frozen, now)
                            if frozen["flight_count"] > 0:
                                tons = round(frozen["total_kg"] / 1000, 2)
                                body = f"Feierabend: {frozen['loaded_count']} Frachtflüge, {tons} t bewegt ✅"
                                if do_quips:
                                    summary = await asyncio.to_thread(
                                        llm.event_summary, event_summary_context(ev, frozen)
                                    )
                                    if summary:
                                        set_transport_summary_quip(conn, ev["id"], summary)
                                        body = summary
                                if push_on:
                                    pushes.append({"title": name, "body": body, "url": "/"})
                            # else: leeres Event — abgeschlossen (Latch), aber kein Push und
                            # kein KI-Aufruf (kein bezahlter LLM-Call ohne jede Aktivität).
                    # Pro-Flug-Sprüche für neue beladene Flüge ohne Cache sammeln (später async erzeugen).
                    if do_quips:
                        collect_quip_jobs(ev, progress)
                conn.commit()
                subscriptions = get_push_subscriptions_for_events(conn) if pushes else []
            finally:
                conn.close()
            for payload in pushes:
                self.broadcast_notify("events", None, payload)
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
        """Zuladung eines Musters recherchieren und vorbefüllen (source='llm').

        Silent-Fail nach außen. Die Methode hat mehrere Ausgänge; drei davon schreiben einen
        Zustand nach ``payload_research``:

        - Erfolg → ``ok``
        - kein Ergebnis (``None``) → ``nichts_gefunden`` (nach 30 Tagen erneut)
        - transienter Fehler → ``fehler`` mit Backoff; **kein Endzustand**

        Der Unterschied ist der ganze Punkt: ``Overloaded`` ist kein „keine Daten".

        Die übrigen Ausgänge schreiben bewusst **nichts** und lassen das Muster damit offen
        (es kommt beim nächsten fälligen Zeitpunkt wieder dran): läuft für dasselbe Muster
        schon eine Recherche (In-Flight-Kurzschluss), ist das Muster inzwischen manuell
        gepflegt, läuft noch ein Backoff, oder schlägt die DB selbst fehl — vor der Recherche
        (dann fand kein Versuch statt, ``attempts`` darf nicht steigen) oder beim Schreiben
        des Ergebnisses. Nie propagiert eine Ausnahme nach außen: die Nachlese ruft diese
        Methode in einer Schleife auf, ein Kandidat darf die übrigen nicht mitreißen.
        """
        from app import llm
        from app.database import (
            get_payload_map, get_payload_research, is_retry_due,
            mark_payload_research, upsert_payload,
        )
        code = normalize_type_code(type_code)
        if not code:
            return
        # In-Flight-Guard: für dasselbe Muster läuft schon eine (bezahlte) Recherche — egal ob
        # vom Live-Auslöser oder von der Nachlese angestoßen. Der DB-Zustand entsteht erst nach
        # dem Ergebnis, deckt diese 30-300 s also nicht ab.
        if code in self._payload_research_inflight:
            logger.debug("Auto-Zuladung %s: Recherche läuft bereits — kein zweiter Start", code)
            return
        self._payload_research_inflight.add(code)
        try:
            jetzt = self._now()
            conn = get_connection(self.db_path)
            try:
                if code in get_payload_map(conn):
                    return  # inzwischen (manuell) gepflegt → nicht anfassen
                st = get_payload_research(conn, code)
                if st is not None and not is_retry_due(st["state"], st["attempts"],
                                                       st["checked_at"], jetzt):
                    return  # Backoff läuft noch
            except Exception:
                # DB-Fehler VOR dem (bezahlten) LLM-Aufruf: es fand noch kein Versuch statt, also
                # keinen mark_payload_research-Aufruf nachschieben (attempts soll nicht steigen).
                # Wichtig fuer _research_due_payloads: ungefangen wuerde das die ganze Nachlese
                # abbrechen, nicht nur diesen einen Kandidaten.
                logger.exception("Auto-Zuladung %s: DB-Fehler vor der Recherche", code)
                return
            finally:
                conn.close()

            try:
                s = await asyncio.to_thread(llm.suggest_aircraft_payload, code)
            except llm.TransientResearchError as exc:
                conn = get_connection(self.db_path)
                try:
                    mark_payload_research(conn, code, "fehler", jetzt, last_error=str(exc)[:200])
                    conn.commit()
                finally:
                    conn.close()
                logger.info("Auto-Zuladung %s: vorübergehend gescheitert (%s) — wird wiederholt",
                            code, exc)
                return
            except Exception as exc:  # noqa: BLE001 — nie einen Poll-Durchlauf reißen
                conn = get_connection(self.db_path)
                try:
                    mark_payload_research(conn, code, "fehler", jetzt, last_error=str(exc)[:200])
                    conn.commit()
                finally:
                    conn.close()
                logger.exception("Auto-Zuladung %s: unerwarteter Fehler", code)
                return

            conn = get_connection(self.db_path)
            try:
                if s is None:
                    mark_payload_research(conn, code, "nichts_gefunden", jetzt)
                    conn.commit()
                    logger.info("Auto-Zuladung: keine Daten für %s gefunden", code)
                    return
                if code in get_payload_map(conn):
                    mark_payload_research(conn, code, "ok", jetzt)
                    conn.commit()
                    return  # inzwischen manuell gepflegt
                upsert_payload(
                    conn, code,
                    mtow_kg=s.get("mtow_kg"), empty_kg=s.get("empty_kg"),
                    fuel_kg=s.get("fuel_kg", s.get("fuel_full_kg")),
                    fuel_full_kg=s.get("fuel_full_kg"),
                    crew_kg=s.get("crew_kg"), source="llm",
                    make_model=s.get("make_model"),
                )
                mark_payload_research(conn, code, "ok", jetzt)
                conn.commit()
            except Exception:
                # Die (bezahlte) Recherche selbst ist gelungen, nur das Schreiben schlug fehl
                # (z. B. SQLite-Lock-Kontention zwischen dem Live-Trigger und der serialisierten
                # Nachlese). Bewusst KEIN weiterer Schreibversuch hier (Gefahr, dieselbe Ursache
                # erneut zu treffen) -- der Zustand bleibt "nie versucht"/alter Backoff-Stand, das
                # Muster gilt beim nächsten fälligen Zeitpunkt wieder als offen und wird erneut
                # recherchiert. Kostet im Fehlerfall ggf. noch einmal ~4 ct, aber ein erfolgreiches
                # Ergebnis verschwindet nicht lautlos für immer. Wichtig fuer
                # _research_due_payloads: ungefangen wuerde das die ganze Nachlese fuer die
                # UEBRIGEN Kandidaten abbrechen, nicht nur diesen einen.
                logger.exception("Auto-Zuladung %s: Ergebnis konnte nicht gespeichert werden", code)
                return
            finally:
                conn.close()
            logger.info("Auto-Zuladung vorbefüllt: %s (%s)", code, s.get("make_model"))
        finally:
            # Garantiert auf JEDEM Rückgabepfad (Erfolg, nichts_gefunden, fehler, manuell
            # gepflegt, DB-Fehler, Cancel) — sonst bliebe das Muster für immer gesperrt.
            self._payload_research_inflight.discard(code)

    async def _research_due_payloads(self) -> None:
        """Nachlese: fällige Muster aus dem Flugbestand, serialisiert und gedeckelt.

        30 der 33 Lücken vom 2026-07-30 sind Altflüge, die vor Einführung der Auto-Recherche
        (2026-07-02) stattfanden — der Live-Auslöser erreicht sie nie. Serialisiert und mit
        Deckel, weil jede Recherche ~4 ct und ~30 s kostet und ein einzelner Request schon
        einmal über 9 Minuten lief (docs/architecture.md:202).

        Ohne ``ANTHROPIC_API_KEY`` (ein unterstützter Zustand) passiert gar nichts: der
        Live-Auslöser prüft das ebenfalls. Ungeprüft lieferte ``suggest_aircraft_payload``
        sofort ``None`` — und ``None`` heißt hier „Muster nicht auffindbar", nicht „System
        nicht konfiguriert". Alle Lücken wären binnen einer halben Stunde mit
        ``nichts_gefunden`` und 30-Tage-Sperre belegt; wird der Key danach gesetzt, passierte
        einen Monat lang nichts. Genau der Fehler, den dieser Branch behebt.
        """
        try:
            from app import llm
            if not llm.is_configured():
                return
            from app.database import payload_research_candidates
            jetzt = self._now()
            conn = get_connection(self.db_path)
            try:
                codes = payload_research_candidates(
                    conn, jetzt, limit=self._PAYLOAD_RESEARCH_LIMIT
                )
            finally:
                conn.close()
            if not codes:
                return
            logger.info("Zuladungs-Nachlese: %d Muster (%s)", len(codes), ", ".join(codes))
            for code in codes:
                await self._auto_research_payload(code)   # serialisiert, nie parallel
        except Exception:
            logger.exception("Error in _research_due_payloads")

    def _muster_name(self, conn, code: str) -> str | None:
        """Name nach Rangfolge: Admin-Korrektur → aircraft_payloads.make_model.

        Die dritte Stufe (LLM-Recherche) füllt `aircraft_payloads` über Teil 8 und wirkt
        deshalb automatisch über Stufe 2 — hier wird sie nicht separat angestoßen.
        """
        from app.aircraft_info import harden_name
        row = conn.execute(
            "SELECT name_override, name FROM aircraft_types WHERE type_code = ?", (code,)
        ).fetchone()
        if row is not None and row["name_override"]:
            return harden_name(row["name_override"])
        p = conn.execute(
            "SELECT make_model FROM aircraft_payloads WHERE type_code = ?", (code,)
        ).fetchone()
        if p is not None and p["make_model"]:
            return harden_name(p["make_model"])
        return None

    async def _resolve_aircraft_type(self, type_code: str) -> None:
        """Muster-Infos für einen Typcode holen und speichern. Silent-Fail nach außen.

        Läuft NIE im Klickpfad: der Aufruf kommt aus dem Poller, der Nachlese oder dem
        Retry-Job. Der Ausgang landet in ``aircraft_types.fetch_state``.

        Nie propagiert eine Ausnahme nach außen — weder ein DB- noch ein HTTP-Fehler: die
        Nachlese ruft diese Methode in einer Schleife auf, ein Kandidat darf die übrigen nicht
        mitreißen, und der Live-Auslöser darf keinen Poll-Durchlauf reißen.
        """
        from app import aircraft_info, llm
        from app.database import (
            get_aircraft_type, get_payload_map, get_payload_research, is_retry_due,
            mark_aircraft_type_state, upsert_aircraft_type_import,
        )
        code = normalize_type_code(type_code)
        if not code:
            return
        # In-Flight-Guard: für dasselbe Muster läuft schon eine Auflösung — egal ob vom
        # Live-Auslöser (jeder Poll, alle 15 s) oder von der 10-Minuten-Nachlese angestoßen.
        # Der DB-Zustand entsteht erst nach der HTTP-Auflösung und deckt deren Laufzeit nicht ab;
        # ohne diesen Kurzschluss liefen mehrere gleichzeitige Requests gegen Wikipedia/Commons
        # für dasselbe Muster (strukturell derselbe Fehler wie der AP32-Kostenbug in Plan A).
        if code in self._aircraft_info_inflight:
            logger.debug("Muster-Info %s: Auflösung läuft bereits — kein zweiter Start", code)
            return
        self._aircraft_info_inflight.add(code)
        try:
            jetzt = self._now()
            conn = get_connection(self.db_path)
            try:
                vorhanden = get_aircraft_type(conn, code)
                if vorhanden and vorhanden["alias_of"]:
                    return  # Alias hat keine eigenen Daten
                if vorhanden and not is_retry_due(
                    vorhanden["fetch_state"] or "neu", vorhanden["attempts"] or 0,
                    vorhanden["checked_at"], jetzt,
                ):
                    # 'ok', laufender Backoff oder 30-Tage-Sperre — nichts zu tun. Der
                    # In-Flight-Guard deckt nur GLEICHZEITIGE Läufe ab, nicht die Wiederholung
                    # beim nächsten Poll: das Kriterium für new_codes ist der Zustand in
                    # payload_research, nicht in aircraft_types. Ohne ANTHROPIC_API_KEY (ein
                    # unterstützter Zustand) bleibt payload_research für immer leer, der Code
                    # stünde bei JEDEM Poll wieder in new_codes — und ohne diese Prüfung liefe
                    # für jedes fliegende Muster alle 15 s eine komplette Wikipedia-Suche samt
                    # Foto-Download, von einer bei Wikimedia vorbelasteten IP.
                    return
                lemma = conn.execute(
                    "SELECT wiki_title_override FROM aircraft_types WHERE type_code = ?", (code,)
                ).fetchone()
                lemma = lemma["wiki_title_override"] if lemma else None
                # Reihenfolge zählt: ERST den Zustand der Zuladungs-Recherche lesen, DANN den
                # Namen. Andersherum gäbe es ein Fenster, in dem die Recherche zwischen beiden
                # Lesevorgängen fertig wird — der Name wäre noch als leer gelesen, der Zustand
                # schon 'ok', und der Zweig unten schriebe fälschlich 'nichts_gefunden'.
                # `_auto_research_payload` schreibt make_model und den 'ok'-Zustand in EINEM
                # Commit; wer 'ok' sieht, sieht deshalb auch den Namen.
                payload_zustand = get_payload_research(conn, code)
                # Eine bereits vorhandene aircraft_payloads-Zeile (gleich welcher Quelle) heisst
                # ZUSAETZLICH "fertig", auch OHNE Endzustand in payload_research: dessen eigener
                # "inzwischen (manuell) gepflegt"-Kurzschluss (`if code in get_payload_map(conn):
                # return`) greift ab der ERSTEN Zeile und ruehrt das Muster dann nie wieder an --
                # ein 'ok'/'nichts_gefunden' in payload_research kaeme fuer 'manual'/'curated'-
                # Zeilen und fuer ueber den Admin-Knopf gespeicherte LLM-Vorschlaege NIE, das
                # waren beides Wege AUSSERHALB von _auto_research_payload. Ohne diese zweite
                # Quelle bliebe so ein Muster fuer immer Kandidat der Nachlese (reale
                # Beobachtung: MR20, Admin-Speicherung 2026-07-26 mit einem 1063-Zeichen-Prosa-
                # make_model, das harden_name() zu Recht verwirft -- und ohne diese Zeile hier
                # zu jedem der folgenden 10-Minuten-Laeufe erneut als einziger Kandidat).
                hat_zuladungszeile = code in get_payload_map(conn)
                name = self._muster_name(conn, code)
            except Exception:
                # DB-Fehler VOR der Auflösung: es fand kein Versuch statt, also auch keinen
                # Zustand nachschieben (attempts soll nicht steigen). Das Muster gilt beim
                # nächsten Lauf wieder als offen. Ungefangen risse das die ganze Nachlese.
                logger.exception("Muster-Info %s: DB-Fehler vor der Auflösung", code)
                return
            finally:
                conn.close()

            if not lemma and not name:
                # Kein brauchbarer Name (oder nur ein Prosa-Altwert) → nichts zu suchen.
                #
                # ABER: „noch kein Name" ist nicht dasselbe wie „es wird nie einen geben".
                # `_muster_name` liest ausschließlich aircraft_payloads.make_model, und genau
                # diese Zeile legt erst die Zuladungs-Recherche aus Plan A an. Der Live-
                # Auslöser startet BEIDE gleichzeitig (`new_codes` enthält per Konstruktion nur
                # Codes OHNE aircraft_payloads-Zeile) — die Recherche braucht 30–300 s, diese
                # Methode ist nach Millisekunden hier. Ohne die Prüfung unten bekäme praktisch
                # JEDES neu gesehene Muster sofort 'nichts_gefunden' und damit 30 Tage Sperre,
                # obwohl der Name Minuten später dasteht. Das ist derselbe Fehler wie der
                # AP32-Kostenbug aus Plan A: ein VORÜBERGEHENDER Zustand als ENDGÜLTIGES
                # Ergebnis gespeichert.
                #
                # Endzustand der Zuladungs-Recherche ist nur 'ok' (fertig, aber ohne
                # verwertbaren make_model — sollte nicht vorkommen) oder 'nichts_gefunden'
                # (wirklich nichts gefunden). Alles andere (nie versucht → None, 'neu',
                # 'fehler' mit Backoff) heißt: die Recherche läuft noch oder ist noch nicht
                # dran. Dann OHNE Zustandsschreibung zurück — der Code bleibt 'neu' und ist
                # beim nächsten Fälligkeitscheck wieder Kandidat, sobald der Name da ist.
                # Preis dieser Wahl: ein Muster, für das nie eine Zuladungs-Recherche läuft
                # (z. B. ohne ANTHROPIC_API_KEY), bleibt dauerhaft Kandidat. Das kostet nichts
                # (kein HTTP, Rückkehr nach wenigen Millisekunden), belegt aber einen der
                # _AIRCRAFT_INFO_LIMIT-Plätze je Nachlese-Lauf. Bewusst so: die Alternative
                # wäre wieder eine 30-Tage-Sperre aus einem Konfigurationszustand heraus.
                zustand_offen = (
                    payload_zustand is None
                    or (payload_zustand.get("state") not in ("ok", "nichts_gefunden"))
                ) and not hat_zuladungszeile
                if zustand_offen:
                    logger.debug(
                        "Muster-Info %s: noch kein Name, Zuladungs-Recherche noch offen (%s) "
                        "— kein Zustand geschrieben",
                        code, (payload_zustand or {}).get("state"),
                    )
                    return
                conn = get_connection(self.db_path)
                try:
                    mark_aircraft_type_state(conn, code, "nichts_gefunden", jetzt)
                    conn.commit()
                except Exception:
                    logger.exception("Muster-Info %s: Zustand konnte nicht gespeichert werden",
                                     code)
                finally:
                    conn.close()
                return

            try:
                if lemma:
                    res = await asyncio.to_thread(
                        aircraft_info.resolve_title, "de", lemma, aircraft_info.fetch_json
                    )
                    if res is None:
                        res = await asyncio.to_thread(
                            aircraft_info.resolve_title, "en", lemma, aircraft_info.fetch_json
                        )
                else:
                    res = await asyncio.to_thread(
                        aircraft_info.resolve_type, name, aircraft_info.fetch_json
                    )
                foto_datei = None
                foto_fehler = None
                if res and res.get("photo_url"):
                    # Das Foto ist die Kür, der Artikeltext die Pflicht: ab hier darf NICHTS
                    # mehr die schon gelungene Recherche wegwerfen. Bis 2026-08-05 lag der
                    # Download vor diesem try, ein Fehler flog in den äußeren Handler und
                    # verwarf den Text — während ein unlesbares Bild längst sauber abgefangen
                    # wurde. Die Asymmetrie war unbegründet und real teuer: beim Neu-Holen
                    # von 13 Mustern auf einmal drosselte Wikimedia den Bild-Download mit
                    # HTTP 429, und C210 verlor deswegen seinen fertigen deutschen Text.
                    try:
                        rohdaten = await asyncio.to_thread(
                            aircraft_info.download_photo, res["photo_url"]
                        )
                        # Rev. 3 (I3): dieselbe Aufbereitung wie beim Admin-Upload — Commons
                        # liefert die ORIGINALdatei (gemessen bis 4 MB), die sonst
                        # unverkleinert auf das Volume und an jedes Mobilgerät ginge.
                        # `to_web_jpeg` verkleinert auf 1280 px und kodiert als JPEG neu;
                        # damit stimmt auch der ausgelieferte MIME-Typ, wenn Commons ein
                        # SVG/TIFF liefert.
                        bilddaten = await asyncio.to_thread(
                            aircraft_info.to_web_jpeg, rohdaten
                        )
                    except ValueError as exc:
                        # Kein von Pillow lesbares Bild (z. B. SVG). Endgültig: ein Retry
                        # bekäme dieselbe Datei. Der Text bleibt, das Foto entfällt.
                        logger.info("Muster-Info %s: Foto unbrauchbar, nur Text (%s)",
                                    code, exc)
                        bilddaten = None
                    except Exception as exc:  # noqa: BLE001 — Text schlägt Foto, immer
                        # Download gescheitert (429, Timeout, 404). Ob das Muster deswegen
                        # wieder auf die Wiedervorlage kommt, entscheidet unten
                        # `llm.is_transient_error` — der Text wird in JEDEM Fall geschrieben.
                        logger.info("Muster-Info %s: Foto nicht ladbar, nur Text (%s)",
                                    code, exc)
                        bilddaten = None
                        foto_fehler = exc
                    if bilddaten is not None:
                        self._photo_dir.mkdir(parents=True, exist_ok=True)
                        foto_datei = f"{code}.jpg"
                        (self._photo_dir / foto_datei).write_bytes(bilddaten)
            except Exception as exc:  # noqa: BLE001 — nie einen Job reißen
                zustand = "fehler" if llm.is_transient_error(exc) else "nichts_gefunden"
                conn = get_connection(self.db_path)
                try:
                    mark_aircraft_type_state(conn, code, zustand, jetzt,
                                             last_error=str(exc)[:200])
                    conn.commit()
                except Exception:
                    logger.exception("Muster-Info %s: Zustand konnte nicht gespeichert werden",
                                     code)
                finally:
                    conn.close()
                logger.info("Muster-Info %s: %s (%s)", code, zustand, exc)
                return

            conn = get_connection(self.db_path)
            try:
                if res is None:
                    mark_aircraft_type_state(conn, code, "nichts_gefunden", jetzt)
                else:
                    upsert_aircraft_type_import(
                        conn, code, now=jetzt,
                        name=name, name_source="payloads" if name else None,
                        wiki_lang=res.get("wiki_lang"), wiki_title=res.get("wiki_title"),
                        extract=res.get("extract"),
                        photo_file=foto_datei,
                        photo_licence=res.get("photo_licence"),
                        photo_artist=res.get("photo_artist"),
                        photo_source_url=res.get("photo_source_url"),
                    )
                    if foto_fehler is not None and llm.is_transient_error(foto_fehler):
                        # Text ist geschrieben und sofort sichtbar; nur das Foto fehlt noch.
                        # `fehler` (statt `ok`) hält das Muster in der Wiedervorlage, damit
                        # der Backoff es später erneut versucht — bei einem 429 ist das Bild
                        # beim nächsten Mal in aller Regel da. Ein endgültiger Fehler (404
                        # auf eine gelöschte Commons-Datei) fällt hier durch und schließt die
                        # Auflösung mit `ok` ab, sonst hinge das Muster endlos im Backoff.
                        mark_aircraft_type_state(conn, code, "fehler", jetzt,
                                                 last_error=str(foto_fehler)[:200])
                    else:
                        mark_aircraft_type_state(conn, code, "ok", jetzt)
                conn.commit()
            except Exception:
                # Die Auflösung selbst ist gelungen, nur das Schreiben schlug fehl (z. B.
                # SQLite-Lock-Kontention zwischen Live-Trigger und Nachlese). Kein zweiter
                # Schreibversuch — der Zustand bleibt offen, das Muster kommt beim nächsten Lauf
                # wieder dran. Wichtig für _resolve_due_aircraft_types: ungefangen bräche das die
                # Nachlese für die ÜBRIGEN Kandidaten ab, nicht nur für diesen einen.
                logger.exception("Muster-Info %s: Ergebnis konnte nicht gespeichert werden", code)
            finally:
                conn.close()
        finally:
            # Garantiert auf JEDEM Rückgabepfad (Alias, kein Name, Fehler, nichts_gefunden, ok,
            # Cancel) — sonst bliebe das Muster für die restliche Prozesslaufzeit gesperrt.
            self._aircraft_info_inflight.discard(code)

    async def _requeue_missing_photos(self) -> None:
        """Zustand zurücksetzen, wo die Fotodatei fehlt.

        Rev. 2 (W2): ``rm -rf data/aircraft-photos/`` ist laut Spec eine legitime Reparatur,
        und das nächtliche Backup enthält die Dateien nicht (nur die DB). Ohne diesen Schritt
        sagt die DB ``photo_file`` gesetzt, die Datei fehlt, und ``fetch_state='ok'`` sorgt
        dafür, dass nie wieder etwas nachgeladen wird.
        """
        from app.database import mark_aircraft_type_state
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT type_code, photo_file FROM aircraft_types "
                "WHERE photo_file IS NOT NULL AND photo_file != ''"
            ).fetchall()
            jetzt = self._now()
            for r in rows:
                if not (self._photo_dir / r["photo_file"]).exists():
                    mark_aircraft_type_state(conn, r["type_code"], "neu", jetzt)
            conn.commit()
        finally:
            conn.close()

    async def _resolve_due_aircraft_types(self) -> None:
        """Nachlese über fällige Muster — serialisiert, gedeckelt."""
        try:
            from app.database import aircraft_type_candidates
            try:
                await self._requeue_missing_photos()
            except Exception:
                # Nur eine Reparaturmaßnahme — schlägt sie fehl, ist das kein Grund, die
                # eigentliche Nachlese ausfallen zu lassen.
                logger.exception("Muster-Infos: Requeue fehlender Fotos fehlgeschlagen")
            jetzt = self._now()
            conn = get_connection(self.db_path)
            try:
                codes = aircraft_type_candidates(conn, jetzt, limit=self._AIRCRAFT_INFO_LIMIT)
            finally:
                conn.close()
            if not codes:
                return
            logger.info("Muster-Infos: %d Muster (%s)", len(codes), ", ".join(codes))
            for code in codes:
                # Fehler-Isolation je Kandidat: _resolve_aircraft_type fängt selbst alles ab,
                # dieses try ist das Netz für alles Unvorhergesehene. Ein `except Exception` nur
                # um die ganze Schleife herum würde beim ersten Ausrutscher die übrigen Muster
                # stillschweigend ausfallen lassen.
                try:
                    await self._resolve_aircraft_type(code)   # serialisiert, nie parallel
                except Exception:
                    logger.exception("Muster-Info %s: Kandidat übersprungen", code)
        except Exception:
            logger.exception("Error in _resolve_due_aircraft_types")

    async def _check_event_reminders(self) -> None:
        """Periodisch (~5 min): FriesenEvents, Bummel-Rennen und Kutter-Events, die in ~1 h
        beginnen, einmalig per Push erinnern. Drei Quellen: generische Kalender-Events
        (events_due_for_reminder), Bummel-Rennen (bummel_races_due_for_reminder) und
        Kutter-Events (transport_events_due_for_reminder, manuell + Kalender, push_enabled-
        gated). Kalender-Bummel/-Kutter sind aus der generischen Quelle ausgeschlossen, damit
        es keinen Doppel-Push gibt. Empfänger sind die Events-Abonnenten (notify_events).
        Latchend via event_reminders_sent (synthetische Keys 'bummel:{id}' / 'kutter:{id}')."""
        try:
            from datetime import datetime, timezone
            from app.database import (
                events_due_for_reminder, bummel_races_due_for_reminder,
                transport_events_due_for_reminder, mark_event_reminded,
                get_push_subscriptions_for_events,
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(self.db_path)
            try:
                generic = events_due_for_reminder(conn, now, lead_min=60)
                bummels = bummel_races_due_for_reminder(conn, now, lead_min=60)
                kutters = transport_events_due_for_reminder(conn, now, lead_min=60)
                any_due = bool(generic or bummels or kutters)
                subscriptions = get_push_subscriptions_for_events(conn) if any_due else []
                for ev in generic:
                    mark_event_reminded(conn, ev["uid"], now)  # latchen, auch ohne Empfänger
                for r in bummels:
                    mark_event_reminded(conn, f"bummel:{r['id']}", now)
                for k in kutters:
                    mark_event_reminded(conn, f"kutter:{k['id']}", now)
                conn.commit()
            finally:
                conn.close()
            if any_due:
                logger.info(
                    "Event-Erinnerung fällig: generic=%s bummel=%s kutter=%s",
                    [e["uid"] for e in generic], [r["id"] for r in bummels],
                    [k["id"] for k in kutters],
                )
            # Nutzlasten einmal bauen — sie speisen beide Anzeigeflächen (Web-Push im Browser,
            # Sim-Benachrichtigung im Kniebrett). Vorher hing die Formulierung im
            # VAPID-Zweig fest; ohne Web-Push-Schlüssel wäre im Cockpit nichts angekommen.
            reminder_pushes: list[dict] = []
            for ev in generic:
                reminder_pushes.append({
                    "title": "FriesenEvent",
                    "body": f"🗓 {_lead_phrase(ev['dtstart'], now)}: {ev.get('summary') or 'FriesenEvent'}",
                    "url": "/",
                })
            for r in bummels:
                reminder_pushes.append({
                    "title": "FriesenFliegerBummel",
                    "body": f"🗓 {_lead_phrase(r['dtstart'], now)}: {r.get('name') or 'FriesenFliegerBummel'}",
                    "url": "/",
                })
            for k in kutters:
                reminder_pushes.append({
                    "title": "FriesenKutter",
                    "body": f"🗓 {_lead_phrase(k['dtstart'], now)}: {k.get('name') or 'FriesenKutter'}",
                    "url": "/",
                })
            for payload in reminder_pushes:
                self.broadcast_notify("events", None, payload)
            if reminder_pushes and subscriptions and self.vapid_private_key:
                for payload in reminder_pushes:
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
        openaip_api_key=settings.OPENAIP_API_KEY,
    )
