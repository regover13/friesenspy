# -*- coding: utf-8 -*-
"""Die Parameter einer FriesenReddung -- reine Rechnung, keine Datenbank (20.09.2026).

**Suchen und Finden sind ZWEI Fenster.** Der Suchkorridor ist weit (1 km) und darf hoch
geflogen werden (2.000 ft) -- er sagt, welche Flaeche abgeflogen ist. Der Fund ist eng (500 ft)
und muss tief sein (1.000 ft) -- er setzt die Rauchfackel. "Abgesucht" heisst damit
ausdruecklich NICHT "haetten wir ihn gesehen"; das traegt, weil zu jedem Event eine Geschichte
gehoert, die das Gebiet eingrenzt.

⚠ Drei Fassungen sind verworfen, und diese Tests halten fest, dass keine wiederkommt: ein
GERECHNETER Fundradius (`korridor + kante/sqrt(2)`, 1,71 km -- eine Cessna 172 sieht niemand aus
1,7 km), der Schrägabstand (bestraft Hoehe, obwohl man von oben weiter sieht) und der Versuch,
beides mit EINER Zahl zu erledigen (dann ist entweder das Absuchen 26 Flugstunden oder der Fund
eine Farce).
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
    "hoehe_max_ft": 2000, "gs_max_kt": 140, "gs_min_kt": 30,
    "fund_radius_m": 150, "fund_hoehe_ft": 1000,
    "havarist_lat": 53.72, "havarist_lon": 7.25,
    "havarist_grund_ft": 20.0,
    "aufnehmen_noetig": 1, "landung_noetig": 1,
}


def test_suchen_ist_weit_und_finden_ist_eng():
    """Der Kern der Aufteilung -- zwei Fenster, nicht eins."""
    assert reddung.korridor_km(EV) == 1.0                      # Suchen, seitlich
    assert reddung.fund_radius_m(EV) == 150                     # Finden, seitlich, in METERN
    assert reddung.fund_radius_km(EV) == pytest.approx(0.15, abs=1e-9)
    assert reddung.fund_radius_km(EV) < reddung.korridor_km(EV)


def test_beide_reichweiten_sind_einstellbar():
    assert reddung.korridor_km({**EV, "korridor_km": 2.5}) == 2.5
    assert reddung.fund_radius_m({**EV, "fund_radius_m": 250}) == 250
    assert reddung.korridor_km({**EV, "korridor_km": None}) == 1.0
    assert reddung.fund_radius_m({**EV, "fund_radius_m": None}) == 150


def test_der_fund_ist_auch_in_der_hoehe_enger():
    """Der Suchkorridor darf hoch geflogen werden, der Fund nicht -- 20 ft Gelaende plus
    2.000 ft Suche gegen 20 ft plus 1.000 ft Fund."""
    assert reddung.hoehe_schranke_msl(EV) == pytest.approx(2020.0)
    assert reddung.fund_hoehe_schranke_msl(EV) == pytest.approx(1020.0)
    assert reddung.fenster_finden(EV).hoehe_max_ft < reddung.fenster_suchen(EV).hoehe_max_ft


def test_das_fundfenster_erbt_das_geschwindigkeitsfenster():
    """Wer parkt, findet nicht; wer rast, sieht nichts -- dieselbe Regel wie beim Suchen."""
    f = reddung.fenster_finden(EV)
    assert f.gs_max_kt == 140 and f.gs_min_kt == 30


def test_die_alten_fassungen_sind_weg():
    """⚠ Drei verworfene Fassungen, verankert am Modul: der GERECHNETE Fundradius
    (korridor + kante/sqrt(2)), der Schrägabstand und der Versuch, Suchen und Finden mit
    EINER Zahl zu erledigen."""
    assert not hasattr(reddung, "fundradius_km"), "der gerechnete Radius ist weg"
    assert not hasattr(reddung, "seitlicher_spielraum_ft"), "der Schrägabstand ist weg"


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
    assert reddung.hoehe_schranke_msl(EV) == pytest.approx(2020.0)
    assert reddung.fenster_suchen(EV).hoehe_max_ft == pytest.approx(2020.0)


def test_ohne_gemessene_grundhoehe_gilt_null():
    assert reddung.grund_ft({**EV, "havarist_grund_ft": None}) == 0.0
    assert reddung.hoehe_schranke_msl({**EV, "havarist_grund_ft": None}) == pytest.approx(2000.0)


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


# --- Event-Analyse fuer die Bilanz (25.09.2026) ------------------------------------------
#
# Nutzer: „zeigt keine tracks an". Bummel und Kutter fuellen beim Oeffnen die Event-Analyse
# mit ihren Streckenplaetzen; eine Reddung hat keine. Ersatz: der naechste Platz zur
# Sektormitte und ein Radius, der von dort den ganzen Sektor erfasst.

def test_die_analyse_erfasst_den_ganzen_sektor():
    from app import geo
    from app.reddung import analyse_platz
    ev = {"sued": 53.54, "west": 6.95, "nord": 53.90, "ost": 7.55}
    a = analyse_platz(ev)
    assert len(a["icao"]) == 4 and a["icao"] != "GLOBAL"
    plat, plon = geo.icao_to_coords(a["icao"])
    for lat in (ev["sued"], ev["nord"]):
        for lon in (ev["west"], ev["ost"]):
            assert geo.haversine(plat, plon, lat, lon) <= a["radius_km"], (lat, lon, a)


def test_die_analyse_nimmt_verdrehte_ecken():
    from app.reddung import analyse_platz
    gerade = analyse_platz({"sued": 53.54, "west": 6.95, "nord": 53.90, "ost": 7.55})
    verdreht = analyse_platz({"sued": 53.90, "west": 7.55, "nord": 53.54, "ost": 6.95})
    assert gerade == verdreht


def test_ohne_platz_in_reichweite_sucht_die_analyse_global():
    from app.reddung import analyse_platz
    a = analyse_platz({"sued": 40.0, "west": -40.0, "nord": 40.3, "ost": -39.6})   # Atlantik
    assert a == {"icao": "global", "radius_km": None}
