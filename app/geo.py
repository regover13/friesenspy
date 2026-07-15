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


# Ergänzungs-Flugplätze (#50) — Plätze, die in airportsdata fehlen (z. B. Segelfluggelände ohne
# offizielle ICAO-Kennung), admin-pflegbar über app.database.custom_airports. geo.py bleibt bewusst
# DB-frei: der Aufrufer (main.py-Lifespan, Admin-Endpoints) befüllt diesen Cache per Push über
# set_custom_airports() — Invalidierung ist einfach ein erneuter Aufruf, kein DB-Zugriff hier.
# Wert-Tupel: (lat, lon, elevation_ft | None, radius_km | None).
#
# #56: custom_airports ist seit diesem Fix ein OVERRIDE (nicht mehr nur ein Fallback für
# gänzlich fehlende Codes) — geprüft VOR airportsdata. Grund: airportsdata kann selbst falsche
# Koordinaten führen (Fund: EBUL/Ursel Air Base ~15 km daneben), die ein reiner Fallback nie
# reparieren könnte, weil airportsdata für den Code ja bereits einen (falschen) Treffer liefert.
# Ein Admin-Eintrag mit demselben Code überschreibt daher bewusst den Standard-Wert; die
# nearest_airport_icao*-Funktionen überspringen dafür jeden airportsdata-Eintrag, dessen Code
# in _CUSTOM_AIRPORTS auftaucht (sonst würde die falsche airportsdata-Position weiterhin
# gefunden, nur eben in Konkurrenz zur richtigen Custom-Position).
#
# #62: ``radius_km`` überschreibt NUR den Suchradius für diesen Code, unabhängig von lat/lon
# (die dabei unverändert von airportsdata übernommen werden können — Fund: EHAM/Schiphol, wo
# der tatsächliche Abhebepunkt bei langem Rollweg mehrere km vom Referenzpunkt entfernt liegen
# kann, die Koordinate selbst aber korrekt ist). ``None`` = der von der aufrufenden Funktion
# übergebene Standardradius gilt unverändert (rückwärtskompatibel für alle bisherigen Einträge).
_CUSTOM_AIRPORTS: dict[str, tuple[float, float, float | None, float | None]] = {}


def set_custom_airports(rows: list[dict]) -> None:
    """Ersetzt den Ergänzungs-Flugplatz-Cache komplett (Invalidierung = Neuaufruf).

    ``rows`` wie von :func:`app.database.list_custom_airports` geliefert (Keys: ``icao``, ``lat``,
    ``lon``, ``elevation_ft``, ``radius_km``). Codes werden uppercase gespeichert (Lookups sind
    case-insensitive).
    """
    global _CUSTOM_AIRPORTS
    _CUSTOM_AIRPORTS = {
        (r["icao"] or "").upper(): (r["lat"], r["lon"], r.get("elevation_ft"), r.get("radius_km"))
        for r in rows
        if r.get("icao") and r.get("lat") is not None and r.get("lon") is not None
    }


def is_known_in_airportsdata(icao: str) -> bool:
    """True wenn ``icao`` bereits in der Standard-Datenbank (airportsdata) existiert —
    UNABHÄNGIG von custom_airports. Für die Admin-Plausiprüfung (#50): ein Ergänzungs-Eintrag
    darf nie einen Platz duplizieren, der schon offiziell bekannt ist (Fund: EDXU/Hüttenbusch
    steckte bereits in airportsdata, war fälschlich als „fehlend" vermutet worden)."""
    try:
        return _airports_icao().get((icao or "").upper()) is not None
    except Exception:
        return False


def airportsdata_coords(icao: str) -> tuple[float, float] | None:
    """(lat, lon) NUR aus der Standard-Datenbank (airportsdata) — ohne ``custom_airports``.

    Gegenstück zu :func:`icao_to_coords`, das bei einem Override (#56) bewusst den
    Custom-Wert liefert. Für die Frage „weicht der Custom-Eintrag von airportsdata ab?"
    ist genau der ungeschminkte Standard-Wert nötig — mit ``icao_to_coords`` vergliche man
    den Override mit sich selbst (immer 0 km). ``None``, wenn der Code dort nicht existiert.
    """
    try:
        airport = _airports_icao().get((icao or "").upper())
    except Exception:
        return None
    if airport is None:
        return None
    return (airport["lat"], airport["lon"])


def search_airports(q: str, limit: int = 20) -> list[dict]:
    """#77-Erweiterung: ICAO-Präfix-Suche über airportsdata + `custom_airports`. Gibt bis zu
    ``limit`` Treffer als ``{icao, name}`` (alphabetisch) zurück — für das Autocomplete an den
    Platz-Eingaben. Leerer/zu kurzer Query → leer."""
    q = (q or "").strip().upper()
    if not q:
        return []
    try:
        airports = _airports_icao()
    except Exception:
        airports = {}
    codes = {c for c in _CUSTOM_AIRPORTS if c.startswith(q)}
    codes |= {c for c in airports if c.startswith(q)}
    out = []
    for c in sorted(codes)[:limit]:
        info = airports.get(c) or {}
        out.append({"icao": c, "name": info.get("name") or ""})
    return out


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
    custom = _CUSTOM_AIRPORTS.get(icao_upper)
    if custom is not None:
        return (custom[0], custom[1])
    try:
        airports = _airports_icao()
        airport = airports.get(icao_upper)
        if airport is not None:
            return (airport["lat"], airport["lon"])
    except Exception:
        return None
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


def nearest_airport_icao(lat: float, lon: float, max_km: float) -> str | None:
    """ICAO des nächstgelegenen Flugplatzes im Umkreis ``max_km`` — sonst None.

    Linearer Scan über die airportsdata-Datenbank (~28k Einträge) mit grobem
    Bounding-Box-Vorfilter; gedacht für seltene Ereignisse (Verlust-Klassifikation),
    nicht für den Poll-Takt.
    """
    best, best_d = None, max_km
    box = max_km / 111.0 + 0.01  # Grad-Näherung
    for icao, a in _airports_icao().items():
        if icao in _CUSTOM_AIRPORTS:
            continue  # #56: von Custom überschattet (Override), airportsdata-Wert ignorieren
        alat, alon = a.get("lat"), a.get("lon")
        if alat is None or alon is None or abs(alat - lat) > box:
            continue
        d = haversine(lat, lon, alat, alon)
        if d <= best_d:
            best, best_d = icao, d
    # Ergänzungs-Flugplätze (#50/#56) NACH airportsdata vergleichen — bei exaktem Distanz-
    # Gleichstand gewinnt Custom (gleiche Nachrang-Reihenfolge wie in nearest_airport_icao_fast).
    # #62: ein Code mit eigenem radius_km darf auch dann als Kandidat zählen, wenn er weiter
    # als max_km entfernt liegt (best_d startet bei max_km) — er gewinnt trotzdem nur, wenn er
    # NÄHER als der bisher beste Treffer ist (echtes "nearest", nicht "erster Treffer im
    # eigenen Radius").
    for icao, (alat, alon, _elev, radius_km) in _CUSTOM_AIRPORTS.items():
        effective_radius = radius_km if radius_km is not None else max_km
        d = haversine(lat, lon, alat, alon)
        if d > effective_radius:
            continue
        if best is None or d <= best_d:
            best, best_d = icao, d
    return best


# Grad-Grid-Bucket-Index: jeder Flugplatz wird nach seiner Ganzzahl-Zelle
# (floor(lat), floor(lon)) einsortiert. Eine Umkreis-Abfrage muss dann nur noch
# die wenigen Zellen der Bounding-Box scannen statt aller ~28k Einträge — gedacht
# für häufige Abfragen (Poll-Takt / Leg-Detektor). Einmal modulweit + faul gecacht.
_AIRPORT_GRID: dict[tuple[int, int], list[tuple[int, str, float, float]]] | None = None


def _airport_grid() -> dict[tuple[int, int], list[tuple[int, str, float, float]]]:
    """Baut (faul, gecacht) den Grad-Grid-Bucket-Index auf.

    Jeder Bucket-Eintrag ist ``(idx, icao, alat, alon)`` mit ``idx`` = Einfüge-Reihenfolge
    aus ``_airports_icao()``. Der Index erlaubt es, Kandidaten in exakt derselben Reihenfolge
    wie der Linearscan zu verarbeiten (identisches Tie-Breaking bei gleicher Distanz).
    """
    global _AIRPORT_GRID
    if _AIRPORT_GRID is None:
        grid: dict[tuple[int, int], list[tuple[int, str, float, float]]] = {}
        for idx, (icao, a) in enumerate(_airports_icao().items()):
            alat, alon = a.get("lat"), a.get("lon")
            if alat is None or alon is None:
                continue
            key = (math.floor(alat), math.floor(alon))
            grid.setdefault(key, []).append((idx, icao, alat, alon))
        _AIRPORT_GRID = grid
    return _AIRPORT_GRID


def nearest_airport_icao_fast(lat: float, lon: float, max_km: float) -> str | None:
    """Schnelle, Grid-indizierte Neuimplementierung von :func:`nearest_airport_icao`.

    Liefert für jede Eingabe byte-identische Ergebnisse wie der Linearscan, scannt aber
    nur die Buckets, die die ``max_km``-Bounding-Box abdecken (in Längengrad großzügig um
    ``cos(lat)`` korrigiert, plus 1 Bucket Rand → Kandidatenmenge ist stets eine Obermenge
    aller Plätze innerhalb ``max_km``). Rückgabe: ICAO des nächsten Platzes ≤ ``max_km`` oder None.
    """
    grid = _airport_grid()

    # Grad-Spannweiten der Bounding-Box (großzügig, damit die Kandidatenmenge exakt bleibt).
    lat_span = max_km / 111.0 + 0.01
    coslat = math.cos(math.radians(lat))
    if abs(coslat) < 1e-6:
        lon_span = 360.0  # nahe Pol: alle Längengrade scannen
    else:
        lon_span = max_km / (111.0 * abs(coslat)) + 0.01

    ilat0 = math.floor(lat - lat_span) - 1
    ilat1 = math.floor(lat + lat_span) + 1
    if lon_span >= 180.0:
        ilon_range = range(-180, 180)
    else:
        ilon_range = range(math.floor(lon - lon_span) - 1, math.floor(lon + lon_span) + 2)

    # Bucket-Keys sammeln (Set gegen Duplikate durch Längengrad-Wraparound bei ±180).
    keys: set[tuple[int, int]] = set()
    for ilat in range(ilat0, ilat1 + 1):
        for ilon_raw in ilon_range:
            ilon = ((ilon_raw + 180) % 360) - 180
            keys.add((ilat, ilon))

    candidates: list[tuple[int, str, float, float]] = []
    for key in keys:
        bucket = grid.get(key)
        if bucket:
            candidates.extend(bucket)
    # Nach Einfüge-Index sortieren → identische Iterationsreihenfolge wie der Linearscan.
    candidates.sort(key=lambda t: t[0])

    best, best_d = None, max_km
    for _idx, icao, alat, alon in candidates:
        if icao in _CUSTOM_AIRPORTS:
            continue  # #56: von Custom überschattet (Override), airportsdata-Wert ignorieren
        d = haversine(lat, lon, alat, alon)
        if d <= best_d:
            best, best_d = icao, d
    # Ergänzungs-Flugplätze (#50/#56): nicht ins Grid einsortiert (würde die Cache-/Tie-Break-
    # Invariante der Funktion stören), stattdessen linear nachgeprüft — die Custom-Liste ist
    # klein (< 50 Einträge), das ist trivial. NACH airportsdata verglichen (identische
    # Nachrang-Reihenfolge wie nearest_airport_icao) → bei Distanz-Gleichstand gewinnt Custom.
    # #62: radius_km-Override analog zu nearest_airport_icao — Kandidat zählt auch jenseits von
    # max_km, gewinnt aber nur bei tatsächlich kürzerer Distanz als der bisher beste Treffer.
    for icao, (alat, alon, _elev, radius_km) in _CUSTOM_AIRPORTS.items():
        effective_radius = radius_km if radius_km is not None else max_km
        d = haversine(lat, lon, alat, alon)
        if d > effective_radius:
            continue
        if best is None or d <= best_d:
            best, best_d = icao, d
    return best


def airport_elevation_ft(icao: str) -> float | None:
    """Elevation (Höhe über MSL, in Fuß) eines Flugplatzes — oder None falls unbekannt.

    Verwendet das ``"elevation"``-Feld aus airportsdata (bereits in Fuß). ICAO ist
    case-insensitive (wie :func:`icao_to_coords`).
    """
    icao_upper = icao.upper()
    custom = _CUSTOM_AIRPORTS.get(icao_upper)
    if custom is not None:
        return float(custom[2]) if custom[2] is not None else None
    try:
        airport = _airports_icao().get(icao_upper)
    except Exception:
        return None
    if airport is not None:
        elev = airport.get("elevation")
        return float(elev) if elev is not None else None
    return None
