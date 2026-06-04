"""StatSim API-Client für historische VATSIM-Flugdaten."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

STATSIM_BASE = "https://api.statsim.net"
logger = logging.getLogger(__name__)


def _normalize_flight(f: dict) -> dict:
    logon = f.get("loggedOn", "") or ""
    arrived = f.get("arrived", "") or ""
    duration_min = None
    if logon and arrived:
        try:
            t0 = datetime.fromisoformat(logon.replace("Z", "+00:00")).astimezone(timezone.utc)
            t1 = datetime.fromisoformat(arrived.replace("Z", "+00:00")).astimezone(timezone.utc)
            duration_min = max(0, int((t1 - t0).total_seconds() / 60))
        except Exception:
            pass

    def _norm_ts(ts: str) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return ts[:19] + "Z" if len(ts) >= 19 else ts

    return {
        "statsim_id": f.get("id"),
        "callsign": f.get("callsign", ""),
        "departure": f.get("departure", ""),
        "arrival": f.get("destination", ""),
        "aircraft": f.get("aircraft", ""),
        "logon_time": _norm_ts(logon),
        "logoff_time": _norm_ts(arrived) if arrived else None,
        "duration_min": duration_min,
    }


async def fetch_pilot_flights(
    client: httpx.AsyncClient,
    cid: int,
    api_key: str,
    days: int = 90,
) -> list[dict]:
    """Gibt Flughistorie eines Piloten von StatSim zurück. Silent fail → []."""
    if not api_key:
        return []
    results = []
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    chunk_days = 31
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        try:
            resp = await client.get(
                f"{STATSIM_BASE}/api/Flights/VatsimId",
                headers={"X-API-Key": api_key},
                params={
                    "vatsimId": str(cid),
                    "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for f in data:
                    results.append(_normalize_flight(f))
        except Exception as e:
            logger.warning(
                "StatSim chunk failed for CID %s (%s→%s): %s",
                cid, cursor.date(), chunk_end.date(), type(e).__name__,
            )
        cursor = chunk_end
    seen: set[int] = set()
    deduped = []
    for f in results:
        sid = f.get("statsim_id")
        if sid is not None and sid not in seen:
            seen.add(sid)
            deduped.append(f)
    return deduped


async def fetch_flight_track(
    client: httpx.AsyncClient,
    statsim_id: int,
    api_key: str,
) -> list[dict]:
    """Gibt GPS-Track eines Fluges von StatSim zurück. Silent fail → []."""
    if not api_key:
        return []
    try:
        resp = await client.get(
            f"{STATSIM_BASE}/api/Flights/Id/{statsim_id}",
            headers={"X-API-Key": api_key},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        positions = data.get("positions", [])
        if not isinstance(positions, list):
            return []
        return [
            {
                "latitude": p.get("latitude", 0.0),
                "longitude": p.get("longitude", 0.0),
                "altitude": p.get("altitude", 0),
                "groundspeed": p.get("speed", 0),
                "heading": p.get("heading", 0),
                "ts": p.get("time", ""),
            }
            for p in positions
            if isinstance(p, dict)
        ]
    except Exception:
        logger.warning("StatSim track fetch failed for flight %s", statsim_id)
        return []
