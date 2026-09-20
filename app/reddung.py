# -*- coding: utf-8 -*-
"""Die Parameter einer FriesenReddung: Fundradius, Ziele, Fenster.

Reine Rechnung, keine Datenbank -- alles hier nimmt ein Event-Dict und gibt Zahlen oder Ziele
zurück. Die Abdeckung selbst rechnet ``app/abdeckung.py``; dieses Modul entscheidet nur, MIT
WELCHEN Werten sie gerechnet wird.

**Der Fundradius wird gerechnet, nicht eingestellt.** Eine abgedeckte Zelle heißt „ein Track
lief im Korridor an ihrem MITTELPUNKT vorbei"; ein Havarist in der Zellecke ist noch die halbe
Zelldiagonale weiter weg. Mit ``korridor + kante/√2`` gilt dagegen: jede abgedeckte Zelle
bedeutet „hier hätten wir ihn gesehen", und volle Abdeckung garantiert den Fund. Wäre der
Radius einstellbar, könnte der Admin einen Fortschrittsbalken erzeugen, der lügt.

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

import math

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
_VORGABE_HOEHE_FT = 1000.0
_VORGABE_GS_MAX_KT = 140.0
_VORGABE_GS_MIN_KT = 30.0


def _zahl(ev: dict, feld: str, vorgabe: float) -> float:
    wert = ev.get(feld)
    return float(wert) if wert is not None else float(vorgabe)


def fundradius_km(korridor_km: float, kante_km: float) -> float:
    """Korridor plus halbe Zelldiagonale -- s. Modulkopf. Bei 1,0/1,0 km sind das 1,71 km."""
    return float(korridor_km) + float(kante_km) / math.sqrt(2.0)


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
        kante_km=_zahl(ev, "kante_km", _VORGABE_KANTE_KM),
        korridor_km=_zahl(ev, "korridor_km", _VORGABE_KORRIDOR_KM),
    )


def havarist_ziel(ev: dict) -> Ziel | None:
    """Der Havarist als gewöhnliches Kreisziel. ``None``, solange kein Ort gesetzt ist."""
    lat, lon = ev.get("havarist_lat"), ev.get("havarist_lon")
    if lat is None or lon is None:
        return None
    radius = fundradius_km(_zahl(ev, "korridor_km", _VORGABE_KORRIDOR_KM),
                           _zahl(ev, "kante_km", _VORGABE_KANTE_KM))
    return (HAVARIST, float(lat), float(lon), radius)


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
