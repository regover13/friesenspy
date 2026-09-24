# -*- coding: utf-8 -*-
"""Abdeckungsrechnung: Welches Ziel wurde tief und langsam überflogen — und von wem zuerst?

Drei geplante Eventtypen stellen dieselbe Frage und sollen sie mit derselben Rechnung
beantworten (Ausgangspunkt: die Umfrage im Forum, September 2026):

* **Zählflug** (#20) — eine Punktliste: Sandbänke, Kolonien, Bojen.
* **Deichkontrolle** (#22) — eine Linie, in Abschnitte geschnitten.
* **FriesenReddung** (#21) — ein Sektor als Zellraster **und** der Havarist. Der ist hier nichts
  Besonderes, sondern ein Ziel mit engem Radius in derselben Liste.

Deshalb kennt dieses Modul nur eine Form: **den Kreis.** Ein Ziel ist ein Punkt mit Radius.
Zellraster und Linienabschnitte entstehen aus :func:`zellen_aus_box` und
:func:`abschnitte_aus_linie` als gewöhnliche Kreise; die Rechnung dahinter weiß nicht mehr,
woher sie kommen. Eine Geometrie heißt: eine Stelle, an der ein Vorzeichenfehler wohnen kann.

**Hier ist keine Datenbank.** Wer rechnen will, holt die Spuren selbst — aus
``position_history``, aus ``statsim_position_history``, oder (bei der FriesenReddung) im Sekundentakt
aus dem Meldeweg der FriesenBrügge. Das Modul rechnet aus Zahlen und ist ohne Fixture prüfbar.

Gerechnet wird gegen STRECKEN, nicht gegen Punkte
-------------------------------------------------
Gemessen am 20.09.2026 an 40.570 Punktpaaren der Produktion (unter 4.000 ft, in Bewegung):

======================================  ======  ======  ======  ======
Abstand zweier aufeinanderfolgender …   Median    p90     p99     max
======================================  ======  ======  ======  ======
… Zeitstempel                            15 s     --     22 s     --
… Positionen am Boden                   0,95 km 1,35 km 2,45 km 12,6 km
======================================  ======  ======  ======  ======

**Ein Fundradius unter etwa 1,3 km ist damit punktweise nicht entscheidbar.** Der Pilot
rutscht zwischen zwei Messungen über den Havaristen hinweg, und nichts löst aus. Mit dem
Abstand Punkt-zu-Strecke ist auch ein Radius von 300 m sicher zu beurteilen: 15 Sekunden Flug
sind praktisch gerade, die Abweichung einer Kurve in dieser Zeit liegt unter dem Radius.

Zwei Kappungen, und warum es zwei sind
--------------------------------------
``luecke_max_s`` (60 s) fängt die Löcher im Abtaststrom: Was in der Lücke geflogen wurde,
weiß niemand, also wird dort nichts gutgeschrieben. Der Wert ist absichtlich großzügig — p99
liegt bei 22 s, er trifft praktisch nur echte Aussetzer.

``sprung_max_km`` (6 km) fängt, was *innerhalb* der erlaubten Zeit unmöglich ist: das Laden
eines Flugs, Slew, den Wechsel des Startplatzes. Die 12,6 km der Messung stammen daher. Ohne
diese zweite Kappung gilt die ganze Luftlinie eines Sprungs als abgesucht — und das ist der
Fehler, der sich als Erfolg tarnt.

Beide Endpunkte müssen im Fenster liegen
----------------------------------------
Tief UND langsam, am Anfang und am Ende des Stücks. Wer im Sturzflug über die Sandbank zieht,
hat nichts gesehen, und die Wertung soll sich in einem Satz erklären lassen. Fehlt Höhe oder
Geschwindigkeit (``NULL``), ist der Überflug nicht belegt — ``NULL`` heißt nicht ``0``.

Welche Höhe hineingegeben wird, entscheidet der Aufrufer und nicht dieses Modul: ``altitude``
aus ``position_history`` ist MSL, die FriesenBrügge kennt zusätzlich die echte AGL.

⚠ **``MSL ≈ AGL`` gilt nur über dem Wasser.** Über dem Watt ist die Geländehöhe ~0, und
dort fällt der Unterschied nicht auf -- ein Suchsektor darf aber überall liegen, im
Mittelgebirge, über einer Großstadt, in Brandenburg. Wer die Schranken gegen MSL prüft,
verschiebt sie dort um die gesamte Geländehöhe. Deshalb lernt die FriesenReddung die
Geländehöhe an der Unglücksstelle und rechnet gegen sie.

Warum das schnell ist
---------------------
Ziele werden in Kacheln von Radiusgröße einsortiert; je Segment werden nur die Kacheln seines
Rechtecks plus zwei Ringe besucht. Gemessen an einem realistischen Abend — 10 Piloten, 2
Stunden, 4.790 Segmente gegen 420 Zellen: **68 ms statt 1.393 ms** (derselbe Abbruch beim
ersten Treffer, dieselbe Geometrie), bei gleichem Ergebnis. Zwei Ringe reichen beweisbar,
weil die Kachel so groß ist wie der größte Radius — einer für die Reichweite, einer für die
Abrundung. ``tests/test_abdeckung.py`` hält die Gleichheit mit der stumpfen Rechnung über
Zufallsdaten fest, damit ein Filterfehler nicht als harmlos fehlende Abdeckung durchgeht.

Für den Einzelfall braucht :func:`abstand_zu_strecke_km` rund **1 Mikrosekunde** — der
Sekundentakt der FriesenBrügge mit einem Dutzend Fliegern ist damit keine Frage.

Alle Segmente aller Piloten werden nach ihrem **End**-Zeitstempel sortiert abgearbeitet. Nur
deshalb ist „wer war zuerst" exakt und der Abbruch beim ersten Treffer erlaubt. Gestempelt
wird das Segmentende — der Augenblick, in dem der Überflug bewiesen ist, nie ein früherer.

Die flache Projektion
---------------------
Abstände werden in einer lokalen Ebene gerechnet, mit einem Längengrad-Maßstab aus der
mittleren Breite aller Ziele (:func:`bezugsbreite`).

Gegen ``geo.haversine`` weicht das um **1,1 Promille ab — und zwar bei jeder Entfernung
gleich, von 200 m bis 20 km** (gemessen). Das ist kein Fehler der Ebene, sondern die
verschiedene Länge eines Breitengrads: hier 111,32 km (der reale Wert auf dieser Breite),
bei der Kugel mit R = 6371 km nur 111,195 km. Der Anteil der Näherung selbst liegt bei 20 km
unter 0,4 Promille. Auf einen Radius von 1,5 km sind das 1,7 Meter — für ein Eventgebiet von
einigen hundert Kilometern also richtig; für eine Rechnung über Kontinente wäre dieses Modul
das falsche Werkzeug.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

#: lat, lon, Höhe in Fuß, Geschwindigkeit in Knoten, ISO-Zeitstempel.
#: Höhe und Geschwindigkeit dürfen ``None`` sein — dann ist das Segment unbrauchbar.
Punkt = tuple[float, float, "float | None", "float | None", str]

#: Ein Pilot und seine zeitlich geordneten Punkte.
Spur = tuple[int, list[Punkt]]

#: Schlüssel, lat, lon, Radius in km. Der Schlüssel ist frei wählbar und muss eindeutig sein;
#: er ist das Einzige, was nach außen gehen darf (s. Verdeckung bei der FriesenReddung).
Ziel = tuple[str, float, float, float]

_KM_JE_GRAD_LAT = 111.32


def _km_je_grad_lon(lat: float) -> float:
    return _KM_JE_GRAD_LAT * math.cos(math.radians(lat))


@dataclass(frozen=True)
class Fenster:
    """Die Bedingungen eines Laufs. Der Radius steht am Ziel, das Fenster am Lauf."""

    hoehe_max_ft: float
    gs_max_kt: float
    gs_min_kt: float = 0.0
    #: Längere Segmente fallen weg — in der Lücke ist nichts belegt.
    luecke_max_s: float = 60.0
    #: Weitere Segmente fallen weg — das ist ein Sprung, kein Flug.
    sprung_max_km: float = 6.0


@dataclass(frozen=True)
class Treffer:
    schluessel: str
    cid: int
    #: Ende des Segments, mit dem der Überflug belegt ist.
    ts: str


@dataclass(frozen=True)
class Abdeckung:
    #: Ziel -> erster Abdecker. Enthält NIE eine Koordinate.
    treffer: dict[str, Treffer]
    #: Ziele, die niemand hatte — in der Reihenfolge der Eingabe.
    offen: tuple[str, ...]
    #: cid -> Zahl der Ziele, die dieser Pilot als ERSTER abgedeckt hat. Jeder Pilot aus
    #: ``spuren`` steht hier, auch mit 0 — sonst fehlt er in der Abendbilanz ganz.
    je_pilot: dict[int, int]
    #: Gruppenwertung, 0..1.
    anteil: float


def _sekunden(ts: str) -> float | None:
    """ISO-Zeitstempel in Sekunden. Ohne Zeitzone gilt UTC (so schreibt es die Datenbank)."""
    try:
        t = (ts or "").strip().replace(" ", "T")
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        d = datetime.fromisoformat(t)
    except (ValueError, TypeError, AttributeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def _strecke_km(alat: float, alon: float, blat: float, blon: float, km_lon: float) -> float:
    return math.hypot((blon - alon) * km_lon, (blat - alat) * _KM_JE_GRAD_LAT)


def _abstand(zlat: float, zlon: float, alat: float, alon: float,
             blat: float, blon: float, km_lon: float) -> float:
    """Abstand des Ziels zur STRECKE A-B (nicht zur Geraden durch A und B)."""
    ax = (alon - zlon) * km_lon
    ay = (alat - zlat) * _KM_JE_GRAD_LAT
    bx = (blon - zlon) * km_lon
    by = (blat - zlat) * _KM_JE_GRAD_LAT
    dx, dy = bx - ax, by - ay
    laenge2 = dx * dx + dy * dy
    if laenge2 <= 0.0:
        return math.hypot(ax, ay)          # A und B identisch: Punktabstand
    # Fußpunkt auf die Strecke begrenzen — sonst zählt die Verlängerung mit, und ein Ziel
    # geradeaus voraus gilt als überflogen, bevor der Pilot dort war.
    t = -(ax * dx + ay * dy) / laenge2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(ax + t * dx, ay + t * dy)


def bezugsbreite(ziele: list[Ziel]) -> float:
    """Die Breite, aus der der Längengrad-Maßstab eines Laufs kommt: das Mittel der Ziele.

    Öffentlich, weil sie mitgegeben werden MUSS, wenn ein einzelner Abstand dasselbe Urteil
    liefern soll wie der ganze Lauf — siehe :func:`abstand_zu_strecke_km`.
    """
    if not ziele:
        return 0.0
    return sum(z[1] for z in ziele) / len(ziele)


def abstand_zu_strecke_km(zlat: float, zlon: float, alat: float, alon: float,
                          blat: float, blon: float, bezug_lat: float | None = None) -> float:
    """Einzelabstand Ziel zur Strecke A-B in km.

    Für den Einzelfall gedacht — etwa die Fundprüfung im Sekundentakt der FriesenBrügge, wo
    es nur ein Ziel und ein Segment gibt.

    ⚠ **``bezug_lat`` mitgeben, wenn das Urteil zum Lauf passen muss.** Ohne Angabe kommt der
    Maßstab aus der Breite des Ziels, :func:`abdeckung` nimmt dagegen das Mittel ALLER Ziele.
    Über einen 40-km-Sektor unterscheiden sich beide um rund 0,25 % — genug, damit ein Ziel
    am Rand seines Radius einmal so und einmal anders entschieden wird. Aufgefallen ist das
    am Gleichheitstest gegen die stumpfe Rechnung: drei von 209 Zellen bekamen einen 15 s
    früheren Stempel. In Betrieb hieße das: bei 1 Hz gefunden, in der Abendbilanz nicht.
    """
    if bezug_lat is None:
        bezug_lat = zlat
    return _abstand(zlat, zlon, alat, alon, blat, blon, _km_je_grad_lon(bezug_lat))


def abdeckung(spuren, ziele: list[Ziel], fenster: Fenster) -> Abdeckung:
    """Wer hat welches Ziel zuerst tief und langsam überflogen?

    ``spuren`` ist eine Folge von ``(cid, punkte)``; die Punkte müssen zeitlich geordnet sein
    (so liefert es ``get_position_history``). Doppelte Zielschlüssel sind nicht vorgesehen.
    """
    je_pilot: dict[int, int] = {}
    for cid, _punkte in spuren:
        je_pilot.setdefault(cid, 0)
    if not ziele:
        return Abdeckung(treffer={}, offen=(), je_pilot=je_pilot, anteil=0.0)

    km_lon = _km_je_grad_lon(bezugsbreite(ziele))
    kachel_km = max(max(z[3] for z in ziele), 0.05)

    def kachel(lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat * _KM_JE_GRAD_LAT / kachel_km),
                math.floor(lon * km_lon / kachel_km))

    eimer: dict[tuple[int, int], list[int]] = {}
    for idx, (_s, zlat, zlon, _r) in enumerate(ziele):
        eimer.setdefault(kachel(zlat, zlon), []).append(idx)

    # Segmente sammeln und prüfen. Sortiert wird nach Segment-ENDE, dann nach CID: Das macht
    # „wer war zuerst" exakt, erlaubt den Abbruch beim ersten Treffer und liefert bei
    # Gleichstand zweimal dasselbe Ergebnis.
    segmente: list[tuple[float, int, float, float, float, float, str]] = []
    for cid, punkte in spuren:
        punkte = list(punkte)
        for a, b in zip(punkte, punkte[1:]):
            if a[2] is None or b[2] is None or a[3] is None or b[3] is None:
                continue
            if a[2] > fenster.hoehe_max_ft or b[2] > fenster.hoehe_max_ft:
                continue
            if a[3] > fenster.gs_max_kt or b[3] > fenster.gs_max_kt:
                continue
            if a[3] < fenster.gs_min_kt or b[3] < fenster.gs_min_kt:
                continue
            t_a, t_b = _sekunden(a[4]), _sekunden(b[4])
            if t_a is None or t_b is None:
                continue
            dt = t_b - t_a
            if dt < 0.0 or dt > fenster.luecke_max_s:
                continue
            if _strecke_km(a[0], a[1], b[0], b[1], km_lon) > fenster.sprung_max_km:
                continue
            segmente.append((t_b, cid, a[0], a[1], b[0], b[1], b[4]))
    segmente.sort(key=lambda s: (s[0], s[1]))

    treffer: dict[str, Treffer] = {}
    for _ende_s, cid, alat, alon, blat, blon, ende_ts in segmente:
        if len(treffer) == len(ziele):
            break
        (ia, ja), (ib, jb) = kachel(alat, alon), kachel(blat, blon)
        i0, i1 = (ia, ib) if ia <= ib else (ib, ia)
        j0, j1 = (ja, jb) if ja <= jb else (jb, ja)
        for i in range(i0 - 2, i1 + 3):
            for j in range(j0 - 2, j1 + 3):
                for idx in eimer.get((i, j), ()):
                    schluessel, zlat, zlon, radius = ziele[idx]
                    if schluessel in treffer:
                        continue
                    if _abstand(zlat, zlon, alat, alon, blat, blon, km_lon) <= radius:
                        treffer[schluessel] = Treffer(schluessel, cid, ende_ts)
                        je_pilot[cid] = je_pilot.get(cid, 0) + 1

    offen = tuple(z[0] for z in ziele if z[0] not in treffer)
    return Abdeckung(treffer=treffer, offen=offen, je_pilot=je_pilot,
                     anteil=len(treffer) / len(ziele))


def raster_masse(sued: float, west: float, nord: float, ost: float,
                 kante_km: float) -> tuple[int, int, float, float]:
    """Zeilen, Spalten und Zellgröße in Grad — die Geometrie des Sektorrasters.

    **Die einzige Stelle, die sie rechnet.** ``zellen_aus_box`` benutzt sie, und der
    Raster-Endpunkt gibt sie an die Karte weiter. Rechneten beide selbst, läge irgendwann
    jede gezeichnete Zelle still neben der gewerteten (Spec 2026-09-23, Abschnitt 3).

    Zelle ``z{i}_{j}`` reicht von ``sued + i·d_lat`` bis ``sued + (i+1)·d_lat`` und von
    ``west + j·d_lon`` bis ``west + (j+1)·d_lon`` — mit den SORTIERTEN Ecken.
    """
    if nord < sued:
        sued, nord = nord, sued
    if ost < west:
        west, ost = ost, west
    kante_km = max(float(kante_km), 0.05)
    km_lon = _km_je_grad_lon((sued + nord) / 2.0)
    zeilen = max(1, math.ceil((nord - sued) * _KM_JE_GRAD_LAT / kante_km))
    spalten = max(1, math.ceil((ost - west) * km_lon / kante_km))
    return zeilen, spalten, kante_km / _KM_JE_GRAD_LAT, kante_km / km_lon


def zellen_aus_box(sued: float, west: float, nord: float, ost: float,
                   kante_km: float, korridor_km: float, praefix: str = "z") -> list[Ziel]:
    """Ein Rechteck in ein Zellraster schneiden — der Suchsektor.

    **Die Kopplung, die man leicht übersieht — und die hier zuerst falsch beschrieben war:**
    Eine große Zellkante gegen einen kleinen Korridor erzeugt **keine Löcher** (so stand es
    hier bis zum 20.09.2026). Jeder Mittelpunkt ist überfliegbar, 100 % sind immer erreichbar.
    Was wirklich passiert, ist eine **grobe Buchhaltung**: Eine 6-km-Zelle gilt als vollständig
    abgesucht, obwohl ein Track nur einen Streifen von 2 · Korridor durch ihre Mitte gelegt hat.

    Der Aufrufer muss deshalb ``kante_km <= korridor_km`` halten. Feiner ist immer erlaubt und
    nur eine Frage der Rechenzeit; grober übertreibt den Fortschritt — und zieht über
    ``fundradius_km`` (s. ``app/reddung.py``) einen großzügigen Fundradius nach sich, weil das
    Versprechen „voll abgesucht = gefunden" sonst nicht mehr gälte.

    Die Zellenzahl wird aufgerundet, damit der Rand der Box mitkommt statt abgeschnitten zu
    werden; der letzte Mittelpunkt darf dafür ein Stück außerhalb liegen.
    """
    if nord < sued:
        sued, nord = nord, sued
    if ost < west:
        west, ost = ost, west
    zeilen, spalten, d_lat, d_lon = raster_masse(sued, west, nord, ost, kante_km)
    ziele: list[Ziel] = []
    for i in range(zeilen):
        zlat = sued + (i + 0.5) * d_lat
        for j in range(spalten):
            zlon = west + (j + 0.5) * d_lon
            ziele.append((f"{praefix}{i}_{j}", zlat, zlon, float(korridor_km)))
    return ziele


def abschnitte_aus_linie(punkte: list[tuple[float, float]], laenge_km: float,
                         korridor_km: float, praefix: str = "a") -> list[Ziel]:
    """Einen Linienzug in Abschnitte schneiden — Küste, Deich, Fahrwasser.

    Jeder Abschnitt wird durch seinen Mittelpunkt vertreten. Die Länge wird gleichmäßig
    verteilt (``gesamt / Anzahl``) statt am Ende einen Rest stehen zu lassen: So liegt jeder
    Punkt der Linie höchstens die halbe Abschnittslänge vom nächsten Mittelpunkt entfernt,
    und mit ``korridor_km >= laenge_km / 2`` ist die Linie durchgehend abdeckbar.
    """
    if not punkte or len(punkte) < 2:
        return []
    km_lon = _km_je_grad_lon(sum(p[0] for p in punkte) / len(punkte))
    kanten: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    gesamt = 0.0
    for a, b in zip(punkte, punkte[1:]):
        laenge = _strecke_km(a[0], a[1], b[0], b[1], km_lon)
        kanten.append((a, b, laenge))
        gesamt += laenge
    if gesamt <= 0.0:
        return []
    anzahl = max(1, math.ceil(gesamt / max(float(laenge_km), 0.01)))
    schritt = gesamt / anzahl
    ziele: list[Ziel] = []
    for k in range(anzahl):
        rest = (k + 0.5) * schritt
        for a, b, laenge in kanten:
            if rest <= laenge or (a, b, laenge) is kanten[-1]:
                t = (rest / laenge) if laenge > 0 else 0.0
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                ziele.append((f"{praefix}{k}",
                              a[0] + t * (b[0] - a[0]),
                              a[1] + t * (b[1] - a[1]),
                              float(korridor_km)))
                break
            rest -= laenge
    return ziele
