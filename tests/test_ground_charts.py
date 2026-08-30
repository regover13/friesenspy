"""Flugplatzkarten: Bildanalyse und Pruefkette.

Die Testblaetter werden **gezeichnet, nicht heruntergeladen**: Die DFS ist keine
Testfixture, und ein Blatt aendert sich mit jedem AIRAC-Zyklus.

``_kunstblatt`` rechnet bewusst mit eigenen Formeln statt mit denen des Moduls -- sonst
pruefte der Test seine eigene Umkehrung.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md
"""
from __future__ import annotations

import io
import math

import pytest
from PIL import Image, ImageDraw

from app import ground_charts
from app.runway_ref import Bahn

TON = 153


def _blatt(striche, groesse=(1400, 800), ton=TON, rauschen=True):
    """Ein Blatt mit den angegebenen Bahnen. striche: [(x0,y0,x1,y1,breite), ...]"""
    im = Image.new("L", groesse, 255)
    z = ImageDraw.Draw(im)
    if rauschen:
        # Gebaeude und Vorfelder in ANDEREN Grautoenen. Ohne sie pruefte der Test nur, ob
        # der Code das einzige Nichtweiss findet.
        # Bewusst KLEINER als eine Bahn: Auf echten Blaettern macht die Bahnfarbe 3,7
        # Prozent aus, jeder andere Grauton 0,2 bis 0,4. Ein Rauschfleck, der die Bahn
        # uebertrifft, pruefte eine Lage, die es nicht gibt -- und liess beim ersten
        # Anlauf bahnfarbe() den Vorfeldton 200 zurueckgeben.
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


# ---------------------------------------------------------------------------
# Ein Kunstblatt aus bekannter Wahrheit -- die Gegenprobe der ganzen Kette
# ---------------------------------------------------------------------------
_M_LON, _M_LAT = 69_000.0, 111_254.0    # grob fuer 51,3 Grad Nord; nur zum Zeichnen


def _kunstblatt(drehung_grad: float, mps: float, bahnen_m, groesse=(2600, 1800),
                ton=TON, bezug=(51.28, 6.75), breite_m=45.0):
    """Ein Blatt zeichnen, dessen Passung bekannt ist.

    ``bahnen_m`` sind Paare ``((ost0, nord0), (ost1, nord1))`` in Metern relativ zum Bezug.
    Zurueck kommen Bild, Bahnliste und die eingesetzte Wahrheit.

    Bewusst mit eigener Trigonometrie und festen Metergraden: Der Test soll pruefen, ob das
    Modul eine eingesetzte Geometrie wiederfindet -- nicht, ob es mit sich selbst
    uebereinstimmt.

    Das Blatt muss gross genug sein, dass die GEDREHTEN Bahnen samt Randsaum hineinpassen.
    Sonst liegen ihre Enden am Papierrand, das Modul verwirft sie als abgeschnitten (was
    richtig ist), und es bleiben zu wenige Passpunkte -- beim ersten Anlauf genau so
    passiert und faelschlich fuer einen Modulfehler gehalten.
    """
    mitte = (groesse[0] / 2.0, groesse[1] / 2.0)
    w = math.radians(drehung_grad)

    def nach_pixel(ost, nord):
        # Meter -> Bild: drehen und skalieren, y nach unten
        x = (ost * math.cos(w) - nord * math.sin(w)) / mps
        y = -(ost * math.sin(w) + nord * math.cos(w)) / mps
        return (mitte[0] + x, mitte[1] + y)

    striche = []
    bahnen = []
    for i, (p0, p1) in enumerate(bahnen_m):
        a = nach_pixel(*p0)
        b = nach_pixel(*p1)
        striche.append((a[0], a[1], b[0], b[1], max(4, int(round(breite_m / mps)))))
        bahnen.append(Bahn(
            name=f"{10 + i}/{28 + i}",
            le=(bezug[0] + p0[1] / _M_LAT, bezug[1] + p0[0] / _M_LON),
            he=(bezug[0] + p1[1] / _M_LAT, bezug[1] + p1[0] / _M_LON),
            laenge=math.hypot(p1[0] - p0[0], p1[1] - p0[1]),
            kurs=math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1])) % 360))
    return _blatt(striche, groesse=groesse, ton=ton), bahnen, {"drehung": drehung_grad,
                                                               "mps": mps}


# --------------------------------------------------------------------------- Bahnfarbe
def test_bahnfarbe_wird_gemessen_nicht_festgelegt():
    """Flugplatzkarte 153, Rollkarte 179 -- der Ton ist keine Konstante des Formats."""
    assert ground_charts.bahnfarbe(_blatt([(100, 400, 1300, 400, 28)])) == 153
    assert ground_charts.bahnfarbe(_blatt([(100, 400, 1300, 400, 28)], ton=179)) == 179


def test_ohne_bahnfarbe_kommt_none():
    """Ein Blatt ohne grosse mittelgraue Flaeche ist keine Flugplatzkarte."""
    assert ground_charts.bahnfarbe(Image.new("L", (1400, 800), 255)) is None


# --------------------------------------------------------------------------- Flaechen
def test_zwei_parallelbahnen_werden_getrennt_gefunden():
    im = _blatt([(100, 300, 1300, 300, 28), (100, 520, 1300, 520, 28)])
    assert len(ground_charts.bahnflaechen(im, TON)) == 2


def test_gebaeude_in_anderer_farbe_zaehlen_nicht_mit():
    im = _blatt([(100, 400, 1300, 400, 28)])
    assert len(ground_charts.bahnflaechen(im, TON)) == 1


# --------------------------------------------------------------------------- Achse
def test_achswinkel_stimmt_auf_ein_zehntel_grad():
    """Der Winkel ist die verlaesslichste Groesse der Kette -- an echten Blaettern stimmten
    die Achsen zweier Parallelbahnen auf 0,01 bis 0,06 Grad ueberein."""
    im = _blatt([(150, 620, 1250, 420, 28)])
    a = ground_charts.hauptachse(ground_charts.bahnflaechen(im, TON)[0])
    soll = math.degrees(math.atan2(-200, 1100))
    assert math.degrees(a.winkel_rad) == pytest.approx(soll, abs=0.2)


def test_abzweig_verkuerzt_die_flaeche_das_tasten_holt_es_zurueck():
    """Rollwegabzweige trennen die Flaeche; gemessene Laengen fielen bis zu 24 Prozent zu
    kurz aus. Bei EDDL hob das Tasten 1414 px auf die richtigen 1769 px."""
    im = _blatt([(150, 400, 1250, 400, 28)])
    z = ImageDraw.Draw(im)
    z.rectangle((690, 380, 730, 420), fill=255)          # weisse Luecke mitten in der Bahn
    flaechen = ground_charts.bahnflaechen(im, TON, mindest=2000)
    groesste = max(flaechen, key=lambda f: sum(b - x + 1 for _, x, b in f))
    a = ground_charts.hauptachse(groesste)
    assert a.laenge < 1000                               # die Flaeche allein ist zu kurz
    ground_charts.enden_tasten(im, TON, a, mps_grob=2.0)
    assert a.gueltig
    assert a.voll == pytest.approx(1100, abs=60)         # getastet stimmt es wieder


def test_tasten_schiesst_nicht_ueber_das_bahnende_hinaus():
    """Ein zweites Stueck weit hinter dem Ende darf nicht angeschlossen werden."""
    im = _blatt([(150, 400, 700, 400, 28)])
    z = ImageDraw.Draw(im)
    z.line((950, 400, 1300, 400), fill=TON, width=28)    # 250 px = 500 m entfernt
    flaechen = ground_charts.bahnflaechen(im, TON, mindest=2000)
    groesste = max(flaechen, key=lambda f: sum(b - x + 1 for _, x, b in f))
    a = ground_charts.hauptachse(groesste)
    ground_charts.enden_tasten(im, TON, a, mps_grob=2.0)
    assert a.voll == pytest.approx(550, abs=60)


def test_querrollweg_verbindet_den_scan_nicht():
    """Ein 23-m-Rollweg quer ueber die verlaengerte Achse einer 45-m-Bahn deckt 51 Prozent.

    Bei der urspruenglichen Schwelle von 55 Prozent stand die Grenze ohne
    Sicherheitsabstand direkt daneben; schraeg kreuzend oder mit Schultern laege er
    darueber. Deshalb 70 Prozent.
    """
    im = _blatt([(150, 400, 700, 400, 28)])
    z = ImageDraw.Draw(im)
    z.line((760, 300, 760, 500), fill=TON, width=14)     # Rollweg quer, halbe Bahnbreite
    flaechen = ground_charts.bahnflaechen(im, TON, mindest=2000)
    groesste = max(flaechen, key=lambda f: sum(b - x + 1 for _, x, b in f))
    a = ground_charts.hauptachse(groesste)
    ground_charts.enden_tasten(im, TON, a, mps_grob=2.0)
    assert a.voll == pytest.approx(550, abs=70)


# --------------------------------------------------------------------------- Pruefkette
def test_die_rechnung_findet_die_eingesetzte_geometrie_wieder():
    im, bahnen, soll = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((-1200, -200), (1200, -200)), ((-1350, 250), (1350, 250))])
    p = ground_charts.passung_rechnen(im, bahnen)
    assert p is not None
    assert p.mps == pytest.approx(1.69, rel=0.05)
    assert p.rest_max < ground_charts.REST_SCHRANKE_M
    assert p.bahnen == 2


def test_ohne_y_spiegelung_gaebe_es_keine_loesung():
    """Bildkoordinaten laufen nach unten, Nordmeter nach oben. Die Matrix [[a,-b],[b,a]]
    hat die Determinante a^2+b^2 > 0, ist also immer orientierungserhaltend -- die wahre
    Abbildung ist es nicht und laege ohne Spiegelung gar nicht im Suchraum. Die Vorabprobe
    lieferte dann 59 m statt 5,7 m fuer dasselbe Blatt.
    """
    import inspect
    import re

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts._versuch))
    assert "(x, -y)" in quelle


def test_kopfueber_wird_verworfen():
    """Zwei gleich lange Parallelbahnen sind unter 180 Grad symmetrisch; der Restfehler
    kann das nicht unterscheiden. Bei EDDM waehlte die Rechnung ohne diese Bedingung
    173,5 statt der richtigen 353,5 Grad, bei gleich kleinem Restfehler."""
    im, bahnen, _ = _kunstblatt(drehung_grad=-6.5, mps=2.58, bahnen_m=[
        ((-1900, -300), (1900, -300)), ((-1900, 300), (1900, 300))])
    p = ground_charts.passung_rechnen(im, bahnen)
    assert p is not None
    assert not (ground_charts.NORDUNG_VERWERFEN[0] < p.drehung
                < ground_charts.NORDUNG_VERWERFEN[1])


def test_das_nordungsfenster_laesst_neunzig_grad_durch():
    """EDDH liegt bei gemessenen 89,97 Grad -- 0,03 neben einer strengen Kante bei (90,270),
    und das Achsrauschen betraegt 0,01 bis 0,06 Grad. Ein strenges Fenster entschiede dort
    per Muenzwurf. Der Fall ist nicht exotisch: Er trifft jedes quer gedruckte Blatt."""
    assert ground_charts.NORDUNG_VERWERFEN[0] > 90.0
    assert ground_charts.NORDUNG_VERWERFEN[1] < 270.0


def test_eine_bahn_allein_reicht_nicht():
    """Zwei Punkte bestimmen die Passung exakt und lassen keinen Restfehler uebrig -- sie
    ist dann unpruefbar, nicht richtig. Betrifft EDDB, EDDC, EDDE, EDDG, EDDR, EDDW."""
    im, bahnen, _ = _kunstblatt(drehung_grad=0.0, mps=2.0,
                                bahnen_m=[((-1300, 0), (1300, 0))])
    assert ground_charts.passung_rechnen(im, bahnen) is None


def test_ohne_referenzbahnen_kommt_none():
    im = _blatt([(150, 400, 1250, 400, 28)])
    assert ground_charts.passung_rechnen(im, []) is None


def test_massstabspruefung_greift_auch_bei_einer_messbaren_bahn():
    """Der Prototyp verglich die Bahnskalen nur untereinander und schaltete sich damit
    still ab, sobald nur eine Bahn unverstuemmelt war. Verglichen wird jetzt gegen die
    Skala aus dem Fit."""
    import inspect
    import re

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts._versuch))
    assert "fit_skala" in quelle
    assert "len(skalen)" not in quelle


def test_die_schranke_ist_ueber_die_bahnlaenge_gestaffelt():
    """Der Malfehler an den Enden ist additiv, sein Anteil also umgekehrt proportional zur
    Laenge: 120 m Anbau sind an 1630 m 7,4 Prozent, an 3000 m nur 4,0. Eine feste
    Prozentschranke verwirft bevorzugt richtige Passungen kurzer Bahnen."""
    kurz = max(ground_charts.SKALA_MINDESTSPIEL,
               ground_charts.SKALA_GRUNDFEHLER_M / 1630.0)
    lang = max(ground_charts.SKALA_MINDESTSPIEL,
               ground_charts.SKALA_GRUNDFEHLER_M / 4000.0)
    assert kurz > lang


# --------------------------------------------------------------------------- Nordung
def test_gedrehtes_blatt_waechst_und_bekommt_durchsichtige_ecken():
    """expand=True laesst an den Ecken Flaeche frei; bei 37 Grad ist das rund die Haelfte
    des Rechtecks. Weiss gefuellt laege ein grosses Dreieckspaar halbdeckend ueber der
    Umgebung des Platzes."""
    im, bahnen, _ = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((-1200, -200), (1200, -200)), ((-1350, 250), (1350, 250))])
    p = ground_charts.passung_rechnen(im, bahnen)
    assert p is not None
    gedreht, grenzen = ground_charts.norden(_png(im), p)
    neu = Image.open(io.BytesIO(gedreht))
    assert neu.mode == "RGBA"
    assert neu.size[0] > im.size[0] and neu.size[1] > im.size[1]
    assert neu.getpixel((0, 0))[3] == 0                  # Ecke durchsichtig, nicht weiss


def test_grenzen_sind_richtig_orientiert():
    im, bahnen, _ = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((-1200, -200), (1200, -200)), ((-1350, 250), (1350, 250))])
    p = ground_charts.passung_rechnen(im, bahnen)
    _, g = ground_charts.norden(_png(im), p)
    assert g["nord"] > g["sued"] and g["ost"] > g["west"]


def test_feldgrenzen_sind_die_bahnhuelle_nicht_die_blattgrenzen():
    """Die Verwechslung von Blatt- und Feldgrenzen steckte hinter dem
    45-Prozent-Massstabsfehler der Sichtflugkarten. Nach dem Drehen zeigt das Blatt viel
    freie Flaeche -- ueber der duerfte die Automatik nicht schon einschalten."""
    im, bahnen, _ = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((-1200, -200), (1200, -200)), ((-1350, 250), (1350, 250))])
    p = ground_charts.passung_rechnen(im, bahnen)
    _, g = ground_charts.norden(_png(im), p)
    assert g["feld_nord"] < g["nord"] and g["feld_sued"] > g["sued"]
    assert g["feld_west"] > g["west"] and g["feld_ost"] < g["ost"]


def test_die_drehung_wird_gegen_den_uhrzeigersinn_angewandt():
    """Image.rotate dreht gegen den Uhrzeigersinn. Ob 322,8 oder 37,2 uebergeben wird,
    entscheidet ueber ein exakt falsch herum liegendes Blatt."""
    import inspect
    import re

    quelle = re.sub(r"#[^\n]*", "", inspect.getsource(ground_charts.norden))
    assert "rotate(-p.drehung" in quelle


def test_analyse_laeuft_auf_dem_rohblatt():
    """mps ist Meter je Pixel im ROHblatt. Das Drehen ist der letzte Schritt und aendert an
    der Passung nichts -- BICUBIC verschmiert die Grautoene, eine Analyse danach waere
    schlechter."""
    im, bahnen, soll = _kunstblatt(drehung_grad=-37.2, mps=1.69, bahnen_m=[
        ((-1200, -200), (1200, -200)), ((-1350, 250), (1350, 250))])
    p = ground_charts.passung_rechnen(im, bahnen)
    assert p.mps == pytest.approx(soll["mps"], rel=0.05)
