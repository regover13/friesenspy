# -*- coding: utf-8 -*-
"""Das Modell von allen Seiten -- eine vollstaendige Ansicht.

    blender --background --python rundum.py

⚠ Fuer ALLE Ansichten dieselbe `ortho_scale`, damit die Groessenverhaeltnisse zwischen den
Bildern stimmen. Wird sie je Ansicht aus der sichtbaren Ausdehnung berechnet, erscheint das
Tier von vorn genauso gross wie von der Seite -- und das taeuscht.
"""
import math
from pathlib import Path

import bpy

ORDNER = Path(r"C:\Users\Tobias\AppData\Local\Temp\robben")
KANTE = 520

bpy.ops.wm.open_mainfile(filepath=str(ORDNER / "seehund.blend"))
obj = bpy.data.objects["Seehund"]
ecken = [obj.matrix_world @ v.co for v in obj.data.vertices]
grenzen = [(min(e[i] for e in ecken), max(e[i] for e in ecken)) for i in range(3)]
spannen = [b - a for a, b in grenzen]
mitte = [(a + b) / 2 for a, b in grenzen]
AUSSCHNITT = max(spannen) * 1.22

# Sandboden -- er gehoert zur Beurteilung, weil der Schatten die Silhouette mittraegt.
bpy.ops.mesh.primitive_plane_add(size=24, location=(mitte[0], mitte[1], 0))
boden = bpy.context.active_object
mat = bpy.data.materials.new("Sand")
mat.use_nodes = True
for n in mat.node_tree.nodes:
    if n.type == "BSDF_PRINCIPLED":
        n.inputs["Base Color"].default_value = (0.55, 0.47, 0.35, 1)
        n.inputs["Roughness"].default_value = 0.96
bpy.context.active_object.data.materials.append(mat)

sd = bpy.data.lights.new("Sonne", type="SUN")
sd.energy = 1.5
sd.angle = math.radians(2.0)
sonne = bpy.data.objects.new("Sonne", sd)
sonne.rotation_euler = (math.radians(44), 0, math.radians(148))
bpy.context.scene.collection.objects.link(sonne)

welt = bpy.data.worlds.new("Welt")
welt.use_nodes = True
welt.node_tree.nodes["Background"].inputs[0].default_value = (0.42, 0.55, 0.72, 1)
welt.node_tree.nodes["Background"].inputs[1].default_value = 0.28
bpy.context.scene.world = welt

s = bpy.context.scene
s.render.engine = "CYCLES"
s.cycles.samples = 84
s.cycles.use_denoising = True
s.render.resolution_x = s.render.resolution_y = KANTE
s.render.image_settings.file_format = "PNG"

ziel = bpy.data.objects.new("Ziel", None)
ziel.location = mitte
bpy.context.scene.collection.objects.link(ziel)

w = max(spannen) * 3 + 2
ANSICHTEN = {
    "r_oben":      (mitte[0], mitte[1], mitte[2] + w),
    "r_unten":     (mitte[0], mitte[1], mitte[2] - w),
    "r_links":     (mitte[0] - w, mitte[1], mitte[2]),
    "r_rechts":    (mitte[0] + w, mitte[1], mitte[2]),
    "r_vorn":      (mitte[0], mitte[1] - w, mitte[2]),
    "r_hinten":    (mitte[0], mitte[1] + w, mitte[2]),
    "r_schraeg1":  (mitte[0] + w * 0.55, mitte[1] - w * 0.62, mitte[2] + w * 0.42),
    "r_schraeg2":  (mitte[0] - w * 0.55, mitte[1] + w * 0.62, mitte[2] + w * 0.42),
}

for name, ort in ANSICHTEN.items():
    kd = bpy.data.cameras.new(name)
    kd.type = "ORTHO"
    kd.ortho_scale = AUSSCHNITT
    kd.clip_start = 0.01
    kd.clip_end = w * 5
    kam = bpy.data.objects.new(name, kd)
    bpy.context.scene.collection.objects.link(kam)
    kam.location = ort
    folge = kam.constraints.new("TRACK_TO")
    folge.target = ziel
    folge.track_axis = "TRACK_NEGATIVE_Z"
    folge.up_axis = "UP_Y"
    bpy.context.scene.camera = kam
    # Von unten steht der Sandboden im Weg -- fuer diese eine Ansicht ausblenden.
    boden.hide_render = (name == "r_unten")
    s.render.filepath = str(ORDNER / f"{name}.png")
    bpy.ops.render.render(write_still=True)

print(f"\nMASSE  Laenge {spannen[1]:.2f} m   Breite {spannen[0]:.2f} m   "
      f"Hoehe {spannen[2]:.2f} m   {len(obj.data.polygons)} Flaechen")
