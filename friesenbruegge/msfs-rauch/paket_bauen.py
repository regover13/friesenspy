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

import base64
import json
import shutil
import struct
import uuid
from pathlib import Path

HIER = Path(__file__).resolve().parent
QUELLEN = HIER / "PackageSources"
DEFINITIONEN = HIER / "PackageDefinitions"
ATLAS = HIER.parent / "xplane" / "objekte" / "rauch.png"

from rauch_bauen import FARBEN, NAMENSRAUM, guid  # noqa: E402  (nach den Pfaden)

HERSTELLER = "devprops"


# --------------------------------------------------------------------------- Trägermodell

def wuerfel_gltf(knoten: str) -> str:
    """Ein unsichtbarer Einheitswürfel als glTF, mit eingebetteten Daten."""
    # Acht Ecken, zwölf Dreiecke. Mehr braucht ein Träger nicht: Er wird nie gezeichnet,
    # er markiert nur den Ort, an dem der Effekt sitzt.
    ecken = [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
    flaechen = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),   # -x, +x
        (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),   # -y, +y
        (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),   # -z, +z
    ]
    ecken_roh = b"".join(struct.pack("<fff", *e) for e in ecken)
    index_roh = b"".join(struct.pack("<HHH", *f) for f in flaechen)
    # Der Indexblock muss an einer Vier-Byte-Grenze beginnen.
    fuell = (-len(ecken_roh)) % 4
    puffer = ecken_roh + b"\x00" * fuell + index_roh

    gltf = {
        "asset": {"version": "2.0", "generator": "FriesenBruegge rauch_bauen",
                  "copyright": "devprops"},
        "scene": 0,
        "scenes": [{"nodes": [0], "name": "Scene"}],
        "nodes": [{"mesh": 0, "name": knoten}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1,
                                    "material": 0, "mode": 4}]}],
        "materials": [{"name": "Invisible", "extensions": {"ASOBO_material_invisible": {}}}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(ecken), "type": "VEC3",
             "min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
            {"bufferView": 1, "componentType": 5123, "count": len(flaechen) * 3,
             "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(ecken_roh), "target": 34962},
            {"buffer": 0, "byteOffset": len(ecken_roh) + fuell,
             "byteLength": len(index_roh), "target": 34963},
        ],
        "buffers": [{"byteLength": len(puffer),
                     "uri": "data:application/octet-stream;base64,"
                            + base64.b64encode(puffer).decode("ascii")}],
    }
    return json.dumps(gltf, indent=1)


def behavior_xml(kennung: str, knoten: str, fx_guid: str) -> str:
    """Verknüpft den Modellknoten mit dem Partikeleffekt.

    Vorbild ist Emeralds `esd_smoke_fx_s.behavior.xml`. Dort steht zusätzlich eine Bedingung
    (`AMBIENT TEMPERATURE <= 10`), weshalb ihr Schornstein im Sommer gar nicht raucht — genau
    die Art stiller Fehler, die eine Station unsichtbar macht. Hier gibt es keine Bedingung:
    Eine Signalsäule brennt immer.
    """
    return f"""<ModelBehaviors>
	<Component ID="{kennung}">
		<UseTemplate Name="ASOBO_VFX_Base_Template">
			<FX_GUID>{fx_guid}</FX_GUID>
			<NODE_ID>{knoten}</NODE_ID>
		</UseTemplate>
	</Component>
</ModelBehaviors>
"""


# --------------------------------------------------------------------------- Paketteile

def material_schreiben() -> None:
    ziel = QUELLEN / "MaterialLibs" / "friesenrauch-mat"
    (ziel / "Textures").mkdir(parents=True, exist_ok=True)
    shutil.copy(ATLAS, ziel / "Textures" / "frs_rauch.png")
    # ⚠ NICHT LEER: Die .FLAGS sagt dem Paketwerkzeug, wie die Textur zu behandeln ist.
    # Ohne Inhalt bricht die TextureLib-Erzeugung mit "Failed to retrieve textures
    # informations" ab (13.09.2026 im Project Editor gesehen). Der Wert stammt aus dem
    # SDK-Beispiel SimpleFX, das denselben Zweck erfuellt.
    (ziel / "Textures" / "frs_rauch.png.FLAGS").write_text(
        "_DEFAULT=+PRECOMPUTEDINVAVG+QUALITYHIGH", encoding="utf-8")

    # Der Atlas ist derselbe wie in X-Plane: 4x4 Wolkenformen, weiss mit Alpha. Die Farbe
    # kommt aus dem Effekt (ParticleColor), nicht aus dem Material -- so tragen alle sechs
    # Farben dieselbe Textur.
    (ziel / "FrsRauch.material").write_text(
        f'<Material Version="1.4.0" Name="FrsRauch" Guid="{guid("material")}" '
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
    print(f"  Material + Atlas ({ATLAS.stat().st_size} Bytes)")


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
        (wurzel / modell / f"{kennung}.xml").write_text(
            "<ModelInfo>\n\t<LODS>\n"
            f'\t\t<LOD ModelFile="{kennung}.gltf"/>\n'
            "\t</LODS>\n\t<Behaviors>\n"
            f'\t\t<IncludeBase RelativeFile="{kennung}.behavior.xml"/>\n'
            "\t</Behaviors>\n</ModelInfo>\n", encoding="utf-8", newline="\r\n")
        (wurzel / modell / f"{kennung}.gltf").write_text(
            wuerfel_gltf(knoten), encoding="utf-8", newline="\n")
        (wurzel / modell / f"{kennung}.behavior.xml").write_text(
            behavior_xml(kennung, knoten, guid(name, "fx")), encoding="utf-8", newline="\r\n")

        teile += [f"[fltsim.{i}]", f"title={kennung}", f"model={name}", "texture=", ""]

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
        return (f'\t\t<AssetGroup Name="{name}">\n'
                f"\t\t\t<Type>{typ}</Type>\n"
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
          # ModularSimObject, nicht SimObject: Der Project Editor findet sonst nichts
          # ("Could not find a valid simobject"). So steht es in jedem SDK-Beispiel.
          gruppe("SimObjects", "ModularSimObject",
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
    print(r'  & "C:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe" FriesenRauch.xml')


if __name__ == "__main__":
    main()
