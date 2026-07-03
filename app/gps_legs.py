"""Reiner, DB-freier GPS-Leg-Detektor für FriesenSpy.

Erkennt Flug-Etappen (Legs) allein aus einer ts-sortierten Positionsliste je Pilot —
ohne Flugplan, ohne Disconnect. Höhe (AGL) ist das Leitsignal, Groundspeed nur sekundär
(STOL/Heli fliegen langsam). Landung wird NUR an einem Flugplatz gewertet.

Die Airport-Auflösung wird injiziert (``nearest_airport`` / ``airport_elev_ft``), damit die
Funktion rein und testbar bleibt.
"""
from __future__ import annotations

from datetime import datetime

# Neue Schwellen (Design (A)). Höhe (AGL) ist das Leitsignal, Groundspeed sekundär.
_GPS_FLYING_GS_KT = 50       # sekundärer Abhebe-Helfer (nur wenn Höhe fehlt); NICHT 60
_GPS_GROUND_AGL_FT = 300     # AGL-Obergrenze für „am Boden" beim Landungs-Guard
_GPS_AIR_AGL_FT = 500        # AGL-Anstieg über Boden = abgehoben (Leitsignal)
_GPS_BLOCK_GS_KT = 2         # Vollstopp-Schwelle (Touchdown-Kandidat)


def _parse_ts(ts: str) -> datetime:
    """ISO8601-UTC-String (…Z) → datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _update_max(cur: int | None, alt: int | None) -> int | None:
    """Max-Höhe über den Leg fortschreiben (None-tolerant)."""
    if alt is None:
        return cur
    if cur is None:
        return alt
    return max(cur, alt)


def _split_on_gaps(positions: list[dict], gap_minutes: int) -> list[list[dict]]:
    """Zeitlich sortieren und an Lücken > ``gap_minutes`` in Segmente teilen."""
    if not positions:
        return []
    ordered = sorted(positions, key=lambda p: p.get("ts", ""))
    segments: list[list[dict]] = []
    current: list[dict] = [ordered[0]]
    for pos in ordered[1:]:
        try:
            dt_prev = _parse_ts(current[-1]["ts"])
            dt_curr = _parse_ts(pos["ts"])
            if (dt_curr - dt_prev).total_seconds() / 60 > gap_minutes:
                segments.append(current)
                current = []
        except Exception:
            pass
        current.append(pos)
    if current:
        segments.append(current)
    return segments


def detect_gps_legs(
    positions: list[dict],
    *,
    nearest_airport,      # callable(lat, lon, max_km) -> icao str | None
    airport_elev_ft,      # callable(icao) -> elevation ft (float) | None
    radius_km: float = 10.0,
    gap_minutes: int = 30,
) -> list[dict]:
    """Erkennt Flug-Etappen aus GPS-Positionen (rein, DB-frei).

    ``positions``: Liste von Dicts mit ``ts`` (ISO8601-UTC), ``latitude``, ``longitude``,
    ``altitude`` (ft MSL, ggf. None), ``groundspeed`` (kt, ggf. None). Wird intern sortiert.

    Zustandsmaschine ON_GROUND → AIRBORNE → ON_GROUND. Die Landung wird SOFORT am Touchdown-
    Sample finalisiert (kein Dwell/LANDED-Zwischenzustand mehr) — jedes erneute Abheben ist
    ein neuer Roh-Leg über die normale, verankerte ON_GROUND-Erkennung. Jeder Leg ist ein
    Dict mit den Keys ``dep_icao, arr_icao, takeoff_ts, landing_ts, complete, dep_source,
    arr_source, max_altitude`` plus ``segment`` (0-basierter Index des Zeit-Segments, das
    ``detect_gps_legs`` nach Gaps > ``gap_minutes`` bildet). Rückgabe: Legs in chronologischer
    Reihenfolge.
    """
    legs: list[dict] = []
    # Segmentierung nach Zeitlücken implementiert die Gap-Regeln direkt: ein Segment-Ende
    # ist zugleich ein Gap-Ende (offen airborne → incomplete; tentativ gelandet → complete).
    for seg_index, segment in enumerate(_split_on_gaps(positions, gap_minutes)):
        seg_legs = _detect_segment(segment, nearest_airport, airport_elev_ft, radius_km)
        for leg in seg_legs:
            leg["segment"] = seg_index
        legs.extend(seg_legs)
    return legs


def _detect_segment(
    samples: list[dict],
    nearest_airport,
    airport_elev_ft,
    radius_km: float,
) -> list[dict]:
    """Zustandsmaschine für ein einzelnes (lückenfreies) Segment."""
    if not samples:
        return []

    legs: list[dict] = []

    state = "INIT"
    ground_ref_ft: int | None = None   # Höhe am letzten Boden-Sample (Takeoff-Referenz)
    dep_icao: str | None = None
    dep_source: str | None = None
    takeoff_ts: str | None = None
    max_alt: int | None = None
    land_ts: str | None = None
    land_arr: str | None = None

    def emit_complete() -> None:
        legs.append({
            "dep_icao": dep_icao,
            "arr_icao": land_arr,
            "takeoff_ts": takeoff_ts,
            "landing_ts": land_ts,
            "complete": True,
            "dep_source": dep_source,
            "arr_source": "gps",
            "max_altitude": max_alt,
        })

    def emit_incomplete() -> None:
        legs.append({
            "dep_icao": dep_icao,
            "arr_icao": None,
            "takeoff_ts": takeoff_ts,
            "landing_ts": None,
            "complete": False,
            "dep_source": dep_source,
            "arr_source": None,
            "max_altitude": max_alt,
        })

    for s in samples:
        ts = s.get("ts")
        lat = s.get("latitude")
        lon = s.get("longitude")
        alt = s.get("altitude")
        gs = s.get("groundspeed")

        if state == "INIT":
            if gs is not None and gs >= _GPS_FLYING_GS_KT:
                # Spawn-in-der-Luft: keine Boden-Referenz → direkt AIRBORNE, dep unbekannt.
                state = "AIRBORNE"
                dep_icao = None
                dep_source = None
                takeoff_ts = ts
                max_alt = _update_max(None, alt)
            else:
                state = "ON_GROUND"
                ground_ref_ft = alt
                dep_icao = nearest_airport(lat, lon, radius_km)
                dep_source = "gps" if dep_icao else None
            continue

        if state == "ON_GROUND":
            # Abheben zuerst gegen die BISHERIGE Boden-Referenz prüfen.
            took_off = False
            if alt is not None and ground_ref_ft is not None:
                took_off = (alt - ground_ref_ft) > _GPS_AIR_AGL_FT
            else:
                # Höhe nicht verfügbar → Groundspeed als sekundärer Helfer.
                took_off = gs is not None and gs > _GPS_FLYING_GS_KT

            if took_off:
                state = "AIRBORNE"
                takeoff_ts = ts
                # dep_icao/dep_source stammen aus dem Boden-Cluster (bereits getrackt).
                max_alt = _update_max(None, alt)
            else:
                # Weiter am Boden: dep-Kandidat aktualisieren. Die Boden-Referenz bleibt auf
                # der Feldhöhe verankert (Minimum) — sie darf NICHT mit dem Steigflug mit-
                # klettern, sonst bleibt (alt − ground_ref_ft) immer nur ein Sample-Schritt
                # und ein normal steigendes Flugzeug (~200 ft/Sample) überschreitet die
                # 500-ft-Schwelle nie → es würde nie ein Abheben erkannt.
                if alt is not None:
                    ground_ref_ft = alt if ground_ref_ft is None else min(ground_ref_ft, alt)
                dep_icao = nearest_airport(lat, lon, radius_km)
                dep_source = "gps" if dep_icao else None
            continue

        if state == "AIRBORNE":
            max_alt = _update_max(max_alt, alt)
            # Touchdown-Kandidat: Vollstopp + Platz im Umkreis + AGL-Guard.
            if gs is not None and gs < _GPS_BLOCK_GS_KT:
                ap = nearest_airport(lat, lon, radius_km)
                if ap is not None:
                    agl_ok = True
                    elev = airport_elev_ft(ap)
                    if alt is not None and elev is not None:
                        agl_ok = (alt - elev) < _GPS_GROUND_AGL_FT
                    if agl_ok:
                        # Landung SOFORT endgültig (kein Dwell/LANDED): emit + zurück ON_GROUND.
                        land_ts = ts
                        land_arr = ap
                        emit_complete()
                        state = "ON_GROUND"
                        ground_ref_ft = alt
                        dep_icao = ap
                        dep_source = "gps"
                        takeoff_ts = None
                        max_alt = None
                        land_ts = None
                        land_arr = None
            # Kein Platz / AGL-Guard verletzt → bleibt AIRBORNE (Absturz/Hover nie als Landung).
            continue

    # Segment-Ende (= Ende oder Gap): offene Zustände finalisieren.
    if state == "AIRBORNE":
        # Rein in der Luft beendet → unvollständiger Leg (Disconnect mid-air).
        emit_incomplete()
    # ON_GROUND/INIT: nie abgehoben → kein Leg (Ghost strukturell gefiltert).

    return legs
