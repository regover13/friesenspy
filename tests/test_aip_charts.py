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


# ---------------------------------------------------------------------------
# Task 4 -- Grad-Zahlen lesen
# ---------------------------------------------------------------------------
from blatt_bauen import ZIFFERN  # noqa: E402


def _bitmap(ziffer: str) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(1 if z == "#" else 0 for z in zeile) for zeile in ZIFFERN[ziffer])


def test_jede_ziffer_der_pruefschrift_wird_erkannt():
    for z in "0123456789":
        assert aip_charts.ziffer_erkennen(_bitmap(z)) == int(z), f"Ziffer {z}"


def test_ein_pixel_hoeher_wird_noch_erkannt():
    """Die Schwellwertbildung an den Raendern erzeugt Hoehenunterschiede von einem Pixel --
    daran scheitert ein Hash-Vergleich, der Schablonenvergleich darf es nicht."""
    bm = _bitmap("5")
    assert aip_charts.ziffer_erkennen(bm + (bm[-1],)) == 5


def test_unlesbares_zeichen_liefert_none():
    """Lieber keine Zahl als eine falsche: Eine falsche Minute verschiebt um 1,85 km."""
    assert aip_charts.ziffer_erkennen(((1, 0, 1), (0, 1, 0), (1, 0, 1))) is None


def test_breite_wird_aus_dem_linken_band_gelesen():
    im = blatt_bauen(breite_links=(54, 14), tick_lat_px=219.0)
    r = aip_charts.rahmen_finden(im)
    ty, _tx = aip_charts.tick_positionen(im, r)
    paare = aip_charts.beschriftung_lesen(im, r, ty, "y")
    assert len(paare) >= 3
    assert [round(g, 4) for _p, g in paare[:3]] == [54.2333, 54.2167, 54.2]


def test_laenge_wird_aus_dem_oberen_band_gelesen():
    """Fassung 1 des Plans las nur das linke Band -- damit fehlte die halbe Passung."""
    im = blatt_bauen(laenge_oben=(9, 36), tick_lon_px=128.4)
    r = aip_charts.rahmen_finden(im)
    _ty, tx = aip_charts.tick_positionen(im, r)
    paare = aip_charts.beschriftung_lesen(im, r, tx, "x")
    assert len(paare) >= 3
    assert [round(g, 4) for _p, g in paare[:3]] == [9.6, 9.6167, 9.6333]


def test_feines_gitter_bleibt_lesbar():
    """Mit festen 20-Pixel-Fenstern griffen benachbarte Beschriftungen ineinander: bei
    dx = 34 waren von 20 Ticks nur 6 lesbar (Gutachten 23.08.2026, Befund B5)."""
    im = blatt_bauen(laenge_oben=(9, 36), tick_lon_px=34.27)
    r = aip_charts.rahmen_finden(im)
    _ty, tx = aip_charts.tick_positionen(im, r)
    paare = aip_charts.beschriftung_lesen(im, r, tx, "x")
    assert len(paare) >= 0.8 * len(tx), f"nur {len(paare)} von {len(tx)} lesbar"


# ---------------------------------------------------------------------------
# Task 5 -- Passung rechnen, Pruefkette
# ---------------------------------------------------------------------------

def test_ausgleichsgerade_meldet_das_groesste_residuum():
    m, b, res = aip_charts.ausgleichsgerade([(0.0, 0.0), (10.0, 1.0), (20.0, 2.0)])
    assert m == pytest.approx(0.1) and b == pytest.approx(0.0) and res < 1e-9


def test_verfaelschte_stuetzstelle_faellt_auf():
    """Ein um eine Bogenminute falsch gelesener Wert erzeugt ein riesiges Residuum -- das
    ist die Pruefung, gegen die die cos-Probe blind ist."""
    gut = [(0.0, 54.0), (219.0, 54.0 - 1 / 60), (438.0, 54.0 - 2 / 60)]
    schlecht = [(0.0, 54.0), (219.0, 54.0 - 2 / 60), (438.0, 54.0 - 2 / 60)]
    assert aip_charts.ausgleichsgerade(gut)[2] < 1e-9
    assert aip_charts.ausgleichsgerade(schlecht)[2] > 1e-4


def test_passung_deckt_das_ganze_blatt_ab():
    """Die Blattgrenzen liegen AUSSERHALB des Kartenfelds -- das Blatt wird ungeschnitten
    ausgeliefert, damit Kopfzeile und Frequenzen lesbar bleiben."""
    im = blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36))
    p = aip_charts.passung_rechnen(im, arp_lat=54.21, arp_lon=9.62)
    assert p is not None
    assert p.nord > p.feld_nord and p.sued < p.feld_sued
    assert p.west < p.feld_west and p.ost > p.feld_ost


def test_platz_ausserhalb_des_kartenfelds_wird_verworfen():
    """Nicht nur 'irgendwo auf dem Blatt': Das Blatt ist rund 10 km hoch, eine Verschiebung
    um 5 km haette den schwaecheren Test bestanden (Gutachten 23.08.2026)."""
    im = blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36))
    assert aip_charts.passung_rechnen(im, arp_lat=54.30, arp_lon=9.62) is None


def test_karte_ohne_rahmen_liefert_keine_passung():
    from PIL import Image
    assert aip_charts.passung_rechnen(Image.new("L", (875, 1240), 255), 54.0, 9.0) is None


def test_cos_probe_verwirft_falsche_breite():
    """EDWT lag mit 4,14 Grad daneben und wurde verworfen."""
    im = blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36))
    assert aip_charts.passung_rechnen(im, arp_lat=48.0, arp_lon=9.62) is None


# ---------------------------------------------------------------------------
# Task 6 -- AIRAC-Nachlauf und Ablage
# ---------------------------------------------------------------------------

def _passung(**abw):
    grund = dict(nord=1.0, sued=0.0, west=0.0, ost=1.0, feld_nord=0.9, feld_sued=0.1,
                 feld_west=0.1, feld_ost=0.9, rahmen_px="132.0,180.0,817.0,865.0",
                 tick_px_lat=219.0, tick_px_lon=128.4)
    return aip_charts.Passung(**{**grund, **abw})


def test_gleiche_geometrie_erhaelt_die_handpassung():
    alt = {"rahmen_px": "132.0,180.0,817.0,865.0", "tick_px_lat": 219.0, "tick_px_lon": 128.4}
    assert aip_charts.geometrie_gleich(alt, _passung()) is True


def test_verschobener_rahmen_erzwingt_neue_passung():
    alt = {"rahmen_px": "132.0,180.0,817.0,900.0", "tick_px_lat": 219.0, "tick_px_lon": 128.4}
    assert aip_charts.geometrie_gleich(alt, _passung()) is False


def test_rasterabstand_wird_schaerfer_geprueft_als_der_rahmen():
    """2 px auf 219 sind 0,9 Prozent, ueber dphi/dv also rund 0,5 Grad Breite -- mehr als die
    Toleranz der cos-Probe. Fuer Rasterabstaende gelten deshalb 0,5 px."""
    alt = {"rahmen_px": "132.0,180.0,817.0,865.0", "tick_px_lat": 220.5, "tick_px_lon": 128.4}
    assert aip_charts.geometrie_gleich(alt, _passung()) is False


def test_blatt_wird_atomar_geschrieben(tmp_path):
    """Sonst liefert FileResponse mitten im Austausch ein abgeschnittenes PNG aus."""
    ziel = tmp_path / "aip" / "EDXR.png"
    aip_charts.blatt_schreiben(ziel, PNG_1X1)
    assert ziel.read_bytes() == PNG_1X1
    assert not list(ziel.parent.glob("*.tmp"))     # kein Rest


def test_kaputte_geometrieangabe_gilt_als_abweichend():
    assert aip_charts.geometrie_gleich({"rahmen_px": "unsinn"}, _passung()) is False
    assert aip_charts.geometrie_gleich({}, _passung()) is False


def test_blatt_beschaffen_findet_die_karte_auf_der_zweiten_seite(tmp_path):
    """Fall EDAZ: Der gespeicherte Link zeigt auf die Textseite, die Karte liegt im selben
    Kapitel. 28 von 446 Karten liegen so."""
    import io
    puffer = io.BytesIO()
    blatt_bauen(breite_links=(54, 14), laenge_oben=(9, 36)).save(puffer, format="PNG")
    karte_b64 = base64.b64encode(puffer.getvalue()).decode()
    leer_b64 = base64.b64encode(PNG_1X1).decode()

    seiten = {
        "https://aip.dfs.de/BasicVFR/pages/P1.html":
            '<meta http-equiv="Refresh" content="0; url=../2026AUG20/pages/AAAA1111BBBB2222CCCC3333DDDD44.html"/>',
        "https://aip.dfs.de/BasicVFR/2026AUG20/pages/AAAA1111BBBB2222CCCC3333DDDD44.html":
            f'<img id="imgAIP" src="data:image/png;base64,{leer_b64}"/>'
            '<a href="../chapter/abc.html">Kapitel</a>',
        "https://aip.dfs.de/BasicVFR/2026AUG20/chapter/abc.html":
            '<a href="../pages/AAAA1111BBBB2222CCCC3333DDDD44.html">1</a><a href="../pages/EEEE5555FFFF6666AAAA7777BBBB88.html">2</a>',
        "https://aip.dfs.de/BasicVFR/2026AUG20/pages/EEEE5555FFFF6666AAAA7777BBBB88.html":
            f'<img id="imgAIP" src="data:image/png;base64,{karte_b64}"/>',
    }
    roh, passung, airac = aip_charts.blatt_beschaffen(
        "https://aip.dfs.de/BasicVFR/pages/P1.html", 54.21, 9.62, seiten.__getitem__)
    assert roh is not None and passung is not None
    assert airac == "2026AUG20"


def test_blatt_beschaffen_meldet_netzfehler_statt_zu_luegen():
    """Ein fehlgeschlagener Abruf darf keine bestehende Karte entwerten."""
    def kaputt(_url):
        raise OSError("Netz weg")
    with pytest.raises(OSError):
        aip_charts.blatt_beschaffen("https://x/y.html", 54.0, 9.0, kaputt)


# ---------------------------------------------------------------------------
# Task 9 -- Handpassung: Rahmenecken -> Blattgrenzen
# ---------------------------------------------------------------------------

def test_handpassung_verlaengert_auf_die_blattkanten():
    """Die geklickten Rahmenecken direkt als Blattgrenzen abzulegen waere falsch: Beim
    Standardblatt wuerde ein 875x1240-Bild in einen 685x685-Rahmen gequetscht, rund 45 %
    Massstabsfehler senkrecht -- ausgerechnet bei den Karten, denen man am meisten vertraut
    (Gutachten 23.08.2026, Befund 5)."""
    p = aip_charts.handpassung(
        breite_px=875, hoehe_px=1240,
        links_px=132, oben_px=180, rechts_px=817, unten_px=865,
        feld_nord=54.2333, feld_sued=54.2000, feld_west=9.6000, feld_ost=9.6333)
    assert p is not None
    # Blatt ragt oben und unten ueber das Feld hinaus
    assert p.nord > p.feld_nord and p.sued < p.feld_sued
    assert p.west < p.feld_west and p.ost > p.feld_ost
    # Und zwar im richtigen Verhaeltnis: 180 px ueber dem Feld bei 685 px Feldhoehe
    grad_je_px = (p.feld_nord - p.feld_sued) / (865 - 180)
    assert p.nord == pytest.approx(p.feld_nord + 180 * grad_je_px, abs=1e-9)
    assert p.sued == pytest.approx(p.feld_sued - (1240 - 865) * grad_je_px, abs=1e-9)


def test_handpassung_weist_verdrehte_ecken_ab():
    assert aip_charts.handpassung(
        breite_px=875, hoehe_px=1240,
        links_px=132, oben_px=180, rechts_px=817, unten_px=865,
        feld_nord=54.20, feld_sued=54.23, feld_west=9.60, feld_ost=9.63) is None
    assert aip_charts.handpassung(
        breite_px=875, hoehe_px=1240,
        links_px=817, oben_px=180, rechts_px=132, unten_px=865,
        feld_nord=54.23, feld_sued=54.20, feld_west=9.60, feld_ost=9.63) is None


def test_handpassung_weist_pixel_ausserhalb_des_blatts_ab():
    assert aip_charts.handpassung(
        breite_px=875, hoehe_px=1240,
        links_px=-5, oben_px=180, rechts_px=817, unten_px=865,
        feld_nord=54.23, feld_sued=54.20, feld_west=9.60, feld_ost=9.63) is None


# ---------------------------------------------------------------------------
# Fehlende Gradzahlen ergaenzen (24.08.2026)
# ---------------------------------------------------------------------------
def _erg(roh, achse, arp):
    return [(t, g + m / 60.0) for t, g, m in aip_charts._grade_ergaenzen(roh, achse, arp)]


def test_fehlende_gradzahl_kommt_vom_lesbaren_nachbarn():
    """Steht die Gradzahl an EINEM Tick, folgt sie fuer alle -- die Ticks sind aequidistant."""
    # Breite: nach unten (wachsender Pixel) nimmt der Wert AB, die Minuten also auch.
    roh = [(100.0, 53, 20), (150.0, None, 19), (200.0, None, 18)]
    assert _erg(roh, "y", 53.31) == [
        (200.0, 53 + 18 / 60), (150.0, 53 + 19 / 60), (100.0, 53 + 20 / 60)]


def test_ohne_jede_gradzahl_liefert_die_platzkoordinate_den_grundwert():
    """Das Kartenfeld ist rund fuenf Bogenminuten hoch und enthaelt den Platz.

    Die mittlere Tickzahl liegt damit wenige Minuten neben ihm; ein Griff daneben waere
    ein ganzer Grad, also 60 Minuten.
    """
    roh = [(100.0, None, 20), (150.0, None, 19), (200.0, None, 18)]
    werte = dict(_erg(roh, "y", 53.317))
    assert werte[100.0] == 53 + 20 / 60
    assert werte[200.0] == 53 + 18 / 60


def test_gradgrenze_im_kartenfeld_wird_aufgerollt():
    """Springt die Minute in Richtung wachsender Werte zurueck, ist ein Grad ueberschritten.

    Ein Platz bei 53°59' hat Ticks bei 58', 59', 00', 01' -- die letzten beiden gehoeren
    zu 54°. Sie stumpf auf 53° zu setzen, legte das Blatt 111 km zu weit sued.
    """
    # Laenge: nach rechts (wachsender Pixel) nimmt der Wert ZU.
    roh = [(100.0, None, 58), (150.0, None, 59), (200.0, None, 0), (250.0, None, 1)]
    werte = dict(_erg(roh, "x", 6.995))
    assert werte[150.0] == 6 + 59 / 60
    assert werte[200.0] == 7.0
    assert werte[250.0] == 7 + 1 / 60


def test_gelesene_gradzahl_wird_nicht_ueberschrieben():
    """Sie muss sich weiter an Pruefung (2) und den Residuen messen lassen.

    Der Zusatz ist rein additiv -- was vorher durchlief, laeuft unveraendert durch. Hier
    steht an einem Tick absichtlich eine unpassende Gradzahl: Sie bleibt stehen, damit die
    Residuenpruefung sie sieht, statt still weggebuegelt zu werden.
    """
    roh = [(100.0, 53, 20), (150.0, 99, 19), (200.0, None, 18)]
    werte = dict(_erg(roh, "y", 53.31))
    assert werte[150.0] == 99 + 19 / 60


def test_ohne_ticks_kommt_nichts_heraus():
    """Kein Sonderfall, aber der Grundwert wird sonst aus einer leeren Folge gebildet."""
    assert aip_charts._grade_ergaenzen([], "y", 53.0) == []


# ---------------------------------------------------------------------------
# Tickstrich abtasten statt schaetzen (24.08.2026)
# ---------------------------------------------------------------------------
def test_strich_ende_findet_das_ende_eines_zwei_pixel_strichs():
    """Auf der 874x1240-Serie ist der waagerechte Tickstrich ZWEI Pixel dick.

    Der feste Ein-Pixel-Abstand liess die zweite Zeile im Suchfenster stehen. Eine
    durchgezogene Zeile macht jede Spalte dunkel, alle Zeichen verschmelzen zu einer Gruppe
    von 19 Pixeln Breite -- und die faellt durch ``2 <= len(g) <= 12``. Herausgekommen ist
    NULL statt zwei Ziffern (gemessen an EDAH, Tick y=315).
    """
    voll = {10, 11}.__contains__
    assert aip_charts._strich_ende(voll, 10, +1) == 12
    assert aip_charts._strich_ende(voll, 11, -1) == 9


def test_strich_ende_laesst_einen_pixel_strich_unveraendert():
    """Die 875er-Serie hat einen Pixel -- dort darf sich nichts aendern."""
    voll = {10}.__contains__
    assert aip_charts._strich_ende(voll, 10, +1) == 11
    assert aip_charts._strich_ende(voll, 10, -1) == 9


def test_strich_ende_laeuft_nicht_davon():
    """Eine grossflaechig dunkle Stelle darf den Lauf nicht mitnehmen."""
    assert aip_charts._strich_ende(lambda p: True, 10, +1, grenze=4) == 14


def test_laengenachse_behaelt_den_festen_abstand():
    """Gemessen: Mit derselben Abtastung fiel EDAH von 10 auf 5 lesbare Laengen-Stuetzstellen.

    Der Zwei-Pixel-Strich ist ein Problem der WAAGERECHTEN Striche; die senkrechten sind auf
    denselben Blaettern einen Pixel dick. Deshalb an den Quelltext gebunden, nicht an eine
    Beschreibung.
    """
    import inspect
    quelle = inspect.getsource(aip_charts.zeichen_im_band)
    kopf, rest = quelle.split('if achse == "y":', 1)
    assert "_strich_ende(zeile_voll" in rest.split("return oben, unten")[0]
    assert "_strich_ende" not in rest.split("return oben, unten")[1]


# ---------------------------------------------------------------------------
# Rasterabstand berichtigen (25.08.2026)
# ---------------------------------------------------------------------------
def test_raster_berichtigen_erkennt_ein_vielfaches():
    """Bei EDWE lieferte raster() 263 px fuer die Breite -- der echte Abstand ist 43,8.

    Genau das Sechsfache. Erkannt wird es ueber die Physik: Eine Bogenminute Laenge ist um
    cos(Breite) kuerzer als eine Bogenminute Breite, also muss dx/dy = cos(Breite) gelten.
    """
    dy, dx = aip_charts._raster_berichtigen(263.0, 26.1, 53.39)
    assert round(dy, 1) == 43.8
    assert dx == 26.1


def test_raster_berichtigen_laesst_stimmiges_in_ruhe():
    """Passt dx/dy schon zur Breite, darf nichts angefasst werden."""
    import math
    lat = 51.5
    dy = 219.0
    dx = dy * math.cos(math.radians(lat))
    assert aip_charts._raster_berichtigen(dy, dx, lat) == (dy, dx)


def test_raster_berichtigen_korrigiert_nur_bei_sauberem_faktor():
    """EDUW misst 127 statt 146 px -- das ist KEIN Vielfaches, sondern der Abstand zweier
    zufaellig gefundener Striche. Dort darf nicht geraten werden.

    Diese Grenze ist der Grund, warum die Berichtigung nichts durchlassen kann, was vorher
    zu Recht abgelehnt wurde: Ohne ganzzahligen Faktor bleibt alles beim gemessenen Wert.
    """
    assert aip_charts._raster_berichtigen(127.0, 86.0, 53.92) == (127.0, 86.0)


def test_raster_berichtigen_kann_auch_die_laenge_treffen():
    """Der Fehler sitzt nicht immer auf der Breitenachse."""
    import math
    lat = 50.0
    dy = 100.0
    echt = dy * math.cos(math.radians(lat))
    dy2, dx2 = aip_charts._raster_berichtigen(dy, echt * 3, lat)
    assert dy2 == dy
    assert abs(dx2 - echt) < 0.01


def test_quer_gedruckte_blaetter_werden_erkannt():
    """Sieben der 446 Blaetter haben Norden zur SEITE (EDLP, EDMA, EDCQ, EDHE, EDLV, EDQG, EDTY).

    Bei EDLP steht die Kopfzeile hochkant, im oberen Band stehen Breiten (51°40', 51°35') statt
    Laengen. Ohne Erkennung sind sie nicht zu retten: Achsen vertauscht, Schrift auf der Seite.

    Erkannt wird an der Geometrie: Auf einem genordeten Blatt ist eine Bogenminute Laenge um
    cos(Breite) kuerzer als eine der Breite, also dx < dy. Steht das Blatt quer, kippt das.
    """
    import math

    class _Bild:
        pass

    lat = 51.61
    cos = math.cos(math.radians(lat))
    # Genordet: dx/dy == cos -> kein Quer-Verdacht.
    assert not aip_charts._quer_verdacht(100.0, 100.0 * cos, lat)
    # Quer: die Achsen tauschen die Rollen.
    assert aip_charts._quer_verdacht(100.0 * cos, 100.0, lat)


def test_quer_test_schlaegt_bei_genordeten_nicht_an():
    """An 380 genordeten Blaettern hat der Test keinen Fehlalarm erzeugt (25.08.2026).

    Ein Fehlalarm waere teuer: Das Blatt wuerde gedreht abgelegt und laege danach quer auf
    der Karte -- schlimmer als ein Blatt, das fehlt.
    """
    import math
    for lat in (47.5, 50.0, 51.6, 53.9, 55.0):
        cos = math.cos(math.radians(lat))
        for k in (1.0, 2.0, 5.0):
            assert not aip_charts._quer_verdacht(100.0 * k, 100.0 * k * cos, lat)
