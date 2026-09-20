# -*- coding: utf-8 -*-
"""Mehrere Objekte auf einmal: die Matrix (20.09.2026).

Nutzerwunsch: *„eine Funktion, die mehrere auf einmal stellt. Also in bspw. einer Matrix (bspw. 1x10, 2x5, 20x2)
mit x m Abstand."* — und: *„Der Startpunkt ist die erste Ecke."* Gedacht für Licht (eine unbeleuchtete Runway),
aber die Funktion gilt für jede Art.

Festgelegt: Startpunkt = erste Ecke; die Reihen (`laengs`) laufen in Rasterrichtung, die Spalten (`quer`)
stehen quer dazu nach RECHTS; ids `<id>-<reihe>-<spalte>`; höchstens 200 Objekte im ganzen Soll.
"""
import math

import pytest

from app import database as db
from app.geo import haversine
from app.main import _matrix_punkte
from tests.test_bruegge_endpunkt import klient  # noqa: F401  (Fixture)


@pytest.fixture()
def admin(klient):
    from tests.test_bruegge_endpunkt import _admin_kekse
    import app.main as main
    return klient, _admin_kekse(), main.get_settings().DB_PATH


def _setze(klient, kekse, **kw):
    return klient.post("/api/admin/bruegge/soll", cookies=kekse,
                       json={"art": "windrad", "lat": 53.78, "lon": 7.91, **kw})


def _soll(pfad):
    c = db.get_connection(pfad)
    try:
        return {r["id"]: r for r in c.execute("SELECT * FROM bruegge_soll").fetchall()}
    finally:
        c.close()


# ---- die Geometrie ----------------------------------------------------------------------

def test_die_erste_ecke_ist_der_startpunkt():
    p = _matrix_punkte(53.78, 7.91, 0.0, 3, 4, 10.0, 10.0)
    assert (p[0][0], p[0][1]) == (1, 1) and (p[0][2], p[0][3]) == (53.78, 7.91)
    assert len(p) == 12


def test_die_reihen_laufen_in_rasterrichtung_die_spalten_nach_rechts():
    # Raster nach Norden: die nächste Reihe liegt nördlich, die nächste Spalte östlich (rechts davon).
    p = {(r, c): (la, lo) for r, c, la, lo in _matrix_punkte(53.78, 7.91, 0.0, 2, 2, 10.0, 10.0)}
    assert p[(2, 1)][0] > p[(1, 1)][0] and abs(p[(2, 1)][1] - p[(1, 1)][1]) < 1e-9
    assert p[(1, 2)][1] > p[(1, 1)][1] and abs(p[(1, 2)][0] - p[(1, 1)][0]) < 1e-9
    # Raster nach Osten: die Reihen laufen nach Osten, die Spalten nach SÜDEN (rechts von Ost).
    q = {(r, c): (la, lo) for r, c, la, lo in _matrix_punkte(53.78, 7.91, 90.0, 2, 2, 10.0, 10.0)}
    assert q[(2, 1)][1] > q[(1, 1)][1]
    assert q[(1, 2)][0] < q[(1, 1)][0]


def test_der_abstand_stimmt_in_metern():
    p = _matrix_punkte(53.78, 7.91, 37.0, 3, 3, 25.0, 40.0)
    d = {(r, c): (la, lo) for r, c, la, lo in p}
    assert haversine(*d[(1, 1)], *d[(2, 1)]) * 1000 == pytest.approx(25.0, abs=0.2)
    assert haversine(*d[(1, 1)], *d[(1, 2)]) * 1000 == pytest.approx(40.0, abs=0.2)
    assert haversine(*d[(1, 1)], *d[(3, 3)]) * 1000 == pytest.approx(math.hypot(50.0, 80.0), abs=0.5)


# ---- der Endpunkt -----------------------------------------------------------------------

def test_zwei_mal_fuenf_stellt_zehn_objekte(admin):
    klient, kekse, pfad = admin
    r = _setze(klient, kekse, id="feuer", laengs=2, quer=5, abstand_m=20, raster_kurs=90)
    assert r.status_code == 200 and r.json()["anzahl"] == 10
    ids = {f"feuer-{a}-{b}" for a in (1, 2) for b in range(1, 6)}
    assert set(r.json()["ids"]) == ids and set(_soll(pfad)) == ids


def test_ein_mal_zehn_und_zwanzig_mal_zwei(admin):
    klient, kekse, pfad = admin
    assert _setze(klient, kekse, id="a", laengs=1, quer=10, abstand_m=5).json()["anzahl"] == 10
    assert _setze(klient, kekse, id="b", laengs=20, quer=2, abstand_m=5).json()["anzahl"] == 40
    assert len(_soll(pfad)) == 50


def test_ein_objekt_bleibt_ein_objekt_mit_der_alten_id(admin):
    klient, kekse, pfad = admin
    r = _setze(klient, kekse, id="einzeln")
    assert r.json()["ids"] == ["einzeln"] and set(_soll(pfad)) == {"einzeln"}


def test_die_positionen_im_soll_sind_die_der_matrix(admin):
    klient, kekse, pfad = admin
    _setze(klient, kekse, id="m", laengs=1, quer=3, abstand_m=30, raster_kurs=0)
    s = _soll(pfad)
    assert (s["m-1-1"]["lat"], s["m-1-1"]["lon"]) == (53.78, 7.91), "die erste Ecke ist der Startpunkt"
    assert haversine(s["m-1-1"]["lat"], s["m-1-1"]["lon"], s["m-1-3"]["lat"], s["m-1-3"]["lon"]) * 1000 \
        == pytest.approx(60.0, abs=0.5)


def test_der_rasterkurs_ist_vorgabe_der_kurs_sonst_nord(admin):
    klient, kekse, pfad = admin
    _setze(klient, kekse, id="k", laengs=2, quer=1, abstand_m=50, kurs=90, kurs_zufall=False)
    s = _soll(pfad)
    assert s["k-2-1"]["lon"] > s["k-1-1"]["lon"], "kurs 90 = Osten"
    _setze(klient, kekse, id="n", laengs=2, quer=1, abstand_m=50)
    s = _soll(pfad)
    assert s["n-2-1"]["lat"] > s["n-1-1"]["lat"], "ohne alles: Norden"


def test_jedes_objekt_wuerfelt_seine_eigene_richtung(admin):
    klient, kekse, pfad = admin
    _setze(klient, kekse, id="z", laengs=1, quer=12, abstand_m=5, kurs_zufall=True)
    kurse = {round(o["kurs"], 1) for o in _soll(pfad).values()}
    assert len(kurse) > 1


# ---- Grenzen ----------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [
    dict(laengs=0, quer=3, abstand_m=5),          # nichts
    dict(laengs=3, quer=3),                        # Abstand fehlt
    dict(laengs=3, quer=3, abstand_m=0),           # Abstand null
    dict(laengs=201, quer=1, abstand_m=5),         # zu viele
    dict(laengs=15, quer=14, abstand_m=5),         # 210
    dict(laengs="x", quer=3, abstand_m=5),         # keine Zahl
])
def test_unsinniges_wird_abgelehnt_und_stellt_nichts(admin, extra):
    klient, kekse, pfad = admin
    assert _setze(klient, kekse, id="x", **extra).status_code == 400
    assert _soll(pfad) == {}


def test_der_soll_fasst_hoechstens_200(admin):
    klient, kekse, pfad = admin
    assert _setze(klient, kekse, id="voll", laengs=10, quer=19, abstand_m=5).status_code == 200      # 190
    assert _setze(klient, kekse, id="mehr", laengs=1, quer=11, abstand_m=5).status_code == 400       # 201
    assert len(_soll(pfad)) == 190
    assert _setze(klient, kekse, id="rest", laengs=1, quer=10, abstand_m=5).status_code == 200       # 200


def test_dieselbe_matrix_nochmal_zaehlt_nicht_doppelt(admin):
    klient, kekse, pfad = admin
    assert _setze(klient, kekse, id="d", laengs=10, quer=19, abstand_m=5).status_code == 200
    assert _setze(klient, kekse, id="d", laengs=10, quer=19, abstand_m=6).status_code == 200
    assert len(_soll(pfad)) == 190


# ---- Zurücknehmen -----------------------------------------------------------------------

def test_die_ganze_matrix_auf_einmal_zuruecknehmen(admin):
    klient, kekse, pfad = admin
    _setze(klient, kekse, id="m", laengs=2, quer=3, abstand_m=5)
    _setze(klient, kekse, id="mm", laengs=1, quer=2, abstand_m=5)      # fremde Matrix, gleicher Anfang
    _setze(klient, kekse, id="m-x")                                     # Einzelobjekt, ähnlicher Name
    r = klient.delete("/api/admin/bruegge/soll/m?gruppe=true", cookies=kekse)
    assert r.status_code == 200 and r.json()["geloescht"] == 6
    assert set(_soll(pfad)) == {"mm-1-1", "mm-1-2", "m-x"}


def test_ohne_gruppe_geht_nur_das_eine(admin):
    klient, kekse, pfad = admin
    _setze(klient, kekse, id="m", laengs=1, quer=3, abstand_m=5)
    klient.delete("/api/admin/bruegge/soll/m-1-2", cookies=kekse)
    assert set(_soll(pfad)) == {"m-1-1", "m-1-3"}


# ---- der Admin --------------------------------------------------------------------------

def test_der_admin_hat_die_matrix_felder_und_schickt_sie():
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "admin.html").read_text(encoding="utf-8")
    for feld in ('id="bg-laengs"', 'id="bg-quer"', 'id="bg-abstand"', 'id="bg-raster"'):
        assert feld in html
    assert "laengs: laengs, quer: quer" in html and "abstand_m:" in html and "raster_kurs:" in html
    assert "?gruppe=true" in html and "Matrix weg" in html
