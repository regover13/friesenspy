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


def test_loeschen_verlangt_das_passwort_erneut(db):
    """⚠ Das Loeschen raeumt Wrack und Fackel aus ALLEN Simulatoren -- ein Klick, unumkehrbar.

    `DELETE /api/admin/bummel/races/{id}` und `.../transport/events/{id}` verlangen dafuer
    `require_confirm`; die Reddung tat es bis zum 21.09.2026 nicht. Anlegen und Aendern
    bleiben bewusst ohne: Der Veranstalter baut ein Event in vielen kleinen Schritten, und
    jedes Mal das Passwort waere eine Zumutung ohne Gewinn.
    """
    eid = _anlegen()
    nur_admin = FakeReq(cookies={ADMIN_COOKIE: TOKEN})
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_delete_reddung_event(nur_admin, eid))
    assert e.value.status_code == 403 and e.value.detail == "confirm_required"
    # Anlegen und Aendern gehen weiterhin ohne zweite Abfrage.
    asyncio.run(main.admin_update_reddung_event(
        FakeReq(cookies={ADMIN_COOKIE: TOKEN}, body={"korridor_km": 2.0}), eid))
    assert _liste()[0]["korridor_km"] == 2.0


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
    assert ev["fund_radius_m"] == 150 and ev["fund_hoehe_ft"] == 1000, "Finden ist eng und tief"
    assert ev["aufnehmen_noetig"] == 1 and ev["landung_noetig"] == 1
    assert ev["stand"]["korridor_km"] == 1.0 and ev["stand"]["fund_radius_m"] == 150


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


def test_eine_zellkante_von_null_wird_abgewiesen(db):
    """⚠ `kante_km: 0` rechnete mit 0,3 (`or 0.3`) und wurde als 0 gespeichert.

    `zellen_aus_box` klemmt dann auf 0,05 km -- aus dem Standardsektor wurden 634.382 Zellen,
    und der Poller-Takt blieb stehen. Genau das, was der Zellendeckel verhindern soll.
    """
    with pytest.raises(HTTPException) as e:
        _anlegen(kante_km=0)
    assert e.value.status_code == 400


def test_die_zellenrechnung_nimmt_eine_null_kante_ernst():
    """Zweiter Riegel, direkt an der Funktion geprueft.

    Die Feldpruefung faengt `kante_km: 0` bereits ab -- deshalb wird dieser Fix ueber den
    Endpunkt nicht sichtbar. Er ist trotzdem noetig: `or 0.3` rechnete mit 0,3, waehrend 0
    gespeichert wurde. Wer die Bereichspruefung lockert, faellt sonst wieder in die Falle.
    """
    koerper = {**SEKTOR, "kante_km": 0}
    fehler = main._validate_reddung_sektor(koerper)
    assert fehler and "Zellen" in fehler, f"eine Null-Kante muss auffallen, nicht {fehler!r}"


def test_zeichenketten_in_zahlenfeldern_werden_abgewiesen(db):
    """⚠ Sie landeten ungeprueft in der Datenbank -- und danach scheiterte DIE GANZE LISTE
    mit 500, weil `compute_reddung_stand` je Event `float()` aufruft. Der Poller-Takt brach
    ebenfalls ab, jede Minute neu."""
    for feld, wert in (("havarist_lat", "abc"), ("korridor_km", "x"), ("hoehe_max_ft", "x"),
                       ("fund_radius_m", "viel"), ("aufnehmen_noetig", "ja")):
        with pytest.raises(HTTPException) as e:
            _anlegen(**{feld: wert})
        assert e.value.status_code == 400, f"{feld}={wert!r} muss 400 geben"


def test_unsinnige_zahlenbereiche_werden_abgewiesen(db):
    for feld, wert in (("havarist_lat", 1000), ("havarist_lon", -500), ("fund_radius_m", -5),
                       ("korridor_km", -1), ("kante_km", 999), ("hoehe_max_ft", 0)):
        with pytest.raises(HTTPException) as e:
            _anlegen(**{feld: wert})
        assert e.value.status_code == 400, f"{feld}={wert} muss 400 geben"


def test_gs_min_darf_nicht_ueber_gs_max_liegen(db):
    with pytest.raises(HTTPException) as e:
        _anlegen(gs_min_kt=200, gs_max_kt=100)
    assert e.value.status_code == 400


def test_ein_teil_update_wird_gegen_den_gespeicherten_stand_geprueft(db):
    """⚠ Die Luecke: Die Sektorpruefung griff nur, wenn ALLE VIER Ecken mitkamen.

    `{"nord": 53.0}` (unter `sued`) ergab einen verdrehten Sektor, `{"nord": 60}` rund 26.000
    Zellen -- beides mit 200 quittiert und gespeichert.
    """
    eid = _anlegen()
    for koerper in ({"nord": 53.0}, {"nord": 60.0}, {"kante_km": 0}):
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.admin_update_reddung_event(FakeReq(body=koerper), eid))
        assert e.value.status_code == 400, f"{koerper} muss 400 geben"
    # Der Sektor steht unveraendert.
    assert _liste()[0]["nord"] == SEKTOR["nord"]


def test_ein_halbes_zeitfenster_wird_gegen_den_gespeicherten_stand_geprueft(db):
    """`{"dtend": …}` allein lief durch `_validate_event_times(None, dtend)` -- und das ist
    stumm. Gespeichert wurde ein Ende VOR dem Start, worauf der Poller das Event sofort
    aufloeste."""
    eid = _anlegen()
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_update_reddung_event(
            FakeReq(body={"dtend": "2026-09-24T17:00:00Z"}), eid))
    assert e.value.status_code == 400


def test_eine_sektoraenderung_verwirft_den_fortgeschriebenen_stand(db):
    """⚠ Die Zellschluessel `z<i>_<j>` zeigen danach auf ANDERE Zellen.

    Ohne Verwerfen stand `zellen 4, abgedeckt 8, anteil 2.0` in der Liste -- und vier Zellen
    galten als abgesucht, ueber die nie jemand geflogen war.
    """
    from app.database import get_progress_snapshot, write_progress_snapshot
    eid = _anlegen()
    c = get_connection(db)
    try:
        write_progress_snapshot(c, "reddung", eid,
                                {"v": 1, "bis": "2026-09-25T17:30:00Z",
                                 "treffer": {"z0_0": [111, "2026-09-25T17:10:00Z"]},
                                 "je_pilot": {"111": 1}, "fund": None},
                                "2026-09-25T17:30:00Z")
        c.commit()
        assert get_progress_snapshot(c, "reddung", eid) is not None
    finally:
        c.close()
    asyncio.run(main.admin_update_reddung_event(FakeReq(body={"kante_km": 2.0}), eid))
    c = get_connection(db)
    try:
        assert get_progress_snapshot(c, "reddung", eid) is None, "der alte Stand muss weg"
    finally:
        c.close()


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


def test_die_havarist_auswahl_zeigt_nur_arten_die_jeder_pilot_sieht():
    """⚠ Vorher filterte die Liste allein auf `status === 'aktiv'` -- also nur darauf, ob der
    Nutzer die Art abgeschaltet hat. Simulator-Tauglichkeit und Fremdpaket blieben aussen vor,
    obwohl der Endpunkt beides mitliefert.

    Das wiegt seit dem 20.09.2026 schwer: Die FriesenBruegge ist bei einer Reddung
    Teilnahmevoraussetzung UND traegt die Wertung. Eine Art, die nur ein Simulator setzen
    kann, laesst einen Piloten mit Bruegge ueber einen leeren Sektor fliegen -- gewertet, aber
    ohne jede Chance. Aufgefallen an `wilga`: MSFS 2024 Payware, MSFS 2020 eine Cessna 152,
    X-Plane eine PA-28.
    """
    q = ADMIN.read_text(encoding="utf-8")
    stelle = q[q.index("async function _rdArtenLaden"):]
    stelle = stelle[:stelle.index("sel.dataset.geladen = '1'")]
    assert "a.anforderbar" in stelle, "abgeschaltete Arten und solche ohne Titel muessen raus"
    assert "a.ueberall" in stelle, "eine Art, die nicht jeder Simulator setzen kann, ist untauglich"
    assert "!a.addon" in stelle, "ein Fremdpaket hat nicht jeder"


def test_eine_gespeicherte_art_geht_beim_bearbeiten_nicht_verloren():
    """⚠ Die Liste ist gefiltert -- steht die Art eines bestehenden Events nicht darin, faellt
    `select.value` still auf leer, und das naechste Speichern schriebe die Vorgabe zurueck.
    Ein Havarist, der beim blossen Oeffnen des Formulars die Gestalt wechselt.
    """
    q = ADMIN.read_text(encoding="utf-8")
    stelle = q[q.index("function rdEdit(id)"):]
    stelle = stelle[:stelle.index("rd-aufnahme-verfaellt")]
    assert "nicht in allen Simulatoren" in stelle, "die fehlende Art muss ergaenzt werden"
    assert "insertBefore" in stelle


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


# --- Oeffentliche Eventliste und das sichtbare Objekt ---------------------

def test_der_oeffentliche_endpunkt_traegt_keine_koordinate(db):
    """⚠ Der Riegel fuer die Liste, die jeder Pilot sieht. Was hier durchkommt, steht in
    jedem Browser."""
    eid = _anlegen()
    asyncio.run(main.admin_update_reddung_event(
        FakeReq(body={"havarist_lat": 53.72, "havarist_lon": 7.25}), eid))
    daten = main.reddung_events()
    assert len(daten) == 1 and daten[0]["name"] == "Reddung Probe"
    text = json.dumps(daten)
    for zahl in ("53.72", "7.25", "havarist_lat", "havarist_lon"):
        assert zahl not in text, f"{zahl} steht in der oeffentlichen Liste"
    assert "stand" in daten[0] and "anteil" in daten[0]["stand"]


def test_die_eventliste_holt_die_reddungen():
    """Ohne diese Zeile taucht ein Event nirgends auf -- gemeldet am 20.09.2026:
    'ich finde das event nicht in der Event ansicht??'"""
    q = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
    assert "/api/reddung/events" in q
    assert "is_reddung" in q and "REDDUNG</span>" in q


def test_ein_stehendes_simobjekt_ohne_partner_wird_nicht_gezeichnet():
    """⚠ Der Havarist stand am 20.09.2026 als Verkehrspunkt auf dem Kniebrett -- und damit die
    Lage, die der ganze Eventtyp verbirgt. Die Bruegge stellt ein Flugzeug-SimObject hin,
    `GET_AIR_TRAFFIC` liefert es wie jedes andere.

    Verankert am Code, nicht an einem Kommentar: Der Filter muss im Zweig fuer Sim-Objekte
    OHNE VATSIM-Partner stehen -- also zwischen `} else {` und `e._key = 'sim:'`.
    """
    q = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
    assert "_SIM_STEHT_KT" in q
    i = q.index("e._key = 'sim:' + s.id;")
    davor = q[q.rindex("} else {", 0, i):i]
    assert "_SIM_STEHT_KT" in davor and "continue" in davor, \
        "der Filter steht nicht im Zweig fuer ungepaarte Sim-Objekte"


def test_die_reddung_hat_bearbeiten_und_link():
    """Gemeldet am 20.09.2026: 'kein bearbeiten Button?' und 'der button Link fehlt auch'."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "rdEdit(" in q and "rdCopyLink(" in q
    assert "_rdEditingId" in q, "ohne Merker legt Speichern ein neues Event an statt zu aendern"
    assert "'/api/admin/reddung/events/' + _rdEditingId" in q


def test_der_fundradius_steht_in_metern():
    """Nutzer, 20.09.2026: 'mach seitliche Abstaende in metern, nicht in fuss'."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "Fundradius (m, seitlich)" in q
    assert "fund_radius_m:" in q
    assert "fund_radius_ft" not in q


# --- Was nach dem Abschluss nicht mehr gehen darf ------------------------

def test_freigeben_geht_nach_der_einlieferung_nicht_mehr(db):
    """⚠ Am 20.09.2026 genau so passiert: Der Knopf stand bei einem abgeschlossenen Fall da,
    ein Klick leerte den Latch -- uebrig blieb eine Einlieferung OHNE Aufnahme, eine
    Reihenfolge, die es nicht geben kann."""
    from app.database import (get_connection as _g, set_reddung_aufgenommen as _auf,
                              set_reddung_eingeliefert as _ein)
    from app.config import get_settings as _s
    eid = _anlegen(havarist_lat=53.72, havarist_lon=7.25)
    c = _g(main.get_settings().DB_PATH)
    _auf(c, eid, "2026-09-25T17:50:00Z", 222)
    _ein(c, eid, "2026-09-25T18:10:00Z", 222, "EDWF")
    c.commit(); c.close()
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_reddung_aufnahme_freigeben(FakeReq(), eid))
    assert e.value.status_code == 400
    assert _liste()[0]["aufgenommen_am"] == "2026-09-25T17:50:00Z", "der Latch bleibt stehen"


def test_freigeben_geht_ohne_aufnahme_nicht(db):
    eid = _anlegen()
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.admin_reddung_aufnahme_freigeben(FakeReq(), eid))
    assert e.value.status_code == 400


def test_der_knopf_steht_nur_da_wenn_er_etwas_tun_kann():
    """Die erste Schranke sitzt in der Oberflaeche -- der Endpunkt ist die zweite."""
    q = ADMIN.read_text(encoding="utf-8")
    assert "ev.aufgenommen_am && !ev.eingeliefert_am && !ev.aufgeloest_am" in q


# --- "FriesenBruegge fehlt" in der Live-Ansicht ---------------------------

def test_der_hinweis_verlangt_eine_anmeldung(db):
    with pytest.raises(HTTPException) as e:
        asyncio.run(main.meine_reddung(FakeReq(cookies={})))
    assert e.value.status_code == 401


@pytest.fixture
def als_pilot(monkeypatch):
    """Als eingeloggter Pilot mit CID 4711.

    `_current_cid` verlangt einen aktiven Forum-Login und ein signiertes `fs_user`-Cookie --
    das gehoert zu den Auth-Tests, nicht hierher. Geprueft wird die Logik des Endpunkts.
    """
    monkeypatch.setattr(main, "_current_cid", lambda request, settings: 4711)
    return 4711


def test_ohne_laufende_reddung_kein_hinweis(db, als_pilot):
    _anlegen()                       # dtstart 2026-09-25, also nicht jetzt
    d = asyncio.run(main.meine_reddung(FakeReq()))
    assert d == {"laeuft": False}


def _laufendes_event(db):
    from datetime import datetime, timedelta, timezone
    jetzt = datetime.now(timezone.utc)
    def iso(x): return x.strftime("%Y-%m-%dT%H:%M:%SZ")
    eid = _anlegen(dtstart=iso(jetzt - timedelta(hours=1)),
                   dtend=iso(jetzt + timedelta(hours=1)))
    return eid, jetzt, iso


def _bruegge_meldet(vor_min=0):
    from datetime import datetime, timedelta, timezone
    from app.database import get_connection as _g
    jetzt = datetime.now(timezone.utc) - timedelta(minutes=vor_min)
    c = _g(main.get_settings().DB_PATH)
    try:
        c.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gemeldet_am, "
                  "simulator) VALUES (4711, 53.7, 7.2, ?, 'msfs2024')",
                  (jetzt.strftime("%Y-%m-%dT%H:%M:%SZ"),))
        c.commit()
    finally:
        c.close()


def test_laufende_reddung_ohne_bruegge_gibt_den_hinweis(db, als_pilot):
    """⭐ Der Hinweis muss VOR dem Flug kommen: Mit Bruegge wird sekundengenau gewertet, ohne
    sie nur alle 15 Sekunden -- und ein Fund verlangt 150 Meter."""
    _laufendes_event(db)
    d = asyncio.run(main.meine_reddung(FakeReq()))
    assert d["laeuft"] is True and d["bruegge"] is False
    assert d["name"] == "Reddung Probe"


def test_mit_meldender_bruegge_kein_hinweis(db, als_pilot):
    _laufendes_event(db)
    _bruegge_meldet()
    d = asyncio.run(main.meine_reddung(FakeReq()))
    assert d["laeuft"] is True and d["bruegge"] is True


def test_eine_alte_meldung_zaehlt_nicht_als_bruegge(db, als_pilot):
    """Ein geschlossener Simulator soll sofort auffallen -- die Bruegge meldet im Sekundentakt."""
    _laufendes_event(db)
    _bruegge_meldet(vor_min=10)
    assert asyncio.run(main.meine_reddung(FakeReq()))["bruegge"] is False


def test_der_hinweis_steht_in_der_oberflaeche():
    q = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
    assert 'id="reddung-hinweis"' in q and "_reddungHinweisPruefen" in q
    assert "/api/me/reddung" in q
    assert "setInterval(_reddungHinweisPruefen" in q, "ein Event kann spaeter beginnen"
    assert 'href="/download"' in q, "ohne Weg zum Paket ist der Hinweis ein Vorwurf"


def test_im_kniebrett_steht_die_adresse_statt_eines_links():
    """Hinter Coherent GT steht kein Browser -- ein <a> laesst sich dort nicht oeffnen.

    Der Fassungshinweis daneben macht es seit v14.51.0 genauso: auf der Website ein Link,
    im Panel die nackte Adresse. Ein toter Link im Tablet ist schlimmer als kein Link --
    der Pilot klickt und nichts passiert.
    """
    q = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
    stelle = q[q.index("function _reddungHinweisPruefen"):]
    stelle = stelle[:stelle.index("\n}")]
    assert "_PANEL_MODUS" in stelle, "der Hinweis unterscheidet Website und Kniebrett nicht"
    assert "friesenspy.devprops.de/download" in stelle, "im Panel fehlt die Adresse als Text"


def test_der_hinweis_sagt_dass_ohne_bruegge_nichts_gewertet_wird():
    """⚠ Genau hier stand am 20.09.2026 das Gegenteil -- "gewertet wirst du trotzdem, nur
    groeber". Das war sachlich falsch: Wrack und Rauchsaeulen kommen ueber die FriesenBruegge
    in den Simulator, ohne sie ist der Sektor leer. Seither zaehlt der Server die Spur eines
    Piloten ohne Bruegge auch nicht mehr mit (`_reddung_punkte_mischen`, `gemeldet_seit`).

    Der Text ist die einzige Stelle, an der der Pilot das rechtzeitig erfaehrt -- wer ihn
    wieder aufweicht, verspricht eine Teilnahme, die es nicht gibt.
    """
    q = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
    stelle = q[q.index("function _reddungHinweisPruefen"):]
    stelle = stelle[:stelle.index("\n}")]
    assert "mitgewertet wirst " in stelle and "du auch nicht" in stelle, \
        "der Hinweis muss sagen, dass ohne FriesenBruegge nicht gewertet wird"
    assert "nur gröber" not in stelle, "die widerlegte Fassung ist zurueck"


def test_eine_aufgeloeste_reddung_gibt_keinen_hinweis_mehr(db, als_pilot):
    """Der Fall ist abgeschlossen -- ein Hinweis waere dann nur noch ein Vorwurf."""
    from app.database import get_connection as _g
    eid, jetzt, iso = _laufendes_event(db)
    c = _g(main.get_settings().DB_PATH)
    try:
        c.execute("UPDATE reddung_events SET aufgeloest_am = ? WHERE id = ?", (iso(jetzt), eid))
        c.commit()
    finally:
        c.close()
    assert asyncio.run(main.meine_reddung(FakeReq())) == {"laeuft": False}


# --- Raster-Endpunkt (Spec 2026-09-23, Abschnitt 3) ------------------------------------

def test_raster_endpunkt_liefert_geometrie_und_zellen(db):
    eid = _anlegen()
    d = main.reddung_raster_endpunkt(eid)
    assert d["id"] == eid and d["name"] == "Reddung Probe"
    assert set(d) == {"id", "name", "dtstart", "dtend", "sektor", "raster", "zellen",
                      "abgedeckt", "anteil", "aufgeloest"}
    assert d["zellen"] == d["raster"]["zeilen"] * d["raster"]["spalten"]
    assert d["abgedeckt"] == []


def test_raster_endpunkt_kennt_unbekannte_ids_nicht(db):
    """Eine leere 200 waere fuer die Karte nicht von „noch unberuehrt" zu unterscheiden."""
    with pytest.raises(HTTPException) as e:
        main.reddung_raster_endpunkt(9999)
    assert e.value.status_code == 404


def test_raster_endpunkt_traegt_keine_koordinate_auch_nach_dem_fund(db):
    """⚠ Der Riegel an der Stelle, die jeder Browser erreicht."""
    eid = _anlegen()
    asyncio.run(main.admin_update_reddung_event(
        FakeReq(body={"havarist_lat": 53.72, "havarist_lon": 7.25}), eid))
    c = get_connection(db)
    try:
        c.execute("UPDATE reddung_events SET gefunden_am='2026-09-25T18:00:00Z', "
                  "gefunden_von=111, aufgeloest_am='2026-09-25T18:00:00Z' WHERE id=?", (eid,))
        c.commit()
    finally:
        c.close()
    text = json.dumps(main.reddung_raster_endpunkt(eid))
    for zahl in ("53.72", "7.25", "havarist"):
        assert zahl not in text, f"{zahl} steht in der Raster-Antwort"


def test_raster_endpunkt_liegt_hinter_dem_login_gate():
    """Er steht NICHT in den gate-freien Praefixen -- sonst waere die Flaeche oeffentlich."""
    assert not "/api/reddung/events/1/raster".startswith(main._GATE_ALLOW_PREFIXES)


def test_die_liste_sagt_ob_eine_reddung_laeuft(db):
    """#44 Punkt 10: „läuft" hing an der Uhr des Geräts -- im Kniebrett die des Sim-PCs."""
    from datetime import datetime, timedelta, timezone
    jetzt = datetime.now(timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    c = get_connection(db)
    try:
        from app.database import create_reddung_event
        create_reddung_event(c, name="Laeuft", dtstart=iso(jetzt - timedelta(hours=1)),
                             dtend=iso(jetzt + timedelta(hours=1)), **SEKTOR)
        create_reddung_event(c, name="Vorbei", dtstart=iso(jetzt - timedelta(hours=5)),
                             dtend=iso(jetzt - timedelta(hours=2)), **SEKTOR)
        create_reddung_event(c, name="Kommt", dtstart=iso(jetzt + timedelta(hours=5)),
                             dtend=iso(jetzt + timedelta(hours=7)), **SEKTOR)
        c.commit()
    finally:
        c.close()
    je = {e["name"]: e for e in main.reddung_events()}
    assert je["Laeuft"]["laeuft"] is True and je["Laeuft"]["vorbei_seit_s"] is None
    assert je["Vorbei"]["laeuft"] is False
    assert 2 * 3600 - 60 <= je["Vorbei"]["vorbei_seit_s"] <= 2 * 3600 + 60
    assert je["Kommt"]["laeuft"] is False and je["Kommt"]["vorbei_seit_s"] is None


# --- Push im Admin: Zustand und Handlung getrennt (25.09.2026) ---------------------------

def _admin_funktion(name: str) -> str:
    import re
    q = ADMIN.read_text(encoding="utf-8")
    m = re.search(rf"(async )?function {name}\(", q)
    assert m, name
    # Bis zur naechsten Funktionsdefinition -- die Einrueckung der schliessenden Klammer ist in
    # admin.html nicht einheitlich.
    naechste = re.search(r"\n\s*(async )?function \w+\(", q[m.end():])
    return q[m.start():m.end() + (naechste.start() if naechste else len(q))]


def test_die_reddung_zeigt_den_push_zustand_wie_bummel_und_kutter():
    """Nutzer, 25.09.2026, vor der Reddung-Zeile: „ist jetzt Push an oder aus?" -- und dann:
    „warum sieht das nicht so aus wie bei den anderen Events??". Bummel und Kutter zeigen den
    Zustand als Abzeichen; die Reddung nur einen Hinweis, wenn aus -- und sonst gar nichts."""
    rumpf = _admin_funktion("loadReddung")
    assert "badge-push-on" in rumpf and "badge-push-off" in rumpf
    assert "· Push aus</span>" not in rumpf


def test_die_knoepfe_nennen_die_handlung_nicht_den_zustand():
    """„Push an" als Knopf neben „Push aus" als Zustand las sich wie ein Widerspruch -- bei
    allen drei Eventtypen gleich."""
    for name in ("renderRaceCard", "loadKutterEventsAdmin", "loadReddung"):
        rumpf = _admin_funktion(name)
        assert "Push einschalten" in rumpf and "Push ausschalten" in rumpf, name
        assert ">Push an</button>" not in rumpf and ">Push aus</button>" not in rumpf, name
        assert "'Push aus' : 'Push an'" not in rumpf, name
