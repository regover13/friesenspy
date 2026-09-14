# -*- coding: utf-8 -*-
"""Die drei Materialfarben auf EINE Textur legen -- und die UVs darauf richten.

WARUM UEBERHAUPT
X-Plane erlaubt genau **eine** Textur je `.obj`; unser Seehund traegt seine Farben aber in
drei Materialien (`brown`, `lightbrown`, `black`). MSFS koennte drei Materialien, braucht
dann aber drei Eintraege in der Materialbibliothek -- eine Textur ist auch dort einfacher.

WARUM KEINE UV-ENTFALTUNG
Naheliegend waere, das Netz aufzuklappen (Smart UV Project) und die Farben zu backen. Das
ist hier ueberfluessiger Aufwand mit Verlusten an den Nahtstellen: Es gibt nur drei FLACHE
Farben, keine Zeichnung. Stattdessen bekommt jede Flaeche die UV-Koordinate der MITTE
ihres Farbfelds -- exakt, verlustfrei, und die Textur darf winzig sein.

⚠ IN DIE MITTE DES FELDS, NICHT AN DEN RAND. Bilineare Filterung und Mipmaps mischen ueber
Feldgrenzen hinweg; ein Punkt am Rand holt sich beim Verkleinern die Nachbarfarbe dazu. Mit
64 x 64 Pixeln und vier Feldern liegen zwischen den Mittelpunkten 32 Pixel -- das haelt bis
in die kleinste Mipmap-Stufe.

⚠ UND DIE FARBEN MUESSEN NACH sRGB. Blender rechnet linear, eine PNG-Textur wird als sRGB
gelesen. Wer die linearen Werte direkt hineinschreibt, bekommt ein deutlich zu dunkles
Tier -- derselbe Fehler, der beim Rauch schon einmal jede Farbe verfaelscht hat.
"""
from __future__ import annotations

KANTE = 64          # Textur 64 x 64
FELDER = 2          # 2 x 2 Felder a 32 Pixel


def _nach_srgb(c: float) -> int:
    c = max(0.0, min(1.0, c))
    s = 1.055 * (c ** (1 / 2.4)) - 0.055 if c > 0.0031308 else 12.92 * c
    return int(round(s * 255))


def _felder(farben: dict) -> list[tuple[str, int, int, tuple]]:
    """Je Material: (Name, Feld-X, Feld-Y, Farbe). Sortiert, damit es reproduzierbar ist."""
    feld = KANTE // FELDER
    raus = []
    for nr, (name, rgba) in enumerate(sorted(farben.items())):
        raus.append((name, (nr % FELDER) * feld, (nr // FELDER) * feld, rgba))
    return raus


def uv_felder(farben: dict) -> dict[str, tuple[float, float]]:
    """Nur die UV-Mitten je Material -- OHNE Pillow.

    ⚠ Getrennt vom Schreiben der Datei, weil BLENDERS PYTHON KEIN PILLOW HAT. Die
    UV-Koordinaten haengen allein von der Feldnummer ab; die Bilddatei entsteht
    ausserhalb, mit dem System-Python. So braucht keiner von beiden das, was der andere
    kann.
    """
    feld = KANTE // FELDER
    uv = {}
    for name, sx, sy, _ in _felder(farben):
        # V laeuft in Bilddateien von oben, in UV von unten.
        uv[name] = ((sx + feld / 2) / KANTE, 1.0 - (sy + feld / 2) / KANTE)
    return uv


def schreiben(pfad, farben: dict[str, tuple]) -> dict[str, tuple[float, float]]:
    """Die Textur schreiben (braucht Pillow). Gibt dieselben UV-Mitten zurueck."""
    from PIL import Image

    bild = Image.new("RGB", (KANTE, KANTE), (0, 0, 0))
    pixel = bild.load()
    feld = KANTE // FELDER
    for name, sx, sy, rgba in _felder(farben):
        farbe = tuple(_nach_srgb(c) for c in rgba[:3])
        for y in range(sy, sy + feld):
            for x in range(sx, sx + feld):
                pixel[x, y] = farbe
    bild.save(pfad, "PNG")
    return uv_felder(farben)


def uv_setzen(netz, uv_je_material: dict[str, tuple[float, float]]) -> int:
    """Jeder Flaeche die UV-Mitte ihres Farbfelds geben. Gibt die Zahl der Ecken zurueck."""
    if not netz.uv_layers:
        netz.uv_layers.new(name="UVMap")
    schicht = netz.uv_layers[0].data
    namen = [m.name if m else "" for m in netz.materials]

    n = 0
    for p in netz.polygons:
        name = namen[p.material_index] if p.material_index < len(namen) else ""
        ziel = uv_je_material.get(name)
        if ziel is None:
            continue
        for i in p.loop_indices:
            schicht[i].uv = ziel
            n += 1
    return n
