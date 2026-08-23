#!/usr/bin/env python3
"""Einmaliges Hilfsskript: Ziffern-Schablonen aus AIP-Blaettern gewinnen.

Aufruf:  python scripts/aip_schablonen.py <verzeichnis-mit-png> [anzahl]

Ausgabe: die haeufigsten Zeichenmuster als ASCII, absteigend nach Haeufigkeit. Die Zuordnung
Muster -> Ziffer traegt ein Mensch in ``app/aip_charts._SCHABLONEN`` ein; sie laesst sich
nicht erraten, nur ansehen.

**Bruchstuecke (2x2, 2x1) und Muster mit leeren Zeilen in der Mitte sind ein Warnzeichen:**
Dann sitzt die Segmentierung noch nicht, und es waere falsch, die Schablonenliste einfach zu
verlaengern -- zuerst gehoert ``zeichen_im_band`` verbessert.

Spec: docs/superpowers/specs/2026-08-23-aip-karten-overlay-design.md, Abschnitt 3.4
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.aip_charts import (  # noqa: E402
    rahmen_finden,
    raster,
    tick_positionen,
    zeichen_im_band,
)


def sammeln(verzeichnis: str, hoechstens: int = 120) -> tuple[collections.Counter, dict]:
    zaehler: collections.Counter = collections.Counter()
    muster: dict[str, tuple] = {}
    blaetter = 0
    for pfad in sorted(Path(verzeichnis).glob("*.png"))[:hoechstens]:
        try:
            im = Image.open(pfad).convert("L")
            r = rahmen_finden(im)
            if r is None:
                continue
            ty, tx = tick_positionen(im, r)
            blaetter += 1
            for ticks, achse in ((ty, "y"), (tx, "x")):
                d, _n, _a = raster(ticks)
                for tick in ticks:
                    for gruppe in zeichen_im_band(im, r, tick, achse, d):
                        for bm in gruppe:
                            s = "/".join("".join(str(v) for v in z) for z in bm)
                            zaehler[s] += 1
                            muster.setdefault(s, bm)
        except Exception as e:  # ein kaputtes Blatt darf den Lauf nicht beenden
            print(f"   {pfad.name}: {str(e)[:60]}", file=sys.stderr)
    print(f"{blaetter} Blaetter ausgewertet", file=sys.stderr)
    return zaehler, muster


def main() -> None:
    verzeichnis = sys.argv[1] if len(sys.argv) > 1 else "/tmp/aiplauf/png"
    hoechstens = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    zaehler, muster = sammeln(verzeichnis, hoechstens)
    print(f"# {len(zaehler)} verschiedene Muster, {sum(zaehler.values())} Vorkommen")
    bruch = sum(n for s, n in zaehler.items() if len(muster[s]) < 6)
    if bruch:
        print(f"# WARNUNG: {bruch} Vorkommen sind kuerzer als 6 Zeilen -- vermutlich "
              f"Bruchstuecke. Erst die Segmentierung pruefen.")
    for s, n in zaehler.most_common(30):
        bm = muster[s]
        print(f"\n--- {n}x  {len(bm[0])}x{len(bm)} ---")
        for z in bm:
            print("    " + "".join("#" if v else "." for v in z))


if __name__ == "__main__":
    main()
