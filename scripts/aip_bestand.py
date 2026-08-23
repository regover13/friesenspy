#!/usr/bin/env python3
"""Erstbefuellung und Auffrischung des AIP-Kartenbestands.

Aufruf:  python scripts/aip_bestand.py [--nur EDXR,EDWF] [--pause 0.4]

Geht alle Eintraege aus ``airport_links`` durch, holt das Blatt, rechnet die Passung und
legt beides ab. Am Ende steht die Quote im Log, dazu die Liste der ungepassten Karten --
**diese Zahl gehoert gemeldet, bevor jemand mit der Handarbeit anfaengt.**

Drei Regeln, die auch der woechentliche Job einhaelt:

1. **Ein fehlgeschlagener Abruf aendert nichts.** Netzfehler oder leere Antwort lassen Zeile
   und Blatt unangetastet und setzen eine gute Karte insbesondere nicht auf ``ungepasst``.
2. **Verwaiste Karten werden abgeraeumt:** Was nicht mehr in ``airport_links`` steht,
   verliert Zeile und Blatt.
3. **Unveraenderte Geometrie erhaelt die Passung** -- auch eine von Hand gesetzte.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md
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
    delete_aip_chart,
    get_aip_chart,
    get_aip_charts,
    get_airport_links,
    get_connection,
    upsert_aip_chart,
)

logger = logging.getLogger("aip_bestand")

_UA = {"User-Agent": "FriesenSpy/AIP-Kartenabgleich (+https://friesenspy.devprops.de)"}
_OPENAIP = "https://api.core.openaip.net/api/airports"


def _hole(client: httpx.Client):
    def holen(url: str) -> str:
        r = client.get(url, headers=_UA, timeout=40.0)
        r.raise_for_status()
        return r.text
    return holen


def platz_koordinate(icao: str, client: httpx.Client, schluessel: str | None,
                     zwischen: dict) -> tuple[float, float] | None:
    """Flugplatzkoordinate: erst airportsdata, ersatzweise OpenAIP.

    ``airportsdata`` kennt 24 der 446 Plaetze nicht -- OpenAIP kannte am 23.08.2026 alle.
    """
    if icao in zwischen:
        return zwischen[icao]
    try:
        import airportsdata
        apt = airportsdata.load("ICAO").get(icao)
    except Exception:
        apt = None
    if apt:
        zwischen[icao] = (apt["lat"], apt["lon"])
        return zwischen[icao]
    if not schluessel:
        zwischen[icao] = None
        return None
    try:
        r = client.get(_OPENAIP, params={"search": icao, "limit": 5},
                       headers={**_UA, "x-openaip-api-key": schluessel}, timeout=25.0)
        r.raise_for_status()
        for eintrag in r.json().get("items", []):
            if eintrag.get("icaoCode") == icao:
                g = eintrag["geometry"]["coordinates"]
                zwischen[icao] = (g[1], g[0])
                return zwischen[icao]
    except Exception as e:
        logger.info("%s: OpenAIP nicht erreichbar (%s)", icao, str(e)[:60])
    zwischen[icao] = None
    return None


def lauf(nur: set[str] | None = None, pause: float = 0.4) -> dict:
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    zaehler: collections.Counter = collections.Counter()
    ungepasst: list[str] = []
    koordinaten: dict = {}
    try:
        links = get_airport_links(conn)
        if nur:
            links = {k: v for k, v in links.items() if k in nur}

        # Regel 2: Was nicht mehr verlinkt ist, verschwindet auch aus dem Bestand.
        if not nur:
            for karte in get_aip_charts(conn, nur_gepasst=False):
                if karte["icao"] not in links:
                    delete_aip_chart(conn, karte["icao"])
                    aip_charts.blatt_pfad(einst.DB_PATH, karte["icao"]).unlink(missing_ok=True)
                    zaehler["verwaist_entfernt"] += 1
            conn.commit()

        with httpx.Client(follow_redirects=True) as client:
            holen = _hole(client)
            for i, (icao, url) in enumerate(sorted(links.items()), 1):
                koord = platz_koordinate(icao, client, einst.OPENAIP_API_KEY, koordinaten)
                if koord is None:
                    zaehler["ohne_koordinate"] += 1
                    ungepasst.append(icao)
                    continue
                try:
                    roh, passung, airac = aip_charts.blatt_beschaffen(
                        url, koord[0], koord[1], holen)
                except Exception as e:
                    # Regel 1: Netzfehler entwertet keine bestehende Karte.
                    logger.warning("%s: Abruf fehlgeschlagen (%s) -- Bestand bleibt",
                                   icao, str(e)[:60])
                    zaehler["abruf_fehler"] += 1
                    continue
                finally:
                    time.sleep(pause)

                if roh is None:
                    zaehler["kein_blatt"] += 1
                    ungepasst.append(icao)
                    continue

                neuer_hash = hashlib.sha256(roh).hexdigest()
                alt = get_aip_chart(conn, icao)

                # Regel 3: Unveraenderte Geometrie erhaelt die Passung, auch die von Hand.
                if (alt and alt["status"] == "gepasst" and passung is not None
                        and aip_charts.geometrie_gleich(alt, passung)):
                    aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), roh)
                    upsert_aip_chart(conn, icao, **{k: alt[k] for k in (
                        "nord", "sued", "west", "ost", "feld_nord", "feld_sued",
                        "feld_west", "feld_ost", "rahmen_px", "tick_px_lat",
                        "tick_px_lon", "quelle")},
                        bild_hash=neuer_hash, airac=airac or alt["airac"], status="gepasst")
                    zaehler["geometrie_unveraendert"] += 1
                    continue

                if passung is None:
                    if alt and alt["quelle"] == "hand" and alt["status"] == "gepasst":
                        logger.info("%s: Automatik scheitert, Handpassung bleibt", icao)
                        zaehler["hand_behalten"] += 1
                        continue
                    aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), roh)
                    upsert_aip_chart(
                        conn, icao, bild_hash=neuer_hash,
                        nord=0, sued=0, west=0, ost=0,
                        feld_nord=0, feld_sued=0, feld_west=0, feld_ost=0,
                        rahmen_px="", tick_px_lat=0, tick_px_lon=0,
                        quelle="auto", airac=airac or "", status="ungepasst")
                    zaehler["ungepasst"] += 1
                    ungepasst.append(icao)
                    continue

                aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), roh)
                upsert_aip_chart(
                    conn, icao, bild_hash=neuer_hash,
                    nord=passung.nord, sued=passung.sued,
                    west=passung.west, ost=passung.ost,
                    feld_nord=passung.feld_nord, feld_sued=passung.feld_sued,
                    feld_west=passung.feld_west, feld_ost=passung.feld_ost,
                    rahmen_px=passung.rahmen_px,
                    tick_px_lat=passung.tick_px_lat, tick_px_lon=passung.tick_px_lon,
                    quelle="auto", airac=airac or "", status="gepasst")
                zaehler["gepasst"] += 1
                if i % 25 == 0:
                    conn.commit()
                    logger.info("%d/%d", i, len(links))
        conn.commit()
    finally:
        conn.close()

    gesamt = sum(zaehler[k] for k in
                 ("gepasst", "geometrie_unveraendert", "hand_behalten",
                  "ungepasst", "kein_blatt", "ohne_koordinate", "abruf_fehler"))
    gut = zaehler["gepasst"] + zaehler["geometrie_unveraendert"] + zaehler["hand_behalten"]
    return {"zaehler": dict(zaehler), "gesamt": gesamt, "gepasst": gut,
            "quote": round(100 * gut / gesamt, 1) if gesamt else 0.0,
            "ungepasst": sorted(ungepasst)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nur", help="nur diese ICAO-Codes, kommagetrennt")
    ap.add_argument("--pause", type=float, default=0.4,
                    help="Pause zwischen zwei Abrufen in Sekunden (Vorgabe 0,4)")
    args = ap.parse_args()
    nur = {c.strip().upper() for c in args.nur.split(",")} if args.nur else None

    ergebnis = lauf(nur=nur, pause=args.pause)
    print(f"\n{ergebnis['gepasst']} von {ergebnis['gesamt']} gepasst "
          f"({ergebnis['quote']} %)")
    print(f"Aufschluesselung: {ergebnis['zaehler']}")
    if ergebnis["ungepasst"]:
        print(f"\nVon Hand nachzutragen ({len(ergebnis['ungepasst'])}):")
        for j in range(0, len(ergebnis["ungepasst"]), 14):
            print("   " + " ".join(ergebnis["ungepasst"][j:j + 14]))
    print("\nZum Vergleich: Der Mess-Prototyp kam am 23.08.2026 auf 91,9 Prozent "
          "(tests/fixtures/aip/messwerte.json). Weicht die Quote deutlich ab, erst melden.")


if __name__ == "__main__":
    main()
