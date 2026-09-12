# -*- coding: utf-8 -*-
"""Schiebt `katalog.json` in die Tabelle `bruegge_katalog` auf dem Server.

    python katalog_hochladen.py --passwort GEHEIM
    python katalog_hochladen.py --passwort GEHEIM --server http://localhost:8091

Gegenstück zu `katalog_sammeln.py`. Getrennt, weil das Sammeln auf dem Rechner des Piloten
laufen muss (dort liegen die `sim.cfg`) und das Hochladen ein Admin-Passwort braucht.

**In Häppchen**, weil ein Katalog rund 2800 Einträge hat: Eine Anfrage mit allem auf einmal
wäre mehrere Megabyte, und wenn sie scheitert, ist nichts angekommen. So bleibt nach einem
Abbruch, was schon drin ist — der Endpunkt lässt sich beliebig oft aufrufen, vorhandene
Prüfergebnisse überschreibt er nicht.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HAEPPCHEN = 500


def hochladen(server: str, passwort: str, eintraege: list[dict]) -> int:
    # Das Admin-Passwort geht als Cookie mit -- denselben Weg nimmt der Browser.
    # `make_admin_token` steht auf dem Server; hier genuegt das Passwort im Klartext, weil
    # `require_admin` beides akzeptiert.
    gesamt = 0
    for i in range(0, len(eintraege), HAEPPCHEN):
        teil = eintraege[i:i + HAEPPCHEN]
        rumpf = json.dumps({"eintraege": teil}).encode("utf-8")
        req = urllib.request.Request(
            server.rstrip("/") + "/api/admin/bruegge/katalog",
            data=rumpf, method="POST",
            headers={"Content-Type": "application/json",
                     "Cookie": "fs_admin=" + passwort})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                antwort = json.load(r)
        except urllib.error.HTTPError as e:
            print(f"  Häppchen {i//HAEPPCHEN + 1}: HTTP {e.code} — {e.read()[:200]!r}")
            return gesamt
        except urllib.error.URLError as e:
            print(f"  Häppchen {i//HAEPPCHEN + 1}: {e}")
            return gesamt
        gesamt += antwort.get("eingetragen", 0)
        print(f"  Häppchen {i//HAEPPCHEN + 1}: {antwort.get('eingetragen')} eingetragen"
              + (f", {antwort['verworfen']} verworfen" if antwort.get("verworfen") else ""))
    return gesamt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datei", default="katalog.json")
    ap.add_argument("--server", default="https://friesenspy.devprops.de")
    ap.add_argument("--passwort", required=True, help="ADMIN_PASSWORD")
    a = ap.parse_args()

    eintraege = json.loads(Path(a.datei).read_text(encoding="utf-8"))
    print(f"{len(eintraege)} Einträge aus {a.datei} nach {a.server}")
    n = hochladen(a.server, a.passwort, eintraege)
    print(f"\n{n} eingetragen.")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
