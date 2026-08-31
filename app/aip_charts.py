"""DFS-Kartenblaetter beschaffen und ablegen.

Bis zum 31.08.2026 stand hier auch die Deutung: Kartenrahmen finden, Gradnetz-Ticks messen,
Ziffern per Schablone lesen, daraus eine Passung rechnen. Das hat 446 Sichtflugkarten
zugeordnet und dabei 171 der Handarbeit ueberlassen -- die Ziffernerkennung traegt nicht bei
jedem Blatt.

Laufend gebraucht wird sie nicht: Die Blaetter aendern sich fast nie. Die am 31.08.2026
durchgesehenen tragen Ausgabedaten von 2014 bis 2026, und beim einzigen Auffrischlauf waren
437 von 446 unveraendert. Und wenn sich eines aendert, ist die Frage ohnehin eine, die nur
ein Mensch beantworten kann: Stimmt die Passung auf dem neuen Blatt noch?

Die Passung entsteht seitdem in ``app/ground_charts.handpassung`` aus zwei geklickten
Punkten -- fuer beide Kartentypen.

**Die Blaetter sind keine PDFs.** Ein Eintrag aus ``airport_links`` wie
``aip.dfs.de/BasicVFR/pages/P0016F.html`` ist eine Weiterleitungsseite mit
``<meta http-equiv="Refresh">``; ein HTTP-Redirect findet NICHT statt. Wer ``curl -L``
benutzt, bekommt die Weiterleitungsseite zurueck und haelt sie fuer die Karte. Die Karte
steckt als PNG in einem ``data:``-URI im HTML der Zielseite.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import base64
import logging
import os
import re
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

_META_REFRESH = re.compile(r'http-equiv=.?Refresh.?[^>]*url=([^"\'>\s]+)', re.I)
_IMG_AIP = re.compile(r'id="imgAIP"[^>]*src="data:image/png;base64,([^"]+)"')
_SEITE = re.compile(r'href="(\.\./pages/[0-9A-Fa-f]+\.html)"')
_KAPITEL = re.compile(r'href="(\.\./chapter/[0-9A-Fa-f]+\.html)"')
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


def kapitel_links(html: str, basis: str) -> list[str]:
    """Die Kapitel-Verweise einer Seite.

    Eine Platzseite verlinkt nicht direkt ihre Geschwister, sondern das Kapitel; erst dessen
    Seite listet alle Blaetter des Platzes. Ohne diesen Zwischenschritt findet man die Karte
    von EDAZ nie, weil die Textseite selbst keinen pages-Link traegt.
    """
    gesehen: dict[str, None] = {}
    for treffer in _KAPITEL.findall(html):
        gesehen.setdefault(urllib.parse.urljoin(basis, treffer), None)
    return list(gesehen)


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


def blatt_schreiben(pfad, roh: bytes) -> None:
    """Blatt atomar ablegen: erst daneben, dann umbenennen.

    Sonst liefert FileResponse mitten im Austausch ein abgeschnittenes PNG aus.
    """
    ziel = Path(pfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(ziel.suffix + ".tmp")
    tmp.write_bytes(roh)
    os.replace(tmp, ziel)


def dfs_blatt_pfad(db_path: str, icao: str, sorte: str, teil: str = "") -> "Path":
    """Wo ein Blatt liegt. ``teil`` haengt einen weiteren Namensteil an, z.B. 'roh'.

    Eigenes Verzeichnis ``aip_dfs/``, ICAO UND Sorte im Namen: Ein Platz kann eine
    Sichtflug- UND eine Flugplatzkarte haben (110 von 446 -- gemessen 31.08.2026), beide
    duerfen sich nicht ueberschreiben. Der alte Ground-Pfad war nur auf ICAO geschluesselt
    und tat genau das.
    """
    code = (icao or "").strip().upper()
    name = f"{code}.{sorte}" + (f".{teil}" if teil else "") + ".png"
    return Path(db_path).parent / "aip_dfs" / name


def seiten_des_kapitels(url: str, hole) -> list[str]:
    """Alle Seiten-URLs des Kapitels hinter einem Kartenlink, die Zielseite zuerst.

    **Wozu.** Bei EDDK sind sechs Seiten im Kapitel, und ohne diese Liste sieht der Admin
    im Seitenwaehler nur eine (24.08.2026). Welche die richtige ist, kann kein Verfahren
    wissen -- deshalb waehlt ein Mensch, und dafuer braucht er die Liste.

    Fehler beim Abruf einzelner Kapitelseiten werden uebersprungen: Eine unerreichbare Seite
    darf die Auswahl nicht verhindern.
    """
    erste = hole(url)
    ziel = airac_url(erste, url) or url
    html = hole(ziel) if ziel != url else erste
    seiten = [ziel]
    for kapitel in kapitel_links(html, ziel):
        try:
            weiter = hole(kapitel)
        except Exception:
            logger.info("AIP: Kapitelseite %s nicht erreichbar", kapitel)
            continue
        for seite in kapitelseiten(weiter, kapitel):
            if seite not in seiten:
                seiten.append(seite)
    return seiten


