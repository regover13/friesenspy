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


# ------------------------------------------------------------- Hauptschalter der Ebene

def test_der_hauptschalter_der_platzkarten_ebene_steht_im_admin():
    assert 'id="dfs-ebene-toggle"' in ADMIN


def test_der_hauptschalter_spricht_seinen_endpunkt_an():
    assert "'/api/admin/aip-charts-dfs/ebene'" in ADMIN_RUMPF


def test_der_hauptschalter_wird_aus_dem_serverzustand_gezeichnet():
    """Sonst steht der Haken nach jedem Neuladen auf 'an', egal was gilt -- und der Admin
    schaltet aus Versehen wieder frei."""
    assert "ebene_aktiv" in ADMIN_RUMPF


def test_der_hauptschalter_nennt_beide_bodensorten():
    """Wer 'Flugplatzkarte' liest und Rollkarten weiter erwartet, wundert sich. Im
    Kniebrett haengen beide an demselben Eintrag."""
    stelle = ADMIN.index('id="dfs-ebene-toggle"')
    umfeld = ADMIN[stelle - 400:stelle + 700]
    assert "Rollkarte" in umfeld


# ------------------------------------------------------------ Vorschau der Passung

def test_die_vorschau_bringt_leaflet_mit():
    """Ohne Kartenbibliothek keine Vorschau. Sie war beim Rueckbau herausgeflogen, weil
    nichts sie mehr benutzte."""
    assert "leaflet@1.9.4/dist/leaflet.css" in ADMIN
    assert "leaflet@1.9.4/dist/leaflet.js" in ADMIN


def test_die_vorschau_hat_einen_platz():
    assert 'id="dfs-vorschau"' in ADMIN
    assert 'id="dfs-vorschau-karte"' in ADMIN


def test_die_vorschau_legt_das_blatt_wie_das_kniebrett_auf():
    """Dieselbe Eckenreihenfolge wie in index.html: [[sued, west], [nord, ost]]. Vertauscht
    faellt das Blatt an die falsche Stelle -- und die Vorschau spraeche einer richtigen
    Passung ihre Richtigkeit ab."""
    assert re.search(r"grenzen\s*=\s*\[\[\s*k\.sued\s*,\s*k\.west\s*\]\s*,"
                     r"\s*\[\s*k\.nord\s*,\s*k\.ost\s*\]\s*\]", ADMIN_RUMPF)
    assert re.search(r"L\.imageOverlay\(\s*k\.bild\s*,\s*grenzen\b", ADMIN_RUMPF)


def test_die_vorschau_zeigt_die_beiden_passpunkte():
    """Der Sinn der Vorschau: Liegt das Blatt schief, sieht man an den Marken sofort, ob
    ein Klick danebensass oder die Koordinate falsch war."""
    assert "p1_lat" in ADMIN_RUMPF and "p2_lat" in ADMIN_RUMPF


def test_die_vorschau_laesst_sich_durchsichtig_stellen():
    """Ohne Regler liegt das Blatt deckend auf dem Luftbild -- man sieht dann gerade das
    nicht, wogegen man vergleichen will."""
    assert 'id="dfs-vorschau-deckkraft"' in ADMIN


# --------------------------------------------- Passen-Maske: Reihenfolge, Klicks, Sekunden

def test_die_maske_steht_in_der_reihenfolge_vorschau_blatt_parameter():
    """Nutzerwunsch 01.09.2026, zweimal nachgeschaerft: Vorschau, Kartenblatt, Parameter.
    Die beiden anklickbaren Flaechen liegen damit beieinander, statt die Werte dazwischen
    zu haben."""
    kasten = ADMIN[ADMIN.index('<div id="dfs-passen"'):ADMIN.index('<!-- ERKENNUNGSLÜCKEN')]
    assert (kasten.index('id="dfs-vorschau"')
            < kasten.index('id="dfs-blatt-box"')
            < kasten.index('class="dfs-punkte"'))


def test_die_koordinaten_lassen_sich_von_der_karte_abgreifen():
    """Auf dem Luftbild trifft man eine Bahnschwelle auf ein bis drei Meter genau -- die
    ARP-Koordinate im Blattkopf gibt nur rund 18 m her, und bei den Plaetzen, um die es
    geht, ist OurAirports selbst das Problem."""
    stelle = ADMIN_RUMPF.index("function _dfsKarteAufbauen")
    block = ADMIN_RUMPF[stelle:stelle + 1200]
    assert "_dfsKarte.on('click'" in block and "e.latlng.lat" in block and "_dfsGradSetzen" in block


def test_jeder_punkt_hat_grad_minuten_und_sekunden():
    """Ohne Sekundenfeld muss man die Sekunden im Kopf in Dezimalminuten umrechnen."""
    for p in ("p1", "p2"):
        for achse in ("lat", "lon"):
            for teil in ("grad", "min", "sek"):
                assert f'id="{p}-{achse}-{teil}"' in ADMIN


def test_der_winkel_addiert_grad_minuten_und_sekunden():
    stelle = ADMIN_RUMPF.index("function _dfsWinkel")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "'-sek'" in block and "3600" in block and "/ 60" in block


def test_der_zielpunkt_wird_gewaehlt_nicht_aus_der_klickzahl_hergeleitet():
    """Aus der Klickzahl hergeleitet trifft ein Klick den falschen Punkt, sobald vorbelegte
    Werte im Spiel sind -- und man sieht es erst an einer schiefen Karte."""
    assert 'name="dfs-ziel"' in ADMIN
    stelle = ADMIN_RUMPF.index("document.getElementById('dfs-blatt').addEventListener('click'")
    block = ADMIN_RUMPF[stelle:stelle + 900]
    assert "_dfsZiel()" in block
    assert "_dfsEcken" not in ADMIN_RUMPF, "der zweite Merker neben den Feldern ist fort"


def test_die_maske_bleibt_nach_dem_speichern_offen():
    """Nutzerwunsch: Vorschau zeigen, aber die Maske weiter anzeigen."""
    stelle = ADMIN_RUMPF.index("document.getElementById('dfs-save-btn')")
    # Nur der Speichern-Haken, nicht der Schliessen-Knopf dahinter -- der DARF verbergen.
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("dfs-abbrechen-btn", stelle)]
    assert "_dfsKarteFuellen" in block
    assert "dfs-passen').style.display = 'none'" not in block


def test_die_liste_blaettert_zu_zehnt():
    assert "DFS_PRO_SEITE = 10" in ADMIN_RUMPF
    stelle = ADMIN_RUMPF.index("function dfsListeZeichnen")
    block = ADMIN_RUMPF[stelle:stelle + 2600]
    assert ".slice(von, von + DFS_PRO_SEITE)" in block


def test_ein_engerer_filter_faengt_wieder_auf_seite_eins_an():
    """Sonst steht man hinter dem Ende und sieht eine leere Liste."""
    assert "function _dfsNeuFiltern() { _dfsSeite = 0;" in ADMIN_RUMPF
    assert "addEventListener('change', _dfsNeuFiltern)" in ADMIN_RUMPF
    assert "addEventListener('input', _dfsNeuFiltern)" in ADMIN_RUMPF


def test_die_maske_holt_zurueckgerechnete_punkte_fuer_auto_karten():
    """Die 68 auto-Karten tragen ein fertiges Rechteck, aber keine geklickten Punkte."""
    stelle = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    block = ADMIN_RUMPF[stelle:stelle + 2600]
    assert "/passhilfe" in block and "hilfe.punkte" in block


def test_die_drei_winkelfelder_duerfen_umbrechen():
    """Drei Felder je Achse statt zwei. Ohne Umbruch sprengt die Gruppe auf dem Telefon den
    Kasten, und der eingetragene Wert ist wieder unsichtbar abgeschnitten -- derselbe
    Fehler wie am 31.08.2026 bei EDKB, nur eine Spalte spaeter."""
    m = re.search(r"\.aip-gm\s*\{([^}]*)\}[\s\S]{0,600}?\.aip-gm\s*\{([^}]*)\}", ADMIN)
    assert "flex-wrap: wrap" in ADMIN[ADMIN.index(".aip-gm {"):ADMIN.index(".aip-gm {") + 2000]
    r = re.search(r"\.dfs-punkt \.aip-gm input\s*\{([^}]*)\}", ADMIN)
    assert r and "min-width" in r.group(1) and "max-width" in r.group(1)


def test_das_umschalten_haengt_am_selbst_gesetzten_nicht_am_gefuellten_feld():
    """Die erste Fassung fragte, ob die FELDER gefuellt sind. Bei einer vorbelegten Karte
    sind sie das immer -- also rueckte sie nie weiter, und man musste jedes Mal von Hand
    umschalten. Genau solche Karten bearbeitet man, seit die auto-Karten ihre Punkte
    mitbringen (Nutzer, 01.09.2026)."""
    stelle = ADMIN_RUMPF.index("function _dfsZielNachziehen")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "_dfsGesetzt[1].px" in block and "_dfsGesetzt[1].geo" in block
    assert "_dfsPunktKomplett" not in ADMIN_RUMPF, "die alte Bedingung ist fort"
    # Beide Haelften werden auch wirklich vermerkt.
    assert "_dfsGesetzt[n].px = true" in ADMIN_RUMPF
    assert "_dfsGesetzt[n].geo = true" in ADMIN_RUMPF
    # Und beim Oeffnen zurueckgesetzt, sonst rueckt die naechste Karte sofort weiter.
    stelle2 = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    assert "_dfsGesetztLeeren()" in ADMIN_RUMPF[stelle2:stelle2 + 1200]


def test_fadenkreuz_auch_ueber_der_vorschaukarte():
    """Eine Bahnschwelle im Luftbild trifft man nur auf wenige Meter, wenn man sieht, wo der
    Zeiger steht. Leaflets eigener Zeiger ist eine Greifhand."""
    assert 'id="dfs-vk-x"' in ADMIN and 'id="dfs-vk-y"' in ADMIN
    stelle = ADMIN_RUMPF.index("getElementById('dfs-vorschau-box')")
    block = ADMIN_RUMPF[stelle:stelle + 1200]
    assert "mousemove" in block and "mouseleave" in block
    # Leaflet setzt `cursor: grab` auf seinem Container -- das muss ueberstimmt werden.
    m = re.search(r"#dfs-vorschau-karte[^{]*\{([^}]*)\}", ADMIN)
    assert m and "crosshair" in m.group(1)


def test_die_maske_nennt_den_status_der_bearbeiteten_zeile():
    """Ein Platz hat bis zu DREI Zeilen -- Sichtflug-, Flugplatz- und Rollkarte. Am
    01.09.2026 sah es deshalb so aus, als bliebe eine frisch gepasste Karte auf "offen"
    stehen: gepasst war die Flugplatzkarte von EDAK, offen geblieben ist die Rollkarte
    daneben."""
    stelle = ADMIN_RUMPF.index("function _dfsKopfSetzen")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "_dfsStatusText" in block and "_dfsSorteText" in block


def test_nach_dem_speichern_wird_der_kopf_nachgezogen():
    stelle = ADMIN_RUMPF.index("document.getElementById('dfs-save-btn')")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("dfs-abbrechen-btn", stelle)]
    assert "_dfsKopfSetzen" in block


def test_der_hinweis_erklaert_das_verschwinden_aus_der_liste():
    """Der Filter 'gepasst' steht standardmaessig AUS. Die Zeile faellt beim Speichern also
    aus der Liste, statt sichtbar den Status zu wechseln -- das sieht aus, als sei nichts
    passiert."""
    # Der Vorgabezustand des Filters, an den der Hinweis gebunden ist:
    stelle = ADMIN.index('class="dfs-status-cb" value="gepasst"')
    assert "checked" not in ADMIN[stelle:stelle + 60], "Vorgabe geaendert -- Hinweis pruefen"
    stelle2 = ADMIN_RUMPF.index("document.getElementById('dfs-save-btn')")
    block = ADMIN_RUMPF[stelle2:ADMIN_RUMPF.index("dfs-abbrechen-btn", stelle2)]
    assert ".dfs-status-cb:checked" in block and "aus der Liste gefallen" in block


def test_die_seitenauswahl_kennt_die_sorte_der_zeile():
    """DER Fehler vom 01.09.2026: In den Sortenfeldern der Seitenauswahl stand immer
    "Sichtflugkarte", ohne jeden Bezug zur Zeile, aus der geklickt wurde -- und was dort
    stand, gewann. Wer aus "EDAK Rollkarte" heraus eine Seite waehlte, schrieb sie in die
    FLUGPLATZkarte, und die anschliessend geoeffnete Passen-Maske stand ebenfalls auf der
    falschen Sorte. Die Passung landete auf einem Blatt, das man nie angesehen hatte; die
    Rollkarte blieb offen und sah aus, als sei nichts gespeichert worden.
    """
    # Der Knopf traegt die Sorte seiner Zeile mit.
    stelle = ADMIN_RUMPF.index("data-dfs-seiten=")
    assert "escA(k.sorte || '')" in ADMIN_RUMPF[stelle:stelle + 300]
    # Und der Klickfaenger reicht sie durch.
    stelle2 = ADMIN_RUMPF.index("closest('button[data-dfs-seiten]')")
    assert "dfsSeiten(icao, sorte)" in ADMIN_RUMPF[stelle2:stelle2 + 300]
    # Die Funktion nimmt sie an ...
    assert "async function dfsSeiten(icao, sorte)" in ADMIN_RUMPF
    # ... und waehlt sie in den Auswahlfeldern vor.
    stelle3 = ADMIN_RUMPF.index("const opt = function (wert, text)")
    assert "wert === sorte ? ' selected' : ''" in ADMIN_RUMPF[stelle3:stelle3 + 400]


def test_die_sortenfelder_werden_aus_einer_stelle_gebaut():
    """Vorher standen die drei Optionen dreimal woertlich da -- einmal je Auswahlfeld. Eine
    Vorauswahl haette man dann an drei Stellen nachtragen muessen, und genau so entstehen
    Felder, die auseinanderlaufen."""
    assert ADMIN_RUMPF.count("<option value=\"flugplatzkarte\">") == 0
    assert "const sortenFeld = function" in ADMIN_RUMPF


# ------------------------------------------------------------- Filter merken

def test_die_filtereinstellung_wird_gemerkt():
    """Sonst stellt man Status und Sorte nach jedem Neuladen wieder von Hand ein."""
    assert "_dfsFilterMerken" in ADMIN_RUMPF and "_dfsFilterHolen" in ADMIN_RUMPF
    stelle = ADMIN_RUMPF.index("function _dfsNeuFiltern")
    assert "_dfsFilterMerken()" in ADMIN_RUMPF[stelle:stelle + 300]


def test_die_gemerkte_einstellung_darf_nicht_alles_ausblenden():
    """Ein Stand ohne einen einzigen Haken zeigte bei jedem Laden eine leere Liste, ohne
    erkennbaren Grund -- genau die Sorte Sackgasse, die am 01.09.2026 schon zweimal wie ein
    Datenverlust aussah."""
    stelle = ADMIN_RUMPF.index("function _dfsFilterHolen")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "length" in block, "kein Rückfall auf die Vorgabe"


def test_die_suche_wird_NICHT_gemerkt():
    """Eine vergessene ICAO-Suche laesst die Liste beim naechsten Oeffnen leer aussehen --
    und man sucht den Fehler in den Daten statt im Suchfeld."""
    stelle = ADMIN_RUMPF.index("function _dfsFilterMerken")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "dfs-suche" not in block


# ------------------------------------------------- Drehung: gerechnet statt getippt

def test_die_maske_zeigt_die_gerechnete_drehung():
    """Ein um 270 Grad gedruckt vorliegendes Blatt braucht KEINE Eingabe: Zwei richtig
    gesetzte Punkte liefern die Drehung von selbst. Ohne Anzeige sieht man das nicht und
    tippt sie ein -- und das tut etwas ganz anderes (s. naechster Test)."""
    assert 'id="dfs-drehung-berechnet"' in ADMIN
    assert "function _dfsDrehungBerechnet" in ADMIN_RUMPF


def test_die_gerechnete_drehung_benutzt_dieselbe_formel_wie_der_server():
    """Sonst zeigt die Maske eine andere Zahl an, als der Server spaeter speichert."""
    stelle = ADMIN_RUMPF.index("function _dfsDrehungBerechnet")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "Math.atan2" in block
    # meter_je_grad: dieselben Reihen wie app/runway_ref.py
    assert "111132.95" in ADMIN_RUMPF and "111412.84" in ADMIN_RUMPF


def test_das_drehfeld_sagt_was_es_wirklich_tut():
    """Es richtet das Blatt NICHT auf, es dreht die ganze Abbildung um Punkt 1 -- Punkt 2
    wandert dabei weg. Am 01.09.2026 gemeldet als "wenn ich das mache, passen die Punkte
    nicht und sie wird komplett versetzt"."""
    stelle = ADMIN.index('id="dfs-drehung"')
    umfeld = ADMIN[max(0, stelle - 700):stelle + 700]
    assert "Punkt 1" in umfeld and "überschreiben" in umfeld.lower()


def test_die_gerechnete_drehung_steht_schon_beim_oeffnen_da():
    """Sonst sieht man erst nach dem ersten Klick, dass die Drehung sich von selbst ergibt."""
    stelle = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    block = ADMIN_RUMPF[stelle:stelle + 2600]
    assert "_dfsDrehungAnzeigen()" in block


# ------------------------------------------------------------------ Blatt zoomen

def test_das_blatt_laesst_sich_zoomen():
    """Ein 3691 px breites Blatt auf Fensterbreite gequetscht heisst: ein Klick trifft vier
    Originalpixel auf einmal. Der Klick rechnet zwar auf die natuerliche Groesse um, aber
    genauer als die Anzeige kann er nicht werden."""
    assert 'id="dfs-blatt-zoom-plus"' in ADMIN and 'id="dfs-blatt-zoom-minus"' in ADMIN
    assert "function _dfsBlattZoom" in ADMIN_RUMPF


def test_der_zoom_setzt_die_breite_in_originalpixeln():
    """Ueber `max-width: 100%` waere jede Zoomstufe wieder auf Fensterbreite gedeckelt."""
    stelle = ADMIN_RUMPF.index("function _dfsBlattZoom")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "naturalWidth" in block
    assert "maxWidth" in block


def test_der_kasten_um_das_blatt_begrenzt_die_hoehe():
    """Ohne Deckel schiebt ein gezoomtes Blatt alles andere aus dem Bild -- und die
    Parameter stehen darunter."""
    m = re.search(r"\.aip-blatt-box\s*\{([^}]*)\}", ADMIN)
    assert m and "max-height" in m.group(1) and "overflow" in m.group(1)


def test_der_zoom_faengt_bei_jedem_blatt_neu_an():
    """Sonst steht das naechste, ganz anders grosse Blatt in einer sinnlosen Stufe."""
    stelle = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    assert "_dfsBlattZoom(" in ADMIN_RUMPF[stelle:stelle + 2600]


def test_die_hoehenbegrenzung_des_blattes_beschneidet_die_vorschau_nicht():
    """Der Vorschaukasten teilt sich die Klasse `.aip-blatt-box` mit dem Blatt -- er braucht
    daraus nur `position: relative` fuer das Fadenkreuz. Die beim Zoom eingefuehrte
    Hoehenbegrenzung haette die 840 px hohe Karte abgeschnitten."""
    stelle = ADMIN.index('id="dfs-vorschau-box"')
    zeile = ADMIN[stelle:ADMIN.index('>', stelle)]
    assert "max-height:none" in zeile


def test_das_drehfeld_wird_nicht_mit_null_vorbelegt():
    """Eine vorbelegte 0 ist nicht nur ueberfluessig, sie ist gefaehrlich: Steht im Feld
    etwas, ueberschreibt der Server damit die GERECHNETE Drehung. Jede offene Zeile traegt
    drehung=0.0, die Maske haette also bei jeder ein "0.0" angeboten -- und ein Speichern
    haette die Drehung auf null gezwungen (Nutzerfund 01.09.2026)."""
    stelle = ADMIN_RUMPF.index("async function dfsPassenStarten(")
    block = ADMIN_RUMPF[stelle:stelle + 3000]
    # Der ALTE Waechter -- "ist eine Zahl da? dann rein damit" -- muss fort sein.
    assert "typeof eintrag.drehung === 'number' ? eintrag.drehung" not in block, \
        "belegt weiterhin blind vor"
    assert "_dfsIstUeberschrieben" in block


def test_eine_wirklich_ueberschriebene_drehung_bleibt_stehen():
    """Sonst ginge sie beim naechsten Speichern verloren -- der Server rechnete sie dann
    aus den Punkten neu, und genau davon wich sie ja bewusst ab."""
    stelle = ADMIN_RUMPF.index("function _dfsIstUeberschrieben")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("\n    }", stelle)]
    assert "_dfsDrehungBerechnet" in block and "360" in block


def test_das_speichern_bietet_das_ergebnis_zum_korrigieren_an():
    """Das Ergebnis kommt ins Ueberschreib-Feld -- mit Absicht: Von dort aus korrigiert man
    es. Ich hatte die Zeile am 01.09.2026 als Fehler entfernt; der Nutzer arbeitet genau so
    ("Dann kann ich ja nicht mehr korrigieren?!") und sie kam zurueck.

    Die Kehrseite ist bekannt und sichtbar: Wer danach einen PUNKT verschiebt, bekommt seine
    neue Drehung von dem alten Wert im Feld ueberstimmt -- die Anzeige "berechnet:" daneben
    zeigt dann zwei verschiedene Zahlen.
    """
    stelle = ADMIN_RUMPF.index("document.getElementById('dfs-save-btn')")
    block = ADMIN_RUMPF[stelle:ADMIN_RUMPF.index("dfs-abbrechen-btn", stelle)]
    assert "dfs-drehung').value = erg.drehung" in block
