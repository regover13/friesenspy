"""Baut aus den Effekten ein fertiges MSFS-Paket: Material, Trägermodell, SimObjects.

Teil zwei von `rauch_bauen.py` (der die Effekt-XMLs erzeugt). Hier entsteht alles, was es
braucht, damit `AICreateSimulatedObject` einen Titel wie `FrsRauch_Signalrot` annimmt:

    PackageSources/
      VisualEffectLibs/devprops/friesenrauch/   die sechs Effekte (aus rauch_bauen.py)
      MaterialLibs/friesenrauch-mat/            Textur + Material
      SimObjects/Misc/FrsRauch/                 sim.cfg + ein Trägermodell je Farbe
      SimObjects/Misc/FrsSeehund/               der Seehund, drei Größen (14.09.2026)
    PackageDefinitions/                         drei Pakete
    FriesenRauch.xml                            das Projekt für fspackagetool

⚠⚠ EIGENE MODELLE MIT TEXTUR: ZWEI STILLE FALLEN, BEIDE OHNE FEHLERMELDUNG
==========================================================================
Am 14.09.2026 beim Seehund zweimal hintereinander hineingelaufen. Der Package Builder
meldet in beiden Fällen **nichts** — er schreibt brav ein glTF, das auf
`<NAME>.PNG.KTX2` verweist, und erzeugt diese Datei einfach nicht. Im Simulator erscheint
ein farbloses Modell, und man sucht den Fehler beim Material.

1. **Die Textur gehört in `SimObjects/<Kategorie>/<Name>/texture/`**, nicht neben das
   glTF. Blenders Exporter legt sie in den Modellordner; MSFS sucht sie im
   Geschwisterordner `texture` — genau das sagt die leere Zeile `texture=` in der sim.cfg.

2. **Und sie braucht eine `.png.xml` daneben**, sonst sammelt der Builder sie nicht ein:

       <BitmapConfiguration>
           <BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot>
       </BitmapConfiguration>

   `MTL_BITMAP_DECAL0` ist der Albedo-Kanal, also die Farbe. Das Vorbild steht im SDK
   unter `Samples/DevmodeProjects/Misc/TrafficVehicles` — dort hat JEDE Textur so eine
   Begleitdatei.

Beides erzeugt `export_msfs.py` (im Robben-Arbeitsordner) automatisch; wer ein weiteres
Modell von Hand anlegt, muss daran denken.

DAS TRÄGERMODELL IST EIN UNSICHTBARER WÜRFEL
============================================

Ein Partikeleffekt braucht in MSFS ein Modell, an dessen Knoten er hängt — anders als in
X-Plane, wo eine `.obj` ganz ohne Geometrie auskommt. Emeralds Rauch-SimObject löst das mit
einem Würfel aus 24 Ecken, dessen Material `ASOBO_material_invisible` trägt; gezeichnet wird
davon nichts.

Hier steht dasselbe, nur von Hand geschrieben: glTF ist JSON, und die Eckpunkte eines Würfels
sind zwölf Dreiecke. Die Zahlen liegen als Base64 im `uri` statt in einer `.bin` — das spart
eine Datei je Farbe und ist im glTF-Standard ausdrücklich vorgesehen.
"""

from __future__ import annotations

import json
import shutil
import struct
import uuid
from pathlib import Path

HIER = Path(__file__).resolve().parent
QUELLEN = HIER / "PackageSources"
#: Der Seehund wird vor dem Bau abgedunkelt kopiert -- die Quelle in `PackageSources` bleibt
#: die helle Fassung aus dem Blender-Export, damit eine Neuausgabe sie nicht doppelt abdunkelt.
QUELLEN_SEEHUND = HIER / "PackageSourcesSeehund"
#: 0,6 = 40 % dunkler (Nutzerwunsch 20.09.2026: In direkter Sonne rendert MSFS das Tier mit
#: Helligkeit ~190, obwohl die hellste Texturfarbe nur 113 hat). In MSFS 2024 neben dem alten
#: Bau geprüft: „die dunklen Seehunde sind besser". Gilt für beide Simulatoren.
HELLIGKEIT_SEEHUND = 0.6
DEFINITIONEN = HIER / "PackageDefinitions"
# ⚠ EIGENE TEXTUR, NICHT DIE VON X-PLANE -- und der Unterschied ist das ganze Bild.
#
# Hier stand `xplane/objekte/rauch.png`: ein 4x4-Atlas mit sechzehn Wolkenformen. X-Plane
# zieht daraus je Partikel EINE Zelle (`ANIM_CELL_RANDOM`). MSFS kann das nicht -- sein
# Material bildet die Datei mit `UVScale 1.0` auf JEDES Partikel ab. Jedes MSFS-Partikel
# zeigte damit alle sechzehn Scheiben gleichzeitig, als Raster; uebereinandergelegt ergab
# das die glatte, strukturlose Saeule vom 14.09.2026 (Screenshot 11:53). Es konnte gar
# keine Wolke werden.
#
# Asobos `vfx_smoke.png` aus dem SDK ist deshalb EINE grosse fransige Wolke ueber die volle
# Flaeche. Genau die entsteht hier -- dieselbe Funktion, `atlas=1`.
TEXTUR = HIER / "rauch_msfs.png"
KANTE = 512

from rauch_bauen import FARBEN, NAMENSRAUM, guid  # noqa: E402  (nach den Pfaden)

HERSTELLER = "devprops"


# --------------------------------------------------------------------------- Trägermodell

# ⚠ WARUM DER WUERFEL KLEIN BLEIBT, obwohl die Sichtweite an der Groesse haengt.
#
# Die naheliegende Idee waere, ihn aufzublasen: Ein 100-m-Wuerfel hat aus 10 km eine
# messbare Bildschirmgroesse und wuerde nicht ausgeblendet. Das ist aber der Umweg --
# `minSize="0"` im LOD-Eintrag (s. unten) schaltet die Groessenpruefung direkt ab, und
# genau so macht es Asobo in seinem eigenen Szenerie-Beispiel.
#
# Ein grosser unsichtbarer Wuerfel haette ausserdem Nebenwirkungen, die keiner will: Die
# Geometrie wandert in jede Entfernungsrechnung des Simulators, und `auf_boden` setzt den
# URSPRUNG auf die Gelaendehoehe -- ein Wuerfel, der 50 m nach unten reicht, steckt dann zur
# Haelfte im Boden. Klein und ohne Groessenpruefung ist beides zusammen.
def wuerfel_gltf(knoten: str, bin_datei: str) -> tuple[str, bytes]:
    """Ein unsichtbarer Einheitswürfel als glTF. Gibt (JSON-Text, Rohpuffer) zurück.

    ⚠ VIERUNDZWANZIG ECKEN, NICHT ACHT — und das ist kein Detail: Der glTF-Compiler des SDK
    bricht sonst ab mit *„Primitive has no NORMAL data; computing flat normals is not
    implemented"* (13.09.2026). Er rechnet Normalen nicht selbst aus, sie müssen in der Datei
    stehen. Eine Würfelecke gehört aber zu drei Flächen mit drei verschiedenen Normalen, also
    braucht jede Fläche ihre eigenen vier Ecken.

    Genau deshalb hat auch Emeralds Trägermodell 24 Ecken. Das war mir aufgefallen, ohne dass
    ich den Grund verstanden hatte — jetzt steht er hier.

    ⚠ KEIN EINGEBETTETES BASE64, SONDERN EINE ECHTE .bin-DATEI DANEBEN — der zweite, viel
    teurere Fund vom selben Tag: Ein `data:`-URI im `buffers`-Eintrag baut zwar fehlerfrei
    und wird von keinem Validator bemängelt, aber der MSFS-Modell-Compiler schreibt ihn beim
    Kompilieren still auf eine externe Referenz um (`"uri":"<Kennung>.bin"`), OHNE diese
    Datei zu erzeugen. Ergebnis im Sim: „Failed to load model data: File not found :
    FrsRauch_Signalorange.bin" — das Trägermodell lädt nie, egal wie richtig Material und
    Verhalten längst waren. Deshalb jetzt von Anfang an eine externe .bin, die tatsächlich
    im Paket liegt.
    """
    # Je Fläche: Normale und vier Ecken gegen den Uhrzeigersinn.
    # ⚠ DER TRAEGER IST SO GROSS WIE DIE SAEULE -- und das ist der dritte Anlauf.
    #
    # Er war ein 2-m-Wuerfel (+-1 m). Aus 10 km ist das ein Subpixel, und MSFS zeichnet ein
    # SimObject nicht, dessen Bildschirmgroesse verschwindet -- mit ihm verschwindet der
    # Emitter, der an ihm haengt. Die Saeule ist 90 m hoch und trotzdem fort, weil der
    # Simulator den TRAEGER misst.
    #
    # Zwei Versuche davor gingen daneben, beide am 14.09.2026 im Flug widerlegt:
    #   * `minSize="0"` im LOD -- stammt aus einem SZENERIE-Beispiel und greift bei
    #     SimObjects offenbar nicht.
    #   * `DistanceToNotAnimate=15000` in der sim.cfg -- regelt die Animation, nicht das
    #     Zeichnen.
    # Der Nutzer hatte von Anfang an die richtige Vermutung ("kann man das modell nicht
    # unsichtbar vergroessern"); ich hatte sie mit einem Umweg abgetan, der nichts brachte.
    #
    # ⚠ NUR NACH OBEN, NICHT IN ALLE RICHTUNGEN. `auf_boden` setzt den URSPRUNG auf die
    # Gelaendehoehe -- ein Wuerfel, der 45 m nach unten reicht, steckt zur Haelfte im Boden
    # und zieht seine Bildschirmgroesse aus etwas, das niemand sieht. Deshalb 0 bis 90 m in
    # der Hoehe (genau die Saeulenhoehe) und +-6 m in der Breite (die Krone misst 12 m).
    #
    # In glTF ist Y oben.
    # ⚠ DIE GROESSE IST EINE MESSREIHE, KEINE EINSTELLUNG -- Stand 14.09.2026:
    #
    #     Traeger      sichtbar ab
    #      2 m           100 m      (der urspruengliche Wuerfel)
    #     90 m             1 km     (Saeulenhoehe -- Faktor 45 brachte Faktor 10)
    #    300 m             ?        <- dieser Versuch
    #
    # Der Zusammenhang ist NICHT linear. Bringt 300 m rund 3 km, ist er es ab hier doch,
    # und 10 km waeren erreichbar. Bringt es weniger, laeuft es gegen eine Grenze des
    # Simulators -- dann ist ein LICHT der richtige Weg (s. MESSLISTE, `wENLK_lightdummy`).
    #
    # Der Nutzer will 10 km; gemessen sind fuer ein grosses Objekt 22 km (CruiseShip01,
    # 11.09.2026), es gibt also keine harte Schranke bei 1 km.
    # ⚠⚠ 300 m BRACHTEN NICHTS -- ABER DIE MESSUNG WAR VERDECKT, UND DAS IST DER PUNKT.
    #
    #      2 m ->  100 m     das Objekt selbst war zu klein
    #     90 m -> 1830 m     Objekt gross genug; ab hier greift etwas anderes
    #    300 m -> 1830 m     unveraendert
    #
    # Ich habe daraus zuerst gelesen: "ueber 90 m bringt Geometrie nichts". Das ist FALSCH,
    # und der Fehler ist eine Verwechslung von zwei Schranken, die zufaellig hintereinander
    # liegen. Waehrend dieser ganzen Reihe stand `MaxDistanceEmission` noch auf der Vorgabe
    # 2000 -- die Partikel hoerten also bei rund 1830 m von sich aus auf zu entstehen. Ab
    # 90 m Traeger war NICHT mehr die Geometrie der Engpass, sondern der Effekt. Die
    # 300-m-Zeile misst deshalb gar nicht die Geometrie; sie misst dieselbe Partikelgrenze
    # ein zweites Mal.
    #
    # WAS TATSAECHLICH BELEGT IST, sind genau zwei Punkte:
    #
    #      2 m ->  100 m         mit `minSize="0"` bereits gesetzt (Commit f7673a6, einen
    #                            Commit VOR der 90-m-Saeule -- der Nutzer ist dazwischen
    #                            geflogen und sah keine Aenderung)
    #     90 m -> MINDESTENS 1830 m   wie viel mehr, verdeckt die Partikelgrenze
    #
    # Dazwischen und darueber ist nichts gemessen. Zum Vergleich von aussen: Ein
    # CruiseShip01 war am 11.09.2026 aus 22 km zu sehen -- Geometrie traegt also weit.
    #
    # ⭐ WICHTIG FUER ALLES OHNE PARTIKEL (Seehunde, Tiere, Fahrzeuge): Dort faellt die
    # Partikelgrenze weg, und die Geometriegrenze ist die EINZIGE. Wer von hier "90 m
    # reichen, mehr bringt nichts" uebernimmt, uebernimmt einen Messfehler.
    #
    # Fuer den Rauch selbst bleiben die 90 m trotzdem richtig: Sie genuegen, damit das
    # Objekt nicht ausgeblendet wird, und weiter als der Effekt reicht, muss der Traeger
    # nicht (s. MAX_SICHT_M in rauch_bauen.py).
    B, H = 6.0, 90.0
    flaechen = [
        ((0.0, 0.0, -1.0), [(-B, 0, -B), (-B, H, -B), (B, H, -B), (B, 0, -B)]),
        ((0.0, 0.0, 1.0), [(B, 0, B), (B, H, B), (-B, H, B), (-B, 0, B)]),
        ((0.0, -1.0, 0.0), [(-B, 0, -B), (B, 0, -B), (B, 0, B), (-B, 0, B)]),
        ((0.0, 1.0, 0.0), [(-B, H, B), (B, H, B), (B, H, -B), (-B, H, -B)]),
        ((-1.0, 0.0, 0.0), [(-B, 0, B), (-B, H, B), (-B, H, -B), (-B, 0, -B)]),
        ((1.0, 0.0, 0.0), [(B, 0, -B), (B, H, -B), (B, H, B), (B, 0, B)]),
    ]

    ecken_roh = b""
    normal_roh = b""
    indizes = []
    for i, (normale, ecken) in enumerate(flaechen):
        for e in ecken:
            ecken_roh += struct.pack("<fff", float(e[0]), float(e[1]), float(e[2]))
            normal_roh += struct.pack("<fff", *normale)
        b = i * 4
        indizes += [b, b + 1, b + 2, b, b + 2, b + 3]

    index_roh = b"".join(struct.pack("<H", i) for i in indizes)
    fuell = (-(len(ecken_roh) + len(normal_roh))) % 4
    puffer = ecken_roh + normal_roh + b"\x00" * fuell + index_roh

    gltf = {
        "asset": {"version": "2.0", "generator": "FriesenBruegge paket_bauen",
                  "copyright": "devprops",
                  # Ohne diese Erweiterung warnt der Validator bei jedem Lauf. Sie sagt nur,
                  # in welcher Konvention Normalenkarten gelesen werden -- wir haben keine,
                  # aber die Warnung verstellt die Sicht auf echte Fehler.
                  "extensions": {"ASOBO_normal_map_convention":
                                 {"tangent_space_convention": "DirectX"}}},
        "scene": 0,
        "scenes": [{"nodes": [0], "name": "Scene"}],
        "nodes": [{"mesh": 0, "name": knoten}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "indices": 2, "material": 0, "mode": 4}]}],
        "materials": [{"name": "Invisible", "extensions": {"ASOBO_material_invisible": {}}}],
        "accessors": [
            # ⚠ DIE BOUNDING BOX MUSS ZUR GEOMETRIE PASSEN -- sie ist das, was der
            # Simulator fuer die Groessenpruefung liest, nicht die Eckpunkte.
            {"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3",
             "min": [-B, 0.0, -B], "max": [B, H, B]},
            {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC3",
             "min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
            {"bufferView": 2, "componentType": 5123, "count": len(indizes), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(ecken_roh), "target": 34962},
            {"buffer": 0, "byteOffset": len(ecken_roh), "byteLength": len(normal_roh),
             "target": 34962},
            {"buffer": 0, "byteOffset": len(ecken_roh) + len(normal_roh) + fuell,
             "byteLength": len(index_roh), "target": 34963},
        ],
        "buffers": [{"byteLength": len(puffer), "uri": bin_datei}],
    }
    return json.dumps(gltf, indent=1), puffer


def behaviors_inline(kennung: str, knoten: str, fx_guid: str) -> str:
    r"""Der `<Behaviors>`-Block im Modell-XML: verknüpft den Knoten mit dem Partikeleffekt.

    ⭐ SEIT 20.09.2026 DIE KLASSISCHE FORM, DIREKT IM MODELL-XML -- und sie läuft in BEIDEN
    Simulatoren. Vorher standen hier die Vorlage `ASOBO_VFX_Template` (eingebunden über
    `Asobo_EX1\Index.xml`) und `<CompileBehaviors version="2"><IncludeBase …/>`, gebaut mit
    dem MSFS-2024-SDK. Das kennt MSFS 2020 nicht: Dort lud das Modell, und es rauchte nicht,
    ohne jede Fehlermeldung. In der 2020er Doku (`Model_Definitions`) stehen die Behaviors
    direkt im Modell-XML unter `<Behaviors>`, die Vorlage heißt `ASOBO_GT_FX` und kommt aus
    `Asobo\Generic\FX.xml`. Im Flug belegt am 20.09.2026: sechs Säulen in MSFS 2020, und in
    MSFS 2024 sahen sie neben dem alten Bau IDENTISCH aus (Nutzer). Es gibt damit nur noch EINE
    Fassung, und sie wird mit dem 2020er SDK gebaut (`bauen.ps1`).

    Die früheren Fehlversuche stehen weiter da, weil sie zeigen, wie still diese Fehler sind
    (13.09.2026, auf Wangerooge — das Paket baute, die Objekte entstanden, und es rauchte
    nicht):

      * Eine unbekannte Vorlage erzeugt keinen Fehler, sie tut einfach nichts. (Ich hatte
        `ASOBO_VFX_Base_Template` geschrieben, aus dem Namen einer ParametersFn abgeleitet,
        nicht nachgeschlagen.)
      * Der Knoten steht als ATTRIBUT am Component (`Node="…"`), nicht als Parameter.
      * `<Behaviors>` mit `IncludeBase` darin war in MSFS 2024 KEIN gültiges Element -- das
        Objekt existierte, hatte aber nie Verhalten. Die inline-Form hier (`<Include>` und
        `<Component>` direkt unter `<Behaviors>`) ist etwas anderes, und sie geht.

    `FX_CODE` ist die Bedingung, unter der der Effekt läuft (ein RPN-Ausdruck). Die
    SDK-Doku: *„When it becomes true the Visual Effect is spawned. When it becomes false
    the Visual Effect is stopped."* Hier stand eine nackte `1`; geschrieben ist es jetzt
    als `1 0 >` -- derselbe Wahrheitswert, aber ein echter Vergleichsausdruck, so wie ihn
    Doku und Vorbilder aus dem DevSupport zeigen.

    ⚠ **Eine immer wahre Bedingung wird nie falsch -- der Effekt bekommt also nie ein
    Stopp-Signal.** Wird das Trägerobjekt gelöscht, wertet niemand die Bedingung mehr aus,
    und der gespawnte Emitter läuft herrenlos weiter (13.09.2026: Objekt über den Spawner
    entfernt, der Rauch blieb stehen und wuchs; erst ein Neustart des Flugs wurde ihn los).
    Die Schranke dagegen sitzt nicht hier, sondern im Effekt selbst: `TimeEmission` in
    `rauch_bauen.py`.

    Emerald setzt dort `(A:AMBIENT TEMPERATURE, celsius) 10 <=`, weshalb ihr Schornstein im
    Sommer nicht raucht. Eine Signalsäule brennt dagegen, solange die Patrone brennt.
    """
    return (
        "\t<Behaviors>\n"
        '\t\t<Include ModelBehaviorFile="Asobo\\Generic\\FX.xml" />\n'
        f'\t\t<Component ID="{kennung}" Node="{knoten}">\n'
        '\t\t\t<UseTemplate Name="ASOBO_GT_FX">\n'
        f"\t\t\t\t<FX_GUID>{fx_guid}</FX_GUID>\n"
        "\t\t\t\t<FX_CODE>1 0 &gt;</FX_CODE>\n"
        "\t\t\t</UseTemplate>\n\t\t</Component>\n\t</Behaviors>\n"
    )


# --------------------------------------------------------------------------- Paketteile

def material_schreiben() -> None:
    ziel = QUELLEN / "MaterialLibs" / "friesenrauch-mat"
    (ziel / "Textures").mkdir(parents=True, exist_ok=True)
    if not TEXTUR.exists():
        # Beim ersten Lauf (und nach jedem Aufraeumen) selbst erzeugen -- eine Wolke ueber
        # die volle Flaeche, gebaut von derselben Rauschfunktion wie die X-Plane-Kacheln.
        # ⚠ NICHT ueber sys.path importieren: Beide Fassungen haben eine Datei
        # `rauch_bauen.py`, und die MSFS-eigene steckt beim Aufruf schon in sys.modules --
        # ein `from rauch_bauen import ...` findet dann die falsche und scheitert mit
        # ImportError (14.09.2026 passiert). Ueber die Dateispezifikation geladen, bekommt
        # das X-Plane-Modul einen eigenen Namen und kollidiert nicht.
        import importlib.util
        quelle = HIER.parent / "xplane" / "rauch_bauen.py"
        spec = importlib.util.spec_from_file_location("xplane_rauch_bauen", quelle)
        xp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(xp)
        xp.textur_schreiben(TEXTUR, atlas=1, zelle=KANTE)
        print(f"  Textur gebaut: {TEXTUR.name} ({KANTE}x{KANTE}, eine Wolke)")
    shutil.copy(TEXTUR, ziel / "Textures" / "frs_rauch.png")
    # ⚠ NICHT LEER: Die .FLAGS sagt dem Paketwerkzeug, wie die Textur zu behandeln ist.
    # Ohne Inhalt bricht die TextureLib-Erzeugung mit "Failed to retrieve textures
    # informations" ab (13.09.2026 im Project Editor gesehen). Der Wert stammt aus dem
    # SDK-Beispiel SimpleFX, das denselben Zweck erfuellt.
    (ziel / "Textures" / "frs_rauch.png.FLAGS").write_text(
        "_DEFAULT=+PRECOMPUTEDINVAVG+QUALITYHIGH", encoding="utf-8")

    # ⚠ SECHS MATERIALDATEIEN, NICHT EINE -- die Bindung Effekt<->Material läuft über den
    # DATEINAMEN, es gibt im VisualEffect-Format keinen Tag, der ausdrücklich darauf
    # verweist (nachgesehen: kein einziges VisualEffect.*-Element im ganzen SDK erwähnt
    # "Material" oder "Texture"). Das SDK-Beispiel SimpleFX bestätigt das indirekt: sein
    # Effekt heißt `EngineSmoke.xml`, sein Material `EngineSmoke.material` -- derselbe
    # Basisname. Eine gemeinsame `FrsRauch.material` für sechs Effekte mit Namen wie
    # `FrsRauch_Navy.xml` passt zu KEINEM davon; ohne passendes Material bekommt ein
    # Partikel keine Textur und zeichnet vermutlich gar nichts (13.09.2026: sechs
    # kompilierte, korrekt verdrahtete Effekte, null sichtbarer Rauch im Flug).
    #
    # Der Atlas bleibt derselbe wie in X-Plane: 4x4 Wolkenformen, weiss mit Alpha. Die
    # Farbe kommt aus dem Effekt (ParticleColor), nicht aus dem Material -- deshalb
    # unterscheiden sich die sechs Materialdateien nur im Namen, nicht im Inhalt.
    for name in FARBEN:
        kennung = f"FrsRauch_{name.capitalize()}"
        (ziel / f"{kennung}.material").write_text(
            f'<Material Version="1.4.0" Name="{kennung}" Guid="{guid("material_" + name)}" '
            'SurfaceType="UNDEFINED" Type="CODE_DIFFUSE" Metal="0.000000" Rough="0.000000" '
            'Opacity="1.000000" BlendMode="Transparent">\n'
            "\t<TagList/>\n\t<FlagList/>\n"
            "\t<TextureList>\n"
            '\t\t<Texture FileName="Textures\\frs_rauch.png" Binding="MTL_BITMAP_DECAL0"/>\n'
            "\t</TextureList>\n"
            "\t<Attributes>\n"
            '\t\t<Diffuse Red="1.000000" Green="1.000000" Blue="1.000000"/>\n'
            '\t\t<Emissive Red="0.000000" Green="0.000000" Blue="0.000000"/>\n'
            '\t\t<UVOffset U="0.000000" V="0.000000"/>\n'
            '\t\t<UVScale U="1.000000" V="1.000000"/>\n'
            "\t\t<UVRotate>0.000000</UVRotate>\n"
            "\t</Attributes>\n</Material>\n", encoding="utf-8", newline="\r\n")
    (ziel / "Library.xml").write_text('<Library Version="1.1.0">\n</Library>\n',
                                      encoding="utf-8", newline="\r\n")
    print(f"  Material + Textur ({TEXTUR.stat().st_size} Bytes)")


def simobjects_schreiben() -> None:
    wurzel = QUELLEN / "SimObjects" / "Misc" / "FrsRauch"
    wurzel.mkdir(parents=True, exist_ok=True)

    teile = ["[VERSION]", "Major=1", "Minor=0", ""]
    for i, name in enumerate(FARBEN):
        kennung = f"FrsRauch_{name.capitalize()}"
        modell = f"model.{name}"
        knoten = f"frs_rauch_{name}"
        (wurzel / modell).mkdir(exist_ok=True)
        (wurzel / modell / "model.CFG").write_text(
            f"[models]\nnormal={kennung}.xml\n", encoding="utf-8", newline="\r\n")
        # (Bis 20.09.2026 stand hier <CompileBehaviors version="2"> mit einer eigenen
        # .behavior.xml -- die 2024er Form, die MSFS 2020 nicht kennt. Jetzt die klassische
        # Form direkt im Modell-XML, s. `behaviors_inline`. Die Notizen unten beschreiben den
        # alten Weg und bleiben als Chronik der Fehlversuche stehen.)
        #
        # ⚠ DER TAG HEISST <CompileBehaviors version="2">, NICHT <Behaviors>.
        #
        # Das war der eigentliche Fehler (13.09.2026, auf Wangerooge geprueft): Das Objekt
        # entstand im Simulator (SimObject Spawner zeigte es), tauchte aber in der
        # Behaviors-Liste des DevMode gar nicht auf -- MSFS hatte die Verhaltensdatei nie
        # geladen, weil <Behaviors> mit IncludeBase kein gueltiges Element ist.
        #
        # Zwei Zwischenstaende waren beide falsch, aus demselben Missverstaendnis:
        #   1. <Behaviors><IncludeBase .../></Behaviors>            -- falscher Tagname
        #   2. <Behaviors Compiled="True" Version="2" Revision="1"> -- das ist die Syntax
        #      der KOMPILIERTEN AUSGABE (so sieht Emeralds behavior.xml aus, mit
        #      <Components>/<FXs>/<Strings> statt <UseTemplate>) -- man kann nicht
        #      Quellcode schreiben und behaupten, er sei schon kompiliert.
        #
        # Das SDK-Beispiel `GroundVehicles/AirportVehicles/.../Exterior.xml` zeigt die
        # richtige Form: <CompileBehaviors version="2"><IncludeBase .../></CompileBehaviors>
        # im model.xml, und die eingebundene Datei bleibt <ModelBehaviors> OHNE
        # Compiled-Attribute -- der Builder kompiliert sie erst beim Bauen.
        (wurzel / modell / f"{kennung}.xml").write_text(
            "<ModelInfo>\n\t<LODS>\n"
            # ⚠ `minSize="0"` -- OHNE DAS ERSCHEINT DER RAUCH ERST KURZ VORHER.
            #
            # MSFS blendet ein Modell aus, sobald seine BILDSCHIRMGROESSE unter `minSize`
            # faellt (Vorgabe > 0). Unser Traeger ist ein 2-m-Wuerfel; aus 10 km ist der ein
            # Subpixel, und mit ihm verschwindet der Emitter, der an ihm haengt -- die
            # Saeule ist 90 m hoch und trotzdem fort, weil der SIMULATOR den WUERFEL misst,
            # nicht den Rauch.
            #
            # Das war der Befund vom 14.09.2026: „der rauch erscheint sehr spaet bei
            # annaeherung!! viel zu spaet." Das Vorbild steht in Asobos eigenem
            # Szenerie-Beispiel (`kalo-projectedmesh-jetway_00.xml`): `<LOD minSize="0" …>`.
            #
            # 0 heisst: nie wegen Groesse ausblenden. Bei einer Handvoll Baaken ist das
            # richtig -- eine Rauchsaeule, die man erst sieht, wenn man daneben steht, ist
            # als Marke wertlos.
            f'\t\t<LOD minSize="0" ModelFile="{kennung}.gltf"/>\n'
            '\t</LODS>\n' + behaviors_inline(kennung, knoten, guid(name, "fx"))
            + "</ModelInfo>\n", encoding="utf-8", newline="\r\n")
        gltf_json, gltf_puffer = wuerfel_gltf(knoten, f"{kennung}.bin")
        (wurzel / modell / f"{kennung}.gltf").write_text(
            gltf_json, encoding="utf-8", newline="\n")
        (wurzel / modell / f"{kennung}.bin").write_bytes(gltf_puffer)

        teile += [f"[fltsim.{i}]", f"title={kennung}", f"model={name}", "texture=", ""]

    # ⚠ OHNE DIESEN BLOCK ERKENNT DER PACKAGE BUILDER GAR NICHTS. Er meldete jede einzelne
    # Datei als „Unlisted file … See 'Extra' category" — selbst die sim.cfg (13.09.2026, im
    # Project Editor). `category` sagt ihm, WAS für ein SimObject das ist; fehlt die Angabe,
    # hält er den ganzen Ordner für Beiwerk und baut ihn nicht.
    #
    # `StaticObject` ist derselbe Wert, den Emerald für seinen Schornsteinrauch benutzt —
    # nachgesehen in dessen `SimObjects/Misc/ESD_Env/sim.cfg`.
    # ⚠⚠ `DistanceToNotAnimate` -- OHNE DAS ERSCHEINT DER RAUCH ERST KURZ VORHER.
    #
    # Der Name sagt es woertlich: die Entfernung, ab der NICHT MEHR ANIMIERT wird. Bei einem
    # Partikeleffekt IST die Animation der Effekt -- faellt sie aus, ist die Saeule fort,
    # egal wie gross das Modell ist und egal was im LOD steht.
    #
    # Befund vom 14.09.2026: Der Nutzer sah die Saeulen erst ab rund 100 m. `minSize="0"` im
    # LOD half nicht -- das regelt die Bildschirmgroesse, nicht die Animation.
    #
    # DAS VORBILD LIEGT AUF SEINEM RECHNER, und zwar fuer denselben Flugplatz: Aerosofts
    # Wangerooge-Paket setzt es in JEDEM SimObject, und die Windsaecke dort sind von weitem
    # zu sehen:
    #
    #     EDWG_SimObjects     category=StaticObject   DistanceToNotAnimate=2000
    #     Windsock_05/_08     category=StaticObject   DistanceToNotAnimate=2000
    #     Library_SimObjects  category=StaticObject   DistanceToNotAnimate=2000
    #
    # 2000 m genuegen fuer einen Windsack. Eine Rauchsaeule ist eine BAAKE -- sie soll von
    # weitem zum Hinfliegen einladen, und der Nutzer hat 10 km gefordert. 15000 laesst Luft.
    #
    # ⚠ UNGEMESSEN ist, was das kostet: Ein Effekt, der ueber 15 km animiert wird, laeuft
    # auch dann, wenn ihn niemand ansieht. Bei einer Handvoll Baaken ist das vertretbar; bei
    # hundert gesetzten Objekten gehoert es in die Messliste.
    teile += ["[General]", "category=StaticObject", "DistanceToNotAnimate=15000", ""]

    (wurzel / "sim.cfg").write_text("\n".join(teile), encoding="utf-8", newline="\r\n")
    print(f"  {len(FARBEN)} SimObjects mit Traegermodell")


def definitionen_schreiben() -> None:
    DEFINITIONEN.mkdir(exist_ok=True)

    def paket(dateiname: str, titel: str, hinweis: str, gruppen: str) -> None:
        (DEFINITIONEN / dateiname).write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AssetPackage Version="0.1.0">\n'
            "\t<ItemSettings>\n"
            "\t\t<ContentType>MISC</ContentType>\n"
            f"\t\t<Title>{titel}</Title>\n"
            "\t\t<Manufacturer/>\n"
            f"\t\t<Creator>{HERSTELLER}</Creator>\n"
            "\t</ItemSettings>\n"
            "\t<Flags>\n\t\t<VisibleInStore>false</VisibleInStore>\n"
            "\t\t<CanBeReferenced>false</CanBeReferenced>\n\t</Flags>\n"
            f"\t<PackageOrderHint>{hinweis}</PackageOrderHint>\n"
            f"\t<AssetGroups>\n{gruppen}\t</AssetGroups>\n"
            "</AssetPackage>\n", encoding="utf-8", newline="\r\n")

    def gruppe(name: str, typ: str, quelle: str, ziel: str) -> str:
        # `Version="1"` steht in jeder SDK-Definition; ohne das Attribut nimmt der Builder
        # eine aeltere Auslegung des Typs an.
        return (f'\t\t<AssetGroup Name="{name}">\n'
                f'\t\t\t<Type Version="1">{typ}</Type>\n'
                "\t\t\t<Flags>\n\t\t\t\t<FSXCompatibility>false</FSXCompatibility>\n"
                "\t\t\t</Flags>\n"
                f"\t\t\t<AssetDir>{quelle}</AssetDir>\n"
                f"\t\t\t<OutputDir>{ziel}</OutputDir>\n"
                "\t\t</AssetGroup>\n")

    paket(f"{HERSTELLER}-friesenrauch-vfx.xml", "friesenrauch-vfx", "CUSTOM_VFX",
          gruppe("VisualEffectLib", "VisualEffectLib",
                 f"PackageSources\\VisualEffectLibs\\{HERSTELLER}\\friesenrauch\\",
                 f"VisualEffectLibs\\{HERSTELLER}\\friesenrauch\\"))
    paket(f"{HERSTELLER}-friesenrauch-mat.xml", "friesenrauch-mat", "MISC",
          gruppe("friesenrauch-mat", "MaterialLib",
                 "PackageSources\\MaterialLibs\\friesenrauch-mat\\",
                 "MaterialLibs\\friesenrauch-mat\\"))
    paket(f"{HERSTELLER}-friesenrauch.xml", "friesenrauch", "MISC",
          # ⚠ ES GIBT ZWEI BAUFORMEN, und der Typ muss zur ORDNERSTRUKTUR passen:
          #
          #   sim.cfg direkt im Objektordner   -> SimObject          (SDK-Beispiel: Bears)
          #   common/config/sim.cfg            -> ModularSimObject   (SDK: GroundVehicles)
          #
          # Unsere ist die klassische. Ein Zwischenstand stand hier auf ModularSimObject,
          # weil ich zuerst nur Flugzeugbeispiele angesehen hatte -- die sind alle modular.
          # Der Package Builder meldete daraufhin JEDE Datei als "Unlisted file ... See
          # 'Extra' category", auch die sim.cfg: Er suchte eine Struktur, die es hier nicht
          # gibt, und hielt folglich alles fuer Beiwerk.
          gruppe("SimObjects", "SimObject",
                 "PackageSources\\SimObjects\\Misc\\FrsRauch\\",
                 "SimObjects\\Misc\\FrsRauch\\") +
          # Der Seehund liegt im SELBEN Teilpaket, nur in einer zweiten Gruppe. Ein eigenes
          # Paket waere ein vierter Teil, den `msfs/paket.ps1` mitfuehren muesste -- und der
          # Nutzer wollte ausdruecklich EIN Paket ("aber ich wollte EIN Paket
          # FriesenBruegge!"). Im fertigen Community-Ordner stehen beide nebeneinander unter
          # SimObjects\Misc\.
          #
          # ⚠ Der Ordnername `msfs-rauch/` stimmt damit nicht mehr mit seinem Inhalt
          # ueberein -- hier entsteht inzwischen alles, was die Bruegge an eigenen Modellen
          # mitbringt. Eine Umbenennung ist faellig, fasst aber viele Pfade an und gehoert
          # deshalb in einen eigenen Schritt.
          gruppe("SeehundObjects", "SimObject",
                 "PackageSourcesSeehund\\SimObjects\\Misc\\FrsSeehund\\",
                 "SimObjects\\Misc\\FrsSeehund\\"))

    (HIER / "FriesenRauch.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Project Version="2" Name="FriesenRauch" FolderName="Packages" '
        'MetadataFolderName="PackagesMetadata">\n'
        "\t<OutputDirectory>.</OutputDirectory>\n"
        "\t<TemporaryOutputDirectory>_PackageInt</TemporaryOutputDirectory>\n"
        "\t<Packages>\n"
        f"\t\t<Package>PackageDefinitions\\{HERSTELLER}-friesenrauch-vfx.xml</Package>\n"
        f"\t\t<Package>PackageDefinitions\\{HERSTELLER}-friesenrauch-mat.xml</Package>\n"
        f"\t\t<Package>PackageDefinitions\\{HERSTELLER}-friesenrauch.xml</Package>\n"
        "\t</Packages>\n</Project>\n", encoding="utf-8", newline="\r\n")
    print("  3 Paketdefinitionen + Projektdatei")


def seehund_schreiben() -> None:
    """Den Seehund mit abgedunkelter Textur nach `PackageSourcesSeehund/` kopieren."""
    import shutil
    from PIL import Image

    ziel = QUELLEN_SEEHUND / "SimObjects" / "Misc" / "FrsSeehund"
    # ⚠ NICHT `rmtree` VOR DEM KOPIEREN: Auf einem OneDrive-Ordner scheiterte das am 20.09.2026 mit
    # "Zugriff verweigert" mitten im Loeschen und liess einen halben Baum zurueck -- der Bau fand
    # dann den Seehund nicht und wartete acht Minuten. Ueberschreiben (`dirs_exist_ok`) kommt ohne
    # Loeschen aus; alle Dateien der Quelle werden ohnehin neu geschrieben.
    shutil.copytree(QUELLEN / "SimObjects" / "Misc" / "FrsSeehund", ziel, dirs_exist_ok=True)
    png = ziel / "texture" / "seehund.png"
    bild = Image.open(png)
    rgb = bild.convert("RGB")
    dunkel = Image.new("RGB", rgb.size)
    dunkel.putdata([tuple(round(c * HELLIGKEIT_SEEHUND) for c in q) for q in rgb.getdata()])
    if bild.mode == "RGBA":
        dunkel.putalpha(bild.getchannel("A"))
    dunkel.save(png)
    print(f"  Seehund: Textur auf {HELLIGKEIT_SEEHUND:.0%} abgedunkelt")


def main() -> None:
    material_schreiben()
    simobjects_schreiben()
    seehund_schreiben()
    definitionen_schreiben()
    print("\nJetzt bauen:")
    print(r"  .\bauen.ps1")
    print("  ⚠ startet MSFS 2020 im Baumodus (ohne Fenster) und beendet es danach selbst.")
    print("    Nicht aufrufen, waehrend jemand fliegt -- erst ansagen.")


if __name__ == "__main__":
    main()
