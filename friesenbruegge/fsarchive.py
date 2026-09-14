# -*- coding: utf-8 -*-
"""Liest SimObject-Titel aus MSFS' `.fsarchive`-Dateien — den gestreamten Paketen.

⭐ **WOZU, UND WARUM ES DIE MÜHE WERT WAR** (14.09.2026)

Die Standardobjekte von MSFS 2024 sind **gestreamt**: Auf der Platte liegen nur
256-kB-Platzhalter, und im ganzen Bestand steht **keine einzige** `sim.cfg` als gewöhnliche
Datei. `katalog_sammeln.py` hat daraus die Titel **geraten** — es nahm den Paketnamen und
schrieb „Titel unbekannt (Paket gestreamt, kein entpackter Ordner)" dazu.

Das musste schiefgehen, und es ging schief:

    deer_o_hemionus                     EXCEPTION_22 — CREATE_OBJECT_FAILED
    reindeer_r_tarandus_groenlandicus   EXCEPTION_22 — CREATE_OBJECT_FAILED

Der Nutzer hat den Befund nicht geglaubt (*„MSFS muss auch einen Hirsch haben!"*) — zu
Recht. MSFS hat zwei, sie heißen nur anders: `CElaphusCanadensisMale` (Wapiti) und
`AAlcesMale` (Elch). Die geratenen Namen waren **Paket**namen, keine Titel.

⚠ **Und vPilots Modellscan half nicht**, obwohl er nach Flugzeugen sucht: 3823 Titel,
davon **null** aus `Official` — er liest ebenfalls nur das Dateisystem.

**Dieser Leser holt die Titel aus den Archiven selbst. 2645 Stück, ohne Simulator.**

DAS FORMAT
==========

Aus der Datei abgelesen, nicht dokumentiert:

    "RASA"            Kennung
    uint32            Fassung (2)
    uint16 + uint16   Art des Archivs — `00 00` oder `03 00`, s. unten
    uint32            Länge des Kopf-JSON
    …                 Auffüllung
    <JSON>            {"encryptionSetup":…, "fileInfoList":[{path, byteOffset, byteSize,
                                                             uncompressed_size, …}]}
    <Daten>           die Dateien; `byteOffset` zählt ab dem Anfang dieses Bereichs

⚠ **ZWEI ARTEN VON ARCHIVEN, UND NUR EINE IST LESBAR:**

| Kopf | Datei | Inhalt | lesbar |
|---|---|---|---|
| `RASA 02 00 00 00` | `minimal.fsarchive` | Konfigurationen (`sim.cfg`, `model.cfg`) | **ja** (`"scheme":"notEncrypted"`) |
| `RASA 02 00 03 00` | `SimObjects/*.fsarchive` | Modelle, Texturen, `aircraft.cfg` | nein |

**Daraus folgt die Grenze dieses Werkzeugs:** SimObjects (Tiere, Fahrzeuge, Boote,
Landmarks) tragen ihren Titel in der `sim.cfg` und liegen damit im unverschlüsselten
`minimal.fsarchive` — **Flugzeuge nicht.** Deren `aircraft.cfg` steckt im verschlüsselten
Teil; das `minimal` eines Flugzeugpakets enthält nur Anhänge (`attached_objects.cfg`,
`panel.cfg`).

**Für Flugzeugtitel gibt es deshalb weiterhin nur einen Weg:** Die Brügge liest `TITLE` im
laufenden Simulator und meldet es (s. `flugzeug` in PROTOKOLL.md). Das ist keine
Doppelung — es sind zwei verschiedene Fälle.

AUFRUF
======

    python fsarchive.py "<Paketordner>"        # ein Paket oder ein ganzer Baum

Ohne Argument wird der StreamedPackages-Ordner von MSFS 2024 genommen.
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path

# Wo MSFS 2024 seine gestreamten Pakete ablegt.
STANDARD = (Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
            / "Microsoft.Limitless_8wekyb3d8bbwe" / "LocalCache" / "Packages"
            / "StreamedPackages")

# Die Titel stehen in diesen beiden Dateien. `aircraft.cfg` ist mit aufgeführt, obwohl sie
# in der Praxis nie im lesbaren Teil liegt -- sollte Asobo das je ändern, findet der Leser
# sie ohne weiteres Zutun.
TITELDATEIEN = ("sim.cfg", "aircraft.cfg")


def lies(pfad: Path):
    """``(Kopf, [(Eintrag, Datenanfang, Rohdaten)])`` — oder ``(None, [])``."""
    d = pfad.read_bytes()
    if d[:4] != b"RASA":
        return None, []
    _fassung, _art, kopf_laenge = struct.unpack_from("<III", d, 4)

    # ⚠ Die Klammer wird GESUCHT, nicht gerechnet. Der JSON beginnt meist bei Byte 32, aber
    # nicht in jedem Archiv -- und ein falscher Offset sieht aus wie ein kaputtes Archiv.
    i = d.find(b'{"encryptionSetup')
    if i < 0:
        return None, []          # verschlüsselt (Kopf `03 00`) oder kein Archiv
    ende = d.find(b"]}", i)
    if ende < 0:
        return None, []
    try:
        kopf = json.loads(d[i:ende + 2].decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None, []
    return kopf, [(e, i + kopf_laenge, d) for e in kopf.get("fileInfoList", [])]


def inhalt(eintrag, datenanfang: int, d: bytes) -> bytes | None:
    """Der Inhalt einer Datei aus dem Archiv, entpackt falls nötig."""
    a = datenanfang + eintrag["byteOffset"]
    roh = d[a:a + eintrag["byteSize"]]
    if eintrag["byteSize"] == eintrag["uncompressed_size"]:
        return roh               # unkomprimiert -- so liegen die .cfg-Dateien vor
    for entpacke in (zlib.decompress,
                     lambda x: zlib.decompress(x, -15)):
        try:
            return entpacke(roh)
        except Exception:
            pass
    return None


def titel_aus(pfad: Path) -> list[tuple[str, str]]:
    """``[(Pfad im Archiv, Titel)]`` aus einem Archiv."""
    kopf, eintraege = lies(pfad)
    if kopf is None:
        return []
    raus = []
    for e, anfang, d in eintraege:
        if not e["path"].lower().endswith(TITELDATEIEN):
            continue
        roh = inhalt(e, anfang, d)
        if not roh:
            continue
        for t in re.findall(r"(?im)^\s*title\s*=\s*(.+?)\s*$",
                            roh.decode("utf-8", "replace")):
            raus.append((e["path"], t.strip('"')))
    return raus


def sammeln(wurzel: Path) -> list[dict]:
    """Alle Titel unter ``wurzel``, je Eintrag mit dem Paket, aus dem sie stammen."""
    dateien = [wurzel] if wurzel.is_file() else sorted(wurzel.rglob("*.fsarchive"))
    raus = []
    for f in dateien:
        # Der Paketname ist der Ordner ueber `content/`.
        paket = f.parent.name
        for teil in f.parts:
            if teil.startswith(("fs20-", "fs24-")):
                paket = teil
                break
        for pfad_im_archiv, t in titel_aus(f):
            raus.append({"paket": paket, "titel": t, "quelle_datei": pfad_im_archiv})
    return raus


def main() -> int:
    wurzel = Path(sys.argv[1]) if len(sys.argv) > 1 else STANDARD
    if not wurzel.exists():
        print(f"nicht gefunden: {wurzel}")
        return 1

    gefunden = sammeln(wurzel)
    nach_paket: dict[str, list[str]] = {}
    for e in gefunden:
        nach_paket.setdefault(e["paket"], []).append(e["titel"])

    for paket in sorted(nach_paket):
        print(f"\n[{paket}]")
        for t in sorted(set(nach_paket[paket])):
            print(f"   {t}")

    einmalig = {e["titel"] for e in gefunden}
    print(f"\n{len(gefunden)} Titel ({len(einmalig)} verschiedene) "
          f"aus {len(nach_paket)} Paketen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
