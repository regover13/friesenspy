# -*- coding: utf-8 -*-
"""`NOCH_NICHT_GESETZT` ist kein Urteil über einen Titel (16.09.2026).

**Im Betrieb aufgefallen:** Der Nutzer setzte eine `flagge` in X-Plane und bekam
``✖ GATTUNG_UNBEKANNT``. Der Grund lag zwei Schritte davor:

1. Die X-Plane-Brügge meldet ``zustand: "fehlgeschlagen"`` mit ``fehler:
   "NOCH_NICHT_GESETZT"``, **solange die Instanz noch nicht existiert**
   (``friesenbruegge/xplane/bruegge.cpp:538``) — also im Normalfall direkt nach dem
   Anfordern, bevor der Simulator das Objekt geladen hat.
2. Der Server nahm das als Prüfergebnis, schrieb ``status = 'aus'`` — und weil `flagge`
   X-Plane-seitig **genau einen** Titel hatte, galt die Zuordnung als eindeutig.
3. Damit war die Art nicht mehr beidseitig, der Server lieferte gar keine Titel mehr, und
   die Brügge meldete folgerichtig ``GATTUNG_UNBEKANNT``.

Die Datei ``flagpole_20m_1.obj`` liegt dabei völlig in Ordnung auf der Platte — nachgesehen.

⚠ **Arten mit mehreren Titeln waren zufällig geschützt**, weil
``bruegge_katalog_ergebnis_melden`` bei ``alle=False`` nur bei genau einem aktiven Titel
schreibt. Der Fehler traf also ausgerechnet die knappsten Arten.
"""
from types import SimpleNamespace

import pytest


@pytest.fixture()
def conn(tmp_path):
    from app import database as db
    pfad = str(tmp_path / "t.db")
    db.init_db(pfad)
    c = db.get_connection(pfad)
    # Eine Art mit GENAU EINEM X-Plane-Titel -- der empfindliche Fall.
    c.execute("UPDATE bruegge_katalog SET art = NULL, rang = NULL, status = NULL "
              "WHERE simulator = 'xplane12'")
    db.katalog_eintragen(c, [{"simulator": "xplane12", "titel": "fahne.obj",
                              "quelle": "bord", "paket": None, "kategorie": None,
                              "bemerkung": None}])
    db.bruegge_katalog_setzen(c, "xplane12", "fahne.obj", art="flagge", rang=1,
                              status="aktiv")
    c.commit()
    yield c
    c.close()


def _zeile(conn):
    r = conn.execute("SELECT status, ergebnis, fehler FROM bruegge_katalog "
                     "WHERE simulator = 'xplane12' AND titel = 'fahne.obj'").fetchone()
    return dict(zip(("status", "ergebnis", "fehler"), r))


def _melden(conn, monkeypatch, fehler: str):
    """Eine Rückmeldung durchs Ohr des Servers schicken."""
    from app import main
    monkeypatch.setattr(main, "bruegge_soll_fuer",
                        lambda c, cid: [{"id": "o1", "art": "flagge"}])
    main._bruegge_katalog_lernen(
        conn, "xplane12", 1,
        [{"id": "o1", "zustand": "fehlgeschlagen", "fehler": fehler}])
    conn.commit()


def test_noch_nicht_gesetzt_legt_nichts_still(conn, monkeypatch):
    """Der eigentliche Fund. Ohne den Fix steht hier `aus` / `fehlgeschlagen`."""
    _melden(conn, monkeypatch, "NOCH_NICHT_GESETZT")
    z = _zeile(conn)
    assert z["status"] == "aktiv", "ein noch nicht geladenes Objekt ist kein kaputter Titel"
    assert z["ergebnis"] is None


def test_die_art_bleibt_anforderbar(conn, monkeypatch):
    """Nicht die Spalte zählt, sondern die Wirkung: Sonst kommt `GATTUNG_UNBEKANNT`."""
    from app import database as db
    _melden(conn, monkeypatch, "NOCH_NICHT_GESETZT")
    assert "flagge" in db.bruegge_arten_anforderbar(conn)
    assert db.bruegge_titel_fuer(conn, "xplane12").get("flagge") == ["fahne.obj"]


def test_ein_echter_fehlschlag_wirkt_weiter(conn, monkeypatch):
    """⚠ Die Gegenprobe — sonst hätte der Fix das Lernen ganz abgeschaltet.

    `EXCEPTION_22` heißt: Der Simulator kennt diesen Container nicht. Das ist ein Urteil
    über den Titel und muss ihn weiterhin stilllegen.
    """
    _melden(conn, monkeypatch, "EXCEPTION_22")
    z = _zeile(conn)
    assert z["status"] == "aus"
    assert z["ergebnis"] == "fehlgeschlagen"


def test_erschoepfte_art_wirkt_weiter(conn, monkeypatch):
    """`KEIN_MODELL_MEHR` heißt: alle Titel durchprobiert, keiner ging."""
    _melden(conn, monkeypatch, "KEIN_MODELL_MEHR")
    assert _zeile(conn)["status"] == "aus"


def test_steht_wird_weiterhin_gelernt(conn, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "bruegge_soll_fuer",
                        lambda c, cid: [{"id": "o1", "art": "flagge"}])
    main._bruegge_katalog_lernen(
        conn, "xplane12", 1,
        [{"id": "o1", "zustand": "steht", "hoehe_ft": 12.5}])
    conn.commit()
    assert _zeile(conn)["ergebnis"] == "steht"


def test_gattung_unbekannt_legt_nichts_still(conn, monkeypatch):
    """⚠⚠ Der Teufelskreis — im Betrieb beobachtet, 16.09.2026.

    `GATTUNG_UNBEKANNT` meldet eine Brügge, wenn sie zu einer angeforderten Art **keine
    Titel bekommen hat**. Das ist eine Aussage über den SERVER, nicht über den Titel — und
    daraus einen Fehlschlag zu machen, schließt einen Kreis:

        Titel `aus` → Art nicht mehr beidseitig → Server liefert keine Titel
                   → Brügge meldet GATTUNG_UNBEKANNT → Titel bleibt `aus`

    Beobachtet an `rauch_hellblau`: Der Titel wurde von Hand reaktiviert und war beim
    nächsten Setzversuch sofort wieder abgeschaltet. Von Hand kommt man da nie heraus.
    """
    from app import database as db
    _melden(conn, monkeypatch, "GATTUNG_UNBEKANNT")
    assert _zeile(conn)["status"] == "aktiv"
    assert "flagge" in db.bruegge_arten_anforderbar(conn)
