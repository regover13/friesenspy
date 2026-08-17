"""Meldepunkte (VRP) aus OpenAIP: einmal holen, im Speicher halten, im Ausschnitt liefern.

Warum ein eigenes Modul und keine zwei Funktionen in main.py: derselbe Grund wie bei
``app/fse.py`` — der Bestand ist Zustand mit eigener Lebensdauer, und der Zuschnitt auf den
Kartenausschnitt ist die Sorte Geometrie, die man gegen Messwerte prüfen will.

**Warum der Bestand hier abgerufen und NICHT als Datei ins Repo gelegt wird** (Abweichung von
der Spec vom 16.08.2026, Abschnitt 2.3): Das FSE-Vorbild liegt im Repo, weil seine Quelle ein
GitHub-Repo ohne Schlüssel ist — jeder kann sie ziehen, auch die Entwicklungssitzung. OpenAIP
verlangt einen Schlüssel, und der steht ausschließlich in ``config.env`` auf dem Server. Ein
Abzug im Repo hieße: Er kann nur dort erzeugt werden, wo der Schlüssel liegt, und muss von Hand
nachgezogen werden, damit er nicht veraltet. Der Server kann beides selbst — er hat den
Schlüssel, und er hat mit dem Datenverzeichnis eine Ablage, die den Container überlebt.

Damit gilt weiterhin alles, was für den Abzug sprach: Der Schlüssel bleibt im Server (die
Kachel-URL im Browser lässt sich nicht vermeiden, diese Abfrage schon), die Ratenbegrenzung der
API sieht genau einen Abruf im Monat statt einen je Kartenbewegung, und der Browser bekommt nie
mehr als den Ausschnitt.

Lizenz der Daten: CC BY-NC 4.0. Die Namensnennung passiert im Frontend, sobald die Ebene an
ist — auch dann, wenn der OpenAIP-Kachel-Layer aus ist (der bringt seine eigene mit).
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.core.openaip.net/api/reporting-points"
# Der Schlüssel geht als HEADER raus, nicht als Query-Parameter. Beides ist erlaubt (s.
# OpenAPI-Schema), aber eine URL landet im Zweifel in einem Log oder einer Fehlermeldung.
_KEY_HEADER = "x-openaip-api-key"
# Vorgabe der API ist ebenfalls 1000; ausgeschrieben, damit die Seitenzahl im Log erklärbar ist.
_SEITE = 1000
# Nur was gezeichnet wird. Ohne diese Auswahl kämen createdBy, updatedAt und Konsorten mit —
# Ballast auf jeder einzelnen Seite.
_FELDER = "name,compulsory,geometry,elevation"
# Nach so vielen Seiten wird abgebrochen. Kein erwarteter Fall (weltweit sind es deutlich
# weniger), sondern eine Bremse gegen eine API, die endlos `nextPage` meldet.
_MAX_SEITEN = 200

# Obergrenze für den angefragten Radius, gespiegelt aus /api/traffic und app/fse.py.
MAX_KM = 250
# Deckel in Stück, nicht in Punkten wie bei FSE: Ein Meldepunkt ist immer genau ein Marker mit
# einer Beschriftung, es gibt hier keine zweite Ebene mit anderer Zeichenlast. 300 ist an den
# FSE-Plätzen (250 Marker) ausgerichtet und darf nach der ersten Messung im Kniebrett wandern.
MAX_PUNKTE = 300

_ERD_KM_JE_GRAD = 111.32
_METER_JE_FUSS = 0.3048


@dataclass
class VrpBestand:
    """Ein Punkt ist ``(name, lat, lon, meldepflichtig, hoehe_ft|None)``.

    Tupel statt Wörterbüchern: Die Feldnamen wären bei jedem einzelnen noch einmal im Speicher.
    Nach außen (``punkte_im_umkreis``) werden daraus benannte Felder — dort sind es höchstens
    ein paar hundert.

    Gemessen 17.08.2026: **6.121 Punkte weltweit**, 334 KB in der Ablage, rund 1,2 MB im
    Speicher. Deutlich weniger als die „einigen zehntausend", von denen dieser Kommentar bis
    dahin ausging — der Abruf ist trotzdem vollständig, die API meldet denselben
    ``totalCount``. Der Bestand ist stark europalastig (Europa 4.683, Südamerika 1.017,
    Nordamerika 2); Einzelheiten in der Spec vom 16.08.2026, Abschnitt 5.2.
    """

    punkte: list = field(default_factory=list)
    stand: str = ""


def _hoehe_ft(elevation) -> int | None:
    """OpenAIP liefert Meter über MSL (``unit: 0``). Gezeigt werden Fuß.

    Fehlt die Angabe oder trägt sie wider Erwarten eine andere Einheit, gibt es keine Höhe.
    Eine umgerechnete Zahl aus unbekannter Einheit wäre schlimmer als gar keine.
    """
    if not isinstance(elevation, dict):
        return None
    wert = elevation.get("value")
    if not isinstance(wert, (int, float)) or elevation.get("unit") != 0:
        return None
    return round(wert / _METER_JE_FUSS)


def _punkt_aus(eintrag: dict):
    """Einen API-Eintrag in die Speicherform bringen — oder ``None``, wenn er unbrauchbar ist."""
    name = (eintrag.get("name") or "").strip()
    geo = eintrag.get("geometry") or {}
    koord = geo.get("coordinates")
    if not name or geo.get("type") != "Point" or not isinstance(koord, list) or len(koord) < 2:
        return None
    lon, lat = koord[0], koord[1]
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return (name, float(lat), float(lon), bool(eintrag.get("compulsory")), _hoehe_ft(eintrag.get("elevation")))


async def abrufen(api_key: str, *, laender: list[str] | None = None,
                  client: httpx.AsyncClient | None = None) -> list:
    """Alle Meldepunkte seitenweise holen.

    ``laender`` (ISO-2) schneidet den Abruf zu — gedacht für die Entwicklung. Ohne Angabe
    kommt der Weltbestand, und das ist die Auslieferung: In Deutschland fliegt der Nutzer mit
    der OpenFlightMap, OpenAIP ist die Karte für den Rest der Welt (Entscheidung 16.08.2026).

    Bewusst NICHT über den ``bbox``-Parameter: Der ist laut Doku „mainly intended for export
    use-cases" und antwortet bei Überlastung mit 429.
    """
    eigener = client is None
    if eigener:
        client = httpx.AsyncClient(timeout=60.0)
    punkte: list = []
    try:
        for land in (laender or [None]):
            seite = 1
            while seite <= _MAX_SEITEN:
                frage = {"page": seite, "limit": _SEITE, "fields": _FELDER}
                if land:
                    frage["country"] = land
                antwort = await client.get(_API_URL, params=frage,
                                           headers={_KEY_HEADER: api_key})
                antwort.raise_for_status()
                daten = antwort.json()
                for eintrag in daten.get("items") or []:
                    p = _punkt_aus(eintrag)
                    if p:
                        punkte.append(p)
                if not daten.get("nextPage"):
                    break
                seite += 1
    finally:
        if eigener:
            await client.aclose()
    return punkte


def speichern(pfad: Path, punkte: list, stand: str) -> None:
    """Atomar schreiben: erst daneben, dann umbenennen.

    Ein abgebrochener Schreibvorgang hinterließe sonst eine halbe Datei, die beim nächsten
    Start nicht parst — und die Ebene wäre still weg, bis jemand nachsieht.
    """
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = pfad.with_suffix(pfad.suffix + ".neu")
    temp.write_text(json.dumps({"stand": stand, "punkte": punkte}, ensure_ascii=False),
                    encoding="utf-8")
    temp.replace(pfad)


def laden(pfad: Path) -> VrpBestand:
    """Den abgelegten Bestand lesen. Fehlt er oder ist er kaputt, bleibt der Bestand leer.

    Kein Ausnahmefehler nach oben: Ohne Meldepunkte läuft die Anwendung vollständig weiter,
    nur die Ebene bleibt leer — genauso wie ohne OpenAIP-Schlüssel die Kachel-Ebene fehlt.
    """
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return VrpBestand()
    except (OSError, ValueError):
        logger.warning("Meldepunkte: %s ist nicht lesbar — Ebene bleibt leer", pfad)
        return VrpBestand()
    punkte = [tuple(p) for p in roh.get("punkte") or [] if isinstance(p, list) and len(p) == 5]
    return VrpBestand(punkte=punkte, stand=str(roh.get("stand") or ""))


def _rechteck(lat: float, lon: float, r_km: float):
    """Grobes Vorfilter-Rechteck um den Bezugspunkt (wie in app/fse.py)."""
    d_lat = r_km / _ERD_KM_JE_GRAD
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    d_lon = r_km / (_ERD_KM_JE_GRAD * cos_lat)
    return lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon


def _entfernung_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Reicht für „welcher Punkt ist näher" — keine Großkreisrechnung nötig."""
    dy = (lat2 - lat1) * _ERD_KM_JE_GRAD
    dx = (lon2 - lon1) * _ERD_KM_JE_GRAD * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def punkte_im_umkreis(bestand: VrpBestand, lat: float, lon: float, r_km: float):
    """Die Meldepunkte im Kartenausschnitt, gedeckelt.

    Der Schlüssel im Ergebnis ist die Position im Bestand. Er ist innerhalb einer Serverlaufzeit
    stabil, und genau das braucht der Abgleich im Browser: Was in zwei aufeinanderfolgenden
    Antworten steht, bleibt unangetastet — sonst flackern die Beschriftungen bei jedem
    Nachladen im Flug. Der Name taugt dafür nicht, den gibt es weltweit vielfach (allein
    „NOVEMBER" hunderte Male).

    ``gekappt`` meldet, dass der Nutzer eine Scheibe statt des vollen Rechtecks sieht —
    dieselbe Zusage wie beim Verkehr und bei FSE.
    """
    r_km = min(r_km, MAX_KM)
    la0, la1, lo0, lo1 = _rechteck(lat, lon, r_km)
    nah = []
    for i, (_, plat, plon, _, _) in enumerate(bestand.punkte):
        if la0 <= plat <= la1 and lo0 <= plon <= lo1:
            nah.append((_entfernung_km(lat, lon, plat, plon), i))
    gekappt = len(nah) > MAX_PUNKTE
    if gekappt:
        nah.sort()
        nah = nah[:MAX_PUNKTE]
    ergebnis = {}
    for _, i in nah:
        name, plat, plon, pflicht, hoehe = bestand.punkte[i]
        ergebnis[str(i)] = {"n": name, "y": plat, "x": plon, "c": 1 if pflicht else 0,
                            "e": hoehe}
    return ergebnis, gekappt


# ---------------------------------------------------------------------------
# Der Bestand als Modulzustand
# ---------------------------------------------------------------------------
# Nicht in app.state wie bei FSE: Der Auffrischungs-Job hängt im Poller, und der kennt die
# FastAPI-App nicht. Ein Modulattribut ist die kleinste Lösung, die beide Seiten erreichen —
# und der Austausch ist atomar (eine Zuweisung), es gibt also keinen Moment, in dem eine
# Anfrage einen halb ersetzten Bestand sieht.
_BESTAND = VrpBestand()


def bestand() -> VrpBestand:
    return _BESTAND


def bestand_setzen(neu: VrpBestand) -> None:
    global _BESTAND
    _BESTAND = neu


def pfad_fuer(db_pfad: str) -> Path:
    """Neben der Datenbank, also im Datenverzeichnis — das überlebt den Container."""
    return Path(db_pfad).resolve().parent / "vrp_openaip.json"


def aus_ablage_laden(db_pfad: str) -> VrpBestand:
    b = laden(pfad_fuer(db_pfad))
    bestand_setzen(b)
    return b
