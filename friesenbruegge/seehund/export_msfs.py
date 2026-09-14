# -*- coding: utf-8 -*-
"""Den Seehund als MSFS-SimObject in die FriesenBruegge-Paketquelle schreiben.

    blender --background --python export_msfs.py

WOHIN
Die Quelle liegt in `friesenbruegge/msfs-rauch/PackageSources/SimObjects/Misc/`. Dort
steht schon `FrsRauch/`; hier kommt `FrsSeehund/` daneben. Aus dieser Quelle macht
`fspackagetool` das Teilpaket, und `paket.ps1` verschmilzt alle Teile zu dem einen
Community-Ordner `friesenbruegge` -- ein Paket, ein Download.

⚠ `<LOD minSize="0" …>` IST HIER NOCH WICHTIGER ALS BEIM RAUCH.
MSFS blendet ein Modell aus, sobald seine Bildschirmgroesse unter `minSize` faellt, und die
Vorgabe ist groesser als 0. Eine Rauchsaeule ist 90 m hoch -- ein Seehund misst 1,6 m und
hat aus 200 ft rund 30 Pixel. Ohne die 0 waere er verschwunden, bevor man ihn zaehlen
kann. Vorbild ist Asobos eigenes Szenerie-Beispiel `kalo-projectedmesh-jetway_00.xml`
(Nutzerhinweis 14.09.2026).

⚠ KEIN `behavior.xml`. Das braucht nur der Rauch, weil dort ein Partikel-Emitter an einem
unsichtbaren Wuerfel haengt. Ein Tier ist schlicht Geometrie.

⚠ `category=StaticObject` IN DER sim.cfg, sonst erkennt der Package Builder den Ordner
nicht und meldet jede Datei als "Unlisted file" -- am 13.09.2026 beim Rauch durchgemacht.
"""
import shutil
import sys
from pathlib import Path

import bpy

ORDNER = Path(r"C:\Users\Tobias\AppData\Local\Temp\robben")
QUELLE = Path(r"D:\User\Tobias\OneDrive\Claude\FriesenSpy\friesenbruegge\msfs-rauch"
              r"\PackageSources\SimObjects\Misc\FrsSeehund")
sys.path.insert(0, str(ORDNER))
import textur  # noqa: E402
import seehund_bauen as bauen  # noqa: E402

TEXTUR = "FrsSeehund.PNG"


def schreib(pfad: Path, text: str, zeilenende: str = "\r\n") -> None:
    """Text schreiben, mit festem Zeilenende.

    ⚠ Eigene Funktion, weil Blender 3.0 PYTHON 3.9 mitbringt und `Path.write_text()` dort
    das Argument `newline` noch nicht kennt (erst ab 3.10). Zweimal darauf hereingefallen,
    im X-Plane- und im MSFS-Exporter -- jetzt gibt es nur noch diese eine Stelle.
    MSFS-Konfigurationsdateien wollen CRLF, glTF und OBJ8 wollen LF.
    """
    with open(pfad, "w", encoding="utf-8", newline=zeilenende) as f:
        f.write(text)


def gltf_exportieren(obj, ordner: Path, kennung: str) -> None:
    """Nur dieses eine Objekt, mit externer Textur und .bin daneben."""
    for o in bpy.context.scene.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=str(ordner / kennung),
        export_format="GLTF_SEPARATE",      # .gltf + .bin + Textur, wie MSFS es erwartet
        use_selection=True,
        export_apply=True,                  # Modifier anwenden
        export_yup=True,                    # glTF ist Y-oben, Blender Z-oben
        export_materials="EXPORT",
        export_texture_dir="",
        export_cameras=False,
        export_lights=False,
    )


def schreiben() -> None:
    QUELLE.mkdir(parents=True, exist_ok=True)
    uv = textur.uv_felder(bauen.FARBEN)

    teile = ["[VERSION]", "Major=1", "Minor=0", ""]
    for i, (name, masse) in enumerate(bauen.GROESSEN.items()):
        kennung = f"FrsSeehund_{name.capitalize()}"
        modell = QUELLE / f"model.{name}"
        modell.mkdir(exist_ok=True)

        obj = bauen.main(ziel=masse, datei=f"seehund_{name}.blend")
        obj.name = obj.data.name = kennung
        textur.uv_setzen(obj.data, uv)

        # Ein Material fuer alle Flaechen, das auf die Palettentextur zeigt -- die drei
        # Farben stehen ja schon darin, und X-Plane wie MSFS bekommen dieselbe Datei.
        mat = bpy.data.materials.new(kennung)
        mat.use_nodes = True
        baum = mat.node_tree
        bsdf = next(n for n in baum.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Roughness"].default_value = 0.42
        if "Specular" in bsdf.inputs:
            bsdf.inputs["Specular"].default_value = 0.35
        bild = baum.nodes.new("ShaderNodeTexImage")
        bild.image = bpy.data.images.load(str(ORDNER / "export" / "seehund.png"))
        bild.interpolation = "Closest"       # ⚠ harte Felder, kein Verwischen der Palette
        baum.links.new(bild.outputs["Color"], bsdf.inputs["Base Color"])
        obj.data.materials.clear()
        obj.data.materials.append(mat)

        gltf_exportieren(obj, modell, kennung)

        # ⚠ DIE TEXTUR GEHOERT IN `texture/`, NICHT IN DEN MODELLORDNER.
        # Blender legt sie neben das glTF; MSFS sucht sie im Geschwisterordner `texture`
        # (so sagt es die leere Zeile `texture=` in der sim.cfg). Beim ersten Bau lag sie
        # falsch: Der Package Builder hat sie NICHT eingesammelt, das kompilierte glTF
        # verwies trotzdem auf `SEEHUND.PNG.KTX2`, und diese Datei gab es nicht -- ohne
        # eine einzige Fehlermeldung. Im Simulator waere ein farbloser Seehund erschienen.
        lose = modell / "seehund.png"
        if lose.exists():
            (QUELLE / "texture").mkdir(exist_ok=True)
            shutil.move(str(lose), str(QUELLE / "texture" / "seehund.png"))
            # ⚠ UND OHNE BEGLEITDATEI SIEHT DER BUILDER SIE NICHT ALS TEXTUR.
            # Zweiter Fehlversuch: Die PNG lag jetzt richtig im texture-Ordner und wurde
            # trotzdem nicht eingesammelt. Im SDK-Beispiel `Misc/TrafficVehicles` hat JEDE
            # Textur eine `.png.xml` daneben, die ihren Steckplatz nennt --
            # `MTL_BITMAP_DECAL0` ist der Albedo-Kanal, also die Farbe.
            schreib(QUELLE / "texture" / "seehund.png.xml",
                    "<BitmapConfiguration>\n"
                    "\t<BitmapSlot>MTL_BITMAP_DECAL0</BitmapSlot>\n"
                    "</BitmapConfiguration>\n")

        schreib(modell / "model.CFG", f"[models]\nnormal={kennung}.xml\n")
        schreib(modell / f"{kennung}.xml",
                "<ModelInfo>\n\t<LODS>\n"
                f'\t\t<LOD minSize="0" ModelFile="{kennung}.gltf"/>\n'
                "\t</LODS>\n</ModelInfo>\n")

        teile += [f"[fltsim.{i}]", f"title={kennung}", f"model={name}", "texture=", ""]
        dateien = sorted(p.name for p in modell.iterdir())
        print(f"  {kennung:22} {masse[1]:.2f} m   {', '.join(dateien)}")

    # ⚠ `DistanceToNotAnimate` -- gefunden am 14.09.2026 am Rauch, uebernommen.
    # Das Vorbild liegt auf demselben Rechner und fuer denselben Flugplatz: Aerosofts
    # Wangerooge-Paket setzt in JEDEM SimObject `DistanceToNotAnimate=2000`, auch bei den
    # Windsaecken und der Objektbibliothek. Unsere sim.cfg hatte nur `category`.
    #
    # ⚠ ABER DER MECHANISMUS IST BEIM SEEHUND UNGEPRUEFT, und das gehoert dazugesagt: Am
    # Rauch ging es um einen Partikel-EMITTER, der ohne Animation nicht laeuft. Ein
    # Seehund ist starre Geometrie -- es gibt daran nichts zu animieren. Ob der Wert hier
    # ueberhaupt etwas bewirkt, zeigt erst der Simulator.
    #
    # 2000 m, nicht 15000 wie beim Rauch: Eine Rauchsaeule ist eine Baake und soll von
    # weitem zum Hinfliegen einladen. Eine Robbe wird GEZAEHLT, nicht gesucht -- aus 200 ft
    # sieht man ohnehin keine 15 km weit, und was nichts bringt, soll auch nichts kosten.
    teile += ["[General]", "category=StaticObject", "DistanceToNotAnimate=2000", ""]
    schreib(QUELLE / "sim.cfg", "\n".join(teile))
    print(f"  sim.cfg mit {len(bauen.GROESSEN)} Eintraegen, category=StaticObject")


schreiben()
