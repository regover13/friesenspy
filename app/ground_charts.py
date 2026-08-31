"""DFS-Flugplatzkarten: Blattkunde und Handpassung.

**Diese Karten werden von Hand gepasst.** Das ist eine Entscheidung, keine Notloesung.

Ein erster Anlauf hat versucht, die Lage automatisch aus der Bahngeometrie zu rechnen --
graue Bahnflaechen im Bild vermessen, Achsen bestimmen, gegen die Schwellenkoordinaten von
OurAirports ausgleichen. Das Verfahren funktioniert, wo es funktioniert: EDDM auf 1,5 m,
EDDP auf 2,9 m, EDDL auf 5,3 m. Aber es kam ueber **drei von 107 Plaetzen mit Kartenblatt**
nicht hinaus, und die Gruende sind strukturell:

* **271 der 446 Plaetze haben in OurAirports keine Schwellenkoordinaten.** Ohne Referenz
  ist nichts zu rechnen.
* Stopways und Blast Pads sind in derselben Grauabstufung gezeichnet wie die Bahn und
  werden mitgemessen -- bei EDDV 2784 m fuer eine 2340-m-Bahn, bei EDDS 6759 m fuer 3345 m.
* Wo nur EINE Bahn erkennbar ist, gibt es zwei Passpunkte. Die Passung ist damit exakt
  bestimmt und **unpruefbar** -- nicht richtig, nur unwiderlegbar.

Der Nutzer hat den Weg deshalb am 31.08.2026 abgewaehlt: "Bau die Automatik zurueck. Was
bringt eine Automatik fuer 3 Plaetze?" Die Blattkunde bleibt, die Rechnerei ist fort. Was
dieses Modul heute leistet:

* ``bahnfarbe`` / ``sorte_aus_ton`` -- ist dieses Blatt eine Flugplatz- oder Rollkarte?
* ``handpassung`` -- aus zwei geklickten Punkten mit ihren Koordinaten eine Passung bilden.
* ``norden`` -- das Blatt genordet ablegen und seine Grenzen ausrechnen.

Der Verlauf der Automatik ist nicht verloren: Er steht in ``scripts/ground_chart_probe.py``
und in der Spec, Abschnitt 2 und 5. Wer ihn wiederbeleben will, findet dort auch, woran er
scheitert.

Reines Pillow. numpy, scipy und OpenCV sind im Projekt nicht vorhanden und werden es nicht.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md
"""
from __future__ import annotations

import collections
import io
import logging
import math
from dataclasses import dataclass

from PIL import Image

from app import runway_ref

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- Blattkunde
TON_TIEF, TON_HOCH = 100, 210      # in diesem Bereich liegt die Bahnfarbe
TON_MINDESTANTEIL = 0.006          # sonst ist das Blatt keine Flugplatzkarte

# Die Sorte steckt im Bahnton selbst. Gemessen am 31.08.2026 ueber 30 Blaetter von 14
# Verkehrsflughaefen:
#
#   153/154 -> 15 Blaetter, darunter beide belegten Flugplatzkarten (EDDL, EDDM)
#   179/180 ->  8 Blaetter, darunter beide belegten Rollkarten (EDDM, EDDV)
#   194-210 ->  4 Blaetter anderer Art (Anflugkarten und dergleichen)
#
# Keine einzige Ueberschneidung. Das ist belegbar und kostet nichts -- der Ton wird ohnehin
# gemessen.
#
# Der zuerst gebaute Weg ueber den Titelkasten oben links traegt NICHT: Der Kopf steht nicht
# bei allen Blaettern an derselben Stelle (EDDL, EDDM, EDDB bei y 53; EDDV bei y 149), und
# es gibt mindestens zwei Setzungsvarianten.
SORTE_TON = {
    "flugplatzkarte": (150, 158),
    "rollkarte": (176, 184),
}

# Wie weit ueber die Passpunkte hinaus die Ebene noch einschaltet.
#
# Bei einer Sichtflugkarte sind die Passpunkte zwei Rahmenecken -- der Rahmen IST das
# Kartenfeld, ein Saum waere schlicht falsch. Bei einer Flugplatz- oder Rollkarte sind es
# zwei Bahnschwellen mitten auf dem Platz; ohne Saum schaltete die Karte erst ein, wenn man
# schon auf der Bahn steht.
FELD_SAUM_M = {"sichtflug": 0.0, "flugplatzkarte": 1000.0, "rollkarte": 1000.0}

# Unter dieser Schwelle wird nicht gedreht. Aus zwei Rahmenecken faellt fast immer ein
# Restwinkel von Hundertsteln bis Zehnteln Grad an (an EDWE und EDAZ gemessen: 0,04 bis
# 0,09). rotate(expand=True) liesse die Leinwand um ein bis zwei Pixel wachsen und
# interpolierte jedes Pixel -- an einem Blatt mit drei Pixel breiten Gradnetzstrichen. Der
# bild_hash aenderte sich ohne inhaltlichen Grund, und der Job meldete eine Aenderung, die
# keine ist.
DREH_SCHWELLE = 0.25

_VIERTEL = {90: Image.Transpose.ROTATE_90,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_270}


@dataclass
class GroundPassung:
    """Eine fertige Passung: Abbildung Bildpixel -> Meter, plus was daraus folgt."""
    drehung: float            # Grad, im Uhrzeigersinn gegen Nord
    mps: float                # Meter je Pixel im ROHblatt
    koeff: tuple              # (a, b, e, f) der Aehnlichkeit, auf gespiegeltem y
    bezug: tuple              # (lat, lon) des Nullpunkts der Meterrechnung
    huelle_m: tuple           # (ost_min, ost_max, nord_min, nord_max) fuer die Feldgrenzen


def bahnfarbe(im: Image.Image) -> int | None:
    """Der dominante mittelgraue Ton -- gemessen, nicht festgelegt.

    Flugplatzkarten nutzen 153/154, Rollkarten 179/180. Eine feste Zahl waere bei der
    naechsten Kartenausgabe falsch. Gemessen an EDDL: Der Ton macht 3,7 Prozent der Flaeche
    aus, waehrend jeder Nachbarwert bei 0,2 bis 0,4 Prozent liegt -- der Peak ist eindeutig.

    ``None``, wenn kein solcher Ton da ist. Dann ist das Blatt keine Flugplatzkarte.
    """
    breite, hoehe = im.size
    px = im.load()
    haeufig: collections.Counter = collections.Counter()
    for y in range(0, hoehe, 3):
        for x in range(0, breite, 3):
            wert = px[x, y]
            if TON_TIEF <= wert <= TON_HOCH:
                haeufig[wert] += 1
    if not haeufig:
        return None
    ton, anzahl = haeufig.most_common(1)[0]
    stichprobe = (breite // 3 + 1) * (hoehe // 3 + 1)
    return ton if anzahl / stichprobe >= TON_MINDESTANTEIL else None


def sorte_aus_ton(ton: int | None) -> str | None:
    """Welche Kartensorte dieser Bahnton bedeutet. ``None`` heisst: keine von beiden."""
    if ton is None:
        return None
    for name, (tief, hoch) in SORTE_TON.items():
        if tief <= ton <= hoch:
            return name
    return None


def sorte_erkennen(im: Image.Image) -> str | None:
    """Kartensorte eines Blattes -- ohne ein Zeichen zu lesen."""
    return sorte_aus_ton(bahnfarbe(im))


# --------------------------------------------------------------------------- Handpassung
def handpassung(p1_px: tuple[float, float], p1_geo: tuple[float, float],
                p2_px: tuple[float, float], p2_geo: tuple[float, float]
                ) -> GroundPassung | None:
    """Passung aus zwei geklickten Punkten mit ihren Koordinaten.

    Zwei Punkte bestimmen eine Aehnlichkeitstransformation vollstaendig: Drehung, Massstab
    und Verschiebung sind vier Unbekannte, zwei Punkte geben vier Gleichungen.

    **Gefragt wird nach zwei Punkten, nicht nach einem Winkel.** Einen Drehwinkel kann
    niemand auf einer Karte ablesen; zwei wiedererkennbare Stellen -- Bahnschwellen, das
    ARP-Kreuz -- schon. Drehung und Massstab werden daraus *hergeleitet*, so wie
    ``aip_charts.handpassung()`` die Blattgrenzen aus zwei Rahmenecken herleitet, statt die
    Klicks direkt abzulegen. Genau an dieser Unterscheidung hing bei den Sichtflugkarten der
    45-Prozent-Massstabsfehler.

    Je weiter die beiden Punkte auseinanderliegen, desto genauer die Passung: Ein Fehler von
    einem Pixel wirkt sich auf den Massstab umgekehrt proportional zu ihrem Abstand aus. Zwei
    gegenueberliegende Bahnschwellen sind deshalb besser als zwei Punkte am selben Vorfeld.

    ``None``, wenn die Angaben nicht zusammenpassen -- gleiche Punkte, gleiche Koordinaten.
    """
    if p1_px == p2_px or p1_geo == p2_geo:
        return None
    bezug = p1_geo
    z1 = (0.0, 0.0)
    z2 = runway_ref.meter(bezug, p2_geo)
    if math.hypot(*z2) < 1.0:
        return None

    # Bild-y laeuft nach unten, Nordmeter nach oben. Ohne diese Spiegelung liegt die
    # richtige Loesung nicht im Suchraum: Die Matrix [[a,-b],[b,a]] hat die Determinante
    # a^2+b^2 > 0 und ist damit immer orientierungserhaltend, die wahre Abbildung ist es
    # nicht. In der Vorabprobe kostete das 59 m statt 5,7 m fuer dasselbe Blatt.
    x1, y1 = float(p1_px[0]), -float(p1_px[1])
    x2, y2 = float(p2_px[0]), -float(p2_px[1])
    dx, dy = x2 - x1, y2 - y1
    nenner = dx * dx + dy * dy
    if nenner < 1e-9:
        return None
    dX, dY = z2[0] - z1[0], z2[1] - z1[1]
    a = (dx * dX + dy * dY) / nenner
    b = (dx * dY - dy * dX) / nenner
    e = z1[0] - a * x1 + b * y1
    f = z1[1] - b * x1 - a * y1
    mps = math.hypot(a, b)
    if mps <= 0:
        return None
    drehung = (-math.degrees(math.atan2(b, a))) % 360.0
    ost = [z1[0], z2[0]]
    nord = [z1[1], z2[1]]
    return GroundPassung(drehung=drehung, mps=mps, koeff=(a, b, e, f), bezug=bezug,
                         huelle_m=(min(ost), max(ost), min(nord), max(nord)))


# --------------------------------------------------------------------------- Nordung
def _drehen(im: Image.Image, drehung: float) -> tuple[Image.Image, float]:
    """Blatt nach Norden drehen. Rueckgabe: Bild und die TATSAECHLICH angewandte Drehung.

    Unter ``DREH_SCHWELLE`` wird gar nicht gedreht. Bei 90/180/270 Grad (auf dieselbe
    Schwelle genau) wird ``transpose`` statt ``rotate`` verwendet -- verlustfrei, genau der
    Fall der sieben quer gedruckten Blaetter.
    """
    rest = drehung % 360.0
    if min(rest, 360.0 - rest) < DREH_SCHWELLE:
        return im, 0.0
    for grad, wie in _VIERTEL.items():
        if abs(rest - grad) < DREH_SCHWELLE:
            return im.transpose(wie), float(grad)
    return im.rotate(-drehung, resample=Image.BICUBIC, expand=True,
                     fillcolor=(0, 0, 0, 0)), drehung


def norden(roh: bytes, p: GroundPassung, sorte: str) -> tuple[bytes, dict] | None:
    """Blatt genordet ablegen und seine Grenzen ausrechnen.

    ``L.imageOverlay`` kann nicht rotieren, die DFS-Blaetter sind aber nach der
    Bahnrichtung gesetzt (EDDL um 37 Grad, EDDM um 6,5). Gedreht wird deshalb hier, einmal
    beim Ablegen.

    **Die Fuellflaeche ist durchsichtig, nicht weiss.** ``expand=True`` laesst an den Ecken
    Flaeche frei; bei 37 Grad ist das rund die Haelfte des abgelegten Rechtecks. Weiss
    gefuellt laege ein grosses Dreieckspaar halbdeckend ueber der Umgebung des Platzes. Die
    quer gedruckten Sichtflugkarten kennen das Problem nicht -- 90 Grad drehen laesst nichts
    frei.

    **Das Blatt waechst erheblich:** bei 37,2 Grad um 102 bis 171 Prozent, je nach
    Seitenverhaeltnis. Nicht "rund 60 Prozent", wie eine fruehere Fassung der Spec behauptete.

    **Vorzeichen:** Das Blatt ist um ``p.drehung`` im Uhrzeigersinn gegen Nord verdreht,
    ``_drehen`` uebergibt deshalb ``-p.drehung`` an ``rotate``.

    **``sorte`` bestimmt den Saum von ``feld_*``** (s. ``FELD_SAUM_M``) -- 0 bei einer
    Sichtflugkarte, wo der Rahmen das Kartenfeld exakt definiert, 1000 m bei einer
    Flugplatz- oder Rollkarte, wo die Passpunkte zwei Bahnschwellen mitten auf dem Platz
    sind.
    """
    try:
        quelle = Image.open(io.BytesIO(roh)).convert("RGBA")
    except Exception:
        return None
    breite, hoehe = quelle.size
    gedreht, tatsaechlich = _drehen(quelle, p.drehung)
    puffer = io.BytesIO()
    gedreht.save(puffer, "PNG")

    a, b, e, f = p.koeff
    ecken_m = []
    for x, y in ((0, 0), (breite, 0), (0, hoehe), (breite, hoehe)):
        ys = -y
        ecken_m.append((a * x - b * ys + e, b * x + a * ys + f))
    ost = [q[0] for q in ecken_m]
    nord = [q[1] for q in ecken_m]
    grenzen = _grenzen_in_grad(p.bezug, min(ost), max(ost), min(nord), max(nord))
    grenzen["drehung"] = tatsaechlich

    # **feld_* ist NICHT nord/sued/west/ost.** Die Feldgrenzen sind die Huelle der
    # gesetzten Punkte zuzueglich eines sortenabhaengigen Saums; nach dem Drehen zeigt das
    # Blatt viel freie Flaeche, und ueber der duerfte die Ebene nicht schon einschalten.
    # Dieselbe Verwechslung steckte hinter dem 45-Prozent-Massstabsfehler der
    # Sichtflugkarten.
    saum = FELD_SAUM_M.get(sorte, 1000.0)
    o0, o1, n0, n1 = p.huelle_m
    feld = _grenzen_in_grad(p.bezug, o0 - saum, o1 + saum, n0 - saum, n1 + saum)
    # **Und nie ueber das Blatt hinaus.** Bei einem kleinen Blatt oder zwei nah gesetzten
    # Punkten ragt die Huelle samt Saum sonst ueber den Rand -- die Ebene schaltete dann
    # dort ein, wo die Karte gar nichts zeigt. Gemessen an einem 2200x1000-Testblatt:
    # feld_nord lag 12 m ueber nord.
    feld["nord"] = min(feld["nord"], grenzen["nord"])
    feld["sued"] = max(feld["sued"], grenzen["sued"])
    feld["ost"] = min(feld["ost"], grenzen["ost"])
    feld["west"] = max(feld["west"], grenzen["west"])
    grenzen.update({f"feld_{k}": v for k, v in feld.items()})
    return puffer.getvalue(), grenzen


def _grenzen_in_grad(bezug, ost_min, ost_max, nord_min, nord_max) -> dict:
    m_lon, m_lat = runway_ref.meter_je_grad(bezug[0])
    return {"sued": bezug[0] + nord_min / m_lat, "nord": bezug[0] + nord_max / m_lat,
            "west": bezug[1] + ost_min / m_lon, "ost": bezug[1] + ost_max / m_lon}
