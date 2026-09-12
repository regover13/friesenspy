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
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HAEPPCHEN = 500


def anmelden(server: str, passwort: str):
    """Erst anmelden, dann arbeiten -- wie der Browser auch.

    ⚠ Das Passwort im Klartext als Cookie zu schicken reicht NICHT: `require_admin` prueft ein
    SIGNIERTES Token (`verify_admin_token`), nicht das Passwort. Der erste Anlauf am
    12.09.2026 endete deshalb mit `401 Admin-Login erforderlich`.

    Der Login-Endpunkt setzt das Token als httponly-Cookie; ein `CookieJar` nimmt es
    entgegen und schickt es bei jeder weiteren Anfrage mit.
    """
    jar = http.cookiejar.CookieJar()
    oeffner = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        server.rstrip("/") + "/api/admin/login",
        data=json.dumps({"password": passwort}).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"})
    with oeffner.open(req, timeout=30) as r:
        r.read()
    return oeffner


def hochladen(oeffner, server: str, eintraege: list[dict]) -> int:
    gesamt = 0
    for i in range(0, len(eintraege), HAEPPCHEN):
        teil = eintraege[i:i + HAEPPCHEN]
        rumpf = json.dumps({"eintraege": teil}).encode("utf-8")
        req = urllib.request.Request(
            server.rstrip("/") + "/api/admin/bruegge/katalog",
            data=rumpf, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with oeffner.open(req, timeout=60) as r:
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
    try:
        oeffner = anmelden(a.server, a.passwort)
    except urllib.error.HTTPError as e:
        print(f"Anmeldung fehlgeschlagen: HTTP {e.code} — {e.read()[:200]!r}")
        return 1
    n = hochladen(oeffner, a.server, eintraege)
    print(f"\n{n} eingetragen.")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
