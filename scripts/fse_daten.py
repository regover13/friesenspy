#!/usr/bin/env python3
"""Bereitet die FSE-Planner-Daten fuer FriesenSpy auf -- weltweit oder auf Europa zugeschnitten.

Quelle: https://github.com/piero-la-lune/FSE-Planner (MIT), Dateien ``src/data/icaodata.json``
(9,1 MB) und ``public/data/zones.json`` (7,2 MB). Von den Feldern brauchen wir nur einen
Bruchteil; die Zonen sind reine Polygonzuege und lassen sich nur ueber die Genauigkeit der
Koordinaten verkleinern.

**Warum es diese Datei zusaetzlich zu fse_zuschnitt.py gibt.** Der Zuschnitt auf Europa war
eine Notloesung gegen die Zeichenlast: Alle Plaetze liegen gleichzeitig in der Karte, und
Leaflet setzt bei jeder Kartenbewegung jeden Pfad neu -- bei 2.335 Plaetzen war das schon
spuerbar, bei 23.780 waere es unbenutzbar. Der Zuschnitt hat das Symptom bekaempft und dabei
den Datenbestand beschnitten (Nutzer-Entscheidung 16.08.2026: es werden alle gebraucht).

Der richtige Hebel ist stattdessen, **serverseitig nur den sichtbaren Ausschnitt zu liefern**
-- so wie ``/api/traffic?lat=&lon=&r=`` es fuer den Verkehr laengst tut. Dann ist der Umfang
des Bestands gleichgueltig, und das Kniebrett sieht nie mehr als ein paar hundert Eintraege.
Diese Datei erzeugt die Grundlage dafuer: den vollstaendigen Bestand, serverseitig abgelegt.

Ablage: ``app/data/fse/`` -- bewusst NICHT unter ``app/static/``. Was dort liegt, wird als
Ganzes ausgeliefert; genau das soll hier nicht passieren.

Aufruf::

    python3 scripts/fse_daten.py /pfad/zum/FSE-Planner-klon          # weltweit
    python3 scripts/fse_daten.py /pfad/zum/FSE-Planner-klon --europa # wie bisher

Ohne Klon geht es auch direkt von GitHub::

    python3 scripts/fse_daten.py --laden
"""
import json
import sys
import urllib.request
from pathlib import Path

# Europa grosszuegig: Island bis Ural, Kanaren bis Nordkap.
LAT = (35.0, 72.0)
LON = (-25.0, 45.0)

ZIEL = Path(__file__).resolve().parents[1] / "app" / "data" / "fse"

ROH_PLAETZE = ("https://raw.githubusercontent.com/piero-la-lune/FSE-Planner"
               "/master/src/data/icaodata.json")
ROH_ZONEN = ("https://raw.githubusercontent.com/piero-la-lune/FSE-Planner"
             "/master/public/data/zones.json")

# Die Zonen werden UNVERAENDERT uebernommen, Koordinate fuer Koordinate.
#
# Hier stand kurzzeitig eine Rundung auf vier Nachkommastellen. Sie ist raus -- aus zwei
# Gruenden, und der zweite ist der wichtigere:
#
# 1. Sie war wirkungslos. Die Rohdaten des FSE-Planners haben bereits hoechstens vier
#    Nachkommastellen (nachgemessen ueber alle Polygone). Die Rundung hat nie etwas entfernt;
#    dass die Datei von 7,2 auf 3,2 MB faellt, liegt allein am kompakten Schreiben
#    (separators ohne Leerzeichen).
# 2. Sie waere auch dann falsch gewesen. Das Problem dieser Ebene ist die ZEICHENLAST, nicht
#    die Dateigroesse (Nutzer-Entscheidung 16.08.2026). Genauigkeit wegzuwerfen, um ein
#    Problem zu lindern, das man gar nicht hat, ist ein schlechter Tausch -- und nachholen
#    laesst er sich jederzeit, falls es wirklich einmal zu langsam wird.


def echte_msfs(eintrag):
    """Im Rohdatensatz steht ``[None]`` bei Plaetzen ohne MSFS-Entsprechung -- eine nichtleere
    Liste, die bei einer truthiness-Pruefung faelschlich als "vorhanden" durchgeht."""
    return [x for x in (eintrag.get("msfs") or []) if x]


def laden(url):
    with urllib.request.urlopen(url) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


def in_europa(eintrag):
    return (LAT[0] <= eintrag["lat"] <= LAT[1]
            and LON[0] <= eintrag["lon"] <= LON[1])


def schreiben(pfad, daten):
    pfad.write_text(json.dumps(daten, separators=(",", ":")), encoding="utf-8")
    return pfad.stat().st_size


def main(argumente):
    nur_europa = "--europa" in argumente
    von_github = "--laden" in argumente
    klon = next((a for a in argumente if not a.startswith("--")), None)

    if von_github or klon is None:
        print("Lade die Rohdaten von GitHub ...")
        plaetze = laden(ROH_PLAETZE)
        zonen = laden(ROH_ZONEN)
    else:
        wurzel = Path(klon)
        plaetze = json.loads((wurzel / "src" / "data" / "icaodata.json")
                             .read_text(encoding="utf-8"))
        zonen = json.loads((wurzel / "public" / "data" / "zones.json")
                           .read_text(encoding="utf-8"))

    if nur_europa:
        plaetze = {k: v for k, v in plaetze.items() if in_europa(v)}

    schlank = {k: {"lat": v["lat"], "lon": v["lon"], "name": v["name"],
                   "msfs": echte_msfs(v), "rwy": v["runway"], "surface": v["surface"],
                   "elev": v["elev"]}
               for k, v in plaetze.items()}
    zs = {k: zonen[k] for k in plaetze if k in zonen}

    ZIEL.mkdir(parents=True, exist_ok=True)
    endung = "eu" if nur_europa else "world"
    a = schreiben(ZIEL / f"fse_airports_{endung}.json", schlank)
    b = schreiben(ZIEL / f"fse_zones_{endung}.json", zs)

    print(f"{len(schlank)} Plaetze  ({a / 1024 / 1024:.2f} MB)")
    print(f"{len(zs)} Zonen     ({b / 1024 / 1024:.2f} MB)")
    print(f"geschrieben nach {ZIEL}")


if __name__ == "__main__":
    main(sys.argv[1:])
