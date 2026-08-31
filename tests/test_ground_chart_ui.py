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


def test_sichtflugkarte_tritt_zurueck_wenn_ein_blatt_liegt():
    """Bedingung ist "ein Blatt LIEGT", nicht "die Position ist im Feld": Ist die Ebene
    Flugplatzkarte abgehakt, bliebe sonst beim Rollen gar keine Karte uebrig."""
    assert "_groundVerdecktSichtflug" in RUMPF
    stelle = RUMPF.index("function _aipKarteNachfuehren")
    block = RUMPF[stelle:stelle + 1600]
    assert "_groundVerdecktSichtflug()" in block


def test_festgenagelte_sichtflugkarte_schlaegt_die_automatik():
    """Ein ausdruecklicher Nutzerbefehl darf nicht still ueberstimmt werden."""
    stelle = RUMPF.index("function _groundNachfuehren")
    block = RUMPF[stelle:stelle + 900]
    assert "_aipKarteFest" in block


def test_marke_ist_magenta_und_hohl():
    """Hohl wie das Vorbild und aus demselben Grund: Sie liegt UEBER dem Platz, ein
    Vollsymbol deckte genau die Stelle zu, auf die es ankommt."""
    m = re.search(r"\.ground-marke rect\s*\{([^}]*)\}", QUELLE)
    assert m
    regel = m.group(1)
    assert "fill: rgba(" in regel                 # durchscheinend, nicht deckend
    assert "#2d9cdb" not in regel                 # nicht die Farbe der Sichtflugkarte
    assert "#e05fd0" in regel                     # magenta


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


# ---------------------------------------------------------------------------
# Admin: offene Punkte und Flugplatzkarten
# ---------------------------------------------------------------------------
ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static"
         / "admin.html").read_text(encoding="utf-8")
ADMIN_RUMPF = _ohne_kommentare(ADMIN)


def test_admin_zeigt_offene_kartenpunkte():
    assert "loadAipVorschlaege" in ADMIN_RUMPF
    assert "/api/admin/aip-vorschlaege" in ADMIN_RUMPF
    assert "vorschlagUebernehmen" in ADMIN_RUMPF
    assert "vorschlagVerwerfen" in ADMIN_RUMPF


def test_verwerfen_geht_per_post_nicht_per_delete():
    """Ein DELETE waere wirkungslos -- der naechste Wochenlauf faende denselben
    quell_hash und legte den Vorschlag sofort wieder an."""
    stelle = ADMIN_RUMPF.index("async function vorschlagVerwerfen")
    block = ADMIN_RUMPF[stelle:stelle + 400]
    assert "'POST'" in block and "'DELETE'" not in block


def test_leere_vorschlagsliste_wird_ganz_verborgen():
    """Eine dauerhaft leere Ueberschrift ist ein Reiz, den niemand braucht."""
    stelle = ADMIN_RUMPF.index("async function loadAipVorschlaege")
    block = ADMIN_RUMPF[stelle:stelle + 1200]
    assert "display = 'none'" in block


def test_uebernehmen_fragt_nach():
    """Es ersetzt eine von Hand gesetzte Passung -- der einzige Weg, auf dem das ueberhaupt
    geschehen darf."""
    stelle = ADMIN_RUMPF.index("async function vorschlagUebernehmen")
    block = ADMIN_RUMPF[stelle:stelle + 400]
    assert "confirm(" in block


def test_admin_zeigt_den_restfehler_in_der_liste():
    """Er ist die einzige Zahl, an der ein Mensch von aussen erkennt, ob eine automatische
    Passung sitzt -- also gehoert er sichtbar in die Liste."""
    stelle = ADMIN_RUMPF.index("async function loadGroundCharts")
    block = ADMIN_RUMPF[stelle:stelle + 2200]
    assert "rest_max" in block
    assert "Restfehler" in block


def test_admin_zaehlt_offene_punkte():
    stelle = ADMIN_RUMPF.index("async function loadGroundCharts")
    block = ADMIN_RUMPF[stelle:stelle + 2200]
    assert "offen" in block
