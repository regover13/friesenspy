"""Pruefungen fuer ``tests/test_readme_aktuell.py`` -- als eigenes Modul, damit sich
jede Wache mit einer kuenstlich geluecktenen README gegenpruefen laesst.

Alle Funktionen nehmen den Text entgegen, statt selbst zu lesen. Genau das macht den
Negativtest moeglich: Eine Wache, von der niemand weiss, ob sie anschlaegt, ist keine.
"""
from __future__ import annotations

import re

# Die Ebenen der Live-Karte stehen im Frontend als Zuweisung an die Leaflet-Auswahl.
# An DIE ist gebunden, nicht an einen Kommentar oder eine Beschriftung im Umfeld --
# eine freie Zeichenkettensuche faende auch die Erwaehnung in einem Kommentar.
_EBENE = re.compile(r"liveOverlays\['([^']+)'\]")
_TAB = re.compile(r'data-tab="([a-z]+)"')
# Ein Settings-Feld ist eine Zeile GROSSBUCHSTABEN mit Typangabe, vier Leerzeichen tief.
_EINSTELLUNG = re.compile(r"^    ([A-Z][A-Z0-9_]*)\s*:", re.M)

_ZAHLWORT = {"zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6,
             "sieben": 7, "acht": 8}


def ebenen_im_frontend(index_html: str) -> list[str]:
    """Namen der abschaltbaren Karten-Ebenen, in der Reihenfolge des Codes."""
    return list(dict.fromkeys(_EBENE.findall(index_html)))


def fehlende_ebenen(readme: str, index_html: str) -> list[str]:
    """Ebenen, die es auf der Karte gibt, aber nicht im Handbuch."""
    return [e for e in ebenen_im_frontend(index_html) if e not in readme]


def einstellungen_in_config(config_py: str) -> list[str]:
    """Namen aller Felder der ``Settings``-Klasse."""
    return list(dict.fromkeys(_EINSTELLUNG.findall(config_py)))


def fehlende_einstellungen(readme: str, config_py: str) -> list[str]:
    """Einstellungen, die der Server kennt, das Handbuch aber nicht."""
    return [e for e in einstellungen_in_config(config_py) if e not in readme]


# Die Bereichsleiste der Admin-Seite und die Typ-Leiste darunter. Gebunden ist an die
# BESCHRIFTUNG, nicht an den `data-tab`-Schluessel: Im Handbuch steht „Bruegge", im Quelltext
# `bruegge` -- ein Vergleich der Schluessel schluege immer fehl und waere damit wertlos.
_ADMIN_BEREICH = re.compile(r'class="tab-btn[^"]*" data-tab="[a-z]+">([^<]+)</button>')
_ADMIN_TYP = re.compile(r'class="typ-btn[^"]*" data-typ="[a-z]+">([^<]+)</button>')


def _beschriftung(roh: str) -> str:
    """„🌉 Brügge" → „Brügge". Das Zeichen davor ist Schmuck und steht nicht im Handbuch."""
    return roh.split(" ")[-1].strip()


def bereiche_der_adminseite(admin_html: str) -> list[str]:
    """Die sechs Bereiche der Admin-Leiste, in der Reihenfolge des Codes."""
    return list(dict.fromkeys(_beschriftung(b) for b in _ADMIN_BEREICH.findall(admin_html)))


def admin_kapitel(readme: str) -> str:
    """Nur das Kapitel „Verwaltung (Admin)“ -- bis zur naechsten Kapitelueberschrift.

    ⚠ Gesucht wird ABSICHTLICH nicht im ganzen Handbuch. Die Namen der Event-Typen kommen
    dort auch sonst vor: „Kieker“ steckt in „FriesenKieker“ im Kapitel zur Bruegge, und ein
    neuer Typ waere damit stillschweigend als dokumentiert durchgegangen. Genau dieser Fall
    hat die erste Fassung dieser Wache wertlos gemacht -- aufgefallen ist er nur, weil der
    Negativtest danebenstand.
    """
    m = re.search(r"^## [^\n]*Verwaltung \(Admin\)\s*$", readme, re.M)
    if m is None:
        raise AssertionError("Kapitel „Verwaltung (Admin)“ nicht gefunden")
    rest = readme[m.end():]
    weiter = re.search(r"^## ", rest, re.M)
    return rest[:weiter.start()] if weiter else rest


def fehlende_admin_bereiche(readme: str, admin_html: str) -> list[str]:
    """Bereiche, die es im Admin gibt, aber nicht im Admin-Kapitel des Handbuchs."""
    kapitel = admin_kapitel(readme)
    return [b for b in bereiche_der_adminseite(admin_html) if b not in kapitel]


def eventtypen_der_adminseite(admin_html: str) -> list[str]:
    """Die Event-Typen der zweiten Leiste. Hier wachsen laut Planung vier weitere nach."""
    return list(dict.fromkeys(_beschriftung(t) for t in _ADMIN_TYP.findall(admin_html)))


def fehlende_admin_eventtypen(readme: str, admin_html: str) -> list[str]:
    kapitel = admin_kapitel(readme)
    return [t for t in eventtypen_der_adminseite(admin_html) if t not in kapitel]


def tabs_im_frontend(index_html: str) -> list[str]:
    return sorted(set(_TAB.findall(index_html)))


def zahlwort_der_tab_ueberschrift(readme: str) -> int:
    """Die Zahl aus „Die vier Tabs im Ueberblick".

    Absichtlich an die Ueberschrift gebunden und nicht an eine Konstante: Genau dort
    steht die Aussage, die falsch wird, wenn ein Tab dazukommt.
    """
    m = re.search(r"^#+ Die (\w+) Tabs im Überblick", readme, re.M)
    if m is None:
        raise AssertionError("Überschrift „Die … Tabs im Überblick“ nicht gefunden")
    wort = m.group(1).lower()
    if wort not in _ZAHLWORT:
        raise AssertionError(f"unbekanntes Zahlwort in der Tab-Überschrift: {wort!r}")
    return _ZAHLWORT[wort]
