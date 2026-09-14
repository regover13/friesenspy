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

⚠ **Junctions muss man ansteuern, nicht durchlaufen.** Viele Community-Pakete sind Junctions.
`find` ohne `-L` übersieht sie (9 statt 309 `sim.cfg`) — daher stand in einer früheren Fassung
von OBJEKTE.md fälschlich „keine Robben". **Und `Path.rglob` übersieht sie ebenso**, entgegen
einer früheren Annahme hier: Von der Wurzel aus fand es 243 Dateien, aus einer Junction heraus
allein 64 weitere. Deshalb durchsucht `_alle_sim_cfg` jeden Paketordner EINZELN.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import sys
from pathlib import Path

# `fsarchive` liegt daneben -- der Aufrufer startet dieses Skript aber oft aus einem anderen
# Verzeichnis, und dann findet Python es nicht von allein.
sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def _alle_sim_cfg(wurzel: Path):
    """Jede `sim.cfg` unter `wurzel` -- auch die hinter Windows-Junctions.

    ⚠ **`Path.rglob` steigt NICHT in Junctions ab.** Hier stand, es tue das „von selbst", und
    das ist falsch: Am 13.09.2026 fand `rglob` von der Community-Wurzel aus **243** `sim.cfg`
    in 21 Paketen -- steigt man dagegen direkt in eine der vier Junctions hinein, liefert
    dasselbe `rglob` allein dort **64** weitere. Im Katalog fehlten dadurch sämtliche
    SayIntentions-Objekte, obwohl sie nachweislich gesetzt werden können (der rote Rauch, den
    der Pilot im Cockpit gesehen hat, stammt genau daraus).

    Der Ausweg ist simpel: eine Ebene tiefer beginnen. Jeder Paketordner wird einzeln
    durchsucht, und ein Junction-Ziel ist aus SEINER Sicht ein ganz normaler Baum.
    """
    gesehen: set[str] = set()

    def darunter(basis: Path):
        try:
            for cfg in basis.rglob("sim.cfg"):
                schluessel = str(cfg).lower()
                if schluessel in gesehen:      # dasselbe Paket kann ueber zwei Wege kommen
                    continue
                gesehen.add(schluessel)
                yield cfg
        except OSError:
            return                              # unlesbarer Ordner darf den Lauf nicht killen

    yield from darunter(wurzel)
    for anker in ("Community", "Official", "OneStore", "StreamedPackages"):
        ordner = wurzel / anker
        if not ordner.is_dir():
            continue
        try:
            kinder = list(ordner.iterdir())
        except OSError:
            continue
        for paket in kinder:
            if paket.is_dir():
                yield from darunter(paket)


def sammle_msfs(wurzel: Path, simulator: str) -> list[dict]:
    """Alle `title=` aus allen `sim.cfg` unterhalb von `wurzel`."""
    raus: list[dict] = []
    gesehen: set[str] = set()
    for cfg in _alle_sim_cfg(wurzel):
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
    """Die gestreamten Pakete -- ihre Titel werden GELESEN, nicht geraten.

    ⭐ **HIER WURDE BIS ZUM 14.09.2026 GERATEN, UND DAS WAR FALSCH.**

    Die Funktion nahm den Paketnamen als Titel und schrieb „Titel unbekannt (Paket
    gestreamt, kein entpackter Ordner)" dazu. Zwei dieser Rateversuche standen als
    gescheitert im Katalog:

        deer_o_hemionus                     EXCEPTION_22 -- CREATE_OBJECT_FAILED
        reindeer_r_tarandus_groenlandicus   EXCEPTION_22 -- CREATE_OBJECT_FAILED

    Der Nutzer hat den Befund nicht geglaubt (*„MSFS muss auch einen Hirsch haben!"*) und
    hatte recht: MSFS hat zwei. Sie heissen `CElaphusCanadensisMale` (Wapiti) und
    `AAlcesMale` (Elch). Die geratenen Namen waren **Paket**namen.

    **Jetzt wird gelesen** (s. `fsarchive.py`): Das `minimal.fsarchive` jedes Pakets ist
    unverschluesselt (`"scheme":"notEncrypted"`) und enthaelt die `sim.cfg` im Klartext.
    2642 Titel aus 1528 Archiven, ohne Simulator.

    ⚠ **FLUGZEUGE BLEIBEN AUSSEN VOR, und das ist keine Nachlaessigkeit:** Deren
    `aircraft.cfg` liegt im VERSCHLUESSELTEN Teil (`RASA 02 00 03 00`); das `minimal` eines
    Flugzeugpakets enthaelt nur Anhaenge. Fuer Flugzeugtitel gibt es genau einen Weg -- die
    Bruegge liest `TITLE` im laufenden Simulator und meldet ihn (s. `flugzeug` in
    PROTOKOLL.md). Zwei Faelle, zwei Wege, keine Doppelung.
    """
    import fsarchive                                    # noqa: E402  (nur hier gebraucht)

    raus = []
    sp = wurzel / "StreamedPackages"
    if not sp.is_dir():
        return raus

    for e in fsarchive.sammeln(sp):
        # Die Kategorie steckt im Paketnamen: `fs24-microsoft-ships-fishing-1` -> `ships`.
        teile = e["paket"].split("-")
        kategorie = teile[2] if len(teile) > 2 else None
        raus.append({"simulator": "msfs2024", "titel": e["titel"], "paket": e["paket"],
                     "quelle": "streamed", "kategorie": kategorie})
    return raus


# ⭐ DREI ZWEIGE, NICHT EINER -- UND DIE AUSWAHL IST EINE ENTSCHEIDUNG, KEINE TECHNIK.
#
# Bis zum 14.09.2026 stand hier nur `sim objects/` (1146 Objekte), mit der Begruendung, die
# uebrigen rund 7000 `.obj` unter `Resources/` seien Autogen-Bausteine und gehoerten in eine
# Szenerie. Die Begruendung stimmt fuer Hausfassaden und Strassenteile -- sie stimmte nicht
# fuer 63 Leuchttuerme, 119 Tanks, Windraeder und 300 Flugplatzfahrzeuge.
#
# ⚠ DIE EIGENTLICHE SCHRANKE WAR EINE ANDERE UND IST GEFALLEN: Ob `XPLMLoadObject` ein
# Autogen-Objekt ueberhaupt laedt und ZEICHNET, war ungemessen. Am 14.09.2026 im Flug belegt
# (Niederbayern): Windrad und Leuchtturm standen und waren beide sichtbar. Erst danach
# lohnte dieser Lauf.
#
# Aufgenommen wird, was ALS EINZELNES OBJEKT einen Sinn ergibt -- ein Leuchtturm, ein
# Tankwagen, ein Seecontainer, ein Bodenschild. Draussen bleibt, was nur im Verbund
# funktioniert: Fassaden, Waende, Daecher, Bodenflaechen, Lampen, Common_Elements. Die
# Auswahl hat der Nutzer am 14.09.2026 getroffen (Container und Bodenschilder ausdruecklich
# dazu); wer sie erweitert, erweitert hier -- und nicht mit einer zweiten Liste woanders.
_XP_ZWEIGE = (
    # (Pfad unter `Resources/default scenery/`, alles darunter mitnehmen?)
    ("sim objects", True),                              # 1146 -- Tiere, Boote, Fahrzeuge
    ("airport scenery/Ramp_Equipment", True),           #  280 -- Tankwagen, Treppen, Schlepper
    ("airport scenery/Ground_Signs", True),             #  203 -- Rollwegschilder
    ("airport scenery/construction", True),             #  102 -- Kraene, Bagger, Container
    ("airport scenery/military", True),                 #   62
    ("airport scenery/towers", True),                   #   47 -- Tower, Radarmasten
    ("airport scenery/Aircraft", True),                 #   32 -- statische Flugzeuge
    ("airport scenery/Dynamic_Vehicles", True),         #   22
    ("1000 autogen/US/industrial/containers", True),    #  215 -- Seecontainer
    ("1000 autogen/US/industrial/tanks", True),         #  119 -- Tanks, Silos
    ("1000 autogen/US/industrial/lighthouses", True),   #   63 -- lighthouse_13 .. _64
    ("1000 autogen/US/industrial/vehicles", True),      #   15
    ("1000 autogen/US/industrial/obstacles", True),     #   12 -- Masten bis 630 m
    ("1000 autogen/US/industrial/power", True),         #    5 -- Windraeder
)


def sammle_xplane(wurzel: Path) -> list[dict]:
    """Die setzbaren `.obj` aus den Zweigen in `_XP_ZWEIGE`.

    X-Plane kennt keine Titel -- `XPLMLoadObject` nimmt den **Pfad relativ zum
    X-System-Ordner** (s. probe-xplane/ERGEBNIS.md, dort im Flug belegt). Genau dieser Pfad
    steht deshalb als `titel` im Katalog.

    Die `kategorie` ist der Ordner, in dem das Objekt liegt -- bei `sim objects/` wie bisher
    die erste Ebene darunter (`dynamic`, `apt_vehicles` ...), bei den uebrigen Zweigen deren
    letzter Pfadteil (`lighthouses`, `Ramp_Equipment` ...). Danach filtert die Admin-Liste.
    """
    raus = []
    szenerie = wurzel / "Resources" / "default scenery"
    gesehen: set[str] = set()
    for zweig, _ in _XP_ZWEIGE:
        basis = szenerie / zweig
        if not basis.is_dir():
            continue
        vorgabe = zweig.rsplit("/", 1)[-1]
        for obj in sorted(basis.rglob("*.obj")):
            rel = obj.relative_to(wurzel).as_posix()
            if rel in gesehen:          # Zweige koennen sich ueberlappen
                continue
            gesehen.add(rel)
            teile = obj.relative_to(basis).parts
            raus.append({"simulator": "xplane12", "titel": rel, "paket": None,
                         "quelle": "bord",
                         "kategorie": (teile[0] if len(teile) > 1 and zweig == "sim objects"
                                       else vorgabe)})
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
