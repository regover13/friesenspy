# -*- coding: utf-8 -*-
"""Havarist und Fackeln als Bruegge-Objekte (20.09.2026)."""
from __future__ import annotations

import pathlib

import pytest

from app.database import bruegge_soll_fuer, bruegge_soll_setzen, get_connection, init_db


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def test_ohne_simulator_gilt_ein_objekt_fuer_alle(conn):
    bruegge_soll_setzen(conn, "havarist-1", "flugzeug_echo", 53.7, 7.2)
    for sim in ("msfs2020", "msfs2024", "xplane12"):
        assert len(bruegge_soll_fuer(conn, 111, sim)) == 1


def test_mit_simulator_sieht_es_nur_dieser(conn):
    bruegge_soll_setzen(conn, "havarist-2020", "boot_klein", 53.7, 7.2, simulator="msfs2020")
    bruegge_soll_setzen(conn, "havarist-2024", "schiff_segel", 53.7, 7.2, simulator="msfs2024")
    ids_2020 = [o["id"] for o in bruegge_soll_fuer(conn, 111, "msfs2020")]
    ids_2024 = [o["id"] for o in bruegge_soll_fuer(conn, 111, "msfs2024")]
    assert ids_2020 == ["havarist-2020"] and ids_2024 == ["havarist-2024"]
    assert bruegge_soll_fuer(conn, 111, "xplane12") == []


def test_ohne_angabe_des_simulators_kommt_weiterhin_alles(conn):
    """Abwaertskompatibel: Wer den Parameter nicht angibt, bekommt wie bisher alles. Sonst
    verliert ein aelterer Aufrufer still Objekte."""
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator="msfs2020")
    assert len(bruegge_soll_fuer(conn, 111)) == 1


def test_der_simulator_laesst_sich_wieder_auf_alle_stellen(conn):
    """Das ON-CONFLICT muss die Spalte mitziehen -- sonst bleibt ein alter Filter stehen und
    das Objekt verschwindet fuer zwei Drittel der Piloten."""
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator="msfs2020")
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator=None)
    assert len(bruegge_soll_fuer(conn, 111, "xplane12")) == 1


def test_der_melde_endpunkt_filtert_nach_simulator():
    """Verankert am Quelltext: Wer den Parameter beim Aufruf wieder wegnimmt, liefert
    2020-Piloten Objekte aus, die sie nicht setzen koennen."""
    quelle = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "bruegge_soll_fuer(conn, cid, simulator)" in quelle
