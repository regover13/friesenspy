"""AIP-Sichtflugkarten: Blatt holen, Gradnetz vermessen, Passung rechnen und pruefen.

Eigenes Modul aus demselben Grund wie ``app/vrp.py``: Der Bestand ist Zustand mit eigener
Lebensdauer, und die Geometrie ist die Sorte Rechnung, die man gegen Messwerte pruefen will.
Deshalb enthaelt dieses Modul weder Datenbank- noch FastAPI-Bezuege.

**Die Blaetter sind keine PDFs.** Ein Eintrag aus ``airport_links`` wie
``aip.dfs.de/BasicVFR/pages/P0016F.html`` ist eine Weiterleitungsseite mit
``<meta http-equiv="Refresh">``; ein HTTP-Redirect findet NICHT statt. Wer ``curl -L``
benutzt, bekommt die Weiterleitungsseite zurueck und haelt sie fuer die Karte. Die Karte
steckt als PNG in einem ``data:``-URI im HTML der Zielseite.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from __future__ import annotations

import base64
import logging
import re
import urllib.parse
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_META_REFRESH = re.compile(r'http-equiv=.?Refresh.?[^>]*url=([^"\'>\s]+)', re.I)
_IMG_AIP = re.compile(r'id="imgAIP"[^>]*src="data:image/png;base64,([^"]+)"')
_SEITE = re.compile(r'href="(\.\./pages/[0-9A-Fa-f]+\.html)"')
_AIRAC = re.compile(r'/BasicVFR/(\d{4}[A-Z]{3}\d{2})/')


def airac_url(html: str, basis: str) -> str | None:
    """Ziel des Meta-Refresh, absolut gemacht. None, wenn die Seite keines traegt."""
    m = _META_REFRESH.search(html)
    return urllib.parse.urljoin(basis, m.group(1).strip()) if m else None


def airac_kennung(url: str) -> str | None:
    """Die Ausgabe aus dem Pfad, z. B. '2026AUG20'."""
    m = _AIRAC.search(url)
    return m.group(1) if m else None


def bild_aus_html(html: str) -> bytes | None:
    """Das Kartenblatt aus dem data:-URI. None, wenn die Seite keines enthaelt."""
    m = _IMG_AIP.search(html)
    return base64.b64decode(m.group(1)) if m else None


def kapitelseiten(html: str, basis: str) -> list[str]:
    """Alle Seiten des Platz-Kapitels, doppelte entfernt, Reihenfolge erhalten.

    Noetig, weil der gespeicherte Link nicht immer auf die Karte zeigt: Bei EDAZ oeffnet er
    die Textseite "VFR-Flugverfahren", die Sichtflugkarte ist die vierte Seite desselben
    Kapitels. 28 von 446 Karten liegen so.
    """
    gesehen: dict[str, None] = {}
    for treffer in _SEITE.findall(html):
        gesehen.setdefault(urllib.parse.urljoin(basis, treffer), None)
    return list(gesehen)


# ---------------------------------------------------------------------------
# Kartenrahmen und Gradnetz
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rahmen:
    """Inneres Kartenfeld plus die beiden Randbaender, in denen die Ticks stehen."""
    links: float
    oben: float
    rechts: float
    unten: float
    band_links: float   # aeussere senkrechte Rahmenlinie
    band_oben: float    # aeussere waagerechte Rahmenlinie


# Der Doppelrahmen liegt rund 24 Pixel auseinander.
_PAAR_MIN, _PAAR_MAX = 15, 35
_FELD_MIN = 200
_SCHWELLEN = (0.65, 0.55, 0.45, 0.35)
# Streng zuerst. Bei EDBY lieferte erst die strengste Schwelle den richtigen Abstand;
# die lockere holte zwei Stoerstriche herein und drueckte 219 auf 28,7.
_TICK_SCHWELLEN = (0.95, 0.85, 0.7, 0.55)
# Grosszuegig: ueber die Gueltigkeit entscheidet die Gleichmaessigkeit in raster(), nicht die
# Anzahl. Eine Grenze von 30 warf Querformat-Karten hinaus (EDAB 31 Ticks, EDWE 39).
#
# raster() prueft alle Positionspaare, ist also quadratisch in der Tickzahl. Bei feinem
# Gitter sind das bis zu 10 000 Kandidaten je Achse und Schwelle. Falls der Erstlauf zu
# lange braucht: erst die Kandidaten eindampfen, nicht die Belegungspruefung opfern.
_TICK_MAX = 100


def _anteile(px, breite: int, hoehe: int, achse: str, von: int, bis: int) -> list[float]:
    """Anteil dunkler Pixel je Zeile bzw. Spalte.

    Nicht der laengste durchgehende Lauf: Die linke Rahmenlinie wird oft von der vertikalen
    "Berichtigung:"-Beschriftung gekreuzt und ist dann nur zu 88 Prozent durchgehend --
    rechts, wo kein Text kreuzt, sind es 100.
    """
    n = hoehe if achse == "h" else breite
    spanne = max(1, bis - von)
    return [
        sum(1 for j in range(von, bis)
            if (px[j, i] if achse == "h" else px[i, j]) < 128) / spanne
        for i in range(n)
    ]


def _linien(werte: list[float], schwelle: float) -> list[float]:
    treffer = [i for i, v in enumerate(werte) if v >= schwelle]
    gruppen: list[list[int]] = []
    for t in treffer:
        if gruppen and t - gruppen[-1][-1] <= 2:
            gruppen[-1].append(t)
        else:
            gruppen.append([t])
    return [sum(g) / len(g) for g in gruppen]


def _paare(linien: list[float]) -> list[tuple[float, float]]:
    """Alle Linienpaare im Doppelrahmen-Abstand."""
    return [(a, b) for a, b in zip(linien, linien[1:]) if _PAAR_MIN <= b - a <= _PAAR_MAX]


def raster(pos: list[float],
           mind_belegung: float = 0.75) -> tuple[float | None, int, float | None]:
    """Bestes Raster in den Kandidatenpositionen: (Abstand, Trefferzahl, Anker).

    In das Randband ragen Hindernissymbole hinein -- bei EDCQ Windraeder -- und werden als
    Tick gelesen. Wer verlangt, dass ALLE Positionen gleichmaessig liegen, scheitert an einem
    einzigen Stoerstrich; gesucht wird deshalb die groesste Teilmenge auf einem Raster.

    Entscheidend ist die **Belegung**: Ein feineres Raster hat immer mindestens so viele
    Treffer, laesst aber Plaetze leer. Ohne diese Pruefung lieferte
    ``raster([100, 150, 200, 217, 250])`` den Wert 16,67 statt 50.

    **Der Anker gehoert mit ins Ergebnis.** Ohne ihn nimmt ``raster_treffer`` die erste
    Position als Bezug -- ist das ausgerechnet ein Stoerstrich, ueberlebt nur er, und das
    Zahlenlesen bekommt keine Stuetzstelle.

    Der Startabstand wird NICHT unterteilt; Luecken deckt das Raster ueber seine Vielfachen ab.
    """
    if len(pos) < 2:
        return None, 0, None
    bestes = None
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            d = pos[j] - pos[i]
            if d < 12:
                continue
            treffer = raster_treffer(pos, d, pos[i])
            if len(treffer) < 2:
                continue
            ks = [round((q - pos[i]) / d) for q in treffer]
            spanne = max(ks) - min(ks)
            if spanne == 0 or len(treffer) / (spanne + 1) < mind_belegung:
                continue
            fein = (max(treffer) - min(treffer)) / spanne
            guete = (len(treffer), fein)
            if bestes is None or guete > bestes[0]:
                bestes = (guete, fein, len(treffer), min(treffer))
    return (bestes[1], bestes[2], bestes[3]) if bestes else (None, 0, None)


def raster_treffer(pos: list[float], d: float, anker: float) -> list[float]:
    """Die Positionen, die auf dem Raster (anker + k*d) liegen. Alles andere ist Stoerstrich.

    Wird auch beim Zahlenlesen gebraucht: Ein Windradstrich mit einer Zahl daneben darf keine
    Stuetzstelle werden.
    """
    if not pos or not d:
        return []
    return [q for q in pos
            if abs((q - anker) / d - round((q - anker) / d)) * d <= 2.0]


def _striche(px, fest_von: float, fest_bis: float, von: float, bis: float,
             achse: str, schwelle: float) -> list[float]:
    spanne = int(fest_bis) - int(fest_von)
    if spanne < 5:
        return []
    treffer = []
    for v in range(int(von), int(bis)):
        n = sum(1 for f in range(int(fest_von), int(fest_bis))
                if (px[f, v] if achse == "y" else px[v, f]) < 128)
        if n >= schwelle * spanne:
            treffer.append(v)
    gruppen: list[list[int]] = []
    for t in treffer:
        if gruppen and t - gruppen[-1][-1] <= 3:
            gruppen[-1].append(t)
        else:
            gruppen.append([t])
    return [sum(g) / len(g) for g in gruppen]


def _traegt_gradnetz(px, fest_von: float, fest_bis: float,
                     von: float, bis: float, achse: str) -> bool:
    """Steht in diesem Randband ein gleichmaessiges Gradnetz?"""
    for sw in _TICK_SCHWELLEN:
        t = _striche(px, fest_von, fest_bis, von, bis, achse, sw)
        if 2 <= len(t) <= _TICK_MAX and raster(t)[0]:
            return True
    return False


def rahmen_finden(im) -> Rahmen | None:
    """Doppelrahmen des Kartenfelds. None, wenn das Blatt keines traegt (Textseite).

    Gesucht wird das **engste** Paar-Rechteck, dessen beide Randbaender ein Gradnetz tragen
    -- nicht das aeusserste. Denn auf manchen Blaettern bilden die Layout-Trennlinien von
    Kopf- und Fusszeile selbst ein Paar im Doppelrahmen-Abstand und wuerden dann gewinnen.
    Gemessen am 23.08.2026 gegen ein Testblatt mit solchen Linien: Die aeusserste Wahl
    lieferte (132, 136, 817, 909) statt (132, 180, 817, 865).

    Der Kartenrahmen ist durch sein Gradnetz definiert, nicht durch seine Lage -- deshalb
    entscheidet das Band, nicht der Rand.
    """
    breite, hoehe = im.size
    px = im.load()
    waagerecht = _anteile(px, breite, hoehe, "h", 0, breite)
    for sh in _SCHWELLEN:
        hp = _paare(_linien(waagerecht, sh))
        kombis = sorted(
            ((unten_i - oben_i, (oben_a, oben_i), (unten_i, unten_a))
             for (oben_a, oben_i) in hp for (unten_i, unten_a) in hp
             if unten_i - oben_i >= _FELD_MIN),
            key=lambda k: k[0])
        for _h, (oben_a, oben_i), (unten_i, _ua) in kombis:
            senkrecht = _anteile(px, breite, hoehe, "v", int(oben_i), int(unten_i))
            for sv in _SCHWELLEN:
                vp = _paare(_linien(senkrecht, sv))
                vkombis = sorted(
                    ((rechts_i - links_i, (links_a, links_i), (rechts_i, rechts_a))
                     for (links_a, links_i) in vp for (rechts_i, rechts_a) in vp
                     if rechts_i - links_i >= _FELD_MIN),
                    key=lambda k: k[0])
                for _b, (links_a, links_i), (rechts_i, _ra) in vkombis:
                    if (_traegt_gradnetz(px, links_a + 2, links_i - 2,
                                         oben_i + 2, unten_i - 2, "y")
                            and _traegt_gradnetz(px, oben_a + 2, oben_i - 2,
                                                 links_i + 2, rechts_i - 2, "x")):
                        return Rahmen(links=links_i, oben=oben_i,
                                      rechts=rechts_i, unten=unten_i,
                                      band_links=links_a, band_oben=oben_a)
    return None


def tick_positionen(im, rahmen: Rahmen | None) -> tuple[list[float], list[float]]:
    """Tickpositionen in den Randbaendern: (senkrecht/Breite, waagerecht/Laenge).

    Genommen wird die ERSTE Schwelle, die ein gueltiges Raster ergibt -- bewusst nicht die
    beste aus allen Kombinationen. Wuerde man 4x4 Schwellenkombinationen gegen die Gegenprobe
    optimieren, stiege deren Zufallstrefferquote von 1,45 auf rund 21 Prozent (Spec 3.2).
    """
    if rahmen is None:
        return [], []
    px = im.load()
    ty: list[float] = []
    tx: list[float] = []
    for sw in _TICK_SCHWELLEN:
        k = _striche(px, rahmen.band_links + 2, rahmen.links - 2,
                     rahmen.oben + 2, rahmen.unten - 2, "y", sw)
        if 2 <= len(k) <= _TICK_MAX and raster(k)[0]:
            ty = k
            break
    for sw in _TICK_SCHWELLEN:
        k = _striche(px, rahmen.band_oben + 2, rahmen.oben - 2,
                     rahmen.links + 2, rahmen.rechts - 2, "x", sw)
        if 2 <= len(k) <= _TICK_MAX and raster(k)[0]:
            tx = k
            break
    return ty, tx


# ---------------------------------------------------------------------------
# Grad-Zahlen lesen
# ---------------------------------------------------------------------------
# MEHRERE Muster je Ziffer: Die DFS-Schrift und die Pruefschrift der Tests sind verschieden
# breit (DFS-"1" ist 3 Pixel breit, die Pruefschrift 5), und ziffer_erkennen() vergleicht nur
# bei gleicher Breite. Mit einem Muster je Ziffer koennten beide nicht nebeneinander stehen.
#
# Die DFS-Muster gewinnt scripts/aip_schablonen.py aus den Blaettern; sie lassen sich nicht
# erraten, nur ansehen. Bis sie eingetragen sind, liest der Code nur die Pruefschrift -- der
# Erstlauf meldet dann eine Quote nahe null, und genau das ist der Hinweis, dass hier noch
# etwas fehlt.
_SCHABLONEN: dict[int, list[tuple[str, ...]]] = {
    0: [("#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#####")],
    1: [("..##.", ".#.#.", "...#.", "...#.", "...#.", "...#.", "...#.", "...#.", "#####"),
        ("..#", "###", "..#", "..#", "..#", "..#", "..#", "..#", "..#")],
    2: [("#####", "....#", "....#", "....#", "#####", "#....", "#....", "#....", "#####")],
    3: [("#####", "....#", "....#", "....#", "#####", "....#", "....#", "....#", "#####")],
    4: [("#...#", "#...#", "#...#", "#...#", "#####", "....#", "....#", "....#", "....#")],
    5: [("#####", "#....", "#....", "#....", "#####", "....#", "....#", "....#", "#####")],
    6: [("#####", "#....", "#....", "#....", "#####", "#...#", "#...#", "#...#", "#####")],
    7: [("#####", "....#", "....#", "....#", "....#", "....#", "....#", "....#", "....#")],
    8: [("#####", "#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#####")],
    9: [("#####", "#...#", "#...#", "#...#", "#####", "....#", "....#", "....#", "#####")],
}
# Ueber diesem Anteil abweichender Pixel gilt ein Zeichen als unlesbar. Lieber keine Zahl als
# eine falsche: Eine falsch gelesene Minute verschiebt die Karte um 1,85 km.
_ZIFFER_MAX_ABWEICHUNG = 0.15


def _auf_hoehe(bm: tuple[tuple[int, ...], ...], hoehe: int) -> tuple[tuple[int, ...], ...]:
    """Bitmap auf eine Zielhoehe bringen, Zeilen proportional abgetastet."""
    if not bm or hoehe < 1:
        return bm
    return tuple(bm[min(len(bm) - 1, int(i * len(bm) / hoehe))] for i in range(hoehe))


def ziffer_erkennen(bitmap: tuple[tuple[int, ...], ...]) -> int | None:
    """Ziffer per Schablonenvergleich. None, wenn keine gut genug passt."""
    if not bitmap or not bitmap[0]:
        return None
    bester: tuple[float, int] | None = None
    for ziffer, muster_liste in _SCHABLONEN.items():
        for muster in muster_liste:
            schablone = tuple(tuple(1 if z == "#" else 0 for z in zeile) for zeile in muster)
            if len(schablone[0]) != len(bitmap[0]):
                continue
            angepasst = _auf_hoehe(bitmap, len(schablone))
            falsch = sum(a != b for za, zs in zip(angepasst, schablone)
                         for a, b in zip(za, zs))
            anteil = falsch / (len(schablone) * len(schablone[0]))
            if bester is None or anteil < bester[0]:
                bester = (anteil, ziffer)
    if bester is None or bester[0] > _ZIFFER_MAX_ABWEICHUNG:
        return None
    return bester[1]


def zahl_lesen(zeichen: list) -> int | None:
    """Ziffernfolge zu einer Zahl. None, sobald ein Zeichen unlesbar ist."""
    if not zeichen:
        return None
    wert = 0
    for bm in zeichen:
        z = ziffer_erkennen(bm)
        if z is None:
            return None
        wert = wert * 10 + z
    return wert


def _zeichen_zerlegen(px, x0: int, x1: int, y0: int, y1: int) -> list:
    """Einzelzeichen in einem Rechteck, von links nach rechts."""
    if x1 <= x0 or y1 <= y0:
        return []
    spalten = [x for x in range(x0, x1) if any(px[x, y] < 128 for y in range(y0, y1))]
    gruppen: list[list[int]] = []
    for x in spalten:
        if gruppen and x - gruppen[-1][-1] <= 1:
            gruppen[-1].append(x)
        else:
            gruppen.append([x])
    out = []
    for g in gruppen:
        if not (2 <= len(g) <= 12):
            continue
        ys = [y for y in range(y0, y1) if any(px[x, y] < 128 for x in g)]
        if not ys or len(ys) > 14:
            continue
        out.append(tuple(
            tuple(1 if px[x, y] < 128 else 0 for x in g)
            for y in range(min(ys), max(ys) + 1)
        ))
    return out


def zeichen_im_band(im, rahmen: Rahmen, tick: float, achse: str,
                    tick_abstand: float | None = None) -> tuple[list, list]:
    """Die beiden Zeichengruppen an einer Tickmarke: (Grad, Minute).

    Bei der Breite (``achse='y'``) steht der Gradwert im linken Band UEBER dem Strich, die
    Minute darunter. Bei der Laenge (``achse='x'``) steht beides im oberen Band, links und
    rechts des Strichs.

    **Das Suchfenster richtet sich nach dem Tickabstand**, nicht nach einer festen Zahl. Mit
    starren 20 Pixeln griffen benachbarte Beschriftungen ineinander, sobald das Gitter fein
    wird: Bei dx = 34 waren von 20 Ticks nur noch 6 lesbar, bei 32 gar keiner mehr -- und 25
    der 446 Karten haben einen Abstand unter 40 Pixeln.
    """
    px = im.load()
    grenze = 20 if tick_abstand is None else max(4, int(tick_abstand / 2) - 1)
    if achse == "y":
        x0, x1 = int(rahmen.band_links) + 1, int(rahmen.links)
        hoch = min(grenze, 14)
        oben = _zeichen_zerlegen(px, x0, x1, max(0, int(tick) - hoch), int(tick) - 1)
        unten = _zeichen_zerlegen(px, x0, x1, int(tick) + 1,
                                  min(im.size[1], int(tick) + hoch))
        return oben, unten
    y0, y1 = int(rahmen.band_oben) + 1, int(rahmen.oben)
    links = _zeichen_zerlegen(px, max(0, int(tick) - grenze), int(tick) - 1, y0, y1)
    rechts = _zeichen_zerlegen(px, int(tick) + 1,
                               min(im.size[0], int(tick) + grenze), y0, y1)
    return links, rechts


def beschriftung_lesen(im, rahmen: Rahmen, ticks: list[float],
                       achse: str) -> list[tuple[float, float]]:
    """Paare (Pixelposition, Winkel in Grad) fuer jeden beschrifteten Tick.

    Nur Ticks, die auf dem Raster liegen, kommen infrage -- ein Hindernissymbol mit einer Zahl
    daneben darf keine Stuetzstelle werden. Ticks mit unlesbarer Zahl fallen heraus.
    """
    d, _anzahl, anker = raster(ticks)
    echte = raster_treffer(ticks, d, anker) if d else ticks
    paare: list[tuple[float, float]] = []
    for t in echte:
        a, b = zeichen_im_band(im, rahmen, t, achse, d)
        grad, minute = zahl_lesen(a), zahl_lesen(b)
        if grad is None or minute is None or not (0 <= minute < 60):
            continue
        paare.append((t, grad + minute / 60.0))
    return paare
