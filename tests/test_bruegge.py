"""Die Brügge: Positionsmatching und Endpunkt.

Die Regeln stammen aus dem Kniebrett (`_verkehrZusammenfuehren`), und genau deshalb prüfen
diese Tests nicht „irgendein Matching", sondern die **Eigenschaften**, die dort im Flug
erarbeitet wurden: Vorsprung statt fester Schranke, Lösen erst nach mehreren Verstößen in
Folge, Fortrechnen gegen das Alter des Feeds.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest

from app import bruegge


def _friese(cid, callsign, lat, lon, alt=0, gs=0, hdg=0, alter_s=0):
    ts = datetime.now(timezone.utc) - timedelta(seconds=alter_s)
    return {
        "cid": cid, "callsign": callsign, "latitude": lat, "longitude": lon,
        "altitude": alt, "groundspeed": gs, "heading": hdg,
        "updated_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------------------
# Die Kinematik
# ---------------------------------------------------------------------------------------

def test_stehendes_flugzeug_wird_nicht_fortgerechnet():
    lat, lon = bruegge.jetzt_gerechnet(53.78, 7.92, kurs=90, gs_kt=0, alter_s=29)
    assert (lat, lon) == (53.78, 7.92)


def test_fortrechnung_folgt_dem_kurs():
    """Nach Norden heißt: Breite steigt, Länge bleibt."""
    lat, lon = bruegge.jetzt_gerechnet(53.0, 7.0, kurs=0, gs_kt=100, alter_s=36)
    assert lat > 53.0
    assert lon == pytest.approx(7.0, abs=1e-9)
    # 100 kt über 36 s sind rund 1,85 km -- also gut 0,0166 Grad Breite.
    assert bruegge.abstand_m(53.0, 7.0, lat, lon) == pytest.approx(1852, rel=0.02)


def test_schranke_waechst_mit_der_geschwindigkeit():
    """Der Kern des Entwurfs: keine feste Zahl, sondern Weg = Geschwindigkeit mal Zeit.

    Eine C172 (110 kt) darf in 29 s rund 1,6 km abweichen, ein Airliner (450 kt) rund 6,7 km.
    Eine feste Schranke wäre für das eine zu weit und für das andere zu eng.
    """
    langsam = bruegge.schranke_m(110, bruegge.PAARUNG_FAKTOR)
    schnell = bruegge.schranke_m(450, bruegge.PAARUNG_FAKTOR)
    assert schnell > langsam * 3
    # Und im Stand greift die Untergrenze, sonst fände ein stehendes Flugzeug nie einen Partner.
    assert bruegge.schranke_m(0, bruegge.PAARUNG_FAKTOR) == bruegge.PAARUNG_MIN_M


def test_hoehenschranke_beachtet_die_sinkrate():
    """Ein sinkendes Flugzeug MUSS von seiner VATSIM-Höhe abweichen -- das ist kein Fehler."""
    ruhig = bruegge.schranke_ft(0, bruegge.PAARUNG_FAKTOR)
    sinkt = bruegge.schranke_ft(2000, bruegge.PAARUNG_FAKTOR)
    assert ruhig == bruegge.PAARUNG_MIN_FT
    # 2000 ft/min über 29 s sind 967 ft; mit Faktor 2 rund 1930.
    assert sinkt == pytest.approx(1933, rel=0.02)


# ---------------------------------------------------------------------------------------
# Die Zuordnung
# ---------------------------------------------------------------------------------------

def test_einzelner_kandidat_wird_zugeordnet():
    k = bruegge.kandidaten_bilden([_friese(111, "FRS01", 53.7800, 7.9200)])
    treffer, grund = bruegge.zuordnen(53.7801, 7.9201, 0, 0, k)
    assert treffer is not None and treffer.cid == 111
    assert "eindeutig" in grund


def test_zu_weit_entfernt_findet_niemanden():
    k = bruegge.kandidaten_bilden([_friese(111, "FRS01", 53.7800, 7.9200)])
    treffer, grund = bruegge.zuordnen(53.9000, 7.9200, 0, 0, k)
    assert treffer is None
    assert "kein Kandidat" in grund


def test_hoehe_trennt_zwei_flugzeuge_uebereinander():
    """Zwei Friesen an derselben Koordinate, 5000 ft auseinander."""
    k = bruegge.kandidaten_bilden([
        _friese(111, "FRS01", 53.7800, 7.9200, alt=1000),
        _friese(222, "FRS02", 53.7800, 7.9200, alt=6000),
    ])
    treffer, _ = bruegge.zuordnen(53.7800, 7.9200, 1050, 0, k)
    assert treffer is not None and treffer.cid == 111


def test_vorsprung_entscheidet_nicht_die_schranke():
    """DER Kernfall, um den es im Kniebrett zwei Fehlversuche gab.

    Zwei Friesen im selben Umkreis: einer 20 m weg, einer 300 m. Beide liegen innerhalb der
    400-m-Untergrenze -- „genau einer innerhalb der Schranke" hätte hier NICHTS zugeordnet.
    Über den Vorsprung ist es eindeutig.
    """
    nah = _friese(111, "FRS01", 53.78000, 7.92000)
    fern = _friese(222, "FRS02", 53.78270, 7.92000)   # rund 300 m nördlich
    k = bruegge.kandidaten_bilden([nah, fern])
    treffer, grund = bruegge.zuordnen(53.78002, 7.92000, 0, 0, k)
    assert treffer is not None and treffer.cid == 111
    assert "Vorsprung" in grund


def test_zwei_dicht_beieinander_werden_nicht_geraten():
    """Kein klarer Vorsprung heißt: nicht zuordnen.

    Eine falsche Zuordnung ist schlimmer als gar keine -- man sieht ihr nicht an, dass sie
    falsch ist.
    """
    k = bruegge.kandidaten_bilden([
        _friese(111, "FRS01", 53.78000, 7.92000),
        _friese(222, "FRS02", 53.78010, 7.92000),   # rund 11 m daneben
    ])
    treffer, grund = bruegge.zuordnen(53.78005, 7.92000, 0, 0, k)
    assert treffer is None
    assert "ohne Vorsprung" in grund


def test_alte_vatsim_meldung_wird_aufgeholt():
    """Ein Friese, dessen Meldung 29 s alt ist, ist weitergeflogen.

    Ohne Fortrechnung läge er 1,5 km hinter seiner tatsächlichen Position -- und die Brügge,
    die dort meldet, wo er wirklich ist, fände ihn nicht.
    """
    # 110 kt nach Osten, Meldung 29 s alt.
    f = _friese(111, "FRS01", 53.7800, 7.9200, gs=110, hdg=90, alter_s=29)
    k = bruegge.kandidaten_bilden([f])
    # Dort steht er jetzt wirklich: rund 1,6 km östlich.
    ist_lat, ist_lon = bruegge.jetzt_gerechnet(53.7800, 7.9200, 90, 110, 29)
    treffer, _ = bruegge.zuordnen(ist_lat, ist_lon, 0, 110, k)
    assert treffer is not None and treffer.cid == 111


# ---------------------------------------------------------------------------------------
# Sprünge
# ---------------------------------------------------------------------------------------

def test_sprung_wird_erkannt():
    """0/90, Seattle, Wangerooge -- der Ladevorgang eines Simulators in drei Schritten."""
    assert bruegge.ist_sprung(53.78, 7.92, 0.0, 90.0) is True
    assert bruegge.ist_sprung(53.78, 7.92, 47.5189, -122.2945) is True


def test_normaler_flug_ist_kein_sprung():
    """Bei 1-Sekunden-Takt liegt selbst ein sehr schnelles Flugzeug unter der Schranke."""
    # 600 kt sind 309 m/s -- eine Sekunde weiter nach Norden.
    lat, lon = bruegge.jetzt_gerechnet(53.78, 7.92, 0, 600, 1)
    assert bruegge.ist_sprung(lat, lon, 53.78, 7.92) is False


def test_erste_meldung_gilt_nicht_als_sprung():
    assert bruegge.ist_sprung(53.78, 7.92, None, None) is False


# ---------------------------------------------------------------------------------------
# Das Halten einer Zuordnung
# ---------------------------------------------------------------------------------------

def test_gemerkte_zuordnung_ist_grosszuegiger_als_die_erstzuordnung():
    """Ein zu frühes Lösen bringt das Flackern zurück -- deshalb Faktor 3 statt 2.

    Gemessen wird das IN FAHRT, und das ist kein Zufall: Im Stand greift die Untergrenze von
    400 m, und die macht beide Schranken gleich groß (s. Test darunter).
    """
    f = _friese(111, "FRS01", 53.78000, 7.92000, gs=110, hdg=90)
    k = bruegge.kandidaten_bilden([f])
    # Bei 110 kt: Erstzuordnung bis rund 3,3 km, Lösen bis rund 4,9 km. 4 km liegt dazwischen.
    weit_lat = 53.78000 + 4000 / 111320.0
    treffer, _ = bruegge.zuordnen(weit_lat, 7.92000, 0, 110, k)
    assert treffer is None, "so weit darf NICHT erstzugeordnet werden"
    assert bruegge.bleibt_plausibel(weit_lat, 7.92000, 0, 110, k[0]) is True,         "eine bestehende Zuordnung muss das aushalten"


def test_im_stand_wirkt_der_loesefaktor_nicht():
    """Eine Eigenschaft, die überrascht -- und die aus dem Kniebrett übernommen ist.

    ``max(400, gs * 29 * faktor)`` ist bei ``gs = 0`` unabhängig vom Faktor immer 400. Der
    großzügigere Löse-Faktor greift also erst oberhalb von rund 13 kt. Für ein stehendes
    Flugzeug ist das unkritisch -- es bewegt sich ja nicht -- aber wer die Konstanten ändert,
    sollte es wissen, statt es für einen Fehler zu halten.
    """
    assert bruegge.schranke_m(0, bruegge.PAARUNG_FAKTOR) ==            bruegge.schranke_m(0, bruegge.PAARUNG_LOESEN_FAKTOR)
    assert bruegge.schranke_m(30, bruegge.PAARUNG_LOESEN_FAKTOR) >            bruegge.schranke_m(30, bruegge.PAARUNG_FAKTOR)
