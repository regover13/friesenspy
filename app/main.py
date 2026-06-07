"""FriesenSpy FastAPI-App — REST-Endpoints + SSE-Stream."""
from __future__ import annotations

import asyncio
import html as _html
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timezone as _timezone

import httpx as _httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import (
    delete_push_subscription,
    get_all_position_history,
    get_calendar_events,
    get_connection,
    get_live_flight_track,
    get_live_positions,
    get_pilot_flights_friesenspy,
    get_stats,
    get_stats_activity,
    get_statsim_flights_for_pilot,
    get_statsim_last_fetched,
    get_statsim_positions,
    init_db,
    save_statsim_positions,
    merge_fragmented_flights,
    upsert_push_subscription,
    upsert_statsim_flights,
)
from app.geo import filter_event_pilots, segment_into_flights
from app.poller import VatsimPoller, create_poller
from app.statsim import fetch_flight_track, fetch_pilot_flights

_logger = logging.getLogger(__name__)

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/frontend-config")
async def frontend_config():
    settings = get_settings()
    return {
        "openaip_api_key": settings.OPENAIP_API_KEY,
        "vapid_public_key": settings.VAPID_PUBLIC_KEY,
    }


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    """Browser-Push-Subscription speichern."""
    body = await request.json()
    endpoint = body.get("endpoint", "")
    p256dh = body.get("p256dh", "")
    auth = body.get("auth", "")
    if not endpoint or not p256dh or not auth:
        return JSONResponse({"error": "endpoint, p256dh and auth are required"}, status_code=400)
    if "permanently-removed.invalid" in endpoint:
        return JSONResponse({"error": "invalid push endpoint"}, status_code=400)
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        upsert_push_subscription(conn, endpoint, p256dh, auth, body.get("pilot_filter"))
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


_STATS_SORT_FIELDS = {"last_flight", "flight_count", "total_duration_min", "total_distance_nm"}


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

    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        rows = get_all_position_history(conn, start, end)
    finally:
        conn.close()

    pilot_map = filter_event_pilots(rows, icao_list, radius, start, end)

    pilots = []
    found_cids: set[int] = set()
    for cid, positions in pilot_map.items():
        found_cids.add(cid)
        callsign = positions[0].get("callsign", "") if positions else ""
        conn2 = get_connection(settings.DB_PATH)
        merged_rows: list[dict] = []
        try:
            name_row = conn2.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
            name = name_row["name"] if name_row else ""
            # Segmentierung über flights-Tabelle (exakter als Zeitlücke)
            flight_rows = conn2.execute(
                """SELECT callsign, departure, arrival, aircraft_short,
                          logon_time, logoff_time, duration_min
                   FROM flights
                   WHERE cid = ?
                     AND logoff_time IS NOT NULL
                     AND logon_time <= ?
                     AND logoff_time >= ?
                   ORDER BY logon_time""",
                (cid, end or "9999-12-31", start or "0000-01-01"),
            ).fetchall()
            if flight_rows:
                # cid zu den Dicts hinzufügen, damit der Geo-Check in merge möglich ist
                merged_rows = merge_fragmented_flights(
                    [dict(r, cid=cid) for r in flight_rows],
                    conn=conn2,
                )
        finally:
            conn2.close()

        if merged_rows:
            flights = []
            for fr in merged_rows:
                if (fr.get("duration_min") or 0) <= 5:
                    continue
                lo, lf = fr["logon_time"], fr.get("logoff_time", "")
                # Vollständigen Track laden (über Eventfenster hinaus — Overlap-Fix)
                full_pos = conn2.execute(
                    "SELECT latitude, longitude, altitude, groundspeed, heading, ts "
                    "FROM position_history WHERE cid = ? AND ts >= ? AND ts <= ? ORDER BY ts",
                    (cid, lo, lf or "9999-12-31T23:59:59Z"),
                ).fetchall()
                seg_positions = [dict(r) for r in full_pos]
                flights.append({
                    "logon_time": lo,
                    "logoff_time": lf,
                    "callsign": fr.get("callsign") or "",
                    "departure": fr.get("departure") or "",
                    "arrival": fr.get("arrival") or "",
                    "aircraft": fr.get("aircraft_short") or fr.get("aircraft") or "",
                    "positions": seg_positions,
                    "source": "friesenspy",
                })
        else:
            # Fallback: Zeitlücken-Segmentierung (z.B. Positionen vor FriesenSpy-Start)
            flights = [dict(f, source="friesenspy") for f in segment_into_flights(positions)]

        pilots.append({
            "cid": cid,
            "callsign": callsign,
            "name": name,
            "flights": flights,
        })

    # StatSim-Ergänzung: Piloten die per DEP/ARR im Zeitfenster gefunden werden,
    # aber keine position_history haben (z.B. FriesenSpy war nicht aktiv)
    if icao_list:
        placeholders = ",".join("?" * len(icao_list))
        conn3 = get_connection(settings.DB_PATH)
        try:
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
    """Async generator für SSE — sendet Live-Positions-Updates oder keepalives."""
    while True:
        if await request.is_disconnected():
            break
        try:
            data = await asyncio.wait_for(poller.sse_queue.get(), timeout=30.0)
            yield f"data: {json.dumps(data)}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"


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
        fs_flights = [
            f for f in merge_fragmented_flights(
                get_pilot_flights_friesenspy(conn, cid, display_days),
                conn=conn,
            )
            if (f.get("duration_min") or 0) > 5
        ]
        statsim_flights: list[dict] = []

        if settings.STATSIM_API_KEY:
            # Immer gecachte Daten sofort zurückgeben
            statsim_flights = get_statsim_flights_for_pilot(conn, cid, display_days)

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
    finally:
        conn.close()

    result: list[dict] = [{"source": "friesenspy", **f} for f in fs_flights]
    for f in statsim_flights:
        lt = (f.get("logon_time") or "")[:16]
        # Deduplizieren: StatSim-Flug unterdrücken wenn sein logon_time innerhalb eines
        # FriesenSpy-Fluges liegt (nötig nach Merge, wo logon_time auf früheren Wert gesetzt wird)
        covered = any(
            (fs.get("logon_time") or "")[:16] <= lt <= (fs.get("logoff_time") or "")[:16]
            for fs in fs_flights
            if fs.get("logon_time") and fs.get("logoff_time")
        )
        if not covered:
            result.append({"source": "statsim", "id": None, **f})
    result.sort(key=lambda x: x.get("logon_time") or "", reverse=True)
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
            "route": fp.get("route", ""),
            "planned_deptime": fp.get("deptime", ""),
        })
    return result


@app.get("/api/calendar/events")
async def get_calendar_events_endpoint():
    """FriesenEvents der letzten 365 Tage aus dem Google-Kalender-Cache."""
    conn = get_connection(get_settings().DB_PATH)
    try:
        return get_calendar_events(conn, days_back=365)
    finally:
        conn.close()


@app.get("/widget", include_in_schema=False)
async def widget():
    """Einbettbares iframe-Widget für friesenflieger.de."""
    from fastapi.responses import HTMLResponse
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        live = get_live_positions(conn)
        stats = get_stats(conn, days=7, callsign_prefix=settings.CALLSIGN_PREFIX)
    finally:
        conn.close()

    total_min = sum(s.get("total_duration_min", 0) for s in stats)
    total_h = total_min / 60
    pilots_html = " &nbsp;·&nbsp; ".join(
        f'<span>{_html.escape(str(p.get("callsign") or p.get("name") or "?"))}</span>'
        for p in live
    ) if live else '<span style="color:#6b9ab8">Niemand online</span>'

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="60">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#04080f;color:#d4e8f5;font-family:'Courier New',monospace;font-size:12px;padding:8px}}
  a{{color:inherit;text-decoration:none;display:block}}
  .hd{{color:#2d9cdb;font-weight:700;font-size:13px;margin-bottom:5px}}
  .badge{{background:#2d9cdb;color:#04080f;padding:1px 6px;font-size:10px;margin-right:6px;font-weight:700}}
  .ft{{margin-top:5px;font-size:10px;color:#6b9ab8;border-top:1px solid rgba(45,156,219,0.2);padding-top:4px}}
</style>
</head>
<body>
<a href="https://friesenspy.devprops.de" target="_blank">
  <div class="hd">◈ FriesenSpy</div>
  <div><span class="badge">{len(live)} online</span>{pilots_html}</div>
  <div class="ft">7&nbsp;Tage:&nbsp;{total_h:.1f}&nbsp;h&nbsp;·&nbsp;friesenspy.devprops.de</div>
</a>
</body>
</html>"""
    return HTMLResponse(
        content=html,
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"},
    )
