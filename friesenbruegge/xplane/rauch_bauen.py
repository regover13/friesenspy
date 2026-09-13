"""Erzeugt die FriesenBrügge-Rauchsäulen für X-Plane 12 — vier Farben, eigenes Werk.

WARUM SELBST GEBAUT
===================

Am 13.09.2026 durchsucht: Es gibt **keine Freeware-Rauchsäule, die man mitliefern darf.**

| Quelle | Rauch | mitliefern |
|---|---|---|
| Emerald Object Library | ja | *„refrain from packaging it with your add-on"* |
| PBK Effects Library | ja | nur als Bibliothek im Community-Ordner |
| Mikea.at AssetPack | nein | CC BY-NC 3.0 AT |
| OpenSceneryX (X-Plane) | nein | Einzeldateien ausdrücklich verboten |
| SayIntentions | ja | kommt nur mit dem **Premium-Abo** |

Alle sind als *Abhängigkeit* gedacht. Der Nutzer wollte ausdrücklich, dass niemand ein
Fremdpaket braucht — und damit bleibt nur der Eigenbau. Was hier entsteht, gehört uns:
keine Lizenzfrage, keine Installation beim Piloten, FriesenFlieger-Farben.

WOZU RAUCH ÜBERHAUPT
====================

Ein Segelboot ist in X-Plane erst aus wenigen hundert Metern zu sehen, ein Hirsch noch
später. Am 13.09.2026 hat der Nutzer auf EDMV sechs gesetzte Objekte gesucht und drei
Hirsche **gar nicht gefunden** — obwohl alle sechs nachweislich dastanden und ihre Höhe
zurückmeldeten. Eine Rauchsäule steht 100 m hoch und ist kilometerweit sichtbar; für jedes
Event, bei dem jemand etwas *finden* soll, ist sie wertvoller als das schönere Modell am
Boden.

WIE ES FUNKTIONIERT
===================

Ein X-Plane-Objekt braucht keine Geometrie, um Partikel auszustoßen. Die Vorlage liegt in
jeder X-Plane-Installation, in der xPilot steckt: `Contrail.obj` ist **189 Bytes** und
enthält keine einzige Fläche — nur einen Verweis auf ein Partikelsystem und einen Emitter.
Genau diese Form entsteht hier, viermal.

Die Formatkenntnis stammt aus drei gemessenen Quellen, nicht aus Vermutungen:
  * `Contrail.pss` (xPilot)                  — der vollständige Aufbau einer .pss
  * `Resources/effects/*.pss` (Laminar)      — BLEND_MODE BLEND ist der Rauchmodus (57×),
                                               ADD dagegen leuchtet (29×)
  * developer.x-plane.com, Partikelsystem    — „Normal … good for smoke"

⚠ **Alle Emitter-Kurven sind konstant.** `SLOT` bindet eine Kurve an ein Dataref; ohne
Bindung (`SLOT 0`) ist nicht dokumentiert, an welcher Stelle X-Plane sie auswertet. Eine
Kurve mit zwei gleichen Stützstellen liefert überall denselben Wert — damit ist die Frage
gegenstandslos, statt sie zu raten.
"""

from __future__ import annotations

import math
from pathlib import Path

HIER = Path(__file__).resolve().parent
ZIEL = HIER / "objekte"

# Die FriesenFlieger-Palette, aus `Hex codes.txt` des Repaint-Kits — dieselbe Quelle wie
# app/badge.py und die Widget-Badges. Nur diese vier Farben; ein Grün gibt es in der Marke
# nicht, und deshalb gibt es hier auch keine grüne Säule.
FARBEN = {
    "navy":     (0x19, 0x1D, 0x53),
    "hellblau": (0x8F, 0xBF, 0xF1),
    "rot":      (0x8A, 0x1B, 0x1B),
    "orange":   (0xD7, 0x5F, 0x28),
}

# Wie hoch die Säule steht: Aufstiegsgeschwindigkeit × Lebensdauer, gebremst durch DRAG
# und getragen vom Auftrieb (negativer GRAVITY-Wert).
#
# 8 m/s über 35 s ergibt rechnerisch 280 m; mit der Bremsung bleiben gut 150 m. Das ist die
# Größenordnung, die eine Säule über Bäume, Hügel und Dunst hebt -- und genau darum geht es:
# Am 13.09.2026 hat der Nutzer sechs gesetzte Objekte auf einem Flugplatz gesucht und drei
# nicht gefunden. Ein Modell am Boden verschwindet hinter allem; eine Säule steht darüber.
AUFSTIEG_MS = 8.0
LEBENSDAUER_S = 35.0
EMIT_RATE = 90.0          # Partikel je Sekunde -- die Dichte kommt aus der ANZAHL
MAX_PARTICLES = 4000      # 90/s × 35 s = 3150, mit Luft nach oben

TEXTUR = "rauch.png"


def textur_schreiben(pfad: Path, kante: int = 128) -> None:
    """Ein weicher, weißer Fleck mit Alpha-Verlauf.

    WEISS, nicht farbig: Die Farbe kommt aus `TINT` in der .pss. So tragen alle vier Säulen
    dieselbe Textur, und eine fünfte Farbe kostet später nur eine .pss.
    """
    from PIL import Image

    bild = Image.new("RGBA", (kante, kante), (255, 255, 255, 0))
    pixel = bild.load()
    mitte = (kante - 1) / 2.0
    for y in range(kante):
        for x in range(kante):
            # Abstand zur Mitte, normiert auf 0..1 am Rand.
            d = math.hypot(x - mitte, y - mitte) / mitte
            if d >= 1.0:
                continue
            # Weicher Rand: cos²-Abfall. Ein linearer Verlauf zeigt bei großen Partikeln
            # einen sichtbaren Kreisrand, ein cos²-Verlauf nicht.
            a = math.cos(d * math.pi / 2.0) ** 2
            pixel[x, y] = (255, 255, 255, int(round(a * 255)))
    bild.save(pfad, "PNG")


def _kurve(name: str, punkte: list[tuple[float, ...]], modus: str = "LINEAR",
           slot: int | None = None) -> str:
    zeilen = [name]
    if slot is not None:
        zeilen.append(f"SLOT {slot}")
    zeilen.append(f"INTERP_MODE {modus}")
    for p in punkte:
        zeilen.append("\t" + "\t".join(f"{w:.6f}" for w in p))
    zeilen.append("END_KEYFRAME_TABLE")
    return "\n".join(zeilen)


def pss_schreiben(pfad: Path, farbe: tuple[int, int, int]) -> None:
    r, g, b = (k / 255.0 for k in farbe)
    teile = [
        "A",
        "1000",
        "PARTICLE_SYSTEM",
        "",
        f" TEXTURE {TEXTUR}",
        "PARTICLE",
        " NAME frs_rauch",
        f" MAX_PARTICLES {MAX_PARTICLES}",
        " BILLBOARD_MODE BILLBOARD",
        # BLEND und nicht ADD: ADD addiert Licht -- damit würde die Navy-Säule vor hellem
        # Himmel verschwinden und jede Farbe nach Weiß laufen. BLEND legt das Partikel wie
        # eine Ebene darüber, so bleibt die Farbe die Farbe (Laminar: „good for smoke").
        " BLEND_MODE BLEND",
        " TEX_CELLS_X 1",
        " TEX_CELLS_Y 1",
        " ANIM_CELL_START 0",
        " ANIM_CELL_COUNT 1",
        " ANIM_CELL_REPEAT 1",
        " ANIM_CELL_RANDOM 0",
        _kurve("ANIM_CELL_KF", [(0.0, 0.0), (1.0, 0.0)]),
        # Die Wolke dehnt sich beim Aufsteigen: 1,5 m am Fuß, 14 m oben.
        #
        # ⚠ Hier stand 3 → 12 → 30 m, und das ergab eine KUGEL statt einer Säule
        # (13.09.2026, im Bild gesehen): Bei 5 m/s und 22 s steigt ein Partikel gut 100 m --
        # ist er dabei 30 m breit, überlappen die Nachbarn vollständig. Laminars eigener
        # `tire_smoke` geht auf 10 m, `engine_smoke_piston` auf 5 m.
        # Unten schmal, oben weit: 1,5 m am Fuß, 6 m auf einem Viertel der Höhe, 28 m
        # ganz oben. Der schmale Fuß macht die Quelle ortbar, die breite Krone macht die
        # Säule von weitem sichtbar -- und der Übergang dazwischen ist das, was sie wie
        # aufsteigenden Rauch aussehen lässt statt wie eine Wolke auf einem Stiel.
        _kurve("SIZE_CURVE", [(0.0, 1.5), (0.25, 5.0), (0.6, 12.0), (1.0, 28.0)],
               "CUBIC_AVG"),
        # Kurz aufblenden, lange halten, weich verschwinden.
        #
        # ⚠ DIE WICHTIGSTE ZAHL DER GANZEN DATEI, und hier stand sie dreifach zu hoch (0,85).
        # Ein Partikel mit Alpha 0,85 ist fast undurchsichtig; hundert davon übereinander
        # ergeben eine massive Fläche, nie eine Wolke. Der Nutzer hat es sofort benannt:
        # „viel zu dicht".
        #
        # Laminar bleibt überall darunter -- `engine_smoke_piston` bei 0,19, `tire_smoke`
        # bei 0,25, `rocket_smoke` bei 0,44. Die Dichte einer Rauchsäule entsteht aus der
        # ANZAHL, nicht aus der Deckkraft des einzelnen Partikels.
        # Schnell da, dann über die ganze Steighöhe ausdünnen. Das Auflösen ist kein
        # Abschalten am Ende, sondern ein Verlauf: Je höher der Partikel kommt, desto
        # durchsichtiger wird er -- und weil er gleichzeitig wächst, franst die Säule oben
        # aus, statt eine Kante zu haben.
        _kurve("ALPHA_CURVE", [(0.0, 0.0), (0.05, 0.24), (0.30, 0.18),
                               (0.65, 0.08), (1.0, 0.0)]),
        _kurve("LENGTH_CURVE", [(0.0, 0.0), (1.0, 0.0)], "CUBIC_AVG"),
        " DIFFUSE 0.500000",
        " AMBIENT 0.750000",
        _kurve("EMISSIVE", [(0.0, 0.0), (1.0, 0.0)], "CUBIC_AVG"),
        # Hier sitzt die Farbe. Konstant über die Lebenszeit -- Signalrauch, der unterwegs
        # die Farbe wechselt, wäre als Marke unbrauchbar.
        _kurve("TINT", [(0.0, r, g, b), (1.0, r, g, b)], "CUBIC_AVG"),
        # Leichter Auftrieb -- ein NEGATIVER Wert zieht nach oben.
        #
        # Hier stand 0, und damit blieben die Partikel stehen, sobald der Drag sie gebremst
        # hatte: alle an derselben Stelle, also eine Kugel. Laminar gibt jedem Rauch etwas
        # Auftrieb mit (-0,02 bei `engine_smoke`, -0,5 beim Feuerrauch); erst dadurch zieht
        # sich die Fahne in die Länge.
        _kurve("GRAVITY_CURVE", [(0.0, -0.06), (1.0, -0.06)], "CUBIC_AVG"),
        # Etwas Unruhe, zunehmend nach oben -- eine geometrisch gerade Rauchfahne sieht
        # gezeichnet aus.
        # Am Fuß ruhig, oben unruhig. Ohne diesen Verlauf steigt eine gerade Röhre auf;
        # mit ihm verteilt sich die Krone seitlich, so wie Rauch es tut, wenn er an Auftrieb
        # verliert.
        _kurve("TURBULENCE", [(0.0, 0.02), (0.4, 0.25), (1.0, 0.9)], "CUBIC_AVG"),
        # Wenig Bremsung: Der Partikel soll steigen, nicht auf halber Höhe stehenbleiben.
        _kurve("DRAG_CURVE", [(0.0, 0.1), (0.3, 0.35), (1.0, 0.5)], "CUBIC_AVG"),
        _kurve("SPIN_CURVE", [(0.0, 0.3), (1.0, 0.05)], "CUBIC_AVG"),
        _kurve("ELASTICITY", [(0.0, 1.0), (1.0, 1.0)], "CUBIC_AVG"),
        " COLLISION_MODE NONE",
        "END_PARTICLE",
        "EMITTER",
        " NAME frs_rauch",
        " EMIT_MODE STREAM",
        "SUB_EMITTER",
        " PARTICLE_TYPE 0",
        # Ab hier ALLE Kurven konstant und an SLOT 0 -- s. Kopf der Datei.
        _kurve("EMIT_RATE", [(0.0, EMIT_RATE, EMIT_RATE), (1.0, EMIT_RATE, EMIT_RATE)],
               "LINEAR"),
        _kurve("INITIAL_SPEED", [(0.0, AUFSTIEG_MS, AUFSTIEG_MS),
                                 (1.0, AUFSTIEG_MS, AUFSTIEG_MS)], "LINEAR"),
        _kurve("ROTATION_SPEED", [(0.0, 0.5, 1.0), (1.0, 0.5, 1.0)], "CUBIC_AVG"),
        _kurve("INITIAL_HEADING", [(0.0, 0.0, 360.0), (1.0, 0.0, 360.0)], "CUBIC_AVG"),
        # 90° = senkrecht nach oben. Der Wert steuert laut Laminar „the direction the
        # particle flies relative to the attached object".
        _kurve("INITIAL_PITCH", [(0.0, 88.0, 92.0), (1.0, 88.0, 92.0)], "CUBIC_AVG"),
        _kurve("DX", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]),
        _kurve("DY", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]),
        _kurve("DZ", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]),
        # Etwas Streuung am Fuß, damit die Quelle nicht wie ein Punkt aussieht.
        _kurve("DLON", [(0.0, 0.0, 1.5), (1.0, 0.0, 1.5)], "CUBIC_AVG"),
        _kurve("DLAT", [(0.0, 0.0, 1.5), (1.0, 0.0, 1.5)], "CUBIC_AVG"),
        _kurve("INITIAL_ROTATION", [(0.0, 0.0, 360.0), (1.0, 0.0, 360.0)], "CUBIC_AVG"),
        _kurve("INITIAL_SIZE", [(0.0, 0.8, 1.2), (1.0, 0.8, 1.2)], "LINEAR"),
        _kurve("INITIAL_ALPHA", [(0.0, 1.0, 1.0), (1.0, 1.0, 1.0)], "CUBIC_AVG"),
        _kurve("TIME_TO_LIVE", [(0.0, LEBENSDAUER_S, LEBENSDAUER_S),
                                (1.0, LEBENSDAUER_S, LEBENSDAUER_S)], "LINEAR"),
        "END_SUB_EMITTER",
        # ⚠ EIN LEERER DATAREF-PLATZ, UND ZWAR ZWINGEND.
        #
        # Hier stand `DATAREFS 0` -- also gar keine Liste -- während oben dreimal `SLOT 0`
        # steht. Damit zeigen drei Kurven auf einen Listenplatz, den es nicht gibt, und
        # X-Plane 12 STÜRZT BEIM ERSTEN ZEICHNEN AB (13.09.2026, Crash-ID
        # 70ea47c1-04cd-486a-850a-13a532e6719f). Im Log steht dazu nichts: Die Brügge
        # meldete alle vier Säulen als `steht`, das Laden hatte also funktioniert.
        #
        # xPilots `Contrail.pss` zeigt das richtige Muster -- eine LEERE `DREF`-Zeile als
        # Platz 0, gefolgt von den echten Bindungen. „An nichts gebunden" ist dort ein
        # vorhandener Platz, keine fehlende Liste.
        #
        # Die Lehre, und sie ist teurer als die Zeile: Ich hatte vorher selbst gemessen,
        # dass es für `DATAREFS 0` mit `SLOT`-Zeilen KEIN Vorbild gibt -- und trotzdem so
        # gebaut, weil die Kurven konstant sind und der Slot damit „egal" schien. Egal ist
        # er für den WERT, nicht für den ZUGRIFF.
        "DATAREFS 1",
        "DREF ",
        "END_EMITTER",
        " TEX_CELLS_X 1",
        " TEX_CELLS_Y 1",
        "DATAREFS 0",
        "END_PARTICLE_SYSTEM",
        "",
    ]
    pfad.write_text("\n".join(teile), encoding="utf-8", newline="\n")


def obj_schreiben(pfad: Path, pss: str) -> None:
    """Ein Objekt ohne jede Geometrie — es hält nur den Emitter.

    Die Form stammt Zeile für Zeile von xPilots `Contrail.obj`, das nachweislich läuft:
    `POINT_COUNTS 0 0 0 0` sagt „keine Eckpunkte", und trotzdem lädt X-Plane die Datei und
    zeichnet die Partikel.
    """
    pfad.write_text("\n".join([
        "I",
        "800",
        "OBJ",
        "# Die FriesenBruegge -- Rauchsaeule. Kein Modell, nur ein Partikel-Emitter.",
        "",
        f"PARTICLE_SYSTEM {pss}",
        "POINT_COUNTS 0 0 0 0",
        "EMITTER frs_rauch 0 0 0 0 0 0",
        "",
    ]), encoding="utf-8", newline="\n")


def main() -> None:
    ZIEL.mkdir(exist_ok=True)
    textur_schreiben(ZIEL / TEXTUR)
    print(f"  {TEXTUR:22} {(ZIEL / TEXTUR).stat().st_size:7} Bytes")
    for name, farbe in FARBEN.items():
        pss = f"rauch_{name}.pss"
        obj = f"rauch_{name}.obj"
        pss_schreiben(ZIEL / pss, farbe)
        obj_schreiben(ZIEL / obj, pss)
        print(f"  {obj:22} {(ZIEL / obj).stat().st_size:7} Bytes   "
              f"{pss:22} {(ZIEL / pss).stat().st_size:7} Bytes   #{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")


if __name__ == "__main__":
    main()
