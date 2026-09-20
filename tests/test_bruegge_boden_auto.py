# -*- coding: utf-8 -*-
"""Feste Höhe statt OnGround — für alle Objekte, wo es geht (20.09.2026).

Der Nutzer sah einen Hubschrauber hüpfen, einen zweiten auf den Kopf kippen, eine Pitts hüpfen; Reiner
meldete es von einer C172. Gemessen (10 Bilder hintereinander): Der Schwerpunkt des Hubschraubers wanderte
um 225 Pixel, eine C172 dagegen um 1. Ursache: Mit `OnGround=1` bleibt ein Flugzeugmodell frei beweglich.
Mit `auf_boden=false` UND einer Höhe FRIERT die Brügge das Objekt ein (`objekt_festhalten`) — der Nutzer
setzte den Heli von Hand auf 4 ft: *„Hier bewegt sich dann gar nichts."* Seine Anweisung: *„mach das doch
einfach für alle Objekte."*
"""
import pytest

from app import database as db
from tests.test_bruegge_endpunkt import klient  # noqa: F401  (Fixture)


@pytest.fixture()
def admin(klient):
    from tests.test_bruegge_endpunkt import _admin_kekse
    import app.main as main
    return klient, _admin_kekse(), main.get_settings().DB_PATH


def _pilot(pfad, cid=1, sim="msfs2024", lat=53.78, lon=7.91, msl=10.5, agl=4.0):
    c = db.get_connection(pfad)
    try:
        db.bruegge_position_schreiben(c, cid, {"lat": lat, "lon": lon, "alt_msl_ft": msl,
                                               "alt_agl_ft": agl, "kurs": 90.0}, sim, "k1")
        c.commit()
    finally:
        c.close()


def _soll(pfad, oid):
    c = db.get_connection(pfad)
    try:
        r = c.execute("SELECT auf_boden, erwartete_hoehe_ft FROM bruegge_soll WHERE id = ?", (oid,)).fetchone()
        return (r[0], r[1]) if r else None
    finally:
        c.close()


def _setze(klient, kekse, **kw):
    return klient.post("/api/admin/bruegge/soll", cookies=kekse,
                       json={"art": "windrad", "lat": 53.781, "lon": 7.911, **kw})


def test_ohne_angabe_steht_das_objekt_auf_fester_hoehe_am_gelaende_des_piloten(admin):
    klient, kekse, pfad = admin
    _pilot(pfad)                                             # Gelände: 10,5 - 4,0 = 6,5 ft
    r = _setze(klient, kekse, id="a1", cid=1)
    assert r.status_code == 200 and r.json()["boden"] == "feste-hoehe-automatisch"
    assert _soll(pfad, "a1") == (0, 6.5), "OnGround AUS und die Höhe des Geländes am Piloten"


def test_der_versatz_der_art_wird_aufgeschlagen(admin):
    """Flugzeugmodelle haben ihren Bezugspunkt 3 bis 12 ft über dem Boden (gemessen an der Höhe,
    die der Simulator beim Aufsetzen meldete)."""
    klient, kekse, pfad = admin
    _pilot(pfad)
    assert klient.post("/api/admin/bruegge/arten", cookies=kekse,
                       json={"art": "windrad", "boden_versatz_ft": 3.9}).status_code == 200
    _setze(klient, kekse, id="a2", cid=1)
    assert _soll(pfad, "a2") == (0, 10.4)                    # 6,5 + 3,9


def test_ausdrueckliches_aufsetzen_gewinnt(admin):
    klient, kekse, pfad = admin
    _pilot(pfad)
    r = _setze(klient, kekse, id="a3", cid=1, auf_boden=True)
    assert r.json()["boden"] == "aufsetzen" and _soll(pfad, "a3")[0] == 1


def test_eine_ausdrueckliche_hoehe_gewinnt_und_wird_nicht_verrechnet(admin):
    klient, kekse, pfad = admin
    _pilot(pfad)
    _soll_antwort = _setze(klient, kekse, id="a4", cid=1, auf_boden=False, erwartete_hoehe_ft=4.0)
    assert _soll_antwort.json()["boden"] == "feste-hoehe"
    assert _soll(pfad, "a4") == (0, 4.0), "der Nutzer setzte den Heli von Hand auf 4 ft -- genau das gilt"


def test_ohne_pilot_bleibt_es_beim_aufsetzen(admin):
    """Das Gelände kennt der Server nur am Piloten. Kein Fehler, aber die Antwort sagt es."""
    klient, kekse, pfad = admin
    r = _setze(klient, kekse, id="a5")                       # cid leer = für alle
    assert r.status_code == 200 and r.json()["boden"] == "aufsetzen" and _soll(pfad, "a5")[0] == 1


def test_weit_vom_piloten_weg_bleibt_es_beim_aufsetzen(admin):
    """Ab 3 km gilt das Gelände am Piloten nicht mehr; OnGround trifft bis 10 km (13.09.2026 gemessen)."""
    klient, kekse, pfad = admin
    _pilot(pfad)
    r = klient.post("/api/admin/bruegge/soll", cookies=kekse,
                    json={"art": "windrad", "lat": 53.78 + 0.05, "lon": 7.91, "id": "a6", "cid": 1})  # ~5,5 km
    assert r.json()["boden"] == "aufsetzen" and _soll(pfad, "a6")[0] == 1
    nah = klient.post("/api/admin/bruegge/soll", cookies=kekse,
                      json={"art": "windrad", "lat": 53.78 + 0.02, "lon": 7.91, "id": "a7", "cid": 1})  # ~2,2 km
    assert nah.json()["boden"] == "feste-hoehe-automatisch"


def test_in_x_plane_bleibt_es_beim_aufsetzen(admin):
    """Dort sondiert die Brügge das Gelände selbst; ein MSFS-Versatz würde die statischen `.obj` anheben."""
    klient, kekse, pfad = admin
    _pilot(pfad, sim="xplane12")
    r = _setze(klient, kekse, id="a8", cid=1)
    assert r.json()["boden"] == "aufsetzen" and _soll(pfad, "a8")[0] == 1


def test_das_abgewaehlte_haekchen_ohne_hoehe_heisst_automatisch(admin):
    """Der Admin schickt `auf_boden: false` und `erwartete_hoehe_ft: null`, wenn nichts eingetragen ist."""
    klient, kekse, pfad = admin
    _pilot(pfad)
    r = _setze(klient, kekse, id="a9", cid=1, auf_boden=False, erwartete_hoehe_ft=None)
    assert r.json()["boden"] == "feste-hoehe-automatisch"


def test_ein_ausdrueckliches_false_ohne_moeglichkeit_bleibt_false(admin):
    """Ohne Pilot gibt es keine Zahl -- aber wer `auf_boden: false` verlangt, bekommt es (Vertrag, s.
    test_bruegge_endpunkt). Nur eine FEHLENDE Angabe fällt auf das sichere Aufsetzen zurück."""
    klient, kekse, pfad = admin
    r = _setze(klient, kekse, id="b1", auf_boden=False)
    assert r.json()["boden"] == "ohne-hoehe" and _soll(pfad, "b1") == (0, None)


def test_der_versatz_wird_geprueft(admin):
    klient, kekse, _ = admin
    for schlecht in ("abc", 500, -200):
        assert klient.post("/api/admin/bruegge/arten", cookies=kekse,
                           json={"art": "windrad", "boden_versatz_ft": schlecht}).status_code == 400


def test_die_arten_liste_traegt_den_versatz(admin):
    klient, kekse, _ = admin
    klient.post("/api/admin/bruegge/arten", cookies=kekse, json={"art": "windrad", "boden_versatz_ft": 12.1})
    arten = {a["art"]: a for a in klient.get("/api/admin/bruegge/arten", cookies=kekse).json()["arten"]}
    assert arten["windrad"]["boden_versatz_ft"] == 12.1


def test_der_admin_setzt_standardmaessig_kein_aufsetzen_mehr():
    """Der Haken „auf den Boden setzen" ist aus, das Höhenfeld leer = automatisch."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "admin.html").read_text(encoding="utf-8")
    assert '<input type="checkbox" id="bg-auf-boden"> auf den Boden setzen' in html
    assert 'id="bg-hoehe" type="number" step="1" placeholder="leer = automatisch"' in html
    assert 'class="bg-a-versatz"' in html and "boden_versatz_ft: parseFloat" in html
    # Der Admin schickt `auf_boden` nur, wenn der Nutzer etwas entschieden hat -- sonst entscheidet der Server.
    assert "isFinite(parseFloat(document.getElementById('bg-hoehe').value)) ? false : undefined" in html
