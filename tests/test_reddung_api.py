# -*- coding: utf-8 -*-
"""Die Admin-Endpunkte der FriesenReddung (20.09.2026).

Der wichtigste Test ist der letzte: Die Koordinate des Havaristen steht im Admin (dort sitzt,
wer das Event macht) -- aber der `stand`, der spaeter in eine Pilotenansicht wandert, enthaelt
sie nicht. Das ist die Kernanforderung aus #21.

Aufbau wie tests/test_admin_api.py: FakeReq statt TestClient, Funktionen direkt gerufen.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.auth import ADMIN_COOKIE, CONFIRM_COOKIE, make_admin_token, make_confirm_token
from app.database import (
    get_connection, get_reddung_event, init_db, set_reddung_aufgenommen,
)

SECRET = "s3cr3t"
PW = "test-admin-pw"
TOKEN = make_admin_token(SECRET, PW)
CONFIRM_TOKEN = make_confirm_token(SECRET, PW, 9_999_999_999)

SEKTOR = {"sued": 53.54, "west": 6.95, "nord": 53.90, "ost": 7.55}


class FakeReq:
    def __init__(self, cookies=None, body=None):
        self.cookies = cookies if cookies is not None else {
            ADMIN_COOKIE: TOKEN, CONFIRM_COOKIE: CONFIRM_TOKEN,
        }
        self._body = body or {}
        self.headers = {}

    async def json(self):
        return self._body


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    monkeypatch.setattr(
        main, "get_settings",
        lambda: SimpleNamespace(
            DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD=PW,
            VAPID_PRIVATE_KEY="vapid", VAPID_CONTACT_EMAIL="mailto:test",
            STATSIM_API_KEY=None,
        ),
    )
    return p


def _anlegen(**extra):
    body = {"name": "Reddung Probe", "dtstart": "2026-09-25T17:00:00Z", **SEKTOR, **extra}
    return asyncio.run(main.admin_create_reddung_event(FakeReq(body=body)))["id"]


def _liste():
    return asyncio.run(main.admin_reddung_events(FakeReq()))["events"]


def test_ohne_anmeldung_geht_nichts(db):
    for ruf in (
        lambda: main.admin_reddung_events(FakeReq(cookies={})),
        lambda: main.admin_create_reddung_event(FakeReq(cookies={}, body={})),
        lambda: main.admin_update_reddung_event(FakeReq(cookies={}, body={}), 1),
        lambda: main.admin_delete_reddung_event(FakeReq(cookies={}), 1),
        lambda: main.admin_reddung_push(FakeReq(cookies={}, body={}), 1),
        lambda: main.admin_reddung_aufnahme_freigeben(FakeReq(cookies={}), 1),
    ):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ruf())
        assert e.value.status_code == 401


def test_anlegen_lesen_aendern_loeschen(db):
    eid = _anlegen()
    liste = _liste()
    assert len(liste) == 1 and liste[0]["name"] == "Reddung Probe"
    assert liste[0]["stand"]["zellen"] > 0
    assert liste[0]["source"] == "manual"
    asyncio.run(main.admin_update_reddung_event(FakeReq(body={
        "havarist_lat": 53.72, "havarist_lon": 7.25, "havarist_art": "flugzeug_echo"}), eid))
    assert _liste()[0]["havarist_lat"] == 53.72
    asyncio.run(main.admin_delete_reddung_event(FakeReq(), eid))
    assert _liste() == []


def test_die_vorgaben_kommen_mit(db):
    _anlegen()
    ev = _liste()[0]
    assert ev["kante_km"] == 1.0 and ev["korridor_km"] == 1.0, "Suchen ist weit"
    assert ev["hoehe_max_ft"] == 2000, "Suchen darf hoch sein"
    assert ev["fund_radius_ft"] == 500 and ev["fund_hoehe_ft"] == 1000, "Finden ist eng und tief"
    assert ev["aufnehmen_noetig"] == 1 and ev["landung_noetig"] == 1
    assert ev["stand"]["korridor_km"] == 1.0 and ev["stand"]["fund_radius_ft"] == 500


def test_ein_verdrehter_sektor_wird_abgewiesen(db):
    """Sued ueber Nord ergibt ein Rechteck mit negativer Hoehe -- das Raster waere leer."""
    with pytest.raises(HTTPException) as e:
        _anlegen(sued=53.9, nord=53.54)
    assert e.value.status_code == 400


def test_ein_riesiger_sektor_wird_abgewiesen(db):
    """Sonst legt ein Verrutschen auf der Karte ein Raster mit Millionen Zellen an und der
    Poller-Takt bleibt stehen."""
    with pytest.raises(HTTPException) as e:
        _anlegen(sued=48.0, west=5.0, nord=55.0, ost=15.0)
    assert e.value.status_code == 400


def test_ein_verdrehtes_zeitfenster_wird_abgewiesen(db):
    with pytest.raises(HTTPException) as e:
        _anlegen(dtend="2026-09-24T17:00:00Z")
    assert e.value.status_code == 400


def test_ein_unbekanntes_feld_wird_abgewiesen(db):
    """update_reddung_event wirft ValueError -- der Endpunkt muss daraus 400 machen, nicht 500."""
    eid = _anlegen()
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_update_reddung_event(FakeReq(body={"havarost_lat": 1.0}), eid))
    assert e.value.status_code == 400


def test_ein_unbekanntes_event_gibt_404(db):
    for ruf in (
        lambda: main.admin_update_reddung_event(FakeReq(body={"name": "x"}), 999),
        lambda: main.admin_delete_reddung_event(FakeReq(), 999),
        lambda: main.admin_reddung_aufnahme_freigeben(FakeReq(), 999),
    ):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ruf())
        assert e.value.status_code == 404


def test_push_umschalten(db):
    eid = _anlegen()
    r = asyncio.run(main.admin_reddung_push(FakeReq(body={"enabled": False}), eid))
    assert r["push_enabled"] is False
    assert _liste()[0]["push_enabled"] == 0


def test_aufnahme_freigeben(db):
    """Der Knopf, den es unabhaengig von der Automatik geben muss -- die liegt im Einzelfall
    falsch, und dann haengt ein ganzer Abend."""
    eid = _anlegen(havarist_lat=53.72, havarist_lon=7.25)
    c = get_connection(db)
    set_reddung_aufgenommen(c, eid, "2026-09-25T17:50:00Z", 222)
    c.commit(); c.close()
    asyncio.run(main.admin_reddung_aufnahme_freigeben(FakeReq(), eid))
    assert _liste()[0]["aufgenommen_am"] is None


def test_loeschen_nimmt_die_objekte_mit(db):
    """Sonst stuende das Wrack bis zum gilt_bis weiter im Simulator -- zu einem Event, das es
    nicht mehr gibt."""
    eid = _anlegen(havarist_lat=53.72, havarist_lon=7.25)
    asyncio.run(main.admin_reddung_events(FakeReq()))
    c = get_connection(db)
    from app.database import get_reddung_event as _g, reddung_objekte_abgleichen
    reddung_objekte_abgleichen(c, _g(c, eid))
    c.commit()
    assert c.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] > 0
    c.close()
    asyncio.run(main.admin_delete_reddung_event(FakeReq(), eid))
    c = get_connection(db)
    try:
        assert c.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] == 0
    finally:
        c.close()


def test_der_stand_traegt_die_koordinate_nicht(db):
    """⚠ Im Admin-Event steht sie -- dort sitzt der Veranstalter. Im `stand` nicht: Der ist die
    Vorlage fuer die spaetere Pilotenansicht."""
    eid = _anlegen()
    asyncio.run(main.admin_update_reddung_event(
        FakeReq(body={"havarist_lat": 53.72, "havarist_lon": 7.25}), eid))
    ev = _liste()[0]
    assert ev["havarist_lat"] == 53.72
    text = json.dumps(ev["stand"])
    assert "53.72" not in text and "7.25" not in text


# --- Admin-Oberflaeche (Quelltext-Wachen) ---------------------------------
#
# Am Quelltext verankert, nicht an Zeichenzahlen oder Reihenfolgen: geprueft werden Bezeichner
# und die Texte, die ein Veranstalter lesen MUSS, damit er kein unloesbares Event anlegt.

import pathlib

ADMIN = pathlib.Path("app/static/admin.html")


def test_der_chip_fuer_die_reddung_steht_in_der_typ_leiste():
    q = ADMIN.read_text(encoding="utf-8")
    assert 'data-typ="reddung"' in q
    assert 'id="typ-reddung"' in q


def test_der_typ_hat_einen_lader():
    """Ein Chip ohne Inhalt dahinter ist eine Einladung ins Leere (Kommentar im Admin)."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "reddung: function" in q and "loadReddung" in q


def test_der_alte_arbeitstitel_steht_nicht_mehr_im_admin():
    assert "Suchflug" not in ADMIN.read_text(encoding="utf-8")


def test_neben_dem_landehaken_steht_was_er_bedeutet():
    """Sonst legt jemand ein Event an, das nur Hubschrauberpiloten abschliessen koennen,
    ohne es zu wissen (Spec, Abschnitt 4)."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "Hubschrauber" in q and "Wasserflugzeug" in q
    assert "Vollstopp" in q


def test_suchen_und_finden_sind_zwei_felder():
    """⚠ Hier stand zuerst das Gegenteil: Der Fundradius sei gerechnet und duerfe kein
    Eingabefeld haben. Aufgegeben am 20.09.2026 -- der Suchkorridor darf weit und hoch sein,
    der Fund muss eng und tief sein, und beides gehoert getrennt einstellbar.
    """
    q = ADMIN.read_text(encoding="utf-8")
    assert 'id="rd-korridor"' in q and 'id="rd-hoehe"' in q          # Suchen
    assert 'id="rd-fund-radius"' in q and 'id="rd-fund-hoehe"' in q  # Finden
    assert "Math.SQRT2" not in q, "der gerechnete Fundradius ist verworfen"


def test_der_admin_sagt_was_der_balken_bedeutet():
    """Ohne diesen Satz haelt ein Veranstalter '100 % abgesucht' fuer 'haetten wir ihn
    gesehen' -- und das ist bei zwei Fenstern nicht mehr wahr."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "heißt deshalb nicht" in q and "hätten wir ihn gesehen" in q


def test_die_schonfrist_steht_im_text():
    q = ADMIN.read_text(encoding="utf-8")
    assert "zehn Minuten" in q and "Abmeldung" in q


def test_die_herkunft_der_grundhoehe_steht_neben_der_zahl():
    assert "havarist_grund_quelle" in ADMIN.read_text(encoding="utf-8")


def test_die_hoehenschranke_ist_als_AGL_beschriftet():
    """MSL waere die falsche Auskunft -- gemessen wird ueber dem Havaristen."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "ft AGL" in q and "über dem Havaristen" in q


def test_die_artenliste_zeigt_nur_den_artnamen():
    """⚠ `bedeutung` ist eine interne Katalognotiz, keine Beschriftung. Als Optionstext machte
    sie jede Zeile bildschirmbreit und das Dropdown unbenutzbar (gemeldet am 20.09.2026 mit
    Bildschirmfoto). Sie gehoert in den Tooltip."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "o.textContent = a.art;" in q
    assert "o.title = a.bedeutung" in q
    assert "a.art + (a.bedeutung" not in q, "bedeutung darf nicht im Optionstext stehen"


def test_die_artenliste_ist_gruppiert():
    """95 Arten in einer flachen Liste sind keine Auswahl. Ein Wrack ist im Regelfall ein
    Flugzeug -- also stehen die oben, ausgeschlossen wird nichts."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "optgroup" in q and "_RD_GRUPPEN" in q
    assert "Flugzeuge und Hubschrauber" in q


def test_kein_hinweistext_steht_in_einer_gitterzelle():
    """⚠ Der Layout-Fehler vom 20.09.2026, mit Bildschirmfoto gemeldet.

    Ein langer `form-hint` INNERHALB einer `form-group` macht seine Gitterzelle hoch, das
    Nachbarfeld bleibt oben -- und die Eingabefelder rutschen gegeneinander aus der Zeile
    ("Breite" stand deutlich tiefer als "Länge"). Hinweise gehoeren als `grid-column:1/-1`
    UNTER die Zeile, zu der sie sprechen.
    """
    q = ADMIN.read_text(encoding="utf-8")
    start = q.index('<div id="rd-form"')
    ende = q.index('<div id="rd-liste"')
    formular = q[start:ende]
    # Jede form-group im Formular einzeln ansehen: keine darf einen Hinweis enthalten.
    stellen = []
    for i, teil in enumerate(formular.split('<div class="form-group">')[1:]):
        zelle = teil.split('</div>')[0]
        if "form-hint" in zelle:
            stellen.append(i + 1)
    assert stellen == [], f"form-hint in Gitterzelle(n) {stellen} — Felder rutschen aus der Zeile"


def test_jeder_hinweis_im_gitter_ist_volle_breite():
    q = ADMIN.read_text(encoding="utf-8")
    start = q.index('<div id="rd-form"')
    ende = q.index('<div id="rd-liste"')
    formular = q[start:ende]
    for stueck in formular.split('class="form-hint"')[1:]:
        kopf = stueck[:120]
        if 'style="margin:2px 0' in kopf:
            continue          # die Hinweise unter den Haken stehen ausserhalb jedes Gitters
        assert "grid-column:1/-1" in kopf or 'style="margin:0 0 8px;"' in kopf, kopf


def test_der_sektor_wird_auf_einer_karte_geklickt():
    """Koordinaten eintippen ist keine Auswahl -- man sieht nicht, wo man landet."""
    q = ADMIN.read_text(encoding="utf-8")
    assert 'id="rd-karte"' in q and "_rdKarteAufbauen" in q
    assert 'name="rd-ziel"' in q


def test_der_klick_schaltet_von_selbst_weiter():
    """Ecke 1 → Ecke 2 → Havarist, ohne dass man zwischendurch umschalten muss."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "_rdZielSetzen(n === 1 ? '2' : 'h')" in q


def test_die_ecken_werden_sortiert():
    """Welche Ecke zuerst geklickt wurde, soll niemand bedenken muessen -- sonst legt ein
    verdrehtes Rechteck ein leeres Raster an, und der Server weist es mit 400 ab."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "_rdSektorAusEcken" in q and "Math.min(a.lat, b.lat)" in q
