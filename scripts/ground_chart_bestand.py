#!/usr/bin/env python3
"""Erstbefuellung und Auffrischung des Flugplatzkarten-Bestands.

Aufruf:  python scripts/ground_chart_bestand.py [--nur EDDL,EDDM] [--pause 0.4]
                                                [--nur-melden]

**Zwei Betriebsarten, und das ist der Kern dieses Skripts.**

``lauf()`` rechnet Passungen -- das ist die Erstbefuellung. Sie geschieht **einmal**, unter
Aufsicht, und ihre Ergebnisse werden angesehen, bevor sie gelten.

``melden()`` rechnet nichts. Es vergleicht nur den ``quell_hash`` des Rohblatts und traegt
jede Aenderung als offenen Punkt ein. Das ist die Betriebsart des Wochenjobs.

**Warum die Trennung.** Die Passung ueber die Bahngeometrie traegt, wo sie traegt: An
31 Blaettern gemessen kamen vier durch die Pruefkette, die uebrigen wurden abgewiesen --
meist, weil Stopways und Blast Pads in derselben Grauabstufung an die Bahn anschliessen und
mitgemessen werden (EDDV: 2784 m fuer eine 2340-m-Bahn). Eine Automatik, die woechentlich
ueber alles laeuft, wuerde daran nichts besser machen, aber jede Woche dieselbe Arbeit tun
und dabei ueber 1000 Seiten von aip.dfs.de holen.

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

from app import aip_charts, ground_charts, runway_ref  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import (  # noqa: E402
    HandpassungGesperrt,
    get_airport_links,
    get_connection,
    get_ground_chart,
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


def platz_bearbeiten(icao: str, kapitel_url: str, holen, csv_pfad, db_path: str,
                     pause: float = 0.3, schranke: float | None = None) -> dict:
    """Ein Platz: Blaetter holen, passen, das beste ablegen.

    Rueckgabe ist ein Bericht -- was gefunden, was gepasst, was abgewiesen wurde. Er ist
    fuer die Erstbefuellung gedacht, bei der ein Mensch die Ergebnisse ansieht.
    """
    from PIL import Image
    import io as _io

    bericht = {"icao": icao, "blaetter": [], "gewaehlt": None}
    bahnen = runway_ref.bahnen(icao, csv_pfad)
    if not bahnen:
        bericht["grund"] = "keine Schwellenkoordinaten"
        return bericht
    try:
        seiten = aip_charts.seiten_des_kapitels(kapitel_url, holen)
    except Exception as e:
        bericht["grund"] = f"Kapitel nicht erreichbar: {str(e)[:50]}"
        return bericht

    beste = None
    for url, roh, sorte, ton in kandidaten(seiten, holen, pause):
        im = Image.open(_io.BytesIO(roh)).convert("L")
        # Die Schranke laesst sich anheben -- fuer Blaetter, die ein Mensch angesehen und
        # fuer gut befunden hat. EDDH kam am 31.08.2026 auf 15,6 m: sechs Zentimeter ueber
        # der Vorgabe, bei Achsen, die im markierten Bild exakt auf beiden Bahnen lagen.
        # Eine solche Karte wegen 0,6 m zu verwerfen waere Buchhaltung, nicht Sorgfalt.
        alte_schranke = ground_charts.REST_SCHRANKE_M
        if schranke is not None:
            ground_charts.REST_SCHRANKE_M = schranke
        try:
            passung = ground_charts.passung_rechnen(im, bahnen, ton)
        except Exception as e:
            logger.info("%s: Passung geworfen (%s)", icao, str(e)[:60])
            passung = None
        finally:
            ground_charts.REST_SCHRANKE_M = alte_schranke
        eintrag = {"url": url, "sorte": sorte, "ton": ton,
                   "rest": None if passung is None else round(passung.rest_max, 2),
                   "bahnen": 0 if passung is None else passung.bahnen}
        bericht["blaetter"].append(eintrag)
        if passung is None:
            continue
        # Erst nach Sorte (Rollkarte vorn), dann nach Restfehler.
        schluessel = (_VORRANG.get(sorte, 9), passung.rest_max)
        if beste is None or schluessel < beste[0]:
            beste = (schluessel, url, roh, sorte, passung)

    if beste is None:
        bericht["grund"] = "keine Passung bestand die Pruefkette"
        return bericht

    _s, url, roh, sorte, passung = beste
    genordet = ground_charts.norden(roh, passung)
    if genordet is None:
        bericht["grund"] = "Nordung fehlgeschlagen"
        return bericht
    bild, grenzen = genordet
    ziel = blatt_pfad(db_path, icao)
    aip_charts.blatt_schreiben(ziel, bild)
    bericht["gewaehlt"] = {
        "url": url, "sorte": sorte, "rest": round(passung.rest_max, 2),
        "bahnen": passung.bahnen, "drehung": round(passung.drehung, 2),
        "mps": round(passung.mps, 4), "grenzen": grenzen,
        "quell_hash": hashlib.sha256(roh).hexdigest(),
        "bild_hash": hashlib.sha256(bild).hexdigest(),
        "airac": aip_charts.airac_kennung(url) or "",
    }
    return bericht


def _offen_vermerken(conn, icao: str, bericht: dict, db_path: str) -> None:
    """Einen Platz als offenen Punkt eintragen: Blaetter da, Passung nicht bestanden.

    Die Zeile traegt Nullen in allen Zahlenfeldern und ``status='ungepasst'`` -- das ist
    ehrlich: Es gibt keine bekannte Lage. ``get_ground_charts()`` filtert sie aus der
    Auslieferung, der Admin sieht sie.

    ``quelle='auto'`` und NICHT 'hand': 'hand' hiesse "von einem Menschen gesetzt" und
    wuerde die Zeile fuer immer gegen jeden spaeteren Lauf sperren, ohne je Handarbeit zu
    enthalten. Genau diese Fehlbenennung ist am 31.08.2026 bei den Sichtflugkarten behoben
    worden.
    """
    beste_sorte = (bericht["blaetter"][0]["sorte"] if bericht["blaetter"]
                   else "flugplatzkarte")
    beste_url = bericht["blaetter"][0]["url"] if bericht["blaetter"] else ""
    try:
        upsert_ground_chart(
            conn, icao, sorte=beste_sorte, seite_url=beste_url,
            quell_hash="", bild_hash="",
            nord=0.0, sued=0.0, west=0.0, ost=0.0,
            feld_nord=0.0, feld_sued=0.0, feld_west=0.0, feld_ost=0.0,
            drehung=0.0, mps=0.0, rest_max=0.0, bahnen=0,
            quelle="auto", airac="", status="ungepasst")
    except HandpassungGesperrt:
        pass          # eine bestehende Handpassung wird davon nicht angeruehrt


def ablegen(conn, icao: str, gewaehlt: dict, quelle: str = "auto") -> bool:
    """Einen Bericht in die Tabelle schreiben. ``False``, wenn eine Handpassung sperrt."""
    g = gewaehlt["grenzen"]
    try:
        upsert_ground_chart(
            conn, icao, sorte=gewaehlt["sorte"], seite_url=gewaehlt["url"],
            quell_hash=gewaehlt["quell_hash"], bild_hash=gewaehlt["bild_hash"],
            nord=g["nord"], sued=g["sued"], west=g["west"], ost=g["ost"],
            feld_nord=g["feld_nord"], feld_sued=g["feld_sued"],
            feld_west=g["feld_west"], feld_ost=g["feld_ost"],
            drehung=gewaehlt["drehung"], mps=gewaehlt["mps"],
            rest_max=gewaehlt["rest"], bahnen=gewaehlt["bahnen"],
            quelle=quelle, airac=gewaehlt["airac"], status="gepasst")
        return True
    except HandpassungGesperrt:
        logger.info("%s: Handpassung gilt, Automatikergebnis wird nur vorgeschlagen", icao)
        vorschlag_anlegen(conn, "ground", icao, gewaehlt["quell_hash"],
                          {k: gewaehlt[k] for k in ("sorte", "url", "rest", "bahnen",
                                                    "drehung", "mps", "airac")},
                          "Automatik weicht von der Handpassung ab")
        return False


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
         schreiben: bool = True, quelle: str = "auto",
         schranke: float | None = None) -> dict:
    """Erstbefuellung: Passungen rechnen und ablegen.

    ``schreiben=False`` rechnet nur und berichtet -- fuer den Blick vor der Uebernahme.
    ``quelle="hand"`` legt die Ergebnisse als Handpassung ab; dann sind sie durch die
    Sperre geschuetzt und kein spaeterer Lauf kann sie anfassen.
    """
    einst = get_settings()
    csv_pfad = runway_ref.datei_holen(Path(einst.DB_PATH).parent / "runways.csv")
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
                b = platz_bearbeiten(icao, url, holen, csv_pfad, einst.DB_PATH, pause,
                                     schranke)
                berichte.append(b)
                if b["gewaehlt"] is None:
                    zaehler[b.get("grund", "unbekannt")[:30]] += 1
                    # **Als offenen Punkt ablegen, nicht schweigend uebergehen.** Ein Platz
                    # mit Kandidatenblaettern, deren Passung die Pruefkette nicht bestand,
                    # ist genau der Fall, den der Nutzer im Admin abarbeiten will
                    # (Entscheidung 30.08.2026: "Sie sollen dann einfach als nur offene
                    # angezeigt werden"). Ohne Zeile erschiene er nirgends.
                    if schreiben and b["blaetter"]:
                        _offen_vermerken(conn, icao, b, einst.DB_PATH)
                        zaehler["offen"] += 1
                    continue
                zaehler["gepasst"] += 1
                if schreiben:
                    if ablegen(conn, icao, b["gewaehlt"], quelle):
                        zaehler["geschrieben"] += 1
                    else:
                        zaehler["hand_gesperrt"] += 1
                if i % 10 == 0:
                    conn.commit()
                    logger.info("%d/%d", i, len(links))
        conn.commit()
    finally:
        conn.close()
    return {"zaehler": dict(zaehler), "berichte": berichte,
            "gepasst": zaehler["gepasst"], "gesamt": len(berichte)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nur", default="")
    p.add_argument("--pause", type=float, default=0.3)
    p.add_argument("--nur-melden", action="store_true",
                   help="nichts rechnen, nur geaenderte Blaetter melden")
    p.add_argument("--trocken", action="store_true", help="rechnen, aber nicht schreiben")
    p.add_argument("--schranke", type=float, default=None,
                   help="Restfehler-Schranke in Metern anheben (nur nach Augenschein)")
    p.add_argument("--als-hand", action="store_true",
                   help="Ergebnisse als Handpassung ablegen (gegen spaetere Laeufe gesperrt)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.nur_melden:
        e = melden(a.pause)
        print(f"geaendert: {len(e['geaendert'])} -- {' '.join(e['geaendert'])}")
        print(e["zaehler"])
        return
    nur = {x.strip().upper() for x in a.nur.split(",") if x.strip()} or None
    e = lauf(nur, a.pause, schreiben=not a.trocken,
             quelle="hand" if a.als_hand else "auto", schranke=a.schranke)
    print(f"gepasst: {e['gepasst']} von {e['gesamt']}")
    print(e["zaehler"])
    for b in e["berichte"]:
        if b["gewaehlt"]:
            g = b["gewaehlt"]
            print(f"  {b['icao']}: {g['sorte']:15s} Rest={g['rest']:6.2f} m  "
                  f"Bahnen={g['bahnen']}  Drehung={g['drehung']:6.2f}")
        else:
            print(f"  {b['icao']}: -- {b.get('grund', '?')} "
                  f"({len(b['blaetter'])} Kandidatenblaetter)")


if __name__ == "__main__":
    main()
