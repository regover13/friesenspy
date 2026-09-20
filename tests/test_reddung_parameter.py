# -*- coding: utf-8 -*-
"""Die Parameter einer FriesenReddung -- reine Rechnung, keine Datenbank (20.09.2026).

Der wichtigste Test hier ist der erste: Der Fundradius wird GERECHNET. Wird er einstellbar,
luegt der Fortschrittsbalken -- eine abgedeckte Zelle heisst nur, dass ein Track im Korridor an
ihrem MITTELPUNKT vorbeilief, und ein Havarist in der Zellecke ist die halbe Zelldiagonale
weiter weg. Siehe Spec, Abschnitt 4.
"""
from __future__ import annotations

import math
import pathlib

import pytest

from app import reddung
from app.gps_legs import _GPS_BLOCK_GS_KT, _GPS_GROUND_AGL_FT

EV = {
    "sued": 53.54, "west": 6.95, "nord": 53.90, "ost": 7.55,
    "kante_km": 1.0, "korridor_km": 1.0,
    "hoehe_max_ft": 1000, "gs_max_kt": 140, "gs_min_kt": 30,
    "havarist_lat": 53.72, "havarist_lon": 7.25,
    "havarist_grund_ft": 20.0,
    "aufnehmen_noetig": 1, "landung_noetig": 1,
}


def test_der_fundradius_ist_korridor_plus_halbe_zelldiagonale():
    assert reddung.fundradius_km(1.0, 1.0) == pytest.approx(1.0 + math.sqrt(2) / 2, abs=1e-9)
    assert reddung.fundradius_km(1.0, 1.0) == pytest.approx(1.7071, abs=1e-4)


def test_volle_abdeckung_garantiert_den_fund():
    """Der Sinn der Rechnung: Jeder Punkt einer abgedeckten Zelle liegt im Fundradius.

    Schlimmster Fall ist die Ecke zwischen vier Zellen -- kante/sqrt(2) vom Mittelpunkt. Wer
    dort liegt und dessen Zelle abgedeckt ist, muss gefunden worden sein.
    """
    for kante in (0.5, 1.0, 2.0, 3.0):
        for korridor in (0.5, 1.0, 2.0):
            ecke = kante / math.sqrt(2)
            assert reddung.fundradius_km(korridor, kante) >= korridor + ecke - 1e-9


def test_strengere_werte_ziehen_den_fundradius_mit():
    """Wer strenger will, verkleinert BEIDE Werte -- das Verhaeltnis bleibt erhalten."""
    assert reddung.fundradius_km(0.6, 0.6) == pytest.approx(1.0243, abs=1e-4)


def test_havarist_ist_ein_gewoehnliches_ziel_mit_dem_schluessel_havarist():
    ziel = reddung.havarist_ziel(EV)
    assert ziel[0] == "havarist"
    assert ziel[1] == 53.72 and ziel[2] == 7.25
    assert ziel[3] == pytest.approx(1.7071, abs=1e-4)


def test_ohne_gesetzten_ort_gibt_es_kein_ziel():
    assert reddung.havarist_ziel({**EV, "havarist_lat": None}) is None


def test_die_zellen_kommen_aus_dem_sektor_und_tragen_den_korridor():
    zellen = reddung.zellen_fuer(EV)
    assert len(zellen) > 1000, "40 x 40 km bei 1-km-Kante"
    assert all(z[3] == 1.0 for z in zellen)
    assert len({z[0] for z in zellen}) == len(zellen)


def test_die_hoehenschranke_ist_agl_ueber_dem_havaristen():
    """1000 ft AGL bei 20 ft Gelaende heisst 1020 ft MSL -- gemessen wird gegen die
    MSL-Hoehe aus position_history."""
    assert reddung.hoehe_schranke_msl(EV) == pytest.approx(1020.0)
    assert reddung.fenster_suchen(EV).hoehe_max_ft == pytest.approx(1020.0)


def test_ohne_gemessene_grundhoehe_gilt_null():
    assert reddung.grund_ft({**EV, "havarist_grund_ft": None}) == 0.0
    assert reddung.hoehe_schranke_msl({**EV, "havarist_grund_ft": None}) == pytest.approx(1000.0)


def test_das_suchfenster_hat_eine_untergrenze():
    """Sonst deckt ein geparktes Flugzeug seine Zelle den ganzen Abend ab."""
    assert reddung.fenster_suchen(EV).gs_min_kt == 30


def test_das_aufnahmefenster_hat_KEINE_untergrenze():
    """Die Falle: Die Suchuntergrenze von 30 kt wuerde genau den Stillstand ausschliessen,
    der beim Aufnehmen gefragt ist."""
    assert reddung.fenster_aufnehmen(EV).gs_min_kt == 0


def test_aufnehmen_mit_landung_nimmt_die_landeregeln_des_projekts():
    f = reddung.fenster_aufnehmen(EV)
    assert f.gs_max_kt == _GPS_BLOCK_GS_KT
    assert f.hoehe_max_ft == pytest.approx(20.0 + _GPS_GROUND_AGL_FT)


def test_aufnehmen_ohne_landung_erlaubt_schwebeflug():
    f = reddung.fenster_aufnehmen({**EV, "landung_noetig": 0})
    assert f.gs_max_kt == reddung.SCHWEBE_GS_KT == 30
    assert f.hoehe_max_ft == pytest.approx(20.0 + _GPS_GROUND_AGL_FT)


def test_die_landeschwellen_werden_importiert_und_nicht_abgeschrieben():
    """Aendert jemand die Landeerkennung, muss die FriesenReddung mitziehen. Verankert am
    Quelltext, damit ein spaeteres Zurueckschreiben der Zahl auffaellt."""
    quelle = pathlib.Path(reddung.__file__).read_text(encoding="utf-8")
    assert "_GPS_BLOCK_GS_KT" in quelle and "_GPS_GROUND_AGL_FT" in quelle
    assert "from app.gps_legs import" in quelle
