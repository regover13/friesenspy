"""Das Gradnetz-Werkzeug.

Es hat vier Blaetter passbar gemacht, an denen das Schwellenverfahren scheiterte -- und
sich dabei drei Fallen eingefangen, gegen die hier gebunden wird.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from scripts.gradnetz import (
    GRAD_FENSTER, gegenschar, maske, netzbild, punkt, schar, verhaeltnis_stimmt,
)


def _gitter(winkel: float, abstand_h: float, abstand_v: float,
            groesse: tuple[int, int] = (900, 700)) -> np.ndarray:
    """Ein gezeichnetes Gitter -- duenne graue Linien auf Weiss, wie auf einem DFS-Blatt."""
    im = Image.new("RGB", groesse, (255, 255, 255))
    z = ImageDraw.Draw(im)
    W, H = groesse
    t = math.radians(winkel)
    lang = 2 * (W + H)
    for k in range(-40, 41):
        r = k * abstand_h
        z.line([(-lang, (r - lang * math.sin(t)) / math.cos(t)),
                (lang, (r + lang * math.sin(t)) / math.cos(t))], fill=(150, 150, 150), width=1)
        r = k * abstand_v
        z.line([((r + lang * math.sin(t)) / math.cos(t), -lang),
                ((r - lang * math.sin(t)) / math.cos(t), lang)], fill=(150, 150, 150), width=1)
    return np.asarray(im, dtype=np.uint8)


def test_ein_ungedrehtes_gitter_wird_gefunden():
    a = _gitter(0.0, 80.0, 60.0)
    grad, gipfel = schar(maske(a, "h"), "h")
    assert grad == pytest.approx(0.0, abs=0.2)
    d = [gipfel[i + 1][0] - gipfel[i][0] for i in range(len(gipfel) - 1)]
    assert np.median(d) == pytest.approx(80.0, abs=1.0)


def test_ein_stark_gedrehtes_blatt_wird_noch_gefunden():
    """EDLP liegt bei 33 Grad. Das Fenster stand zuerst bei +-8 Grad und meldete dort einen
    Treffer -- irgendwelche Rollwege, gleichmaessig genug, um zu ueberzeugen."""
    assert GRAD_FENSTER >= 34.0
    a = _gitter(33.2, 90.0, 70.0)
    grad, _ = schar(maske(a, "h"), "h")
    assert grad == pytest.approx(33.2, abs=0.3)


def test_die_zweite_schar_wird_am_winkel_der_ersten_gefesselt():
    """Frei gesucht findet die zweite Schar in einem vollen Blatt Rollwege. Ein
    geographisches Gitter ist rechtwinklig -- der Winkel ist also bereits bekannt."""
    a = _gitter(20.0, 100.0, 65.0)
    erst = schar(maske(a, "h"), "h")
    zweit = gegenschar(a, "v", erst[0])
    assert zweit[0] == pytest.approx(erst[0], abs=0.3)
    d = [zweit[1][i + 1][0] - zweit[1][i][0] for i in range(len(zweit[1]) - 1)]
    assert np.median(d) == pytest.approx(65.0, abs=1.0)


def test_der_schnittpunkt_liegt_auf_beiden_linien():
    x, y = punkt(16.0, 320.7, 16.0, 759.1)
    t = math.radians(16.0)
    assert y * math.cos(t) - x * math.sin(t) == pytest.approx(320.7, abs=1e-6)
    assert x * math.cos(t) + y * math.sin(t) == pytest.approx(759.1, abs=1e-6)


def test_das_abstandsverhaeltnis_entlarvt_vertauschte_scharen():
    """DIE Probe ohne Beschriftung. Bei EDLP (57 Grad gedreht) sind die waagerechteren
    Linien die der LAENGEN; verwechselt man sie, sieht das Blatt kaputt aus.

    EDDH, gemessen: Breiten 280,8 px, Laengen 166,9 px bei 53,63 Grad Nord.
    """
    assert verhaeltnis_stimmt(280.8, 166.9, 53.63)
    assert not verhaeltnis_stimmt(166.9, 280.8, 53.63), "vertauscht muss auffallen"


def test_das_verhaeltnis_faengt_auch_einen_falschen_schritt():
    """Waere eine Schar in Wahrheit 20 Sekunden statt 10, stimmte das Verhaeltnis nicht."""
    assert not verhaeltnis_stimmt(280.8 * 2, 166.9, 53.63)


def test_das_netzbild_zeichnet_beide_scharen(tmp_path):
    """Ohne dieses Bild wird die Beschriftung an einer gerechneten Stelle zugeschnitten --
    und man erwischt das Etikett der Nachbarlinie. Bei EDDS kostete das 8,28 Prozent."""
    im = Image.new("RGB", (400, 300), (255, 255, 255))
    ziel = str(tmp_path / "netz.png")
    netzbild(im, 0.0, [50.0, 150.0], 0.0, [80.0, 200.0], ziel)
    aus = np.asarray(Image.open(ziel).convert("RGB"))
    assert (aus[:, :, 0] > 200).any() and (aus[:, :, 2] > 200).any()
