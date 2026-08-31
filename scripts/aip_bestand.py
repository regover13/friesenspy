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


def _hole(client: httpx.Client, pause: float = 0.4):
    """Abrufer mit eingebauter Hoeflichkeitspause.

    **Die Pause gehoert HIER hinein, nicht neben die Aufrufstelle.** Beim ersten Lauf am
    31.08.2026 stand sie nur um die zwei offensichtlichen Abrufe je Karte; die
    Kapitelaufloesung in ``seiten_des_kapitels`` ging voellig ungebremst durch und feuerte
    28 Anfragen je Sekunde auf aip.dfs.de (gemessen im Log: drei Kapitelseiten in 71 ms).
    So gebunden ist jeder Weg zur DFS gebremst, auch ein kuenftiger.
    """
    def holen(url: str) -> str:
        r = client.get(url, headers=_UA, timeout=40.0)
        r.raise_for_status()
        time.sleep(pause)
        return r.text
    return holen


def _seite_ueber_bild_hash(seiten: list[str], hole, bild_hash: str,
                           sorte: str) -> int | None:
    """Einmaliges Nachtragen von ``seite_nr`` fuer migrierte Zeilen (Spec 6.2).

    ``bild_hash`` ist der Hash des ABGELEGTEN, ggf. gedrehten Blatts. Bei den
    Sichtflugkarten ist das fuer 439 von 446 zugleich der Rohbytes-Hash -- dort trifft die
    Suche. Fuer die sieben quer gedruckten stimmt er nicht; sie erscheinen als "Seite
    unbekannt" und warten auf eine manuelle Wahl (Spec 6.3) -- sichtbar, nicht stumm
    uebersprungen.

    **Bei Flugplatz- und Rollkarten wird gar nicht erst gesucht.** Dort ist das abgelegte
    Blatt IMMER das genordete (nach der Bahnrichtung zurueckgedreht), sein Hash kann also
    mit keiner DFS-Rohseite uebereinstimmen. Eine Suche crawlte das ganze Kapitel und faende
    garantiert nichts -- und zwar in JEDEM Wochenlauf erneut, solange seite_nr unbekannt
    bleibt. Am 31.08.2026 waren das 68 Zeilen zu je rund sechs Seiten.
    """
    if not bild_hash or sorte != "sichtflug":
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

    **Nach jedem Schreiben wird committet.** Ein einziges ``commit()`` am Ende hielt eine
    Schreibtransaktion ueber den GANZEN Lauf offen -- also ueber hunderte Netzabrufe hinweg.
    In WAL bleiben Leser davon unberuehrt, andere SCHREIBER nicht: Am 31.08.2026 scheiterte
    ``save_prefile_sigs`` im 15-Sekunden-Poll 79 Mal mit "database is locked", bis der Lauf
    abgebrochen wurde. Eine Transaktion darf keinen Netzabruf umspannen.

    Kosten: EIN Abruf je Karte fuer das Blatt -- das Bild steckt als data-URI in derselben
    HTML-Seite (``aip_charts.bild_aus_html``) --, dazu die Kapitelaufloesung, die je PLATZ
    nur einmal geschieht (110 Plaetze haben zwei Zeilen).
    """
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    zaehler: collections.Counter = collections.Counter()
    geaendert: list[str] = []
    # Kapitelseiten je Platz nur EINMAL aufloesen. 110 der 446 Plaetze haben zwei Zeilen
    # (Sichtflug- und Flugplatzkarte); ohne diesen Speicher liefe die Aufloesung doppelt --
    # bei rund vier Abrufen je Aufloesung sind das 440 Anfragen umsonst.
    kapitel_speicher: dict[str, list[str]] = {}
    try:
        links = get_airport_links(conn)
        karten = get_charts_dfs(conn)
        with httpx.Client(follow_redirects=True) as client:
            hole = _hole(client, pause)
            for k in karten:
                icao, sorte = k["icao"], k["sorte"]
                url = links.get(icao)

                # 1. Verwaist / Rueckkehr -- unabhaengig vom Rest, denn ohne Link gibt es
                # nichts zu holen.
                if url is None:
                    if k["status"] != "verwaist":
                        upsert_chart_dfs(conn, icao, sorte, status="verwaist",
                                         status_vorher=k["status"])
                        conn.commit()
                        zaehler["verwaist"] += 1
                    continue
                if k["status"] == "verwaist":
                    upsert_chart_dfs(conn, icao, sorte,
                                     status=k["status_vorher"] or "offen")
                    conn.commit()
                    zaehler["zurueckgekehrt"] += 1
                    k = dict(k, status=k["status_vorher"] or "offen")

                if url in kapitel_speicher:
                    seiten = kapitel_speicher[url]
                else:
                    try:
                        seiten = aip_charts.seiten_des_kapitels(url, hole)
                    except Exception as e:
                        logger.info("%s: Kapitel nicht erreichbar (%s)", icao, str(e)[:50])
                        zaehler["kapitel_fehler"] += 1
                        continue
                    kapitel_speicher[url] = seiten

                seite_nr = k["seite_nr"]
                if seite_nr is None or not (0 <= seite_nr < len(seiten)):
                    seite_nr = _seite_ueber_bild_hash(seiten, hole, k["bild_hash"], sorte)
                    if seite_nr is None:
                        zaehler["seite_unbekannt"] += 1
                        continue

                try:
                    roh = aip_charts.bild_aus_html(hole(seiten[seite_nr]))
                except Exception as e:
                    logger.info("%s: Seite nicht erreichbar (%s)", icao, str(e)[:50])
                    zaehler["abruf_fehler"] += 1
                    continue
                if roh is None:
                    zaehler["kein_bild"] += 1
                    continue
                roh_hash = hashlib.sha256(roh).hexdigest()

                # 2. Noch nie gesehen -- kein Vergleich moeglich.
                if not k["gesehener_hash"]:
                    upsert_chart_dfs(conn, icao, sorte, status=k["status"],
                                     seite_nr=seite_nr, gesehener_hash=roh_hash)
                    conn.commit()
                    zaehler["erstmalig"] += 1
                    continue

                if roh_hash == k["gesehener_hash"]:
                    if seite_nr != k["seite_nr"]:
                        upsert_chart_dfs(conn, icao, sorte, status=k["status"],
                                         seite_nr=seite_nr)
                        conn.commit()
                    zaehler["unveraendert"] += 1
                    continue

                # 3. Ohne Passung ist nichts zu pruefen -- das neue Blatt wird das gueltige.
                if k["status"] not in ("gepasst", "auto"):
                    aip_charts.blatt_schreiben(
                        aip_charts.dfs_blatt_pfad(einst.DB_PATH, icao, sorte, "roh"), roh)
                    upsert_chart_dfs(conn, icao, sorte, status=k["status"],
                                     seite_nr=seite_nr, gesehener_hash=roh_hash)
                    conn.commit()
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
                conn.commit()
                zaehler["pruefen"] += 1
                geaendert.append(f"{icao}/{sorte}")
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
