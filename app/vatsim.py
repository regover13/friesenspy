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


def filter_friesen_pilots(
    callsign_prefix: str, vatsim_data: dict, excluded_cids: frozenset[int] = frozenset()
) -> list[dict]:
    """Filtert VATSIM-Piloten nach Callsign-Prefix (z.B. 'FRS').

    Args:
        callsign_prefix: Callsign-Präfix (case-insensitiv), z.B. 'FRS'.
        vatsim_data: Dictionary von VATSIM-API mit 'pilots'-Schlüssel.
        excluded_cids: CIDs, die trotz passendem Callsign-Präfix NICHT als Friesen gelten
            sollen (Admin-Checkbox "Aktiv" in der Piloten-Pflegeliste, s. get_inactive_cids()).

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
        and p.get("cid") not in excluded_cids
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


def snapshot_other_traffic(callsign_prefix: str, vatsim_data: dict) -> list[dict]:
    """Alle NICHT-Friesen als schlanke Karten-Einträge für ``/api/traffic``.

    Bewusst kurze Feldnamen: Dieselbe Antwort geht über die Netzwerkverbindung des
    Simulators ins Kniebrett, und bei 60 Flugzeugen sparen die kurzen Namen rund ein
    Drittel der Nutzlast.

    Ausgeschlossen wird allein über das Callsign-Präfix -- ein per Admin-Checkbox auf
    "inaktiv" gesetzter Pilot fällt damit aus BEIDEN Listen heraus (er ist kein Friese mehr
    und wird auch nicht als Fremdverkehr nachgereicht). Das ist die Absicht der Checkbox.

    Args:
        callsign_prefix: Präfix der eigenen Leute, z. B. 'FRS'.
        vatsim_data: Rohantwort der VATSIM-API.

    Returns:
        Liste von Dicts mit cid/cs/lat/lon/alt/gs/hdg/ac/dep/arr. Leer bei kaputter Eingabe.
        ``cid`` dient nur dazu, den Anfragenden selbst aussortieren zu können, und geht
        nicht an den Client (s. ``/api/traffic``).
    """
    pilots = vatsim_data.get("pilots") if isinstance(vatsim_data, dict) else None
    if not isinstance(pilots, list):
        return []

    prefix = (callsign_prefix or "").upper()

    def _zahl(wert) -> int:
        try:
            return int(float(wert))
        except (TypeError, ValueError):
            return 0

    out: list[dict] = []
    for p in pilots:
        if not isinstance(p, dict):
            continue
        cs = str(p.get("callsign") or "")
        if not cs or (prefix and cs.upper().startswith(prefix)):
            continue
        lat, lon = p.get("latitude"), p.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        # 0/0 ist im Feed der Platzhalter für "noch keine Position" -- ein echtes Flugzeug
        # im Golf von Guinea wäre der Preis dafür, und den zahlen wir gern.
        if lat == 0.0 and lon == 0.0:
            continue
        fp = p.get("flight_plan")
        fp = fp if isinstance(fp, dict) else {}

        out.append({
            "cid": p.get("cid"),
            "cs": cs,
            "lat": lat,
            "lon": lon,
            "alt": _zahl(p.get("altitude")),
            "gs": _zahl(p.get("groundspeed")),
            "hdg": _zahl(p.get("heading")),
            "ac": str(fp.get("aircraft_short") or ""),
            "dep": str(fp.get("departure") or ""),
            "arr": str(fp.get("arrival") or ""),
        })
    return out
