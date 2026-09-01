"""Flugplatzkarten: Blattkunde, Handpassung, Nordung.

Die Testblaetter werden **gezeichnet, nicht heruntergeladen**: Die DFS ist keine
Testfixture, und ein Blatt aendert sich mit jedem AIRAC-Zyklus.

Die frueher hier gepruefte Bahnvermessung ist am 31.08.2026 zurueckgebaut worden -- sie kam
ueber drei von 107 Plaetzen nicht hinaus. Was davon uebrig ist, steht in
``scripts/ground_chart_probe.py`` und in Abschnitt 2 und 5 der Spec.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from app import ground_charts

TON = 153


def _blatt(striche, groesse=(1400, 800), ton=TON, rauschen=True):
    """Ein Blatt mit den angegebenen Bahnen. striche: [(x0,y0,x1,y1,breite), ...]"""
    im = Image.new("L", groesse, 255)
    z = ImageDraw.Draw(im)
    if rauschen:
        # Gebaeude und Vorfelder in ANDEREN Grautoenen, und bewusst KLEINER als eine Bahn:
        # Auf echten Blaettern macht die Bahnfarbe 3,7 Prozent aus, jeder andere Grauton
        # 0,2 bis 0,4. Ein Rauschfleck, der die Bahn uebertrifft, pruefte eine Lage, die es
        # nicht gibt -- und liess beim ersten Anlauf bahnfarbe() den Vorfeldton 200
        # zurueckgeben.
        z.rectangle((40, 40, 150, 110), fill=228)
        z.rectangle((1240, 700, 1330, 770), fill=200)
        z.ellipse((330, 40, 390, 100), fill=176)
    for x0, y0, x1, y1, br in striche:
        z.line((x0, y0, x1, y1), fill=ton, width=br)
    return im


def _png(im: Image.Image) -> bytes:
    p = io.BytesIO()
    im.save(p, "PNG")
    return p.getvalue()


# --------------------------------------------------------------------------- Blattkunde
def test_bahnfarbe_wird_gemessen_nicht_festgelegt():
    """Flugplatzkarte 153, Rollkarte 179 -- der Ton ist keine Konstante des Formats."""
    assert ground_charts.bahnfarbe(_blatt([(100, 400, 1300, 400, 28)])) == 153
    assert ground_charts.bahnfarbe(_blatt([(100, 400, 1300, 400, 28)], ton=179)) == 179


def test_ohne_bahnfarbe_kommt_none():
    """Ein Blatt ohne grosse mittelgraue Flaeche ist keine Flugplatzkarte."""
    assert ground_charts.bahnfarbe(Image.new("L", (1400, 800), 255)) is None


def test_sorte_kommt_aus_dem_bahnton():
    """Gemessen ueber 30 Blaetter von 14 Verkehrsflughaefen: 153/154 sind Flugplatzkarten
    (15 Blaetter), 179/180 Rollkarten (8), 194 bis 210 anderes. Keine Ueberschneidung."""
    assert ground_charts.sorte_aus_ton(153) == "flugplatzkarte"
    assert ground_charts.sorte_aus_ton(154) == "flugplatzkarte"
    assert ground_charts.sorte_aus_ton(179) == "rollkarte"
    assert ground_charts.sorte_aus_ton(180) == "rollkarte"


def test_fremde_toene_sind_keine_flugplatzkarte():
    for ton in (194, 195, 200, 210, None):
        assert ground_charts.sorte_aus_ton(ton) is None


def test_sorte_am_blatt():
    assert ground_charts.sorte_erkennen(
        _blatt([(100, 400, 1300, 400, 28)])) == "flugplatzkarte"
    assert ground_charts.sorte_erkennen(
        _blatt([(100, 400, 1300, 400, 28)], ton=179)) == "rollkarte"
    assert ground_charts.sorte_erkennen(Image.new("L", (1400, 800), 255)) is None


# --------------------------------------------------------------------------- Handpassung
# Die beiden Schwellen der EDDL-Bahn 05R/23L, UNGERUNDET aus runways.csv (Stand
# 30.08.2026): 2999 m lang, 052,79 Grad rechtweisend.
#
# Auf fuenf Nachkommastellen gerundet ergaben dieselben Punkte 3211 m und 056 Grad -- ein
# Laengenfehler von sieben Prozent. Der Test haette dann eine Geometrie geprueft, die es
# nicht gibt. Derselbe Fehler ist mir in tests/test_runway_ref.py schon einmal unterlaufen.
S_05R = (51.279598236083984, 6.751989841461182)
S_23L = (51.2958984375, 6.786220073699951)
BAHN_M = 2999.0


def test_zwei_punkte_bestimmen_drehung_und_massstab():
    """Vier Unbekannte, zwei Punkte, vier Gleichungen -- vollstaendig bestimmt.

    Die Bahn wird hier waagerecht ins Bild gelegt, so wie die DFS-Blaetter sie drucken. Bei
    einer Bahnrichtung von 052,8 Grad muss die Karte also um 052,8 - 90 = -37,2 Grad
    verdreht sein, was als 322,8 herauskommt -- genau der Wert, der an EDDL gemessen wurde.
    """
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    assert p is not None
    assert p.drehung == pytest.approx(322.8, abs=1.0)
    assert p.mps == pytest.approx(BAHN_M / 1770, rel=0.02)


def test_die_passung_bildet_die_gesetzten_punkte_richtig_ab():
    """Die Gegenprobe: Wer die geklickten Pixel durch die Passung schickt, muss wieder bei
    den eingegebenen Koordinaten landen."""
    from app import runway_ref

    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    a, b, e, f = p.koeff
    for px, geo in (((200.0, 500.0), S_05R), ((1970.0, 500.0), S_23L)):
        x, y = px[0], -px[1]
        ost, nord = a * x - b * y + e, b * x + a * y + f
        soll = runway_ref.meter(p.bezug, geo)
        assert ost == pytest.approx(soll[0], abs=0.5)
        assert nord == pytest.approx(soll[1], abs=0.5)


def test_gleiche_punkte_ergeben_keine_passung():
    assert ground_charts.handpassung((10.0, 10.0), S_05R, (10.0, 10.0), S_23L) is None
    assert ground_charts.handpassung((10.0, 10.0), S_05R, (99.0, 99.0), S_05R) is None


def test_zu_nah_beieinander_liegende_koordinaten_werden_abgewiesen():
    """Unter einem Meter Abstand ist der Massstab nicht mehr zu bestimmen -- das Ergebnis
    waere eine Zahl ohne Bedeutung."""
    fast = (S_05R[0] + 0.000001, S_05R[1])
    assert ground_charts.handpassung((10.0, 10.0), S_05R, (900.0, 10.0), fast) is None


def test_ein_gedrehtes_blatt_ergibt_eine_gedrehte_passung():
    """Liegt dieselbe Bahn senkrecht statt waagerecht im Bild, ist die Karte um 90 Grad
    anders orientiert."""
    waagerecht = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    senkrecht = ground_charts.handpassung((500.0, 1970.0), S_05R, (500.0, 200.0), S_23L)
    assert senkrecht is not None
    diff = (senkrecht.drehung - waagerecht.drehung) % 360
    assert diff == pytest.approx(90.0, abs=1.5) or diff == pytest.approx(270.0, abs=1.5)


# --------------------------------------------------------------------------- Nordung
def test_gedrehtes_blatt_waechst_und_bekommt_durchsichtige_ecken():
    """expand=True laesst an den Ecken Flaeche frei; bei 37 Grad ist das rund die Haelfte
    des Rechtecks. Weiss gefuellt laege ein grosses Dreieckspaar halbdeckend ueber der
    Umgebung des Platzes."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    gedreht, _grenzen = ground_charts.norden(_png(im), p, "flugplatzkarte")
    neu = Image.open(io.BytesIO(gedreht))
    assert neu.mode == "RGBA"
    assert neu.size[0] > im.size[0] and neu.size[1] > im.size[1]
    assert neu.getpixel((0, 0))[3] == 0                  # Ecke durchsichtig, nicht weiss


def test_grenzen_sind_richtig_orientiert():
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, g = ground_charts.norden(_png(im), p, "flugplatzkarte")
    assert g["nord"] > g["sued"] and g["ost"] > g["west"]


def test_feldgrenzen_sind_die_punkthuelle_nicht_die_blattgrenzen():
    """Die Verwechslung von Blatt- und Feldgrenzen steckte hinter dem
    45-Prozent-Massstabsfehler der Sichtflugkarten. Nach dem Drehen zeigt das Blatt viel
    freie Flaeche -- ueber der duerfte die Automatik nicht schon einschalten."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, g = ground_charts.norden(_png(im), p, "flugplatzkarte")
    assert g["feld_nord"] <= g["nord"] and g["feld_sued"] >= g["sued"]
    assert g["feld_west"] >= g["west"] and g["feld_ost"] <= g["ost"]


def test_das_feld_ragt_nie_ueber_das_blatt_hinaus():
    """Bei einem kleinen Blatt oder zwei nah gesetzten Punkten ragte die Huelle samt Saum
    sonst ueber den Rand -- die Automatik schaltete dann dort ein, wo die Karte nichts
    zeigt. Gemessen an einem 2200x1000-Blatt: feld_nord lag 12 m ueber nord."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2100, 700))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, g = ground_charts.norden(_png(im), p, "flugplatzkarte")
    for k in ("nord", "sued", "west", "ost"):
        assert g["sued"] <= g["feld_" + k] <= g["nord"] or k in ("west", "ost")
    assert g["feld_nord"] <= g["nord"]
    assert g["feld_sued"] >= g["sued"]


def test_die_drehung_wird_gegen_den_uhrzeigersinn_angewandt():
    """Image.rotate dreht gegen den Uhrzeigersinn. Ob 322,8 oder 37,2 uebergeben wird,
    entscheidet ueber ein exakt falsch herum liegendes Blatt.

    Die Drehung sitzt seit Task 4b in _drehen, nicht mehr direkt in norden.
    """
    import inspect
    import re

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts._drehen))
    assert "rotate(-drehung" in quelle


def test_kaputte_bilddaten_geben_none_statt_einer_ausnahme():
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    assert ground_charts.norden(b"kein PNG", p, "flugplatzkarte") is None


# --------------------------------------------------------------------------- Sorte und Saum
def test_der_saum_haengt_an_der_sorte():
    """Zwei Bedeutungen in einer Spalte waeren sonst die Folge.

    Das alte aip_charts.handpassung legte feld_* EXAKT auf die geklickten Rahmenecken --
    richtig, denn bei einer Sichtflugkarte definiert der Rahmen das Kartenfeld praezise.
    ground_charts.norden legt es auf die Huelle plus 1000 m -- richtig fuer eine
    Flugplatzkarte, wo die Passpunkte zwei Bahnschwellen mitten auf dem Platz sind und die
    Karte sonst erst einschaltete, wenn man schon auf der Bahn steht.

    Beides durch dieselbe Funktion und ohne Sorte hiesse: die 171 migrierten
    Sichtflugzeilen behielten ihr rahmengenaues feld_*, jede neu gesetzte bekaeme das
    andere -- und die Ebene schaltete auf allen vier Seiten einen Kilometer zu frueh ein.
    """
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, sicht = ground_charts.norden(_png(im), p, "sichtflug")
    _, platz = ground_charts.norden(_png(im), p, "flugplatzkarte")
    assert platz["feld_nord"] > sicht["feld_nord"]
    assert platz["feld_sued"] < sicht["feld_sued"]
    assert platz["feld_ost"] > sicht["feld_ost"]
    assert platz["feld_west"] < sicht["feld_west"]


def test_ohne_saum_ist_das_feld_genau_die_punkthuelle():
    """Die Gegenprobe zum rahmengenauen Verhalten der 171 Bestandszeilen."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), S_05R, (1970.0, 500.0), S_23L)
    _, g = ground_charts.norden(_png(im), p, "sichtflug")
    assert g["feld_nord"] == pytest.approx(max(S_05R[0], S_23L[0]), abs=1e-4)
    assert g["feld_sued"] == pytest.approx(min(S_05R[0], S_23L[0]), abs=1e-4)


# Fast genau Ost, mit einem Nord-Versatz von 3 m ueber rund 3488 m -- das ergibt eine
# Drehung nahe 0 (bzw. 360, je nach Vorzeichen), aber nicht exakt 0. An EDWE und EDAZ
# gemessen faellt aus zwei Rahmenecken tatsaechlich ein Restwinkel von 0,04 bis 0,09 Grad an.
FAST_OST = (51.28, 6.75)
FAST_OST_ZIEL = (51.280027098626237, 6.80)      # +3 m Nord


def test_eine_winzige_drehung_dreht_nicht():
    """rotate(expand=True) liesse die Leinwand um ein bis zwei Pixel wachsen und jedes
    Pixel interpolieren -- an einem Blatt, dessen Gradnetzstriche drei Pixel breit sind.
    Der bild_hash aenderte sich, obwohl inhaltlich nichts geschieht, und der Job meldete
    beim naechsten Lauf eine Aenderung."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), FAST_OST, (1970.0, 500.0), FAST_OST_ZIEL)
    gedreht, g = ground_charts.norden(_png(im), p, "sichtflug")
    assert Image.open(io.BytesIO(gedreht)).size == im.size
    assert g["drehung"] == 0.0


def test_rechte_winkel_werden_verlustfrei_gedreht():
    """Die sieben quer gedruckten Blaetter sind genau dieser Fall. transpose() ist
    verlustfrei, rotate(resample=BICUBIC) interpoliert jedes Pixel."""
    import inspect
    import re

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts._drehen))
    assert "transpose" in quelle
    modul = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts))
    assert "ROTATE_90" in modul and "ROTATE_180" in modul and "ROTATE_270" in modul


def test_norden_gibt_die_tatsaechlich_angewandte_drehung_zurueck_nicht_die_gerechnete():
    """Es gibt eine GERECHNETE Drehung -- nahe 0 bzw. 360, aber nicht exakt. Die Rueckgabe
    muss trotzdem 0.0 sagen, sonst schriebe der Aufrufer eine Drehung in die Datenbank,
    waehrend das Blatt ungedreht liegt."""
    im = _blatt([(200, 500, 1970, 500, 28)], groesse=(2200, 1000))
    p = ground_charts.handpassung((200.0, 500.0), FAST_OST, (1970.0, 500.0), FAST_OST_ZIEL)
    assert p.drehung not in (0.0, 360.0)
    _, g = ground_charts.norden(_png(im), p, "sichtflug")
    assert g["drehung"] == 0.0


def test_drehung_ueberschreiben_behaelt_massstab_und_ankerpunkt():
    """Bei zwei nah beieinanderliegenden Punkten ist der abgeleitete Wert schlecht --
    Nachjustieren von Hand muss den Massstab und den Ankerpunkt unangetastet lassen, sonst
    verschiebt sich das Blatt beim Korrigieren der Drehung."""
    p1_px = (200.0, 500.0)
    p = ground_charts.handpassung(p1_px, S_05R, (1970.0, 500.0), S_23L)
    ueberschrieben = ground_charts.drehung_ueberschreiben(p, p1_px, 15.0)
    assert ueberschrieben.drehung == pytest.approx(15.0)
    assert ueberschrieben.mps == pytest.approx(p.mps)
    assert ueberschrieben.bezug == p.bezug
    # p1 bildet unter der neuen Passung weiterhin auf den Nullpunkt (0,0) ab -- derselbe
    # Ankerpunkt wie bei der urspruenglichen Berechnung.
    a, b, e, f = ueberschrieben.koeff
    x, y = p1_px[0], -p1_px[1]
    assert (a * x - b * y + e, b * x + a * y + f) == pytest.approx((0.0, 0.0), abs=1e-6)


def test_die_bahnvermessung_ist_zurueckgebaut():
    """Sie kam ueber drei von 107 Plaetzen nicht hinaus (Nutzerentscheidung 31.08.2026:
    "Was bringt eine Automatik fuer 3 Plaetze?").

    Der Test bindet an die Abwesenheit, damit sie nicht unbemerkt zurueckkehrt: Ein
    Verfahren, das 271 Plaetzen ohne Schwellenkoordinaten prinzipiell nichts nuetzt,
    gehoert nicht in den Wochenlauf.
    """
    for weg in ("passung_rechnen", "bahnflaechen", "hauptachse", "enden_tasten",
                "achsen_zusammenfassen", "aehnlich"):
        assert not hasattr(ground_charts, weg), weg


# --------------------------------------------------- Viertelwendungen (Fund 01.09.2026)

def test_die_viertelwendung_dreht_in_dieselbe_richtung_wie_der_allgemeine_weg():
    """DER Test. Bei 90 und 270 Grad nimmt ``_drehen`` eine verlustfreie Abkuerzung ueber
    ``transpose`` -- und die drehte in die ENTGEGENGESETZTE Richtung wie ``rotate(-drehung)``.

    PILs ``ROTATE_90`` dreht gegen den Uhrzeigersinn, ``rotate(-90)`` mit ihm. Bei 180 Grad
    faellt es nicht auf, weil symmetrisch; bei 90 und 270 liegt das Blatt um 180 Grad
    verdreht. Gemeldet als "die Karte wird falsch herum gedreht" (EDTM, Drehung 90,00).
    """
    from PIL import Image
    from app.ground_charts import _drehen
    # Ein Bild, das man eindeutig wiedererkennt -- quadratisch, damit die Groesse nicht
    # schon durch das Seitenverhaeltnis unterscheidbar waere.
    im = Image.new("RGB", (40, 40), (255, 255, 255))
    im.paste((0, 0, 0), (0, 0, 14, 6))
    for grad in (90, 180, 270):
        gedreht, tatsaechlich = _drehen(im, float(grad))
        assert tatsaechlich == float(grad)
        soll = im.rotate(-grad, expand=True)
        assert list(gedreht.convert("L").getdata()) == list(soll.convert("L").getdata()), \
            f"Viertelwendung um {grad} Grad dreht anders als rotate(-{grad})"


def test_die_viertelwendung_bleibt_verlustfrei():
    """Der Grund fuer die Abkuerzung: rotate() interpoliert jedes Pixel und liesse den
    bild_hash ohne inhaltlichen Grund wandern. Sie darf also weiter transpose benutzen."""
    import inspect

    from app import ground_charts
    quelle = inspect.getsource(ground_charts._drehen)
    assert "transpose" in quelle
