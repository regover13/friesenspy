"""AIP-Sichtflugkarten: Ablage, Bildanalyse, Pruefkette.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
Plan: docs/superpowers/plans/2026-08-23-aip-karten-overlay.md
"""
from __future__ import annotations

import pytest

from app.database import (
    delete_aip_chart,
    get_aip_chart,
    get_aip_charts,
    get_connection,
    init_db,
    upsert_aip_chart,
)

BOUNDS = dict(nord=54.24, sued=54.19, west=9.55, ost=9.65,
              feld_nord=54.235, feld_sued=54.195, feld_west=9.56, feld_ost=9.64)
GEO = dict(rahmen_px="132,180,817,865", tick_px_lat=219.0, tick_px_lon=128.4)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)                       # nimmt einen PFAD, keine Verbindung
    c = get_connection(db)
    yield c
    c.close()


def test_karte_anlegen_und_lesen(conn):
    upsert_aip_chart(conn, "edxr", bild_hash="abc", **BOUNDS, **GEO,
                     quelle="auto", airac="2026AUG20", status="gepasst")
    k = get_aip_chart(conn, "EDXR")
    assert k["icao"] == "EDXR"                       # normalisiert
    assert k["nord"] == pytest.approx(54.24)
    assert k["feld_nord"] == pytest.approx(54.235)   # Feld liegt INNERHALB des Blatts
    assert k["quelle"] == "auto"


def test_ungepasste_karten_bleiben_aus_der_liste(conn):
    upsert_aip_chart(conn, "EDXR", bild_hash="a", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    upsert_aip_chart(conn, "EDWJ", bild_hash="b", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="ungepasst")
    assert [k["icao"] for k in get_aip_charts(conn)] == ["EDXR"]
    assert len(get_aip_charts(conn, nur_gepasst=False)) == 2


def test_handpassung_ueberschreibt_und_bleibt_erkennbar(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="ungepasst")
    upsert_aip_chart(conn, "EDWJ", bild_hash="a", **{**BOUNDS, "nord": 55.0}, **GEO,
                     quelle="hand", airac="x", status="gepasst")
    k = get_aip_chart(conn, "EDWJ")
    assert k["quelle"] == "hand" and k["nord"] == pytest.approx(55.0)


def test_verwaiste_karte_laesst_sich_entfernen(conn):
    """Verschwindet der Eintrag aus airport_links, darf die Karte nicht im Umlauf bleiben."""
    upsert_aip_chart(conn, "EDWJ", bild_hash="a", **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    assert delete_aip_chart(conn, "EDWJ") == 1
    assert get_aip_chart(conn, "EDWJ") is None


def test_fehlendes_pflichtfeld_wird_abgewiesen(conn):
    with pytest.raises(ValueError):
        upsert_aip_chart(conn, "EDXR", bild_hash="a")
