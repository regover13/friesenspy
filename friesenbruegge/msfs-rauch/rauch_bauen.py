"""Erzeugt die FriesenBrügge-Rauchsäulen für MSFS 2020/2024 — sechs Farben, eigenes Werk.

Das Gegenstück zu ../xplane/rauch_bauen.py. Gleicher Zweck, gleiche Farben, anderes Format.

WARUM SELBST GEBAUT
===================

Am 13.09.2026 im laufenden MSFS 2024 alles geprüft, was es von der Stange gibt:

| Titel | | |
|---|---|---|
| `SIAI_VFX_Smoke_Red` | eine **Wand** über mehrere hundert Meter | und SayIntentions-Abo |
| `Smoke_Volcano` | weiße **Halbkugel**, rund 100 m | Bordmittel, aber unbrauchbar |
| `VfxSpawner` | wird angenommen, zeichnet **nichts** | |
| `ESD_Env_Smoke_Chimney_Small` | grauer Schornstein — und nur **unter 10 °C** | Emerald |
| `item_flare_*` | kompakte Farbwolken, vier Farben | Campout, muss installiert sein |

Keines ist eine Signalsäule, und **mitliefern darf man keines**: Emerald verbietet es wörtlich
(*„refrain from packaging it with your add-on"*), SayIntentions hängt am Abo, Campout ist ein
Fremdpaket. Also bauen wir sie selbst — wie für X-Plane schon geschehen.

DASS DAS GEHT, IST DER FUND DES TAGES
=====================================

Ein MSFS-Partikeleffekt sieht aus wie eine kompilierte Binärdatei (`.spb`), und danach hatte
es ausgesehen, als bräuchte es den Visual-Effects-Editor im DevMode — also Klickarbeit, die
ich nicht leisten kann. Das SDK bringt aber ein Beispielprojekt mit, und dort liegt die
**Quelle**:

    Samples/DevmodeProjects/Misc/SimpleFX/.../EngineSmoke.xml
    Samples/DevmodeProjects/SimObjects/Aircraft/WasmAircraft/.../smoke.xml

Beide sind lesbares XML, und `fspackagetool.exe` macht daraus die `.spb`. Das Format ist ein
Knotengraph: Jeder Knoten hat eine GUID, und Werte werden über GUID-Verweise verdrahtet
(`{GUID}, vorgabewert` — die Null-GUID heißt „keine Verbindung, nimm die Zahl").

Alles, was die X-Plane-Säule ausmacht, hat hier eine Entsprechung:

| X-Plane `.pss` | MSFS-XML |
|---|---|
| `TIME_TO_LIVE` | `ParticleLifetime` |
| `EMIT_RATE` | `ParticleRate` |
| `MAX_PARTICLES` | `Capacity` |
| `TINT` | `Vector4` → `ParticleColor` |
| `ALPHA_CURVE` | `GetBezierCurve` auf `AgeOverLifetime` → `w` des `Vector4` |
| `GRAVITY_CURVE` (negativ) | `GravityVector` mit `GravityScale` −1 |
| Streuung (Min/Max-Spalten) | `RandomValue` |
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

HIER = Path(__file__).resolve().parent
QUELLEN = HIER / "PackageSources"
DEFINITIONEN = HIER / "PackageDefinitions"

# Dieselben sechs Farben wie in X-Plane -- vier aus dem FriesenFlieger-Repaint-Kit, zwei
# Signalfarben. Der Server fordert eine FARBE an und muss sich darauf verlassen können, dass
# jeder Pilot sie sieht, gleich in welchem Simulator (PROTOKOLL.md, Abschnitt 3).
FARBEN = {
    "navy":         (0x19, 0x1D, 0x53),
    "hellblau":     (0x8F, 0xBF, 0xF1),
    "rot":          (0x8A, 0x1B, 0x1B),
    "orange":       (0xD7, 0x5F, 0x28),
    "signalrot":    (0xE3, 0x06, 0x13),
    "signalorange": (0xFF, 0x6A, 0x13),
}

# Die Werte stammen aus dem X-Plane-Durchgang vom 13.09.2026, bei dem zehn Anläufe nötig
# waren. Übertragen, nicht neu erfunden:
LEBENSDAUER_S = 22.0      # X-Plane: 45 s bei 3 m/s. MSFS-Partikel sind teurer, s. Kommentar
RATE = 60.0               # Partikel je Sekunde
KAPAZITAET = 2000.0       # Rate x Lebensdauer, mit Luft nach oben
GROESSE_M = 6.0           # mittlere Partikelgröße
AUFTRIEB = -0.35          # negativer GravityScale = nach oben

# Ein fester Namensraum, damit aus demselben Namen immer dieselbe GUID wird. Ohne das
# bekäme jeder Lauf neue GUIDs, und ein Paket-Update zerrisse die Verweise: Die
# Behaviour-Datei des SimObjects verweist den Effekt über genau diese Zahl.
NAMENSRAUM = uuid.UUID("7f3c1a90-5b2e-4d61-9a77-af8e5c000001")


def guid(*teile: str) -> str:
    return "{" + str(uuid.uuid5(NAMENSRAUM, "|".join(teile))).upper() + "}"


NULL = "{00000000-0000-0000-0000-000000000000}"


def effekt_xml(name: str, farbe: tuple[int, int, int]) -> str:
    """Ein vollständiger Partikeleffekt als Knotengraph."""
    r, g, b = (k / 255.0 for k in farbe)
    # Jeder Knoten bekommt seine eigene, aus dem Namen abgeleitete GUID.
    G = {k: guid(name, k) for k in (
        "fx", "emitter", "init", "update", "output", "farbe", "alter", "alpha_kurve",
        "groesse_kurve", "auftrieb", "streu_x", "streu_z", "richtung", "summe", "id")}
    # Und die Ausgangswerte (das, was ein Knoten LIEFERT) brauchen eigene GUIDs.
    W = {k: guid(name, "wert", k) for k in (
        "farbe", "alter", "alpha", "auftrieb", "streu_x", "streu_z", "richtung", "summe",
        "id", "groesse")}

    return f"""<?xml version="1.0" encoding="UTF-8"?>

<SimBase.Document Type="AceXML" version="1,0">
    <Descr>AceXML Document</Descr>
    <WorldBase.Flight>
        <VisualEffect.VisualEffect InstanceId="{G['fx']}">
            <Name>FrsRauch{name.capitalize()}</Name>
            <EmitterList>
                <ObjectReference InstanceId="{G['emitter']}" id="Emitter"/>
            </EmitterList>
        </VisualEffect.VisualEffect>
        <VisualEffect.Emitter InstanceId="{G['emitter']}">
            <ParticleRate>{NULL}, {RATE:.6f}</ParticleRate>
            <Capacity>{KAPAZITAET:.3f}</Capacity>
            <ParticleInit>
                <ObjectReference InstanceId="{G['init']}" id="BlockParticleInit"/>
            </ParticleInit>
        </VisualEffect.Emitter>
        <VisualEffect.BlockParticleInit InstanceId="{G['init']}">
            <ParticleUpdate>
                <ObjectReference InstanceId="{G['update']}" id="BlockParticleUpdate"/>
            </ParticleUpdate>
            <ParticleLifetime>
                <FloatIn>{NULL}, {LEBENSDAUER_S:.6f}</FloatIn>
            </ParticleLifetime>
            <ParticleSize>
                <FloatIn>{NULL}, {GROESSE_M:.6f}</FloatIn>
            </ParticleSize>
            <ParticleVelocity>
                <Float3In>{W['summe']}, 0.000000, 0.000000, 0.000000</Float3In>
            </ParticleVelocity>
        </VisualEffect.BlockParticleInit>
        <VisualEffect.BlockParticleUpdate InstanceId="{G['update']}">
            <ParticleOutput>
                <ObjectReference InstanceId="{G['output']}" id="Output"/>
            </ParticleOutput>
        </VisualEffect.BlockParticleUpdate>
        <VisualEffect.Output InstanceId="{G['output']}">
            <ParticleColor>
                <ColorIn>{W['farbe']}, 0, 0, 0, 0</ColorIn>
            </ParticleColor>
        </VisualEffect.Output>

        <!-- Die Farbe. x/y/z sind Rot/Gruen/Blau, w ist die Deckkraft, und die haengt an
             einer Kurve ueber die Lebenszeit, genau wie ALPHA_CURVE in der .pss. -->
        <VisualEffect.Vector4 InstanceId="{G['farbe']}">
            <OutputValue>{W['farbe']}</OutputValue>
            <x>{NULL}, {r:.6f}</x>
            <y>{NULL}, {g:.6f}</y>
            <z>{NULL}, {b:.6f}</z>
            <w>{W['alpha']}, 0.000000</w>
        </VisualEffect.Vector4>

        <!-- Das Alter des Partikels, normiert auf 0..1: die x-Achse aller Kurven. -->
        <VisualEffect.GetParticleAttribute InstanceId="{G['alter']}">
            <OutputValue>{W['alter']}</OutputValue>
            <ParticleAttributeType>AgeOverLifetime</ParticleAttributeType>
        </VisualEffect.GetParticleAttribute>

        <!-- Die Deckkraft ueber die Hoehe. Uebertragen aus der X-Plane-Fassung, wo zehn
             Anlaeufe noetig waren. Unten dicht (die Quelle soll ortbar sein), oben duenn
             (die Krone soll sich aufloesen). Format: x,y,NAN,NAN je Stuetzstelle. -->
        <VisualEffect.GetBezierCurve InstanceId="{G['alpha_kurve']}">
            <OutputValue>{W['alpha']}</OutputValue>
            <FXTime>{W['alter']}, 0.000000</FXTime>
            <Curve>0.000,0.000,NAN,NAN,0.030,0.700,NAN,NAN,0.200,0.550,NAN,NAN,0.420,0.160,NAN,NAN,0.680,0.050,NAN,NAN,1.000,0.000,NAN,NAN</Curve>
        </VisualEffect.GetBezierCurve>

        <!-- Auftrieb: ein NEGATIVER Schwerkraftfaktor zieht nach oben. -->
        <VisualEffect.GravityVector InstanceId="{G['auftrieb']}">
            <OutputValue>{W['auftrieb']}</OutputValue>
            <GravityScale>{NULL}, {AUFTRIEB:.6f}</GravityScale>
        </VisualEffect.GravityVector>

        <!-- Seitliche Streuung. Ohne sie steigen alle Partikel im Gleichschritt, und die
             Saeule bleibt eine Roehre statt zu zerfasern (13.09.2026 in X-Plane gemessen). -->
        <VisualEffect.GetParticleAttribute InstanceId="{G['id']}">
            <OutputValue>{W['id']}</OutputValue>
            <ParticleAttributeType>id</ParticleAttributeType>
        </VisualEffect.GetParticleAttribute>
        <VisualEffect.RandomValue InstanceId="{G['streu_x']}">
            <OutputValue>{W['streu_x']}</OutputValue>
            <MinRandValue>{NULL}, -0.700000</MinRandValue>
            <MaxRandValue>{NULL}, 0.700000</MaxRandValue>
            <RandSeed>{NULL}, 1024.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>
        <VisualEffect.RandomValue InstanceId="{G['streu_z']}">
            <OutputValue>{W['streu_z']}</OutputValue>
            <MinRandValue>{NULL}, -0.700000</MinRandValue>
            <MaxRandValue>{NULL}, 0.700000</MaxRandValue>
            <RandSeed>{NULL}, 512.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>
        <VisualEffect.LocalDirection InstanceId="{G['richtung']}">
            <OutputValue>{W['richtung']}</OutputValue>
            <x>{W['streu_x']}, 0.000000</x>
            <z>{W['streu_z']}, 0.000000</z>
        </VisualEffect.LocalDirection>
        <VisualEffect.AddOperation InstanceId="{G['summe']}">
            <OutputValue>{W['summe']}</OutputValue>
            <xVariant>{W['richtung']}, 0.000000</xVariant>
            <yVariant>{W['auftrieb']}, 0.000000</yVariant>
        </VisualEffect.AddOperation>
    </WorldBase.Flight>
</SimBase.Document>
"""


def main() -> None:
    ziel = QUELLEN / "VisualEffectLibs" / "devprops" / "friesenrauch"
    ziel.mkdir(parents=True, exist_ok=True)

    namen = []
    for name, farbe in FARBEN.items():
        datei = f"FrsRauch_{name.capitalize()}"
        (ziel / f"{datei}.xml").write_text(effekt_xml(name, farbe), encoding="utf-8",
                                          newline="\r\n")
        namen.append(datei)
        print(f"  {datei + '.xml':32} #{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")

    eintraege = "\n".join(f'\t<VisualEffect File="{n}"/>' for n in namen)
    (ziel / "VisualEffectLibrary.vfxlib").write_text(
        f'<VisualEffectLibrary Version="1.0.0">\n{eintraege}\n</VisualEffectLibrary>\n',
        encoding="utf-8", newline="\r\n")
    print(f"  {'VisualEffectLibrary.vfxlib':32} {len(namen)} Effekte")


if __name__ == "__main__":
    main()
