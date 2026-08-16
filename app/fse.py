"""FSE-Weltbestand: im Speicher halten und den Kartenausschnitt daraus schneiden.

Warum ein eigenes Modul und keine zwei Funktionen in main.py: Der Bestand ist Zustand mit
eigener Lebensdauer (einmal beim Start gelesen, danach nur gelesen), und die Filterlogik ist
die einzige Stelle im Projekt mit Geometrie-Entscheidungen, die man gegen Messwerte pruefen
will. Beides gehoert nicht zwischen die Endpunkt-Definitionen.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# Deckel in PUNKTEN, nicht in Stueck: Ein Platz ist ein CircleMarker mit 1 Punkt, eine Zone ein
# Polygon mit im Mittel 7 (max 21). Bei New York stellen die Zonen damit 88 % der Zeichenlast
# -- ein Stueckzahl-Deckel wuerde beide gleich behandeln und die falsche Ebene schonen. Die
# Werte sind gegen Coherent GT gewaehlt (s. main.py: "ab ein paar hundert Elementen zaeh") und
# stehen zur Korrektur, sobald die Panel-Selbstdiagnose Canvas misst.
MAX_PUNKTE_PLAETZE = 250
MAX_PUNKTE_ZONEN = 900
# Obergrenze fuer den angefragten Radius, gespiegelt aus /api/traffic.
MAX_KM = 250

_ERD_KM_JE_GRAD = 111.32

# Rechteck des angefragten Ausschnitts: (lat_min, lat_max, lon_min, lon_max).
Rechteck = tuple


@dataclass
class FseBestand:
    plaetze: dict = field(default_factory=dict)
    # Schlichte Punktlisten. Sie vorserialisiert zu halten war erwogen und gemessen verworfen:
    # json.load baut die Listen ohnehin, bevor irgendetwas daraus abgeleitet werden kann -- die
    # Zeichenketten kaemen obendrauf, und der freigegebene Listenspeicher geht nicht ans
    # Betriebssystem zurueck (mit malloc_trim gegengeprueft). Gemessen 55,3 statt 50,8 MB,
    # also 4,5 MB TEURER (s. Spec 2026-08-16, Abschnitt 4). Der Bestand haelt insgesamt
    # 49,7 MB -- aber nur, weil _auf_einen_zweig unveraenderte Listen durchreicht; ohne das
    # waeren es 70,7 MB (Review-Fund 16.08.2026).
    zonen: dict = field(default_factory=dict)
    zonen_bbox: dict = field(default_factory=dict)


def _auf_einen_zweig(punkte):
    """Alle Ecken auf den Laengen-Zweig der ERSTEN Ecke ziehen.

    36 Zonen tragen Laengen jenseits +-180. 34 davon sind durchgehend (NFNA 175,98 -> 181,65)
    und zeichnen sich ueber die Datumsgrenze korrekt -- sie muessen unangetastet bleiben.
    Pauschales Normalisieren auf +-180 machte aus jeder von ihnen ein Band quer ueber die
    Karte, also genau den Fehler, der hier behoben werden soll.

    Neu gebaut wird die Liste deshalb NUR, wenn sich wirklich etwas aendert. Der Unterschied
    ist kein Rechenaufwand, sondern Speicher: Ein bedingungsloser Neubau erzeugt 23.780 frische
    Listenstrukturen, waehrend die Rohdaten noch leben -- und den Verschnitt gibt der Allokator
    nicht ans Betriebssystem zurueck. Gemessen (VmRSS nach gc.collect und malloc_trim,
    Python 3.12): 70,7 MB bedingungslos, 49,8 MB so. 21 MB fuer zwei geaenderte Zonen.
    """
    basis = punkte[0][1]
    # round() liefert genau dann 0, wenn die Differenz in [-180, 180] liegt -- die Bedingung
    # deckt sich also exakt mit "die Umrechnung waere wirkungslos".
    if all(-180.0 <= p[1] - basis <= 180.0 for p in punkte):
        return punkte
    return [[p[0], p[1] - 360.0 * round((p[1] - basis) / 360.0)] for p in punkte]


def _polzelle(punkte) -> bool:
    """Umschliesst dieses Polygon einen Pol?

    Genau zwei tun das: CYLT (Alert, Nordpol) und NZPG (McMurdo, Suedpol). Ihre Ecken laufen
    einmal ganz um die Erde -- CYLT von 103 Grad Ost ueber 0 und -63 nach -189 (also 171 Ost)
    und zurueck nach 110 Ost. So ein Ring hat in Laenge/Breite KEINE nahtfreie Darstellung:
    Auf welchen Zweig man die Ecken auch zieht, es bleibt ein Sprung von fast 360 Grad, und
    Leaflet zieht daraus ein Band quer ueber die ganze Karte. Bei CYLT bringt die
    Zweig-Korrektur die Spanne nur von 342 auf 234 Grad.

    Deshalb werden diese beiden gar nicht erst ausgeliefert. Der Preis ist klein und benannt:
    In den Breitenbaendern der zwei Zellen liegen zusammen 12 der 23.780 Plaetze; dort fehlt
    die Landeflaeche des Pol-Platzes. Das Band dagegen erschiene bei JEDER Abfrage in diesen
    Baendern, weil die Bbox fast den ganzen Laengenbereich abdeckt.

    Erkannt wird datengetrieben statt ueber eine ICAO-Liste: Was nach der Zweig-Korrektur
    immer noch mehr als 180 Grad spannt, kann kein zusammenhaengendes Gebiet auf einer Karte
    sein.
    """
    laengen = [p[1] for p in punkte]
    return max(laengen) - min(laengen) > 180.0


def laden(verzeichnis: Path) -> FseBestand:
    plaetze = json.loads((verzeichnis / "fse_airports_world.json").read_text(encoding="utf-8"))
    rohzonen = json.loads((verzeichnis / "fse_zones_world.json").read_text(encoding="utf-8"))
    b = FseBestand(plaetze=plaetze)
    for icao, roh in rohzonen.items():
        punkte = _auf_einen_zweig(roh)
        if _polzelle(punkte):
            continue
        b.zonen[icao] = punkte
        breiten = [p[0] for p in punkte]
        laengen = [p[1] for p in punkte]
        b.zonen_bbox[icao] = (min(breiten), max(breiten), min(laengen), max(laengen))
    return b


def _rechteck(lat: float, lon: float, r_km: float):
    """Der Ausschnitt als Bbox. cos(lat) wird nach unten gekappt, sonst wird das Rechteck an
    den Polen unendlich breit.

    Rechnet NICHT ueber die Datumsgrenze -- bekannter Rest, s. Spec Abschnitt 10 (14 von
    23.780 Plaetzen: Fiji, Neuseeland, Marshallinseln, Aleuten).
    """
    dlat = r_km / _ERD_KM_JE_GRAD
    dlon = r_km / (_ERD_KM_JE_GRAD * max(0.05, math.cos(math.radians(lat))))
    return (lat - dlat, lat + dlat, lon - dlon, lon + dlon)


def _entfernung_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Aequirektangulaere Naeherung. Auf 250 km liegt ihr Fehler unter einem Promille, und
    gebraucht wird sie nur zum Sortieren und Kappen -- Haversine waere hier Rechenzeit ohne
    Wirkung."""
    dlat = (lat2 - lat1) * _ERD_KM_JE_GRAD
    dlon = (lon2 - lon1) * _ERD_KM_JE_GRAD * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def plaetze_im_umkreis(bestand: FseBestand, lat: float, lon: float, r_km: float):
    r_km = min(r_km, MAX_KM)
    la0, la1, lo0, lo1 = _rechteck(lat, lon, r_km)
    nah = []
    for icao, a in bestand.plaetze.items():
        if la0 <= a["lat"] <= la1 and lo0 <= a["lon"] <= lo1:
            nah.append((_entfernung_km(lat, lon, a["lat"], a["lon"]), icao))
    gekappt = len(nah) > MAX_PUNKTE_PLAETZE
    if gekappt:
        nah.sort()
        nah = nah[:MAX_PUNKTE_PLAETZE]
    return {icao: bestand.plaetze[icao] for _, icao in nah}, gekappt


def _bbox_abstand_km(bbox, lat: float, lon: float, cos_lat: float) -> float:
    """Abstand des BEZUGSPUNKTS zur Zonen-Bbox.

    Zwei Entscheidungen stecken hier drin.

    (1) Gemessen wird vom PUNKT, nicht vom Ausschnitts-RECHTECK. Gegen das Rechteck hat JEDE
    schneidende Zone Abstand 0 -- bei New York sind das 389 Stueck -- und der Deckel
    entschiede zwischen ihnen alphabetisch. Die Zelle, in der man steht, flog dabei
    nachweislich heraus. Vom Punkt aus hat nur sie 0, alle anderen wachsen mit ihrer
    Entfernung.

    (2) Gemessen wird zur BBOX der Zone, nicht zur Position ihres Flugplatzes. Die frueher
    hier stehende Begruendung -- "sonst fiele die Zelle heraus, in der man steht" -- war
    FALSCH und ist am 16.08.2026 in einem Review widerlegt worden: Die Zonen sind
    Voronoi-Zellen, die umschliessende gehoert also per Definition dem naechstgelegenen
    Flugplatz und stuende auch nach Flugplatzentfernung ganz vorn (an 131 von 131 geprueften
    Punkten bestaetigt). Der echte Grund ist ein anderer: Die Bbox haelt auch die grossen
    NACHBARzellen im Bild, deren Flugplatz weit ausserhalb liegt -- ueber dem Ozean gerade
    die, die die graue Kulisse lueckenlos machen.

    cos(lat) kommt von aussen: es ist ueber die ganze Anfrage konstant, und es je Zone neu zu
    berechnen (23.780-mal cos/radians) kostet fast die Haelfte der Anfragezeit.
    """
    dlat = max(bbox[0] - lat, lat - bbox[1], 0.0)
    dlon = max(bbox[2] - lon, lon - bbox[3], 0.0)
    return math.hypot(dlat * _ERD_KM_JE_GRAD, dlon * _ERD_KM_JE_GRAD * cos_lat)


def zonen_im_umkreis(bestand: FseBestand, lat: float, lon: float, r_km: float):
    r_km = min(r_km, MAX_KM)
    la0, la1, lo0, lo1 = _rechteck(lat, lon, r_km)
    cos_lat = math.cos(math.radians(lat))
    treffer = []
    for icao, bb in bestand.zonen_bbox.items():
        # Reiner Bbox-Schnitt, kein exakter Polygontest: gemessen liefert er bei Wangerooge
        # 90 von 90 und bei New York 389 von 389 identisch, im Nordatlantik eine Zone weniger.
        if bb[1] < la0 or bb[0] > la1 or bb[3] < lo0 or bb[2] > lo1:
            continue
        treffer.append((_bbox_abstand_km(bb, lat, lon, cos_lat), icao))
    treffer.sort()
    ausgabe = {}
    punkte = 0
    gekappt = False
    for _, icao in treffer:
        kosten = len(bestand.zonen[icao])
        if punkte + kosten > MAX_PUNKTE_ZONEN:
            gekappt = True
            # Nicht abbrechen, sondern ueberspringen: Eine 21-Punkte-Zelle mitten in der Liste
            # duerfte sonst alles Kleinere dahinter mitreissen und Budget verschenken.
            continue
        ausgabe[icao] = bestand.zonen[icao]
        punkte += kosten
    return ausgabe, gekappt
