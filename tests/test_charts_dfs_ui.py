"""Die Admin-Ansicht "AIP Charts DFS" im Quelltext.

Tests binden an Deklarationen, nicht an Kommentare -- eine freie Zeichenkettensuche faende
sonst den Kommentar statt die Anweisung.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import re
from pathlib import Path

ADMIN = (Path(__file__).resolve().parents[1] / "app" / "static"
         / "admin.html").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


# NUR den <script>-Inhalt von Kommentaren befreien, nicht die ganze Datei: Ein Attribut wie
# accept="image/*" (Musteranalyse-Upload, unverwandt) enthaelt woertlich "/*" und taeuscht
# dem naiven Muster ueber die GESAMTE Datei einen offenen Blockkommentar vor -- alles bis
# zum naechsten "*/" irgendwo im Dokument verschwaende dann unbemerkt.
_SCRIPT = max(re.findall(r"<script>(.*?)</script>", ADMIN, re.S), key=len)
ADMIN_RUMPF = _ohne_kommentare(_SCRIPT)


def test_grad_und_minuten_sind_getrennte_felder():
    """Auf dem Blatt steht 'N 47 Grad 51,53 Minuten'. Ein einzelnes Feld '(Grad)' verleitet
    dazu, 47.5153 einzutragen -- gemeint sind 47,859. Der Unterschied sind zwoelf
    Kilometer; am 24.08.2026 genau so passiert."""
    for feld in ("p1-lat-grad", "p1-lat-min", "p1-lon-grad", "p1-lon-min",
                 "p2-lat-grad", "p2-lat-min", "p2-lon-grad", "p2-lon-min"):
        assert 'id="' + feld + '"' in ADMIN


def test_klicks_werden_auf_die_natuerliche_bildgroesse_umgerechnet():
    """Der Server kennt Originalpixel, der Browser skaliert auf seine Anzeigebreite. Bei
    einem 3101 px breiten Blatt in einem 900 px breiten Kasten laege jeder Punkt um mehr
    als das Dreifache daneben."""
    stelle = ADMIN_RUMPF.index("getElementById('dfs-blatt').addEventListener")
    block = ADMIN_RUMPF[stelle:stelle + 800]
    assert "naturalWidth" in block and "naturalHeight" in block


def test_die_seitenauswahl_zeigt_kein_passt_haekchen():
    """Es war irrefuehrend: Dieselbe Automatik hat bei EDDK aus sechs Kapitelseiten die
    falsche gewaehlt (Nutzer, 24.08.2026)."""
    stelle = ADMIN_RUMPF.index("async function dfsSeiten(")
    block = ADMIN_RUMPF[stelle:stelle + 2500]
    assert "passt" not in block


def test_statusfilter_erlaubt_mehrfachauswahl():
    stelle = ADMIN.index("dfsFilterStatus")
    block = ADMIN[stelle:stelle + 1500]
    assert "checkbox" in block.lower()


def test_drehung_ist_ein_eigenes_feld():
    assert 'id="dfs-drehung"' in ADMIN


def test_die_bahnschwellen_helfen_beim_passen():
    """Auf diesem Weg sind die 68 Ground-Karten entstanden: Schwellenkoordinaten aus
    runways.csv abschreiben. Ohne die Anzeige haette runway_ref.bahnen() keinen
    Produktivaufrufer mehr -- 110 Zeilen toter Code mit zehn Tests dahinter."""
    stelle = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    block = ADMIN_RUMPF[stelle:stelle + 3000]
    assert "schwellen" in block.lower()


def test_die_seitenauswahl_kann_nicht_gefunden_festhalten():
    """Sonst kommt derselbe Platz beim naechsten Durchgang wieder -- und die Arbeitsliste
    bliebe dauerhaft rund 780 Eintraege lang, in denen nichts abhakbar ist."""
    stelle = ADMIN_RUMPF.index("async function dfsSeiten(")
    block = ADMIN_RUMPF[stelle:stelle + 3000]
    assert "nicht-gefunden" in block


def test_platz_ohne_zeile_heisst_nicht_nachgesehen():
    """Nicht 'nicht gefunden'. Der Unterschied ist, ob jemand nachgesehen hat."""
    assert "nicht nachgesehen" in ADMIN


def test_status_pruefen_zeigt_das_neue_blatt_mit_den_alten_klickpunkten():
    """Ersetzt eine maschinelle Ausschnittspruefung bewusst durch den Augenschein
    (Spec 5.4) -- die Maske zeigt beide Wege, uebernehmen und verwerfen."""
    stelle = ADMIN_RUMPF.index("async function dfsPruefenZeigen(")
    block = ADMIN_RUMPF[stelle:stelle + 1500]
    assert "roh.png" in block
    assert "dfs-uebernehmen-btn" in block and "dfs-verwerfen-btn" in block


def test_uebernehmen_und_verwerfen_gehen_ueber_die_neuen_endpunkte():
    stelle = ADMIN_RUMPF.index("dfs-uebernehmen-btn' ? 'uebernehmen' : 'verwerfen'")
    block = ADMIN_RUMPF[stelle:stelle + 400]
    assert "/uebernehmen" not in block and "/verwerfen" not in block  # ueber die Variable
    assert "+ weg" in block or "'/' + weg" in block


def test_passen_ruft_die_vereinigte_maske_fuer_beide_sorten():
    """Eine Maske, keine zwei -- der Unterschied zwischen Sichtflug- und Flugplatzkarte
    steckt im Server (Saum, Task 4b), nicht in zwei getrennten Formularen."""
    assert "async function dfsPassenStarten(icao, sorte)" in ADMIN_RUMPF
    assert "/api/admin/aip-charts-dfs/'" in ADMIN_RUMPF


def test_rohbild_kommt_aus_dem_neuen_pfad():
    """aip-chart-roh/{icao}/{sorte}.png, nicht mehr aip-ground-chart/{icao}.roh.png."""
    stelle = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    block = ADMIN_RUMPF[stelle:stelle + 800]
    assert "/aip-chart-roh/" in block


def test_alte_admin_funktionen_sind_fort():
    for alt in ("loadAipCharts", "loadGroundCharts", "loadAipVorschlaege",
               "vorschlagUebernehmen", "vorschlagVerwerfen", "groundPassen",
               "aipPassenStarten", "aipSeitenZeigen", "_aipEingaben", "_aipFelderSetzen"):
        assert alt not in ADMIN_RUMPF, alt


def test_kartenliste_ist_horizontal_scrollbar():
    """UI-Regel aus CLAUDE.md: breite Tabellen gehoeren in .table-wrap."""
    start = ADMIN.index('id="dfs-charts"')
    assert "table-wrap" in ADMIN[max(0, start - 400):start + 400]


def test_fadenkreuz_ueber_dem_kartenblatt():
    """Ohne die Linien schaetzt man beim Klicken, ob man auf der Rahmenlinie steht oder
    daneben -- der Fehler geht unmittelbar in die gerechnete Passung ein."""
    assert 'id="dfs-fk-x"' in ADMIN and 'id="dfs-fk-y"' in ADMIN
    stelle = ADMIN.index("getElementById('dfs-fk-x')")
    block = ADMIN[stelle:stelle + 1200]
    assert "mousemove" in block and "mouseleave" in block
    assert "img.getBoundingClientRect()" in block
