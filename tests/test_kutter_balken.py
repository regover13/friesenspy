"""Richtung der Balken im Kutter: oben füllen, unten leeren.

Der Gesamtbalken (``_kSegLegend``) ist ein FORTSCHRITTSbalken — er wächst mit dem Gelieferten.
Der Block je Abholplatz (``_kStockLegend``) ist ein BESTANDSbalken — er zeigt, was dort noch
liegt, und leert sich mit jedem Abflug.

In v14.27.1 war der untere herum: Die Füllung war das bereits Abgeholte, der Balken also am
Anfang leer und am Ende voll. Gemeldet am 10.09.2026 („Ich will, dass der Balken sich leert").
Die Verwechslung ist naheliegend genug, um sie festzunageln — beide Größen unterscheiden sich
nur durch ein Vorzeichen, und der Fehler sieht in einem Standbild völlig plausibel aus.

Quelltext-Test statt Verhaltenstest: Die Zeichenfunktionen sind reines Browser-JavaScript ohne
Testlauf im Projekt. Geprüft wird deshalb der AUSDRUCK, der die Breite berechnet — nicht ein
Kommentar daneben, der beim nächsten Umbau stehen bleiben könnte.
"""
from __future__ import annotations

from pathlib import Path

import pytest

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8")


def _funktion(name: str) -> str:
    """Rumpf einer JS-Funktion per Klammerzählung — robuster als eine Zeilenzahl."""
    start = INDEX.index(f"function {name}(")
    tiefe, i = 0, start
    while True:
        if INDEX[i] == "{":
            tiefe += 1
        elif INDEX[i] == "}":
            tiefe -= 1
            if tiefe == 0:
                return INDEX[start:i + 1]
        i += 1


@pytest.fixture(scope="module")
def stock() -> str:
    return _funktion("_kStockLegend")


def _breitenrechnung(stock: str) -> str:
    """Alles zwischen dem Beginn der Segment-Schleife und dem erzeugten ``<div>``.

    Bewusst der GANZE Block, nicht nur die ``pct``-Zeile: In v14.27.1 stand die Umrechnung in
    einer eigenen Zeile davor (``const picked = target_kg - on_stack_kg``). Ein Ausschnitt, der
    erst bei ``const pct`` beginnt, übersieht genau die Fassung, gegen die hier geprüft wird —
    beim ersten Anlauf ist das passiert.
    """
    return stock[stock.index("const segs = items.map"):
                 stock.index("return '<div class=\"kutter-seg")]


def test_fuellung_je_abholplatz_ist_der_reststapel(stock: str):
    """Die farbige Breite kommt aus ``on_stack_kg`` — dem, was noch daliegt."""
    rumpf = _breitenrechnung(stock)
    assert "on_stack_kg" in rumpf, f"Fuellung haengt nicht am Reststapel:\n{rumpf}"


def test_fuellung_ist_nicht_das_bereits_abgeholte(stock: str):
    """Kein ``target_kg - on_stack_kg`` in der Breitenrechnung — das wäre wieder die
    Fortschritts-Lesart von v14.27.1."""
    entkernt = _breitenrechnung(stock).replace(" ", "").replace("\n", "")
    assert "target_kg||0)-(c.on_stack_kg" not in entkernt, \
        "Die Fuellung rechnet wieder das Abgeholte statt des Reststapels"


def test_segmentbreite_bleibt_am_manifest(stock: str):
    """Die Breite der SCHIENE ist das Manifest-Ziel und ändert sich nie.

    Sonst spränge der Balken, sobald eine Frachtart fertig wird — genau der Fehler, den der
    Review zu v14.27.1 gefunden hat.
    """
    assert "100 * c.target_kg / totalTarget" in stock


def test_gesamtbalken_bleibt_ein_fortschrittsbalken():
    """Gegenprobe: Oben zählt weiterhin das Gelieferte, nicht der Reststapel."""
    seg = _funktion("_kSegLegend")
    assert "delivered_kg" in seg
    assert "on_stack_kg" not in seg
