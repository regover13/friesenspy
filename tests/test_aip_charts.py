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


# ---------------------------------------------------------------------------
# Task 2 -- Blatt beschaffen
# ---------------------------------------------------------------------------
import base64  # noqa: E402

from app import aip_charts  # noqa: E402

BASIS = "https://aip.dfs.de/BasicVFR/pages/P0016F.html"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


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


# ---------------------------------------------------------------------------
# Task 3 -- Kartenrahmen und Gradnetz vermessen
# ---------------------------------------------------------------------------
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "aip"))
from blatt_bauen import blatt_bauen  # noqa: E402


def test_rahmen_wird_im_standardlayout_gefunden():
    r = aip_charts.rahmen_finden(blatt_bauen())
    assert r is not None
    assert (round(r.links), round(r.oben), round(r.rechts), round(r.unten)) == (132, 180, 817, 865)


def test_rahmen_auch_bei_gekreuzter_linie():
    """Die vertikale 'Berichtigung:'-Beschriftung unterbricht die linke Rahmenlinie; sie ist
    dann nur zu 88 Prozent durchgehend. Deshalb zaehlt der Anteil, nicht der laengste Lauf."""
    r = aip_charts.rahmen_finden(blatt_bauen(rahmen_kreuzen=True))
    assert r is not None and round(r.links) == 132


def test_rahmen_nicht_die_kopfzeilenlinie():
    """Layout-Trennlinien von Kopf- und Fusszeile bilden auf manchen Blaettern selbst ein
    Paar im Doppelrahmen-Abstand. Die naive Wahl (aeusserstes Paar) lieferte dann
    (132, 136, 817, 909) statt (132, 180, 817, 865) -- gemessen am 23.08.2026."""
    r = aip_charts.rahmen_finden(blatt_bauen(kopf_fuss_linien=True))
    assert r is not None
    assert (round(r.links), round(r.oben), round(r.rechts), round(r.unten)) == \
        (132, 180, 817, 865)


def test_rahmen_auch_wenn_alles_zusammenkommt():
    r = aip_charts.rahmen_finden(
        blatt_bauen(kopf_fuss_linien=True, stoerstriche=True, rahmen_kreuzen=True))
    assert r is not None and (round(r.oben), round(r.unten)) == (180, 865)


def test_textseite_hat_keinen_rahmen():
    from PIL import Image
    assert aip_charts.rahmen_finden(Image.new("L", (875, 1240), 255)) is None


def test_raster_verwirft_stoerstriche():
    """Gutachten 23.08.2026: Ein feineres Raster hat immer mindestens so viele Treffer.
    Ohne Belegungspruefung lieferte diese Eingabe 16,67 statt 50."""
    d, n, _anker = aip_charts.raster([100.0, 150.0, 200.0, 217.0, 250.0])
    assert d == pytest.approx(50.0)
    assert n == 4


def test_raster_unterteilt_den_abstand_nicht():
    """Ein zu feines Raster passt immer, und die Achsen-Vielfachen wuerden es zudecken.
    Bei EDAB kam so ein Drittel des echten Abstands heraus, bei 0,006 Grad Probenfehler."""
    assert aip_charts.raster([0.0, 60.0, 120.0])[0] == pytest.approx(60.0)


def test_raster_vertraegt_luecken():
    """Fehlt ein Tick, bleibt das Raster gueltig -- die Vielfachen decken die Luecke ab."""
    assert aip_charts.raster([151.0, 289.0, 566.0, 704.0])[0] == pytest.approx(138.3, abs=0.5)


def test_raster_treffer_filtert_ausreisser():
    """Nur die Positionen auf dem Raster taugen als Stuetzstelle fuers Zahlenlesen."""
    pos = [100.0, 150.0, 200.0, 217.0, 250.0]
    d, _n, anker = aip_charts.raster(pos)
    assert aip_charts.raster_treffer(pos, d, anker) == [100.0, 150.0, 200.0, 250.0]


def test_stoerstrich_ganz_vorn_kippt_die_stuetzstellen_nicht():
    """Ohne mitgelieferten Anker nimmt raster_treffer pos[0] -- ist das der Stoerstrich,
    ueberlebt genau er, und beschriftung_lesen liefert eine leere Liste (Gutachten
    23.08.2026, Befund B1)."""
    ticks = [172.0, 196.0, 324.0, 453.0, 581.0, 709.0]
    d, _n, anker = aip_charts.raster(ticks)
    assert aip_charts.raster_treffer(ticks, d, anker) == [196.0, 324.0, 453.0, 581.0, 709.0]


def test_ticks_liefern_die_gebauten_abstaende():
    im = blatt_bauen(tick_lat_px=219.0, tick_lon_px=128.4)
    ty, tx = aip_charts.tick_positionen(im, aip_charts.rahmen_finden(im))
    assert aip_charts.raster(ty)[0] == pytest.approx(219.0, abs=1.0)
    assert aip_charts.raster(tx)[0] == pytest.approx(128.4, abs=1.0)


def test_feines_gitter_wird_nicht_verworfen():
    """Eine Obergrenze von 30 Ticks warf Querformat-Karten hinaus (EDAB 31, EDWE 39)."""
    im = blatt_bauen(tick_lat_px=54.78, tick_lon_px=32.1)
    ty, _tx = aip_charts.tick_positionen(im, aip_charts.rahmen_finden(im))
    assert len(ty) > 10
