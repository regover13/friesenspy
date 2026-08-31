"""Die Gegenprobe zur Handpassung muss einen falschen Klick wirklich fangen.

Der erste Anlauf tat das nicht: Er verglich Pixelabstand mal Massstab mit der Bahnlaenge
aus OurAirports -- und bestand IMMER mit 0,00 Prozent, weil ``handpassung`` den Massstab aus
denselben zwei Punkten ableitet. Die Rechnung prueft sich selbst.

Diese Tests binden deshalb an das, worauf es ankommt: Ein absichtlich danebengesetzter
Klick MUSS durchfallen.
"""
from __future__ import annotations

import math

import pytest

from app import runway_ref

from scripts.passung_pruefen import (
    leiste_px, massstab_aus_leiste, pruefe,
)

# Die beiden Schwellen der EDDL-Bahn 05R/23L, UNGERUNDET aus runways.csv.
S_05R = (51.279598236083984, 6.751989841461182)
S_23L = (51.2958984375, 6.786220073699951)

# Die Laenge wird GERECHNET, nicht getippt. "2999 m" ist der gerundete Wert; er ergibt
# 0,02 Prozent Abweichung und laesst den Genauigkeitstest scheitern. Dieselbe Rundungsfalle
# ist in diesem Projekt schon zweimal zugeschnappt (tests/test_runway_ref.py und
# tests/test_ground_charts.py) -- gerundete Zahlen in einem Test, der Genauigkeit prueft,
# sind ein Widerspruch in sich.
BAHN_M = math.hypot(*runway_ref.meter(S_05R, S_23L))

# Ein gedachtes Blatt: die Bahn waagerecht, 1770 px zwischen den Schwellen.
P1 = (200.0, 500.0)
P2 = (1970.0, 500.0)
MPS_WAHR = BAHN_M / 1770.0                     # rund 1,695 m/px

# Eine Massstabsleiste, die zu diesem Blatt passt: 500 m ueber 295 px.
LEISTE_A, LEISTE_B = (100.0, 1150.0), (100.0 + 500.0 / MPS_WAHR, 1150.0)
LEISTE_M = 500.0


def _mps_leiste():
    return massstab_aus_leiste(LEISTE_A, LEISTE_B, LEISTE_M)


def _px_leiste():
    return leiste_px(LEISTE_A, LEISTE_B)


def test_die_leiste_misst_denselben_massstab():
    assert _mps_leiste() == pytest.approx(MPS_WAHR, rel=1e-9)


def test_richtig_gesetzte_schwellen_bestehen():
    e = pruefe(P1, S_05R, P2, S_23L, _mps_leiste(), _px_leiste())
    assert e["ok"]
    assert e["abweichung_prozent"] == pytest.approx(0.0, abs=0.01)


def test_ein_mitgeklickter_stopway_faellt_durch():
    """DER Test. Die alte Fassung bestand hier mit 0,00 Prozent.

    120 m Stopway sind bei diesem Massstab rund 71 px. Der Klick sitzt also am Ende der
    grauen Flaeche statt an der Schwelle -- genau der Fehler, an dem die alte
    Bahnvermessung gescheitert ist (EDDV: 2784 m fuer eine 2340-m-Bahn).
    """
    p2_falsch = (P2[0] + 120.0 / MPS_WAHR, P2[1])
    e = pruefe(P1, S_05R, p2_falsch, S_23L, _mps_leiste(), _px_leiste())
    assert not e["ok"], "der Stopway-Fehler wird nicht gefangen"
    assert e["abweichung_prozent"] > e["schranke_prozent"]


def test_ein_kleines_wackeln_besteht_noch():
    """Drei bis fuenf Pixel Klickunsicherheit sind normal und duerfen nicht anschlagen --
    sonst faellt jede zweite richtige Passung durch und die Schranke wird weggedrueckt."""
    e = pruefe(P1, S_05R, (P2[0] + 5.0, P2[1] + 2.0), S_23L, _mps_leiste(), _px_leiste())
    assert e["ok"], f"{e.get('abweichung_prozent')} % -- zu streng"


def test_ohne_leiste_gilt_die_passung_als_ungeprueft():
    """Kein stilles Bestehen: Wer keine Leiste misst, hat nichts geprueft, und das muss
    dranstehen."""
    e = pruefe(P1, S_05R, P2, S_23L, None)
    assert not e["ok"]
    assert e["geprueft"] is False
    assert "UNGEPRUEFT" in e["grund"]


def test_ein_faktor_zwei_fehler_faellt_aus_dem_band():
    """Grober Schutz zusaetzlich zur Leiste: Wer die halbe Bahn klickt, landet beim
    doppelten Massstab."""
    e = pruefe(P1, S_05R, (P1[0] + 885.0, P1[1]), S_23L, _mps_leiste(), _px_leiste())
    assert not e["ok"]


def test_eine_zu_kurz_gemessene_leiste_wird_abgewiesen():
    """Unter 20 px ist der Wert Rauschen -- drei Pixel Unsicherheit waeren dort 15 Prozent."""
    with pytest.raises(ValueError):
        massstab_aus_leiste((100.0, 100.0), (110.0, 100.0), 500.0)


def test_die_pruefung_ist_nicht_zirkulaer():
    """Der Kern: Das Ergebnis muss sich aendern, wenn NUR der Klick wandert.

    Die alte Fassung lieferte fuer jede beliebige Klickposition dieselbe Abweichung von
    0,00 Prozent. Hier muss sie mit dem Fehler wachsen.
    """
    abweichungen = []
    for versatz_px in (0.0, 20.0, 50.0, 100.0):
        e = pruefe(P1, S_05R, (P2[0] + versatz_px, P2[1]), S_23L, _mps_leiste(), _px_leiste())
        abweichungen.append(e["abweichung_prozent"])
    assert abweichungen == sorted(abweichungen)
    assert abweichungen[0] < abweichungen[-1], "die Probe reagiert gar nicht auf den Klick"


def test_eine_laengere_leiste_ergibt_eine_schaerfere_schranke():
    """Die Schranke haengt fast ganz an der Leiste: drei Pixel sind auf 295 px ein volles
    Prozent, auf 1180 px nur ein Viertel davon.

    Wer sorgfaeltiger misst, soll auch schaerfer geprueft werden -- eine feste Schranke
    liesse sonst bei langer Leiste unnoetig viel durch."""
    kurz = pruefe(P1, S_05R, P2, S_23L, _mps_leiste(), 295.0)
    lang = pruefe(P1, S_05R, P2, S_23L, _mps_leiste(), 1180.0)
    assert lang["schranke_prozent"] < kurz["schranke_prozent"]


def test_mit_langer_leiste_faellt_auch_ein_kleiner_stopway_durch():
    """Bei 295 px Leiste rutschte ein 60-m-Stopway mit 1,96 Prozent durch. Mit einer
    viermal so lang gemessenen Leiste wird er gefangen."""
    p2_falsch = (P2[0] + 60.0 / MPS_WAHR, P2[1])
    kurz = pruefe(P1, S_05R, p2_falsch, S_23L, _mps_leiste(), 295.0)
    lang = pruefe(P1, S_05R, p2_falsch, S_23L, _mps_leiste(), 1180.0)
    assert kurz["ok"], "bei kurzer Leiste ist das erwartet -- sie kann es nicht aufloesen"
    assert not lang["ok"], "bei langer Leiste muss er gefangen werden"
