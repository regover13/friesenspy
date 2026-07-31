# tests/test_aircraft_ui_static.py
"""Invarianten der beiden statischen Seiten rund um das Muster-Info-Panel.

Fuer Vanilla-JS gibt es in diesem Projekt keinen Testlaeufer -- diese Pruefungen greifen
deshalb auf den Quelltext zu. Das ist grob, faengt aber genau die drei Rueckfaelle ab, die
zwei unabhaengige Reviews gefunden haben und die man einer Zeile nicht ansieht.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
ADMIN = (STATIC / "admin.html").read_text(encoding="utf-8")


def test_ac_link_listener_haengt_in_der_capture_phase():
    """C1: sonst ist der Aircraft-Link im Flugplan-Modal tot.

    `.fp-modal-box` traegt `onclick="event.stopPropagation()"` -- in der Bubble-Phase
    erreicht der Klick auf einen ac-link im Modal das `document` nie, der Link haengt dann
    nur ein '#' an die URL.
    """
    m = re.search(
        r"document\.addEventListener\('click', function \(e\) \{"
        r"\s*const a = e\.target\.closest.*?\}(?P<ende>[^;]*);",
        INDEX, re.S,
    )
    assert m, "delegierter ac-link-Listener nicht gefunden"
    assert "true" in m.group("ende"), \
        "ac-link-Listener haengt in der Bubble-Phase — stopPropagation() der Modal-Box " \
        "verschluckt den Klick, bevor er das document erreicht"


def test_ac_modal_schliesst_bei_klick_auf_das_overlay():
    """Minor: alle anderen Modals tun das. Sicher erst mit der Capture-Phase aus C1."""
    box = re.search(r'<div id="ac-modal" class="modal">\s*<div class="modal-box"([^>]*)>', INDEX)
    assert box, "#ac-modal .modal-box nicht gefunden"
    assert "event.stopPropagation()" in box.group(1), \
        "ohne stopPropagation schliesst jeder Klick INS Modal es sofort wieder"
    assert re.search(
        r"getElementById\('ac-modal'\)\.addEventListener\('click'", INDEX
    ), "kein Overlay-Klick-Handler fuer #ac-modal"


def test_ac_link_traegt_keine_eigene_unterstreichung():
    """Stehende UI-Regel: Klickbares ist allein durch Blau gekennzeichnet.

    Der Designator stand in derselben Tabellenzeile wie die Strecken-Zelle (`.text-green`,
    nur blau) und sah als einziges Klickziel der App anders aus — gepunktete `border-bottom`
    plus `text-decoration: underline` beim Hover.
    """
    m = re.search(r"\.ac-link\s*\{([^}]*)\}", INDEX)
    assert m, ".ac-link-Regel nicht gefunden"
    regel = m.group(1)
    assert "border-bottom" not in regel, \
        ".ac-link hat wieder eine eigene Unterstreichung — kein anderes Klickziel hat eine"
    assert "underline" not in regel
    assert not re.search(r"\.ac-link:hover\s*\{[^}]*underline", INDEX), \
        ".ac-link:hover unterstreicht wieder — die anderen Klickziele tun das nicht"


def test_actype_deeplink_wird_vor_dem_tab_abbruch_ausgewertet():
    """Der Teilen-Knopf im Muster-Panel teilt `#actype=<code>` ohne `tab`-Parameter.

    `initFromUrl` steigt bei fehlendem `tab` mit `return` aus — steht die actype-Auswertung
    danach, oeffnet der geteilte Link beim Empfaenger gar nichts.
    """
    m = re.search(r"async function initFromUrl\(\)\s*\{(.*?)\n\}", INDEX, re.S)
    assert m, "initFromUrl nicht gefunden"
    quelle = m.group(1)
    # Zeilenanfang-Anker: der Hinweis-Kommentar ueber der actype-Zeile nennt den Abbruch
    # selbst, ein blosses find() faende deshalb den Kommentar statt der echten Anweisung.
    m_actype = re.search(r"^\s*const acType = p\.get\('actype'\)", quelle, re.M)
    m_return = re.search(r"^\s*if \(!tab\) return", quelle, re.M)
    assert m_actype, "actype-Deep-Link fehlt in initFromUrl"
    assert m_return, "Tab-Abbruch nicht gefunden — Test veraltet"
    assert m_actype.start() < m_return.start(), \
        "actype wird erst nach dem Tab-Abbruch gelesen — ein Link ohne tab oeffnet nichts"


def test_hover_zustand_bleibt_auf_dem_touchscreen_nicht_haengen():
    """Auf dem iPhone blieb der Teilen-Knopf nach dem Antippen im :hover-Zustand.

    Dessen Hintergrund `--green-faint` ist halbtransparent — der Knopf sah danach
    „durchsichtig" aus und wurde erst beim naechsten Tippen wieder normal. Beide
    Knopf-Hover-Regeln des Muster-Panels gehoeren deshalb in `@media (hover: hover)`.
    """
    for regel in (".btn-share:hover", ".modal-close:hover"):
        m = re.search(re.escape(regel) + r"\s*\{", INDEX)
        assert m, f"{regel} nicht gefunden"
        davor = INDEX[:m.start()]
        # letzter geoeffneter @media-Block vor der Regel muss die hover-Abfrage sein
        letzte_media = davor.rfind("@media")
        assert letzte_media != -1 and "hover: hover" in davor[letzte_media:], \
            f"{regel} steht ausserhalb von @media (hover: hover) — der Zustand bleibt " \
            "auf dem Touchscreen nach dem Antippen haengen"


def test_modal_knoepfe_liegen_nicht_ueber_dem_foto():
    """Teilen und Schliessen sassen absolut positioniert auf dem Foto und waren dort
    kaum zu lesen. Sie gehoeren in die Kopfzeile im Fluss, die das Foto nach unten drueckt."""
    box = re.search(
        r'<div id="ac-modal" class="modal">\s*<div class="modal-box"[^>]*>(.*?)<div id="ac-body"',
        INDEX, re.S,
    )
    assert box, "#ac-modal-Kopfbereich nicht gefunden"
    assert 'class="ac-topbar"' in box.group(1), "Kopfzeile .ac-topbar fehlt"
    assert re.search(r"#ac-modal \.modal-close \{[^}]*position: static", INDEX), \
        "das Schliessen-Kreuz ist wieder absolut positioniert und liegt auf dem Foto"


def test_types_deeplink_wird_vor_dem_tab_abbruch_ausgewertet():
    """Wie #actype: der Teilen-Knopf der Musterliste teilt `#types=1` ohne `tab`-Parameter."""
    m = re.search(r"async function initFromUrl\(\)\s*\{(.*?)\n\}", INDEX, re.S)
    assert m, "initFromUrl nicht gefunden"
    quelle = m.group(1)
    m_types  = re.search(r"^\s*if \(p\.get\('types'\)\) openTypesModal\(\);", quelle, re.M)
    m_return = re.search(r"^\s*if \(!tab\) return", quelle, re.M)
    assert m_types, "types-Deep-Link fehlt in initFromUrl"
    assert m_return, "Tab-Abbruch nicht gefunden — Test veraltet"
    assert m_types.start() < m_return.start(), \
        "types wird erst nach dem Tab-Abbruch gelesen — ein Link ohne tab oeffnet nichts"


def test_types_modal_steht_vor_ac_modal_im_dom():
    """Ein Muster-Kuerzel-Klick INNERHALB der Musterliste oeffnet #ac-modal darueber.

    Beide Overlays haben denselben z-index (10000) -- bei Gleichstand gewinnt die
    Dokument-Position (spaeter im DOM = optisch oben). #ac-modal muss deshalb NACH
    #types-modal stehen, sonst verschwindet das Muster-Panel hinter der Liste.
    """
    pos_types = INDEX.find('id="types-modal"')
    pos_ac    = INDEX.find('id="ac-modal"')
    assert pos_types != -1, "#types-modal nicht gefunden"
    assert pos_ac != -1, "#ac-modal nicht gefunden"
    assert pos_types < pos_ac, \
        "#ac-modal steht vor #types-modal im DOM — stapelt sich beim Verschachteln dahinter"


def test_types_modal_schliesst_bei_klick_auf_das_overlay():
    assert re.search(
        r"getElementById\('types-modal'\)\.addEventListener\('click'", INDEX
    ), "kein Overlay-Klick-Handler fuer #types-modal"


def test_musterliste_verlinkt_aus_jeder_zeile_zurueck_ins_muster_modal():
    """Kernanforderung: aus der Liste heraus wieder ins einzelne Muster-Panel springen."""
    m = re.search(r"function renderTypesModalBody\(\)\s*\{(.*?)\n\}", INDEX, re.S)
    assert m, "renderTypesModalBody nicht gefunden"
    assert "acLink(t.code)" in m.group(1), \
        "Musterliste verlinkt die Zeilen nicht ueber den bestehenden ac-link zurueck"


def test_misave_loescht_kein_hochgeladenes_foto():
    """I2: photo_override='' loescht die 'blob'-Markierung — ein hochgeladenes Foto
    verschwaende beim naechsten Speichern (z. B. einer Namenskorrektur) aus der Anzeige.
    Das Kaestchen 'Kein Foto' ist bei 'blob' laut miPrefill NICHT angehakt."""
    m = re.search(r"async function miSave\(\).*?\n    \}", ADMIN, re.S)
    assert m, "miSave nicht gefunden"
    quelle = m.group(0)
    assert "photo_override: document.getElementById('mi-nophoto').checked ? '-' : ''" \
        not in quelle, "photo_override wird weiterhin bedingungslos gesendet"
    assert "!== 'blob'" in quelle, \
        "miSave unterscheidet den 'blob'-Fall nicht — das eigene Foto geht verloren"
