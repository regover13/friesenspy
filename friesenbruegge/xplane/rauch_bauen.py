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
    # Die vier aus `Hex codes.txt` des Repaint-Kits -- dieselbe Quelle wie app/badge.py.
    "navy":         (0x19, 0x1D, 0x53),
    "hellblau":     (0x8F, 0xBF, 0xF1),
    "rot":          (0x8A, 0x1B, 0x1B),
    "orange":       (0xD7, 0x5F, 0x28),
    # Und zwei Signalfarben dazu (Nutzerwunsch 13.09.2026). Das FF-Rot ist ein dunkles
    # Weinrot -- vor Wald und Schatten verschwindet es, und genau dort soll eine Säule ja
    # gefunden werden. Diese beiden sind das, was ein echtes Rauchsignal trägt: hell,
    # gesättigt, gegen jeden Hintergrund sichtbar.
    "signalrot":    (0xE3, 0x06, 0x13),
    "signalorange": (0xFF, 0x6A, 0x13),
}

# Wie hoch die Säule steht: Aufstiegsgeschwindigkeit × Lebensdauer, gebremst durch DRAG
# und getragen vom Auftrieb (negativer GRAVITY-Wert).
#
# 3 m/s über 30 s ergibt rechnerisch 90 m; mit der Bremsung bleiben rund 65 m. Das ist die
# Größenordnung, die eine Säule über Bäume, Hügel und Dunst hebt -- und genau darum geht es:
# Am 13.09.2026 hat der Nutzer sechs gesetzte Objekte auf einem Flugplatz gesucht und drei
# nicht gefunden. Ein Modell am Boden verschwindet hinter allem; eine Säule steht darüber.
#
# ⚠ Hier standen 8 m/s, und der Fuß der Säule war ein DÜNNER STRICH (13.09.2026, im Bild
# gesehen). Bei 90 Partikeln je Sekunde und 8 m/s liegen sie 9 cm auseinander, sind aber nur
# 1,5 m groß -- das ergibt eine Perlenschnur, keine Säule. Echter Signalrauch quillt mit 2-3
# m/s; die Dichte unten kommt daher, dass die Partikel eng beieinander bleiben.
AUFSTIEG_MS = 3.0
LEBENSDAUER_S = 30.0
# Am 14.09.2026 von 45 auf 30 gesetzt -- dieselbe Nutzerentscheidung, die MSFS von 22 herauf
# gebracht hat: "ich finde xplane zu gross und msfs zu klein". Beide Fassungen waren
# abgenommen, keine war die Referenz, beide bewegten sich zur Mitte.
#
# ⚠ UND DIE WERTE DARUNTER WERDEN JETZT GERECHNET, NICHT EINGETRAGEN.
#
# Das war die zweite Haelfte der Vorgabe ("und rechnen das im Verhaeltnis!!"), und sie war
# hier nicht erfuellbar: Endgroesse und Kapazitaet standen als feste Zahlen da, obwohl beide
# an der Lebensdauer haengen. Genau so laufen zwei Fassungen auseinander -- in MSFS kostete
# der Wechsel eine Zeile, hier waere er Handarbeit an drei Stellen gewesen, von denen man
# zwei vergisst. Die Ableitungen sind dieselben wie in msfs-rauch/rauch_bauen.py:
#
#   Saeulenhoehe = Aufstieg x Lebensdauer             135 m -> 90 m
#   Endgroesse   = 0,133 x Hoehe                      18,0 m -> 12,0 m
#   Kapazitaet   = Rate x Lebensdauer x 1,25          12000 -> 8250
#
# Die EMIT_RATE bleibt, und das faellt aus der Rechnung: Die Dichte je Meter ist
# `Rate x Lebensdauer / Hoehe`, und Hoehe und Lebensdauer wachsen proportional.
_HOEHE_M = AUFSTIEG_MS * LEBENSDAUER_S    # 90 m

EMIT_RATE = 220.0         # Partikel je Sekunde -- s. ALPHA_CURVE zur Überlappung
MAX_PARTICLES = int(EMIT_RATE * LEBENSDAUER_S * 1.25)   # 8250, mit Luft nach oben

# Die Groessenkurve: unten die Rauchpatrone, oben die sich aufloesende Krone.
#
# ⚠ DER FUSS IST FEST, DAS ENDE IST ABGELEITET -- wie in MSFS (GROESSE_START_M dort). Die
# Quelle ist eine Patrone und wird nicht groesser, nur weil der Rauch laenger lebt; die
# Krone dagegen steht am oberen Ende der Saeule und waechst mit ihr.
GROESSE_START_M = 0.8     # an der Quelle -- ⚠ am Fuss KLEIN halten, sonst verwaescht sie
# Am 14.09.2026 von 1,2 auf 0,8 -- Nutzerentscheidung, nachdem beide Fassungen
# nebeneinander standen. MSFS fuehrte den Fuss seit jeher mit 0,8, und mit gleicher
# Krone (11,97 m) war der Fuss der letzte Wert, in dem sich die Simulatoren noch
# unterschieden. Er hat die schmalere Quelle gewaehlt, nicht die breitere.
GROESSE_ENDE_M = 0.133 * _HOEHE_M         # oben, wo sich die Krone aufloesen soll

# Stuetzstellen als (Alter 0..1, Anteil an der Spanne 0..1) -- dieselbe Bauart wie MSFS'
# _GROESSE_STUETZEN. Die Zahlen selbst sind die abgenommenen: 1,2 / 2,6 / 6,5 / 18,0 auf
# 135 m Saeule, hier als Anteile ausgedrueckt, damit sie jede Hoehe mitgehen.
_GROESSE_STUETZEN = ((0.00, 0.000), (0.20, 0.083), (0.45, 0.315), (1.00, 1.000))

TEXTUR = "rauch.png"


# Der Atlas: 4x4 Zellen, sechzehn verschiedene Wolkenformen.
#
# ⚠ WARUM NICHT EIN FLECK, und das ist der Fund des Nachmittags: Hier stand eine einzige
# glatte Kreisscheibe -- und die Säule sah im Simulator aus wie eine KETTE AUS KUGELN
# (13.09.2026, im Bild gesehen). Jeder Partikel war als Kreis erkennbar, und eine Perlenkette
# kann nicht ausfransen, egal wie sehr man sie verteilt.
#
# Laminars eigene Rauchtextur (`Resources/effects/aircraft_system.png`, 1024x1024) ist
# dagegen ein ATLAS aus Dutzenden unregelmäßiger Wolkenformen. Dafür gibt es die Felder
# TEX_CELLS_X/Y und ANIM_CELL_RANDOM: Jeder Partikel zieht eine andere Zelle, und dadurch
# sieht keiner aus wie der andere. Genau das lässt echte Partikel zu Schwaden verschmelzen.
ATLAS = 4          # 4x4 = 16 Formen
ZELLE = 128        # Pixel je Zelle -> 512x512 gesamt


def _rauschen(kante: int, keim: int):
    """Fraktales Rauschen über mehrere Oktaven, als Liste von Fließkommawerten.

    Value Noise von Hand: ein grobes Zufallsgitter wird bikubisch hochskaliert, und davon
    mehrere Oktaven mit halbierender Amplitude addiert. Pillow kann das Hochskalieren, also
    braucht es dafür kein numpy -- und keine Abhängigkeit, die im Paket landen müsste.
    """
    import random

    from PIL import Image

    rnd = random.Random(keim)
    summe = [0.0] * (kante * kante)
    amplitude = 1.0
    gesamt = 0.0
    # ⚠ DIE OKTAVEN HAENGEN AN DER KANTE, sonst wird eine grosse Textur weich statt fransig.
    # Hier stand fest (2, 4, 8, 16, 32). Auf einer 128er-Zelle ist die feinste Oktave damit
    # 4 Pixel breit -- auf der 512er-Textur fuer MSFS aber 16, also viermal zu grob: Es kam
    # ein weicher Klumpen heraus statt der ausgefransten Wolke (14.09.2026 im Bild gesehen).
    # Die Fransen sind kein Beiwerk; an einer glatten Scheibe ist X-Plane am 13.09.2026
    # schon einmal gescheitert ("Kette aus Kugeln").
    gitterfolge = [2]
    while gitterfolge[-1] < kante // 4:
        gitterfolge.append(gitterfolge[-1] * 2)
    for gitter in gitterfolge:
        klein = Image.new("L", (gitter, gitter))
        klein.putdata([rnd.randrange(256) for _ in range(gitter * gitter)])
        gross = klein.resize((kante, kante), Image.BICUBIC)
        for i, wert in enumerate(gross.getdata()):
            summe[i] += (wert / 255.0) * amplitude
        gesamt += amplitude
        amplitude *= 0.55
    return [w / gesamt for w in summe]


def textur_schreiben(pfad: Path, atlas: int = ATLAS, zelle: int = ZELLE) -> None:
    """Wolkige Formen auf einem Blatt -- `atlas` x `atlas` Stück.

    WEISS, nicht farbig: Die Farbe kommt aus `TINT` in der .pss. So tragen alle Säulen
    dieselbe Textur, und eine weitere Farbe kostet nur eine .pss.

    ⚠ **MSFS RUFT DIESELBE FUNKTION MIT `atlas=1`**, und das ist kein Geschmack, sondern
    der Unterschied zwischen den beiden Partikelsystemen:

    * X-Plane kennt Zellen (`TEX_CELLS_X/Y`, `ANIM_CELL_RANDOM 1`) und zieht für jedes
      Partikel **eine** der sechzehn Formen.
    * MSFS kennt sie nicht. Sein Material bildet die Datei mit `UVScale 1.0` auf **jedes**
      Partikel ab -- ein Partikel zeigte damit alle sechzehn Scheiben auf einmal, als
      Raster. Hundert solcher Raster übereinander ergeben die glatte, strukturlose Fläche,
      die am 14.09.2026 im Bild stand (Screenshot 11:53) -- eine einzelne Wolke war darin
      nicht auszumachen, und konnte es rechnerisch auch nicht.

    Asobos eigene Rauchtextur (`Samples/.../vfx_smoke.png`, 512x512) ist genau deshalb
    **eine** grosse fransige Wolke über die volle Fläche, und sein Material steht ebenfalls
    auf `UVScale 1.0`. Wir folgen dem Vorbild, das nachweislich funktioniert.

    ⚠ **Eine glatte Scheibe darf daraus nicht werden** -- das war in X-Plane am 13.09.2026
    schon einmal der Fehler ("Kette aus Kugeln"). Die Fransigkeit kommt hier aus dem
    Schwellwert unten, nicht aus der Zellenvielfalt, und bleibt bei `atlas=1` erhalten.
    """
    from PIL import Image

    kante = atlas * zelle
    bild = Image.new("RGBA", (kante, kante), (255, 255, 255, 0))
    pixel = bild.load()
    mitte = (zelle - 1) / 2.0

    for zy in range(atlas):
        for zx in range(atlas):
            rausch = _rauschen(zelle, keim=1000 + zy * atlas + zx)
            # Das Rauschen auf den vollen Bereich 0..1 strecken. Ohne diesen Schritt liegen
            # die Werte um 0,5 herum, und nach Schwellwert und Randabfall bleibt ein blasses
            # Klümpchen in der Zellenmitte übrig -- gemessen am 13.09.2026: Spitzendeckkraft
            # 155 statt 255, und nur 9,7 % der Fläche überhaupt sichtbar.
            tief, hoch = min(rausch), max(rausch)
            spanne = (hoch - tief) or 1.0
            for y in range(zelle):
                for x in range(zelle):
                    d = math.hypot(x - mitte, y - mitte) / mitte
                    if d >= 1.0:
                        continue
                    # Der Randabfall greift erst im äußeren Drittel. Vorher stand hier ein
                    # cos²-Verlauf über die ganze Zelle -- der dämpft schon in der Mitte auf
                    # die Hälfte und lässt der Form keinen Platz.
                    rand = 1.0 if d < 0.62 else math.cos((d - 0.62) / 0.38 * math.pi / 2.0)
                    roh = ((rausch[y * zelle + x] - tief) / spanne) * rand

                    # Der Schwellwert ist das, was die Form FRANSIG macht: Alles darunter
                    # fällt weg, der Rest wird gespreizt. Ohne ihn bleibt eine weiche Scheibe
                    # mit etwas Struktur -- mit ihm entstehen Ausläufer, Löcher und Zipfel,
                    # so wie auf Laminars Blatt.
                    a = (roh - 0.18) / 0.82
                    if a <= 0.0:
                        continue
                    pixel[zx * zelle + x, zy * zelle + y] = (
                        255, 255, 255, int(round(min(1.0, a) * 255)))
    bild.save(pfad, "PNG")


def groessen_stuetzen() -> list[tuple[float, float]]:
    """Die Größenkurve aus Fuß, Ende und den Anteilen -- nie von Hand eingetragen."""
    spanne = GROESSE_ENDE_M - GROESSE_START_M
    return [(t, GROESSE_START_M + anteil * spanne) for t, anteil in _GROESSE_STUETZEN]


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
        # Der Atlas, und die Zufallswahl daraus. ANIM_CELL_RANDOM 1 heißt: Jeder Partikel
        # zieht beim Entstehen eine der 16 Formen -- das ist der Unterschied zwischen einer
        # Perlenkette und einer Rauchfahne.
        f" TEX_CELLS_X {ATLAS}",
        f" TEX_CELLS_Y {ATLAS}",
        " ANIM_CELL_START 0",
        f" ANIM_CELL_COUNT {ATLAS * ATLAS}",
        " ANIM_CELL_REPEAT 1",
        " ANIM_CELL_RANDOM 1",
        _kurve("ANIM_CELL_KF", [(0.0, 0.0), (1.0, 0.0)]),
        # Die Wolke dehnt sich beim Aufsteigen: 1,5 m am Fuß, 14 m oben.
        #
        # ⚠ Hier stand 3 → 12 → 30 m, und das ergab eine KUGEL statt einer Säule
        # (13.09.2026, im Bild gesehen): Bei 5 m/s und 22 s steigt ein Partikel gut 100 m --
        # ist er dabei 30 m breit, überlappen die Nachbarn vollständig. Laminars eigener
        # `tire_smoke` geht auf 10 m, `engine_smoke_piston` auf 5 m.
        #
        # Unten schmal, oben weit -- der schmale Fuß macht die Quelle ortbar, die breite
        # Krone macht die Säule von weitem sichtbar, und der Übergang dazwischen ist das,
        # was sie wie aufsteigenden Rauch aussehen lässt statt wie eine Wolke auf einem
        # Stiel. Die Zahlen stehen oben bei _GROESSE_STUETZEN und werden gerechnet.
        #
        # Die Lücken am Fuß (13.09.2026, einzelne Kügelchen mit Luft dazwischen) kamen NICHT
        # von zu kleinen Partikeln, sondern von zu wenigen: 23 Stück im untersten Meter,
        # gestreut über einen Kegel von ±20°. Mit 220 statt 70 je Sekunde und ±11° sind es
        # 72 Stück auf 2,8 m² Querschnitt -- eine 29-fache Überdeckung, da bleibt nichts offen.
        #
        # Ein Zwischenstand hatte hier 3,0 m stehen. Das war doppelt gemoppelt und zog gegen
        # die eben erst verengte Kegelöffnung: Der Fuß wäre breiter geworden als die Säule.
        _kurve("SIZE_CURVE", groessen_stuetzen(), "CUBIC_AVG"),
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
        # ⚠ DIE DECKKRAFT MUSS SCHNELLER FALLEN, ALS DIE FLÄCHE WÄCHST. Das ist der
        # Rechenfehler, der am 13.09.2026 die Keule oben erzeugt hat:
        #
        #   Ein Partikel wuchs von 1,5 m auf 28 m -- die überdeckte Fläche steigt damit um
        #   das 350-fache (28²/1,5²). Die Deckkraft fiel im selben Zug nur von 0,24 auf 0,08,
        #   also auf ein Drittel. Netto war die Krone rund HUNDERTMAL dichter als der Fuß --
        #   während eine echte Rauchsäule nach oben hin durchsichtiger wird.
        #
        # Deshalb jetzt: 0,30 am Fuß, aber schon bei einem Viertel der Höhe nur noch 0,12 und
        # bei zwei Dritteln 0,035. Zusammen mit der flacheren Größenkurve (18 m statt 28)
        # nimmt die Gesamtdeckung nach oben ab, statt zu.
        #
        # Vorbild sind echte Fotos von Signalrauch (Nutzer, 13.09.2026): unten dicht und
        # quellend, oben breit, hell und ausgefranst.
        # ⚠ DIE DECKKRAFT SUMMIERT SICH ÜBER DIE ÜBERLAPPUNGEN, und danach muss sie
        # bemessen werden -- nicht danach, wie ein einzelner Partikel aussieht:
        #
        #   Gesamtdeckung = 1 - (1 - alpha)^N   bei N übereinanderliegenden Partikeln
        #
        # Mit alpha 0,30 und N ≈ 20 sind das 99,9 % -- eine massive Wand, durch die weder
        # die Wolkenstruktur noch der Himmel dringt. Genau so sah es aus. Mit alpha 0,09
        # und N ≈ 10 bleiben 61 %, und das ist Rauch.
        # ⚠ DAS ERSTE FÜNFTEL IST UNDURCHSICHTIG, und zwar auf ausdrücklichen Wunsch
        # (13.09.2026): Eine Rauchquelle, durch die man den Himmel sieht, ist als Marke
        # wertlos -- sie soll ja auffallen. 0,95 heißt: fast jeder einzelne Partikel deckt
        # für sich. Was dann noch durchscheint, sind die LÖCHER der Wolkenformen, und die
        # decken sich bei mehreren übereinander gegenseitig ab.
        #
        # Danach fällt die Kurve steil -- die Krone bleibt so dünn und verweht wie zuvor.
        # Genau dieser Gegensatz macht die Säule aus: unten Quelle, oben Auflösung.
        # ⚠ DIE OBEREN WERTE SIND GEGEN DIE DREIFACHE PARTIKELZAHL GERECHNET.
        # Wer EMIT_RATE verdreifacht, verdreifacht auch die Überlappungen -- und damit wäre
        # die Krone schlagartig wieder eine Wand. Damit die Gesamtdeckung dort gleich bleibt,
        # muss die Deckkraft auf a_neu = 1 - (1 - a_alt)^(1/3) fallen: aus 0,16 wird 0,06,
        # aus 0,05 wird 0,018. Unten dagegen bleibt sie hoch, denn dort SOLL es dicht sein.
        _kurve("ALPHA_CURVE", [(0.0, 0.0), (0.02, 0.70), (0.20, 0.50),
                               (0.42, 0.06), (0.68, 0.018), (0.88, 0.005), (1.0, 0.0)]),
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
        _kurve("TURBULENCE", [(0.0, 0.05), (0.3, 0.5), (1.0, 1.6)], "CUBIC_AVG"),
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
        # ⚠ DIE ZWEITE UND DRITTE SPALTE SIND EINE SPANNE, kein Wiederholungsfehler:
        # X-Plane würfelt für jeden Partikel einen Wert dazwischen. Hier stand zweimal
        # derselbe -- alle Partikel stiegen exakt gleich schnell, im Gleichschritt, und
        # genau deshalb blieb die Säule eine geschlossene Wurst statt zu zerfasern
        # (13.09.2026, dreimal im Bild gesehen).
        #
        # 1,5 bis 5,4 m/s heißt: Die schnellsten sind am Ende ihrer Lebenszeit dreimal so
        # hoch wie die langsamsten. Das allein franst die Fahne auf.
        _kurve("INITIAL_SPEED", [(0.0, AUFSTIEG_MS * 0.5, AUFSTIEG_MS * 1.8),
                                 (1.0, AUFSTIEG_MS * 0.5, AUFSTIEG_MS * 1.8)], "LINEAR"),
        _kurve("ROTATION_SPEED", [(0.0, 0.5, 1.0), (1.0, 0.5, 1.0)], "CUBIC_AVG"),
        _kurve("INITIAL_HEADING", [(0.0, 0.0, 360.0), (1.0, 0.0, 360.0)], "CUBIC_AVG"),
        # 90° = senkrecht nach oben; die SPANNE ist die Auffächerung.
        #
        # ⚠ Hier stand 88-92°, also ±2° -- und damit blieb die Säule geometrisch eine Röhre,
        # egal wie stark die Turbulenz wackelte. Eine echte Rauchsäule wird nach oben breiter,
        # weil sie aus einem KEGEL austritt.
        #
        # ±11° ergibt bei 10 m Höhe rund 2 m Breite (die Quelle bleibt also ortbar) und bei
        # 90 m gut 17 m -- genau der Trichter, den die Fotos zeigen. Der Effekt ist reine
        # Geometrie und damit sicher, während TURBULENCE bei Laminar nie über 0,25 geht und
        # unser Wert von 1,6 ungemessen ist.
        # ±11° statt ±20°: Der weite Kegel hat die wenigen Partikel am Fuß über zu viel
        # Fläche verteilt. Die Breite oben kommt ohnehin aus der gestreuten Geschwindigkeit
        # und der Turbulenz, nicht aus dem Austrittswinkel.
        _kurve("INITIAL_PITCH", [(0.0, 79.0, 101.0), (1.0, 79.0, 101.0)], "CUBIC_AVG"),
        _kurve("DX", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]),
        _kurve("DY", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]),
        _kurve("DZ", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]),
        # Etwas Streuung am Fuß, damit die Quelle nicht wie ein Punkt aussieht.
        _kurve("DLON", [(0.0, 0.0, 0.7), (1.0, 0.0, 0.7)], "CUBIC_AVG"),
        _kurve("DLAT", [(0.0, 0.0, 0.7), (1.0, 0.0, 0.7)], "CUBIC_AVG"),
        _kurve("INITIAL_ROTATION", [(0.0, 0.0, 360.0), (1.0, 0.0, 360.0)], "CUBIC_AVG"),
        _kurve("INITIAL_SIZE", [(0.0, 0.8, 1.2), (1.0, 0.8, 1.2)], "LINEAR"),
        _kurve("INITIAL_ALPHA", [(0.0, 1.0, 1.0), (1.0, 1.0, 1.0)], "CUBIC_AVG"),
        # Auch die Lebensdauer streut -- sonst enden alle Partikel auf derselben Höhe,
        # und die Krone bekommt eine waagerechte Kante.
        _kurve("TIME_TO_LIVE", [(0.0, LEBENSDAUER_S * 0.55, LEBENSDAUER_S),
                                (1.0, LEBENSDAUER_S * 0.55, LEBENSDAUER_S)], "LINEAR"),
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
        f" TEX_CELLS_X {ATLAS}",
        f" TEX_CELLS_Y {ATLAS}",
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
