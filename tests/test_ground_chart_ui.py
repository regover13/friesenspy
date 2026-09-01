"""Die Ebene "Flugplatzkarte" im Frontend.

Quelltext-Tests binden an Deklarationen, nicht an Kommentare -- eine freie Suche faende
sonst die Erklaerung statt der Anweisung.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 10
"""
from __future__ import annotations

import re
from pathlib import Path

QUELLE = (Path(__file__).resolve().parents[1] / "app" / "static"
          / "index.html").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


RUMPF = _ohne_kommentare(QUELLE)


def test_die_ebene_ist_eingehaengt():
    assert "liveOverlays['Flugplatzkarte'] = _groundGruppe" in RUMPF


def test_der_zustand_wird_doppelt_gefuehrt():
    """Die Sichtflugkarte EDDL und die Flugplatzkarte EDDL tragen DIESELBE ICAO.

    Mit geteilten Variablen machte ein Wegklick der einen die andere unerreichbar, und die
    Sperre fiele nie, weil beide Automatiken dasselbe Blatt wollen.
    """
    for name in ("_groundAktiv", "_groundFest", "_groundAus", "_groundOverlay",
                 "_groundMarken"):
        assert re.search(rf"(let|const)\s+{name}\b", RUMPF), name


def test_engere_hysterese_als_bei_der_sichtflugkarte():
    """0,02 Grad sind rund 2 km -- groesser als mancher Flugplatz."""
    m = re.search(r"_GROUND_HYSTERESE\s*=\s*([0-9.]+)", RUMPF)
    a = re.search(r"_AIP_KARTE_HYSTERESE\s*=\s*([0-9.]+)", RUMPF)
    assert m and a
    assert float(m.group(1)) < float(a.group(1))


def test_sichtflugkarte_tritt_NICHT_mehr_zurueck():
    """Umgekehrt seit dem 31.08.2026: Die Platzkarte legt sich per zIndex UEBER die
    Sichtflugkarte, statt sie zu verdraengen (Nutzerentscheidung "die Platzkarte soll auf
    der Karte immer ueber der Sichtflugkarte liegen").

    Der Grund ist die Flaeche: Ein um 37 Grad gedrehtes Blatt wird als achsenparalleles
    Rechteck abgelegt, dessen Ecken durchsichtig sind -- bei EDDL rund die Haelfte. Die
    fuellt jetzt die Sichtflugkarte darunter, nicht die nackte Grundkarte.

    Ausfuehrlich getestet in tests/test_charts_dfs_ui.py.
    """
    assert "_groundVerdecktSichtflug" not in RUMPF


def test_die_sichtflugkarte_schlaegt_die_flugplatzkarte_NICHT_mehr():
    """Umgekehrt seit dem 31.08.2026. Die Regel war noetig, solange die Flugplatzkarte die
    Sichtflugkarte VERDRAENGTE: Wer eine Sichtflugkarte festgenagelt hatte, sollte sie nicht
    still verlieren.

    Seit die Platzkarte per zIndex darueber liegt, ist sie nicht nur ueberfluessig, sondern
    schaedlich -- sie stand VOR der _groundFest-Pruefung und ueberstimmte damit sogar ein
    ausdrueckliches Festnageln der Flugplatzkarte: Antippen blendete sie ein, der naechste
    Positionstakt nahm sie eine Sekunde spaeter wieder weg (Nutzer-Fund an EDDL).
    """
    stelle = RUMPF.index("function _groundNachfuehren")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert "_aipKarteFest" not in block


def test_marke_ist_blau_und_hohl():
    """Blau wie das Vorbild -- die Farbregel des Projekts haelt Blau fuer Klickbares frei,
    und diese Marke ist klickbar. Hohl, weil sie UEBER dem Platz liegt: Ein Vollsymbol
    deckte genau die Stelle zu, auf die es ankommt."""
    m = re.search(r"\.ground-marke rect\s*\{([^}]*)\}", QUELLE)
    assert m
    regel = m.group(1)
    assert "fill: rgba(" in regel                 # durchscheinend, nicht deckend
    assert "#2d9cdb" in regel                     # dieselbe Farbe wie .aip-marke


def test_die_beiden_marken_unterscheiden_sich_in_der_form():
    """Bei gleicher Farbe traegt die Form die Unterscheidung: hochkantes Blatt mit
    Textzeilen gegen liegendes Rechteck mit Quer- und Laengsstrichen."""
    aip = re.search(r"_aipMarkeIcon[\s\S]{0,700}?</svg>", RUMPF)
    ground = re.search(r"_groundMarkeIcon[\s\S]{0,700}?</svg>", RUMPF)
    assert aip and ground
    assert aip.group(0) != ground.group(0)


def test_die_marken_liegen_nicht_exakt_uebereinander():
    """Beide Markensaetze liegen ueber demselben Platz; ohne Versatz waere die untere nicht
    anklickbar."""
    stelle = RUMPF.index("function _groundMarkenAnpassen")
    block = RUMPF[stelle:stelle + 1400]
    assert re.search(r"lat\s*-\s*0\.\d+", block)


def test_sse_laedt_beide_kartenarten_neu():
    stelle = RUMPF.index("_aipKartenLaden(true)")
    assert "_groundKartenLaden(true)" in RUMPF[stelle:stelle + 200]


def test_merker_ohne_localstorage():
    """Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart.

    Gebunden an die beiden Funktionen selbst, nicht an ein Zeichenfenster hinter
    ``_GROUND_PREF_KEY``: Das Fenster mass frueher 900 Zeichen und zerbrach, sobald jemand
    zwischen Schluessel und Funktionen etwas einfuegte -- ohne dass am Merker etwas falsch
    gewesen waere.
    """
    schreib = re.search(r"function _saveGroundPref\([^)]*\)\s*\{[^}]*\}", RUMPF)
    lies = re.search(r"function _loadGroundPref\([^)]*\)\s*\{[^}]*\}", RUMPF)
    assert schreib and lies
    assert "_prefSchreib(_GROUND_PREF_KEY" in schreib.group(0)
    assert "_prefLies(_GROUND_PREF_KEY" in lies.group(0)
    assert "localStorage" not in schreib.group(0) + lies.group(0)

# Der Admin-Teil (offene Punkte, Flugplatzkarten passen) ist mit dem Rueckbau (31.08.2026)
# in die vereinigte Maske "AIP Charts DFS" aufgegangen. Siehe tests/test_charts_dfs_ui.py.


# ---------------------------------------------------- Hauptschalter aus dem Admin
#
# Der Server liefert bei ausgeschalteter Ebene keine Bodenblaetter mehr. Das Frontend muss
# daraufhin auch den EINTRAG aus der Ebenen-Auswahl nehmen -- ein Haken, hinter dem nichts
# liegt, sieht aus wie ein Fehler und war genau der Anlass fuer den Schalter.

def test_der_hauptschalter_wird_aus_der_antwort_gelesen():
    assert "flugplatzkarte_aktiv" in RUMPF


def test_die_liste_wird_beim_start_geholt():
    """Ohne diesen Abruf erfaehrt die Seite den Schalter nie: ``_groundNachfuehren`` steigt
    aus, solange die Ebene AUS ist, und laedt die Liste dann auch nicht. Der tote Eintrag
    bliebe genau in dem Fall stehen, fuer den es den Schalter gibt."""
    stelle = RUMPF.index("const liveEbenen = L.control.layers(")
    assert "_groundKartenLaden(" in RUMPF[stelle:stelle + 2000]


def test_das_stilllegen_ueberschreibt_die_nutzerwahl_nicht():
    """``map.removeLayer`` loest ``overlayremove`` aus. Ungebremst schriebe das die
    gemerkte Nutzer-Wahl auf AUS -- schaltet der Admin die Ebene spaeter wieder frei,
    bliebe sie beim Nutzer trotzdem verschwunden, ohne dass er es veranlasst hat."""
    stelle = RUMPF.index("function _groundEbeneAnwenden")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert "_groundEbeneStilllegen = true" in block
    stelle2 = RUMPF.index("liveMap.on('overlayremove'")
    haken = RUMPF[stelle2:stelle2 + 400]
    assert "_groundEbeneStilllegen" in haken and "_saveGroundPref(false)" in haken


def test_der_eintrag_verschwindet_aus_der_ebenen_auswahl():
    stelle = RUMPF.index("function _groundEbeneAnwenden")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert "removeLayer(_groundGruppe)" in block


# ------------------------------------- Zwei Bodenkarten an einem Platz (Nutzerentscheidung)

def test_die_rollkarte_hat_vorrang_vor_der_flugplatzkarte():
    """Liegen beide ueber der Position, gewinnt die Rollkarte: Am Boden braucht man
    Rollwege und Positionen, nicht die Uebersicht.

    Vorher entschied allein, welcher FELDMITTELPUNKT naeher liegt. Bei zwei Blaettern
    desselben Platzes liegen die praktisch aufeinander -- die Wahl haette also Zentimeter
    entschieden und konnte beim Rollen umschlagen.
    """
    stelle = RUMPF.index("function _groundNachfuehren")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert "_groundRang" in block, "keine Vorrangregel im Auswahlschritt"
    # Die Regel selbst steht in _groundRang -- dort muss die Rollkarte den kleineren Rang
    # haben, denn der kleinere gewinnt.
    rang = re.search(r"function _groundRang\(k\)\s*\{[^}]*\}", RUMPF)
    assert rang and "'rollkarte' ? 0" in rang.group(0)


def test_der_rang_steht_vor_dem_abstand():
    """Sonst schlaegt ein zufaellig naeherer Mittelpunkt den Vorrang wieder."""
    stelle = RUMPF.index("function _groundNachfuehren")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert block.index("_groundRang(k)") < block.index("if (d(k) < d(treffer))")


def test_zwei_bodenkarten_eines_platzes_bekommen_getrennte_marken():
    """Der Versatz von 0,004 Grad trennt Boden- von Sichtflugkarten, nicht zwei Bodenkarten
    voneinander -- die laegen exakt uebereinander und die untere waere nicht antippbar."""
    stelle = RUMPF.index("function _groundMarkenAnpassen")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert "_groundDoppelt" in block


def test_der_versatz_greift_nur_wo_es_wirklich_zwei_gibt():
    """109 der 111 Plaetze haben genau eine Bodenkarte. Deren Marke darf nicht wandern."""
    stelle = RUMPF.index("function _groundMarkenAnpassen")
    block = RUMPF[stelle:RUMPF.index("\n}", stelle)]
    assert "> 1" in block
