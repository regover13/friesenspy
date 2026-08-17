# tests/test_mithoeren.py
"""Zusicherungen zum Mithören über listen.vatsim.net (Spec vom 16.08.2026, Teil A).

Für Vanilla-JS gibt es in diesem Projekt keinen Testläufer — geprüft wird deshalb der
Quelltext. Grob, aber es hält genau die Zusagen fest, die man einer einzelnen Zeile nicht
ansieht: die geprüfte Adresse, das neue Fenster, die Hausfarbe und vor allem die
Kniebrett-Regel. Letztere ist eine Vorgabe des Nutzers und darf nicht still verlorengehen.
"""
from __future__ import annotations

import re
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8"
)


def test_adresse_steht_genau_einmal_im_quelltext():
    """Die Route ist gegen das ausgelieferte Bundle geprüft: /live/<CALLSIGN>.

    Genau einmal, weil es genau einen Bauort geben soll (listenLinkIcon). Eine zweite
    Fundstelle hieße: irgendwo wurde die URL von Hand zusammengesetzt.
    """
    assert INDEX.count("https://listen.vatsim.net/live/") == 1


def test_callsign_wird_kodiert_in_den_pfad_gesetzt():
    """Der Wert landet im PFAD, nicht in einem Parameter — dort gilt encodeURIComponent."""
    assert "listen.vatsim.net/live/' + encodeURIComponent(cs)" in INDEX


def test_link_oeffnet_ein_neues_fenster_ohne_opener():
    m = re.search(r"function listenLinkIcon\(callsign\) \{.*?\n\}", INDEX, re.S)
    assert m, "listenLinkIcon nicht gefunden"
    quelle = m.group(0)
    assert 'target="_blank"' in quelle
    assert 'rel="noopener"' in quelle, "ohne noopener bekommt die fremde Seite window.opener"
    assert "event.stopPropagation()" in quelle, (
        "ohne stopPropagation löst der Klick in der Live-Tabelle den Zellen-Handler aus "
        "bzw. schließt im Karten-Popup die Blase"
    )


def test_symbol_ist_im_kniebrett_ausgeblendet():
    """Vorgabe des Nutzers: Im EFB-Panel gibt es keinen Browser, in dem der Link aufginge."""
    assert re.search(
        r"html\.vr-panel \.listen-link-icon \{[^}]*display:\s*none", INDEX
    ), "html.vr-panel .listen-link-icon { display: none } fehlt"


def test_symbol_traegt_die_hausfarbe_fuer_klickbares():
    """`.icon` zeichnet über stroke: currentColor, und ein globales `a { color }` gibt es
    nicht — ohne diese Regel nähme der Browser sein Standard-Linkblau."""
    assert re.search(
        r"\.listen-link-icon \{[^}]*color:\s*var\(--green\)", INDEX
    ), ".listen-link-icon setzt keine Farbe"


def test_eigenes_sprite_statt_des_teamspeak_headsets():
    """Das Headset steht in dieser Anwendung für TeamSpeak. Ein Symbol, zwei Bedeutungen —
    das wäre eine zu viel."""
    assert '<symbol id="icon-speaker"' in INDEX
    m = re.search(r"function listenLinkIcon\(callsign\) \{.*?\n\}", INDEX, re.S)
    assert m and "icon('speaker')" in m.group(0)
    assert "icon('headset')" not in (m.group(0) if m else "")


def test_symbol_haengt_an_den_beiden_vorgesehenen_stellen():
    """Live-Tabelle und Karten-Popup eines Friesen — und sonst nirgends (Spec 1.3):
    im Flugplan-Fenster wäre es ein zweiter Weg im selben Klickpfad, beim Fremdverkehr
    stünde es mal da und mal nicht."""
    assert INDEX.count("listenLinkIcon(p.callsign)") == 2
    assert re.search(
        r'<td class="td-callsign"[^>]*>\$\{escHtml\(\(p\.callsign \|\| \'\'\)\.toUpperCase\(\)\)\}'
        r"\$\{listenLinkIcon\(p\.callsign\)\}</td>",
        INDEX,
    ), "in der Live-Tabelle fehlt das Symbol hinter dem Callsign"
    assert re.search(
        r'<div class="popup-callsign">\$\{escHtml\(\(p\.callsign \|\| \'\'\)\.toUpperCase\(\)\)\}'
        r"\$\{listenLinkIcon\(p\.callsign\)\}</div>",
        INDEX,
    ), "im Karten-Popup fehlt das Symbol hinter dem Callsign"


def test_ohne_callsign_kein_symbol():
    """Ein Lautsprecher, der auf /live/ ohne Wert zeigt, führt ins Leere (dort: 404)."""
    m = re.search(r"function listenLinkIcon\(callsign\) \{.*?\n\}", INDEX, re.S)
    assert m and "if (!cs) return '';" in m.group(0)
