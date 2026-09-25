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
    # #44 Punkt 10: `laeuft` und `vorbei_seit_s` kommen vom Server, nicht von der Geraeteuhr.
    liste = [
        {"id": 1, "laeuft": True, "vorbei_seit_s": None},            # laeuft
        {"id": 2, "laeuft": False, "vorbei_seit_s": 81000},          # vor 22,5 h zu Ende
        {"id": 3, "laeuft": False, "vorbei_seit_s": 400000},         # alt
        {"id": 4, "laeuft": True, "vorbei_seit_s": None},            # laeuft auch
        {"id": 5, "laeuft": False, "vorbei_seit_s": None},           # kommt erst
    ]
    q = _funktion("_reddungZuZeigen")
    assert _node(q, f"_reddungZuZeigen({json.dumps(liste)}, null)") == [1, 2, 4]
    assert _node(q, f"_reddungZuZeigen({json.dumps(liste)}, 3)") == [1, 2, 3, 4]
    assert _node(q, "_reddungZuZeigen([], null)") == []


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
         "laeuft": False, "vorbei_seit_s": 50000,
         "stand": {"anteil": 0.42, "abgedeckt": 672, "zellen": 1600, "kante_km": 1.0,
                   "flaeche_km2": 672.0,
                   "sektor": {"sued": 53.54, "west": 6.95, "nord": 53.9, "ost": 7.55},
                   "gefunden": {"cid": 1, "name": "Stefan", "ts": "2026-09-24T19:12:00Z"},
                   "aufgenommen": {"cid": 2, "name": "Wolfgang", "ts": "2026-09-24T19:30:00Z"},
                   "eingeliefert": {"cid": 2, "name": "Wolfgang", "icao": "EDWF",
                                    "ts": "2026-09-24T19:50:00Z"},
                   "dauer_min": 38,
                   "je_pilot": [{"cid": 1, "name": "Stefan", "zellen": 400},
                                {"cid": 3, "name": "Nur Doppelt", "zellen": 0}]}}
    text = _node(_funktion("_reddungZeitfenster") + _funktion("_reddungTeilenText"), f"_reddungTeilenText({json.dumps(r)})")
    assert "FriesenReddung" in text and "Vermisst über der Jade" in text
    assert "42 %" in text and "672 km²" in text
    assert "Stefan um 19:12 UTC" in text and "EDWF" in text and "38 Minuten" in text
    assert "Stefan (400 Zellen)" in text and "Nur Doppelt" not in text
    for zahl in ("53.54", "6.95", "53.9", "7.55"):
        assert zahl not in text, f"Koordinate {zahl} im Teilen-Text"


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_der_teilen_text_unterscheidet_noch_nicht_und_nicht_gefunden():
    r = {"id": 3, "name": "X", "laeuft": True, "vorbei_seit_s": None,
         "stand": {"anteil": 0.1, "abgedeckt": 10, "zellen": 100, "kante_km": 1.0,
                   "flaeche_km2": 10.0, "je_pilot": []}}
    q = _funktion("_reddungZeitfenster") + _funktion("_reddungTeilenText")
    assert "Noch nicht gefunden" in _node(q, f"_reddungTeilenText({json.dumps(r)})")
    r.update(laeuft=False, vorbei_seit_s=3600)
    danach = _node(q, f"_reddungTeilenText({json.dumps(r)})")
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
              "var _reddungMeinStatus = null;\n"
              + _funktion("_reddungBalken") + _funktion("_reddungMarkenHtml")
              + _funktion("_reddungStatusZeile") + _funktion("_reddungBannerBlock"))
    r = {"id": 2, "name": "Probe", "stand": {"anteil": 0.5, "offen": 10, "kante_km": 1.0,
                                             "offen_km2": 9.6,
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


# --- Aufnehmen und Einliefern sind derselbe Pilot (Nutzer, 25.09.2026) ------------------

_MARKEN = {"gefunden": {"cid": 1, "name": "Stefan", "ts": "2026-09-24T19:12:00Z"},
           "aufgenommen": {"cid": 2, "name": "Wolfgang", "ts": "2026-09-24T19:30:00Z"},
           "eingeliefert": {"cid": 2, "name": "Wolfgang", "icao": "EDWF",
                            "ts": "2026-09-24T19:50:00Z"}}


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_die_marken_nennen_den_retter_nur_einmal():
    """*„Aufnehmendem und Einlieferndem? Das ist doch immer derselbe"* -- ja: Der Poller setzt
    `eingeliefert_von` ausnahmslos auf `aufgenommen_von` (eingeliefert wird durch dessen
    Landung). Zweimal denselben Namen zu nennen, liest sich wie zwei Leute."""
    quelle = "function escHtml(s){return String(s);}\n" + _funktion("_reddungMarkenHtml")
    html = _node(quelle, f"_reddungMarkenHtml({json.dumps(_MARKEN)})")
    assert html.count("Wolfgang") == 1 and "EDWF" in html and "19:50" in html
    assert "Stefan" in html


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_der_teilen_text_nennt_den_retter_nur_einmal():
    r = {"id": 3, "name": "X", "laeuft": False, "vorbei_seit_s": 50000,
         "stand": {"anteil": 0.4, "abgedeckt": 4, "zellen": 10, "kante_km": 1.0,
                   "flaeche_km2": 4.0, "je_pilot": [], **_MARKEN}}
    text = _node(_funktion("_reddungZeitfenster") + _funktion("_reddungTeilenText"), f"_reddungTeilenText({json.dumps(r)})")
    assert text.count("Wolfgang") == 1 and "EDWF" in text and "19:50" in text



# --- #44: Nachbesserungen im Frontend -----------------------------------------------------

def test_zur_karte_wartet_auf_die_karte():
    """#44 Punkt 2: Nach festen 300 ms entfiel `fitBounds` still, wenn die Karte noch nicht
    stand. Jetzt wie `switchToMapAndCenter`: bis zu 20 × 100 ms warten."""
    rumpf = _ohne_kommentare(_funktion("reddungAufKarte"))
    assert re.search(r"for \(let (\w+) = 0; \1 < 20\b", rumpf), "keine Warteschleife"
    assert "setTimeout(r, 100)" in rumpf and "setTimeout(r, 300)" not in rumpf


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_die_ebene_steht_vor_dem_verkehr():
    """#44 Punkt 3: `addOverlay` haengt ans Ende -- hinter „Verkehr", der laut Nutzerwahl ganz
    unten stehen soll."""
    q = _funktion("_ebeneVorEinsortieren")
    layers = [{"name": "OpenAIP"}, {"name": "Verkehr"}, {"name": "FriesenReddung", "id": "x"}]
    erg = _node(q, f"(() => {{ const l = {json.dumps(layers)}; "
                   f"_ebeneVorEinsortieren(l, l[2], 'Verkehr'); return l.map(e => e.name); }})()")
    assert erg == ["OpenAIP", "FriesenReddung", "Verkehr"]
    ohne = _node(q, "(() => { const l = [{name: 'A'}, {name: 'B'}]; "
                    "_ebeneVorEinsortieren(l, l[1], 'Verkehr'); return l.map(e => e.name); })()")
    assert ohne == ["A", "B"], "ohne Verkehr-Eintrag bleibt alles, wie es ist"
    abgleich = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    assert "_ebeneVorEinsortieren(" in abgleich and "_liveEbenenControl._update()" in abgleich


def test_nur_die_juengste_antwort_zaehlt():
    """#44 Punkt 4: Eine aeltere Liste oder ein spaetes Raster durfte eine neuere Antwort
    ueberschreiben."""
    takt = _ohne_kommentare(_funktion("_reddungTakt"))
    assert "++_reddungTaktNr" in takt and "!== _reddungTaktNr" in takt
    raster = _ohne_kommentare(_funktion("_reddungRasterHolen"))
    assert "_reddungRasterNr" in raster
    assert "_reddungZuZeigen(_reddungListe, _reddungGeoeffnetId).includes(id)" in raster


def test_der_rahmen_folgt_dem_sektor():
    """#44 Punkt 5: Nach einer Admin-Aenderung zeigte der Rahmen den alten Sektor."""
    assert "z.rahmen.setBounds(" in _ohne_kommentare(_funktion("_reddungZeichnen"))


def test_die_flaeche_kommt_vom_server():
    """#44 Punkt 8: genau gerechnet auf dem Server -- nicht mehr Zellen × Kante² im Browser."""
    assert "st.offen_km2" in _funktion("_reddungBannerBlock")
    assert "st.flaeche_km2" in _funktion("_reddungBilanzHtml")
    assert "st.flaeche_km2" in _funktion("_reddungTeilenText")
    for name in ("_reddungBannerBlock", "_reddungBilanzHtml", "_reddungTeilenText"):
        assert "kante * kante" not in _funktion(name), name


def test_die_bilanz_hat_eine_adresse():
    """#44 Punkt 9: Ohne eigenen URL-Zustand oeffnete ein Neuladen, was vorher in der Adresse
    stand -- etwa einen Kutter."""
    assert "setUrlState({ tab: 'events', reddung:" in _funktion("openReddungDetail")
    start = _ohne_kommentare(_funktion("initFromUrl"))
    assert "p.get('reddung')" in start and "openReddungDetail(" in start


def test_eine_fehlende_reddung_laesst_keine_alte_bilanz_stehen():
    """#44 Punkt 9: Fehlte das Event in der Liste, blieb der Inhalt der vorher offenen Bilanz."""
    rumpf = _ohne_kommentare(_funktion("_reddungBilanzZeigen"))
    assert "_reddungListeGeladen" in rumpf and "gibt es nicht mehr" in _funktion("_reddungBilanzZeigen")


def test_die_geraeteuhr_entscheidet_nichts_mehr():
    """#44 Punkt 10: „läuft" und „vorbei" kommen vom Server."""
    assert "r.laeuft" in _funktion("_reddungBannerZeigen")
    code = _ohne_kommentare(INDEX)
    assert "_jetztIso" not in code, "die Geraeteuhr wird fuer die FriesenReddung nicht mehr gebraucht"


def test_das_raster_wird_nur_bei_sichtbarer_karte_geholt():
    """#44 Punkt 11: Wer zum LIVE-Tab zurueckging, holte weiter alle 30 s das Raster."""
    rumpf = _ohne_kommentare(_funktion("_reddungKarteAbgleichen"))
    assert "getElementById('tab-karte')" in rumpf and "classList.contains('active')" in rumpf


def test_die_neuen_zustaende_stehen_vor_dem_ersten_aufruf():
    erster_aufruf = INDEX.index("setInterval(_reddungTakt, 30000)")
    for name in ("let _reddungTaktNr", "const _reddungRasterNr", "let _reddungListeGeladen"):
        assert INDEX.index(name) < erster_aufruf, name


def test_die_bilanz_zeigt_die_spuren_des_abends():
    """Nutzer, 25.09.2026: „zeigt keine tracks an". Wie beim Kutter: Formular der
    Event-Analyse mit Platz, Radius und Zeitfenster fuellen und suchen."""
    rumpf = _ohne_kommentare(_funktion("openReddungDetail"))
    for stueck in ("getElementById('ev-icao').value", "getElementById('ev-radius').value",
                   "getElementById('ev-start').value", "getElementById('ev-end').value",
                   ".analyse", "searchEvents();"):
        assert stueck in rumpf, stueck
    assert rumpf.index("await _reddungTakt()") < rumpf.index("searchEvents();")


@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_die_spuren_ziehen_den_blick_nicht_von_der_bilanz_weg():
    """Nutzer, 25.09.2026: „das soll aber auf das Event scrollen und nicht auf die Tracks!
    Wie bei Bummel und Kutter!" renderEventsResults() scrollt am Ende zu seinen Ergebnissen --
    ausser eine dieser Ansichten ist offen. Die Bedingung wird hier ausgewertet, nicht gesucht."""
    rumpf = _ohne_kommentare(_funktion("renderEventsResults"))
    m = re.search(r"if \((.+?)\) \{?\s*results\.scrollIntoView", rumpf)
    assert m, "Scroll zu den Ergebnissen fehlt"
    bedingung = m.group(1)

    def scrollt(bummel, kutter, reddung):
        return _node(f"let _activeBummel = {bummel}, _kutterOpenId = {kutter}, "
                     f"_reddungOffenId = {reddung};", f"!!({bedingung})")

    assert scrollt("null", "null", "null") is True       # freie Suche: zu den Ergebnissen
    assert scrollt("{}", "null", "null") is False        # Bummel
    assert scrollt("null", "3", "null") is False         # Kutter
    assert scrollt("null", "null", "7") is False         # Reddung


# --- Das Eventende steht dabei (Nutzer, 25.09.2026: „event Ende steht niergens") ----------

@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_das_zeitfenster_nennt_beginn_und_ende():
    q = _funktion("_reddungZeitfenster")
    gleich = _node(q, "_reddungZeitfenster({dtstart: '2026-09-25T17:00:00Z', dtend: '2026-09-25T17:52:00Z'})")
    assert gleich == "25.09.2026, 17:00–17:52 UTC"
    ueber = _node(q, "_reddungZeitfenster({dtstart: '2026-09-25T21:00:00Z', dtend: '2026-09-26T00:30:00Z'})")
    assert ueber == "25.09.2026, 21:00 – 26.09.2026, 00:30 UTC", "ueber Mitternacht beide Daten"


def test_bilanz_live_block_und_teilen_text_nennen_das_ende():
    assert "_reddungZeitfenster(r)" in _funktion("_reddungBilanzHtml")
    assert "_reddungZeitfenster(r)" in _funktion("_reddungTeilenText")
    block = _ohne_kommentare(_funktion("_reddungBannerBlock"))
    assert "Ende ${" in block and "r.dtend" in block


# --- Eigener Stand: VATSIM und FriesenBruegge, dauerhaft sichtbar (25.09.2026) ------------
#
# „was passiert, wenn einer die Meldung ungeduldig wegklickt. Woher weiß er dann, dass die
# Brücke meldet?" -- bis dahin: gar nicht. Der Hinweis erschien nur, wenn etwas FEHLTE, und
# weggeklickt blieb er fuer das ganze Event weg.

@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_die_statuszeile_sagt_was_fehlt_und_bestaetigt_wenn_alles_da_ist():
    q = _funktion("_reddungStatusZeile")
    ok = _node(q, "_reddungStatusZeile({laeuft: true, bruegge: true, vatsim: true})")
    assert "Du bist dabei" in ok
    ohne_vatsim = _node(q, "_reddungStatusZeile({laeuft: true, bruegge: false, vatsim: false})")
    assert "nicht gewertet" in ohne_vatsim and "VATSIM" in ohne_vatsim
    ohne_bruegge = _node(q, "_reddungStatusZeile({laeuft: true, bruegge: false, vatsim: true})")
    assert "FriesenBrügge" in ohne_bruegge and "VATSIM" not in ohne_bruegge.split("nicht gewertet")[1]
    assert _node(q, "_reddungStatusZeile(null)") == ""
    assert _node(q, "_reddungStatusZeile({laeuft: false})") == ""


def test_der_live_block_zeigt_den_eigenen_stand():
    """Nicht wegklickbar: Er steht im Block, solange die FriesenReddung laeuft."""
    block = _ohne_kommentare(_funktion("_reddungBannerBlock"))
    assert "_reddungStatusZeile(_reddungMeinStatus)" in block
    assert INDEX.index("let _reddungMeinStatus") < INDEX.index("setInterval(_reddungTakt, 30000)")


def test_der_hinweis_nennt_vatsim_und_kommt_bei_neuem_zustand_wieder():
    rumpf = _funktion("_reddungHinweisPruefen")
    assert "VATSIM" in rumpf
    code = _ohne_kommentare(rumpf)
    assert "_reddungMeinStatus = d" in code and "_reddungBannerZeigen()" in code
    # Weggeklickt gilt fuer Event UND Zustand -- aendert sich, was fehlt, kommt er wieder.
    assert "d.vatsim" in code and "d.bruegge" in code
    weg = _ohne_kommentare(_funktion("_reddungHinweisWeg"))
    assert "dataset.zustand" in weg


# --- Fundort auf der Event-Karte nach dem Ende (#50, 25.09.2026) --------------------------

@pytest.mark.skipif(not _NODE, reason="node fehlt")
def test_die_event_karte_kennt_den_fundort_nur_bei_offener_bilanz():
    """Der Server liefert `fundort` erst nach dem Eventende. Die Karte zeigt ihn nur, wenn
    genau diese Reddung offen ist -- eine freie Event-Suche danach bekommt keine Marke."""
    quelltext = _funktion("_reddungFundort")
    liste = ("[{id: 3, fundort: {lat: 53.7, lon: 7.2}, "
             "stand: {gefunden: {name: 'Pilot X', ts: '2026-09-25T19:01:39Z'}}}, "
             "{id: 4, fundort: null, stand: {}}]")
    def fundort(offen):
        return _node(f"let _reddungListe = {liste}, _reddungOffenId = {offen};\n"
                     "function escHtml(s) { return s; }\n" + quelltext, "_reddungFundort()")
    ort = fundort("3")
    assert ort["lat"] == 53.7 and ort["lon"] == 7.2
    assert "Pilot X" in ort["text"] and "19:01 UTC" in ort["text"]
    assert fundort("4") is None, "ohne Fundort vom Server keine Marke"
    assert fundort("null") is None, "freie Event-Suche: keine Marke"
    # Nicht gefunden: der Ort kommt trotzdem (Nutzerentscheidung 25.09.2026), und die Marke
    # sagt, dass ihn niemand fand.
    liste2 = "[{id: 5, fundort: {lat: 53.7, lon: 7.2}, stand: {}}]"
    ort = _node(f"let _reddungListe = {liste2}, _reddungOffenId = 5;\n"
                "function escHtml(s) { return s; }\n" + quelltext, "_reddungFundort()")
    assert ort["lat"] == 53.7 and "nicht gefunden" in ort["text"]


def test_die_event_karte_setzt_die_marke_und_nimmt_sie_in_den_ausschnitt():
    rumpf = _ohne_kommentare(_funktion("renderEventsMap"))
    assert "_reddungFundort()" in rumpf
    i = rumpf.index("_reddungFundort()")
    assert i < rumpf.index("eventsMap.fitBounds(bounds"), "der Ausschnitt muss ihn enthalten"
    assert "bounds.push([fo.lat, fo.lon])" in rumpf


def test_die_readme_nennt_den_fundort():
    assert "Fundort" in README
