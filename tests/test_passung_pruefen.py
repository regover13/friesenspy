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


def test_ein_feines_blatt_faellt_nicht_am_plausibilitaetsband_durch():
    """1:3000 gibt rund 0,51 m/px. Die Untergrenze stand bei 0,8 und wies EDLP deshalb ab,
    obwohl die Leiste nur 0,61 Prozent abwich.

    Der Fehler war die Kalibrierung: Die Grenze war an 68 bereits gepassten Blaettern
    gemessen, unter denen kein einziges 1:3000 war. Eine an vorhandenen Faellen geeichte
    Schranke kennt nur die vorhandenen Faelle.
    """
    p2_fein = (P1[0] + 1770.0, P1[1])
    mps_fein = 0.51
    leiste_a, leiste_b = (100.0, 1150.0), (100.0 + 500.0 / mps_fein, 1150.0)
    # Zwei Punkte, die bei 0,51 m/px genau 1770 px auseinanderliegen.
    import app.runway_ref as rr
    strecke = mps_fein * 1770.0
    ziel = (S_05R[0], S_05R[1] + strecke / (111320.0 * math.cos(math.radians(S_05R[0]))))
    e = pruefe(P1, S_05R, p2_fein, ziel,
               massstab_aus_leiste(leiste_a, leiste_b, 500.0),
               leiste_px(leiste_a, leiste_b))
    assert e["im_band"], f"{e['mps_bahn']} m/px faellt aus dem Band"
    assert e["ok"], e.get("grund")


def test_das_band_deckt_die_ganze_spanne_der_dfs_blaetter():
    """Von 1:3000 (EDLP, 0,51 m/px) bis 1:40000 (ETSI, 6,82). Beide Grenzen haben je einmal
    eine richtige Passung abgewiesen, weil sie an den bis dahin gepassten Blaettern geeicht
    waren -- und unter denen war weder das eine noch das andere.

    Ueber den Faktor dreizehn kann ein Band keinen Faktor-2-Fehler mehr fangen. Der Test
    haelt deshalb nur noch fest, dass beide echten Faelle durchpassen; die Pruefung leistet
    die Leiste.
    """
    from scripts.passung_pruefen import MPS_MAX, MPS_MIN
    assert MPS_MIN <= 0.51 and MPS_MAX >= 6.82


# --------------------------------------------------- Verfahren ARP (ohne Schwellenkoordinaten)

from scripts.passung_pruefen import aus_arp, blattdrehung, probe_bahnlaenge  # noqa: E402


def test_die_blattdrehung_faellt_aus_bahn_und_wahrem_kurs():
    """EDBM: Bahn waagerecht gezeichnet, gedruckt sind 088 Grad rechtweisend."""
    assert blattdrehung((100, 500), (800, 500), 88.0) == pytest.approx(358.0, abs=0.01)
    # Nordgerichtetes Blatt: eine Bahn mit Kurs 090 liegt dort waagerecht.
    assert blattdrehung((100, 500), (800, 500), 90.0) == pytest.approx(0.0, abs=0.01)


def test_aus_arp_baut_eine_passung_mit_dem_vorgegebenen_massstab():
    """Der Sinn des Verfahrens: Massstab kommt aus der Leiste, Drehung aus der Bahnrichtung,
    Lage aus dem ARP -- und keine einzige Schwellenkoordinate wird gebraucht."""
    from app import ground_charts
    p1, g1, p2, g2 = aus_arp((400.0, 300.0), (50.0, 8.0), mps=1.5, drehung=12.0)
    p = ground_charts.handpassung(p1, g1, p2, g2)
    assert p.mps == pytest.approx(1.5, rel=2e-3)
    assert p.drehung == pytest.approx(12.0, abs=0.05)


def test_aus_arp_haelt_den_arp_fest():
    p1, g1, _p2, _g2 = aus_arp((123.0, 456.0), (49.5, 11.07), mps=0.9, drehung=340.0)
    assert p1 == (123.0, 456.0) and g1 == (49.5, 11.07)


def test_die_bahnlaengen_probe_faengt_einen_falschen_massstab():
    """Die Gegenprobe des ARP-Verfahrens. Sie misst etwas anderes als das, woraus die
    Passung gebaut wurde -- die Leiste steckt ja schon im Massstab."""
    gut = probe_bahnlaenge((100.0, 500.0), (100.0 + 860.0 / 1.7, 500.0), 1.7, 860.0)
    assert gut["ok"] and gut["abweichung_prozent"] == pytest.approx(0.0, abs=0.05)
    schlecht = probe_bahnlaenge((100.0, 500.0), (100.0 + 860.0 / 1.7, 500.0), 2.1, 860.0)
    assert not schlecht["ok"]


def test_die_bahnlaengen_probe_vertraegt_die_rundung_der_gedruckten_laenge():
    """EDBM druckt 1000 m fuer 1001,6. Eine Schranke von 0,5 Prozent wiese das ab."""
    e = probe_bahnlaenge((0.0, 0.0), (1001.6, 0.0), 1.0, 1000.0)
    assert e["ok"]
