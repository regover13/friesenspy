"""Bahnschwellen als Referenz fuer die Flugplatzkarten-Passung.

Quelle ist OurAirports -- dieselbe, die ``scripts/nearby_airports.py`` schon benutzt. Es
kommt also kein neuer Lieferant hinzu, nur eine zweite Datei desselben.

**OpenAIP scheidet aus.** Es liefert keine Schwellenkoordinaten, sondern nur ``trueHeading``
-- fuer EDDL den Wert 50 bei tatsaechlich 052,7 Grad. Drei Grad sind auf 3 km Bahnlaenge
150 m; als Passreferenz ist das unbrauchbar.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 5.1
"""
from __future__ import annotations

import csv
import logging
import math
import time
from collections import namedtuple
from pathlib import Path

logger = logging.getLogger(__name__)

Bahn = namedtuple("Bahn", "name le he laenge kurs")

URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
HOECHSTALTER_S = 30 * 24 * 3600

_SCHWELLEN = ("le_latitude_deg", "le_longitude_deg", "he_latitude_deg", "he_longitude_deg")


def meter_je_grad(lat: float) -> tuple[float, float]:
    """Meter je Grad Laenge und Breite auf dieser Breite.

    **Nicht mit festen Werten rechnen.** Der Prototyp benutzte 110540 fuer die Breite --
    das ist der Aequatorwert; der Meridiangrad betraegt bei 47,5 bis 55 Grad Nord aber
    111 181 bis 111 324 m, ein Fehler von 0,58 bis 0,70 Prozent. Zusammen mit dem
    Laengengrad-Fehler von 0,2 Prozent ergibt das eine **Anisotropie von rund 0,45 Prozent,
    die eine Aehnlichkeitstransformation prinzipiell nicht absorbieren kann**: bis zu 5 m
    auf einem grossflaechigen Platz, also ein Drittel der 15-m-Schranke, voellig ohne Not.

    Die Reihen sind die ueblichen Naeherungen fuer das WGS84-Ellipsoid.
    """
    p = math.radians(lat)
    breite = 111132.95 - 559.82 * math.cos(2 * p) + 1.175 * math.cos(4 * p)
    laenge = 111412.84 * math.cos(p) - 93.5 * math.cos(3 * p)
    return laenge, breite


def meter(von: tuple[float, float], nach: tuple[float, float]) -> tuple[float, float]:
    """Ost- und Nordabstand zweier Punkte in Metern.

    Die Breite wird je Punktpaar gebildet, nicht einmal fest fuer den ganzen Platz: Ueber
    3 km Nordausdehnung sind das sonst rund 2 m Scherung.
    """
    m_lon, m_lat = meter_je_grad((von[0] + nach[0]) / 2.0)
    return ((nach[1] - von[1]) * m_lon, (nach[0] - von[0]) * m_lat)


def bahnen(icao: str, datei: Path | str) -> list[Bahn]:
    """Alle offenen Bahnen des Platzes, die beide Schwellenkoordinaten tragen."""
    code = (icao or "").strip().upper()
    aus: list[Bahn] = []
    with open(datei, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("airport_ident") or "").upper() != code or r.get("closed") == "1":
                continue
            if not all(r.get(k) for k in _SCHWELLEN):
                continue
            le = (float(r["le_latitude_deg"]), float(r["le_longitude_deg"]))
            he = (float(r["he_latitude_deg"]), float(r["he_longitude_deg"]))
            ost, nord = meter(le, he)
            aus.append(Bahn(name=f"{r['le_ident']}/{r['he_ident']}", le=le, he=he,
                            laenge=math.hypot(ost, nord),
                            kurs=math.degrees(math.atan2(ost, nord)) % 360))
    return aus


def datei_holen(ziel: Path, hole=None) -> Path:
    """runways.csv besorgen, wenn die Ablage fehlt oder aelter als 30 Tage ist.

    **Der Ablageort gehoert neben die Datenbank**, nicht nach ``scripts/.cache/`` wie bei
    ``nearby_airports.py``. Jenes Verzeichnis steht in ``.gitignore`` und ist im Container
    eine Image-Schicht: bei jedem Deploy weg, also bei jedem Containerstart neu zu laden.

    Faellt die Quelle aus, bleibt eine vorhandene Datei in Gebrauch -- dieselbe Regel wie
    bei einem fehlgeschlagenen Blattabruf: Ein Netzfehler entwertet keinen Bestand.
    """
    ziel = Path(ziel)
    if ziel.is_file() and time.time() - ziel.stat().st_mtime < HOECHSTALTER_S:
        return ziel
    if hole is None:
        import httpx

        def hole(url: str) -> str:
            r = httpx.get(url, timeout=90.0, follow_redirects=True)
            r.raise_for_status()
            return r.text
    try:
        text = hole(URL)
    except Exception as e:
        if ziel.is_file():
            logger.warning("runways.csv nicht erreichbar (%s) -- alte Ablage bleibt",
                           str(e)[:60])
            return ziel
        raise
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ziel)
    return ziel
