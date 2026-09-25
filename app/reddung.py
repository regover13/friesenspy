# -*- coding: utf-8 -*-
"""Die Parameter einer FriesenReddung: Fundradius, Ziele, Fenster.

Reine Rechnung, keine Datenbank -- alles hier nimmt ein Event-Dict und gibt Zahlen oder Ziele
zurück. Die Abdeckung selbst rechnet ``app/abdeckung.py``; dieses Modul entscheidet nur, MIT
WELCHEN Werten sie gerechnet wird.

**Suchen und Finden sind zwei Fenster, und das ist der Kern:**

======  ====================  ==================  ==========================================
         seitlich              Höhe (AGL)          Bedeutung
======  ====================  ==================  ==========================================
Suchen  ``korridor_km`` 1 km  ``hoehe_max_ft``    „Fläche abgeflogen" — was der Balken zählt
                              2.000 ft
Finden  ``fund_radius_m``     ``fund_hoehe_ft``   die Rauchfackel — dicht und tief drüber
        150 m                 1.000 ft
======  ====================  ==================  ==========================================

**„Abgesucht" heißt damit ausdrücklich NICHT „hätten wir ihn gesehen".** Die Fläche ist
abgeflogen; gesehen hätte man eine Cessna 172 erst aus 150 m. Das trägt, weil zu jedem Event
eine **Geschichte** gehört, die das Gebiet eingrenzt („über der Sandbank weggeblieben") — und
weil ein Suchkorridor von 150 m einen 40-km-Sektor auf 26 Flugstunden brächte.

⚠ **Drei verworfene Fassungen, damit keine davon wiederkommt** (alle am 20.09.2026):

1. **Fundradius GERECHNET** aus ``korridor + kante/√2`` (bei 1/1 km 1,71 km), damit volle
   Abdeckung den Fund garantiert. Die Garantie war schön und die Zahl falsch: **Eine Cessna 172
   sieht niemand aus 1,7 km.**
2. **Schrägabstand** -- Höhe und Seitenabstand in einem, also eine Kugel. Verworfen, weil er
   Höhe bestraft, obwohl man von oben weiter sieht: Bei 1.000 ft Radius und 1.000 ft Flughöhe
   bliebe null Spielraum zur Seite.
3. **Eigene Zahl ``fund_radius_ft``** (500 ft) neben dem Korridor. Verworfen, weil das dieselbe
   physikalische Größe zweimal einstellbar macht -- „der Suchsektor bestimmt doch die seitliche
   Reichweite schon" (Nutzer). Zwei Regler für eine Sache laufen später auseinander.

Bleibt eine Ungenauigkeit, die man kennen soll: Eine abgedeckte Zelle heißt „ein Track lief im
Korridor an ihrem MITTELPUNKT vorbei". In der Zellecke sind es bis zu 0,71 · Zellkante mehr.
Bei Kante gleich Korridor ist das ein Drittel Spielraum -- wer es genauer will, macht die Kante
kleiner als den Korridor.

**Die Höhenschranke ist AGL über dem Havaristen.** ``position_history.altitude`` ist MSL, also
wird die Grundhöhe der Unglücksstelle addiert -- das ist AGL über dem Wrack, nicht AGL unter
dem Flugzeug, und genau das ist die richtige Bezugsgröße für „ist er tief über der
Unglücksstelle hinweggeflogen?". Woher die Grundhöhe kommt (Messung der Brügge, Admin-Eingabe,
Platzhöhe) entscheidet ``app/database.py``; hier wird sie nur benutzt.

**Und fürs Aufnehmen gelten die Landeregeln des Projekts**, importiert statt abgeschrieben:
``_GPS_BLOCK_GS_KT`` und ``_GPS_GROUND_AGL_FT`` aus ``app/gps_legs.py``. ``detect_gps_legs``
selbst lässt sich nicht benutzen -- die Funktion verlangt für eine Landung einen Platz im
Umkreis („Kein Platz / AGL-Guard verletzt → bleibt AIRBORNE (Absturz/Hover nie als Landung)"),
und die Außenlandung am Wrack ist genau der Fall, den sie absichtlich nicht zählt.
"""
from __future__ import annotations

from app.abdeckung import Fenster, Ziel, zellen_aus_box
from app.gps_legs import _GPS_BLOCK_GS_KT, _GPS_GROUND_AGL_FT

#: Schlüssel des Havaristen in der Zielliste. Er ist ein gewöhnliches Ziel -- derselbe
#: Rechenweg wie für eine Rasterzelle, nur mit engerem Radius.
HAVARIST = "havarist"

#: Geschwindigkeit, unter der ein Schwebeflug gilt (Aufnehmen ohne Landung). Verlangt
#: praktisch einen Hubschrauber -- ein Flächenflugzeug kommt nicht darunter, ohne zu landen.
#: Ein Wasserflugzeug erfüllt die Bedingung ebenfalls, weil eine Wasserung unter 2 kt endet.
SCHWEBE_GS_KT = 30.0

_VORGABE_KANTE_KM = 1.0
_VORGABE_KORRIDOR_KM = 1.0
_VORGABE_HOEHE_FT = 2000.0
_VORGABE_GS_MAX_KT = 140.0
_VORGABE_GS_MIN_KT = 30.0


def _zahl(ev: dict, feld: str, vorgabe: float) -> float:
    wert = ev.get(feld)
    return float(wert) if wert is not None else float(vorgabe)


#: Seitliche Abstände stehen in METERN, Höhen in Fuß.
#:
#: Das ist keine Inkonsequenz, sondern die Sprache der Sache: In der Luft rechnet man Höhen in
#: Fuß, am Boden Entfernungen in Metern. Der Fundradius stand eine Stunde lang in Fuß
#: (500 ft) -- Nutzerentscheidung vom 20.09.2026, er steht jetzt in Metern.
_VORGABE_FUND_RADIUS_M = 150.0
_VORGABE_FUND_HOEHE_FT = 1000.0


def korridor_km(ev: dict) -> float:
    """Die seitliche Reichweite fürs SUCHEN — was der Fortschrittsbalken zählt."""
    return _zahl(ev, "korridor_km", _VORGABE_KORRIDOR_KM)


def kante_km(ev: dict) -> float:
    """Die Zellkante des Rasters — die Feinheit der Buchhaltung, nie größer als der Korridor."""
    return _zahl(ev, "kante_km", _VORGABE_KANTE_KM)


def fund_radius_m(ev: dict) -> float:
    """Die seitliche Reichweite fürs FINDEN in METERN — deutlich enger als der Suchkorridor."""
    return _zahl(ev, "fund_radius_m", _VORGABE_FUND_RADIUS_M)


def fund_radius_km(ev: dict) -> float:
    return fund_radius_m(ev) / 1000.0


def fund_hoehe_schranke_msl(ev: dict) -> float:
    """Die Höhenschranke fürs FINDEN, auf MSL umgerechnet."""
    return grund_ft(ev) + _zahl(ev, "fund_hoehe_ft", _VORGABE_FUND_HOEHE_FT)


def fenster_finden(ev: dict) -> Fenster:
    """Eng und tief. Das Geschwindigkeitsfenster ist dasselbe wie beim Suchen -- wer parkt,
    findet nicht, und wer rast, sieht nichts."""
    return Fenster(
        hoehe_max_ft=fund_hoehe_schranke_msl(ev),
        gs_max_kt=_zahl(ev, "gs_max_kt", _VORGABE_GS_MAX_KT),
        gs_min_kt=_zahl(ev, "gs_min_kt", _VORGABE_GS_MIN_KT),
    )


def grund_ft(ev: dict) -> float:
    """Geländehöhe (MSL) an der Unglücksstelle; 0, solange nichts bekannt ist."""
    return _zahl(ev, "havarist_grund_ft", 0.0)


def hoehe_schranke_msl(ev: dict) -> float:
    """Die AGL-Schranke, auf MSL umgerechnet -- so kommt die Höhe aus position_history."""
    return grund_ft(ev) + _zahl(ev, "hoehe_max_ft", _VORGABE_HOEHE_FT)


def zellen_fuer(ev: dict) -> list[Ziel]:
    """Das Zellraster des Sektors. Kante gleich Korridor ergibt ein lückenloses Raster."""
    return zellen_aus_box(
        float(ev["sued"]), float(ev["west"]), float(ev["nord"]), float(ev["ost"]),
        kante_km=kante_km(ev),
        korridor_km=_zahl(ev, "korridor_km", _VORGABE_KORRIDOR_KM),
    )


def havarist_ziel(ev: dict) -> Ziel | None:
    """Der Havarist als Kreisziel — mit dem engen FUNDRADIUS, nicht mit dem Suchkorridor.

    ``None``, solange kein Ort gesetzt ist.
    """
    lat, lon = ev.get("havarist_lat"), ev.get("havarist_lon")
    if lat is None or lon is None:
        return None
    return (HAVARIST, float(lat), float(lon), fund_radius_km(ev))


def fenster_suchen(ev: dict) -> Fenster:
    """Tief und langsam -- und nicht im Stillstand: Die Untergrenze verhindert, dass ein
    geparktes Flugzeug seine Zelle den ganzen Abend abdeckt."""
    return Fenster(
        hoehe_max_ft=hoehe_schranke_msl(ev),
        gs_max_kt=_zahl(ev, "gs_max_kt", _VORGABE_GS_MAX_KT),
        gs_min_kt=_zahl(ev, "gs_min_kt", _VORGABE_GS_MIN_KT),
    )


def fenster_aufnehmen(ev: dict) -> Fenster:
    """Fürs Aufnehmen: die Landeregeln des Projekts, und ``gs_min_kt`` MUSS 0 sein.

    ⚠ Die Untergrenze des Suchfensters (30 kt) würde hier genau den Stillstand ausschließen,
    der gefragt ist. Das ist der Fallstrick dieser Funktion.
    """
    mit_landung = bool(ev.get("landung_noetig", 1))
    return Fenster(
        hoehe_max_ft=grund_ft(ev) + _GPS_GROUND_AGL_FT,
        gs_max_kt=float(_GPS_BLOCK_GS_KT) if mit_landung else SCHWEBE_GS_KT,
        gs_min_kt=0.0,
    )


#: So weit darf der naechste Platz von der Sektormitte weg sein, damit die Event-Analyse ihn
#: nimmt. Liegt keiner so nah (Sektor auf offener See), sucht sie global.
_ANALYSE_PLATZ_MAX_KM = 150.0


def analyse_platz(ev: dict) -> dict:
    """Platz und Radius für die Event-Analyse der Bilanz: ``{"icao", "radius_km"}``.

    Bummel und Kutter füllen die Event-Analyse mit ihren Streckenplätzen -- eine Reddung hat
    keine. Ersatz: der nächste Platz zur Sektormitte und ein Radius, der von dort den ganzen
    Sektor erfasst (Nutzer, 25.09.2026: „zeigt keine tracks an"). Findet sich kein Platz in
    Reichweite, ``{"icao": "global", "radius_km": None}``.

    Nur aus dem Sektor gerechnet -- der ist öffentlich. Die Lage des Havaristen geht nicht ein.
    """
    import math
    from app import geo
    sued, nord = sorted((float(ev["sued"]), float(ev["nord"])))
    west, ost = sorted((float(ev["west"]), float(ev["ost"])))
    mlat, mlon = (sued + nord) / 2.0, (west + ost) / 2.0
    icao = geo.nearest_airport_icao_fast(mlat, mlon, _ANALYSE_PLATZ_MAX_KM)
    lage = geo.icao_to_coords(icao) if icao else None
    if not lage:
        return {"icao": "global", "radius_km": None}
    weitest = max(geo.haversine(lage[0], lage[1], lat, lon)
                  for lat in (sued, nord) for lon in (west, ost))
    # Etwas Rand: Wer knapp ausserhalb wendet, gehoert trotzdem zum Abend.
    return {"icao": icao, "radius_km": int(math.ceil(weitest + 5.0))}

