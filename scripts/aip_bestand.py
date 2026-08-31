#!/usr/bin/env python3
"""Woechentlicher Abgleich der AIP-Kartenblaetter -- rechnet nichts, meldet nur.

Aufruf:  python scripts/aip_bestand.py [--pause 0.4]

**Es gibt keine Automatik mehr** (Nutzerentscheidung 31.08.2026: "Wir bauen die Automatik
komplett zurueck. Fuer alle Kartentypen! Wir belassen es bei einer einfachen
Hash-Aktualitaetspruefung."). Der Grund liegt in den Daten: Die Blaetter aendern sich fast
nie -- beim einzigen bisherigen Auffrischlauf waren 437 von 446 unveraendert. Eine
Maschinerie, die Rahmen sucht und Ziffern liest, arbeitete also fast immer fuer nichts.

``melden()`` tut je Karte genau vier Dinge:

1. Ist der Platz aus ``airport_links`` verschwunden -> Status ``verwaist`` (nicht
   geloescht, s. ``app/database.upsert_chart_dfs`` Spec Abschnitt 4.5).
2. Ist ``gesehener_hash`` leer (frisch migrierte Sichtflugkarten) -> eintragen, NICHT
   melden. Der Rohbytes-Hash war nie vorhanden, kein Vergleich moeglich.
3. Hat die Karte keine Passung (``offen``, ``nicht_gefunden``) -> das neue Blatt wird
   stillschweigend das gueltige. Es gibt nichts zu pruefen, die Frage stellt sich erst,
   wenn jemand passt.
4. Sonst (``gepasst``, ``auto``) und der Hash weicht ab -> Status ``pruefen``, das neue
   Blatt liegt daneben, der Nutzer entscheidet im Admin.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import aip_charts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import (  # noqa: E402
    get_airport_links,
    get_charts_dfs,
    get_connection,
    upsert_chart_dfs,
)

logger = logging.getLogger("aip_bestand")

_UA = {"User-Agent": "FriesenSpy/AIP-Kartenabgleich (+https://friesenspy.devprops.de)"}


def _hole(client: httpx.Client):
    def holen(url: str) -> str:
        r = client.get(url, headers=_UA, timeout=40.0)
        r.raise_for_status()
        return r.text
    return holen


def _seite_ueber_bild_hash(seiten: list[str], hole, bild_hash: str) -> int | None:
    """Einmaliges Nachtragen von ``seite_nr`` fuer migrierte Zeilen (Spec 6.2).

    ``bild_hash`` ist der Hash des ABGELEGTEN, ggf. gedrehten Blatts -- fuer die sieben
    quer gedruckten Sichtflugkarten stimmt er nicht mit den DFS-Rohbytes ueberein. Fuer
    diese sieben liefert die Suche kein Ergebnis; die Zeile erscheint als "Seite unbekannt"
    und wartet auf eine manuelle Wahl im Admin (Spec 6.3) -- sichtbar, nicht stumm
    uebersprungen.
    """
    if not bild_hash:
        return None
    for i, url in enumerate(seiten):
        try:
            roh = aip_charts.bild_aus_html(hole(url))
        except Exception:
            continue
        if roh and hashlib.sha256(roh).hexdigest() == bild_hash:
            return i
    return None


def melden(pause: float = 0.4) -> dict:
    """Fuer jede Karte das Rohblatt holen und den Hash vergleichen. Siehe Modul-Docstring.

    Kosten: EIN Abruf je Karte, nicht zwei -- das Bild steckt als data-URI in derselben
    HTML-Seite (``aip_charts.bild_aus_html``). Dazu je Platz einen fuer die
    Kapitelaufloesung, gecacht ueber ``seiten``-Wiederverwendung innerhalb eines Laufs waere
    eine Optimierung fuer spaeter -- bei 556 Karten und einmal woechentlich nicht dringend.
    """
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    zaehler: collections.Counter = collections.Counter()
    geaendert: list[str] = []
    try:
        links = get_airport_links(conn)
        karten = get_charts_dfs(conn)
        with httpx.Client(follow_redirects=True) as client:
            hole = _hole(client)
            for k in karten:
                icao, sorte = k["icao"], k["sorte"]
                url = links.get(icao)

                # 1. Verwaist / Rueckkehr -- unabhaengig vom Rest, denn ohne Link gibt es
                # nichts zu holen.
                if url is None:
                    if k["status"] != "verwaist":
                        upsert_chart_dfs(conn, icao, sorte, status="verwaist",
                                         status_vorher=k["status"])
                        zaehler["verwaist"] += 1
                    continue
                if k["status"] == "verwaist":
                    upsert_chart_dfs(conn, icao, sorte,
                                     status=k["status_vorher"] or "offen")
                    zaehler["zurueckgekehrt"] += 1
                    k = dict(k, status=k["status_vorher"] or "offen")

                try:
                    seiten = aip_charts.seiten_des_kapitels(url, hole)
                except Exception as e:
                    logger.info("%s: Kapitel nicht erreichbar (%s)", icao, str(e)[:50])
                    zaehler["kapitel_fehler"] += 1
                    continue
                finally:
                    time.sleep(pause)

                seite_nr = k["seite_nr"]
                if seite_nr is None or not (0 <= seite_nr < len(seiten)):
                    seite_nr = _seite_ueber_bild_hash(seiten, hole, k["bild_hash"])
                    if seite_nr is None:
                        zaehler["seite_unbekannt"] += 1
                        continue

                try:
                    roh = aip_charts.bild_aus_html(hole(seiten[seite_nr]))
                except Exception as e:
                    logger.info("%s: Seite nicht erreichbar (%s)", icao, str(e)[:50])
                    zaehler["abruf_fehler"] += 1
                    continue
                finally:
                    time.sleep(pause)
                if roh is None:
                    zaehler["kein_bild"] += 1
                    continue
                roh_hash = hashlib.sha256(roh).hexdigest()

                # 2. Noch nie gesehen -- kein Vergleich moeglich.
                if not k["gesehener_hash"]:
                    upsert_chart_dfs(conn, icao, sorte, status=k["status"],
                                     seite_nr=seite_nr, gesehener_hash=roh_hash)
                    zaehler["erstmalig"] += 1
                    continue

                if roh_hash == k["gesehener_hash"]:
                    if seite_nr != k["seite_nr"]:
                        upsert_chart_dfs(conn, icao, sorte, status=k["status"],
                                         seite_nr=seite_nr)
                    zaehler["unveraendert"] += 1
                    continue

                # 3. Ohne Passung ist nichts zu pruefen -- das neue Blatt wird das gueltige.
                if k["status"] not in ("gepasst", "auto"):
                    aip_charts.blatt_schreiben(
                        aip_charts.dfs_blatt_pfad(einst.DB_PATH, icao, sorte, "roh"), roh)
                    upsert_chart_dfs(conn, icao, sorte, status=k["status"],
                                     seite_nr=seite_nr, gesehener_hash=roh_hash)
                    zaehler["blatt_ausgetauscht"] += 1
                    continue

                # 4. gepasst/auto: zur Pruefung vorlegen. Die bestehende Passung bleibt
                # unangetastet -- das neue Blatt liegt NEBEN dem gueltigen.
                aip_charts.blatt_schreiben(
                    aip_charts.dfs_blatt_pfad(einst.DB_PATH, icao, sorte,
                                              f"neu.{roh_hash[:12]}"), roh)
                upsert_chart_dfs(conn, icao, sorte, status="pruefen",
                                 status_vorher=k["status"], seite_nr=seite_nr,
                                 gesehener_hash=roh_hash)
                zaehler["pruefen"] += 1
                geaendert.append(f"{icao}/{sorte}")
        conn.commit()
    finally:
        conn.close()
    return {"zaehler": dict(zaehler), "geaendert": sorted(geaendert), "gesamt": len(karten)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pause", type=float, default=0.4)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    e = melden(a.pause)
    print(f"geprueft: {e['gesamt']} -- zur Pruefung vorgelegt: {len(e['geaendert'])}")
    print(e["zaehler"])
    if e["geaendert"]:
        print(" ".join(e["geaendert"]))


if __name__ == "__main__":
    main()
