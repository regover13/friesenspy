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
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import ADMIN_COOKIE, check_password, make_admin_token, verify_admin_token
from app.config import get_settings
from app.database import (
    apply_bummel_overrides,
    canonicalize_flights,
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
    update_bummel_race,
    update_bummel_reveals,
    upsert_bummel_override,
    delete_push_subscription,
    get_all_position_history,
    get_calendar_events,
    get_connection,
    get_live_flight_track,
    get_live_positions,
    get_stats,
    get_stats_activity,
    get_statsim_last_fetched,
    get_statsim_positions,
    init_db,
    save_statsim_positions,
    merge_fragmented_flights,
    upsert_push_subscription,
    upsert_statsim_flights,
)
from app.geo import filter_event_pilots, haversine, segment_into_flights
from app.poller import VatsimPoller, create_poller
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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/frontend-config")
async def frontend_config():
    settings = get_settings()
    return {
        "openaip_api_key": settings.OPENAIP_API_KEY,
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
        "version": VERSION,
        "changelog": CHANGELOG,
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
    """
    icao_list = [code.strip().upper() for code in icao.split(",") if code.strip()]
    global_search = icao_list == ["GLOBAL"]

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

    pilots = []
    found_cids: set[int] = set()
    for cid, positions in pilot_map.items():
        found_cids.add(cid)
        callsign = positions[0].get("callsign", "") if positions else ""
        conn2 = get_connection(settings.DB_PATH)
        flights: list[dict] = []
        name = ""
        try:
            name_row = conn2.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
            name = name_row["name"] if name_row else ""
            # Segmentierung über flights-Tabelle (exakter als Zeitlücke)
            # Fetch-End um 12h erweitern damit Merge-Fragmente mitgeladen werden;
            # nach dem Merge wird auf das echte Fenster (logon_time <= end) gefiltert.
            if end:
                try:
                    fetch_end = (
                        datetime.fromisoformat(end.replace("Z", "+00:00"))
                        + timedelta(hours=12)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    fetch_end = end
            else:
                fetch_end = "9999-12-31"
            flight_rows = conn2.execute(
                """SELECT callsign, departure, arrival, aircraft_short,
                          logon_time, logoff_time, duration_min, distance_nm, block_min,
                          route, remarks, cruise_altitude, cruise_tas, flight_rules, aircraft_icao, alternate,
                          deptime, enroute_time, fuel_time
                   FROM flights
                   WHERE cid = ?
                     AND superseded_by IS NULL
                     AND logon_time <= ?
                     AND (logoff_time IS NULL OR logoff_time >= ?)
                   ORDER BY logon_time""",
                (cid, fetch_end, start or "0000-01-01"),
            ).fetchall()
            if flight_rows:
                # Duplikate entfernen (gleiche logon_time+dep+arr, entstehen bei Container-Neustarts)
                seen: set[tuple] = set()
                deduped: list[dict] = []
                for r in flight_rows:
                    key = (r["logon_time"], r["departure"] or "", r["arrival"] or "")
                    if key not in seen:
                        seen.add(key)
                        deduped.append(dict(r, cid=cid))
                merged_rows = merge_fragmented_flights(deduped, conn=conn2)
                # Nur Flüge behalten, die innerhalb des Eventfensters GESTARTET sind
                if end:
                    merged_rows = [fr for fr in merged_rows if (fr.get("logon_time") or "") <= end]
                for fr in merged_rows:
                    if fr.get("logoff_time") and (fr.get("distance_nm") or 0) <= 0.5 and (fr.get("duration_min") or 0) <= 5:
                        continue
                    lo, lf = fr["logon_time"], fr.get("logoff_time", "")
                    # Vollständigen Track laden (über Eventfenster hinaus — Overlap-Fix)
                    full_pos = conn2.execute(
                        "SELECT latitude, longitude, altitude, groundspeed, heading, ts "
                        "FROM position_history WHERE cid = ? AND ts >= ? AND ts <= ? ORDER BY ts",
                        (cid, lo, lf or "9999-12-31T23:59:59Z"),
                    ).fetchall()
                    # Dauer und Strecke für aktive Flüge on-the-fly berechnen
                    duration = fr.get("duration_min")
                    dist = fr.get("distance_nm") or 0
                    if not lf:
                        try:
                            logon_dt = datetime.fromisoformat(lo.replace("Z", "+00:00"))
                            duration = max(0, int((datetime.now(_timezone.utc) - logon_dt).total_seconds() / 60))
                        except Exception:
                            pass
                        if len(full_pos) >= 2:
                            dist_km = sum(
                                haversine(full_pos[i][0], full_pos[i][1], full_pos[i + 1][0], full_pos[i + 1][1])
                                for i in range(len(full_pos) - 1)
                                if full_pos[i][0] and full_pos[i][1] and full_pos[i + 1][0] and full_pos[i + 1][1]
                            )
                            dist = round(dist_km / 1.852)
                    flights.append({
                        "logon_time": lo,
                        "logoff_time": lf,
                        "callsign": fr.get("callsign") or "",
                        "departure": fr.get("departure") or "",
                        "arrival": fr.get("arrival") or "",
                        "aircraft": fr.get("aircraft_short") or fr.get("aircraft") or "",
                        "aircraft_icao": fr.get("aircraft_icao") or "",
                        "route": fr.get("route") or "",
                        "remarks": fr.get("remarks") or "",
                        "cruise_altitude": fr.get("cruise_altitude") or "",
                        "cruise_tas": fr.get("cruise_tas") or "",
                        "flight_rules": fr.get("flight_rules") or "",
                        "alternate": fr.get("alternate") or "",
                        "deptime": fr.get("deptime") or "",
                        "enroute_time": fr.get("enroute_time") or "",
                        "fuel_time": fr.get("fuel_time") or "",
                        "duration_min": duration,
                        "block_min": fr.get("block_min"),
                        "distance_nm": dist,
                        "positions": [dict(r) for r in full_pos],
                        "source": "friesenspy",
                    })
            else:
                # Fallback: Zeitlücken-Segmentierung (z.B. Positionen vor FriesenSpy-Start)
                flights = [dict(f, source="friesenspy") for f in segment_into_flights(positions)]
        finally:
            conn2.close()

        pilots.append({
            "cid": cid,
            "callsign": callsign,
            "name": name,
            "flights": flights,
        })

    # StatSim-Ergänzung: Piloten die per DEP/ARR im Zeitfenster gefunden werden,
    # aber keine position_history haben (z.B. FriesenSpy war nicht aktiv)
    if global_search or icao_list:
        conn3 = get_connection(settings.DB_PATH)
        try:
            if global_search:
                statsim_rows = conn3.execute(
                    """
                    SELECT sc.cid, sc.callsign, sc.departure, sc.arrival, sc.aircraft,
                           sc.logon_time, sc.logoff_time, sc.duration_min, sc.statsim_id, p.name
                    FROM statsim_cache sc
                    LEFT JOIN pilots p ON sc.cid = p.cid
                    WHERE sc.logon_time != ''
                      AND sc.logoff_time IS NOT NULL
                      AND sc.duration_min > 5
                      AND sc.logon_time <= ?
                      AND sc.logoff_time >= ?
                      AND sc.callsign LIKE ?
                    ORDER BY sc.cid, sc.logon_time
                    """,
                    (end or "9999-12-31", start or "0000-01-01",
                     settings.CALLSIGN_PREFIX + "%"),
                ).fetchall()
            else:
                placeholders = ",".join("?" * len(icao_list))
                statsim_rows = conn3.execute(
                    f"""
                    SELECT sc.cid, sc.callsign, sc.departure, sc.arrival, sc.aircraft,
                           sc.logon_time, sc.logoff_time, sc.duration_min, sc.statsim_id, p.name
                    FROM statsim_cache sc
                    LEFT JOIN pilots p ON sc.cid = p.cid
                    WHERE (sc.departure IN ({placeholders}) OR sc.arrival IN ({placeholders}))
                      AND sc.logon_time != ''
                      AND sc.logoff_time IS NOT NULL
                      AND sc.duration_min > 5
                      AND sc.logon_time <= ?
                      AND sc.logoff_time >= ?
                      AND sc.callsign LIKE ?
                    ORDER BY sc.cid, sc.logon_time
                    """,
                    (*icao_list, *icao_list, end or "9999-12-31", start or "0000-01-01",
                     settings.CALLSIGN_PREFIX + "%"),
                ).fetchall()
        finally:
            conn3.close()

        statsim_by_cid: dict[int, list[dict]] = {}
        for r in statsim_rows:
            cid = r["cid"]
            if cid not in found_cids:
                statsim_by_cid.setdefault(cid, []).append(dict(r))

        for cid, st_flights in statsim_by_cid.items():
            pilots.append({
                "cid": cid,
                "callsign": st_flights[0].get("callsign") or "",
                "name": st_flights[0].get("name") or "",
                "flights": [
                    {
                        "logon_time":  f.get("logon_time") or "",
                        "logoff_time": f.get("logoff_time") or "",
                        "callsign":    f.get("callsign") or "",
                        "departure":   f.get("departure") or "",
                        "arrival":     f.get("arrival") or "",
                        "aircraft":    f.get("aircraft") or "",
                        "statsim_id":  f.get("statsim_id"),
                        "positions":   [],
                        "source":      "statsim",
                    }
                    for f in st_flights
                ],
            })

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
        display_days = days if days > 0 else 99999

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

        # Eine Wahrheit: kanonische (gemergte, deduplizierte) Flüge dieses Piloten.
        # callsign_prefix="" → alle Callsigns des Piloten (auch Nicht-FRS, wie bisher).
        start = (
            datetime.now(_timezone.utc) - timedelta(days=display_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Gecachte StatSim-Daten immer einbeziehen (gültige Wahrheit, identisch zu /api/stats);
        # nur der Hintergrund-Fetch oben hängt am API-Key.
        result = canonicalize_flights(
            conn,
            cids=[cid],
            callsign_prefix="",
            start=start,
            include_statsim=True,
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


def _build_race_view(conn, race: dict, now: str, *, force_reveal: bool = False) -> dict:
    """Öffentliche Sicht auf ein Rennen — vor Enthüllung redigiert (keine Zeiten/Schnitt).

    Admin-Korrekturen (``bummel_overrides``) werden auf die Wertung angewandt. ``force_reveal``
    liefert die volle Sicht auch während des Rennens (nur für die Admin-Vorschau).
    """
    route_icaos = [c for c in (race.get("route") or "").split(",") if c.strip()]
    route_set = {c.strip().upper() for c in route_icaos}
    standings = compute_bummel_standings(conn, route_icaos, race["dtstart"], race["dtend"])
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


@app.get("/api/bummel/races")
async def get_bummel_races():
    """Liste aller Bummel-Rennen (Status + Teilnehmerzahl, keine Zeiten vor Enthüllung)."""
    now = datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(get_settings().DB_PATH)
    try:
        update_bummel_reveals(conn, now, callsign_prefix=get_settings().CALLSIGN_PREFIX)
        out = []
        for race in list_bummel_races(conn):
            view = _build_race_view(conn, race, now)
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
    """Öffentliche Sicht eines Rennens — redigiert (keine Zeiten) bis zur Enthüllung."""
    now = datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(get_settings().DB_PATH)
    try:
        update_bummel_reveals(conn, now, callsign_prefix=get_settings().CALLSIGN_PREFIX)
        race = get_bummel_race(conn, race_id)
        if not race:
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        return _build_race_view(conn, race, now)
    finally:
        conn.close()


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
            radius_km=float(body.get("radius_km") or 10),
        )
        conn.commit()
        return {"status": "ok", "id": rid}
    finally:
        conn.close()


@app.post("/api/admin/bummel/races/{race_id}")
async def admin_update_race(request: Request, race_id: int):
    """Renn-Felder bearbeiten (name/route/dtstart/dtend/radius_km)."""
    require_admin(request)
    body = await request.json()
    fields = {k: body[k] for k in ("name", "route", "dtstart", "dtend", "radius_km") if k in body}
    conn = get_connection(get_settings().DB_PATH)
    try:
        if not get_bummel_race(conn, race_id):
            raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
        if fields:
            update_bummel_race(conn, race_id, **fields)
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
    """Wieder verbergen / neu starten (revealed_at zurücksetzen)."""
    require_admin(request)
    conn = get_connection(get_settings().DB_PATH)
    try:
        force_bummel_revealed(conn, race_id, None)
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
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


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
