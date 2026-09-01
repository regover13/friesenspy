"""Passpunkte aus einer gespeicherten Lage zurueckrechnen.

Die 68 auto-Karten tragen ein fertiges Rechteck, aber keine geklickten Punkte -- die alte
Automatik hat nie welche erzeugt. In der Passen-Maske kam deshalb allein die Drehung an.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.ground_charts import handpassung, norden, punkte_aus_lage

BREITE, HOEHE = 1600, 1100
S_05R = (51.279598236083984, 6.751989841461182)
S_23L = (51.2958984375, 6.786220073699951)


def _blatt() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (BREITE, HOEHE), (255, 255, 255)).save(puffer, "PNG")
    return puffer.getvalue()


def _hin_und_zurueck(p1_px, p2_px):
    """Passung bilden, ablegen wie im Betrieb, aus dem Ergebnis Punkte zurueckrechnen."""
    p = handpassung(p1_px, S_05R, p2_px, S_23L)
    _bytes, grenzen = norden(_blatt(), p, "flugplatzkarte")
    zurueck = punkte_aus_lage(BREITE, HOEHE, p.drehung, p.mps,
                              grenzen["nord"], grenzen["sued"], grenzen["west"], grenzen["ost"])
    neu = handpassung((zurueck["p1_x"], zurueck["p1_y"]), (zurueck["p1_lat"], zurueck["p1_lon"]),
                      (zurueck["p2_x"], zurueck["p2_y"]), (zurueck["p2_lat"], zurueck["p2_lon"]))
    return p, zurueck, neu


@pytest.mark.parametrize("p1_px,p2_px", [
    ((200.0, 800.0), (1400.0, 300.0)),     # schraeg, wie eine gedrehte Bahn
    ((150.0, 550.0), (1450.0, 550.0)),     # waagerecht -- Drehung nahe 0
    ((800.0, 950.0), (800.0, 150.0)),      # senkrecht
])
def test_die_zurueckgerechnete_passung_ist_dieselbe(p1_px, p2_px):
    """DER Test: Was zurueckkommt, muss dasselbe Blatt an dieselbe Stelle legen."""
    alt, _zurueck, neu = _hin_und_zurueck(p1_px, p2_px)
    assert neu.mps == pytest.approx(alt.mps, rel=1e-3)
    assert min(abs(neu.drehung - alt.drehung),
               360 - abs(neu.drehung - alt.drehung)) < 0.05


def test_die_zurueckgerechneten_ecken_treffen_das_gespeicherte_rechteck():
    """Nicht nur Massstab und Drehung -- auch die LAGE muss stimmen. Ein Vorzeichenfehler
    in der Rueckrechnung faellt sonst nicht auf, weil er das Blatt nur verschiebt."""
    alt, _z, neu = _hin_und_zurueck((200.0, 800.0), (1400.0, 300.0))
    _b1, alt_g = norden(_blatt(), alt, "flugplatzkarte")
    _b2, neu_g = norden(_blatt(), neu, "flugplatzkarte")
    for kante in ("nord", "sued", "west", "ost"):
        # 1e-5 Grad sind rund einen Meter.
        assert neu_g[kante] == pytest.approx(alt_g[kante], abs=2e-5), kante


def test_die_punkte_liegen_weit_auseinander_und_im_blatt():
    """Ein Pixel Fehler wirkt sich umgekehrt proportional zum Abstand auf den Massstab aus."""
    z = punkte_aus_lage(BREITE, HOEHE, 37.0, 1.7, 51.30, 51.25, 6.70, 6.80)
    for wert, grenze in ((z["p1_x"], BREITE), (z["p2_x"], BREITE),
                         (z["p1_y"], HOEHE), (z["p2_y"], HOEHE)):
        assert 0 <= wert <= grenze
    assert abs(z["p2_x"] - z["p1_x"]) > BREITE * 0.6


def test_eine_zeile_ohne_lage_gibt_nichts_zurueck():
    """auto-Karten ohne Rechteck gibt es nicht, aber offene Zeilen tragen vier Nullen."""
    assert punkte_aus_lage(BREITE, HOEHE, 0.0, 1.7, 0.0, 0.0, 0.0, 0.0) is None
    assert punkte_aus_lage(BREITE, HOEHE, 0.0, 0.0, 51.3, 51.25, 6.7, 6.8) is None
