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
    """Im Kniebrett haelt kein Browser-Speicher ueber einen Sim-Neustart."""
    stelle = RUMPF.index("_GROUND_PREF_KEY")
    block = RUMPF[stelle:stelle + 900]
    assert "_prefSchreib" in block and "_prefLies" in block
    assert "localStorage" not in block

# Der Admin-Teil (offene Punkte, Flugplatzkarten passen) ist mit dem Rueckbau (31.08.2026)
# in die vereinigte Maske "AIP Charts DFS" aufgegangen. Siehe tests/test_charts_dfs_ui.py.
