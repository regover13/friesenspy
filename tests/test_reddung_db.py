# -*- coding: utf-8 -*-
"""Tabelle und Latches der FriesenReddung (20.09.2026)."""
from __future__ import annotations

import pytest

from app.database import (
    clear_reddung_aufnahme, create_reddung_event, delete_reddung_event, get_connection,
    get_reddung_event, init_db, list_reddung_events, reddung_grund_merken,
    set_reddung_aufgeloest, set_reddung_aufgenommen, set_reddung_eingeliefert,
    set_reddung_gefunden, update_reddung_event,
)

SEKTOR = dict(sued=53.54, west=6.95, nord=53.90, ost=7.55)


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def _ev(conn, **extra):
    return create_reddung_event(conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
                                **SEKTOR, **extra)


def test_anlegen_und_lesen(conn):
    eid = _ev(conn)
    ev = get_reddung_event(conn, eid)
    assert ev["name"] == "Reddung Probe"
    assert ev["sued"] == 53.54 and ev["ost"] == 7.55


def test_die_vorgaben_stehen_in_der_tabelle(conn):
    """Sie stehen in der DDL, damit eine von Hand angelegte Zeile brauchbar ist."""
    ev = get_reddung_event(conn, _ev(conn))
    assert ev["kante_km"] == 1.0 and ev["korridor_km"] == 1.0
    assert ev["hoehe_max_ft"] == 1000 and ev["gs_max_kt"] == 140 and ev["gs_min_kt"] == 30
    assert ev["aufnehmen_noetig"] == 1 and ev["landung_noetig"] == 1
    assert ev["aufnahme_verfaellt"] == 1
    assert ev["push_enabled"] == 1


def test_dtend_bekommt_den_mitternacht_standard(conn):
    ev = get_reddung_event(conn, _ev(conn))
    assert ev["dtend"] == "2026-09-26T00:00:00Z"


def test_aendern_und_loeschen(conn):
    eid = _ev(conn)
    update_reddung_event(conn, eid, havarist_lat=53.72, havarist_lon=7.25,
                         havarist_art="flugzeug_echo", landung_noetig=0)
    ev = get_reddung_event(conn, eid)
    assert ev["havarist_lat"] == 53.72 and ev["landung_noetig"] == 0
    delete_reddung_event(conn, eid)
    assert get_reddung_event(conn, eid) is None


def test_unbekanntes_feld_wird_abgewiesen(conn):
    """Sonst schreibt ein Tippfehler im Admin still ins Leere."""
    with pytest.raises(ValueError):
        update_reddung_event(conn, _ev(conn), havarost_lat=1.0)


def test_unbekanntes_feld_wird_auch_beim_anlegen_abgewiesen(conn):
    with pytest.raises(ValueError):
        _ev(conn, havarost_lat=1.0)


def test_latches_setzen_nur_beim_ersten_mal(conn):
    eid = _ev(conn)
    assert set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111) is True
    assert set_reddung_gefunden(conn, eid, "2026-09-25T17:45:00Z", 222) is False
    ev = get_reddung_event(conn, eid)
    assert ev["gefunden_von"] == 111 and ev["gefunden_am"] == "2026-09-25T17:30:00Z"


def test_der_aufnehmende_muss_nicht_der_finder_sein(conn):
    eid = _ev(conn)
    set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111)
    assert set_reddung_aufgenommen(conn, eid, "2026-09-25T17:50:00Z", 222) is True
    assert get_reddung_event(conn, eid)["aufgenommen_von"] == 222


def test_einliefern_merkt_den_platz(conn):
    eid = _ev(conn)
    assert set_reddung_eingeliefert(conn, eid, "2026-09-25T18:20:00Z", 222, "EDWF") is True
    ev = get_reddung_event(conn, eid)
    assert ev["eingeliefert_icao"] == "EDWF" and ev["eingeliefert_von"] == 222


def test_aufnahme_zuruecknehmen_macht_den_latch_wieder_frei(conn):
    """Bricht der Aufnehmende ab, muss ein anderer uebernehmen koennen."""
    eid = _ev(conn)
    set_reddung_aufgenommen(conn, eid, "2026-09-25T17:50:00Z", 222)
    clear_reddung_aufnahme(conn, eid)
    ev = get_reddung_event(conn, eid)
    assert ev["aufgenommen_am"] is None and ev["aufgenommen_von"] is None
    assert set_reddung_aufgenommen(conn, eid, "2026-09-25T18:05:00Z", 333) is True


def test_grundhoehe_merken_und_ihre_herkunft(conn):
    eid = _ev(conn)
    assert reddung_grund_merken(conn, eid, 20.0, "gemessen") is True
    ev = get_reddung_event(conn, eid)
    assert ev["havarist_grund_ft"] == 20.0 and ev["havarist_grund_quelle"] == "gemessen"


def test_eine_messung_ueberschreibt_eine_schaetzung_aber_nicht_umgekehrt(conn):
    """Die Messung der Bruegge ist die beste Quelle. Eine spaetere Platzhoehe darf sie
    nicht verdraengen -- sonst kippt die Hoehenschranke mitten im Abend, und niemand
    versteht, warum ein Ueberflug ploetzlich nicht mehr zaehlt."""
    eid = _ev(conn)
    reddung_grund_merken(conn, eid, 45.0, "platz")
    assert reddung_grund_merken(conn, eid, 20.0, "gemessen") is True
    assert get_reddung_event(conn, eid)["havarist_grund_ft"] == 20.0
    assert reddung_grund_merken(conn, eid, 45.0, "platz") is False
    assert get_reddung_event(conn, eid)["havarist_grund_ft"] == 20.0


def test_aufloesen_ist_ebenfalls_ein_latch(conn):
    eid = _ev(conn)
    assert set_reddung_aufgeloest(conn, eid, "2026-09-26T00:00:00Z") is True
    assert set_reddung_aufgeloest(conn, eid, "2026-09-26T00:05:00Z") is False


def test_liste_filtert_nach_zeit(conn):
    _ev(conn)
    assert len(list_reddung_events(conn)) == 1
    assert list_reddung_events(conn, since="2026-10-01T00:00:00Z") == []
