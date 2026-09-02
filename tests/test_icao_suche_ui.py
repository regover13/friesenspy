"""Das ICAO-Suchfeld auf der Live-Karte.

Wunsch von Engelhard Hinrichs (Forum, 02.09.2026): ein Feld, in das man eine Kennung
tippt, und die Karte springt hin -- auch nach KSPF, also weltweit.

Quelltext-Tests binden an Deklarationen, nicht an Kommentare -- eine freie Suche faende
sonst die Erklaerung statt der Anweisung.
"""
from __future__ import annotations

import re
from pathlib import Path

QUELLE = (Path(__file__).resolve().parents[1] / "app" / "static"
          / "index.html").read_text(encoding="utf-8")


def _ohne_kommentare(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


RUMPF = _ohne_kommentare(QUELLE)


def _block(name: str) -> str:
    stelle = RUMPF.index("function " + name)
    return RUMPF[stelle:RUMPF.index("\n}", stelle)]


def test_die_suche_haengt_an_der_live_karte():
    assert "_addIcaoSucheControl(liveMap)" in RUMPF


def test_es_gibt_ein_eigenes_tastenfeld():
    """Im Kniebrett laeuft die Seite in einem <iframe> der EFB-Shell; die
    Bildschirmtastatur des Simulators oeffnet nur `Coherent.trigger('FOCUS_INPUT_FIELD')`
    aus dem Host-Frame. Ein blosses Textfeld waere in VR unbedienbar."""
    zeichen = re.search(r"const\s+_ICAO_ZEICHEN\s*=\s*'([^']+)'", RUMPF)
    assert zeichen
    assert len(zeichen.group(1)) == 36           # A-Z und 0-9
    assert "_ICAO_ZEICHEN.charAt(i)" in _block("_addIcaoSucheControl")


def test_im_kniebrett_ist_das_feld_schreibgeschuetzt():
    """Dort gibt es keine Tastatur, die es fuellen koennte -- und ein Fokus im Panel faengt
    Tastendruecke ab, die sonst das Flugzeug steuern."""
    assert "_PANEL_MODUS ? ' readonly'" in _block("_addIcaoSucheControl")


def test_der_sprung_schaltet_moving_map_ab():
    """setView mit anderer Zoomstufe feuert zuerst 'zoomstart'; der Merker _naviZoomt nimmt
    genau diesen Fall von der ueblichen Abschaltung aus. Ohne die ausdrueckliche Abschaltung
    spraenge die Karte hin und eine Sekunde spaeter zum eigenen Flugzeug zurueck."""
    block = _block("_icaoSpringen")
    assert "_naviMerke(_NAVI_MOVING_KEY, false)" in block


def test_der_sprung_zoomt_niemanden_heraus():
    """Wer schon naeher dran ist, behaelt seine Stufe."""
    assert "Math.max(liveMap.getZoom(), _ICAO_ZOOM)" in _block("_icaoSpringen")


def test_die_langsamere_antwort_ueberschreibt_die_neuere_nicht():
    """'ED' und 'EDW' koennen in umgekehrter Reihenfolge zurueckkommen."""
    block = _block("_icaoSuchen")
    assert "++_icaoLauf" in block and "lauf !== _icaoLauf" in block


def test_treffer_ohne_position_werden_nicht_angeboten():
    block = _block("_icaoListeZeigen")
    assert "typeof t.lat === 'number'" in block


def test_erst_ab_zwei_zeichen_wird_gesucht():
    """Bei einem Zeichen liefert der Server 20 beliebige Treffer -- das ist keine Auswahl."""
    assert re.search(r"const\s+_ICAO_MIN_ZEICHEN\s*=\s*2", RUMPF)
    assert "_ICAO_MIN_ZEICHEN" in _block("_icaoSuchen")


def test_kein_zeichen_jenseits_von_ascii():
    """Coherent GT malt nichts jenseits von ASCII -- im Kniebrett stand statt des
    Gradzeichens einmal ein leeres Kaestchen ("038[] 6 kt", 23.08.2026). Loeschen und
    Schliessen sind deshalb als SVG gezeichnet, nicht als Zeichen gesetzt."""
    stelle = QUELLE.index("//  ICAO-SUCHE: einen Platz auf der Karte anspringen")
    abschnitt = QUELLE[stelle:QUELLE.index("//  SICHTFLUGKARTE ALS OVERLAY", stelle)]
    schlimm = [c for c in abschnitt if ord(c) > 127]
    assert not schlimm, schlimm
