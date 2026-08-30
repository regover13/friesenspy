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
4. **Ein handgepasstes Blatt wird trotzdem aufgefrischt**, wenn das neue Bild nachweislich
   denselben Kartenausschnitt zeigt. Sonst bleibt alles unangetastet und der Platz landet in
   ``handpassung_pruefen`` -- diese Liste nennt die Karten, deren Handpassung veraltet sein
   koennte, und **gehoert gemeldet**. Ohne Regel 4 fror jede handgepasste Karte auf dem Stand
   ihrer Handarbeit ein, denn die Automatik scheitert an ihr ja dauerhaft.

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
    HandpassungGesperrt,
    delete_aip_chart,
    get_aip_chart,
    get_aip_charts,
    get_airport_links,
    get_connection,
    upsert_aip_chart,
    verwaisen,
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


def _handblatt_auffrischen(conn, einst, icao: str, roh: bytes, airac: str | None,
                           alt: dict, zaehler, nachsehen: list[str]) -> None:
    """Das neue Bild unter eine bestehende Handpassung legen -- aber nur, wenn es dieselbe
    Karte ist.

    **Warum das noetig wurde.** Die Regel "Automatik scheitert, Handpassung bleibt" liess
    frueher auch das BILD unangetastet: Der Zweig sprang vor ``blatt_schreiben`` heraus. Da
    die Automatik an genau diesen Blaettern dauerhaft scheitert -- sonst waeren sie nicht von
    Hand gesetzt --, bekamen sie nie wieder ein neues Bild. 154 Sichtflugkarten waren damit
    auf dem Stand ihrer Handarbeit eingefroren, ohne dass irgendwo etwas auffiel.

    **Warum trotzdem nicht einfach geschrieben wird.** ``blatt_beschaffen`` liefert bei
    gescheiterter Passung das Bild der VERLINKTEN Seite. Bei 28 Plaetzen ist das nicht die
    Sichtflugkarte, sondern eine Textseite oder ein anderes Blatt desselben Kapitels -- blind
    geschrieben laege dort die falsche Karte unter einer richtigen Passung. Deshalb
    entscheidet ``blatt_auffrischen``, und im Zweifel wird nichts angefasst.
    """
    frisch = aip_charts.blatt_auffrischen(roh, alt)
    if frisch is None:
        logger.warning("%s: Blatt hat sich geaendert, zeigt aber nicht denselben Ausschnitt "
                       "wie die Handpassung -- nichts angetastet, bitte nachsehen", icao)
        zaehler["handpassung_pruefen"] += 1
        nachsehen.append(icao)
        return
    aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), frisch)
    upsert_aip_chart(conn, icao, **{k: alt[k] for k in (
        "nord", "sued", "west", "ost", "feld_nord", "feld_sued",
        "feld_west", "feld_ost", "rahmen_px", "tick_px_lat", "tick_px_lon", "quelle")},
        bild_hash=hashlib.sha256(frisch).hexdigest(),
        airac=airac or alt["airac"], status="gepasst")
    logger.info("%s: Blatt aufgefrischt, Handpassung gilt unveraendert weiter", icao)
    zaehler["hand_blatt_aufgefrischt"] += 1


def _karte_schreiben(conn, icao: str, zaehler, vorschlag_faellig: list, **felder) -> bool:
    """Passung ablegen und eine gesperrte Handpassung sauber abfangen.

    Der Lauf darf an einer gesperrten Karte nicht abbrechen: Eine Ausnahme mitten im
    Durchgang liesse die restlichen 400 Karten liegen, und der naechste Lauf finge wieder
    von vorn an. Gemeldet wird sie stattdessen -- ihr Fund wird zum Vorschlag, den der
    Admin ansehen kann.

    Rueckgabe: True, wenn geschrieben wurde. Nur dann darf der Aufrufer das BILD tauschen.
    """
    try:
        upsert_aip_chart(conn, icao, **felder)
        return True
    except HandpassungGesperrt:
        logger.info("%s: Handpassung gilt, Automatikergebnis wird nur vorgeschlagen", icao)
        zaehler["hand_gesperrt"] += 1
        vorschlag_faellig.append(icao)
        return False


def lauf(nur: set[str] | None = None, pause: float = 0.4) -> dict:
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    zaehler: collections.Counter = collections.Counter()
    ungepasst: list[str] = []
    nachsehen: list[str] = []
    vorschlag_faellig: list[str] = []
    koordinaten: dict = {}
    try:
        links = get_airport_links(conn)
        if nur:
            links = {k: v for k, v in links.items() if k in nur}

        # Regel 2: Was nicht mehr verlinkt ist, verschwindet auch aus dem Bestand.
        if not nur:
            for karte in get_aip_charts(conn, nur_gepasst=False):
                if karte["icao"] in links:
                    continue
                if karte["quelle"] == "hand":
                    # Eine Handpassung ist Arbeit eines Menschen. Sie verschwindet aus der
                    # Anzeige, aber nicht von der Platte -- Blatt und Zeile bleiben. Taucht
                    # der Link wieder auf (ein AIRAC-Wechsel benennt Kapitelseiten um),
                    # genuegt ein Setzen auf status='gepasst'.
                    if karte["status"] != "verwaist":
                        verwaisen(conn, karte["icao"])
                        logger.info("%s: Link verschwunden, Handpassung bleibt erhalten "
                                    "(status=verwaist)", karte["icao"])
                        zaehler["hand_verwaist"] += 1
                    continue
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
                        if neuer_hash != alt["bild_hash"]:
                            _handblatt_auffrischen(conn, einst, icao, roh, airac,
                                                   alt, zaehler, nachsehen)
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

                # Erst die Passung, dann das Bild. Andersherum laege bei einer gesperrten
                # Handpassung das NEUE Blatt unter der ALTEN Passung -- und genau das ist
                # die Verzerrung, die der Nutzer am 30.08.2026 verboten hat.
                geschrieben = _karte_schreiben(
                    conn, icao, zaehler, vorschlag_faellig, bild_hash=neuer_hash,
                    nord=passung.nord, sued=passung.sued,
                    west=passung.west, ost=passung.ost,
                    feld_nord=passung.feld_nord, feld_sued=passung.feld_sued,
                    feld_west=passung.feld_west, feld_ost=passung.feld_ost,
                    rahmen_px=passung.rahmen_px,
                    tick_px_lat=passung.tick_px_lat, tick_px_lon=passung.tick_px_lon,
                    quelle="auto", airac=airac or "", status="gepasst")
                if not geschrieben:
                    continue
                aip_charts.blatt_schreiben(aip_charts.blatt_pfad(einst.DB_PATH, icao), roh)
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
            "ungepasst": sorted(ungepasst),
            "handpassung_pruefen": sorted(nachsehen),
            "vorschlag_faellig": sorted(vorschlag_faellig)}


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
    if ergebnis["handpassung_pruefen"]:
        print(f"\nBlatt geaendert, Ausschnitt passt nicht zur Handpassung "
              f"({len(ergebnis['handpassung_pruefen'])}) -- nachsehen:")
        print("   " + " ".join(ergebnis["handpassung_pruefen"]))
    print("\nZum Vergleich: Der Mess-Prototyp kam am 23.08.2026 auf 91,9 Prozent "
          "(tests/fixtures/aip/messwerte.json). Weicht die Quote deutlich ab, erst melden.")


if __name__ == "__main__":
    main()
