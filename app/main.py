"""FriesenSpy FastAPI-App — REST-Endpoints + SSE-Stream."""
from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from datetime import timezone as _timezone

import httpx as _httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import ADMIN_COOKIE, check_password, make_admin_token, verify_admin_token
from app.config import get_settings
from app.database import (
    _DATA_RETENTION_DAYS,
    aggregate_bummel_kpis,
    aggregate_kutter_kpis,
    apply_bummel_overrides,
    audit_gps_vs_refile,
    canonicalize_flights,
    canonicalize_legs,
    compute_bummel_standings,
    create_bummel_race,
    delete_bummel_override,
    delete_bummel_race,
    force_bummel_revealed,
    get_bummel_race,
    get_push_subscriptions_for_events,
    list_bummel_overrides,
    list_bummel_races,
    public_bummel_view,
    set_bummel_push_enabled,
    set_bummel_reveal_suppressed,
    update_bummel_race,
    update_bummel_reveals,
    upsert_bummel_override,
    delete_pilot,
    delete_push_subscription,
    get_all_position_history,
    get_all_push_subscriptions,
    get_app_setting,
    get_calendar_events,
    get_connection,
    get_push_subscription_by_endpoint,
    list_pilots,
    set_app_setting,
    upsert_pilot,
    get_live_flight_track,
    get_live_positions,
    get_stats,
    get_stats_activity,
    get_statsim_last_fetched,
    get_statsim_positions,
    init_db,
    count_uncached_statsim,
    get_uncached_statsim_ids,
    save_statsim_positions,
    upsert_push_subscription,
    upsert_statsim_flights,
    compute_transport_progress,
    create_transport_event,
    delete_transport_event,
    get_transport_event,
    get_transport_cargo,
    get_transport_quips,
    list_transport_events,
    update_transport_event,
    set_transport_push_enabled,
    list_aircraft_payloads,
    upsert_payload,
    transport_default_payload_kg,
    list_cargo_catalog,
    upsert_cargo_catalog,
    delete_cargo_catalog,
    transport_quips_enabled,
    clear_transport_quips,
    get_progress_snapshot,
    write_progress_snapshot,
    delete_progress_snapshot,
    delete_progress_snapshots,
    list_custom_airports,
    upsert_custom_airport,
    delete_custom_airport,
    rebuild_flight_cache,
    list_gps_detection_gaps,
    dismiss_gps_detection_gap,
)
from app import geo
from app.geo import filter_event_pilots
from app.poller import VatsimPoller, create_poller, send_web_push
from app.statsim import fetch_flight_track, fetch_pilot_flights
from app.version import CHANGELOG, VERSION

_logger = logging.getLogger(__name__)


def configure_logging(level: str = "INFO") -> None:
    """Root-Logger konfigurieren, damit App-INFO-Logs sichtbar werden.

    Unter uvicorn hat der Root-Logger keinen eigenen Handler — Pythons
    Last-Resort-Handler gibt dann nur WARNING+ aus, weshalb INFO-Zeilen wie
    "PrefilePush … sent OK" verschwinden. `force=True` (re)installiert einen
    StreamHandler am Root-Logger und setzt das Level; uvicorns eigene benannte
    Logger bleiben unberührt. Ungültiges Level → Fallback INFO.
    """
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

# CID → Zeitpunkt des letzten vollständigen StatSim-Abrufs (days=0).
# Verloren beim Neustart → erstes days=0 nach Restart holt immer frische Daten.
_full_history_fetched: dict[int, datetime] = {}
_full_history_fetching: set[int] = set()  # laufende Full-Fetches
_statsim_updating: set[int] = set()       # laufende 31-Tage-Hintergrund-Fetches


async def _fetch_statsim_background(cid: int, api_key: str, db_path: str, full: bool) -> None:
    """Holt StatSim-Daten im Hintergrund und schreibt sie in den Cache."""
    try:
        async with _httpx.AsyncClient() as client:
            statsim_days = 365 if full else 31
            fresh = await fetch_pilot_flights(client, cid, api_key, statsim_days)
        for f in fresh:
            f["cid"] = cid
        conn = get_connection(db_path)
        try:
            upsert_statsim_flights(conn, fresh)
            conn.commit()
            # Frisch gecachte StatSim-Flüge können verwaiste eigene Tracks decken (A1-Schaden)
            # → sofort rekonstruieren, nicht erst beim nächsten Container-Start.
            try:
                from app.database import reconstruct_orphaned_flights
                if reconstruct_orphaned_flights(conn, cids=[cid]):
                    conn.commit()
            except Exception:
                _logger.exception("Track-Rekonstruktion nach StatSim-Refresh fehlgeschlagen")
        finally:
            conn.close()
        if full:
            _full_history_fetched[cid] = datetime.now(_timezone.utc)
    except Exception as e:
        _logger.warning("StatSim background fetch failed CID %s: %s", cid, type(e).__name__)
    finally:
        if full:
            _full_history_fetching.discard(cid)
        else:
            _statsim_updating.discard(cid)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    init_db(settings.DB_PATH)
    conn = get_connection(settings.DB_PATH)
    try:
        geo.set_custom_airports(list_custom_airports(conn))  # #50: Ergänzungs-Flugplätze laden
    finally:
        conn.close()
    poller = create_poller()
    app.state.poller = poller
    await poller.start()
    yield
    # Shutdown
    await poller.stop()


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# .webmanifest ist vielen mimetypes-DBs unbekannt → sonst als text/plain ausgeliefert.
# Vor dem StaticFiles-Mount registrieren, damit guess_type den korrekten Typ liefert.
import mimetypes as _mimetypes
_mimetypes.add_type("application/manifest+json", ".webmanifest")

app = FastAPI(title="FriesenSpy", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def no_index_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/")
async def index():
    return FileResponse("app/static/index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """Admin-Seite (Login-Formular + Bummel-Rennverwaltung). Schutz erfolgt über die
    /api/admin/*-Endpoints (Cookie); diese Seite selbst ist statisch."""
    return FileResponse("app/static/admin.html")


@app.get("/impressum", include_in_schema=False)
async def impressum_page():
    """Impressum (§ 5 DDG) — statische Seite."""
    return FileResponse("app/static/impressum.html")


@app.get("/datenschutz", include_in_schema=False)
async def datenschutz_page():
    """Datenschutzerklärung (Art. 13 DSGVO) — statische Seite."""
    return FileResponse("app/static/datenschutz.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


def _resolve_banner_version(selected: str | None) -> str | None:
    """Banner-Auswahl auf eine konkrete Changelog-Version (oder None = kein Banner) auflösen.

    ``off`` → None; eine konkrete Version → diese (falls existent, sonst None);
    ``auto``/leer → neuester Eintrag mit ``highlight: true`` (Fallback: neuester Eintrag).
    """
    if selected == "off":
        return None
    if selected and selected != "auto":
        return selected if any(e.get("version") == selected for e in CHANGELOG) else None
    for e in CHANGELOG:
        if e.get("highlight"):
            return e.get("version")
    return CHANGELOG[0]["version"] if CHANGELOG else None


@app.get("/api/frontend-config")
async def frontend_config():
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        selected = get_app_setting(conn, "banner_version", "auto")
    finally:
        conn.close()
    return {
        "openaip_api_key": settings.OPENAIP_API_KEY,
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        "version": VERSION,
        "changelog": CHANGELOG,
        "banner_version": _resolve_banner_version(selected),
        "callsign_prefix": settings.CALLSIGN_PREFIX,
    }


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    """Browser-Push-Subscription speichern."""
    body = await request.json()
    endpoint = body.get("endpoint", "")
    p256dh = body.get("p256dh", "")
    auth = body.get("auth", "")
    if not endpoint or not p256dh or not auth:
        _logger.warning(
            "push/subscribe 400 (fehlende Felder): endpoint=%s p256dh=%s auth=%s",
            (endpoint[:60] or "LEER"), bool(p256dh), bool(auth),
        )
        return JSONResponse({"error": "endpoint, p256dh and auth are required"}, status_code=400)
    if "permanently-removed.invalid" in endpoint:
        _logger.warning("push/subscribe 400 (permanently-removed.invalid): %s", endpoint[:80])
        return JSONResponse({"error": "invalid push endpoint"}, status_code=400)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        upsert_push_subscription(
            conn, endpoint, p256dh, auth,
            body.get("pilot_filter"),
            notify_prefiles=bool(body.get("notify_prefiles", False)),
            notify_ts=bool(body.get("notify_ts", False)),
            notify_events=bool(body.get("notify_events", False)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@app.delete("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    """Browser-Push-Subscription entfernen."""
    body = await request.json()
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        delete_push_subscription(conn, body["endpoint"])
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@app.get("/api/live")
async def get_live(request: Request):
    """Aktuelle Live-Positionen aller online Friesen."""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        positions = get_live_positions(conn)
    finally:
        conn.close()
    return positions


@app.get("/api/stats/activity")
async def get_stats_activity_endpoint(days: int = 30):
    """Flugaktivität über Zeit für Chart — gruppiert nach Tag/Woche/Monat."""
    days = _clamp_retention_days(days)  # #67: nie über die globale 365-Tage-Anzeigegrenze
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        return get_stats_activity(conn, days=days, callsign_prefix=settings.CALLSIGN_PREFIX)
    finally:
        conn.close()


_STATS_SORT_FIELDS = {"last_flight", "flight_count", "total_duration_min"}


@app.get("/api/stats")
async def get_stats_endpoint(
    request: Request,
    days: int = 30,
    sort_by: str = "last_flight",
    sort_dir: str = "desc",
):
    """Flugstunden pro Pilot. ?days=30|90|365&sort_by=...&sort_dir=asc|desc"""
    if sort_by not in _STATS_SORT_FIELDS:
        sort_by = "last_flight"
    days = _clamp_retention_days(days)  # #67: nie über die globale 365-Tage-Anzeigegrenze
    reverse = sort_dir != "asc"
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        stats = get_stats(conn, days=days, callsign_prefix=settings.CALLSIGN_PREFIX)
    finally:
        conn.close()
    if sort_by == "last_flight":
        stats.sort(key=lambda x: x.get("last_flight") or "", reverse=reverse)
    else:
        stats.sort(key=lambda x: x.get(sort_by) or 0, reverse=reverse)
    return stats


@app.get("/api/stats/special-events")
async def get_special_events_stats(days: int = 30):
    """Aggregierte Kennzahlen beider Spezial-Events (FriesenKutter + FriesenFliegerBummel) im
    Zeitfenster — NUR abgeschlossene Events/Rennen, bedient aus den #66-Snapshots (kein
    Track-Recompute). ?days=30|90|365."""
    if days not in (30, 90, 365):
        days = 30
    now = _now_iso()
    since = (datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_timezone.utc)
             - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    settings = get_settings()
    prefix = settings.CALLSIGN_PREFIX
    conn = get_connection(settings.DB_PATH)
    try:
        # --- FriesenKutter: abgeschlossen (summarized_at) & dtend im Fenster ---
        k_progresses = []
        for ev in list_transport_events(conn, since=since):
            if not ev.get("summarized_at") or (ev.get("dtend") or "") < since:
                continue
            p = _kutter_progress(conn, ev, now, prefix)
            if (p.get("flight_count") or 0) > 0:
                k_progresses.append(p)
        kutter = aggregate_kutter_kpis(k_progresses)

        # --- FriesenFliegerBummel: revealed_at & now>=dtend & dtend im Fenster ---
        update_bummel_reveals(conn, now, callsign_prefix=prefix)
        b_views = []
        for race in list_bummel_races(conn, since=since):
            dtend = race.get("dtend") or ""
            if not race.get("revealed_at") or now < dtend or dtend < since:
                continue
            v = _bummel_view(conn, race, now)
            if (v.get("participant_count") or 0) > 0:
                b_views.append(v)
        bummel = aggregate_bummel_kpis(b_views)

        return {"kutter": kutter, "bummel": bummel}
    finally:
        conn.close()


@app.get("/api/events")
async def get_events(
    request: Request,
    icao: str,
    radius: float = 150.0,
    start: str = "",
    end: str = "",
):
    """Event-Suche: Wer war bei einem bestimmten Event dabei?

    Query params:
        icao:   kommagetrennte ICAO-Codes, z.B. "EDDK,EDDL"
        radius: Suchradius in km (default 150)
        start:  ISO8601 UTC, z.B. "2024-01-01T10:00:00Z"
        end:    ISO8601 UTC, z.B. "2024-01-01T18:00:00Z"

    Flüge kommen aus :func:`canonicalize_legs` — dieselbe Wahrheit wie Statistik/Piloten-
    Detail/Bummel/Kutter (#33). Callsign-Filter bleibt FRS-Präfix (nicht `""`): position_history
    (und damit `flights`) enthält ohnehin nur FRS-Sessions (Poller filtert per Callsign,
    `filter_friesen_pilots`), aber `statsim_cache` kennt auch Fremd-Callsigns bekannter Piloten
    — die gehören laut 2-Klassen-Regel nur in die Piloten-Statistik, nicht in die Event-Analyse.
    """
    icao_list = [code.strip().upper() for code in icao.split(",") if code.strip()]
    global_search = icao_list == ["GLOBAL"]

    # #67: kein Suchfenster älter als die globale 365-Tage-Anzeigegrenze. Die älteren Positionen
    # bleiben in der DB (Cleanup deaktiviert), sind aber nicht durchsuchbar — verhindert
    # irreführende Teil-Treffer aus einem Zeitraum, der bewusst ausgeblendet ist.
    start = _clamp_retention_start(start, _now_iso())

    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        rows = get_all_position_history(conn, start, end)
    finally:
        conn.close()

    if global_search:
        from collections import defaultdict as _dd
        _pm: dict = _dd(list)
        for row in rows:
            cid = row.get("cid")
            if cid is not None:
                _pm[cid].append(row)
        pilot_map = dict(_pm)
    else:
        pilot_map = filter_event_pilots(rows, icao_list, radius, start, end)

    # callsign je cid aus der GPS-Nähe-Suche — Fallback-Anzeige, falls canonicalize_legs für
    # diesen Piloten keinen Flug im Fenster liefert (Teilnahme bleibt GPS-belegt, seltener Randfall).
    callsign_by_cid: dict[int, str] = {
        cid: (positions[0].get("callsign", "") if positions else "")
        for cid, positions in pilot_map.items()
    }

    # StatSim-Ergänzung: Piloten, die per DEP/ARR im Zeitfenster gefunden werden, aber keine
    # position_history haben (z.B. FriesenSpy war nicht aktiv) — nur zur cid-Ermittlung; die
    # Flug-Dicts selbst liefert canonicalize_legs (deckt StatSim intern mit ab).
    if global_search or icao_list:
        conn3 = get_connection(settings.DB_PATH)
        try:
            if global_search:
                statsim_rows = conn3.execute(
                    """
                    SELECT DISTINCT sc.cid, sc.callsign
                    FROM statsim_cache sc
                    WHERE sc.logon_time != ''
                      AND sc.logoff_time IS NOT NULL
                      AND sc.duration_min > 5
                      AND sc.logon_time <= ?
                      AND sc.logoff_time >= ?
                      AND sc.callsign LIKE ?
                    """,
                    (end or "9999-12-31", start or "0000-01-01",
                     settings.CALLSIGN_PREFIX + "%"),
                ).fetchall()
            else:
                placeholders = ",".join("?" * len(icao_list))
                statsim_rows = conn3.execute(
                    f"""
                    SELECT DISTINCT sc.cid, sc.callsign
                    FROM statsim_cache sc
                    WHERE (sc.departure IN ({placeholders}) OR sc.arrival IN ({placeholders}))
                      AND sc.logon_time != ''
                      AND sc.logoff_time IS NOT NULL
                      AND sc.duration_min > 5
                      AND sc.logon_time <= ?
                      AND sc.logoff_time >= ?
                      AND sc.callsign LIKE ?
                    """,
                    (*icao_list, *icao_list, end or "9999-12-31", start or "0000-01-01",
                     settings.CALLSIGN_PREFIX + "%"),
                ).fetchall()
        finally:
            conn3.close()

        for r in statsim_rows:
            cid = r["cid"]
            if cid not in callsign_by_cid:
                callsign_by_cid[cid] = r["callsign"] or ""

    all_cids = list(callsign_by_cid.keys())
    if not all_cids:
        return {"pilots": []}

    conn2 = get_connection(settings.DB_PATH)
    try:
        all_flights = canonicalize_legs(
            conn2, cids=all_cids, callsign_prefix=settings.CALLSIGN_PREFIX,
            start=start, end=end,
        )
        flights_by_cid: dict[int, list[dict]] = {}
        for f in all_flights:
            flights_by_cid.setdefault(f["cid"], []).append(f)

        pilots = []
        for cid in all_cids:
            name_row = conn2.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
            name = name_row["name"] if name_row else ""
            flights = flights_by_cid.get(cid, [])
            callsign = (flights[0].get("callsign") if flights else "") or callsign_by_cid.get(cid, "")
            pilots.append({
                "cid": cid,
                "callsign": callsign,
                "name": name,
                "flights": [
                    {
                        "logon_time": f.get("logon_time") or "",
                        "logoff_time": f.get("logoff_time") or "",
                        "callsign": f.get("callsign") or "",
                        "aircraft": f.get("aircraft") or "",
                        "aircraft_icao": f.get("aircraft_icao") or "",
                        "gps_departure": f.get("gps_departure") or "",
                        "gps_arrival": f.get("gps_arrival") or "",
                        "plan_departure": f.get("plan_departure") or "",
                        "plan_arrival": f.get("plan_arrival") or "",
                        "connection_closed": bool(f.get("connection_closed")),
                        "last_pos_ts": f.get("last_pos_ts") or "",
                        "duration_min": f.get("duration_min"),
                        "block_min": f.get("block_min"),
                        "distance_nm": f.get("distance_nm"),
                        "route": f.get("route") or "",
                        "remarks": f.get("remarks") or "",
                        "cruise_altitude": f.get("cruise_altitude") or "",
                        "cruise_tas": f.get("cruise_tas") or "",
                        "flight_rules": f.get("flight_rules") or "",
                        "alternate": f.get("alternate") or "",
                        "deptime": f.get("deptime") or "",
                        "enroute_time": f.get("enroute_time") or "",
                        "fuel_time": f.get("fuel_time") or "",
                        "id": f.get("id"),
                        "statsim_id": f.get("statsim_id"),
                        "cid": f.get("cid"),
                        "source": f.get("source"),
                    }
                    for f in flights
                ],
            })
    finally:
        conn2.close()

    return {"pilots": pilots}


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


async def _event_generator(request: Request, poller: VatsimPoller):
    """Async generator für SSE — sendet Live-Positions-Updates oder keepalives.

    Jede Verbindung registriert ihre eigene Queue (Per-Client-Fan-out) und deregistriert sie
    beim Disconnect im finally — so bekommt JEDER Client jedes Update (statt nur einer).
    """
    queue = poller.subscribe_sse()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        poller.unsubscribe_sse(queue)


@app.get("/api/sse")
async def sse_endpoint(request: Request):
    """SSE-Stream für Live-Updates."""
    poller: VatsimPoller = request.app.state.poller
    return StreamingResponse(
        _event_generator(request, poller),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/pilots/{cid}/flights")
async def get_pilot_flights(cid: int, days: int = 90, background_tasks: BackgroundTasks = None):
    """Alle Flüge eines Piloten: FriesenSpy sofort + StatSim aus Cache.

    StatSim wird im Hintergrund aktualisiert (letzter 31-Tage-Chunk bei normalem
    Aufruf; volle 365 Tage bei days=0). Antwort kommt immer sofort.
    Header X-StatSim-Status: fresh | updating | no-key
    """
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    statsim_status = "no-key"
    try:
        # #67: „letztes Jahr" (days=0) und jeder größere Wert werden auf die globale 365-Tage-
        # Anzeigegrenze gekappt — ältere Legs bleiben in der DB, werden aber nicht angezeigt.
        display_days = _clamp_retention_days(days) if days > 0 else _DATA_RETENTION_DAYS

        if settings.STATSIM_API_KEY:
            if days == 0:
                # Force full refresh (365 Tage) — Cooldown 24 h
                if cid in _full_history_fetching:
                    statsim_status = "updating"
                else:
                    last_full = _full_history_fetched.get(cid)
                    if last_full and (datetime.now(_timezone.utc) - last_full).total_seconds() < 86400:
                        statsim_status = "fresh"
                    else:
                        _full_history_fetching.add(cid)
                        if background_tasks is not None:
                            background_tasks.add_task(
                                _fetch_statsim_background, cid, settings.STATSIM_API_KEY, settings.DB_PATH, True
                            )
                        statsim_status = "updating"
            else:
                # Normaler Aufruf — nur letzten 31-Tage-Chunk im Hintergrund holen
                if cid in _statsim_updating:
                    statsim_status = "updating"
                else:
                    last = get_statsim_last_fetched(conn, cid)
                    cache_fresh = False
                    if last:
                        try:
                            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                            age_h = (datetime.now(_timezone.utc) - last_dt.astimezone(_timezone.utc)).total_seconds() / 3600
                            cache_fresh = age_h < 24
                        except Exception:
                            pass
                    if cache_fresh:
                        statsim_status = "fresh"
                    else:
                        _statsim_updating.add(cid)
                        if background_tasks is not None:
                            background_tasks.add_task(
                                _fetch_statsim_background, cid, settings.STATSIM_API_KEY, settings.DB_PATH, False
                            )
                        statsim_status = "updating"

        # Eine Wahrheit: kanonische GPS-Flüge dieses Piloten (GPS-only Phase 2, #23) — inkl.
        # unrefilter Zwischenlandungen (je Leg eine eigene Zeile).
        # callsign_prefix="" → alle Callsigns des Piloten (auch Nicht-FRS, wie bisher).
        start = (
            datetime.now(_timezone.utc) - timedelta(days=display_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Gecachte StatSim-Daten sind bei canonicalize_legs immer mit dabei (gültige Wahrheit,
        # identisch zu /api/stats); nur der Hintergrund-Fetch oben hängt am API-Key.
        result = canonicalize_legs(
            conn,
            cids=[cid],
            callsign_prefix="",
            start=start,
        )
    finally:
        conn.close()

    return JSONResponse(content=result, headers={"X-StatSim-Status": statsim_status})


@app.get("/api/pilots/{cid}/live-track")
async def get_pilot_live_track(cid: int):
    """Positions-Track des aktuell laufenden Fluges aus position_history."""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        return get_live_flight_track(conn, cid)
    finally:
        conn.close()


@app.get("/api/flights/{flight_id}/track")
async def get_flight_track(flight_id: int, logon: str = "", logoff: str = ""):
    """Positionshistorie eines FriesenSpy-Fluges aus position_history.

    logon/logoff können als Query-Params übergeben werden (nötig nach Merge
    zweier Fragmente, wo die DB noch alte Zeiten hat).
    """
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        flight = conn.execute(
            "SELECT cid, logon_time, logoff_time FROM flights WHERE id = ?", (flight_id,)
        ).fetchone()
        if not flight:
            raise HTTPException(status_code=404, detail="Flight not found")
        effective_logon = logon or flight["logon_time"] or ""
        effective_logoff = logoff or flight["logoff_time"] or datetime.now(_timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        rows = conn.execute(
            """
            SELECT latitude, longitude, altitude, groundspeed, heading, ts
            FROM position_history
            WHERE cid = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (flight["cid"], effective_logon, effective_logoff),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/api/pilots/{cid}/track")
async def get_pilot_track_window(cid: int, logon: str = "", logoff: str = ""):
    """Positions-Track eines GPS-Legs rein über cid + Zeitfenster (GPS-only, #v8.1.0).

    Anders als ``/api/flights/{id}/track`` braucht dieser Endpoint KEINE ``flights``-Zeile —
    er bedient GPS-Legs ohne zugeordneten Flugplan (``id=None``). Die Anzeige leitet den Track
    damit ausschließlich aus GPS ab. ``logoff`` MUSS für offene Legs die letzte Positionszeit
    (``last_pos_ts``) sein, NICHT „now" — sonst würden Positionen späterer Flüge mitgezogen.
    """
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        effective_logon = logon or ""
        effective_logoff = logoff or datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            """
            SELECT latitude, longitude, altitude, groundspeed, heading, ts
            FROM position_history
            WHERE cid = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (cid, effective_logon, effective_logoff),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/api/flights/statsim/{statsim_id}/track")
async def get_statsim_flight_track(statsim_id: int):
    """Positionshistorie eines StatSim-Fluges (lokal gecacht, sonst von StatSim API)."""
    conn = get_connection(get_settings().DB_PATH)
    try:
        cached = get_statsim_positions(conn, statsim_id)
        if cached:
            return cached
        settings = get_settings()
        if not settings.STATSIM_API_KEY:
            return []
        async with _httpx.AsyncClient() as client:
            positions = await fetch_flight_track(client, statsim_id, settings.STATSIM_API_KEY)
        if positions:
            save_statsim_positions(conn, statsim_id, positions)
            conn.commit()
        return positions
    finally:
        conn.close()


_statsim_backfill_state = {"running": False, "fetched": 0, "remaining": None}


async def _statsim_backfill_worker(db_path: str, api_key: str, prefix: str) -> None:
    """Hintergrund-Schleife: holt uncachte StatSim-Tracks batchweise bis keine mehr übrig sind.
    Seriell (ein Abruf nach dem anderen, 0,3 s Drossel) → keine DB-Sperr-Konflikte."""
    try:
        async with _httpx.AsyncClient() as client:
            while True:
                conn = get_connection(db_path)
                try:
                    ids = get_uncached_statsim_ids(conn, callsign_prefix=prefix, limit=50)
                    if not ids:
                        break
                    got = 0
                    for sid in ids:
                        try:
                            positions = await fetch_flight_track(client, sid, api_key)
                        except Exception:
                            positions = None
                        if positions:
                            save_statsim_positions(conn, sid, positions)
                            conn.commit()
                            got += 1
                            _statsim_backfill_state["fetched"] += 1
                        await asyncio.sleep(0.3)
                    _statsim_backfill_state["remaining"] = count_uncached_statsim(
                        conn, callsign_prefix=prefix
                    )
                finally:
                    conn.close()
                if got == 0:  # nur noch Flüge ohne API-Track → Abbruch (kein Endlos-Retry)
                    break
    except Exception:
        _logger.exception("StatSim-Backfill-Worker abgebrochen")
    finally:
        _statsim_backfill_state["running"] = False


@app.post("/api/admin/statsim-backfill")
async def admin_statsim_backfill(request: Request, limit: int = 40, background: int = 0):
    """Holt die GPS-Tracks von StatSim-Flügen (jüngste ohne lokalen Track) von der StatSim-API und
    cached sie in ``statsim_position_history`` — Grundlage für die GPS-Leg-Analyse aller StatSim-Flüge
    (#23 Task 5b, Schatten). Rein additiv, keine Wertungswirkung, gedrosselt (0,3 s je Abruf).

    ``background=1`` startet eine serverseitige Schleife, die bis zur Erschöpfung durchläuft (nicht an
    den Request gebunden) und sofort zurückkehrt — Fortschritt via ``GET …/statsim-backfill/status``.
    Ohne ``background`` synchron bis ``limit`` Flüge; **resumebar** (wiederholt aufrufen bis
    ``remaining`` = 0).
    """
    require_admin(request)
    settings = get_settings()
    if not settings.STATSIM_API_KEY:
        return {"had_key": False, "requested": 0, "fetched": 0, "empty": 0, "remaining": None}

    # callsign_prefix="" (nicht settings.CALLSIGN_PREFIX): Track-Backfill soll für JEDEN Flug
    # eines bekannten Piloten laufen, unabhängig vom Callsign — der Präfix entscheidet nur
    # über die Wertung, nicht darüber, ob GPS-Split-Logik angewendet wird (s. poller.py
    # _fetch_statsim_tracks).
    if background:
        if _statsim_backfill_state["running"]:
            return {"had_key": True, "started": False, "already_running": True,
                    **_statsim_backfill_state}
        conn = get_connection(settings.DB_PATH)
        try:
            remaining = count_uncached_statsim(conn, callsign_prefix="")
        finally:
            conn.close()
        _statsim_backfill_state.update({"running": True, "fetched": 0, "remaining": remaining})
        asyncio.create_task(_statsim_backfill_worker(
            settings.DB_PATH, settings.STATSIM_API_KEY, ""
        ))
        return {"had_key": True, "started": True, "remaining": remaining}

    limit = max(1, min(150, int(limit)))
    conn = get_connection(settings.DB_PATH)
    fetched = 0
    empty = 0
    points = 0
    try:
        ids = get_uncached_statsim_ids(conn, callsign_prefix="", limit=limit)
        async with _httpx.AsyncClient() as client:
            for sid in ids:
                try:
                    positions = await fetch_flight_track(client, sid, settings.STATSIM_API_KEY)
                except Exception:
                    positions = None
                if positions:
                    save_statsim_positions(conn, sid, positions)
                    fetched += 1
                    points += len(positions)
                else:
                    empty += 1
                await asyncio.sleep(0.3)
        conn.commit()
        remaining = count_uncached_statsim(conn, callsign_prefix="")
    finally:
        conn.close()
    return {
        "had_key": True, "requested": len(ids), "fetched": fetched,
        "empty": empty, "points": points, "remaining": remaining,
    }


@app.get("/api/admin/statsim-backfill/status")
async def admin_statsim_backfill_status(request: Request):
    """Fortschritt des Hintergrund-Backfills: ``running``, in diesem Lauf ``fetched``, ``remaining``."""
    require_admin(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        remaining = count_uncached_statsim(conn, callsign_prefix="")
    finally:
        conn.close()
    return {"running": _statsim_backfill_state["running"],
            "fetched": _statsim_backfill_state["fetched"], "remaining": remaining}


@app.get("/api/prefiles")
async def get_prefiles(request: Request):
    """Eingereichte VATSIM-Flugpläne mit FRS*-Callsign (aus letztem VATSIM-Poll)."""
    poller: VatsimPoller = request.app.state.poller
    settings = get_settings()
    result = []
    for p in poller.last_prefiles:
        fp = p.get("flight_plan") or {}
        cid = p.get("cid")
        name = ""
        if cid:
            conn = get_connection(settings.DB_PATH)
            try:
                row = conn.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
                if row:
                    name = row["name"]
            finally:
                conn.close()
        result.append({
            "callsign": p.get("callsign", ""),
            "cid": cid,
            "name": name,
            "departure": fp.get("departure", ""),
            "arrival": fp.get("arrival", ""),
            "alternate": fp.get("alternate", ""),
            "route": fp.get("route", ""),
            "remarks": fp.get("remarks", ""),
            "flight_rules": fp.get("flight_rules", ""),
            "aircraft_icao": fp.get("aircraft_icao", ""),
            "aircraft": fp.get("aircraft", ""),
            "cruise_tas": fp.get("cruise_tas", ""),
            "altitude": fp.get("altitude", ""),
            "enroute_time": fp.get("enroute_time", ""),
            "fuel_time": fp.get("fuel_time", ""),
            "deptime": fp.get("deptime", ""),
        })
    return result


@app.get("/api/teamspeak")
async def get_teamspeak(request: Request):
    """Aktuell im TeamSpeak befindliche FriesenFlieger (FRS-getaggte Clients).

    Liefert den letzten Snapshot des TS-Polls (nur FRS-getaggt). `enabled` zeigt an,
    ob die TS-Überwachung überhaupt aktiv ist — der Client blendet das Panel sonst aus.
    """
    poller: VatsimPoller = request.app.state.poller
    # Bewusst nur das FRS-Callsign nach außen geben — Klarnamen/Nick-Zusätze bleiben serverseitig.
    users = [{"frs": c["frs"]} for c in poller.ts_clients]
    return {
        "enabled": get_settings().TS_NOTIFY_ENABLED,
        "count": len(users),
        "users": users,
    }


@app.get("/api/airport/{icao}")
async def get_airport_coords(icao: str):
    """Koordinaten eines Flughafens via airportsdata (offline)."""
    from app.geo import icao_to_coords
    coords = icao_to_coords(icao.upper())
    if coords is None:
        raise HTTPException(status_code=404, detail="ICAO not found")
    return {"icao": icao.upper(), "lat": coords[0], "lon": coords[1]}


@app.get("/api/airports/check")
async def check_airports(codes: str = ""):
    """#77: eine kommagetrennte ICAO-Liste gegen die bekannten Plätze (airportsdata + eigene
    `custom_airports`) prüfen. Gibt die UNBEKANNTEN Codes zurück (`{"unknown": [...]}`) — für die
    Warnung an den Platz-Eingaben in Kutter- und Bummel-Editor. Offline, kein Auth nötig."""
    from app.geo import icao_to_coords
    unknown: list[str] = []
    for raw in codes.split(","):
        c = raw.strip().upper()
        if c and c not in unknown and icao_to_coords(c) is None:
            unknown.append(c)
    return {"unknown": unknown}


@app.get("/api/airports/search")
async def search_airports_endpoint(q: str = ""):
    """#77-Erweiterung: ICAO-Präfix-Suche (airportsdata + `custom_airports`) fürs Autocomplete an
    den Platz-Eingaben. `?q=EDW` → bis zu 20 Treffer `{results: [{icao, name}]}`. Offline."""
    from app.geo import search_airports
    return {"results": search_airports(q, limit=20)}


@app.get("/api/calendar/events")
async def get_calendar_events_endpoint():
    """FriesenEvents der letzten 365 Tage aus dem Google-Kalender-Cache."""
    conn = get_connection(get_settings().DB_PATH)
    try:
        return get_calendar_events(conn, days_back=365)
    finally:
        conn.close()


def _open_bummel_legs(conn, route_set: set[str], start: str, end: str) -> list[dict]:
    """Aktuell laufende Flüge (logoff_time IS NULL) auf einem Streckenbein.

    Liefert die „gerade unterwegs"-Info fürs Live-Banner: Flüge ohne block_min/Wertung,
    deren Start UND Ziel zur Strecke gehören. Provisorisch, bis der Flug abgeschlossen ist.
    """
    settings = get_settings()
    rows = conn.execute(
        "SELECT f.cid, f.callsign, f.departure, f.arrival, f.logon_time, f.aircraft_short, "
        "p.name FROM flights f LEFT JOIN pilots p ON f.cid = p.cid "
        "WHERE f.logoff_time IS NULL AND f.superseded_by IS NULL "
        "AND f.callsign LIKE ? AND f.logon_time <= ?",
        (settings.CALLSIGN_PREFIX + "%", end or "9999-12-31"),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        dep = (r["departure"] or "").strip().upper()
        arr = (r["arrival"] or "").strip().upper()
        if dep in route_set and arr in route_set and dep != arr:
            out.append({
                "cid": r["cid"],
                "name": r["name"] or "",
                "callsign": r["callsign"] or "",
                "departure": dep,
                "arrival": arr,
                "logon_time": r["logon_time"],
                "aircraft": r["aircraft_short"] or "",
            })
    return out


def _race_status(race: dict, now: str) -> str:
    """scheduled | running | waiting | revealed."""
    if race.get("revealed_at"):
        return "revealed"
    if now < (race.get("dtstart") or ""):
        return "scheduled"
    if now < (race.get("dtend") or ""):
        return "running"
    return "waiting"  # dtend erreicht, aber noch nicht enthüllt (Nachzügler)


def _transport_status(ev: dict, now: str) -> str:
    """scheduled | running | waiting | done (Feierabend-Bilanz erstellt)."""
    if ev.get("summarized_at"):
        return "done"
    if now < (ev.get("dtstart") or ""):
        return "scheduled"
    if now < (ev.get("dtend") or ""):
        return "running"
    return "waiting"  # dtend erreicht, aber Feierabend noch nicht gelatcht (Nachzügler)


def _build_race_view(conn, race: dict, now: str, *, force_reveal: bool = False) -> dict:
    """Öffentliche Sicht auf ein Rennen — vor Enthüllung redigiert (keine Zeiten/Schnitt).

    Admin-Korrekturen (``bummel_overrides``) werden auf die Wertung angewandt. ``force_reveal``
    liefert die volle Sicht auch während des Rennens (nur für die Admin-Vorschau).
    """
    route_icaos = [c for c in (race.get("route") or "").split(",") if c.strip()]
    route_set = {c.strip().upper() for c in route_icaos}
    standings = compute_bummel_standings(
        conn, route_icaos, race["dtstart"], race["dtend"],
        radius_km=race.get("radius_km"),  # None/0 → Default-Umkreis in der Funktion
    )
    overrides = list_bummel_overrides(conn, race["id"])
    if overrides:
        standings = apply_bummel_overrides(standings, overrides)
    in_progress = _open_bummel_legs(conn, route_set, race["dtstart"], race["dtend"])
    revealed = force_reveal or bool(race.get("revealed_at"))
    view = public_bummel_view(standings, in_progress, revealed=revealed)
    view["id"] = race["id"]
    view["name"] = race.get("name") or ""
    view["dtstart"] = race.get("dtstart")
    view["dtend"] = race.get("dtend")
    view["status"] = _race_status(race, now)
    if revealed and standings.get("disqualified"):
        view["disqualified"] = standings["disqualified"]
    return view


def _bummel_view(conn, race: dict, now: str, *, force_reveal: bool = False) -> dict:
    """Öffentliche Sicht auf ein Rennen — eingefroren (abgeschlossen) oder live, danach frische
    Überlagerung von Status + Metadaten aus der DB-Zeile (#66 §3).

    Ein Rennen gilt nur als abgeschlossen, wenn ``revealed_at`` gesetzt UND ``now >= dtend`` ist —
    ein per Admin-Override VOR ``dtend`` erzwungenes Reveal friert NICHT ein (bleibt live)."""
    finished = bool(race.get("revealed_at")) and now >= (race.get("dtend") or "")
    view = _frozen_or_compute(
        conn, "bummel", race["id"], finished=finished, now=now,
        compute_fn=lambda: _build_race_view(conn, race, now, force_reveal=force_reveal),
    )
    view = dict(view)
    view["status"] = _race_status(race, now)          # frisch
    view["name"] = race.get("name") or ""              # Metadaten aus der DB-Zeile
    # `route` NICHT aus der DB-Zeile überlagern: die berechnete/eingefrorene View liefert `route`
    # als Array (public_bummel_view: [ICAO, …]), die DB-Zeile aber als CSV-String — ein Überlagern
    # bräche das Frontend (`route.join(...)` auf einem String → TypeError, alle Bummel-Ansichten).
    # Eine Routen-Änderung invalidiert den Snapshot ohnehin (Admin-Edit/Kalender-Sync), daher ist
    # eine frische Überlagerung hier nicht nötig (#66 Review-Fund 1).
    view["dtstart"] = race.get("dtstart")
    view["dtend"] = race.get("dtend")
    return view


@app.get("/api/bummel/races")
async def get_bummel_races():
    """Liste aller Bummel-Rennen (Status + Teilnehmerzahl, keine Zeiten vor Enthüllung) — letzte
    ``_DATA_RETENTION_DAYS`` Tage (#67), abgeschlossene Rennen aus dem Snapshot (#66)."""
    now = datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(get_settings().DB_PATH)
    try:
        update_bummel_reveals(conn, now, callsign_prefix=get_settings().CALLSIGN_PREFIX)
        out = []
        for race in list_bummel_races(conn, since=_retention_since(now)):
            view = _bummel_view(conn, race, now)
            out.append({
                "id": view["id"], "name": view["name"], "route": view["route"],
                "dtstart": view["dtstart"], "dtend": view["dtend"],
                "status": view["status"], "participant_count": view["participant_count"],
                "calendar_uid": race.get("calendar_uid"), "source": race.get("source"),
            })
        return out
    finally:
        conn.close()


@app.get("/api/bummel/race/{race_id}")
async def get_bummel_race_endpoint(race_id: int):
    """Öffentliche Sicht eines Rennens — redigiert (keine Zeiten) bis zur Enthüllung, abgeschlossen
    aus dem Snapshot (#66)."""
    now = datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(get_settings().DB_PATH)
    try:
        update_bummel_reveals(conn, now, callsign_prefix=get_settings().CALLSIGN_PREFIX)
        race = get_bummel_race(conn, race_id)
        if not race:
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        return _bummel_view(conn, race, now)
    finally:
        conn.close()


def _fmt_de_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return d.strftime("%d.%m.%Y")
    except Exception:
        return ""


# Render-Version der Forum-Badges. Fließt in den ETag/Cache-Schlüssel von Kutter- UND Bummel-
# Badge ein: Ändert sich NUR das Layout/Rendering (nicht die Daten), bleibt der datenbasierte
# Hash sonst gleich und Browser/Forum zeigen per 304 das alte Bild. Bei jeder sichtbaren
# Layout-Änderung an app/badge.py hochzählen — dann holen alle Clients frisch.
_BADGE_RENDER_VERSION = "3"  # v8.8.1: Team-Tonnage + Footer-Layout-Fix (Kutter-Badge)


def _badge_entry_data(view: dict, race: dict, cid: int) -> tuple[dict, bool]:
    """Render-Daten + Sieger-Flag für einen Teilnehmer aus einer (enthüllten) Renn-Sicht.

    Wirft 404, wenn die CID nicht teilgenommen hat.
    """
    complete = {e["cid"]: e for e in view.get("complete", [])}
    incomplete = {e["cid"]: e for e in view.get("incomplete", [])}
    entry = complete.get(cid) or incomplete.get(cid)
    if not entry:
        raise HTTPException(status_code=404, detail="Teilnehmer nicht gefunden")
    is_winner = cid in complete and entry.get("rank") == 1
    d = {
        "callsign": entry.get("callsign") or f"CID {cid}",
        "name": entry.get("name") or "",
        "aircraft": entry.get("aircraft") or "",  # Badge setzt ASCII-Platzhalter (Pillow-Tofu)
        "total_min": entry.get("total_min"),
        "delta": entry.get("delta"),
        "delta_sec": entry.get("delta_sec"),
        "rank": entry.get("rank"),
        "complete": cid in complete,
        "event": race.get("name") or "FriesenFliegerBummel",
        "date": _fmt_de_date(race.get("dtstart")),
    }
    return d, is_winner


def _render_badge(d: dict, is_winner: bool) -> bytes:
    """Badge-PNG erzeugen (Sieger groß, sonst Medaille)."""
    from app.badge import render_medal, render_winner_badge
    return render_winner_badge(d) if is_winner else render_medal(d)


@app.get("/api/bummel/race/{race_id}/badge/{cid}.png")
async def get_bummel_badge(request: Request, race_id: int, cid: int):
    """Forum-Badge (PNG) für einen Teilnehmer — Sieger groß, sonst Medaille. Erst nach Enthüllung."""
    import hashlib
    import os

    now = datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        update_bummel_reveals(conn, now, callsign_prefix=settings.CALLSIGN_PREFIX)
        race = get_bummel_race(conn, race_id)
        if not race:
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        view = _bummel_view(conn, race, now)
        if not view.get("revealed"):
            raise HTTPException(status_code=404, detail="Ergebnisse noch nicht enthüllt")
        d, is_winner = _badge_entry_data(view, race, cid)
    finally:
        conn.close()

    # Hash über alle ergebnisrelevanten Felder. Dient (a) als Datei-Cache-Schlüssel und (b) als
    # ETag: Ändert sich der Sieger (z. B. durch Admin-Override oder eine Wertungsänderung), ändert
    # sich der ETag → der Browser/das Forum holt ein frisches Bild statt eines veralteten.
    key = hashlib.md5(
        f"v{_BADGE_RENDER_VERSION}|{race.get('revealed_at')}|{is_winner}|{d['total_min']}|"
        f"{d.get('delta_sec')}|{d['aircraft']}|{d['callsign']}|{d.get('event')}".encode()
    ).hexdigest()[:10]
    etag = f'"{key}"'
    # no-cache erzwingt Revalidierung; passt der ETag noch, antwortet der Server mit 304 (kein
    # erneuter Download), sonst mit dem frischen Bild.
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    cache_dir = os.path.join(os.path.dirname(settings.DB_PATH) or ".", "badges")
    path = os.path.join(cache_dir, f"{race_id}_{cid}_{key}.png")
    try:
        with open(path, "rb") as fh:
            png = fh.read()
    except OSError:
        png = _render_badge(d, is_winner)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(png)
        except OSError:
            pass  # Cache optional — Bild wurde bereits erzeugt
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-cache", "ETag": etag})


@app.get("/api/admin/bummel/races/{race_id}/badge/{cid}.png")
async def admin_bummel_badge(request: Request, race_id: int, cid: int):
    """Badge-Vorschau für den Admin — funktioniert auch VOR der Enthüllung, immer frisch gerendert."""
    require_admin(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        race = get_bummel_race(conn, race_id)
        if not race:
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        view = _build_race_view(conn, race, _now_iso(), force_reveal=True)
        d, is_winner = _badge_entry_data(view, race, cid)
    finally:
        conn.close()
    png = _render_badge(d, is_winner)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/bummel/active")
async def get_bummel_active():
    """Aktuell laufendes/wartendes Rennen für das Live-Banner — sonst null.

    Liefert die öffentliche (redigierte) Sicht; Zeiten/Schnitt erst nach Enthüllung. Ein bereits
    enthülltes Rennen erscheint hier nicht mehr (Ergebnisse dann im Events-Tab).
    """
    now = datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(get_settings().DB_PATH)
    try:
        update_bummel_reveals(conn, now, callsign_prefix=get_settings().CALLSIGN_PREFIX)
        active = next(
            (
                r for r in list_bummel_races(conn)
                if not r.get("revealed_at")
                and (r.get("dtstart") or "") <= now
                and r.get("route")
            ),
            None,
        )
        if not active:
            return None
        return _build_race_view(conn, active, now)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admin-Auth (signiertes Cookie via SECRET_KEY) — schützt /api/admin/*
# ---------------------------------------------------------------------------

_ADMIN_COOKIE_PATH = "/api/admin"

# Einfacher In-Process-Brute-Force-Schutz: max. N Fehlversuche je IP im Zeitfenster → 429.
# Reicht für ein Einzel-Admin-Tool (ein uvicorn-Worker); resettet bei Neustart.
_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW_SEC = 60.0
_login_fails: dict[str, list[float]] = {}


def _login_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _login_fails.get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
    _login_fails[ip] = recent
    return len(recent) >= _LOGIN_MAX_FAILS


def require_admin(request: Request) -> None:
    """FastAPI-Dependency: wirft 401, wenn kein gültiges Admin-Cookie vorliegt."""
    settings = get_settings()
    token = request.cookies.get(ADMIN_COOKIE, "")
    if not verify_admin_token(token, settings.SECRET_KEY, settings.ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Admin-Login erforderlich")


@app.post("/api/admin/login")
async def admin_login(request: Request):
    """Admin-Login per Passwort → setzt ein signiertes httponly-Cookie.

    Mit Brute-Force-Bremse (Rate-Limit je IP) und secure-Cookie hinter HTTPS.
    """
    ip = request.client.host if request.client else "?"
    if _login_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Zu viele Fehlversuche — bitte später erneut.")
    body = await request.json()
    settings = get_settings()
    if not check_password(body.get("password", ""), settings.ADMIN_PASSWORD):
        _login_fails.setdefault(ip, []).append(time.monotonic())
        _logger.warning("Admin-Login fehlgeschlagen von %s", ip)
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    _login_fails.pop(ip, None)  # Erfolg → Zähler zurücksetzen
    token = make_admin_token(settings.SECRET_KEY, settings.ADMIN_PASSWORD)
    # secure nur hinter HTTPS (nginx setzt X-Forwarded-Proto); lokal über HTTP weiterhin nutzbar.
    is_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp = JSONResponse({"status": "ok"})
    resp.set_cookie(
        ADMIN_COOKIE, token, httponly=True, secure=is_https, samesite="lax",
        path=_ADMIN_COOKIE_PATH, max_age=60 * 60 * 24,
    )
    return resp


@app.post("/api/admin/logout")
async def admin_logout():
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(ADMIN_COOKIE, path=_ADMIN_COOKIE_PATH)
    return resp


@app.get("/api/admin/me")
async def admin_me(request: Request):
    """Prüft, ob der Client als Admin eingeloggt ist (fürs Frontend)."""
    require_admin(request)
    return {"admin": True}


# ---------------------------------------------------------------------------
# Admin: Banner-/Hinweis-Verwaltung
# ---------------------------------------------------------------------------

@app.get("/api/admin/banner")
async def admin_get_banner(request: Request):
    """Aktuelle Banner-Auswahl + alle Changelog-Einträge (für die Admin-Auswahl)."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        selected = get_app_setting(conn, "banner_version", "auto")
    finally:
        conn.close()
    entries = [
        {"version": e.get("version"), "date": e.get("date", ""),
         "title": e.get("title", ""), "highlight": bool(e.get("highlight"))}
        for e in CHANGELOG
    ]
    return {"selected": selected, "entries": entries}


@app.get("/api/admin/gps-leg-audit")
async def admin_gps_leg_audit(
    request: Request, days: int = 30, cid: int | None = None, statsim: int = 0
):
    """Read-only Audit: vergleicht die Refile-Flüge mit der collapsed GPS-Sicht aus
    :func:`app.database.canonicalize_legs` (GPS-only Phase 2, #23, Task 6). Rechnet on-demand,
    schreibt nichts — liefert die Kennzahlen von :func:`app.database.audit_gps_vs_refile`.

    ``days`` (1..365) spannt das Fenster ``[jetzt-days, jetzt]``; ``cid`` schränkt optional
    auf einen Piloten ein. ``statsim`` (0..500) hängt zusätzlich die GPS-Leg-Interpretation der
    jüngsten N StatSim-Flüge an (in-memory aus ``statsim_position_history``, nichts gespeichert).
    Rein additiv/lesend: fasst ``flights``/Wertungen nicht an.
    """
    require_admin(request)
    settings = get_settings()
    days = max(1, min(365, int(days)))
    now = datetime.now(_timezone.utc)
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(settings.DB_PATH)
    try:
        flights = canonicalize_flights(
            conn, start=start, end=end, callsign_prefix=settings.CALLSIGN_PREFIX
        )
        scope_cids = sorted({
            f["cid"] for f in flights
            if f.get("source") == "friesenspy" and f.get("cid") is not None
        })
        if cid is not None:
            # Explizit auf diesen Piloten einschränken (auch wenn er gar keine Flüge hat).
            scope_cids = [cid]
            audit_cids: list[int] | None = [cid]
        else:
            audit_cids = scope_cids or None

        result = audit_gps_vs_refile(
            conn,
            cids=audit_cids,
            start=start,
            end=end,
            callsign_prefix=settings.CALLSIGN_PREFIX,
            statsim_sample=max(0, min(500, int(statsim))),
        )
    finally:
        conn.close()
    return result


@app.post("/api/admin/banner")
async def admin_set_banner(request: Request):
    """Banner-Auswahl setzen: ``auto`` | ``off`` | konkrete Version."""
    require_admin(request)
    body = await request.json()
    version = str(body.get("version", "auto")).strip() or "auto"
    conn = get_connection(get_settings().DB_PATH)
    try:
        set_app_setting(conn, "banner_version", version)
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "selected": version, "resolved": _resolve_banner_version(version)}


# ---------------------------------------------------------------------------
# Admin: Push (Test ans eigene Gerät + Broadcast) & Piloten-Verwaltung
# ---------------------------------------------------------------------------

@app.post("/api/admin/push/test")
async def admin_push_test(request: Request):
    """Test-Benachrichtigung NUR an das angegebene (eigene) Gerät senden.

    Der Browser meldet seinen eigenen Push-Endpoint; es wird ausschließlich an genau diese
    eine Subscription gesendet — nie an andere Friesen.
    """
    require_admin(request)
    settings = get_settings()
    if not settings.VAPID_PRIVATE_KEY:
        raise HTTPException(status_code=400, detail="VAPID nicht konfiguriert")
    body = await request.json()
    endpoint = str(body.get("endpoint", "")).strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint erforderlich")
    conn = get_connection(settings.DB_PATH)
    try:
        sub = get_push_subscription_by_endpoint(conn, endpoint)
    finally:
        conn.close()
    if not sub:
        raise HTTPException(status_code=404, detail="Bitte zuerst in der App Push aktivieren.")
    # Titel/Text aus dem Broadcast-Formular als Vorschau übernehmen; sonst Standard-Testtext.
    title = str(body.get("title", "")).strip() or "FriesenSpy Test ✅"
    text = str(body.get("body", "")).strip() or "Test-Benachrichtigung vom Admin."
    payload = {"title": title, "body": text, "url": "/"}
    await send_web_push(
        settings.VAPID_PRIVATE_KEY, settings.VAPID_CONTACT_EMAIL, settings.DB_PATH,
        [sub], payload, label="Admin-Test",
    )
    return {"status": "ok", "sent": 1}


@app.post("/api/admin/push/broadcast")
async def admin_push_broadcast(request: Request):
    """Freie Nachricht (Titel + Text) als Push an eine wählbare Zielgruppe senden."""
    require_admin(request)
    settings = get_settings()
    if not settings.VAPID_PRIVATE_KEY:
        raise HTTPException(status_code=400, detail="VAPID nicht konfiguriert")
    body = await request.json()
    title = str(body.get("title", "")).strip()
    text = str(body.get("body", "")).strip()
    audience = str(body.get("audience", "all")).strip()
    if not title or not text:
        raise HTTPException(status_code=400, detail="title und body erforderlich")
    conn = get_connection(settings.DB_PATH)
    try:
        subs = (get_push_subscriptions_for_events(conn) if audience == "events"
                else get_all_push_subscriptions(conn))
    finally:
        conn.close()
    if subs:
        payload = {"title": title, "body": text, "url": "/"}
        await send_web_push(
            settings.VAPID_PRIVATE_KEY, settings.VAPID_CONTACT_EMAIL, settings.DB_PATH,
            subs, payload, label=f"Admin-Broadcast({audience})",
        )
    return {"status": "ok", "audience": audience, "sent": len(subs)}


@app.get("/api/admin/pilots")
async def admin_list_pilots(request: Request):
    """Bekannte Piloten (cid, name, added_at, callsigns) für die Admin-Verwaltung."""
    require_admin(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        return list_pilots(conn, callsign_prefix=settings.CALLSIGN_PREFIX)
    finally:
        conn.close()


@app.post("/api/admin/pilots")
async def admin_upsert_pilot(request: Request):
    """Pilot anlegen oder Namen aktualisieren ({cid, name})."""
    require_admin(request)
    body = await request.json()
    try:
        cid = int(body.get("cid"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Gültige CID erforderlich")
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name erforderlich")
    conn = get_connection(get_settings().DB_PATH)
    try:
        upsert_pilot(conn, cid, name)
        conn.commit()
        return {"status": "ok", "cid": cid, "name": name}
    finally:
        conn.close()


@app.delete("/api/admin/pilots/{cid}")
async def admin_delete_pilot(request: Request, cid: int):
    """Pilot aus der pilots-Tabelle entfernen."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        delete_pilot(conn, cid)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admin: Bummel-Rennverwaltung (alle geschützt via require_admin)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/api/admin/bummel/races")
async def admin_list_races(request: Request):
    """Volle Renn-Liste für die Admin-Seite (inkl. Status, Overrides, Push-Schalter)."""
    require_admin(request)
    now = _now_iso()
    conn = get_connection(get_settings().DB_PATH)
    try:
        out = []
        for race in list_bummel_races(conn):
            out.append({
                **race,
                "status": _race_status(race, now),
                "overrides": list_bummel_overrides(conn, race["id"]),
            })
        return out
    finally:
        conn.close()


@app.get("/api/admin/bummel/races/{race_id}/preview")
async def admin_preview_race(request: Request, race_id: int):
    """Volle Standings (mit Overrides) — auch während des laufenden Rennens (Admin vertraut)."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        race = get_bummel_race(conn, race_id)
        if not race:
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        return _build_race_view(conn, race, _now_iso(), force_reveal=True)
    finally:
        conn.close()


@app.post("/api/admin/bummel/races")
async def admin_create_race(request: Request):
    """Manuelles Rennen anlegen (ohne Kalender)."""
    require_admin(request)
    body = await request.json()
    route = ",".join(c.strip().upper() for c in str(body.get("route", "")).replace(" ", ",").split(",") if c.strip())
    if len(route.split(",")) < 2 or not body.get("dtstart"):
        raise HTTPException(status_code=400, detail="route (≥2 ICAOs) und dtstart erforderlich")
    conn = get_connection(get_settings().DB_PATH)
    try:
        rid = create_bummel_race(
            conn,
            name=body.get("name") or "FriesenFliegerBummel",
            route=route,
            dtstart=body["dtstart"],
            dtend=body.get("dtend") or "",
        )
        conn.commit()
        return {"status": "ok", "id": rid}
    finally:
        conn.close()


@app.post("/api/admin/bummel/races/{race_id}")
async def admin_update_race(request: Request, race_id: int):
    """Renn-Felder bearbeiten (name/route/dtstart/dtend)."""
    require_admin(request)
    body = await request.json()
    fields = {k: body[k] for k in ("name", "route", "dtstart", "dtend") if k in body}
    conn = get_connection(get_settings().DB_PATH)
    try:
        if not get_bummel_race(conn, race_id):
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        if fields:
            update_bummel_race(conn, race_id, **fields)
        # Unbedingt (auch bei leerem Body) — "Rennen antippen + speichern" ist der bewusste
        # manuelle Neuberechnungs-Hebel für ein bereits eingefrorenes Rennen (#66 Task 7).
        delete_progress_snapshot(conn, "bummel", race_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/admin/bummel/races/{race_id}")
async def admin_delete_race(request: Request, race_id: int):
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        delete_bummel_race(conn, race_id)
        delete_progress_snapshot(conn, "bummel", race_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/bummel/races/{race_id}/reveal")
async def admin_reveal_race(request: Request, race_id: int):
    """Notfall-Enthüllung: Ergebnisse sofort sichtbar machen — und (einmalig) Ergebnis-Push
    an die Events-Abonnenten, wie beim automatischen Enthüllen."""
    require_admin(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        race = get_bummel_race(conn, race_id)
        if not race:
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        was_revealed = bool(race.get("revealed_at"))
        force_bummel_revealed(conn, race_id, _now_iso())
        set_bummel_reveal_suppressed(conn, race_id, False)  # manuelles Enthüllen hebt Verbergen auf
        conn.commit()
        # Push nur beim ERSTEN Enthüllen (latchend) + wenn fürs Rennen erlaubt + VAPID gesetzt.
        if not was_revealed and race.get("push_enabled") and settings.VAPID_PRIVATE_KEY:
            subs = get_push_subscriptions_for_events(conn)
            if subs:
                from app.poller import send_web_push
                payload = {"title": race.get("name") or "FriesenFliegerBummel",
                           "body": "Die Bummel-Ergebnisse sind da! 🏁", "url": "/"}
                asyncio.create_task(send_web_push(
                    settings.VAPID_PRIVATE_KEY, settings.VAPID_CONTACT_EMAIL, settings.DB_PATH,
                    subs, payload, label="Bummel-Reveal(admin)",
                ))
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/bummel/races/{race_id}/hide")
async def admin_hide_race(request: Request, race_id: int):
    """Wieder verbergen / neu starten (revealed_at zurücksetzen).

    Bei einem bereits abgelaufenen Rennen würde der Auto-Reveal-Job (``update_bummel_reveals``)
    es sonst binnen einer Minute wieder enthüllen — deshalb wird es zusätzlich dauerhaft
    unterdrückt (``reveal_suppressed``). Ein noch laufendes Rennen wird nur verborgen und am
    regulären Ende normal automatisch enthüllt.
    """
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        race = get_bummel_race(conn, race_id)
        force_bummel_revealed(conn, race_id, None)
        if race and (race.get("dtend") or "") and _now_iso() >= race["dtend"]:
            set_bummel_reveal_suppressed(conn, race_id, True)
        delete_progress_snapshot(conn, "bummel", race_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/bummel/races/{race_id}/push")
async def admin_toggle_push(request: Request, race_id: int):
    """Push-Benachrichtigungen für dieses Rennen ein-/ausschalten."""
    require_admin(request)
    body = await request.json()
    conn = get_connection(get_settings().DB_PATH)
    try:
        set_bummel_push_enabled(conn, race_id, bool(body.get("enabled")))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/bummel/races/{race_id}/override")
async def admin_set_override(request: Request, race_id: int):
    """Teilnehmer-Korrektur setzen: action ∈ exclude|disqualify|winner|manual."""
    require_admin(request)
    body = await request.json()
    action = body.get("action")
    if action not in ("exclude", "disqualify", "winner", "manual"):
        raise HTTPException(status_code=400, detail="action muss exclude|disqualify|winner|manual sein")
    cid = body.get("cid")
    if cid is None:
        raise HTTPException(status_code=400, detail="cid erforderlich")
    conn = get_connection(get_settings().DB_PATH)
    try:
        upsert_bummel_override(
            conn, race_id, int(cid), action,
            manual_total_min=body.get("manual_total_min"),
            note=body.get("note"),
        )
        delete_progress_snapshot(conn, "bummel", race_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/admin/bummel/races/{race_id}/override/{cid}")
async def admin_delete_override(request: Request, race_id: int, cid: int):
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        delete_bummel_override(conn, race_id, cid)
        delete_progress_snapshot(conn, "bummel", race_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# FriesenKutter — Transportflug-Events (öffentlich + Admin)
# ---------------------------------------------------------------------------

def _normalize_route(raw: str) -> str:
    """Freitext ('EDWG EDWA EDWA' / 'edwg,edxh') → normalisierte, **deduplizierte** ICAO-CSV.
    Reihenfolge bleibt erhalten (beim Bummel ist die Strecke eine Sequenz); Trenner Komma,
    Semikolon ODER Leerzeichen; leere Teile entfallen."""
    out: list[str] = []
    for c in str(raw or "").replace(";", ",").replace(" ", ",").split(","):
        c = c.strip().upper()
        if c and c not in out:
            out.append(c)
    return ",".join(out)


def _transport_event_meta(ev: dict, progress: dict) -> dict:
    """Event-Metadaten + kompakter Fortschritt (ohne den vollen Flug-Feed) für Listen."""
    return {
        "id": ev["id"], "name": ev["name"], "route": ev["route"],
        "destination": ev.get("destination"), "dtstart": ev["dtstart"], "dtend": ev["dtend"],
        "source": ev.get("source"), "calendar_uid": ev.get("calendar_uid"),
        "total_kg": progress["total_kg"], "target_kg": progress["target_kg"],
        "progress_pct": progress["progress_pct"], "flight_count": progress["flight_count"],
        "loaded_count": progress["loaded_count"], "cargo": progress["cargo"],
        "reserved_total_kg": progress.get("reserved_total_kg", 0.0),
        "lost_total_kg": progress.get("lost_total_kg", 0.0),
    }


def _retention_since(now: str) -> str:
    """Anzeige-Grenze für öffentliche Listen-Endpoints: ``now`` − ``_DATA_RETENTION_DAYS`` Tage
    (#66/#67, ISO-Z). Reine Anzeigegrenze — nichts wird gelöscht."""
    from app.database import _DATA_RETENTION_DAYS
    dt = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_timezone.utc)
    return (dt - timedelta(days=_DATA_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_retention_days(days: int) -> int:
    """Zeitraum-Parameter auf die globale Anzeigegrenze klemmen (#67): 1 … ``_DATA_RETENTION_DAYS``.
    Ältere Daten bleiben in der DB (Cleanup ist deaktiviert), werden aber nicht angezeigt."""
    from app.database import _DATA_RETENTION_DAYS
    return max(1, min(days, _DATA_RETENTION_DAYS))


def _clamp_retention_start(start: str, now: str) -> str:
    """Events-Startgrenze (#67): kein Start älter als ``now`` − ``_DATA_RETENTION_DAYS``. Ein leerer
    oder zu alter Start wird auf die Grenze angehoben — die älteren Daten existieren weiterhin,
    sind aber nicht durchsuchbar. String-Vergleich ist gültig (beide ISO-Z, gleiche Länge)."""
    floor = _retention_since(now)
    return floor if (not start or start < floor) else start


def _frozen_or_compute(conn, kind: str, ref_id: int, *, finished: bool, compute_fn, now: str) -> dict:
    """Gemeinsamer Zugriffs-Helfer Kutter/Bummel (#66 §3): ein abgeschlossenes Event/Rennen wird
    aus dem Snapshot bedient (Lazy-Freeze beim ersten Read, falls noch keiner existiert);
    ein aktives wird immer live gerechnet."""
    if finished:
        snap = get_progress_snapshot(conn, kind, ref_id)
        if snap is not None:
            return snap
        result = compute_fn()
        write_progress_snapshot(conn, kind, ref_id, result, now)
        conn.commit()
        return result
    return compute_fn()


def _kutter_progress(conn, ev: dict, now: str, prefix: str) -> dict:
    """Fortschritt eines Kutter-Events: eingefroren (abgeschlossen) oder live, danach frische
    Überlagerung der NICHT eingefrorenen Felder — KI-Sprüche entstehen erst NACH dem
    ``summarized_at``-Latch (Summary danach, Pro-Flug-Quips async), s. Spec §3."""
    finished = bool(ev.get("summarized_at"))
    progress = _frozen_or_compute(
        conn, "kutter", ev["id"], finished=finished, now=now,
        compute_fn=lambda: compute_transport_progress(
            conn, ev, now, callsign_prefix=prefix, skip_open_probe=finished),
    )
    progress = dict(progress)
    progress["summary_quip"] = ev.get("summary_quip")
    quips = get_transport_quips(conn, ev["id"])
    if quips:
        for f in progress.get("flights", []):
            q = quips.get(f.get("flight_key"))
            if q:
                f["quip"] = q
    return progress


@app.get("/api/transport/events")
async def transport_events():
    """Alle FriesenKutter-Events (Kalender + manuell) mit kompaktem Fortschritt — letzte
    ``_DATA_RETENTION_DAYS`` Tage (#67), abgeschlossene Events aus dem Snapshot (#66)."""
    now = _now_iso()
    conn = get_connection(get_settings().DB_PATH)
    try:
        prefix = get_settings().CALLSIGN_PREFIX
        return [
            _transport_event_meta(ev, _kutter_progress(conn, ev, now, prefix))
            for ev in list_transport_events(conn, since=_retention_since(now))
        ]
    finally:
        conn.close()


@app.get("/api/transport/event/{event_id}")
async def transport_event_detail(event_id: int):
    """Voller Zustand eines Events: Zielbalken (cargo) + chronologischer Flug-Feed — abgeschlossen
    aus dem Snapshot, aktiv live (#66)."""
    now = _now_iso()
    conn = get_connection(get_settings().DB_PATH)
    try:
        ev = get_transport_event(conn, event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Event nicht gefunden")
        progress = _kutter_progress(conn, ev, now, get_settings().CALLSIGN_PREFIX)
        # unmapped_types nur für Admin relevant — aus der öffentlichen Sicht entfernen.
        progress.pop("unmapped_types", None)
        return {
            "id": ev["id"], "name": ev["name"], "route": ev["route"],
            "destination": ev.get("destination"), "dtstart": ev["dtstart"], "dtend": ev["dtend"],
            "source": ev.get("source"), "summarized_at": ev.get("summarized_at"), **progress,
        }
    finally:
        conn.close()


def _kutter_badge_data(progress: dict, ev: dict, cid: int) -> dict:
    """Render-Daten für einen Kutter-Badge aus einer bereits berechneten
    ``compute_transport_progress``-Sicht. Wirft 404, wenn die CID nicht teilgenommen hat.

    Verlust-kg pro Art (geklaut/versenkt) werden aus ``progress["losses"]`` für die CID
    aufsummiert — ``returned`` (ehrlich zurückgebracht) zählt dabei NICHT als Verlust.
    """
    entry = next((p for p in progress.get("participants", []) if p["cid"] == cid), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Teilnehmer nicht gefunden")
    stolen_kg = sum(
        l.get("lost_kg") or 0.0 for l in progress.get("losses", [])
        if l.get("cid") == cid and l.get("loss_kind") == "stolen"
    )
    sunk_kg = sum(
        l.get("lost_kg") or 0.0 for l in progress.get("losses", [])
        if l.get("cid") == cid and l.get("loss_kind") == "sunk"
    )
    return {
        "callsign": entry.get("callsign") or f"CID {cid}",
        "name": entry.get("name") or "",
        "aircraft": entry.get("aircraft") or "",  # Badge setzt ASCII-Platzhalter (Pillow-Tofu)
        "delivered_kg": entry.get("delivered_kg") or 0.0,
        "stolen_kg": round(stolen_kg, 1),
        "sunk_kg": round(sunk_kg, 1),
        # Gesamt-Tonnage des EVENTS (Teamleistung, nicht nur dieser Pilot) — Nutzer-Wunsch
        # 06.07.: der Kutter ist eine gemeinsame Leistung, das Badge soll sie feiern.
        "team_total_kg": round(progress.get("total_kg") or 0.0, 1),
        "team_target_kg": round(progress.get("target_kg") or 0.0, 1) if progress.get("target_kg") else None,
        "event": ev.get("name") or "FriesenKutter",
        "date": _fmt_de_date(ev.get("dtstart")),
    }


def _render_kutter_badge(d: dict) -> bytes:
    from app.badge import render_kutter_badge
    return render_kutter_badge(d)


@app.get("/api/transport/event/{event_id}/badge/{cid}.png")
async def get_transport_badge(request: Request, event_id: int, cid: int):
    """Forum-Badge (PNG) für einen Kutter-Teilnehmer — erst nach der Feierabend-Bilanz
    (``summarized_at``), damit kein Zwischenstand als "fertig" verewigt wird."""
    import hashlib
    import os

    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        ev = get_transport_event(conn, event_id)
        if not ev or not ev.get("summarized_at"):
            raise HTTPException(status_code=404, detail="Event noch nicht abgeschlossen")
        progress = _kutter_progress(conn, ev, _now_iso(), settings.CALLSIGN_PREFIX)
        d = _kutter_badge_data(progress, ev, cid)
    finally:
        conn.close()

    # Hash über alle ergebnisrelevanten Felder — dient (a) als Datei-Cache-Schlüssel und (b) als
    # ETag (analog Bummel-Badge): ändert sich die Bilanz nachträglich, ändert sich der ETag.
    key = hashlib.md5(
        f"v{_BADGE_RENDER_VERSION}|{ev.get('summarized_at')}|{d['delivered_kg']}|{d['stolen_kg']}|"
        f"{d['sunk_kg']}|{d['aircraft']}|{d['callsign']}|{d.get('event')}|{d['team_total_kg']}".encode()
    ).hexdigest()[:10]
    etag = f'"{key}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

    cache_dir = os.path.join(os.path.dirname(settings.DB_PATH) or ".", "badges")
    path = os.path.join(cache_dir, f"kutter_{event_id}_{cid}_{key}.png")
    try:
        with open(path, "rb") as fh:
            png = fh.read()
    except OSError:
        png = _render_kutter_badge(d)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(png)
        except OSError:
            pass  # Cache optional — Bild wurde bereits erzeugt
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-cache", "ETag": etag})


@app.get("/api/admin/transport/events/{event_id}/badge/{cid}.png")
async def admin_transport_badge(request: Request, event_id: int, cid: int):
    """Badge-Vorschau für den Admin — funktioniert auch VOR der Feierabend-Bilanz, immer frisch
    gerendert (kein Cache)."""
    require_admin(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        ev = get_transport_event(conn, event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Event nicht gefunden")
        progress = _kutter_progress(conn, ev, _now_iso(), settings.CALLSIGN_PREFIX)
        d = _kutter_badge_data(progress, ev, cid)
    finally:
        conn.close()
    png = _render_kutter_badge(d)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/admin/transport/events")
async def admin_transport_events(request: Request):
    """Admin-Liste: Events inkl. Fracht-Manifest (zum Bearbeiten)."""
    require_admin(request)
    now = _now_iso()
    conn = get_connection(get_settings().DB_PATH)
    try:
        return [
            {**ev, "status": _transport_status(ev, now), "cargo": get_transport_cargo(conn, ev["id"])}
            for ev in list_transport_events(conn)
        ]
    finally:
        conn.close()


def _validate_transport_manifest(destination: str, cargo: list) -> str | None:
    """#84: ein manuelles Kutter-Event verlangt ein Ziel + ein Manifest mit Startplätzen je Ware.
    Gibt eine Fehlermeldung zurück oder ``None``. Jede Fracht-Zeile (Name + Menge > 0) braucht
    mind. einen Startplatz ≠ Ziel; ohne solche Zeile wäre die abgeleitete Route nur das Ziel und
    kein Flug zählte."""
    from app.database import _normalize_icao_list
    if not destination:
        return "Ziel-ICAO erforderlich."
    # Genau EIN Ziel — mehrere würden als ein kaputter Code gespeichert und die Zählung still
    # verfälschen (mehrere Ziele sind bewusst nicht unterstützt).
    dest_codes = _normalize_icao_list(destination)
    if dest_codes and "," in dest_codes:
        return "Nur ein Ziel-ICAO erlaubt (mehrere Ziele werden nicht unterstützt)."
    rows = 0
    for line in (cargo or []):
        name = (line.get("name") or "").strip()
        try:
            kg = float(line.get("target_kg"))
        except (TypeError, ValueError):
            continue
        if not name or kg <= 0:
            continue
        rows += 1
        if not _normalize_icao_list(line.get("departure"), exclude=destination):
            return f"Frachtart „{name}“ braucht mindestens einen Startplatz (nicht das Ziel)."
    if rows == 0:
        return "Mindestens eine Frachtart mit Menge erforderlich."
    return None


@app.post("/api/admin/transport/events")
async def admin_create_transport_event(request: Request):
    """Manuelles Transportevent anlegen (Ziel, Zeitfenster, Manifest mit Startplätzen je Ware).
    #84: keine Strecke mehr — die Route wird aus den Startplätzen der Fracht + Ziel abgeleitet."""
    require_admin(request)
    body = await request.json()
    dest = str(body.get("destination") or "").strip().upper()
    if not body.get("dtstart"):
        raise HTTPException(status_code=400, detail="dtstart erforderlich")
    err = _validate_transport_manifest(dest, body.get("cargo") or [])
    if err:
        raise HTTPException(status_code=400, detail=err)
    conn = get_connection(get_settings().DB_PATH)
    try:
        eid = create_transport_event(
            conn,
            name=body.get("name") or "FriesenKutter",
            destination=dest,
            dtstart=body["dtstart"],
            dtend=body.get("dtend") or None,
            cargo=body.get("cargo") or None,
        )
        conn.commit()
        return {"status": "ok", "id": eid}
    finally:
        conn.close()


@app.post("/api/admin/transport/events/{event_id}")
async def admin_update_transport_event(request: Request, event_id: int):
    """Event bearbeiten (name/destination/dtstart/dtend/cargo). cargo ersetzt das Manifest.
    #84: keine Strecke mehr — die Route wird aus den Startplätzen abgeleitet."""
    require_admin(request)
    body = await request.json()
    fields: dict = {}
    for k in ("name", "dtstart", "dtend"):
        if k in body:
            fields[k] = body[k]
    if "destination" in body:
        fields["destination"] = str(body.get("destination") or "").strip().upper()
    if "cargo" in body:
        fields["cargo"] = body["cargo"]
    conn = get_connection(get_settings().DB_PATH)
    try:
        cur = get_transport_event(conn, event_id)
        if not cur:
            raise HTTPException(status_code=404, detail="Event nicht gefunden")
        # #84: wird das Manifest geändert, gegen das (ggf. neue) Ziel validieren.
        if "cargo" in body:
            dest = fields.get("destination", cur.get("destination")) or ""
            err = _validate_transport_manifest(dest, body["cargo"])
            if err:
                raise HTTPException(status_code=400, detail=err)
        if fields:
            update_transport_event(conn, event_id, **fields)
        # Unbedingt (auch bei leerem Body) — "Event antippen + speichern" ist der bewusste
        # manuelle Neuberechnungs-Hebel für ein bereits eingefrorenes Event (#66 Task 7).
        delete_progress_snapshot(conn, "kutter", event_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/transport/events/{event_id}/push")
async def admin_toggle_transport_push(request: Request, event_id: int):
    """Push-Benachrichtigungen für dieses Transport-Event ein-/ausschalten."""
    require_admin(request)
    body = await request.json()
    conn = get_connection(get_settings().DB_PATH)
    try:
        set_transport_push_enabled(conn, event_id, bool(body.get("enabled")))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/admin/transport/events/{event_id}")
async def admin_delete_transport_event(request: Request, event_id: int):
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        delete_transport_event(conn, event_id)
        delete_progress_snapshot(conn, "kutter", event_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.get("/api/admin/transport/payloads")
async def admin_transport_payloads(request: Request):
    """Zuladungs-Tabelle + globaler Default + beobachtete, noch nicht gepflegte Flugzeugtypen."""
    require_admin(request)
    now = _now_iso()
    conn = get_connection(get_settings().DB_PATH)
    try:
        prefix = get_settings().CALLSIGN_PREFIX
        unmapped: set[str] = set()
        for ev in list_transport_events(conn):
            p = _kutter_progress(conn, ev, now, prefix)
            unmapped.update(p.get("unmapped_types") or [])
        return {
            "payloads": list_aircraft_payloads(conn),
            "unmapped_types": sorted(unmapped),
            "default_kg": transport_default_payload_kg(conn),
            "llm_configured": _llm_configured(),
            "quips_enabled": transport_quips_enabled(conn),
        }
    finally:
        conn.close()


@app.post("/api/admin/transport/payloads")
async def admin_upsert_payload(request: Request):
    """Zuladungs-Zeile speichern: type_code + Komponenten (mtow/empty/fuel) und/oder payload_kg."""
    require_admin(request)
    body = await request.json()
    type_code = str(body.get("type_code") or "").strip()
    if not type_code:
        raise HTTPException(status_code=400, detail="type_code erforderlich")

    def _num(key):
        v = body.get(key)
        try:
            return float(v) if v is not None and str(v) != "" else None
        except (TypeError, ValueError):
            return None

    conn = get_connection(get_settings().DB_PATH)
    try:
        upsert_payload(
            conn, type_code,
            payload_kg=_num("payload_kg"), mtow_kg=_num("mtow_kg"),
            empty_kg=_num("empty_kg"), fuel_kg=_num("fuel_kg"), crew_kg=_num("crew_kg"),
            source="manual", make_model=(body.get("make_model") or None),
        )
        # Zuladungs-Änderung wirkt auf ALLE Kutter-Events (#66 Task 7) — global invalidieren.
        delete_progress_snapshots(conn, "kutter")
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.get("/api/admin/transport/payloads/suggest")
async def admin_transport_payload_suggest(request: Request, type: str):
    """KI-Vorschlag (Claude) für die Zuladungs-Komponenten eines Flugzeugtyps."""
    require_admin(request)
    from app import llm
    if not llm.is_configured():
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY nicht konfiguriert")
    # Blockierender Sonnet-5-Aufruf (Web-Search, bis zu ~1-2 Min.) — in einen Thread auslagern,
    # sonst haengt die Event-Loop und damit die GESAMTE App fuer die Dauer der Recherche.
    suggestion = await asyncio.to_thread(llm.suggest_aircraft_payload, type)
    if suggestion is None:
        raise HTTPException(status_code=502, detail="Kein Vorschlag verfügbar")
    return suggestion


@app.post("/api/admin/transport/default-payload")
async def admin_set_default_payload(request: Request):
    """Globalen Fallback-Zuladungswert (kg) für ungepflegte Flugzeugtypen setzen."""
    require_admin(request)
    body = await request.json()
    try:
        value = float(body.get("default_kg"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="default_kg (Zahl) erforderlich")
    conn = get_connection(get_settings().DB_PATH)
    try:
        set_app_setting(conn, "transport_default_payload_kg", str(value))
        # Globaler Fallback wirkt auf ALLE Kutter-Events (#66 Task 7) — global invalidieren.
        delete_progress_snapshots(conn, "kutter")
        conn.commit()
        return {"status": "ok", "default_kg": value}
    finally:
        conn.close()


def _reload_custom_airports_geo_cache(conn) -> None:
    """Nach jedem Admin-Write auf custom_airports: geo-Cache neu befüllen (Invalidierung =
    Neuaufruf) — billig, läuft synchron im Request."""
    geo.set_custom_airports(list_custom_airports(conn))


def _rebuild_flight_cache_background(db_path: str) -> None:
    """Voller flight_cache-Rebuild (v8.6.2) als Hintergrund-Task NACH der Response — der
    inkrementelle Refresh (#30, `_FLIGHT_CACHE_INCREMENTAL_DAYS`) fasst nur die letzten 7 Tage
    an, ein neuer/geänderter Platz muss aber auch ältere, bislang fälschlich offene Flüge neu
    erkennen lassen (#50). `canonicalize_legs(conn)` ohne Fenster ist teuer (mehrere Sekunden bei
    >3000 StatSim-Flügen) — läuft daher NICHT mehr blockierend im Request (Fund: Admin-Speichern/
    -Löschen fühlte sich dadurch eingefroren an). Eigene, frische DB-Connection: die des
    Endpoints ist zu diesem Zeitpunkt bereits geschlossen (FastAPI führt BackgroundTasks NACH
    dem Response-Close aus). Die Erkennungslücken-Prüfliste ist von dieser Verzögerung nicht
    betroffen, da sie `canonicalize_legs` ohnehin live und unabhängig vom flight_cache aufruft."""
    conn = get_connection(db_path)
    try:
        rebuild_flight_cache(conn, full=True)
    finally:
        conn.close()


@app.get("/api/admin/airports")
async def admin_get_airports(request: Request):
    """Alle Ergänzungs-Flugplätze (Plätze, die in airportsdata fehlen)."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        return {"airports": list_custom_airports(conn)}
    finally:
        conn.close()


@app.post("/api/admin/airports")
async def admin_upsert_airport(request: Request, background_tasks: BackgroundTasks):
    """Ergänzungs-Flugplatz speichern: icao (Pflicht), lat/lon/name/elevation_ft/radius_km optional.

    #56: ``override`` (optional, Body-Feld) erlaubt bewusstes Überschreiben eines bereits in
    airportsdata bekannten Codes — nötig, weil airportsdata selbst falsche Koordinaten führen
    kann (Fund: EBUL/Ursel Air Base ~15 km daneben). Ohne ``override`` bleibt die Plausiprüfung
    (#50) als Schutz gegen versehentliche Duplikate aktiv (409, damit das Frontend zwischen
    „echter Fehler" (400) und „Bestätigung nötig" (409) unterscheiden kann).

    #62: lat/lon dürfen leer bleiben, wenn der Code bereits irgendwo bekannt ist (Custom-Eintrag
    ODER airportsdata) — dann werden die bereits bekannten Koordinaten übernommen. Das erlaubt
    einen reinen Radius-Override (``radius_km``, z. B. für Großflughäfen wie EHAM, deren
    Abhebepunkt weiter als der Standardradius vom Referenzpunkt entfernt liegen kann), ohne
    Koordinaten erneut eintippen zu müssen, die man selbst gar nicht genau kennt. Ist der Code
    nirgends bekannt, bleiben lat/lon Pflicht (400).
    """
    require_admin(request)
    body = await request.json()
    icao = str(body.get("icao") or "").strip()
    if not icao:
        raise HTTPException(status_code=400, detail="icao erforderlich")
    override = bool(body.get("override"))
    if not override and geo.is_known_in_airportsdata(icao):
        known_coords = geo.icao_to_coords(icao)
        coords_txt = f" (dort: {known_coords[0]}, {known_coords[1]})" if known_coords else ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"{icao.upper()} ist bereits in airportsdata bekannt{coords_txt} — "
                "mit override bewusst überschreiben?"
            ),
        )
    lat_raw, lon_raw = body.get("lat"), body.get("lon")
    if lat_raw in (None, "") and lon_raw in (None, ""):
        known_coords = geo.icao_to_coords(icao)
        if known_coords is None:
            raise HTTPException(
                status_code=400,
                detail="lat/lon erforderlich (Code ist nirgends mit bekannten Koordinaten hinterlegt)",
            )
        lat, lon = known_coords
    else:
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="lat/lon (Zahlen) erforderlich")
    elev_raw = body.get("elevation_ft")
    if elev_raw is None or str(elev_raw) == "":
        elevation_ft = geo.airport_elevation_ft(icao)
    else:
        try:
            elevation_ft = float(elev_raw)
        except (TypeError, ValueError):
            elevation_ft = None
    radius_raw = body.get("radius_km")
    radius_km: float | None = None
    if radius_raw not in (None, ""):
        try:
            radius_km = float(radius_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="radius_km muss eine Zahl sein")
        if radius_km <= 0:
            raise HTTPException(status_code=400, detail="radius_km muss > 0 sein")

    conn = get_connection(get_settings().DB_PATH)
    try:
        upsert_custom_airport(
            conn, icao, name=(body.get("name") or None), lat=lat, lon=lon,
            elevation_ft=elevation_ft, radius_km=radius_km,
        )
        conn.commit()
        _reload_custom_airports_geo_cache(conn)
        background_tasks.add_task(_rebuild_flight_cache_background, get_settings().DB_PATH)
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/admin/airports/{icao}")
async def admin_delete_airport(icao: str, request: Request, background_tasks: BackgroundTasks):
    """Löscht einen Ergänzungs-Flugplatz."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        delete_custom_airport(conn, icao)
        conn.commit()
        _reload_custom_airports_geo_cache(conn)
        background_tasks.add_task(_rebuild_flight_cache_background, get_settings().DB_PATH)
        return {"status": "ok"}
    finally:
        conn.close()


@app.get("/api/admin/detection-gaps")
async def admin_get_detection_gaps(request: Request):
    """Flüge mit fehlendem GPS-Start/-Landung trotz bekanntem Flugplan — Kandidaten für
    fehlende custom_airports-Einträge (v8.6.0)."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        return {"gaps": list_gps_detection_gaps(conn)}
    finally:
        conn.close()


@app.post("/api/admin/detection-gaps/dismiss")
async def admin_dismiss_detection_gap(request: Request):
    """Markiert einen einzelnen Flug dauerhaft als „kein Datenfehler" (Absturz,
    Recording-Lücke) — verschwindet aus der Prüfliste, unabhängig vom Flugplatz-Code."""
    require_admin(request)
    body = await request.json()
    cid = body.get("cid")
    logon_time = body.get("logon_time")
    if cid is None or not logon_time:
        raise HTTPException(status_code=400, detail="cid und logon_time erforderlich")
    conn = get_connection(get_settings().DB_PATH)
    try:
        dismiss_gps_detection_gap(conn, int(cid), str(logon_time))
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.get("/api/admin/transport/catalog")
async def admin_transport_catalog(request: Request):
    """Frachtart-Katalog (Stammdaten) auflisten."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        return list_cargo_catalog(conn)
    finally:
        conn.close()


@app.post("/api/admin/transport/catalog")
async def admin_upsert_catalog(request: Request):
    """Frachtart im Katalog anlegen/ändern: name (Pflicht), emoji, per_flight_max_kg, id (für Update)."""
    require_admin(request)
    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name erforderlich")
    conn = get_connection(get_settings().DB_PATH)
    try:
        upsert_cargo_catalog(
            conn, id=body.get("id"), name=name,
            emoji=(body.get("emoji") or None), per_flight_max_kg=body.get("per_flight_max_kg"),
        )
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/admin/transport/catalog/{catalog_id}")
async def admin_delete_catalog(request: Request, catalog_id: int):
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        delete_cargo_catalog(conn, catalog_id)
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.post("/api/admin/transport/quips-enabled")
async def admin_set_quips_enabled(request: Request):
    """Lustige KI-Sprüche global an-/ausschalten."""
    require_admin(request)
    body = await request.json()
    enabled = bool(body.get("enabled"))
    conn = get_connection(get_settings().DB_PATH)
    try:
        set_app_setting(conn, "transport_quips_enabled", "1" if enabled else "0")
        conn.commit()
        return {"status": "ok", "enabled": enabled}
    finally:
        conn.close()


@app.post("/api/admin/transport/events/{event_id}/regenerate-quips")
async def admin_regenerate_transport_quips(event_id: int, request: Request):
    """Gecachte KI-Sprüche eines Events löschen → der Poller baut sie beim nächsten Durchlauf
    (~60 s) neu, mit der aktuellen Spruch-Logik. Nötig, wenn ein bereits generierter Spruch
    veraltet ist (z. B. Liefer-Text für einen inzwischen als geklaut/versunken erkannten Flug)."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        cleared = clear_transport_quips(conn, event_id)
        conn.commit()
        return {"status": "ok", "cleared": cleared}
    finally:
        conn.close()


def _llm_configured() -> bool:
    try:
        from app import llm
        return llm.is_configured()
    except Exception:  # noqa: BLE001
        return False


@app.get("/widget/preview", include_in_schema=False)
async def widget_preview():
    """Vorschau-Seite für das Widget — zeigt iframe + Einbettungscode."""
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>FriesenSpy Widget – Vorschau</title>
<style>
  body{background:#d0e0f0;color:#053080;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;padding:32px;max-width:640px;margin:0 auto}
  h1{color:#053080;font-size:1.1rem;margin-bottom:4px;font-weight:700}
  p{font-size:0.85rem;color:#104090;margin-bottom:20px}
  .preview-box{border:1px solid rgba(5,48,128,0.3);padding:12px;background:rgba(255,255,255,0.5);margin-bottom:24px;border-radius:4px}
  .preview-label{font-size:0.7rem;color:#5577aa;margin-bottom:8px;letter-spacing:0.08em;text-transform:uppercase;font-weight:600}
  iframe{width:100%;min-height:88px;border:none;display:block}
  .code-box{background:#fff;border:1px solid rgba(5,48,128,0.25);padding:12px;font-size:0.75rem;overflow-x:auto;white-space:pre;color:#053080;border-radius:4px;cursor:pointer;position:relative;font-family:'Courier New',monospace}
  .copy-hint{position:absolute;top:8px;right:10px;font-size:0.65rem;color:#5577aa}
  .copied{color:#053080!important;font-weight:700}
  .note{font-size:0.75rem;color:#5577aa;margin-top:12px;line-height:1.6}
  a{color:#D31141}
</style>
</head>
<body>
<h1>✈ FriesenSpy Widget</h1>
<p>So sieht das Widget auf einer Webseite aus — aktualisiert sich automatisch alle 60 Sekunden.</p>
<div class="preview-box">
  <div class="preview-label">Vorschau</div>
  <iframe id="w-preview" src="/widget" scrolling="no"></iframe>
</div>
<div class="preview-label" style="margin-bottom:8px">Einbettungscode (klicken zum Kopieren)</div>
<div class="code-box" onclick="copyCode(this)" title="Klicken zum Kopieren">
<span class="copy-hint" id="hint">📋 kopieren</span>&lt;iframe
  src="https://friesenspy.devprops.de/widget"
  width="420" height="140"
  style="border:none;"
  scrolling="no"&gt;&lt;/iframe&gt;</div>
<div class="note">
  Die Höhe (<code>height</code>) ggf. anpassen — mit eingereichten Flugplänen wird das Widget höher.<br>
  ⚠ phpBB (unser Forum) erlaubt standardmäßig keine iframes in Beiträgen — der Code funktioniert nur auf externen Webseiten (z.B. friesenflieger.de).<br>
  Direkter Link zum Widget: <a href="/widget">friesenspy.devprops.de/widget</a>
</div>
<script>
// Vorschau-iframe (same-origin) automatisch an den Inhalt anpassen, damit auch die
// "geplant:"-Zeile (Flugpläne) und der TS-Zähler vollständig sichtbar sind.
const _wf = document.getElementById('w-preview');
function _fitPreview() {
  try {
    const h = _wf.contentWindow.document.body.scrollHeight;
    if (h) _wf.style.height = h + 'px';
  } catch (e) { /* same-origin sollte klappen; sonst min-height-Fallback */ }
}
_wf.addEventListener('load', _fitPreview);  // initial + bei jedem 60s-Auto-Refresh des Widgets
setInterval(_fitPreview, 5000);             // fängt Inhalts-Reflow (neue Prefiles) zwischendurch ab
function copyCode(el) {
  const code = `<iframe\\n  src="https://friesenspy.devprops.de/widget"\\n  width="420" height="140"\\n  style="border:none;"\\n  scrolling="no"></iframe>`;
  navigator.clipboard.writeText(code).then(() => {
    const h = document.getElementById('hint');
    h.textContent = '✓ kopiert';
    h.className = 'copy-hint copied';
    setTimeout(() => { h.textContent = '📋 kopieren'; h.className = 'copy-hint'; }, 2000);
  });
}
</script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})


@app.get("/widget", include_in_schema=False)
async def widget(request: Request):
    """Einbettbares iframe-Widget für friesenflieger.de."""
    from fastapi.responses import HTMLResponse
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        live = get_live_positions(conn)
        stats = get_stats(conn, days=7, callsign_prefix=settings.CALLSIGN_PREFIX)
    finally:
        conn.close()

    poller: VatsimPoller = request.app.state.poller
    prefiles = poller.last_prefiles
    ts_count = len(poller.ts_clients)
    ts_badge = (
        f'<span class="badge ts-badge">🎧&nbsp;{ts_count}&nbsp;im&nbsp;TS</span>'
        if settings.TS_NOTIFY_ENABLED else ''
    )

    total_min = sum(s.get("total_duration_min", 0) for s in stats)
    total_h = total_min / 60
    pilots_html = " &nbsp;·&nbsp; ".join(
        f'<span>{_html.escape(str(p.get("callsign") or p.get("name") or "?"))}</span>'
        for p in live
    ) if live else '<span class="none">Niemand online</span>'

    prefile_html = ""
    if prefiles:
        import re as _re
        def _widget_prefile_item(p: dict) -> str:
            fp = p.get("flight_plan") or {}
            callsign = p.get("callsign", "?")
            dep = fp.get("departure", "?")
            arr = fp.get("arrival", "?")
            deptime = fp.get("deptime", "")
            remarks = fp.get("remarks", "") or ""
            dof_m = _re.search(r'DOF/(\d{2})(\d{2})(\d{2})', remarks)
            date_s = f"{dof_m.group(3)}.{dof_m.group(2)}." if dof_m else ""
            time_s = f"{deptime[:2]}:{deptime[2:]}z" if len(deptime) == 4 else ""
            when = " ".join(filter(None, [date_s, time_s]))
            when_html = f'&nbsp;<span class="muted-time">{_html.escape(when)}</span>' if when else ""
            return (
                f'<span>{_html.escape(callsign)}'
                f'&nbsp;<span class="muted">{_html.escape(dep)}→{_html.escape(arr)}</span>'
                f'{when_html}</span>'
            )
        items = " &nbsp;·&nbsp; ".join(_widget_prefile_item(p) for p in prefiles)
        prefile_html = f'<div class="pf">geplant:&nbsp;{items}</div>'

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="60">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#d0e0f0;color:#053080;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:12px}}
  a{{color:inherit;text-decoration:none;display:block}}
  .hd{{background:#053080;color:#fff;padding:4px 10px;font-size:12px;font-weight:700;display:flex;align-items:center;gap:8px}}
  .hd-title{{flex:1}}
  .badge{{background:#D31141;color:#fff;padding:1px 6px;font-size:10px;font-weight:700;border-radius:2px}}
  .ts-badge{{background:#0a7a3a}}
  .bd{{padding:5px 10px 4px}}
  .none{{color:#5577aa}}
  .muted{{color:#5577aa}}
  .pf{{font-size:10px;color:#104090;margin-top:2px}}
  .muted-time{{color:#5577aa;font-size:9px}}
  .ft{{font-size:10px;color:#104090;margin-top:4px;border-top:1px solid rgba(5,48,128,0.2);padding-top:3px}}
</style>
</head>
<body>
<a href="https://friesenspy.devprops.de" target="_blank">
  <div class="hd">
    <span class="hd-title">✈ FriesenSpy</span>
    <span class="badge">{len(live)}&nbsp;online</span>
    {ts_badge}
  </div>
  <div class="bd">
    <div>{pilots_html}</div>
    {prefile_html}
    <div class="ft">Flugstunden der letzten 7&nbsp;Tage:&nbsp;{total_h:.1f}&nbsp;h&nbsp;·&nbsp;FriesenSpy.devprops.de</div>
  </div>
</a>
</body>
</html>"""
    return HTMLResponse(
        content=html,
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"},
    )
