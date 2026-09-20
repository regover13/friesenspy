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
| MSFS 2020 | `SimObjects/*/*/sim.cfg` und `aircraft.cfg`, Feld `title=` |
| MSFS 2024 | dasselbe für Community-Pakete; der eigene Bestand ist **gestreamt** |
| X-Plane 12 | es gibt keine Titel — der **Dateipfad** der `.obj` ist der Bezeichner |

⚠ **Flugzeuge tragen ihren Titel in `aircraft.cfg`, nicht in `sim.cfg`.** Bis zum 16.09.2026
wurde nur `sim.cfg` gesucht, und deshalb hat dieser Lauf **noch nie einen Flugzeugtitel
geliefert** — auch nicht aus Paketen, die welche haben. Die Gegenprobe war eindeutig:
`gotfriends-wilga` stand mit 19 Zeilen im Katalog, und das waren Bienen, Wohnwagen, Pfützen
und ein Windsack aus `SimObjects/{Misc,Animals,Humans}`; kein einziger der zwölf
`Wilga 80X: …`-Titel. Was im Katalog trotzdem nach Flugzeug aussah, waren Handeinträge und
die Meldungen der Brügge (`quelle='gemeldet'`).

⚠⚠ **Und nicht jeder `title=` aus einer `aircraft.cfg` lässt sich setzen** — am 16.09.2026 am
fliegenden Simulator gemessen (GitHub-Issue #40):

    presets/…/passenger/config/aircraft.cfg      "Mi-2 [passenger]"                    steht
    common/config/aircraft.cfg                   "Digital Aeronautics Mi-2 Hoplite"    EXCEPTION_22

Der Eintrag unter `common/` ist der **Basiseintrag der Modular-Struktur** und keine wählbare
Variante — man kann ihn nicht einmal fliegen, und `AICreateSimulatedObject` nimmt ihn nicht.
Deshalb bleibt er hier draußen, solange er nicht zusätzlich als Preset vorkommt (`--mit-basis`
nimmt ihn doch mit, markiert). Die Trennlinie ist an beiden Enden belegt: Steht derselbe Name
in `common` **und** als Preset — so bei `A2A Piper PA-24-250 Comanche` und
`A2A Piper Aerostar 600` —, dann setzt er sich. `common` schadet nicht, es genügt nur nicht.

⚠ **Junctions muss man ansteuern, nicht durchlaufen.** Viele Community-Pakete sind Junctions.
`find` ohne `-L` übersieht sie (9 statt 309 `sim.cfg`) — daher stand in einer früheren Fassung
von OBJEKTE.md fälschlich „keine Robben". **Und `Path.rglob` übersieht sie ebenso**, entgegen
einer früheren Annahme hier: Von der Wurzel aus fand es 243 Dateien, aus einer Junction heraus
allein 64 weitere. Deshalb durchsucht `_alle_objekt_cfg` jeden Paketordner EINZELN.
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


#: Die zwei Dateien, in denen ein MSFS-Objekt seinen Titel traegt. `sim.cfg` gehoert den
#: Szenerieobjekten (Tiere, Boote, Fahrzeuge), `aircraft.cfg` den Flugzeugen -- und die fehlte
#: hier bis zum 16.09.2026 vollstaendig, s. Modul-Docstring.
_CFG_NAMEN = ("sim.cfg", "aircraft.cfg")


def _alle_objekt_cfg(wurzel: Path):
    """Jede `sim.cfg` und `aircraft.cfg` unter `wurzel` -- auch die hinter Windows-Junctions.

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
            for name in _CFG_NAMEN:
                for cfg in basis.rglob(name):
                    schluessel = str(cfg).lower()
                    if schluessel in gesehen:  # dasselbe Paket kann ueber zwei Wege kommen
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


def _ist_basiseintrag(cfg: Path) -> bool:
    """Steht dieser Titel im Basiseintrag der Modular-Struktur (`common/config/aircraft.cfg`)?

    ⚠ **Ein solcher Titel laesst sich NICHT setzen** -- am 16.09.2026 gemessen, nicht
    hergeleitet: `Digital Aeronautics Mi-2 Hoplite` aus `common/config/aircraft.cfg`
    scheiterte mit `EXCEPTION_22`, waehrend `Mi-2 [passenger]` aus
    `presets/…/passenger/config/aircraft.cfg` im selben Lauf stand. Der Grund liegt nahe: Der
    common-Eintrag ist keine waehlbare Variante, man kann ihn nicht einmal fliegen.

    Die Erkennung haengt bewusst an BEIDEM -- Dateiname und Ordner. `sim.cfg` bleibt
    unberuehrt (dort gibt es diese Struktur nicht), und ein Ordner `common` anderswo im Baum
    macht aus einem Szenerieobjekt keinen Basiseintrag.

    ⚠ Das ist eine Aussage ueber die Datei, nicht ueber den TITEL: Steht derselbe Name
    zusaetzlich in einem Preset, setzt er sich (beide A2A-Muster, gemessen). Darueber
    entscheidet deshalb `sammle_msfs` beim Zusammenfuehren, nicht diese Funktion.
    """
    return cfg.name.lower() == "aircraft.cfg" and "common" in {t.lower() for t in cfg.parts}


def sammle_msfs(wurzel: Path, simulator: str,
                mit_basis: bool = False) -> tuple[list[dict], list[str]]:
    """Alle `title=` aus allen `sim.cfg`/`aircraft.cfg` unterhalb von `wurzel`.

    Gibt ``(eintraege, nur_basis)`` zurueck. ``nur_basis`` sind die Flugzeugtitel, die
    AUSSCHLIESSLICH im Basiseintrag der Modular-Struktur stehen (s. `_ist_basiseintrag`) --
    sie bleiben draussen, weil sie im Simulator scheitern. Der zweite Rueckgabewert ist
    nicht Zierrat: Ohne ihn verschwaende der Lauf sie stillschweigend, und wer den Katalog
    spaeter vermisst, haette keinen Anhaltspunkt.

    ``mit_basis=True`` nimmt sie doch auf -- markiert in `bemerkung`, damit man im Admin
    sieht, woran man ist. Gedacht fuer den Fall, dass sich die Messung irgendwann als zu
    eng erweist; die Vorgabe bleibt das Weglassen.

    ⚠ **Zweistufig, und das muss so sein:** Ob ein Titel taugt, entscheidet sich erst, wenn
    ALLE seine Fundstellen bekannt sind -- die Preset-Datei kann nach der common-Datei
    kommen. Ein Durchlauf, der beim ersten Treffer entscheidet, wuerde `A2A Piper PA-24-250
    Comanche` wegwerfen, obwohl er nachweislich steht.
    """
    # titel -> {"basis": bool (nur in common gefunden), "eintrag": dict}
    fund: dict[str, dict] = {}
    for cfg in _alle_objekt_cfg(wurzel):
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
        basis = _ist_basiseintrag(cfg)
        for t in _titel_aus_cfg(cfg):
            vorher = fund.get(t)
            if vorher is None:
                fund[t] = {"basis": basis,
                           "eintrag": {"simulator": simulator, "titel": t, "paket": paket,
                                       "quelle": quelle, "kategorie": kategorie}}
            elif vorher["basis"] and not basis:
                # Derselbe Name auch als waehlbare Variante -- DIE Fundstelle zaehlt, und
                # mit ihr Paket und Kategorie (die common-Datei liegt oft eine Ebene hoeher).
                fund[t] = {"basis": False,
                           "eintrag": {"simulator": simulator, "titel": t, "paket": paket,
                                       "quelle": quelle, "kategorie": kategorie}}

    raus: list[dict] = []
    nur_basis: list[str] = []
    for t, f in fund.items():
        if not f["basis"]:
            raus.append(f["eintrag"])
            continue
        nur_basis.append(t)
        if mit_basis:
            e = dict(f["eintrag"])
            e["bemerkung"] = ("nur Basiseintrag (common/config/aircraft.cfg) -- "
                              "im Simulator gemessen NICHT setzbar")
            raus.append(e)
    return raus, sorted(nur_basis)


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
    # (Pfad unter `Resources/default scenery/`, Kategorie im Katalog)
    #
    # ⚠ Das zweite Feld war bis zum 15.09.2026 ein ungenutztes `True` ("alles darunter
    # mitnehmen?") -- `rglob` nimmt ohnehin alles. Jetzt traegt es die KATEGORIE, und das
    # war noetig: Zwei der neuen Zweige enden beide auf `static`
    # (`cars/static`, `cars_EU/static`), der letzte Pfadteil taugt dort nicht als Name.
    # `None` heisst: letzter Pfadteil, wie bisher.
    ("sim objects", None),                              # 1146 -- Tiere, Boote, Fahrzeuge
    ("airport scenery/Ramp_Equipment", None),           #  280 -- Tankwagen, Treppen, Schlepper
    ("airport scenery/Ground_Signs", None),             #  203 -- Rollwegschilder
    ("airport scenery/construction", None),             #  102 -- Kraene, Bagger, Container
    ("airport scenery/military", None),                 #   62
    ("airport scenery/towers", None),                   #   47 -- Tower, Radarmasten
    ("airport scenery/Aircraft", None),                 #   32 -- statische Flugzeuge
    ("airport scenery/Dynamic_Vehicles", None),         #   22
    ("1000 autogen/US/industrial/containers", None),    #  215 -- Seecontainer
    ("1000 autogen/US/industrial/tanks", None),         #  119 -- Tanks, Silos
    ("1000 autogen/US/industrial/lighthouses", None),   #   63 -- lighthouse_13 .. _64
    ("1000 autogen/US/industrial/vehicles", None),      #   15
    ("1000 autogen/US/industrial/obstacles", None),     #   12 -- Masten bis 630 m
    ("1000 autogen/US/industrial/power", None),         #    5 -- Windraeder

    # ⭐ ZWEITE ERWEITERUNG, 15.09.2026 -- Anlass: "16 Arten waren viel zu wenig fuer so
    # viele Objekte!" Der Katalog kannte 2327 der 7995 `.obj` unter `default scenery`, also
    # nicht einmal ein Drittel. Was hier dazukommt, ist nach derselben Regel ausgewaehlt wie
    # oben: aufgenommen wird, was ALS EINZELNES OBJEKT einen Sinn ergibt.
    #
    # ⚠ `Common_Elements` stand bis heute pauschal auf der Ausschlussliste, und fuer den
    # groessten Teil zu Recht -- `Fence_Facades` (137), `Lighting` (81), `barriers` (58) und
    # `Parking_Items` (79) sind Verbundteile. In SECHS seiner Unterordner stehen aber
    # Einzelobjekte, und darunter genau die, an denen bisher vier Artenpaare scheiterten:
    # der Krankenwagen, das Zelt, die Flughafenfeuerwehr und der Tankwagen.
    ("airport scenery/Common_Elements/Vehicles", None),         # 126 -- Ambulanz, Pickup, Cargo
    ("airport scenery/Common_Elements/fire_department", None),  #  18 -- Striker 4x4/6x6
    ("airport scenery/Common_Elements/camping", None),          #  27 -- Zelte, Tische
    ("airport scenery/Common_Elements/Water_Towers", None),     #   6 -- WT_1930/1960/1990
    ("airport scenery/Common_Elements/radars", None),           #  45 -- ASR, SSR, Wetterradar
    ("airport scenery/Common_Elements/antennas", None),         #  33 -- Antennen, Satellitenschuesseln
    ("airport scenery/Common_Elements/Fuel", None),             #  34 -- Avgas-Faesser, Hydranten
    ("airport scenery/Common_Elements/Miscellaneous", None),    #  39 -- Flaggenmast, Boje
    # Gabelstapler (24) und Silos -- das europaeische Gegenstueck zu Ramp_Equipment.
    ("airport scenery/Euro_Airports", None),                    # 189
    # ⚠ NUR `static`. Die `dynamic`-Zwillinge sind fuer den fahrenden Verkehr gedacht und
    # tragen Animationen; als abgestelltes Objekt ist die statische Fassung die richtige.
    ("1000 roads/objects/cars/static", "cars"),                   #  36 -- PKW, Polizei (US)
    ("1000 roads/objects/cars_EU/static", "cars_EU"),                #  43 -- PKW, Busse (EU)

    # ⭐ DRITTE ERWEITERUNG, 20.09.2026 -- Anlass: „Was ist mit Xplane und 2020?" nach dem
    # Abgleich Platte gegen Katalog (5 076 von 7 995 Standardobjekten fehlten). Meist zu Recht
    # (Autogen, Straßen, Gelände, Hügel), aber vier Gruppen sind Einzelobjekte:
    ("airport scenery/1000_Landmarks", "landmarks"),          #   4 -- Eiffelturm, Freiheitsstatue
    ("900 roads/trains", "trains"),                           # 187 -- Güterwagen, Lokomotiven
    ("900 us objects/skyscrapers", "skyscrapers"),            #  23 -- Hochhäuser (generisch)
)

#: Die offiziellen Pakete unter `Custom Scenery/`, die bei jeder X-Plane-12-Installation
#: mitkommen (20.09.2026 gefunden): 16 „X-Plane Landmarks - <Stadt>" mit rund 165 Objekten
#: (Brandenburger Tor, Fernsehturm, Eiffelturm, Empire State …) und 6 „X-Plane Airports -
#: <Platz>" mit 137. Bis dahin stand davon NICHTS im Katalog -- der Sammellauf las nur
#: `Resources/default scenery`. Ein Kölner Dom ist nicht dabei.
#:
#: ⚠ Der Titel ist wie überall der Pfad relativ zum X-Plane-Ordner, hier also
#: `Custom Scenery/<Paket>/objects/<Name>.obj` -- `XPLMLoadObject` nimmt jeden solchen Pfad. In
#: `paket` steht der Ordnername, damit die Admin-Liste danach filtern kann.
_XP_CUSTOM = (
    ("X-Plane Landmarks - ", "landmarks"),
    ("X-Plane Airports - ", "airports_custom"),
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
    for zweig, kategorie in _XP_ZWEIGE:
        basis = szenerie / zweig
        if not basis.is_dir():
            continue
        vorgabe = kategorie or zweig.rsplit("/", 1)[-1]
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
    # ⭐ Und dann ALLES, was übrig ist (20.09.2026, Nutzer: „Ich meine auch übersehene Objekte!“).
    # Bis dahin galt die Regel „nur, was als einzelnes Objekt einen Sinn ergibt“ (14.09.); sie
    # hat 5 076 von 7 995 Standardobjekten draußen gelassen -- und niemand konnte sagen, ob
    # darunter etwas Brauchbares war. Jetzt steht alles im Katalog, sortiert nach Ordner
    # (`kategorie`), und ob ein Objekt taugt, sagt der Lauf, nicht die Vermutung. Die
    # Verbundteile (Fassaden, Lampen, Autogen, Hügel) laufen mit; der Admin filtert nach
    # Kategorie, und `--nur-kategorie` beim Prüfwerkzeug hält sie aus einem ersten Lauf heraus.
    for obj in sorted(szenerie.rglob("*.obj")):
        rel = obj.relative_to(wurzel).as_posix()
        if rel in gesehen:
            continue
        gesehen.add(rel)
        teile = obj.relative_to(szenerie).parts
        raus.append({"simulator": "xplane12", "titel": rel, "paket": None, "quelle": "bord",
                     "kategorie": "/".join(teile[:2]) if len(teile) > 2 else teile[0]})
    raus += sammle_xplane_custom(wurzel)
    return raus


def sammle_xplane_custom(wurzel: Path) -> list[dict]:
    """Die `.obj` der offiziellen Pakete unter `Custom Scenery/` (s. `_XP_CUSTOM`)."""
    raus = []
    cs = wurzel / "Custom Scenery"
    if not cs.is_dir():
        return raus
    for ordner in sorted(cs.iterdir()):
        if not ordner.is_dir():
            continue
        for vorsatz, kategorie in _XP_CUSTOM:
            if not ordner.name.startswith(vorsatz):
                continue
            for obj in sorted(ordner.rglob("*.obj")):
                raus.append({"simulator": "xplane12",
                             "titel": obj.relative_to(wurzel).as_posix(),
                             "paket": ordner.name, "quelle": "bord", "kategorie": kategorie})
    return raus


def _basis_melden(nur_basis: list[str], mit_basis: bool) -> None:
    """Was wegen `common/config/aircraft.cfg` draussen blieb -- sichtbar, nicht stillschweigend.

    Ein weggelassener Titel, von dem niemand erfaehrt, ist genau die Sorte Luecke, die spaeter
    als „der Simulator hat das nicht" missverstanden wird. Drei Beispiele reichen, um den Fall
    wiederzuerkennen; die Zahl sagt den Rest.
    """
    if not nur_basis:
        return
    wort = "mitgenommen (--mit-basis)" if mit_basis else "weggelassen"
    beispiel = ", ".join(nur_basis[:3]) + ("  …" if len(nur_basis) > 3 else "")
    print(f"            {len(nur_basis):5d} Basiseintraege {wort}: {beispiel}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nur", choices=["msfs2020", "msfs2024", "xplane12"],
                    help="nur diesen Simulator")
    ap.add_argument("--xplane", default=r"D:\X-Plane 12", help="X-Plane-Wurzel")
    ap.add_argument("--ausgabe", default="katalog.json")
    ap.add_argument("--mit-basis", action="store_true",
                    help="auch die Basiseintraege aus common/config/aircraft.cfg aufnehmen "
                         "(gemessen nicht setzbar -- nur fuer die Fehlersuche)")
    a = ap.parse_args()

    alles: list[dict] = []

    if a.nur in (None, "msfs2024"):
        w = _msfs_wurzel("Microsoft.Limitless_8wekyb3d8bbwe")
        if w:
            teil, nur_basis = sammle_msfs(w, "msfs2024", mit_basis=a.mit_basis)
            gestreamt = sammle_gestreamt(w)
            print(f"MSFS 2024:  {len(teil):5d} Titel, {len(gestreamt):5d} gestreamte Platzhalter")
            _basis_melden(nur_basis, a.mit_basis)
            alles += teil + gestreamt
        else:
            print("MSFS 2024:  nicht gefunden")

    if a.nur in (None, "msfs2020"):
        w = _msfs_wurzel("Microsoft.FlightSimulator_8wekyb3d8bbwe")
        if w:
            teil, nur_basis = sammle_msfs(w, "msfs2020", mit_basis=a.mit_basis)
            print(f"MSFS 2020:  {len(teil):5d} Titel")
            _basis_melden(nur_basis, a.mit_basis)
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
