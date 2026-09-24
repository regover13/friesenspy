# -*- coding: utf-8 -*-
"""Die Nutzeransichten der FriesenReddung (Spec 2026-09-23).

Reine Funktionen werden in node ausgefuehrt (herausgeschnitten aus index.html), alles andere
an Bezeichnern im Code geprueft -- nie an Kommentaren.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
INDEX = (WURZEL / "app" / "static" / "index.html").read_text(encoding="utf-8")
README = (WURZEL / "README.md").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _funktion(name: str) -> str:
    """Den Quelltext einer Funktion auf oberster Ebene -- bis zur ersten `}` in Spalte 0."""
    m = re.search(rf"^(async )?function {re.escape(name)}\(", INDEX, flags=re.M)
    assert m, f"function {name} fehlt"
    return INDEX[m.start():INDEX.index("\n}\n", m.start()) + 3]


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _node(quelltext: str, ausdruck: str):
    skript = quelltext + "\nconsole.log(JSON.stringify(" + ausdruck + "));"
    erg = subprocess.run([_NODE, "-e", skript], capture_output=True, text=True, timeout=20)
    assert erg.returncode == 0, erg.stderr
    return json.loads(erg.stdout.strip().splitlines()[-1])


# --- Takt und Live-Block ------------------------------------------------------------------

def test_der_live_block_steht_ueber_bummel_und_kutter():
    """Eine laufende FriesenReddung ist die Lage mit der Uhr im Nacken."""
    live = INDEX[INDEX.index('<div id="tab-live"'):INDEX.index('<div id="tab-karte"')]
    assert live.index('id="reddung-banner"') < live.index('id="bummel-banner"')


def test_der_takt_laeuft_und_haelt_einen_aussetzer_aus():
    """Review-Fokus 5: Ist die Liste kurz nicht erreichbar, bleibt alles, wie es war --
    der Block darf nicht bei jedem Netzaussetzer verschwinden."""
    rumpf = _ohne_kommentare(_funktion("_reddungTakt"))
    assert "fetch('/api/reddung/events')" in rumpf
    fang = rumpf.index("catch")
    assert rumpf.index("return", fang) < rumpf.index("_reddungBannerZeigen()")
    assert "setInterval(_reddungTakt, 30000)" in INDEX
    assert "_reddungTakt();" in _funktion("alleDatenNeuLaden")


def test_die_zustaende_stehen_vor_dem_ersten_aufruf():
    """⚠ Ein `let` hinter seinem ersten Aufruf auf oberster Ebene legt die GANZE Seite lahm
    (TDZ) -- und `node --check` findet das nicht."""
    erster_aufruf = INDEX.index("setInterval(_reddungTakt, 30000)")
    assert INDEX.index("let _reddungListe") < erster_aufruf


def test_der_live_block_stapelt_mehrere_laufende():
    """Review-Fokus 2: Zwei gleichzeitig -- beide erscheinen, nicht nur die erste."""
    rumpf = _ohne_kommentare(_funktion("_reddungBannerZeigen"))
    assert ".map(_reddungBannerBlock).join('')" in rumpf


def test_der_live_block_liest_nur_die_liste():
    """Die Liste fuehrt keine Koordinate; das Raster gehoert der Karte."""
    for name in ("_reddungBannerZeigen", "_reddungBannerBlock", "_reddungMarkenHtml"):
        assert "/raster" not in _funktion(name), name


def test_die_readme_beschreibt_den_live_block():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "Noch nicht zu sehen" not in abschnitt, "die alte Ankuendigung muss weg"
    assert "**Was du davon siehst:**" in abschnitt
    liste = abschnitt[abschnitt.index("**Was du davon siehst:**"):]
    assert "**Live-Ansicht:**" in liste


# --- Kartenebene -----------------------------------------------------------------------

@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_zu_zeigen_sind_laufende_frische_und_die_geoeffnete():
    """Review-Fokus 2: zwei laufende gleichzeitig -- beide. Dazu, was vor weniger als 24 h
    endete, und die eine aus der Bilanz, gleich welchen Alters (Spec Abschnitt 4)."""
    liste = [
        {"id": 1, "dtstart": "2026-09-24T17:00:00Z", "dtend": "2026-09-24T20:00:00Z"},  # laeuft
        {"id": 2, "dtstart": "2026-09-23T17:00:00Z", "dtend": "2026-09-23T20:30:00Z"},  # vor 22,5 h zu Ende
        {"id": 3, "dtstart": "2026-09-20T17:00:00Z", "dtend": "2026-09-20T20:00:00Z"},  # alt
        {"id": 4, "dtstart": "2026-09-24T17:30:00Z", "dtend": "2026-09-24T21:00:00Z"},  # laeuft auch
        {"id": 5, "dtstart": "2026-09-25T17:00:00Z", "dtend": "2026-09-25T20:00:00Z"},  # kommt erst
    ]
    q = _funktion("_reddungZuZeigen")
    jetzt = '"2026-09-24T19:00:00Z"'
    assert _node(q, f"_reddungZuZeigen({json.dumps(liste)}, {jetzt}, null)") == [1, 2, 4]
    assert _node(q, f"_reddungZuZeigen({json.dumps(liste)}, {jetzt}, 3)") == [1, 2, 3, 4]
    assert _node(q, f"_reddungZuZeigen([], {jetzt}, null)") == []


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_laeufe_fassen_eine_zeile_zusammen_und_enden_am_rahmen():
    """Review-Fokus 3: Die letzte Zeile/Spalte ragt ueber den Sektor (aufgerundet) -- die
    Flaeche muss am Rahmen enden, nicht darueber hinaus."""
    raster = {"zeilen": 2, "spalten": 3, "d_lat": 0.01, "d_lon": 0.02}
    sektor = {"sued": 50.0, "west": 8.0, "nord": 50.015, "ost": 8.05}
    q = _funktion("_reddungLaeufe")
    ringe = _node(q, f"_reddungLaeufe(['z0_1','z0_0','z1_2'], {json.dumps(raster)}, {json.dumps(sektor)})")
    assert len(ringe) == 2
    assert [p for ring in ringe[:1] for pkt in ring for p in pkt] == pytest.approx(
        [50.0, 8.0, 50.0, 8.04, 50.01, 8.04, 50.01, 8.0])
    assert [p for ring in ringe[1:] for pkt in ring for p in pkt] == pytest.approx(
        [50.01, 8.04, 50.01, 8.05, 50.015, 8.05, 50.015, 8.04])
    luecke = _node(q, f"_reddungLaeufe(['z0_0','z0_2'], {json.dumps(raster)}, {json.dumps(sektor)})")
    assert len(luecke) == 2, "eine Luecke in der Zeile trennt die Laeufe"
    assert _node(q, f"_reddungLaeufe([], {json.dumps(raster)}, {json.dumps(sektor)})") == []


def test_kein_canvas_auf_dieser_karte():
    """⚠ liveMap laeuft mit leaflet-rotate, und das traegt den Canvas-Renderer nicht: Versatz,
    der sich je Zoomstufe verdoppelt (FSE-Ebenen bis 16.08.2026). Geprueft ueber den GANZEN
    Code ohne Kommentare -- dort steht die Warnung, im Code darf der Aufruf nie stehen."""
    assert "L.canvas" not in _ohne_kommentare(INDEX)
    rumpf = _ohne_kommentare(_funktion("_reddungZeichnen"))
    assert "renderer" not in rumpf


def test_die_flaeche_ist_ein_mehrfachpolygon():
    """Als flache Ringliste naehme Leaflet jeden Ring ab dem zweiten als LOCH des ersten."""
    rumpf = _ohne_kommentare(_funktion("_reddungZeichnen"))
    assert "ringe.map(r => [r])" in rumpf and "L.polygon(" in rumpf
    assert "setLatLngs(" in rumpf, "beim Nachladen ersetzen, nicht neu anlegen"


def test_die_ebene_haengt_sich_nachtraeglich_ein_und_wieder_aus():
    rumpf = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    assert "_liveEbenenControl.addOverlay(_reddungGruppe, 'FriesenReddung')" in rumpf
    assert "_liveEbenenControl.removeLayer(_reddungGruppe)" in rumpf


def test_eine_abwahl_haelt_bis_zum_neuladen():
    """Review-Fokus 4: Der naechste Takt darf eine abgewaehlte Ebene nicht wieder einschalten.
    Nur „Zur Karte" schaltet sie zurueck."""
    abgleich = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    assert "!_reddungAbgewaehlt" in abgleich
    assert "overlayremove" in abgleich and "_reddungSelbst" in abgleich
    assert "_reddungAbgewaehlt = false" in _funktion("reddungAufKarte")
    # Nicht gespeichert: kein Merker fuer diese Ebene.
    assert "_prefSchreib" not in abgleich


def test_abgelaufene_werden_einmal_geladen():
    rumpf = _ohne_kommentare(_funktion("_reddungRasterHolen"))
    assert "_reddungRasterFertig" in rumpf and "/raster" in rumpf


def test_die_karte_holt_sich_die_ebene_beim_oeffnen():
    """Sonst erscheint sie erst mit dem naechsten Takt, bis zu 30 s nach dem Oeffnen.

    ⚠ Verankert an `_vollbildWiederherstellen();` -- das steht genau einmal im Code und nur in
    diesem Handler. `if (tab === 'karte') {` steht zweimal (auch in `} else if (tab === …`)."""
    assert INDEX.count("_vollbildWiederherstellen();") == 1
    stelle = INDEX.index("_vollbildWiederherstellen();")
    davor = INDEX[INDEX.rindex("await initLiveMap();", 0, stelle):stelle]
    danach = INDEX[stelle:INDEX.index("refreshLiveData();", stelle)]
    assert "await initLiveMap();" in davor
    assert "_reddungKarteAbgleichen();" in danach


def test_die_kartenzustaende_stehen_vor_dem_ersten_aufruf():
    erster_aufruf = INDEX.index("setInterval(_reddungTakt, 30000)")
    for name in ("let _reddungGruppe", "let _reddungGeoeffnetId", "const _reddungZeichnung",
                 "const _reddungRasterFertig", "let _reddungAbgewaehlt", "let _reddungSelbst"):
        assert INDEX.index(name) < erster_aufruf, name


def test_die_legende_nennt_die_ebene_mit_eigenem_satz():
    start = INDEX.index('<div class="panel-title">Karten-Legende</div>')
    block = INDEX[start:INDEX.index("TAB: STATISTIKEN", start)]
    zeile = next(z for z in re.findall(r"<li>(.*?)</li>", block, re.S)
                 if "<strong>FriesenReddung</strong>" in z)
    satz = re.sub(r"<[^>]+>", "", zeile).split("—", 1)
    assert len(satz) == 2 and len(satz[1].strip()) > 15


def test_die_readme_beschreibt_die_karte():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "**Karte:**" in abschnitt
    layer = README[README.index("## 🗺️ Karten-Layer"):]
    assert "**FriesenReddung**" in layer[:layer.index("\n---")]


# --- Bilanz und Teilen -----------------------------------------------------------------

def test_die_eventliste_oeffnet_die_bilanz():
    """Bisher fiel der Klick bis _prefillEventForm durch und fuellte das Suchformular."""
    rumpf = _ohne_kommentare(_funktion("renderFriesenEvents"))
    assert "else if (ev.is_reddung) openReddungDetail(ev._reddungId);" in rumpf
    assert rumpf.index("openReddungDetail") < rumpf.index("_prefillEventForm(ev)")


def test_jede_andere_ansicht_schliesst_die_bilanz():
    for name in ("_prefillEventForm", "openBummel", "openKutterDetail"):
        assert "_reddungZu();" in _funktion(name), name
    suche = INDEX[INDEX.index("getElementById('events-search-btn').addEventListener"):]
    assert "_reddungZu();" in suche[:suche.index("searchEvents();")]


def test_die_bilanz_schliesst_die_anderen():
    rumpf = _funktion("openReddungDetail")
    for panel in ("bummel-results", "kutter-results", "events-results"):
        assert f"getElementById('{panel}').classList.add('hidden')" in rumpf, panel


def test_der_takt_frischt_die_offene_bilanz_auf():
    rumpf = _ohne_kommentare(_funktion("_reddungTakt"))
    assert rumpf.index("_reddungBannerZeigen()") < rumpf.index("_reddungBilanzZeigen()")


def test_die_bilanz_hat_ihr_panel_mit_teilen_knopf():
    ev = INDEX[INDEX.index('<div id="tab-events"'):]
    assert ev.index('id="kutter-results"') < ev.index('id="reddung-results"')
    assert 'onclick="copyReddungShareHeader(this)"' in ev


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_der_teilen_text_nennt_die_marken_und_keinen_ort():
    r = {"id": 3, "name": "Vermisst über der Jade", "dtend": "2026-09-24T20:00:00Z",
         "stand": {"anteil": 0.42, "abgedeckt": 672, "zellen": 1600, "kante_km": 1.0,
                   "sektor": {"sued": 53.54, "west": 6.95, "nord": 53.9, "ost": 7.55},
                   "gefunden": {"cid": 1, "name": "Stefan", "ts": "2026-09-24T19:12:00Z"},
                   "aufgenommen": {"cid": 2, "name": "Wolfgang", "ts": "2026-09-24T19:30:00Z"},
                   "eingeliefert": {"cid": 2, "name": "Wolfgang", "icao": "EDWF",
                                    "ts": "2026-09-24T19:50:00Z"},
                   "dauer_min": 38,
                   "je_pilot": [{"cid": 1, "name": "Stefan", "zellen": 400},
                                {"cid": 3, "name": "Nur Doppelt", "zellen": 0}]}}
    text = _node(_funktion("_reddungTeilenText"),
                 f"_reddungTeilenText({json.dumps(r)}, '2026-09-25T10:00:00Z')")
    assert "FriesenReddung" in text and "Vermisst über der Jade" in text
    assert "42 %" in text and "672 km²" in text
    assert "Stefan um 19:12 UTC" in text and "EDWF" in text and "38 Minuten" in text
    assert "Stefan (400 Zellen)" in text and "Nur Doppelt" not in text
    for zahl in ("53.54", "6.95", "53.9", "7.55"):
        assert zahl not in text, f"Koordinate {zahl} im Teilen-Text"


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_der_teilen_text_unterscheidet_noch_nicht_und_nicht_gefunden():
    r = {"id": 3, "name": "X", "dtend": "2026-09-24T20:00:00Z",
         "stand": {"anteil": 0.1, "abgedeckt": 10, "zellen": 100, "kante_km": 1.0,
                   "je_pilot": []}}
    q = _funktion("_reddungTeilenText")
    assert "Noch nicht gefunden" in _node(q, f"_reddungTeilenText({json.dumps(r)}, '2026-09-24T19:00:00Z')")
    danach = _node(q, f"_reddungTeilenText({json.dumps(r)}, '2026-09-24T21:00:00Z')")
    assert "Nicht gefunden" in danach and "Noch" not in danach


def test_die_zustaende_der_bilanz_stehen_vor_dem_ersten_aufruf():
    assert INDEX.index("let _reddungOffenId") < INDEX.index("setInterval(_reddungTakt, 30000)")


def test_die_readme_beschreibt_die_bilanz():
    abschnitt = README[README.index("## 🚨 FriesenReddung"):README.index("## 🔧 Verwaltung")]
    assert "**Events:**" in abschnitt and "Teilen" in abschnitt


# --- Behebungen aus dem Abschluss-Review (Opus + Fable, 24.09.2026) ------------------

@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_nach_der_rettung_steht_nicht_mehr_laeuft_gerade():
    """Review W1 (Opus): Nach der Einlieferung stand bis dtend weiter „läuft gerade" --
    bei Event 2 am 20.09.2026 waeren das 93 Minuten gewesen. Der Server behandelt ein
    aufgeloestes Event laengst nicht mehr als laufend (/api/me/reddung)."""
    quelle = ("function escHtml(s){return String(s);}\nfunction icon(){return '';}\n"
              + _funktion("_reddungBalken") + _funktion("_reddungMarkenHtml")
              + _funktion("_reddungBannerBlock"))
    r = {"id": 2, "name": "Probe", "stand": {"anteil": 0.5, "offen": 10, "kante_km": 1.0,
                                             "aufgeloest": True,
                                             "gefunden": {"name": "A", "ts": "2026-09-20T16:40:00Z"}}}
    html = _node(quelle, f"_reddungBannerBlock({json.dumps(r)})")
    assert "läuft gerade" not in html and "abgeschlossen" in html
    assert "noch offen" not in html, "nach der Aufloesung ist nichts mehr offen"
    r["stand"]["aufgeloest"] = False
    assert "läuft gerade" in _node(quelle, f"_reddungBannerBlock({json.dumps(r)})")


def test_aufgeloeste_raster_werden_nicht_mehr_nachgefragt():
    """Review W1: Nach der Aufloesung ist die Abdeckung eingefroren -- kein Abruf alle 30 s."""
    rumpf = _ohne_kommentare(_funktion("_reddungRasterHolen"))
    assert "stand.aufgeloest" in rumpf


def test_zur_karte_schaltet_die_moving_map_ab():
    """Review W2 (Opus): fitBounds aendert den Zoom, `_naviZoomt` verhindert das Abschalten,
    und die Karte springt eine Sekunde spaeter zurueck zum eigenen Flugzeug -- im Cockpit
    der Normalfall. Vorbild ist `_icaoSpringen`."""
    rumpf = _ohne_kommentare(_funktion("reddungAufKarte"))
    aus = rumpf.index("_movingMap = false;")
    assert aus < rumpf.index("fitBounds(")
    assert "_naviMerke(_NAVI_MOVING_KEY, false);" in rumpf and "_naviKnopfAnstrich();" in rumpf


def test_die_abwahl_endet_mit_dem_abend():
    """Review W3 (Opus) / G3 (Fable): Verschwindet der Eintrag mangels Reddung, gilt die Abwahl
    nicht fuer den naechsten Abend -- sonst stuende die Ebene dort still abgehakt, genau das,
    was die Spec mit „nicht speichern" vermeiden wollte."""
    rumpf = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    leer = rumpf[rumpf.index("if (!ids.length) {"):]
    leer = leer[:leer.index("return;")]
    assert "_reddungAbgewaehlt = false" in leer
