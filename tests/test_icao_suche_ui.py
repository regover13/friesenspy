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
    reihen = re.search(r"const\s+_ICAO_TASTENREIHEN\s*=\s*\[([^\]]+)\]", RUMPF)
    assert reihen
    zeichen = "".join(re.findall(r"'([^']+)'", reihen.group(1)))
    assert len(zeichen) == 36                              # A-Z und 0-9, keins doppelt
    assert set(zeichen) == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def test_das_tastenfeld_ist_qwertz_mit_ziffernreihe():
    """Nutzerwunsch 02.09.2026. Alphabetisch waere kuerzer zu schreiben, aber niemand sucht
    Buchstaben alphabetisch."""
    reihen = re.findall(r"'([A-Z0-9]+)'", re.search(
        r"const\s+_ICAO_TASTENREIHEN\s*=\s*\[([^\]]+)\]", RUMPF).group(1))
    assert reihen == ['1234567890', 'QWERTZUIOP', 'ASDFGHJKL', 'YXCVBNM']


def test_das_tastenfeld_gibt_es_nur_im_kniebrett():
    """Am Schreibtisch liegt eine echte Tastatur vor dem Nutzer -- ein nachgebautes
    Tastenfeld waere dort nur im Weg (Nutzerwunsch 02.09.2026)."""
    block = _block("_addIcaoSucheControl")
    stelle = block.index("_ICAO_TASTENREIHEN[r]")
    davor = block[:stelle]
    assert "if (_PANEL_MODUS) {" in davor
    assert davor.rindex("if (_PANEL_MODUS) {") > davor.rindex("const box =")


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


def test_der_suchkasten_liegt_ueber_den_kartensymbolen():
    """Leaflet gibt seinen Ecken `z-index: 1000`, im Kniebrett steht eine davon sogar auf
    1100 (Ebenen-Auswahl, s. test_vr_panel). Mit demselben Rang lag der Kasten HINTER
    Ebenen-Auswahl, Kompass und Lupe -- im Kniebrett war das Eingabefeld halb verdeckt
    (Nutzer-Bild 02.09.2026).

    Verdecken ist hier richtig herum: Der Kasten ist nur offen, solange gesucht wird, und
    traegt sein eigenes X zum Schliessen -- an die Symbole kommt man also immer wieder
    heran. Ohne dieses X waere die Anhebung eine Falle."""
    m = re.search(r"\n    \.icao-box \{([^}]*)\}", QUELLE, re.S)
    assert m, ".icao-box nicht gefunden"
    rang = re.search(r"z-index: (\d+)", m.group(1))
    assert rang and int(rang.group(1)) > 1100, \
        "der Kasten muss ueber Leaflets angehobene Ecken (1100) hinaus"
    # Das X ist die Bedingung dafuer, dass er verdecken darf.
    assert 'class="icao-taste icao-zu"' in QUELLE
    assert "querySelector('.icao-zu').onclick" in QUELLE


def test_der_seitenzoom_wird_zurueckgeholt():
    """iOS zoomt beim Fokus in ein Eingabefeld in die Seite hinein und zoomt danach nicht von
    selbst zurueck. Im Kartenvollbild liegen die Schaltflaechen -- auch "Vollbild verlassen"
    -- danach ausserhalb des Bildes, und die Auszoom-Geste faengt Leaflet ab: Der Nutzer kam
    nur noch ueber einen Neustart der App heraus (Fund 02.09.2026, mit Bild)."""
    block = _block("_seitenZoomZurueck")
    assert "maximum-scale=1.0" in block
    # Die Sperre muss WIEDER WEG -- ein dauerhaftes maximum-scale=1 naehme jedem den
    # Zwei-Finger-Zoom auf der Karte.
    assert "setTimeout(" in block and "_viewportSetzen(_VIEWPORT_NORMAL)" in block


def test_der_viewport_eintrag_wird_ausgetauscht_nicht_geaendert():
    """Safari uebernimmt ein per setAttribute zurueckgenommenes `maximum-scale` erst beim
    naechsten Laden der Seite. Die Sperre blieb dadurch stehen: Das Feld zoomte genau einmal
    hinein, danach nie wieder -- und der GEWOLLTE Zwei-Finger-Zoom war mit tot (am Geraet
    gegengeprueft, 02.09.2026)."""
    block = _block("_viewportSetzen")
    assert "document.createElement('meta')" in block
    assert "replaceChild(neu, alt)" in block


def test_der_normale_eintrag_wird_nur_einmal_gelesen():
    """Laufen zwei Rueckholungen kurz hintereinander, laese die zweite den gesperrten Stand
    als "normal" -- und die Sperre bliebe fuer immer stehen."""
    import re
    m = re.search(r"const _VIEWPORT_NORMAL = \(function \(\) \{", RUMPF)
    assert m, "der Ausgangswert muss beim Laden festgehalten werden, nicht je Aufruf"
    assert "_VIEWPORT_NORMAL" in _block("_seitenZoomZurueck")


def test_der_zoom_kommt_schon_beim_verlassen_des_feldes_zurueck():
    """Nicht erst beim Schliessen des Kastens: Wer die Tastatur wegtippt und den Kasten offen
    laesst, sass sonst weiter auf der hineingezoomten Seite (zweite Nutzer-Aufnahme)."""
    block = _block("_addIcaoSucheControl")
    assert "_icaoFeld.onblur = function () { _seitenZoomZurueck(); }" in block
    assert "_seitenZoomZurueck()" in _block("_icaoOeffnen")


def test_die_feldschrift_haelt_die_sechzehn_pixel():
    """Unter 16 px zoomt Safari beim Fokus grundsaetzlich. In px und nicht in rem: An der
    Basisgroesse haengend wuerde der Wert still kippen, sobald die jemand aendert."""
    assert "font-size: 16px; letter-spacing: 2px" in QUELLE


def test_nur_auf_ios():
    """Andere Browser zoomen beim Fokus gar nicht erst und wuerden hier nur ihre eigene, vom
    Nutzer gewaehlte Zoomstufe verlieren."""
    assert "const _IOS_GERAET = /iP(hone|ad|od)/.test(" in RUMPF
    assert "if (!_IOS_GERAET) return;" in _block("_seitenZoomZurueck")
