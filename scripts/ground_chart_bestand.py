#!/usr/bin/env python3
"""Erstbefuellung und Auffrischung des Flugplatzkarten-Bestands.

Aufruf:  python scripts/ground_chart_bestand.py [--nur EDDL,EDDM] [--pause 0.4]
                                                [--nur-melden]

**Zwei Betriebsarten, und das ist der Kern dieses Skripts.**

``lauf()`` beschafft Blaetter und traegt sie als offene Punkte ein. Es **passt nichts** --
die Lage setzt ein Mensch im Admin.

``melden()`` rechnet nichts. Es vergleicht nur den ``quell_hash`` des Rohblatts und traegt
jede Aenderung als offenen Punkt ein. Das ist die Betriebsart des Wochenjobs.

**Warum keine Automatik.** Ein erster Anlauf hat die Lage aus der Bahngeometrie gerechnet
und kam ueber drei von 107 Plaetzen nicht hinaus -- 271 der 446 Plaetze haben gar keine
Schwellenkoordinaten, und wo es sie gibt, verlaengern gleichfarbige Stopways die Messung
(EDDV: 2784 m fuer eine 2340-m-Bahn). Der Verlauf steht in scripts/ground_chart_probe.py.

Der Nutzer hat deshalb am 30.08.2026 entschieden: die Blaetter einmal von Hand passen,
Aenderungen danach nur melden. Wortlaut: "Das ist dann eine einmalige Anpassung. Updates
kommen nur selten. Die spaeteren Updates kann ich dann Manuel unter admin abarbeiten. Sie
sollen dann einfach als nur offene angezeigt werden."

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md
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

from app import aip_charts, ground_charts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import (  # noqa: E402
    HandpassungGesperrt,
    get_airport_links,
    get_connection,
    get_ground_charts,
    upsert_ground_chart,
    vorschlag_anlegen,
)

logger = logging.getLogger("ground_chart_bestand")

_UA = {"User-Agent": "FriesenSpy/AIP-Kartenabgleich (+https://friesenspy.devprops.de)"}

# Die Rollkarte hat Vorrang: Sie traegt beim Rollen mehr (Rollleitlinien farbcodiert,
# Haltepunkte, Standplaetze einzeln nummeriert). Fehlt sie, tritt die Flugplatzkarte an
# ihre Stelle. Im Ebenen-Menue steht deshalb nur EIN Eintrag.
_VORRANG = {"rollkarte": 0, "flugplatzkarte": 1}


def blatt_pfad(db_path: str, icao: str) -> Path:
    """Wo ein genordetes Flugplatzblatt liegt.

    Eigenes Verzeichnis: ``<db>/aip/<ICAO>.png`` ist von den Sichtflugkarten belegt.
    """
    return (Path(db_path).parent / "aip_ground"
            / f"{(icao or '').strip().upper()}.png")


def _hole(client: httpx.Client):
    def holen(url: str) -> str:
        r = client.get(url, headers=_UA, timeout=40.0)
        r.raise_for_status()
        return r.text
    return holen


def kandidaten(html_seiten: list[str], holen, pause: float = 0.3):
    """Aus den Kapitelseiten die Flugplatz- und Rollkarten heraussuchen.

    Liefert Tupel ``(url, roh, sorte, ton)``. Seiten ohne Bild oder ohne Bahnfarbe fallen
    weg -- das sind Textseiten, Anflugkarten und dergleichen.
    """
    from PIL import Image
    import io as _io

    aus = []
    for url in html_seiten:
        try:
            roh = aip_charts.bild_aus_html(holen(url))
        except Exception:
            continue
        finally:
            time.sleep(pause)
        if roh is None:
            continue
        try:
            im = Image.open(_io.BytesIO(roh)).convert("L")
        except Exception:
            continue
        ton = ground_charts.bahnfarbe(im)
        sorte = ground_charts.sorte_aus_ton(ton)
        if sorte is None:
            continue
        aus.append((url, roh, sorte, ton))
    return aus


def platz_bearbeiten(icao: str, kapitel_url: str, holen, db_path: str,
                     pause: float = 0.3) -> dict:
    """Ein Platz: Kandidatenblaetter holen und das beste ROH ablegen.

    **Gepasst wird hier nichts.** Die Automatik ist am 31.08.2026 zurueckgebaut worden --
    sie kam ueber drei von 107 Plaetzen nicht hinaus. Dieses Skript sorgt nur noch dafuer,
    dass das richtige Blatt vorliegt; die Lage setzt ein Mensch im Admin.

    Das Blatt wird UNGEDREHT abgelegt: Es gibt noch keine bekannte Nordung, und der Admin
    klickt auf dem Rohblatt. Gedreht wird erst beim Speichern der Handpassung.

    Die Rollkarte hat Vorrang, wo es beide gibt -- sie traegt beim Rollen mehr.
    """
    from PIL import Image
    import io as _io

    bericht = {"icao": icao, "blaetter": [], "gewaehlt": None}
    try:
        seiten = aip_charts.seiten_des_kapitels(kapitel_url, holen)
    except Exception as e:
        bericht["grund"] = f"Kapitel nicht erreichbar: {str(e)[:50]}"
        return bericht

    beste = None
    for url, roh, sorte, ton in kandidaten(seiten, holen, pause):
        im = Image.open(_io.BytesIO(roh)).convert("L")
        bericht["blaetter"].append({"url": url, "sorte": sorte, "ton": ton,
                                    "groesse": im.size})
        schluessel = (_VORRANG.get(sorte, 9), -im.size[0] * im.size[1])
        if beste is None or schluessel < beste[0]:
            beste = (schluessel, url, roh, sorte)

    if beste is None:
        bericht["grund"] = "kein Blatt in Flugplatzkarten-Farbe"
        return bericht

    _s, url, roh, sorte = beste
    # Als ".roh.png" ablegen, NICHT unter dem Auslieferungsnamen: Das Rohblatt ist
    # ungedreht und noch ohne Lage. Der Admin klickt darauf; erst seine Passung erzeugt das
    # genordete Blatt, das ausgeliefert wird.
    aip_charts.blatt_schreiben(blatt_pfad(db_path, icao).with_name(f"{icao}.roh.png"), roh)
    bericht["gewaehlt"] = {
        "url": url, "sorte": sorte,
        "quell_hash": hashlib.sha256(roh).hexdigest(),
        "airac": aip_charts.airac_kennung(url) or "",
    }
    return bericht


def blatt_vermerken(conn, icao: str, gewaehlt: dict) -> None:
    """Ein beschafftes Blatt eintragen -- ungepasst, mit Nullen in allen Lagefeldern.

    Das ist ehrlich: Es gibt keine bekannte Lage. ``get_ground_charts()`` filtert die Zeile
    aus der Auslieferung, der Admin sieht sie als offenen Punkt und passt sie.

    ``quelle='auto'`` und NICHT 'hand': 'hand' hiesse "von einem Menschen gesetzt" und
    wuerde die Zeile fuer immer gegen jeden spaeteren Lauf sperren, ohne je Handarbeit zu
    enthalten. Genau diese Fehlbenennung ist am 31.08.2026 bei den Sichtflugkarten behoben
    worden.
    """
    try:
        upsert_ground_chart(
            conn, icao, sorte=gewaehlt["sorte"], seite_url=gewaehlt["url"],
            quell_hash=gewaehlt["quell_hash"], bild_hash="",
            nord=0.0, sued=0.0, west=0.0, ost=0.0,
            feld_nord=0.0, feld_sued=0.0, feld_west=0.0, feld_ost=0.0,
            drehung=0.0, mps=0.0, rest_max=0.0, bahnen=0,
            quelle="auto", airac=gewaehlt["airac"], status="ungepasst")
    except HandpassungGesperrt:
        # Eine bestehende Handpassung wird davon nicht angeruehrt. Das neue Blatt liegt
        # trotzdem auf der Platte -- melden() traegt es als Vorschlag ein.
        logger.info("%s: Handpassung gilt, Blatt bleibt unberuehrt", icao)


def melden(pause: float = 0.4) -> dict:
    """Betriebsart des Wochenjobs: **nichts rechnen, nur Aenderungen melden.**

    Fuer jede abgelegte Karte wird ihre gemerkte Seite geholt und der ``quell_hash``
    verglichen. Weicht er ab, ist das Blatt neu und der Platz wird als offener Punkt
    eingetragen -- der Nutzer arbeitet ihn im Admin ab.

    Das kostet zwei Abrufe je Karte statt eines vollen Kapiteldurchlaufs mit Bildanalyse,
    und es kann per Bauart keine bestehende Passung beschaedigen.
    """
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    zaehler: collections.Counter = collections.Counter()
    geaendert: list[str] = []
    try:
        karten = get_ground_charts(conn, nur_gepasst=False)
        with httpx.Client(follow_redirects=True) as client:
            holen = _hole(client)
            for k in karten:
                if not k["seite_url"]:
                    zaehler["ohne_seite"] += 1
                    continue
                try:
                    roh = aip_charts.bild_aus_html(holen(k["seite_url"]))
                except Exception as e:
                    logger.info("%s: Seite nicht erreichbar (%s)", k["icao"], str(e)[:50])
                    zaehler["abruf_fehler"] += 1
                    continue
                finally:
                    time.sleep(pause)
                if roh is None:
                    zaehler["kein_bild"] += 1
                    continue
                neu = hashlib.sha256(roh).hexdigest()
                if neu == k["quell_hash"]:
                    zaehler["unveraendert"] += 1
                    continue
                # Das neue Rohblatt daneben legen, damit der Admin es ansehen kann.
                aip_charts.blatt_schreiben(
                    blatt_pfad(einst.DB_PATH, k["icao"]).with_name(
                        f"{k['icao']}.ground.{neu[:12]}.png"), roh)
                vorschlag_anlegen(
                    conn, "ground", k["icao"], neu,
                    {"sorte": k["sorte"], "url": k["seite_url"],
                     "airac": aip_charts.airac_kennung(k["seite_url"]) or ""},
                    "Neues Blatt bei der DFS -- Passung von Hand pruefen")
                zaehler["geaendert"] += 1
                geaendert.append(k["icao"])
        conn.commit()
    finally:
        conn.close()
    return {"zaehler": dict(zaehler), "geaendert": sorted(geaendert),
            "gesamt": sum(zaehler.values())}


def lauf(nur: set[str] | None = None, pause: float = 0.3,
         schreiben: bool = True) -> dict:
    """Blaetter beschaffen und als offene Punkte eintragen. Passt nichts."""
    einst = get_settings()
    conn = get_connection(einst.DB_PATH)
    berichte = []
    zaehler: collections.Counter = collections.Counter()
    try:
        links = get_airport_links(conn)
        if nur:
            links = {k: v for k, v in links.items() if k in nur}
        with httpx.Client(follow_redirects=True) as client:
            holen = _hole(client)
            for i, (icao, url) in enumerate(sorted(links.items()), 1):
                b = platz_bearbeiten(icao, url, holen, einst.DB_PATH, pause)
                berichte.append(b)
                if b["gewaehlt"] is None:
                    zaehler[b.get("grund", "unbekannt")[:32]] += 1
                    continue
                zaehler[b["gewaehlt"]["sorte"]] += 1
                if schreiben:
                    blatt_vermerken(conn, icao, b["gewaehlt"])
                if i % 10 == 0:
                    conn.commit()
                    logger.info("%d/%d", i, len(links))
        conn.commit()
    finally:
        conn.close()
    mit_blatt = sum(1 for b in berichte if b["gewaehlt"])
    return {"zaehler": dict(zaehler), "berichte": berichte,
            "mit_blatt": mit_blatt, "gesamt": len(berichte)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nur", default="")
    p.add_argument("--pause", type=float, default=0.3)
    p.add_argument("--nur-melden", action="store_true",
                   help="nichts beschaffen, nur geaenderte Blaetter melden")
    p.add_argument("--trocken", action="store_true",
                   help="holen und berichten, aber nichts eintragen")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.nur_melden:
        e = melden(a.pause)
        print(f"geaendert: {len(e['geaendert'])} -- {' '.join(e['geaendert'])}")
        print(e["zaehler"])
        return
    nur = {x.strip().upper() for x in a.nur.split(",") if x.strip()} or None
    e = lauf(nur, a.pause, schreiben=not a.trocken)
    print(f"Blaetter gefunden: {e['mit_blatt']} von {e['gesamt']}")
    print(e["zaehler"])
    for b in e["berichte"]:
        if b["gewaehlt"]:
            g = b["gewaehlt"]
            print(f"  {b['icao']}: {g['sorte']:15s} {g['url'][-24:]}")


if __name__ == "__main__":
    main()
