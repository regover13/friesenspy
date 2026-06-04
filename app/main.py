"""FriesenSpy FastAPI-App — REST-Endpoints + SSE-Stream."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timezone as _timezone

import httpx as _httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import (
    get_all_position_history,
    get_connection,
    get_live_positions,
    get_pilot_flights_friesenspy,
    get_stats,
    get_statsim_flights_for_pilot,
    get_statsim_last_fetched,
    init_db,
    upsert_statsim_flights,
)
from app.geo import filter_event_pilots, segment_into_flights
from app.poller import VatsimPoller, create_poller
from app.statsim import fetch_flight_track, fetch_pilot_flights


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


@app.get("/api/stats")
async def get_stats_endpoint(request: Request, days: int = 30):
    """Flugstunden pro Pilot. ?days=30|90|365"""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        stats = get_stats(conn, days=days)
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
            row = conn2.execute("SELECT name FROM pilots WHERE cid = ?", (cid,)).fetchone()
            name = row["name"] if row else ""
        finally:
            conn2.close()
        flights = segment_into_flights(positions)
        pilots.append({
            "cid": cid,
            "callsign": callsign,
            "name": name,
            "flights": flights,   # war: "positions": positions
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
async def get_pilot_flights(cid: int, days: int = 90):
    """Alle Flüge eines Piloten: FriesenSpy + StatSim (gecached 24h)."""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        fs_flights = get_pilot_flights_friesenspy(conn, cid, days if days > 0 else 99999)
        statsim_flights: list[dict] = []
        if settings.STATSIM_API_KEY:
            last = get_statsim_last_fetched(conn, cid)
            cache_fresh = False
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    age_h = (
                        datetime.now(_timezone.utc) - last_dt.astimezone(_timezone.utc)
                    ).total_seconds() / 3600
                    cache_fresh = age_h < 24
                except Exception:
                    pass
            if not cache_fresh:
                async with _httpx.AsyncClient() as client:
                    if days == 0:
                        # Alle Flüge seit StatSim-Start (2020-01-22)
                        from datetime import datetime as _dt
                        statsim_days = (_dt.now(_timezone.utc) - _dt(2020, 1, 22, tzinfo=_timezone.utc)).days
                    else:
                        statsim_days = max(days, 365)
                    fresh = await fetch_pilot_flights(client, cid, settings.STATSIM_API_KEY, statsim_days)
                for f in fresh:
                    f["cid"] = cid
                upsert_statsim_flights(conn, fresh)
                conn.commit()
            display_days = days if days > 0 else 99999
            statsim_flights = get_statsim_flights_for_pilot(conn, cid, display_days)
    finally:
        conn.close()

    fs_logons = {(f.get("logon_time") or "")[:16] for f in fs_flights}
    result: list[dict] = [{"source": "friesenspy", **f} for f in fs_flights]
    for f in statsim_flights:
        lt = (f.get("logon_time") or "")[:16]
        if lt not in fs_logons:
            result.append({"source": "statsim", "id": None, **f})
    result.sort(key=lambda x: x.get("logon_time") or "", reverse=True)
    return result


@app.get("/api/flights/{flight_id}/track")
async def get_flight_track(flight_id: int):
    """Positionshistorie eines FriesenSpy-Fluges aus position_history."""
    settings = get_settings()
    conn = get_connection(settings.DB_PATH)
    try:
        flight = conn.execute(
            "SELECT logon_time, logoff_time FROM flights WHERE id = ?", (flight_id,)
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
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (logon, logoff),
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
