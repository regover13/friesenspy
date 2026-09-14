# -*- coding: utf-8 -*-
"""Aus dem freien Walross-Modell einen Seehund machen.

    "D:\\Program Files\\Blender Foundation\\Blender 3.0\\blender.exe" --background ^
        --python seehund_bauen.py

HERKUNFT UND LIZENZ
Grundlage ist "Walrus" von **Poly by Google**, aus dem Nachlass des 2021 abgeschalteten
Dienstes, archiviert auf poly.pizza/m/5T7nIjx9ekP. Lizenz **CC BY 3.0** -- Aenderung und
Weitergabe sind ausdruecklich erlaubt, Bedingung ist allein die Namensnennung. Die gehoert
damit in jedes Paketmanifest und auf die Downloadseite.

WARUM AUSGERECHNET EIN WALROSS
Vier freie Modelle standen zur Wahl (14.09.2026, alle CC BY). Zwei davon -- beide
"Sea lion" genannt -- SITZEN AUFRECHT wie im Zoo; von oben sieht man einen Ruecken mit
hochgerecktem Kopf. Die beiden "Walrus" liegen ausgestreckt auf dem Bauch, Flossen
seitlich, und genau so liegt ein Seehund auf der Sandbank. Die Pose entscheidet, nicht der
Dateiname.

WAS HIER GEAENDERT WIRD
1. Die Stosszaehne (Material `white`, 224 Flaechen) fallen weg -- ein Seehund hat keine.
2. Die Farben gehen vom Walross-Braun auf Seehund-Graubraun. Das ist nicht Kosmetik: Auf
   hellem Trockensand -- also dort, wo Robben liegen -- verschwand das helle Walross fast,
   und der Kontrast entscheidet aus 200 ft mehr als die Polygonzahl.
3. Die Proportionen werden auf einen Seehund gezogen, s. unten.

⚠ DIE ROHMASSE SIND WILLKUERLICH. Das Modell misst 972 Einheiten in der Laengsachse --
Poly-Modelle tragen keine verlaessliche Massstabsangabe. Wer die Skalierung weglaesst,
bekommt einen 972 m langen Seehund; genau daran ist das erste Rendering gescheitert
(Blenders Kamera schnitt bei 100 Einheiten ab, ohne eine Meldung).

⚠ UND GLEICHMAESSIG SKALIEREN REICHT NICHT. Auf 1,70 m Laenge gebracht war das Tier
1,52 m breit und 1,20 m hoch -- ein Wuerfel mit Flossen. Das Modell ist ein stilisiertes,
gedrungenes Walross; ein Seehund ist schlank. Gemessen an Phoca vitulina:

    Laenge   1,4-1,9 m   ->  1,70 m
    Breite     ~0,40 m Koerper, mit abgespreizten Vorderflossen ~0,60 m
    Hoehe   liegend ~0,30 m, mit erhobenem Kopf bis ~0,50 m

Deshalb je Achse ein eigener Faktor. Aus der Naehe sieht ein so gestauchtes Tier flacher
aus als das Original -- das ist gewollt, denn ein Seehund IST flach.
"""
import sys
from pathlib import Path

import bmesh
import bpy

ORDNER = Path(r"C:\Users\Tobias\AppData\Local\Temp\robben")
QUELLE = ORDNER / "walross_b.glb"

sys.path.insert(0, str(ORDNER))
import form  # noqa: E402  -- die Formkorrekturen; wer an der Form dreht, dreht dort

# ⭐ DREI GROESSEN, EIN MODELL. Eine Liegegruppe im Wattenmeer besteht aus Bullen, Kuehen
# und Heulern; zwanzig exakt gleich grosse Tiere nebeneinander sehen von oben nach Tapete
# aus. Die Zahlen sind belegt, nicht geschaetzt:
#
#   Seehundstation Norddeich    Weibchen 1,60 m / bis 100 kg, Maennchen 1,80 m / bis 120 kg
#   Deutscher Jagdverband       Koerperlaenge 1,20-1,80 m; Heuler 80-90 cm, 7-10 kg
#
# Breite und Hoehe wachsen NICHT linear mit: Ein Heuler ist gedrungener als ein Bulle.
# Deshalb je Groesse ein eigener Satz, statt einmal zu skalieren.
GROESSEN = {
    # Name         (X quer, Y laengs, Z hoch) in Metern
    "bulle":       (0.66, 1.80, 0.46),
    "kuh":         (0.58, 1.60, 0.42),
    "heuler":      (0.34, 0.85, 0.25),
}
ZIEL = GROESSEN["kuh"]          # die Vorgabe, wenn niemand etwas anderes sagt
WEG = {"white"}         # die Stosszaehne

# Seehundfarben, LINEAR (Blender rechnet linear, nicht sRGB). Ein nasser Seehund ist
# dunkler, als man denkt -- und dunkel ist hier erwuenscht, s. Kontrast oben.
FARBEN = {
    "brown":      (0.115, 0.108, 0.098, 1.0),   # Ruecken, graubraun
    "lightbrown": (0.165, 0.155, 0.140, 1.0),   # Schnauze und Bauchseite, etwas heller
    "black":      (0.020, 0.018, 0.016, 1.0),   # Augen, Nase
}


def material_farbe(m, rgba):
    m.use_nodes = True
    m.diffuse_color = rgba                      # auch fuers Viewport und fuer Exporte,
    for n in m.node_tree.nodes:                 # die den Node-Baum nicht lesen
        if n.type == "BSDF_PRINCIPLED":
            n.inputs["Base Color"].default_value = rgba
            n.inputs["Roughness"].default_value = 0.42      # feucht, nicht spiegelnd
            if "Specular" in n.inputs:
                n.inputs["Specular"].default_value = 0.35


def masse(obj):
    ecken = [obj.matrix_world @ v.co for v in obj.data.vertices]
    return [(min(e[i] for e in ecken), max(e[i] for e in ecken)) for i in range(3)]


def main(ziel=None, datei="seehund.blend"):
    global ZIEL
    if ziel is not None:
        ZIEL = ziel
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(QUELLE))
    netze = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert len(netze) == 1, f"erwartet ein Netz, gefunden {len(netze)}"
    obj = netze[0]
    obj.name = obj.data.name = "Seehund"

    vorher = len(obj.data.polygons)

    # --- 1. Stosszaehne weg ------------------------------------------------------------
    weg_nummern = {i for i, m in enumerate(obj.data.materials) if m and m.name in WEG}
    assert weg_nummern, f"Material {WEG} nicht gefunden"
    netz = bmesh.new()
    netz.from_mesh(obj.data)
    netz.faces.ensure_lookup_table()

    # ⚠ WELCHE RAENDER VORHER SCHON OFFEN WAREN, MUSS MAN WISSEN, BEVOR MAN LOESCHT.
    # Das Rohmodell hat 776 offene Kanten -- es ist aus getrennten Teilen gebaut. Wer
    # hinterher stumpf alle Loecher fuellt, verschliesst auch die, die dazugehoeren
    # (etwa die Unterseite der Flossen), und bekommt Flaechen quer durch das Tier.
    vorher_offen = {k.index for k in netz.edges if len(k.link_faces) < 2}

    bmesh.ops.delete(netz, geom=[f for f in netz.faces
                                 if f.material_index in weg_nummern], context="FACES")
    bmesh.ops.delete(netz, geom=[v for v in netz.verts if not v.link_faces], context="VERTS")
    netz.edges.ensure_lookup_table()
    print(f"  Stosszaehne weg: {vorher} -> {len(netz.faces)} Flaechen")

    # Die Loecher schliessen, die DURCH DAS LOESCHEN entstanden sind. Sichtbar war das als
    # kantiger Auswuchs unter dem Kopf (Nutzer, 14.09.2026): Man sah von schraeg unten in
    # die Oberlippe hinein, und die Innenseite der Rueckwand wirkte wie ein Fortsatz.
    neu_offen = [k for k in netz.edges
                 if len(k.link_faces) < 2 and k.index not in vorher_offen]
    if neu_offen:
        bmesh.ops.holes_fill(netz, edges=neu_offen, sides=0)
        bmesh.ops.recalc_face_normals(netz, faces=netz.faces[:])
        print(f"  Zahnloecher geschlossen: {len(neu_offen)} offene Kanten "
              f"-> {len(netz.faces)} Flaechen")

    netz.to_mesh(obj.data)
    netz.free()

    # Den leeren Materialplatz mitnehmen, damit er nicht in den Export wandert
    for i in sorted(weg_nummern, reverse=True):
        obj.data.materials.pop(index=i)

    # --- 2. Farben ---------------------------------------------------------------------
    for m in obj.data.materials:
        if m and m.name in FARBEN:
            material_farbe(m, FARBEN[m.name])

    # --- 3. Auf Seehundmasse ziehen ----------------------------------------------------
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    grenzen = masse(obj)
    spannen = [b - a for a, b in grenzen]
    faktoren = tuple(ZIEL[i] / spannen[i] for i in range(3))
    obj.scale = faktoren
    print("  Faktoren: " + "  ".join(f"{'XYZ'[i]} {faktoren[i]:.5f}" for i in range(3)))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Augen, Nase und Wuelste von der ungleichen Skalierung befreien -- s. form.entzerren.
    teile, schlimmste = form.entzerren(obj.data, faktoren)
    print(f"  Entzerrt: {teile} kleine Teile (schlimmstes Verhaeltnis war "
          f"{schlimmste:.1f} : 1)")

    # --- 3b. Aus dem Walross einen Seehund formen --------------------------------------
    # Erst JETZT, weil die Grenzen in `form.py` in Metern stehen und damit lesbar sind.
    gekuerzt, neue_laenge = form.kopf_kuerzen(obj.data)
    print(f"  Kopf gekuerzt: {gekuerzt * 100:.1f} cm -> Laenge {neue_laenge:.3f} m")

    grenzen = masse(obj)
    starr, starre_ecken = form.anpassen(obj.data, boden_z=grenzen[2][0])
    print(f"  Starr mitbewegt: {starr} Teile ({starre_ecken} Ecken) -- Augen, Nase, Wuelste")

    ecken, geschrumpft = form.wuelste_einziehen(obj.data)
    print(f"  Lippenwuelste eingezogen: {ecken} Ecken, "
          f"{geschrumpft * 100:.0f} % schmaler")

    ecken, gross = form.nase_kleiner(obj.data)
    print(f"  Nase verkleinert: {ecken} Ecken -> {gross:.3f} m")

    # ⚠ DAS FUELLEN DER KERBE VERLAENGERT DAS TIER -- es schiebt Ecken in +Y. Gemessen:
    # 1,70 m gingen auf 1,78 m. Also die Laengsachse danach zurueckholen; Breite und Hoehe
    # bleiben, die hat die Formkorrektur ja absichtlich veraendert.
    grenzen = masse(obj)
    laengs = grenzen[1][1] - grenzen[1][0]
    if abs(laengs - ZIEL[1]) > 0.001:
        obj.scale = (1.0, ZIEL[1] / laengs, 1.0)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        print(f"  Laenge nach dem Formen zurueckgeholt: {laengs:.3f} -> {ZIEL[1]:.2f} m")

    grenzen = masse(obj)
    print(f"  Form angelegt: Backen schmaler, Schwanzflosse zusammen "
          f"-> Breite {grenzen[0][1] - grenzen[0][0]:.2f} m")

    # --- 4. Ursprung mittig und auf den Bauch ------------------------------------------
    # Beide Simulatoren setzen ein Objekt an seinem Ursprung ab; ein Tier, das zur Haelfte
    # im Sand steckt, faellt auf.
    grenzen = masse(obj)
    obj.location = (-(grenzen[0][0] + grenzen[0][1]) / 2,
                    -(grenzen[1][0] + grenzen[1][1]) / 2,
                    -grenzen[2][0])
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    # --- 5. Glatt schattieren, aber Kanten behalten -----------------------------------
    bpy.ops.object.shade_smooth()
    obj.data.use_auto_smooth = True
    obj.data.auto_smooth_angle = 0.61           # 35 Grad

    grenzen = masse(obj)
    print("  ENDMASSE")
    for name, i in (("Laenge (Y)", 1), ("Breite (X)", 0), ("Hoehe  (Z)", 2)):
        print(f"    {name}: {grenzen[i][1] - grenzen[i][0]:5.2f} m")
    print(f"    Flaechen: {len(obj.data.polygons)}")

    bpy.ops.wm.save_as_mainfile(filepath=str(ORDNER / datei))
    print(f"  gespeichert: {ORDNER / datei}")
    return obj


main()
