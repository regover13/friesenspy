#!/usr/bin/env python3
"""Schneidet die FSE-Planner-Daten auf Europa zu.

Quelle: https://github.com/piero-la-lune/FSE-Planner (MIT). Weltweit sind es 17 MB --
9,5 MB Flugplaetze und 7,5 MB Zonen. Fuer FriesenSpy reicht Europa, und von den Feldern
brauchen wir nur einen Bruchteil.

Aufruf:  python3 scripts/fse_zuschnitt.py /pfad/zum/FSE-Planner-klon
"""
import json
import sys
from pathlib import Path

# Europa grosszuegig: Island bis Ural, Kanaren bis Nordkap
LAT = (35.0, 72.0)
LON = (-25.0, 45.0)
ZIEL = Path(__file__).resolve().parents[1] / "app" / "static" / "data"


def echte_msfs(eintrag):
    """Im Rohdatensatz steht [None] bei Plaetzen ohne MSFS-Entsprechung -- eine nichtleere
    Liste, die bei einer truthiness-Pruefung faelschlich als 'vorhanden' durchgeht."""
    return [x for x in (eintrag.get("msfs") or []) if x]


def main(klon):
    klon = Path(klon)
    plaetze = json.loads((klon / "src" / "data" / "icaodata.json").read_text(encoding="utf-8"))
    zonen = json.loads((klon / "public" / "data" / "zones.json").read_text(encoding="utf-8"))

    drin = {k: v for k, v in plaetze.items()
            if LAT[0] <= v["lat"] <= LAT[1] and LON[0] <= v["lon"] <= LON[1]}
    schlank = {k: {"lat": v["lat"], "lon": v["lon"], "name": v["name"],
                   "msfs": echte_msfs(v), "rwy": v["runway"], "surface": v["surface"],
                   "elev": v["elev"]}
               for k, v in drin.items()}
    zs = {k: zonen[k] for k in drin if k in zonen}

    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / "fse_airports_eu.json").write_text(
        json.dumps(schlank, separators=(",", ":")), encoding="utf-8")
    (ZIEL / "fse_zones_eu.json").write_text(
        json.dumps(zs, separators=(",", ":")), encoding="utf-8")
    print(f"{len(schlank)} Plaetze, {len(zs)} Zonen geschrieben")


if __name__ == "__main__":
    main(sys.argv[1])
