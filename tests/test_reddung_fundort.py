# -*- coding: utf-8 -*-
"""Der Fundort einer FriesenReddung nach dem Eventende (GitHub-Issue #50, 25.09.2026).

Bis dahin galt: Die Lage des Havaristen erscheint auf keiner Karte (Nutzerentscheidung
24.09.2026). Nach dem Ende eines Abends zeigt die Event-Karte unter der Bilanz jetzt, wo das
Wrack stand -- **solange das Event laeuft, bleibt alles, wie es war.** Die Riegel dafuer stehen
in ``test_reddung_db.py`` (Stand und Raster) und hier (die neue Funktion vor dem Ende).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.database import (
    create_reddung_event, get_connection, get_progress_snapshot, get_reddung_event, init_db,
    reddung_fundort, reddung_fortschreiben, set_reddung_aufgeloest, set_reddung_gefunden,
    update_reddung_event,
)

LAT, LON = 53.72, 7.25
G_LAT = 1.0 / 111.32
G_LON = 1.0 / (111.32 * math.cos(math.radians(LAT)))
JETZT = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def _event(conn, *, ende_vor_min: float) -> int:
    """Ein Abend, der vor `ende_vor_min` Minuten endete (negativ: laeuft noch)."""
    ende = JETZT - timedelta(minutes=ende_vor_min)
    return create_reddung_event(
        conn, name="Reddung Probe", dtstart=_iso(ende - timedelta(hours=2)), dtend=_iso(ende),
        sued=LAT - 2 * G_LAT, west=LON - 2 * G_LON, nord=LAT + 2 * G_LAT, ost=LON + 2 * G_LON,
        havarist_lat=LAT, havarist_lon=LON, havarist_grund_ft=10.0)


def _gefunden(conn, eid, vor_min: float):
    set_reddung_gefunden(conn, eid, _iso(JETZT - timedelta(minutes=vor_min)), 111)


def test_solange_das_event_laeuft_gibt_es_keinen_fundort(conn):
    """⚠ Der Riegel aus #21 -- auch nach Fund und Aufloesung, solange `dtend` nicht erreicht
    ist. Nach der Aufloesung fliegen womoeglich noch andere im Sektor."""
    eid = _event(conn, ende_vor_min=-30)
    _gefunden(conn, eid, 20)
    set_reddung_aufgeloest(conn, eid, _iso(JETZT - timedelta(minutes=10)))
    assert reddung_fundort(conn, get_reddung_event(conn, eid), _iso(JETZT)) is None
    snap = get_progress_snapshot(conn, "reddung", eid) or {}
    assert "fundort" not in json.dumps(snap)


def test_nicht_gefunden_heisst_kein_fundort(conn):
    """Ohne Fund gibt es keinen Fundort -- auch nicht nach dem Ende."""
    eid = _event(conn, ende_vor_min=30)
    assert reddung_fundort(conn, get_reddung_event(conn, eid), _iso(JETZT)) is None


def test_nach_dem_ende_steht_die_lage_des_havaristen(conn):
    eid = _event(conn, ende_vor_min=30)
    _gefunden(conn, eid, 60)
    ort = reddung_fundort(conn, get_reddung_event(conn, eid), _iso(JETZT))
    assert ort == {"lat": LAT, "lon": LON}


def test_der_fundort_steht_im_snapshot_und_bleibt(conn):
    """Ein spaeteres Verschieben im Admin aendert einen verkuendeten Abend nicht mehr."""
    eid = _event(conn, ende_vor_min=30)
    _gefunden(conn, eid, 60)
    reddung_fundort(conn, get_reddung_event(conn, eid), _iso(JETZT))
    assert get_progress_snapshot(conn, "reddung", eid)["fundort"] == {"lat": LAT, "lon": LON}
    update_reddung_event(conn, eid, havarist_lat=LAT + 0.5, havarist_lon=LON + 0.5)
    ort = reddung_fundort(conn, get_reddung_event(conn, eid), _iso(JETZT))
    assert ort == {"lat": LAT, "lon": LON}


def test_das_fortschreiben_behaelt_den_fundort(conn):
    """Der Snapshot wird bei jedem Fortschreiben neu zusammengesetzt -- der Fundort darf dabei
    nicht verloren gehen."""
    eid = _event(conn, ende_vor_min=30)
    ev = get_reddung_event(conn, eid)
    # Ein Snapshot, der noch nicht bis zum Ende reicht -- so muss das Fortschreiben unten
    # ihn wirklich neu schreiben, statt am Vergleich der `bis` stehen zu bleiben.
    reddung_fortschreiben(conn, ev, bis=_iso(JETZT - timedelta(minutes=90)))
    _gefunden(conn, eid, 60)
    reddung_fundort(conn, get_reddung_event(conn, eid), _iso(JETZT))
    ev = get_reddung_event(conn, eid)
    reddung_fortschreiben(conn, ev, bis=ev["dtend"])
    assert get_progress_snapshot(conn, "reddung", eid)["bis"] == ev["dtend"], "neu geschrieben"
    assert get_progress_snapshot(conn, "reddung", eid)["fundort"] == {"lat": LAT, "lon": LON}
