# -*- coding: utf-8 -*-
"""Ein zugeordneter Titel hat IMMER einen Status (16.09.2026).

**Der Fund, vom Nutzer im Betrieb bemerkt:** *„wenn ich einer neuen Art ein Objekt zuordne,
muss ich den status von aktiv auf aus und wieder auf aktiv wechseln, damit aktiv gespeichert
wird."*

Drei Stellen ergaben zusammen einen Fehler, den man nicht sehen konnte:

1. Der Admin schickt beim Zuordnen **nur** ``art`` (``admin.html``, ``bg-t-setzart``).
2. ``bruegge_katalog_setzen`` liess ``status`` daraufhin unberuehrt — und bei einem nie
   zugeordneten Titel ist das ``NULL``.
3. Die Anzeige zeigt ``z.status || 'aktiv'``. **NULL sah damit aus wie „aktiv".**

Ausgeliefert wird aber nur ``status = 'aktiv'`` (``bruegge_titel_fuer``,
``bruegge_arten_beidseitig``, ``bruegge_arten_anforderbar``). Der Titel war also stumm,
die Art womoeglich gesperrt — und im Admin sah alles richtig aus.

⚠ Die Umkehrung steht schon laenger da und bleibt: ``art = None`` raeumt Rang und Status weg.
Dies hier ist ihr fehlendes Gegenstueck — **mit** Art braucht es einen Status.
"""
import sqlite3

import pytest

from app import database as db


@pytest.fixture()
def conn(tmp_path):
    pfad = str(tmp_path / "t.db")
    db.init_db(pfad)
    c = db.get_connection(pfad)
    # Ein frischer Titel, wie ihn eine Bruegge meldet: ohne Art, ohne Rang, ohne Status.
    db.katalog_eintragen(c, [{"simulator": "msfs2024", "titel": "TestFlieger Passengers",
                              "quelle": "bord", "paket": None, "kategorie": None,
                              "bemerkung": None}])
    c.commit()
    yield c
    c.close()


def _status(conn, titel="TestFlieger Passengers"):
    r = conn.execute("SELECT art, rang, status FROM bruegge_katalog "
                     "WHERE simulator = 'msfs2024' AND titel = ?", (titel,)).fetchone()
    return dict(zip(("art", "rang", "status"), r))


def test_frisch_gemeldet_hat_keinen_status(conn):
    """Die Ausgangslage — ohne sie prueft der Test darunter nichts."""
    assert _status(conn)["status"] is None


def test_zuordnen_ohne_status_macht_aktiv(conn):
    """Der eigentliche Fund: EIN Aufruf, wie der Admin ihn schickt, muss genuegen."""
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers", art="tier_gross")
    conn.commit()
    z = _status(conn)
    assert z["art"] == "tier_gross"
    assert z["status"] == "aktiv", "ein zugeordneter Titel ohne Status wird nie ausgeliefert"


def test_der_titel_geht_danach_wirklich_hinaus(conn):
    """Nicht nur die Spalte — die Wirkung. `status` zaehlt nur, weil die Auslieferung ihn liest."""
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers", art="tier_gross")
    conn.commit()
    assert "TestFlieger Passengers" in db.bruegge_titel_fuer(conn, "msfs2024")["tier_gross"]


def test_ein_abgeschalteter_titel_bleibt_abgeschaltet(conn):
    """⚠ Die Luecke wird gefuellt, nicht ueberschrieben.

    `status = 'aus'` kommt aus einem gescheiterten Setzversuch
    (`bruegge_katalog_ergebnis_melden`) und ist eine Eigenschaft des TITELS, nicht der
    Zuordnung. Wer ihn einer anderen Art gibt, macht ihn nicht heil — sonst holte man sich
    einen nachweislich kaputten Titel durch Umhaengen zurueck.
    """
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers",
                              art="tier_gross", status="aus")
    conn.commit()
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers", art="boot_klein")
    conn.commit()
    z = _status(conn)
    assert z["art"] == "boot_klein"
    assert z["status"] == "aus"


def test_ein_ausdruecklicher_status_gewinnt(conn):
    """Wer `status` mitschickt, bekommt ihn — die Fuellung greift nur bei NULL."""
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers",
                              art="tier_gross", status="aus")
    conn.commit()
    assert _status(conn)["status"] == "aus"


def test_art_wegnehmen_raeumt_weiter_auf(conn):
    """Die bestehende Umkehrung darf der Fix nicht beschaedigen."""
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers",
                              art="tier_gross", rang=3)
    conn.commit()
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers", art=None)
    conn.commit()
    assert _status(conn) == {"art": None, "rang": None, "status": None}


def test_ohne_art_entsteht_kein_status(conn):
    """Nur `rang` zu aendern darf keine Zuordnung erfinden."""
    db.bruegge_katalog_setzen(conn, "msfs2024", "TestFlieger Passengers", rang=2)
    conn.commit()
    z = _status(conn)
    assert z["art"] is None and z["status"] is None
