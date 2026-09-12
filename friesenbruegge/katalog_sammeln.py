# -*- coding: utf-8 -*-
"""Liest den Objektbestand aller installierten Simulatoren aus und schreibt ihn als JSON.

**Warum das nicht im Browser oder auf dem Server läuft:** Die Titel stehen in
Konfigurationsdateien auf der Platte des Piloten — der Server hat sie nie gesehen, und keine
Dokumentation listet sie. Am 12.09.2026 kostete genau das einen Abend: Von 45 Tiertiteln des
MSFS-2020-Bestands funktionieren in MSFS 2024 nur sieben, und welche, verrät nur der Versuch.

Ausgabe geht nach `katalog.json` und von dort über `POST /api/admin/bruegge/katalog` in die
Tabelle `bruegge_katalog`.

    python katalog_sammeln.py                 # alles, was gefunden wird
    python katalog_sammeln.py --nur msfs2024
    python katalog_sammeln.py --ausgabe woanders.json

## Drei Simulatoren, drei Verfahren

| | wo die Titel stehen |
|---|---|
| MSFS 2020 | `SimObjects/*/*/sim.cfg`, Feld `title=` |
| MSFS 2024 | dasselbe für Community-Pakete; der eigene Bestand ist **gestreamt** |
| X-Plane 12 | es gibt keine Titel — der **Dateipfad** der `.obj` ist der Bezeichner |

⚠ **`find`/`rglob` muss Symlinks folgen.** Viele Community-Pakete sind Junctions; ohne das
findet die Suche 9 statt 309 `sim.cfg` — daher stand in einer früheren Fassung von OBJEKTE.md
fälschlich „keine Robben". Pythons `Path.rglob` folgt ihnen von selbst.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# `title=` in einer sim.cfg. Anführungszeichen sind optional, Kommentare hinter `;` möglich.
TITEL = re.compile(r'^\s*title\s*=\s*"?([^";\r\n]+)', re.IGNORECASE | re.MULTILINE)


def _msfs_wurzel(paket_ordner: str) -> Path | None:
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / paket_ordner / "LocalCache" / "Packages"
    return p if p.is_dir() else None


def _titel_aus_cfg(datei: Path) -> list[str]:
    try:
        text = datei.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # Mehrere `title=` je Datei sind der Regelfall: Ein Ordner `Bears` traegt `BlackBear`,
    # `GrizzlyBear`, `PolarBear` und `SyrianBear` in einer einzigen sim.cfg.
    return [t.strip() for t in TITEL.findall(text) if t.strip()]


def sammle_msfs(wurzel: Path, simulator: str) -> list[dict]:
    """Alle `title=` aus allen `sim.cfg` unterhalb von `wurzel`."""
    raus: list[dict] = []
    gesehen: set[str] = set()
    for cfg in wurzel.rglob("sim.cfg"):
        teile = cfg.parts
        if "SimObjects" not in teile:
            continue
        i = teile.index("SimObjects")
        kategorie = teile[i + 1] if len(teile) > i + 1 else None
        # Der Paketordner ist das Verzeichnis unter Community/Official/StreamedPackages.
        paket = None
        for anker in ("Community", "OneStore", "StreamedPackages", "Official"):
            if anker in teile:
                j = teile.index(anker)
                if len(teile) > j + 1:
                    paket = teile[j + 1]
                break
        quelle = "community" if "Community" in teile else "bord"
        for t in _titel_aus_cfg(cfg):
            if t in gesehen:
                continue
            gesehen.add(t)
            raus.append({"simulator": simulator, "titel": t, "paket": paket,
                         "quelle": quelle, "kategorie": kategorie})
    return raus


def sammle_gestreamt(wurzel: Path) -> list[dict]:
    """Pakete, die NUR als Platzhalter dastehen -- ihr Inhalt kommt aus der Cloud.

    **Ihre Titel sind unbekannt**, denn die `sim.cfg` steckt im `minimal.fsarchive`. Der
    Ordnername ist NICHT der Titel (12.09.2026 geprüft: `Bear_U_Maritimus` wird abgelehnt,
    auch mit `_EX1`). Sie kommen trotzdem in den Katalog — mit dem Ordnernamen als Platzhalter
    und `quelle='streamed'`, damit sichtbar bleibt, **wie viel Bestand hier unerreichbar ist**.
    """
    raus = []
    sp = wurzel / "StreamedPackages"
    if not sp.is_dir():
        return raus
    for paket in sp.iterdir():
        if not paket.is_dir():
            continue
        # Nur SimObject-Pakete interessieren; Flugzeuge, Szenerien und Liveries nicht.
        if "simobjects" not in paket.name.lower():
            continue
        # Der Ordner unter SimObjects/ ist der beste verfuegbare Hinweis auf den Titel.
        namen = [d.name for d in paket.rglob("SimObjects/*/*") if d.is_dir()]
        kategorie = None
        for d in paket.rglob("SimObjects/*"):
            if d.is_dir():
                kategorie = d.name
                break
        if not namen:
            namen = [paket.name.replace("fs24-microsoft-simobjects-", "")
                                .replace("fs24-asobo-simobjects-", "")]
        for n in namen:
            raus.append({"simulator": "msfs2024", "titel": n, "paket": paket.name,
                         "quelle": "streamed", "kategorie": kategorie})
    return raus


def sammle_xplane(wurzel: Path) -> list[dict]:
    """Die setzbaren `.obj` aus `Resources/default scenery/sim objects/`.

    X-Plane kennt keine Titel -- `XPLMLoadObject` nimmt den **Pfad relativ zum
    X-System-Ordner** (s. probe-xplane/ERGEBNIS.md, dort im Flug belegt). Genau dieser Pfad
    steht deshalb als `titel` im Katalog.

    Bewusst NUR `sim objects/`: Die uebrigen rund 7000 `.obj` unter `Resources/` sind
    Autogen-Bausteine (Haeuser, Zaeune, Strassenteile) -- die gehoeren in eine Szenerie, nicht
    an eine Kieker-Station.
    """
    raus = []
    basis = wurzel / "Resources" / "default scenery" / "sim objects"
    if not basis.is_dir():
        return raus
    for obj in basis.rglob("*.obj"):
        rel = obj.relative_to(wurzel).as_posix()
        teile = obj.relative_to(basis).parts
        raus.append({"simulator": "xplane12", "titel": rel, "paket": None,
                     "quelle": "bord",
                     "kategorie": teile[0] if len(teile) > 1 else "dynamic"})
    return raus


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nur", choices=["msfs2020", "msfs2024", "xplane12"],
                    help="nur diesen Simulator")
    ap.add_argument("--xplane", default=r"D:\X-Plane 12", help="X-Plane-Wurzel")
    ap.add_argument("--ausgabe", default="katalog.json")
    a = ap.parse_args()

    alles: list[dict] = []

    if a.nur in (None, "msfs2024"):
        w = _msfs_wurzel("Microsoft.Limitless_8wekyb3d8bbwe")
        if w:
            teil = sammle_msfs(w, "msfs2024")
            gestreamt = sammle_gestreamt(w)
            print(f"MSFS 2024:  {len(teil):5d} Titel, {len(gestreamt):5d} gestreamte Platzhalter")
            alles += teil + gestreamt
        else:
            print("MSFS 2024:  nicht gefunden")

    if a.nur in (None, "msfs2020"):
        w = _msfs_wurzel("Microsoft.FlightSimulator_8wekyb3d8bbwe")
        if w:
            teil = sammle_msfs(w, "msfs2020")
            print(f"MSFS 2020:  {len(teil):5d} Titel")
            alles += teil
        else:
            print("MSFS 2020:  nicht gefunden")

    if a.nur in (None, "xplane12"):
        w = Path(a.xplane)
        if w.is_dir():
            teil = sammle_xplane(w)
            print(f"X-Plane 12: {len(teil):5d} Objekte")
            alles += teil
        else:
            print(f"X-Plane 12: nicht gefunden ({w})")

    Path(a.ausgabe).write_text(json.dumps(alles, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    print(f"\n{len(alles)} Einträge nach {a.ausgabe}")

    # Eine kleine Übersicht, damit sofort auffällt, wenn eine Quelle leer bleibt.
    nach = {}
    for e in alles:
        nach.setdefault((e["simulator"], e["quelle"]), 0)
        nach[(e["simulator"], e["quelle"])] += 1
    for (sim, q), n in sorted(nach.items()):
        print(f"  {sim:<10} {q:<10} {n:5d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
