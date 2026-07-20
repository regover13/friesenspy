"""FriesenSpy FastAPI-App — REST-Endpoints + SSE-Stream."""
from __future__ import annotations

import asyncio
import hmac
import html as _html
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from datetime import timezone as _timezone
from urllib.parse import quote

import httpx as _httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from app.auth import (
    ADMIN_COOKIE,
    CONFIRM_COOKIE,
    check_password,
    make_admin_token,
    make_confirm_token,
    verify_admin_token,
    verify_confirm_token,
)
from app.config import get_settings
from app.forum_sso import (
    USER_COOKIE,
    make_user_token,
    verify_sso_token,
    verify_user_token,
)
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
    get_push_overview,
    list_visibility_restrictions,
    get_app_setting,
    get_calendar_events,
    get_connection,
    get_push_subscription_by_endpoint,
    get_pilot_visibility,
    set_pilot_visibility,
    set_push_subscription_owner,
    upsert_forum_callsign,
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
    clear_transport_summarized,
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
    if settings.SSO_SECRET and settings.SSO_SECRET == settings.SECRET_KEY:
        _logger.warning(
            "SSO_SECRET == SECRET_KEY — bitte UNTERSCHIEDLICHE Geheimnisse verwenden "
            "(Token-Trennung greift zwar über das typ-Feld, gleiche Secrets sind aber unsauber)."
        )
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


# Pfade, die auch bei aktivem Gate IMMER erreichbar bleiben (Login-Flow, Break-glass,
# Rechtstexte, PWA-Assets, Health).
_GATE_ALLOW_PREFIXES = (
    "/auth/", "/static/", "/health", "/robots.txt", "/favicon",
    "/impressum", "/datenschutz", "/admin", "/api/admin/",
    "/manifest", "/sw.js", "/api/me", "/widget",
)

# Break-glass-Kopie des Admin-Cookies auf ``path=/`` — das eigentliche Admin-Cookie liegt auf
# ``/api/admin`` und würde vom Browser für ``/`` nie mitgesendet (Fable-Review F1).
_SITE_ADMIN_COOKIE = "fs_admin_site"


def _request_is_authenticated(request: Request, settings) -> bool:
    if verify_user_token(request.cookies.get(USER_COOKIE, ""), settings.SECRET_KEY):
        return True
    # Break-glass: gültiges Admin-Cookie (path=/) zählt auch als eingeloggt.
    if verify_admin_token(request.cookies.get(_SITE_ADMIN_COOKIE, ""),
                          settings.SECRET_KEY, settings.ADMIN_PASSWORD):
        return True
    return False


@app.middleware("http")
async def forum_login_gate(request: Request, call_next):
    """Bei aktivem Board-Login: nicht-eingeloggte Anfragen abweisen (HTML → Login-Redirect,
    sonst 401). Ohne Schalter/Secrets völlig inaktiv (Default), daher kein Einfluss im Normalbetrieb."""
    path = request.url.path
    # Öffentliche Badge-PNGs (in Foren-Beiträge eingebettet) bleiben auch bei aktivem Gate
    # erreichbar — Cross-Site-<img> sendet das SameSite=Lax-Cookie sonst nicht mit.
    if not path.startswith(_GATE_ALLOW_PREFIXES) and "/badge/" not in path:
        settings = get_settings()
        if _forum_login_active_cached(settings) and not _request_is_authenticated(request, settings):
            wants_html = request.method == "GET" and "text/html" in request.headers.get("accept", "")
            if wants_html:
                return RedirectResponse("/auth/forum/login", status_code=302)
            return JSONResponse({"detail": "Login erforderlich"}, status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


# HTML-Einstiegsseiten NICHT heuristisch cachen lassen: sonst sieht ein Nutzer nach einem
# Deploy weiter das alte index.html (mit frischen API-Daten, aber altem Markup/JS) — genau der
# „neue Version im Changelog, aber neuer Button fehlt“-Effekt. `no-cache` erzwingt eine
# Revalidierung bei jedem Aufruf; dank ETag/Last-Modified von FileResponse ist das billig (304).
_HTML_NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
async def index():
    return FileResponse("app/static/index.html", headers=_HTML_NO_CACHE)


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """Admin-Seite (Login-Formular + Bummel-Rennverwaltung). Schutz erfolgt über die
    /api/admin/*-Endpoints (Cookie); diese Seite selbst ist statisch."""
    return FileResponse("app/static/admin.html", headers=_HTML_NO_CACHE)


@app.get("/impressum", include_in_schema=False)
async def impressum_page():
    """Impressum (§ 5 DDG) — statische Seite."""
    return FileResponse("app/static/impressum.html", headers=_HTML_NO_CACHE)


@app.get("/datenschutz", include_in_schema=False)
async def datenschutz_page():
    """Datenschutzerklärung (Art. 13 DSGVO) — statische Seite."""
    return FileResponse("app/static/datenschutz.html", headers=_HTML_NO_CACHE)


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
            owner_cid=_current_cid(request, settings),   # nur aus dem Cookie, nie aus dem Body
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
    """Aktuell laufende Flüge (logoff_time IS NULL) auf einem Strecken-Leg.

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

# Step-up-Bestätigung für kritische Aktionen (Löschen, Push/Veröffentlichen): nach einmaliger
# Passworteingabe gilt ein Zeitfenster, in dem keine erneute Passwortabfrage nötig ist (der
# Bestätigungsdialog erscheint trotzdem weiterhin bei jeder kritischen Aktion, nur ohne Feld).
_CONFIRM_TTL_SEC = 2 * 60 * 60

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
    """FastAPI-Dependency: wirft 401, wenn keine Admin-Berechtigung vorliegt.

    Zwei Wege gelten als Admin:
    1. Forum-SSO-Session (``fs_user``) mit ``is_admin`` — Mitglied der Forum-Gruppe „Events".
    2. Passwort-Admin-Cookie (``fs_admin``) — Fallback/Break-glass, wenn keine Events-Gruppe
       erkannt wird (Board-Login aus, Forum-Ausfall, Nicht-Events-Admin).
    """
    settings = get_settings()
    claims = verify_user_token(request.cookies.get(USER_COOKIE, ""), settings.SECRET_KEY)
    if claims and claims.get("is_admin"):
        return
    if verify_admin_token(request.cookies.get(ADMIN_COOKIE, ""), settings.SECRET_KEY, settings.ADMIN_PASSWORD):
        return
    raise HTTPException(status_code=401, detail="Admin-Login erforderlich")


def require_admin_page(request: Request) -> None:
    """Admin-Prüfung für HTML-Seiten AUSSERHALB von ``/api/admin``.

    ``require_admin`` prüft ``fs_admin`` — das liegt auf ``path=/api/admin`` und wird für eine
    Seite unter ``/admin/...`` vom Browser nie mitgesendet. Hier zählt deshalb die
    Break-glass-Kopie ``fs_admin_site`` (``path=/``) oder eine Forum-Session mit Admin-Recht.
    """
    settings = get_settings()
    claims = verify_user_token(request.cookies.get(USER_COOKIE, ""), settings.SECRET_KEY)
    if claims and claims.get("is_admin"):
        return
    if verify_admin_token(request.cookies.get(_SITE_ADMIN_COOKIE, ""),
                          settings.SECRET_KEY, settings.ADMIN_PASSWORD):
        return
    raise HTTPException(status_code=401, detail="Admin-Login erforderlich")


def require_confirm(request: Request) -> None:
    """Step-up-Dependency für kritische Aktionen (Löschen, Push/Veröffentlichen).

    Setzt ``require_admin`` voraus (Aufrufer prüft das zuerst) und verlangt zusätzlich ein
    frisches Bestätigungs-Token (``fs_confirm``), das der Nutzer über ``/api/admin/confirm``
    durch erneute Passworteingabe erhält. Fehlt/abgelaufen → 403 mit ``confirm_required``,
    worauf das Frontend die Passwortabfrage zeigt und die Aktion wiederholt.
    """
    settings = get_settings()
    token = request.cookies.get(CONFIRM_COOKIE, "")
    if verify_confirm_token(token, settings.SECRET_KEY, settings.ADMIN_PASSWORD, int(time.time())):
        return
    raise HTTPException(status_code=403, detail="confirm_required")


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
    # Break-glass-Kopie auf path=/ — damit ein eingeloggter Admin die App auch bei aktivem
    # Board-Login (und Forum-Ausfall) ohne Forum-Login sehen kann (Fable-Review F1).
    resp.set_cookie(
        _SITE_ADMIN_COOKIE, token, httponly=True, secure=is_https, samesite="lax",
        path="/", max_age=60 * 60 * 24,
    )
    return resp


@app.post("/api/admin/confirm")
async def admin_confirm(request: Request):
    """Step-up-Bestätigung: prüft das Passwort erneut und setzt ein kurzlebiges Confirm-Cookie.

    Danach sind kritische Aktionen (Löschen, Push/Veröffentlichen) für ``_CONFIRM_TTL_SEC``
    Sekunden ohne erneute Abfrage möglich. Nutzt dieselbe IP-Brute-Force-Bremse wie der Login.
    """
    require_admin(request)  # nur eingeloggte Admins dürfen bestätigen
    ip = request.client.host if request.client else "?"
    if _login_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Zu viele Fehlversuche — bitte später erneut.")
    body = await request.json()
    settings = get_settings()
    if not check_password(body.get("password", ""), settings.ADMIN_PASSWORD):
        _login_fails.setdefault(ip, []).append(time.monotonic())
        _logger.warning("Admin-Bestätigung fehlgeschlagen von %s", ip)
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    _login_fails.pop(ip, None)
    expires_at = int(time.time()) + _CONFIRM_TTL_SEC
    token = make_confirm_token(settings.SECRET_KEY, settings.ADMIN_PASSWORD, expires_at)
    is_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp = JSONResponse({"status": "ok", "ttl": _CONFIRM_TTL_SEC})
    resp.set_cookie(
        CONFIRM_COOKIE, token, httponly=True, secure=is_https, samesite="lax",
        path=_ADMIN_COOKIE_PATH, max_age=_CONFIRM_TTL_SEC,
    )
    return resp


@app.post("/api/admin/logout")
async def admin_logout():
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(ADMIN_COOKIE, path=_ADMIN_COOKIE_PATH)
    resp.delete_cookie(_SITE_ADMIN_COOKIE, path="/")
    resp.delete_cookie(CONFIRM_COOKIE, path=_ADMIN_COOKIE_PATH)
    return resp


@app.get("/api/admin/me")
async def admin_me(request: Request):
    """Prüft, ob der Client als Admin eingeloggt ist (fürs Frontend)."""
    require_admin(request)
    return {"admin": True}


# ---------------------------------------------------------------------------
# Forum-SSO (Board-Login) — Schalter, Helfer, Endpoints
# ---------------------------------------------------------------------------

# Gate-Aktiv-Status mit kurzem TTL cachen (Middleware läuft pro Request, auch für Assets).
_gate_cache: dict[str, float | bool] = {"val": False, "ts": 0.0}
_GATE_TTL_SEC = 5.0


def _reset_gate_cache() -> None:
    """Cache verwerfen — nach jedem Schalter-Wechsel (und in Tests) aufrufen."""
    _gate_cache["ts"] = 0.0


def _forum_sso_configured(settings) -> bool:
    """True, wenn alle Bridge-Secrets gesetzt sind. ``getattr`` mit Default, damit die
    global laufende Gate-Middleware auch mit knapp gemockten Settings (Tests) nicht bricht."""
    return bool(getattr(settings, "SSO_SECRET", "") and getattr(settings, "FORUM_SSO_URL", "")
                and getattr(settings, "FORUM_SSO_CALLBACK", ""))


def _forum_login_active(conn, settings) -> bool:
    """True nur, wenn die Bridge konfiguriert ist UND der Admin-Schalter AN steht."""
    if not _forum_sso_configured(settings):
        return False
    return get_app_setting(conn, "forum_login_enabled", "0") == "1"


def _forum_login_active_cached(settings) -> bool:
    # Ohne konfigurierte Bridge gar nicht erst die DB anfassen (Default-/Normalbetrieb).
    if not _forum_sso_configured(settings):
        return False
    now = time.monotonic()
    if now - float(_gate_cache["ts"]) > _GATE_TTL_SEC:
        conn = get_connection(settings.DB_PATH)
        try:
            _gate_cache["val"] = get_app_setting(conn, "forum_login_enabled", "0") == "1"
        finally:
            conn.close()
        _gate_cache["ts"] = now
    return bool(_gate_cache["val"])


def _current_cid(request: Request, settings) -> int | None:
    """CID des eingeloggten Forum-Nutzers oder None.

    Das Login-Gate schützt ``/api/me/*`` NICHT (steht in der Allowlist) — diese Prüfung im
    Endpoint ist die alleinige Verteidigung. Bei ausgeschaltetem Board-Login zählt ein evtl. noch
    gültiges ``fs_user``-Cookie NICHT (Gleichlauf mit ``/api/me``). Die CID kommt als String aus
    einem freien phpBB-Profilfeld → trimmen, auf Ziffern prüfen, zu int. Break-glass-Admin ohne
    CID / Tippfehler-CID → None.
    """
    if not _forum_login_active_cached(settings):
        return None
    claims = verify_user_token(request.cookies.get(USER_COOKIE, ""), settings.SECRET_KEY)
    if not claims:
        return None
    raw = str(claims.get("cid", "")).strip()
    return int(raw) if raw.isdigit() else None


@app.get("/api/admin/forum-login")
async def admin_get_forum_login(request: Request):
    """Board-Login-Status für die Admin-Oberfläche."""
    require_admin(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        enabled = get_app_setting(conn, "forum_login_enabled", "0") == "1"
    finally:
        conn.close()
    return {"enabled": enabled, "configured": _forum_sso_configured(settings)}


@app.post("/api/admin/forum-login")
async def admin_set_forum_login(request: Request):
    """Board-Login an-/ausschalten (Admin)."""
    require_admin(request)
    require_confirm(request)
    body = await request.json()
    enabled = bool(body.get("enabled"))
    conn = get_connection(get_settings().DB_PATH)
    try:
        set_app_setting(conn, "forum_login_enabled", "1" if enabled else "0")
        conn.commit()
    finally:
        conn.close()
    _reset_gate_cache()
    return {"status": "ok", "enabled": enabled}


# Einmal-Nonce-Store gegen Replay des eingehenden SSO-Tokens (In-Process, TTL = Token-Frische).
_used_sso_nonces: dict[str, float] = {}


def _consume_sso_nonce(nonce: str) -> bool:
    """True beim ERSTEN Sehen eines Nonce; False, wenn schon verbraucht. Prunt alte Einträge."""
    from app.forum_sso import SSO_TOKEN_MAX_AGE_SEC
    now = time.monotonic()
    for k, t in list(_used_sso_nonces.items()):
        if now - t > SSO_TOKEN_MAX_AGE_SEC + 5:
            _used_sso_nonces.pop(k, None)
    if not nonce or nonce in _used_sso_nonces:
        return False
    _used_sso_nonces[nonce] = now
    return True


def _is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def _safe_next_path(raw: str) -> str | None:
    """Sanitize a post-login redirect target to a SEITENINTERNEN Pfad (kein Open-Redirect).

    Erlaubt nur Pfade, die mit genau EINEM ``/`` beginnen (keine ``//host``- oder
    ``/\\host``-Protokoll-relativen URLs) und keine Steuer-/Whitespace-Zeichen enthalten
    (Header-Injection). Alles andere → ``None`` (Aufrufer nimmt dann den Default ``/``)."""
    if not raw or not raw.startswith("/") or raw.startswith(("//", "/\\")):
        return None
    if any(c.isspace() for c in raw):
        return None
    return raw


@app.get("/auth/forum/login")
async def forum_login(request: Request):
    """Startet den Board-Login: Redirect zur Forum-Bridge mit state + Callback.

    Ein optionaler ``next``-Parameter (seiteninterner Pfad) merkt sich, wohin nach erfolgreichem
    Login zurückgeleitet wird — z. B. ``/admin``, wenn der Login auf der Admin-Seite gestartet
    wurde. Er wird kurzlebig als Cookie mitgeführt (wie ``state``) und im Callback ausgewertet."""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        active = _forum_login_active(conn, settings)
    finally:
        conn.close()
    if not active:
        return RedirectResponse("/", status_code=302)
    state = secrets.token_urlsafe(24)
    target = (f"{settings.FORUM_SSO_URL}?redirect={quote(settings.FORUM_SSO_CALLBACK, safe='')}"
              f"&state={quote(state, safe='')}")
    resp = RedirectResponse(target, status_code=302)
    resp.set_cookie("fs_sso_state", state, httponly=True, secure=_is_https(request),
                    samesite="lax", path="/auth/forum", max_age=300)
    next_path = _safe_next_path(request.query_params.get("next", ""))
    if next_path:
        resp.set_cookie("fs_sso_next", next_path, httponly=True, secure=_is_https(request),
                        samesite="lax", path="/auth/forum", max_age=300)
    return resp


@app.get("/auth/forum/callback")
async def forum_callback(request: Request):
    """Nimmt das signierte Token der Bridge entgegen → eigene FriesenSpy-Session."""
    settings = get_settings()
    token = request.query_params.get("token", "")
    state = request.query_params.get("state", "")
    cookie_state = request.cookies.get("fs_sso_state", "")
    if (not state or not cookie_state
            or not hmac.compare_digest(state.encode("utf-8"), cookie_state.encode("utf-8"))):
        raise HTTPException(status_code=400, detail="Ungültiger SSO-Status")
    claims = verify_sso_token(token, settings.SSO_SECRET)
    if claims is None:
        raise HTTPException(status_code=401, detail="Ungültiges SSO-Token")
    if not _consume_sso_nonce(str(claims.get("nonce", ""))):
        raise HTTPException(status_code=401, detail="SSO-Token bereits verwendet")
    exp = time.time() + settings.USER_SESSION_MAX_AGE_SEC
    user_token = make_user_token(
        settings.SECRET_KEY, str(claims.get("name", "")),
        str(claims.get("cid", "")), bool(claims.get("is_admin")), exp,
    )
    # Autoritative Callsign→CID-Map aus dem Forum-Profil (Token v2, Feld `cs`) pflegen —
    # defensiv (nur Liste, nur String-Einträge, plausible Länge) + eigene Alt-Zeilen bereinigen.
    raw_cid = str(claims.get("cid", "")).strip()
    cs_list = claims.get("cs")
    if raw_cid.isdigit() and isinstance(cs_list, list):
        cid_int = int(raw_cid)
        clean: list[str] = []
        for cs in cs_list:
            if isinstance(cs, str):
                v = cs.strip().upper()
                if 0 < len(v) <= 16 and v not in clean:
                    clean.append(v)
        # Callsign-Map ist Nice-to-have: ein DB-Fehler (z. B. „database is locked") darf den
        # Login NICHT scheitern lassen — der nächste Login holt es nach (Fable-Fund F3).
        try:
            conn = get_connection(settings.DB_PATH)
            try:
                for v in clean:
                    upsert_forum_callsign(conn, v, cid_int)
                if clean:
                    placeholders = ",".join("?" * len(clean))
                    conn.execute(
                        f"DELETE FROM forum_callsign WHERE cid = ? AND callsign NOT IN ({placeholders})",
                        (cid_int, *clean),
                    )
                else:
                    # Keine Rufzeichen mehr im Profil → alle Alt-Zeilen dieser CID entfernen (F4).
                    conn.execute("DELETE FROM forum_callsign WHERE cid = ?", (cid_int,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            _logger.warning("forum_callsign-Persistierung fehlgeschlagen (Login läuft weiter)",
                            exc_info=True)
    # Nach erfolgreichem Login zum gemerkten Ziel (z. B. /admin) zurück, sonst zur Startseite.
    dest = _safe_next_path(request.cookies.get("fs_sso_next", "")) or "/"
    resp = RedirectResponse(dest, status_code=302)
    resp.set_cookie(USER_COOKIE, user_token, httponly=True, secure=_is_https(request),
                    samesite="lax", path="/", max_age=settings.USER_SESSION_MAX_AGE_SEC)
    resp.delete_cookie("fs_sso_state", path="/auth/forum")
    resp.delete_cookie("fs_sso_next", path="/auth/forum")
    return resp


@app.get("/auth/forum/logout")
async def forum_logout():
    """Meldet NUR FriesenSpy ab (Forum-Session bleibt)."""
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(USER_COOKIE, path="/")
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    """Login-Status für das Frontend. Nur relevant, wenn der Board-Login aktiv ist — ein evtl.
    noch gültiges ``fs_user``-Cookie zählt NICHT, wenn der Schalter aus (oder nicht konfiguriert)
    ist (sonst zeigt der Name-Chip trotz öffentlicher App weiter einen Namen).

    **Sliding-Session:** Bei gültigem Login wird das ``fs_user``-Cookie mit frischem Ablauf neu
    gesetzt. Weil die SPA ``/api/me`` periodisch pingt, bleibt ein aktiver Tab so eingeloggt,
    ohne alle 20 min unterbrochen zu werden."""
    settings = get_settings()
    if not _forum_login_active_cached(settings):
        return JSONResponse({"logged_in": False, "board_login_active": False})
    claims = verify_user_token(request.cookies.get(USER_COOKIE, ""), settings.SECRET_KEY)
    if not claims:
        return JSONResponse({"logged_in": False, "board_login_active": True})
    resp = JSONResponse({"logged_in": True, "board_login_active": True,
                         "name": claims.get("name", ""), "cid": claims.get("cid", ""),
                         "is_admin": bool(claims.get("is_admin"))})
    exp = time.time() + settings.USER_SESSION_MAX_AGE_SEC
    resp.set_cookie(
        USER_COOKIE,
        make_user_token(settings.SECRET_KEY, str(claims.get("name", "")),
                        str(claims.get("cid", "")), bool(claims.get("is_admin")), exp),
        httponly=True, secure=_is_https(request), samesite="lax", path="/",
        max_age=settings.USER_SESSION_MAX_AGE_SEC,
    )
    return resp


# ---------------------------------------------------------------------------
# Subjekt-Sichtbarkeit — „Wer darf über mich benachrichtigt werden?"
# ---------------------------------------------------------------------------

@app.get("/api/me/visibility")
async def api_me_visibility(request: Request):
    """Aktuelle Sichtbarkeit + Picker-Kandidaten (Mitglieder-Registry). Nur eingeloggt."""
    settings = get_settings()
    cid = _current_cid(request, settings)
    if cid is None:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    conn = get_connection(settings.DB_PATH)
    try:
        vis = get_pilot_visibility(conn, cid) or {
            "mode": "everyone", "allowlist": [], "services": ["online", "prefile", "ts"]}
        # Picker-Kandidaten = AKTIVE Piloten der globalen 365-Tage-Anzeigegrenze (#67) — exakt
        # dieselbe Quelle wie die Benachrichtigungs-Zielliste (/api/stats?days=365), damit beide
        # Picker identisch sind. Ein länger als 365 Tage inaktiver Pilot (z. B. FRS1525) tauchte
        # sonst NUR hier auf (list_pilots kannte die ganze Historie ohne Zeitgrenze).
        pilots = [{"cid": p["cid"], "callsign": p["last_callsign"] or p["name"]}
                  for p in get_stats(conn, days=_DATA_RETENTION_DAYS,
                                     callsign_prefix=settings.CALLSIGN_PREFIX)]
    finally:
        conn.close()
    return {"mode": vis["mode"], "allowlist": vis.get("allowlist", []),
            "services": vis.get("services", ["online", "prefile", "ts"]), "pilots": pilots}


@app.post("/api/me/visibility")
async def api_me_visibility_set(request: Request):
    """Sichtbarkeit setzen (everyone/allowlist/nobody). Nur eingeloggt."""
    settings = get_settings()
    cid = _current_cid(request, settings)
    if cid is None:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    body = await request.json()
    mode = body.get("mode")
    if mode not in ("everyone", "allowlist", "nobody"):
        raise HTTPException(status_code=400, detail="Ungültiger Modus")
    allowlist = None
    if mode == "allowlist":
        # Ganzzahlen filtern, Länge kappen (leere Liste erlaubt = effektiv niemand).
        allowlist = [int(x) for x in (body.get("allowlist") or [])
                     if str(x).lstrip("-").isdigit()][:500]
    # services: für welche Aktivitäten die Einschränkung gilt (nur bei restriktivem Modus).
    services = None
    if mode != "everyone" and body.get("services") is not None:
        services = [s for s in body.get("services") if s in ("online", "prefile", "ts")]
    conn = get_connection(settings.DB_PATH)
    try:
        set_pilot_visibility(conn, cid, mode, allowlist, services)
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "mode": mode}


@app.post("/api/push/claim")
async def api_push_claim(request: Request):
    """Backfill: bestehendes Push-Abo dem eingeloggten Nutzer zuordnen (last-login-wins).
    Anonym → No-op."""
    settings = get_settings()
    cid = _current_cid(request, settings)
    body = await request.json()
    endpoint = body.get("endpoint", "")
    if cid is None or not endpoint:
        return {"status": "skipped"}
    conn = get_connection(settings.DB_PATH)
    try:
        set_push_subscription_owner(conn, endpoint, cid)
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


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
    require_confirm(request)
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
    require_confirm(request)
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


_PUSH_OVERVIEW_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Push-Diagnose</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0e1720;color:#d6e2ee;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;padding:24px;max-width:1100px;margin:0 auto}
  h1{font-size:1.1rem;margin-bottom:4px}
  .sub{color:#6f8296;font-size:.8rem;margin-bottom:20px}
  input{background:#16232f;border:1px solid #2a3d4e;color:#d6e2ee;border-radius:6px;padding:9px 12px;font-size:.95rem;width:220px}
  button{background:#2d9cdb;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:.9rem;cursor:pointer;margin-left:8px}
  button:hover{filter:brightness(1.08)}
  .err{color:#ff6b6b;font-size:.85rem;min-height:1.2em;margin-top:8px}
  .cards{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}
  .card{background:#16232f;border:1px solid #223343;border-radius:8px;padding:10px 14px;min-width:120px}
  .card .n{font-size:1.4rem;font-weight:700}
  .card .l{color:#6f8296;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em}
  h2{font-size:.92rem;margin:22px 0 8px;color:#9fb3c6}
  .table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #223343;border-radius:8px;scrollbar-width:thin;scrollbar-color:#3a4d5e #16232f}
  .table-scroll::-webkit-scrollbar{height:10px}
  .table-scroll::-webkit-scrollbar-thumb{background:#3a4d5e;border-radius:5px}
  table{width:max-content;min-width:100%;border-collapse:collapse;font-size:.83rem}
  th,td{text-align:left;padding:7px 11px;white-space:nowrap;border-bottom:1px solid #1c2b38}
  th{background:#132030;color:#8ea3b6;font-weight:600;position:sticky;top:0}
  td.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
  .muted{color:#6f8296}
  .yes{color:#57c97a}
  .no{color:#3f5266}
  .empty{color:#6f8296;padding:12px;font-size:.85rem}
  .hidden{display:none}
</style>
</head>
<body>
<h1>Push-Diagnose</h1>
<div class="sub">Zugriff nur mit Admin-Login + Extra-Passwort. Kein Beweis, dass Nutzer Meldungen sehen — nur der Zustell-Handshake mit dem Push-Dienst.</div>
<div id="gate">
  <input type="password" id="pw" placeholder="Diagnose-Passwort" autocomplete="off">
  <button id="go">Anzeigen</button>
  <div class="err" id="err"></div>
</div>
<div id="out" class="hidden"></div>
<script>
'use strict';
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function ago(iso){if(!iso)return '';const d=new Date(iso.replace(' ','T'));if(isNaN(d))return esc(iso);const m=Math.floor((Date.now()-d.getTime())/60000);if(m<60)return m+' min';const h=Math.floor(m/60);if(h<48)return h+' h';return Math.floor(h/24)+' d';}
function b(v){return v?'<span class="yes">✔</span>':'<span class="no">–</span>';}
function health(h){return h==='ok'?'🟢':h==='fail'?'🔴':'⚪';}

const gate=document.getElementById('gate'),out=document.getElementById('out'),errEl=document.getElementById('err');

async function load(){
  const pw=document.getElementById('pw').value;
  errEl.textContent='';
  let r;
  try{r=await fetch('/api/admin/push/overview',{headers:{'X-Overview-Pass':pw},credentials:'same-origin'});}
  catch(e){errEl.textContent='Netzwerkfehler.';return;}
  if(r.status===401){errEl.textContent='Falsches Passwort (oder Admin-Login abgelaufen).';return;}
  if(!r.ok){errEl.textContent='Fehler '+r.status+'.';return;}
  const d=await r.json();
  render(d);
  gate.classList.add('hidden');out.classList.remove('hidden');
}

function render(d){
  const t=d.totals;
  const card=(n,l)=>`<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  let h=`<div class="cards">
    ${card(t.abos,'Abos')}
    ${card(t.personen,'Personen')}
    ${card(t.eingeloggt,'eingeloggt')}
    ${card(t.anonym,'anonym')}
    ${card(t.health_ok,'🟢 zugestellt')}
    ${card(t.health_fail,'🔴 fehlerhaft')}
    ${card(t.health_unknown,'⚪ ungesendet')}
  </div>`;
  h+=`<div class="sub">Auswahl-Beliebtheit: Flugpläne ${t.will_prefiles} · TeamSpeak ${t.will_ts} · Events ${t.will_events}${d.vapid_configured?'':' · <span style="color:#ff6b6b">VAPID nicht konfiguriert!</span>'}</div>`;

  h+='<h2>Abos &amp; Auswahl</h2>';
  h+='<div class="sub">„Online“ ist die Grundfunktion und hat keinen Schalter — jedes Abo bekommt sie, '+
     'die Spalte „Piloten“ sagt für wen. Flugpläne und TS sind Zusatz-Optionen für dieselben Piloten. '+
     'Events gilt pauschal, unabhängig von der Piloten-Auswahl.</div>';
  if(!d.subscriptions.length){h+='<div class="empty">Keine Abos.</div>';}
  else{
    h+='<div class="table-scroll"><table><thead><tr>'+
      '<th>Status</th><th>Wer</th><th>Plattform</th><th>Piloten</th>'+
      '<th>Online</th><th>Flugpläne</th><th>TS</th><th>Events</th>'+
      '<th>angelegt</th><th>letzte OK</th><th>letzter Fehler</th></tr></thead><tbody>';
    for(const s of d.subscriptions){
      const who=s.owner_name?esc(s.owner_name):'<span class="muted">anonym</span>';
      const flt=s.pilot_filter.length?esc(s.pilot_filter.join(', ')):'<span class="muted">alle</span>';
      const fail=s.last_fail_at?ago(s.last_fail_at)+(s.last_status?' ('+esc(s.last_status)+')':''):'';
      h+=`<tr><td>${health(s.health)}</td><td>${who}</td><td>${esc(s.platform)}</td><td>${flt}</td>`+
         `<td>${b(true)}</td><td>${b(s.notify_prefiles)}</td><td>${b(s.notify_ts)}</td><td>${b(s.notify_events)}</td>`+
         `<td class="muted">${ago(s.created_at)}</td>`+
         `<td class="muted">${ago(s.last_ok_at)}</td><td class="muted">${fail}</td></tr>`;
    }
    h+='</tbody></table></div>';
  }

  h+='<h2>Piloten mit eingeschränkter Sichtbarkeit</h2>';
  if(!d.suppressed_pilots.length){h+='<div class="empty">Niemand — alle sichtbar für jeden.</div>';}
  else{
    h+='<div class="table-scroll"><table><thead><tr><th>Wer</th><th>Modus</th><th>Erlaubte</th><th>gilt für</th><th>geändert</th></tr></thead><tbody>';
    for(const v of d.suppressed_pilots){
      const allow=v.allowlist.length?esc(v.allowlist.join(', ')):'<span class="muted">niemand</span>';
      const svc=v.services.length?esc(v.services.join(', ')):'<span class="muted">keinen</span>';
      h+=`<tr><td>${esc(v.who)}</td><td>${esc(v.mode)}</td><td>${allow}</td><td>${svc}</td><td class="muted">${ago(v.updated_at)}</td></tr>`;
    }
    h+='</tbody></table></div>';
  }

  out.innerHTML=h;
}

document.getElementById('go').addEventListener('click',load);
document.getElementById('pw').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
document.getElementById('pw').focus();
</script>
</body>
</html>"""


_SERVICE_LABELS = {"online": "Online", "prefile": "Flugplan", "ts": "TeamSpeak"}


def _push_platform(endpoint: str) -> str:
    """Plattform aus dem Push-Endpoint-Host ableiten (kostenlos, kein Tracking)."""
    from urllib.parse import urlparse
    host = (urlparse(endpoint or "").netloc or "").lower()
    if "fcm.googleapis.com" in host or "android.googleapis.com" in host:
        return "Chrome / Android"
    if "mozilla.com" in host:
        return "Firefox"
    if "apple.com" in host:
        return "Apple (Safari/iOS)"
    if "windows.com" in host or "wns" in host:
        return "Windows / Edge"
    return host or "?"


def _push_health(last_ok: str | None, last_fail: str | None) -> str:
    """Zustellungs-Zustand aus den letzten Versand-Zeitstempeln (ISO, lexikografisch sortierbar)."""
    if last_fail and (not last_ok or last_fail > last_ok):
        return "fail"
    if last_ok:
        return "ok"
    return "unknown"


def _require_push_overview(request: Request) -> None:
    """Admin-Login PLUS Extra-Passwort (per Header) für die Push-Diagnose.

    Ist ``PUSH_OVERVIEW_PASSWORD`` leer, existiert das Feature nicht (404) — hält es unauffällig.
    """
    require_admin(request)
    settings = get_settings()
    if not settings.PUSH_OVERVIEW_PASSWORD:
        raise HTTPException(status_code=404, detail="Not found")
    if not check_password(request.headers.get("x-overview-pass", ""), settings.PUSH_OVERVIEW_PASSWORD):
        raise HTTPException(status_code=401, detail="Falsches Diagnose-Passwort")


@app.get("/api/admin/push/overview")
async def admin_push_overview(request: Request):
    """Push-Abos + Auswahl + Zustellungs-Diagnose + Unsichtbarkeits-Einstellungen (JSON)."""
    _require_push_overview(request)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        subs = get_push_overview(conn)
        vis = list_visibility_restrictions(conn)
        names = {p["cid"]: p.get("name") for p in list_pilots(conn, callsign_prefix=settings.CALLSIGN_PREFIX)}
    finally:
        conn.close()

    def _name(cid) -> str:
        try:
            cid_i = int(cid)
        except (TypeError, ValueError):
            return "?"
        return names.get(cid_i) or f"CID {cid_i}"

    def _filter_names(pf) -> list[str]:
        if not pf:
            return []
        try:
            return [_name(c) for c in json.loads(pf)]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    out_subs = []
    for s in subs:
        oc = s.get("owner_cid")
        out_subs.append({
            "owner_cid": oc,
            "owner_name": _name(oc) if oc is not None else None,
            "platform": _push_platform(s.get("endpoint", "")),
            "pilot_filter": _filter_names(s.get("pilot_filter")),
            "notify_prefiles": bool(s.get("notify_prefiles")),
            "notify_ts": bool(s.get("notify_ts")),
            "notify_events": bool(s.get("notify_events")),
            "created_at": s.get("created_at"),
            "last_ok_at": s.get("last_ok_at"),
            "last_fail_at": s.get("last_fail_at"),
            "last_status": s.get("last_status"),
            "health": _push_health(s.get("last_ok_at"), s.get("last_fail_at")),
        })

    logged_in = sum(1 for s in out_subs if s["owner_cid"] is not None)
    distinct_people = len({s["owner_cid"] for s in out_subs if s["owner_cid"] is not None})
    totals = {
        "abos": len(out_subs),
        "eingeloggt": logged_in,
        "anonym": len(out_subs) - logged_in,
        "personen": distinct_people,
        "will_prefiles": sum(1 for s in out_subs if s["notify_prefiles"]),
        "will_ts": sum(1 for s in out_subs if s["notify_ts"]),
        "will_events": sum(1 for s in out_subs if s["notify_events"]),
        "health_ok": sum(1 for s in out_subs if s["health"] == "ok"),
        "health_fail": sum(1 for s in out_subs if s["health"] == "fail"),
        "health_unknown": sum(1 for s in out_subs if s["health"] == "unknown"),
    }

    def _service_labels(raw) -> list[str]:
        """JSON-Liste der Services in lesbare Labels (``["online","ts"]`` → ``Online, TeamSpeak``)."""
        if not raw:
            return []
        try:
            return [_SERVICE_LABELS.get(s, s) for s in json.loads(raw)]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    out_vis = [{
        "who": _name(v.get("cid")), "cid": v.get("cid"), "mode": v.get("mode"),
        # CIDs zu Namen auflösen — roh sind sie für Menschen unlesbar (wie pilot_filter).
        "allowlist": _filter_names(v.get("allowlist")),
        "services": _service_labels(v.get("services")),
        "updated_at": v.get("updated_at"),
    } for v in vis]

    return {
        "vapid_configured": bool(settings.VAPID_PRIVATE_KEY),
        "totals": totals,
        "subscriptions": out_subs,
        "suppressed_pilots": out_vis,
    }


@app.get("/admin/push-overview", include_in_schema=False)
async def admin_push_overview_page(request: Request):
    """Unauffällige Diagnose-Seite: fragt das Extra-Passwort ab und rendert die Übersicht.

    Reihenfolge: erst die 404-Abschaltung, dann der Admin-Login. Andersherum bekäme ein
    Nicht-Admin bei abgeschaltetem Feature ein 401 statt 404 — und damit den Hinweis, dass
    unter dieser URL überhaupt etwas liegt.

    ``require_admin_page`` statt ``require_admin``: diese Seite liegt nicht unter
    ``/api/admin``, wo das eigentliche Admin-Cookie gilt.
    """
    from fastapi.responses import HTMLResponse
    settings = get_settings()
    if not settings.PUSH_OVERVIEW_PASSWORD:
        raise HTTPException(status_code=404, detail="Not found")
    require_admin_page(request)
    return HTMLResponse(content=_PUSH_OVERVIEW_HTML)


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
    require_confirm(request)
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
    require_confirm(request)
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
    """Freitext ('EDWG EDWA EDWG' / 'edwg,edxh') → normalisierte ICAO-CSV. **Reihenfolge UND
    Wiederholungen bleiben erhalten** — eine Bummel-Strecke ist eine Sequenz und darf legitim
    Plätze wiederholen bzw. wieder am Start enden (Rundkurs). Trenner Komma/Semikolon/Leerzeichen;
    leere Teile entfallen. (Kutter-Startplätze werden dagegen als Menge dedupliziert, s.
    _normalize_icao_list.)"""
    return ",".join(
        c.strip().upper()
        for c in str(raw or "").replace(";", ",").replace(" ", ",").split(",")
        if c.strip()
    )


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
    # Kein Badge ohne echten Transport: wer nur am Platz geladen und zurückgegeben hat (oder nur
    # gewartet/leer geflogen ist), hat nichts bewegt (`contributed` False) → wie „nicht teilgenommen".
    if not entry or not entry.get("contributed", True):
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


def _validate_transport_times(dtstart, dtend) -> str | None:
    """Enddatum muss NACH dem Startdatum liegen. Verhindert den 20.07.2026-Fall: ein Tippfehler im
    Enddatum (Monat/Jahr in der Vergangenheit) ließ den Poller `now >= dtend` sofort erfüllen und
    fror das Event Sekunden nach Start ein. ISO-8601-UTC-Strings vergleichen lexikografisch =
    chronologisch. Fehlt dtend, greift der Mitternacht-Default (kein Fehler)."""
    ds = (str(dtstart) if dtstart else "").strip()
    de = (str(dtend) if dtend else "").strip()
    if ds and de and de <= ds:
        return "Enddatum muss nach dem Startdatum liegen."
    return None


def _validate_transport_manifest(destination: str, cargo: list) -> str | None:
    """#84: ein manuelles Kutter-Event verlangt ein Ziel + ein Manifest mit Startplätzen je Ware.
    Gibt eine Fehlermeldung zurück oder ``None``. Jede Fracht-Zeile (Name + Menge > 0) braucht
    GENAU EINEN Startplatz ≠ Ziel (Entscheidung 6: eine Zeile = ein Stapel = ein Platz); ohne
    gültige Zeile wäre die abgeleitete Route nur das Ziel und kein Flug zählte."""
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
        # Entscheidung 6 (Spec 2026-07-15): eine Manifest-Zeile = ein Stapel = GENAU ein Platz.
        # Der "geteilte Topf" (departure NULL) und die CSV-Liste entfallen: eine Zeile ohne
        # eindeutigen Ort hat keinen Stapel, an dem sie liegen könnte.
        dep = _normalize_icao_list(line.get("departure"), exclude=destination)
        if not dep or "," in dep:
            return (f"Frachtart „{name}“: Jede Frachtart liegt an genau einem Platz. "
                    "Für dieselbe Ware an mehreren Plätzen leg mehrere Zeilen an.")
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
    terr = _validate_transport_times(body.get("dtstart"), body.get("dtend"))
    if terr:
        raise HTTPException(status_code=400, detail=terr)
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
        # Enddatum-Sanity gegen die EFFEKTIVEN Werte (geänderte + bestehende).
        terr = _validate_transport_times(
            fields.get("dtstart", cur.get("dtstart")), fields.get("dtend", cur.get("dtend")))
        if terr:
            raise HTTPException(status_code=400, detail=terr)
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
        # Snapshot-Löschung ALLEIN reicht nicht: `finished` hängt an `summarized_at`, sonst
        # schreibt der Poller den Snapshot beim nächsten Tick neu → Event bliebe eingefroren.
        # Deshalb hier zusätzlich auftauen (Fund 20.07.2026, #238).
        delete_progress_snapshot(conn, "kutter", event_id)
        clear_transport_summarized(conn, event_id)
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
    require_confirm(request)
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
            empty_kg=_num("empty_kg"), fuel_kg=_num("fuel_kg"),
            fuel_full_kg=_num("fuel_full_kg"), crew_kg=_num("crew_kg"),
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
    require_confirm(request)
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
            # #78: Grund ist reine Dokumentation -- kein Pflichtfeld, keine Validierung
            # (Freitext, das Admin-UI schlägt nur die bereits vergebenen Gründe vor).
            reason=(str(body.get("reason") or "").strip() or None),
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
    require_confirm(request)
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
    require_confirm(request)
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
    require_confirm(request)
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
    require_confirm(request)
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


# FriesenFlieger-Palette (Hex codes.txt aus dem Repaint Kit) — dieselbe Quelle wie
# app/badge.py. Nur diese vier Farben; ein Grün gibt es in der Marke nicht.
_FF_LBLUE = "#8FBFF1"
_FF_NAVY = "#191D53"
_FF_RED = "#8A1B1B"
_FF_ORANGE = "#D75F28"

# Badge-Symbole als SVG statt als Emoji: ein Farb-Emoji (🎧) liegt blass auf dem hellblauen
# Badge, weil es seine eigenen Farben mitbringt. `fill="currentColor"` übernimmt dagegen die
# Schriftfarbe des Badges (Navy) und bleibt bei 9 px sauber lesbar.
_ICON_PLANE = (
    '<svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
    '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1'
    'v-1.5L13 19v-5.5L21 16z"/></svg>'
)
_ICON_HEADSET = (
    '<svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
    '<path d="M12 3a9 9 0 0 0-9 9v5a3 3 0 0 0 3 3h1a1 1 0 0 0 1-1v-5a1 1 0 0 0-1-1H5v-1a7 7 0 '
    '0 1 14 0v1h-2a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1h1a3 3 0 0 0 3-3v-5a9 9 0 0 0-9-9z"/></svg>'
)


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
        f'<span class="badge ts-badge">{_ICON_HEADSET}{ts_count}&nbsp;im&nbsp;TS</span>'
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
  /* iOS/Safari bläst Text in einem iframe sonst selbsttätig auf ("Text Autosizing"): es hält
     das Dokument für eine Desktop-Seite und vergrößert die Schrift, damit sie "lesbar" wird —
     im Forum stand die 10-px-Fußzeile dadurch größer da als der Text der Seite ringsum.
     100% = Schriftgrößen so lassen, wie sie hier definiert sind. Chrome zeigt den Effekt nicht. */
  html{{-webkit-text-size-adjust:100%;text-size-adjust:100%}}
  body{{background:#d0e0f0;color:#053080;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;font-size:12px}}
  a{{color:inherit;text-decoration:none;display:block}}
  .hd{{background:#053080;color:#fff;padding:4px 10px;font-size:12px;font-weight:700;display:flex;align-items:center;gap:8px}}
  .hd-title{{flex:1}}
  /* Beide Zähler in FF-Hellblau auf dunklem Text. Das Padding der .hd-Zeile lässt den
     dunkelblauen Balken rundum stehen, die Badges sitzen als helle Felder darin. */
  .badge{{background:{_FF_LBLUE};color:{_FF_NAVY};padding:1px 6px;font-size:10px;font-weight:700;border-radius:2px;display:inline-flex;align-items:center;gap:3px}}
  .ts-badge{{background:{_FF_LBLUE}}}
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
    <span class="badge">{_ICON_PLANE}{len(live)}&nbsp;online</span>
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
