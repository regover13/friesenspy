"""Baut aus den Effekten ein fertiges MSFS-Paket: Material, Trägermodell, SimObjects.

Teil zwei von `rauch_bauen.py` (der die Effekt-XMLs erzeugt). Hier entsteht alles, was es
braucht, damit `AICreateSimulatedObject` einen Titel wie `FrsRauch_Signalrot` annimmt:

    PackageSources/
      VisualEffectLibs/devprops/friesenrauch/   die sechs Effekte (aus rauch_bauen.py)
      MaterialLibs/friesenrauch-mat/            Textur + Material
      SimObjects/Misc/FrsRauch/                 sim.cfg + ein Trägermodell je Farbe
    PackageDefinitions/                         drei Pakete
    FriesenRauch.xml                            das Projekt für fspackagetool

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
    flaechen = [
        ((0.0, 0.0, -1.0), [(-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)]),
        ((0.0, 0.0, 1.0), [(1, -1, 1), (1, 1, 1), (-1, 1, 1), (-1, -1, 1)]),
        ((0.0, -1.0, 0.0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
        ((0.0, 1.0, 0.0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
        ((-1.0, 0.0, 0.0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
        ((1.0, 0.0, 0.0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
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
            {"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3",
             "min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
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


def behavior_xml(kennung: str, knoten: str, fx_guid: str) -> str:
    r"""Verknüpft den Modellknoten mit dem Partikeleffekt.

    ⚠ VIER DINGE WAREN HIER FALSCH, und alle vier blieben stumm oder meldeten sich erst
    Schritt für Schritt — das Paket baute, die Objekte entstanden im Simulator, und es
    rauchte nicht (13.09.2026, auf Wangerooge):

      1. Der umschließende Tag im model.xml hieß `<Behaviors>` statt `<CompileBehaviors
         version="2">` — dazu mehr in `simobjects_schreiben()`. Ohne den richtigen Tag
         wird die Datei nie kompiliert, das Objekt existiert aber trotzdem (nur ohne
         jedes Verhalten) — deshalb tauchte es im SimObject Spawner auf, aber nicht in
         der Behaviors-Liste des DevMode.
      2. Die Vorlage heißt `ASOBO_VFX_Template`. Ich hatte `ASOBO_VFX_Base_Template`
         geschrieben — abgeleitet aus dem Namen der ParametersFn, nicht nachgeschlagen.
         Eine unbekannte Vorlage erzeugt keinen Fehler, sie tut einfach nichts.
      3. `ASOBO_VFX_Template` ist NICHT automatisch bekannt — sie muss eingebunden werden.
         Der erste Versuch (`Include ModelBehaviorFile="Asobo_EX1\Common\Exterior\
         Templates\VFX.xml"`, aus echten Flugzeugmodellen wie `Asobo_C172SP` abgeschrieben)
         schlug weiter fehl: Diese Datei BENUTZT `ASOBO_VFX_Template` bloß, definiert es
         nicht. Die Definition liegt in `Base\Component\VFX.xml` — die wiederum selbst
         von `Helper\ParametersFnHelpers.xml` abhängt (für
         `ASOBO_PFN_Call_Overridable_ParametersFn_Helper`), eingebunden in genau dieser
         Reihenfolge durch `Base\Index.xml`. Der sichere Weg ist deshalb nicht die
         Einzeldatei, sondern die Root-Indexdatei `Asobo_EX1\Index.xml` — sie lädt
         `Base\Index.xml`, `Common\Index.xml` und `Generic\Index.xml` in der richtigen
         Reihenfolge. Genau das macht auch jedes echte Flugzeugmodell als ALLERERSTEN
         Include, noch vor dem (unnötigen) Include der Einzeldatei.
      4. Der Knoten steht als ATTRIBUT am Component (`Node="…"`), nicht als Parameter.
         So macht es auch Emeralds kompilierte Datei.

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
    return f"""<ModelBehaviors>
\t<Include ModelBehaviorFile="Asobo_EX1\\Index.xml" />
\t<Component ID="{kennung}" Node="{knoten}">
\t\t<UseTemplate Name="ASOBO_VFX_Template">
\t\t\t<FX_GUID>{fx_guid}</FX_GUID>
\t\t\t<FX_NAME>{kennung}</FX_NAME>
\t\t\t<FX_CODE>1 0 &gt;</FX_CODE>
\t\t</UseTemplate>
\t</Component>
</ModelBehaviors>
"""


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
            '\t</LODS>\n\t<CompileBehaviors version="2">\n'
            f'\t\t<IncludeBase RelativeFile="{kennung}.behavior.xml"/>\n'
            "\t</CompileBehaviors>\n</ModelInfo>\n", encoding="utf-8", newline="\r\n")
        gltf_json, gltf_puffer = wuerfel_gltf(knoten, f"{kennung}.bin")
        (wurzel / modell / f"{kennung}.gltf").write_text(
            gltf_json, encoding="utf-8", newline="\n")
        (wurzel / modell / f"{kennung}.bin").write_bytes(gltf_puffer)
        (wurzel / modell / f"{kennung}.behavior.xml").write_text(
            behavior_xml(kennung, knoten, guid(name, "fx")), encoding="utf-8", newline="\r\n")

        teile += [f"[fltsim.{i}]", f"title={kennung}", f"model={name}", "texture=", ""]

    # ⚠ OHNE DIESEN BLOCK ERKENNT DER PACKAGE BUILDER GAR NICHTS. Er meldete jede einzelne
    # Datei als „Unlisted file … See 'Extra' category" — selbst die sim.cfg (13.09.2026, im
    # Project Editor). `category` sagt ihm, WAS für ein SimObject das ist; fehlt die Angabe,
    # hält er den ganzen Ordner für Beiwerk und baut ihn nicht.
    #
    # `StaticObject` ist derselbe Wert, den Emerald für seinen Schornsteinrauch benutzt —
    # nachgesehen in dessen `SimObjects/Misc/ESD_Env/sim.cfg`.
    teile += ["[General]", "category=StaticObject", ""]

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
                 "SimObjects\\Misc\\FrsRauch\\"))

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


def main() -> None:
    material_schreiben()
    simobjects_schreiben()
    definitionen_schreiben()
    print("\nJetzt bauen:")
    print(r"  .\bauen.ps1")
    print("  ⚠ startet MSFS SICHTBAR im Baumodus und beendet es danach selbst.")
    print("    Nicht aufrufen, waehrend jemand fliegt -- erst ansagen.")


if __name__ == "__main__":
    main()
