"""Synthetische AIP-Blaetter fuer die Tests.

**Warum keine echten Blaetter im Repo:** ``regover13/friesenspy`` ist oeffentlich. Die
DFS-Sichtflugkarten tragen "© DFS Deutsche Flugsicherung GmbH"; sie hier abzulegen waere eine
Veroeffentlichung -- genau das, was die Spec ausschliesst (Zugriff nur durch
``forum_login_gate``, kein Export). Die gemessenen Zahlen echter Blaetter stehen dagegen in
``messwerte.json``: Messwerte sind Tatsachen, kein Werk.

Fuer die Erkennung ist das kein Verlust, im Gegenteil -- ein erzeugtes Blatt ist
deterministisch, und man kann gezielt die Faelle bauen, an denen die Erkennung frueher
gescheitert ist (Stoerstriche im Randband, gekreuzte Rahmenlinie, feines Gitter).

Die Ziffernformen hier sind NICHT die der DFS. Sie pruefen die Segmentierung und den
Schablonenvergleich als Verfahren; die echten Schablonen gewinnt
``scripts/aip_schablonen.py`` aus den Blaettern auf dem Server.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

# Eigene 5x9-Bitmapschrift. Bewusst schlicht und gut unterscheidbar.
ZIFFERN: dict[str, tuple[str, ...]] = {
    "0": ("#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#####"),
    "1": ("..##.", ".#.#.", "...#.", "...#.", "...#.", "...#.", "...#.", "...#.", "#####"),
    "2": ("#####", "....#", "....#", "....#", "#####", "#....", "#....", "#....", "#####"),
    "3": ("#####", "....#", "....#", "....#", "#####", "....#", "....#", "....#", "#####"),
    "4": ("#...#", "#...#", "#...#", "#...#", "#####", "....#", "....#", "....#", "....#"),
    "5": ("#####", "#....", "#....", "#....", "#####", "....#", "....#", "....#", "#####"),
    "6": ("#####", "#....", "#....", "#....", "#####", "#...#", "#...#", "#...#", "#####"),
    "7": ("#####", "....#", "....#", "....#", "....#", "....#", "....#", "....#", "....#"),
    "8": ("#####", "#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#####"),
    "9": ("#####", "#...#", "#...#", "#...#", "#####", "....#", "....#", "....#", "#####"),
}
ZIFFER_B, ZIFFER_H, ZIFFER_ABSTAND = 5, 9, 2


def _zahl_malen(zeichnung: ImageDraw.ImageDraw, text: str, x: int, y: int) -> None:
    for i, z in enumerate(text):
        muster = ZIFFERN.get(z)
        if muster is None:
            continue
        ox = x + i * (ZIFFER_B + ZIFFER_ABSTAND)
        for dy, zeile in enumerate(muster):
            for dx, p in enumerate(zeile):
                if p == "#":
                    zeichnung.point((ox + dx, y + dy), fill=0)


def blatt_bauen(
    breite: int = 875,
    hoehe: int = 1240,
    feld: tuple[int, int, int, int] = (132, 180, 817, 865),
    band: int = 24,
    tick_lat_px: float = 219.0,
    tick_lon_px: float = 128.4,
    breite_links: tuple[int, int] = (54, 14),
    laenge_oben: tuple[int, int] = (9, 36),
    stoerstriche: bool = False,
    rahmen_kreuzen: bool = False,
    kopf_fuss_linien: bool = False,
) -> Image.Image:
    """Ein Blatt mit Doppelrahmen, Gradnetz und Beschriftung.

    ``stoerstriche``  setzt zusaetzliche senkrechte Striche ins obere Randband -- so sehen
                      Hindernissymbole (Windraeder) aus, die bei EDCQ die Tickfolge zerstoert
                      haben.
    ``rahmen_kreuzen`` unterbricht die linke Rahmenlinie, wie es die vertikale
                      "Berichtigung:"-Beschriftung tut (dort nur 88 Prozent durchgehend).
    """
    links, oben, rechts, unten = feld
    im = Image.new("L", (breite, hoehe), 255)
    d = ImageDraw.Draw(im)

    # Innerer und aeusserer Rahmen
    d.rectangle([links, oben, rechts, unten], outline=0)
    d.rectangle([links - band, oben - band, rechts + band, unten + band], outline=0)

    if rahmen_kreuzen:
        # Luecke in der linken aeusseren Linie: die Erkennung darf nicht am laengsten
        # durchgehenden Lauf haengen, sondern am Anteil dunkler Pixel.
        mitte = (oben + unten) // 2
        d.line([links - band, mitte - 40, links - band, mitte + 40], fill=255)

    # Ticks am oberen Band tragen die LAENGE
    grad, minute = laenge_oben
    x = float(links) + tick_lon_px / 2
    i = 0
    while x < rechts:
        d.line([x, oben - band, x, oben], fill=0)
        _zahl_malen(d, f"{grad:02d}", int(x) - 16, oben - band + 3)
        _zahl_malen(d, f"{(minute + i) % 60:02d}", int(x) + 3, oben - band + 3)
        x += tick_lon_px
        i += 1

    # Ticks am linken Band tragen die BREITE
    grad_l, minute_l = breite_links
    y = float(oben) + tick_lat_px / 2
    j = 0
    while y < unten:
        d.line([links - band, y, links, y], fill=0)
        _zahl_malen(d, f"{grad_l:02d}", links - band + 3, int(y) - ZIFFER_H - 2)
        _zahl_malen(d, f"{(minute_l - j) % 60:02d}", links - band + 3, int(y) + 3)
        y += tick_lat_px
        j += 1

    if kopf_fuss_linien:
        # Echte Blaetter tragen ueber und unter dem Kartenfeld je eine Layout-Trennlinie,
        # die weiter aussen liegt und ueber die volle Blattbreite laeuft. rahmen_finden darf
        # sie NICHT fuer den Kartenrahmen halten. Bewusst als PAAR gezeichnet (Abstand 24 px,
        # also im Doppelrahmen-Fenster) -- eine Einzellinie waere kein ernsthafter Test.
        for ly in (oben - band - 44, oben - band - 20,
                   unten + band + 20, unten + band + 44):
            if 0 <= ly < hoehe:
                d.line([0, ly, breite - 1, ly], fill=0)

    if stoerstriche:
        for sx in (links + 40, links + 95, links + 150):
            d.line([sx, oben - band + 4, sx, oben - 2], fill=0)

    return im


if __name__ == "__main__":  # Sichtprobe
    blatt_bauen().save("/tmp/blatt_probe.png")
    print("geschrieben: /tmp/blatt_probe.png")
