"""AIP-Sichtflugkarten: Blatt holen, Gradnetz vermessen, Passung rechnen und pruefen.

Eigenes Modul aus demselben Grund wie ``app/vrp.py``: Der Bestand ist Zustand mit eigener
Lebensdauer, und die Geometrie ist die Sorte Rechnung, die man gegen Messwerte pruefen will.
Deshalb enthaelt dieses Modul weder Datenbank- noch FastAPI-Bezuege.

**Die Blaetter sind keine PDFs.** Ein Eintrag aus ``airport_links`` wie
``aip.dfs.de/BasicVFR/pages/P0016F.html`` ist eine Weiterleitungsseite mit
``<meta http-equiv="Refresh">``; ein HTTP-Redirect findet NICHT statt. Wer ``curl -L``
benutzt, bekommt die Weiterleitungsseite zurueck und haelt sie fuer die Karte. Die Karte
steckt als PNG in einem ``data:``-URI im HTML der Zielseite.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
"""
from __future__ import annotations

import base64
import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)

_META_REFRESH = re.compile(r'http-equiv=.?Refresh.?[^>]*url=([^"\'>\s]+)', re.I)
_IMG_AIP = re.compile(r'id="imgAIP"[^>]*src="data:image/png;base64,([^"]+)"')
_SEITE = re.compile(r'href="(\.\./pages/[0-9A-Fa-f]+\.html)"')
_AIRAC = re.compile(r'/BasicVFR/(\d{4}[A-Z]{3}\d{2})/')


def airac_url(html: str, basis: str) -> str | None:
    """Ziel des Meta-Refresh, absolut gemacht. None, wenn die Seite keines traegt."""
    m = _META_REFRESH.search(html)
    return urllib.parse.urljoin(basis, m.group(1).strip()) if m else None


def airac_kennung(url: str) -> str | None:
    """Die Ausgabe aus dem Pfad, z. B. '2026AUG20'."""
    m = _AIRAC.search(url)
    return m.group(1) if m else None


def bild_aus_html(html: str) -> bytes | None:
    """Das Kartenblatt aus dem data:-URI. None, wenn die Seite keines enthaelt."""
    m = _IMG_AIP.search(html)
    return base64.b64decode(m.group(1)) if m else None


def kapitelseiten(html: str, basis: str) -> list[str]:
    """Alle Seiten des Platz-Kapitels, doppelte entfernt, Reihenfolge erhalten.

    Noetig, weil der gespeicherte Link nicht immer auf die Karte zeigt: Bei EDAZ oeffnet er
    die Textseite "VFR-Flugverfahren", die Sichtflugkarte ist die vierte Seite desselben
    Kapitels. 28 von 446 Karten liegen so.
    """
    gesehen: dict[str, None] = {}
    for treffer in _SEITE.findall(html):
        gesehen.setdefault(urllib.parse.urljoin(basis, treffer), None)
    return list(gesehen)
