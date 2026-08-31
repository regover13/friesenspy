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


def test_die_passen_eingaben_koennen_auf_dem_telefon_nicht_zusammenquetschen():
    """Am 31.08.2026 gemeldet: "Auto passung von edkb. Keine Koordinaten!!?" -- die Werte
    STANDEN im DOM (Endpunkt und Fuellfunktion nachgemessen), aber die Felder lagen in
    einem fuenfspaltigen Tabellenraster ohne .table-wrap. Auf einem Telefon bleibt davon
    nach der Polsterung (8px 12px = 24px je Feld) keine Inhaltsbreite uebrig, und der
    eingetragene Wert ist unsichtbar abgeschnitten.

    Der Test bindet an die Struktur, nicht an das Aussehen: keine Tabelle, dafuer eine
    Mindestbreite je Feld.
    """
    stelle = ADMIN.index('id="p1-lat-grad"')
    umfeld = ADMIN[max(0, stelle - 1500):stelle]
    assert "<table" not in umfeld, "Passen-Eingaben stehen wieder in einer Tabelle"
    assert "dfs-punkte" in umfeld
    m = re.search(r"\.dfs-punkt input\s*\{([^}]*)\}", ADMIN)
    assert m, "keine Regel fuer .dfs-punkt input"
    assert "min-width" in m.group(1)
    # width:auto muss die 100-Prozent-Regel der allgemeinen input-Formatierung schlagen.
    assert "width: auto" in m.group(1)


def test_alle_eingabefelder_tragen_type_text():
    """Ohne ``type="text"`` greift die Themenregel ``input[type="text"]`` nicht -- das Feld
    erscheint dann in der Browser-Vorgabe (weiss auf dunklem Grund) und sieht aus, als
    gehoere es nicht dazu. So fielen die Bild-x/y-Felder am 31.08.2026 auf."""
    for feld in ("p1-x", "p1-y", "p2-x", "p2-y",
                 "p1-lat-grad", "p1-lat-min", "p2-lon-grad", "p2-lon-min"):
        stelle = ADMIN.index('id="' + feld + '"')
        assert 'type="text"' in ADMIN[max(0, stelle - 60):stelle], feld


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


# ---------------------------------------------------------------------------
# Task 8: Stapelung und Transparenzregler im Kniebrett (index.html)
# ---------------------------------------------------------------------------
INDEX = (Path(__file__).resolve().parents[1] / "app" / "static"
         / "index.html").read_text(encoding="utf-8")
INDEX_RUMPF = _ohne_kommentare(INDEX)


def test_die_platzkarte_liegt_ueber_der_sichtflugkarte():
    """Ein um 37 Grad gedrehtes Blatt wird als achsenparalleles Rechteck abgelegt, dessen
    Ecken durchsichtig sind -- bei EDDL rund die Haelfte der Flaeche. Darunter gehoert die
    Sichtflugkarte, nicht die nackte Grundkarte (Nutzerentscheidung 31.08.2026)."""
    z_sicht = int(re.search(r"_Z_SICHTFLUG\s*=\s*(\d+)", INDEX_RUMPF).group(1))
    z_platz = int(re.search(r"_Z_PLATZKARTE\s*=\s*(\d+)", INDEX_RUMPF).group(1))
    assert z_platz > z_sicht


def test_die_stapelung_haengt_nicht_an_der_einfuegereihenfolge():
    """bringToFront() kippt, sobald eine Karte nachgeladen wird -- etwa nach dem
    SSE-Ereignis, das den Kartenbestand neu holt."""
    assert "bringToFront" not in INDEX_RUMPF
    for name in ("_Z_SICHTFLUG", "_Z_PLATZKARTE"):
        assert re.search(rf"zIndex:\s*{name}", INDEX_RUMPF), name


def test_die_verdeckungslogik_ist_entfernt():
    """Mit ihr entfallen die drei Zustaende, die sie noetig gemacht hatte: festgenagelte
    Sichtflugkarte gegen anlaufende Automatik, abgehakte Ebene ohne Ersatz, geteilter
    Wegklick-Merker."""
    assert "_groundVerdecktSichtflug" not in INDEX_RUMPF


def test_der_deckkraftregler_erscheint_auch_bei_flugplatzkarten():
    """Er hing an _aipKarteAktiv; liegt eine Flugplatzkarte, ist der null und der Regler
    verschwand -- obwohl genau dann etwas zu regeln waere."""
    stelle = INDEX_RUMPF.index("function _aipDeckkraftAnzeigen")
    block = INDEX_RUMPF[stelle:stelle + 400]
    assert "_groundAktiv" in block


def test_der_regler_bedient_beide_overlays():
    """Mit demselben Wert -- zwei verschiedene waeren ein zweiter Regler, und im Cockpit
    ist ein Regler besser als zwei."""
    stelle = INDEX_RUMPF.index("function _aipDeckkraftSetzen")
    block = INDEX_RUMPF[stelle:stelle + 700]
    assert "_aipKarteOverlay" in block and "_groundOverlay" in block


def test_der_kartenzustand_haengt_an_icao_und_sorte():
    """Sichtflug- und Flugplatzkarte desselben Platzes tragen dieselbe ICAO. Sobald ein
    Platz Flugplatz- UND Rollkarte hat -- was der Rueckbau ermoeglicht --, ist der
    Schluessel mehrdeutig und find(k => k.icao === _groundFest) trifft die erste von
    zweien."""
    assert "function _groundSchluessel" in INDEX_RUMPF
    stelle = INDEX_RUMPF.index("function _groundSchluessel")
    assert "sorte" in INDEX_RUMPF[stelle:stelle + 200]
    assert "k.icao === _groundFest" not in INDEX_RUMPF
    assert "k.icao === _groundAktiv" not in INDEX_RUMPF


def test_die_flugplatzkarte_haengt_nicht_an_der_sichtflugkarte():
    """Beide Ebenen sind unabhaengig, seit die Platzkarte per zIndex darueber liegt.

    Bis 31.08.2026 stand in _groundNachfuehren
    ``if (_aipKarteFest) { _groundZeigen(null); return; }`` -- ein Rest aus der Zeit der
    Verdraengung. Er stand VOR der _groundFest-Pruefung und ueberstimmte damit sogar ein
    ausdrueckliches Festnageln der Flugplatzkarte: Antippen blendete sie ein, der naechste
    Positionstakt nahm sie eine Sekunde spaeter wieder weg (Nutzer-Fund an EDDL).
    """
    stelle = INDEX_RUMPF.index("function _groundNachfuehren")
    block = INDEX_RUMPF[stelle:INDEX_RUMPF.index("\n}", stelle)]
    assert "_aipKarteFest" not in block


def test_ein_festgenageltes_platzblatt_ueberlebt_den_naechsten_takt():
    """_groundFest muss VOR jeder Automatik greifen -- sonst ist Antippen wirkungslos."""
    stelle = INDEX_RUMPF.index("function _groundNachfuehren")
    block = INDEX_RUMPF[stelle:INDEX_RUMPF.index("\n}", stelle)]
    assert block.index("_groundFest") < block.index("_eigenePosition")


def test_beide_kartentypen_kommen_aus_einem_endpunkt():
    """Eine Tabelle, ein Endpunkt -- das Frontend filtert nach k.sorte, statt zwei
    Endpunkte zu befragen."""
    assert "/api/aip-charts-dfs" in INDEX_RUMPF
    assert "/api/aip-ground-charts" not in INDEX_RUMPF
    for name, bedingung in (("_aipKartenLaden", "=== 'sichtflug'"),
                            ("_groundKartenLaden", "!== 'sichtflug'")):
        stelle = INDEX_RUMPF.index("function " + name)
        assert bedingung in INDEX_RUMPF[stelle:stelle + 800], name
