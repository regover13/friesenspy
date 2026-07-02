"""Geographische Hilfsfunktionen für FriesenSpy: Haversine-Distanz und Event-Filter."""
from __future__ import annotations

import math

import airportsdata


# airportsdata.load("ICAO") parst eine ~28.000-Flughäfen-Datenbank und ist teuer.
# Einmal modulweit cachen (deterministisch → identische Ergebnisse, nur einmal geladen).
_AIRPORTS_ICAO: dict | None = None


def _airports_icao() -> dict:
    global _AIRPORTS_ICAO
    if _AIRPORTS_ICAO is None:
        _AIRPORTS_ICAO = airportsdata.load("ICAO")
    return _AIRPORTS_ICAO


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Berechnet Großkreis-Distanz zwischen zwei Koordinaten in km.

    Args:
        lat1: Breitengrad Punkt 1 (Dezimalgrad)
        lon1: Längengrad Punkt 1 (Dezimalgrad)
        lat2: Breitengrad Punkt 2 (Dezimalgrad)
        lon2: Längengrad Punkt 2 (Dezimalgrad)

    Returns:
        Distanz in Kilometern
    """
    # Erdradius in km
    R = 6371.0

    # Umrechnung in Radianten
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    # Unterschiede berechnen
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    # Haversine-Formel
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


def icao_to_coords(icao: str) -> tuple[float, float] | None:
    """
    Gibt (latitude, longitude) für einen ICAO-Code zurück, oder None falls nicht gefunden.

    Verwendet das airportsdata-Package (ICAO-Datenbank eingebettet, kein API-Call).

    Args:
        icao: ICAO-Code (z.B. 'EDDK'), case-insensitive (wird zu uppercase konvertiert)

    Returns:
        (lat, lon) Tuple als floats, oder None falls Airport nicht gefunden
    """
    icao_upper = icao.upper()
    try:
        airports = _airports_icao()
        airport = airports.get(icao_upper)
        if airport is None:
            return None
        return (airport["lat"], airport["lon"])
    except Exception:
        return None


def filter_event_pilots(
    position_history_rows: list[dict],
    icao_list: list[str],
    radius_km: float,
    start_utc: str,
    end_utc: str,
) -> dict[int, list[dict]]:
    """
    Findet Piloten die während eines Events in der Nähe eines der Airports waren.

    Args:
        position_history_rows: Ergebnis von database.get_all_position_history()
                               Jedes Dict hat: cid, callsign, latitude, longitude, ts, ...
        icao_list: Liste von ICAO-Codes (z.B. ['EDDK', 'EDDL'])
        radius_km: Suchradius in km
        start_utc: ISO8601 UTC Startzeit (bereits gefiltert durch DB-Query)
        end_utc: ISO8601 UTC Endzeit (bereits gefiltert durch DB-Query)

    Returns:
        Dict von cid → [position_dicts] für alle Piloten die mindestens einmal
        innerhalb des Radius waren. Nur Piloten mit mindestens einem Treffer.
        (Alle Positionen des Piloten zurückgeben, nicht nur die Treffer-Positionen)

    Logik:
        1. Für jeden ICAO-Code: icao_to_coords() aufrufen (überspringen falls None)
        2. Für jede Position in position_history_rows:
           Haversine-Distanz zu jedem Airport berechnen
           Falls mindestens eine Distanz ≤ radius_km: Pilot ist "dabei"
        3. Ergebnis: {cid: [alle_positionen_dieses_piloten_im_zeitfenster]}
    """
    # 1. Airport-Koordinaten auflösen
    airport_coords: list[tuple[float, float]] = []
    for icao in icao_list:
        coords = icao_to_coords(icao)
        if coords is not None:
            airport_coords.append(coords)

    # Falls keine gültigen Airports: leeres Ergebnis
    if not airport_coords:
        return {}

    # 2. Sammle Piloten die mindestens einmal im Radius waren
    pilots_in_radius: set[int] = set()

    for row in position_history_rows:
        cid = row.get("cid")
        lat = row.get("latitude")
        lon = row.get("longitude")

        # Falls kritische Daten fehlen: überspringen
        if cid is None or lat is None or lon is None:
            continue

        # Prüfe Distanz zu jedem Airport
        for airport_lat, airport_lon in airport_coords:
            dist = haversine(lat, lon, airport_lat, airport_lon)
            if dist <= radius_km:
                pilots_in_radius.add(cid)
                break  # Pilot ist dabei, kein weiteres Prüfen nötig

    # 3. Für jeden Pilot im Radius: alle Positionen des Piloten sammeln
    result: dict[int, list[dict]] = {}
    for cid in pilots_in_radius:
        positions = [row for row in position_history_rows if row.get("cid") == cid]
        result[cid] = positions

    return result


def segment_into_flights(
    positions: list[dict],
    gap_minutes: int = 30,
) -> list[dict]:
    """Teilt eine flache Positions-Liste in einzelne Flüge auf.

    Ein neuer Flug beginnt wenn zwischen zwei aufeinanderfolgenden
    Positionen mehr als gap_minutes vergangen sind.

    Returns:
        Liste von Flug-Dicts: [{"logon_time", "logoff_time", "positions"}]
    """
    if not positions:
        return []
    sorted_pos = sorted(positions, key=lambda p: p.get("ts", ""))
    segments: list[list[dict]] = []
    current: list[dict] = [sorted_pos[0]]
    for pos in sorted_pos[1:]:
        try:
            from datetime import datetime, timezone as _tz
            dt_prev = datetime.fromisoformat(current[-1]["ts"].replace("Z", "+00:00"))
            dt_curr = datetime.fromisoformat(pos["ts"].replace("Z", "+00:00"))
            if (dt_curr - dt_prev).total_seconds() / 60 > gap_minutes:
                segments.append(current)
                current = []
        except Exception:
            pass
        current.append(pos)
    if current:
        segments.append(current)
    return [
        {
            "logon_time": seg[0].get("ts", ""),
            "logoff_time": seg[-1].get("ts", ""),
            "positions": seg,
        }
        for seg in segments
    ]


def nearest_airport_icao(lat: float, lon: float, max_km: float) -> str | None:
    """ICAO des nächstgelegenen Flugplatzes im Umkreis ``max_km`` — sonst None.

    Linearer Scan über die airportsdata-Datenbank (~28k Einträge) mit grobem
    Bounding-Box-Vorfilter; gedacht für seltene Ereignisse (Verlust-Klassifikation),
    nicht für den Poll-Takt.
    """
    best, best_d = None, max_km
    box = max_km / 111.0 + 0.01  # Grad-Näherung
    for icao, a in _airports_icao().items():
        alat, alon = a.get("lat"), a.get("lon")
        if alat is None or alon is None or abs(alat - lat) > box:
            continue
        d = haversine(lat, lon, alat, alon)
        if d <= best_d:
            best, best_d = icao, d
    return best
