"""VATSIM-API-Client für FriesenSpy — Abrufen und Filtern von Pilotendaten."""
from __future__ import annotations

import httpx

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"


async def fetch_vatsim_data(client: httpx.AsyncClient) -> dict:
    """Ruft VATSIM-API ab. Gibt geparsten JSON-Dict zurück. Wirft httpx.HTTPError bei Fehler.

    Args:
        client: httpx.AsyncClient für die HTTP-Anfrage.

    Returns:
        Dictionary mit den VATSIM-Daten (enthält 'pilots', 'controllers', 'servers' etc.).

    Raises:
        httpx.HTTPError: Bei HTTP-Fehler (Connection, Timeout, Status-Code etc.)
    """
    response = await client.get(VATSIM_DATA_URL)
    response.raise_for_status()
    return response.json()


def filter_friesen_pilots(callsign_prefix: str, vatsim_data: dict) -> list[dict]:
    """Filtert VATSIM-Piloten nach Callsign-Prefix (z.B. 'FRS').

    Args:
        callsign_prefix: Callsign-Präfix (case-insensitiv), z.B. 'FRS'.
        vatsim_data: Dictionary von VATSIM-API mit 'pilots'-Schlüssel.

    Returns:
        Liste der matching pilot-Objekte (unmodifiziert aus VATSIM).
    """
    if "pilots" not in vatsim_data:
        return []

    pilots = vatsim_data["pilots"]
    if not isinstance(pilots, list):
        return []

    prefix = callsign_prefix.upper()
    return [
        p for p in pilots
        if isinstance(p, dict) and p.get("callsign", "").upper().startswith(prefix)
    ]


def pilot_to_position(pilot: dict) -> dict:
    """Konvertiert VATSIM-Piloten-Dict in flaches Position-Dict.

    Args:
        pilot: Pilot-Dictionary aus VATSIM-API.

    Returns:
        Flaches Position-Dictionary mit Feldern:
        - cid: Pilot-Kennummer (int)
        - name: Pilot-Name (str)
        - callsign: Flugzeug-Callsign (str)
        - aircraft: Flugzeug-Typ aus flight_plan (str, '' falls kein flight_plan)
        - aircraft_short: Gleich wie aircraft
        - departure: Ausgangsflughafen (str, '' falls kein flight_plan)
        - arrival: Zielflughafen (str, '' falls kein flight_plan)
        - latitude: Geografische Breite (float)
        - longitude: Geografische Länge (float)
        - altitude: Flughöhe in Fuß (int)
        - groundspeed: Geschwindigkeit über Grund (int)
        - heading: Kursrichtung (int, 0-359)
        - logon_time: ISO8601 UTC String
    """
    flight_plan = pilot.get("flight_plan")
    fp = flight_plan if (flight_plan and isinstance(flight_plan, dict)) else {}

    aircraft_full = fp.get("aircraft", "")
    aircraft = fp.get("aircraft_short", "") or (aircraft_full.split("/")[0] if aircraft_full else "")
    departure = fp.get("departure", "")
    arrival = fp.get("arrival", "")

    # Full flight plan fields for modal
    flight_rules = fp.get("flight_rules", "")
    aircraft_icao = fp.get("aircraft_icao", "") or fp.get("aircraft", "").split("/")[0] if fp.get("aircraft") else ""
    alternate = fp.get("alternate", "")
    deptime = fp.get("deptime", "")
    cruise_altitude = fp.get("altitude", "")
    cruise_tas = fp.get("cruise_tas", "")
    enroute_time = fp.get("enroute_time", "")
    fuel_time = fp.get("fuel_time", "")
    route = fp.get("route", "")
    remarks = fp.get("remarks", "")

    return {
        "cid": pilot.get("cid"),
        "name": pilot.get("name", ""),
        "callsign": pilot.get("callsign", ""),
        "aircraft": aircraft,
        "aircraft_short": aircraft,
        "departure": departure,
        "arrival": arrival,
        "latitude": pilot.get("latitude", 0.0),
        "longitude": pilot.get("longitude", 0.0),
        "altitude": pilot.get("altitude", 0),
        "groundspeed": pilot.get("groundspeed", 0),
        "heading": pilot.get("heading", 0),
        "logon_time": pilot.get("logon_time", ""),
        "last_updated": pilot.get("last_updated", ""),
        "flight_rules": flight_rules,
        "aircraft_icao": aircraft_icao,
        "alternate": alternate,
        "deptime": deptime,
        "cruise_altitude": cruise_altitude,
        "cruise_tas": cruise_tas,
        "enroute_time": enroute_time,
        "fuel_time": fuel_time,
        "route": route,
        "remarks": remarks,
    }
