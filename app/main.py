"""FriesenSpy FastAPI-App — REST-Endpoints + SSE-Stream."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timezone as _timezone

import httpx as _httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import (
    get_all_position_history,
    get_connection,
    get_live_flight_track,
    get_live_positions,
    get_pilot_flights_friesenspy,
    get_stats,
    get_stats_activity,
    get_statsim_flights_for_pilot,
    get_statsim_last_fetched,
    init_db,
    merge_fragmented_flights,
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


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/frontend-config")
async def frontend_config():
    settings = get_settings()
    return {"openaip_api_key": settings.OPENAIP_API_KEY}


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


@app.get("/api/stats")
async def get_stats_endpoint(request: Request, days: int = 30):
    """Flugstunden pro Pilot. ?days=30|90|365"""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        stats = get_stats(conn, days=days, callsign_prefix=settings.CALLSIGN_PREFIX)
    finally:
        conn.close()
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
    for cid, positions in pilot_map.items():
        callsign = positions[0].get("callsign", "") if positions else ""
        conn2 = get_connection(settings.DB_PATH)
        try:
            name_row = conn2.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
            name = name_row["name"] if name_row else ""
            # Segmentierung über flights-Tabelle (exakter als Zeitlücke)
            flight_rows = conn2.execute(
                """SELECT callsign, departure, arrival, aircraft_short,
                          logon_time, logoff_time
                   FROM flights
                   WHERE cid = ?
                     AND logoff_time IS NOT NULL
                     AND logon_time <= ?
                     AND logoff_time >= ?
                   ORDER BY logon_time""",
                (cid, end or "9999-12-31", start or "0000-01-01"),
            ).fetchall()
        finally:
            conn2.close()

        if flight_rows:
            merged_rows = merge_fragmented_flights(
                [dict(r) for r in flight_rows]
            )
            flights = []
            for fr in merged_rows:
                lo, lf = fr["logon_time"], fr.get("logoff_time", "")
                seg_positions = [p for p in positions if lo <= p.get("ts", "") <= lf]
                flights.append({
                    "logon_time": lo,
                    "logoff_time": lf,
                    "callsign": fr.get("callsign") or "",
                    "departure": fr.get("departure") or "",
                    "arrival": fr.get("arrival") or "",
                    "aircraft": fr.get("aircraft_short") or fr.get("aircraft") or "",
                    "positions": seg_positions,
                })
        else:
            # Fallback: Zeitlücken-Segmentierung (z.B. Positionen vor FriesenSpy-Start)
            flights = segment_into_flights(positions)

        pilots.append({
            "cid": cid,
            "callsign": callsign,
            "name": name,
            "flights": flights,
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
        fs_flights = merge_fragmented_flights(
            get_pilot_flights_friesenspy(conn, cid, display_days)
        )
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

    fs_logons = {(f.get("logon_time") or "")[:16] for f in fs_flights}
    result: list[dict] = [{"source": "friesenspy", **f} for f in fs_flights]
    for f in statsim_flights:
        lt = (f.get("logon_time") or "")[:16]
        if lt not in fs_logons:
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
async def get_flight_track(flight_id: int):
    """Positionshistorie eines FriesenSpy-Fluges aus position_history."""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        flight = conn.execute(
            "SELECT cid, logon_time, logoff_time FROM flights WHERE id = ?", (flight_id,)
        ).fetchone()
        if not flight:
            raise HTTPException(status_code=404, detail="Flight not found")
        logon = flight["logon_time"] or ""
        logoff = flight["logoff_time"] or datetime.now(_timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        rows = conn.execute(
            """
            SELECT latitude, longitude, altitude, groundspeed, heading, ts
            FROM position_history
            WHERE cid = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (flight["cid"], logon, logoff),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/api/flights/statsim/{statsim_id}/track")
async def get_statsim_flight_track(statsim_id: int):
    """Positionshistorie eines StatSim-Fluges (live von StatSim API)."""
    settings = get_settings()
    if not settings.STATSIM_API_KEY:
        return []
    async with _httpx.AsyncClient() as client:
        return await fetch_flight_track(client, statsim_id, settings.STATSIM_API_KEY)
