"""AIP-Sichtflugkarten: Ablage und Beschaffung.

Bis zum 31.08.2026 stand hier auch die Bildanalyse -- Kartenrahmen finden, Gradnetz-Ticks
messen, Ziffern per Schablone lesen, daraus eine Passung rechnen. Sie ist zurueckgebaut
(Nutzerentscheidung 31.08.2026, s. ``app/aip_charts.py``-Docstring); die Passung entsteht
seitdem in ``app/ground_charts.handpassung`` aus zwei geklickten Punkten, fuer beide
Kartentypen.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import base64

import pytest

from app import aip_charts
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

BASIS = "https://aip.dfs.de/BasicVFR/pages/P0016F.html"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)                       # nimmt einen PFAD, keine Verbindung
    c = get_connection(db)
    yield c
    c.close()


# --------------------------------------------------------------------------- Altes Schema
# Die Zeilen unten testen die ALTE Tabelle aip_charts (upsert_aip_chart) -- die verliert erst
# in Task 9 ihre Aufrufer und wird nicht vor der Migration geloescht (Spec 3.1: die alten
# Tabellen bleiben stehen, bis der neue Stand geprueft ist).
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


# --------------------------------------------------------------------------- Beschaffung
def test_meta_refresh_wird_aufgeloest():
    html = ('<html><head><meta http-equiv="Refresh" '
            'content="0; url=../2026AUG20/pages/ABC.html" /></head></html>')
    assert aip_charts.airac_url(html, BASIS) == \
        "https://aip.dfs.de/BasicVFR/2026AUG20/pages/ABC.html"


def test_ohne_meta_refresh_kein_ziel():
    assert aip_charts.airac_url("<html></html>", BASIS) is None


def test_airac_kennung_steht_im_pfad():
    assert aip_charts.airac_kennung(
        "https://aip.dfs.de/BasicVFR/2026AUG20/pages/ABC.html") == "2026AUG20"
    assert aip_charts.airac_kennung(BASIS) is None


def test_bild_wird_aus_dem_data_uri_geholt():
    b64 = base64.b64encode(PNG_1X1).decode()
    html = f'<img id="imgAIP" class="pageImage" src="data:image/png;base64,{b64}"/>'
    roh = aip_charts.bild_aus_html(html)
    assert roh is not None
    assert roh.startswith(b"\x89PNG\r\n\x1a\n")     # echte Magic, keine Zeichenkette


def test_seite_ohne_bild_liefert_none():
    assert aip_charts.bild_aus_html("<html><img src='logo.png'></html>") is None


def test_kapitelseiten_ohne_doppelte():
    html = ('<a href="../pages/AAA.html">1</a>'
            '<a href="../pages/BBB.html">2</a>'
            '<a href="../pages/AAA.html">nochmal</a>')
    seiten = aip_charts.kapitelseiten(
        html, "https://aip.dfs.de/BasicVFR/2026AUG20/chapter/c.html")
    assert seiten == ["https://aip.dfs.de/BasicVFR/2026AUG20/pages/AAA.html",
                      "https://aip.dfs.de/BasicVFR/2026AUG20/pages/BBB.html"]


def test_blatt_wird_atomar_geschrieben(tmp_path):
    """Sonst liefert FileResponse mitten im Austausch ein abgeschnittenes PNG aus."""
    ziel = tmp_path / "aip" / "EDXR.png"
    aip_charts.blatt_schreiben(ziel, PNG_1X1)
    assert ziel.read_bytes() == PNG_1X1
    assert not list(ziel.parent.glob("*.tmp"))     # kein Rest


def test_dfs_blatt_pfad_traegt_icao_und_sorte():
    """Ein Platz kann eine Sichtflug- UND eine Flugplatzkarte haben (110 von 446 -- gemessen
    31.08.2026); der alte Ground-Pfad war nur auf ICAO geschluesselt und liess beide sich
    gegenseitig ueberschreiben."""
    a = aip_charts.dfs_blatt_pfad("/data/x.db", "eddl", "sichtflug")
    b = aip_charts.dfs_blatt_pfad("/data/x.db", "eddl", "flugplatzkarte")
    assert a != b
    assert a.name == "EDDL.sichtflug.png"
    roh = aip_charts.dfs_blatt_pfad("/data/x.db", "eddl", "sichtflug", "roh")
    assert roh.name == "EDDL.sichtflug.roh.png"


# --------------------------------------------------------------------------- Rueckbau
def test_die_bilddeutung_ist_zurueckgebaut():
    """Sie hat ihren Zweck erfuellt -- 446 Sichtflugkarten und 110 Flugplatzblaetter sind
    beschafft und zugeordnet. Laufend gebraucht wird sie nicht: Die Blaetter aendern sich
    fast nie (Ausgabedaten von 2014 bis 2026; 437 von 446 beim einzigen Auffrischlauf
    unveraendert), und wenn doch, ist die Frage eine fuer einen Menschen.

    Der Test bindet an die Abwesenheit, damit sie nicht unbemerkt zurueckkehrt.
    """
    for weg in ("rahmen_finden", "tick_positionen", "tick_positionen_mit_band",
                "passung_rechnen", "zahl_lesen", "ziffer_erkennen", "beschriftung_lesen",
                "ausgleichsgerade", "ist_quer_gedruckt", "geometrie_gleich",
                "gerade_aus_bestand", "zeigt_denselben_ausschnitt", "blatt_auffrischen",
                "genordet_rechnen", "blatt_beschaffen", "handpassung", "raster",
                "Rahmen", "Passung"):
        assert not hasattr(aip_charts, weg), weg


def test_die_beschaffung_bleibt():
    """Blaetter holen und ablegen wird weiter gebraucht -- nur das Deuten nicht."""
    for da in ("airac_url", "airac_kennung", "bild_aus_html", "kapitel_links",
               "kapitelseiten", "seiten_des_kapitels", "blatt_schreiben",
               "dfs_blatt_pfad"):
        assert hasattr(aip_charts, da), da
