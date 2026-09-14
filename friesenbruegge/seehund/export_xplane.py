# -*- coding: utf-8 -*-
"""Den Seehund als X-Plane-OBJ8 schreiben.

    blender --background --python export_xplane.py

⚠ OBJ8 IST NICHT WAVEFRONT-OBJ. Gleiche Endung, anderes Format. Ein aus dem Netz
heruntergeladenes `.obj` ist fuer X-Plane unbrauchbar und umgekehrt. Der Aufbau steht in
`friesenbruegge/xplane/rauch_bauen.py` -- dort entsteht schon ein OBJ8, nur ohne Geometrie
(`POINT_COUNTS 0 0 0 0`). Hier kommt sie dazu:

    VT  x y z   nx ny nz   s t        je Ecke, Position + Normale + Textur
    IDX10 / IDX                       die Dreiecksindizes, zehn je Zeile
    TRIS  offset anzahl                zeichnen

⚠ ACHSEN: Blender ist Z-oben und Y-nach-hinten, X-Plane ist Y-oben und -Z-nach-vorn.
    x_xp = x_bl        y_xp = z_bl        z_xp = -y_bl
Wer das vergisst, bekommt ein Tier, das auf der Seite liegt und in den Boden schaut.

⚠ EINE TEXTUR JE OBJEKT -- deshalb die Palettentextur aus `textur.py`.
"""
import sys
from pathlib import Path

import bpy

ORDNER = Path(r"C:\Users\Tobias\AppData\Local\Temp\robben")
ZIEL = ORDNER / "export"
sys.path.insert(0, str(ORDNER))
import textur  # noqa: E402
import seehund_bauen as bauen  # noqa: E402


def obj8_schreiben(obj, pfad: Path, textur_datei: str) -> tuple[int, int]:
    netz = obj.data
    netz.calc_normals_split()
    uv = netz.uv_layers[0].data if netz.uv_layers else None

    # Je Schleife (Flaeche-Ecke) ein Eintrag -- so darf dieselbe Ecke in zwei Flaechen
    # verschiedene Normalen und UVs haben, und genau das braucht ein kantiges Modell.
    ecken: list[tuple] = []
    bekannt: dict[tuple, int] = {}
    dreiecke: list[int] = []

    netz.calc_loop_triangles()
    for tri in netz.loop_triangles:
        # X-Plane zeichnet gegen den Uhrzeigersinn von vorn -- Blender auch, aber durch
        # den Achsentausch (Y -> -Z) kippt die Orientierung, also die Reihenfolge drehen.
        for li in (tri.loops[0], tri.loops[2], tri.loops[1]):
            schleife = netz.loops[li]
            v = netz.vertices[schleife.vertex_index]
            p = obj.matrix_world @ v.co
            n = schleife.normal
            s, t = (uv[li].uv if uv else (0.5, 0.5))
            schluessel = (round(p.x, 5), round(p.y, 5), round(p.z, 5),
                          round(n.x, 4), round(n.y, 4), round(n.z, 4),
                          round(s, 5), round(t, 5))
            nr = bekannt.get(schluessel)
            if nr is None:
                nr = len(ecken)
                bekannt[schluessel] = nr
                # Achsentausch Blender -> X-Plane
                ecken.append((p.x, p.z, -p.y, n.x, n.z, -n.y, s, t))
            dreiecke.append(nr)

    zeilen = ["I", "800", "OBJ", "",
              f"TEXTURE {textur_datei}",
              f"POINT_COUNTS {len(ecken)} 0 0 {len(dreiecke)}", ""]
    for e in ecken:
        zeilen.append("VT\t" + "\t".join(f"{w:.6f}" for w in e))
    zeilen.append("")
    for i in range(0, len(dreiecke), 10):
        teil = dreiecke[i:i + 10]
        schluessel = "IDX10" if len(teil) == 10 else "IDX"
        for w in ([teil] if len(teil) == 10 else [[x] for x in teil]):
            zeilen.append(f"{schluessel}\t" + "\t".join(str(n) for n in w))
    zeilen += ["", f"TRIS\t0\t{len(dreiecke)}", ""]
    # ⚠ open() statt Path.write_text: Blender 3.0 bringt Python 3.9 mit, und dort kennt
    # write_text() das Argument `newline` noch nicht (erst ab 3.10). Ohne newline="\n"
    # schriebe Windows CRLF in eine Datei, die X-Plane mit LF erwartet.
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(zeilen))
    return len(ecken), len(dreiecke) // 3


def main() -> None:
    ZIEL.mkdir(exist_ok=True)
    # Nur die UV-Mitten -- die Bilddatei schreibt das System-Python, s. textur.uv_felder.
    uv_felder = textur.uv_felder(bauen.FARBEN)
    print(f"  {len(uv_felder)} Farbfelder: " +
          ", ".join(f"{n} -> {u:.3f}/{v:.3f}" for n, (u, v) in sorted(uv_felder.items())))

    for name, masse in bauen.GROESSEN.items():
        obj = bauen.main(ziel=masse, datei=f"seehund_{name}.blend")
        n = textur.uv_setzen(obj.data, uv_felder)
        ecken, tris = obj8_schreiben(obj, ZIEL / f"seehund_{name}.obj", "seehund.png")
        gross = (ZIEL / f"seehund_{name}.obj").stat().st_size
        print(f"  {name:8} {masse[1]:.2f} m   {ecken:4} Ecken, {tris:4} Dreiecke, "
              f"{n} UVs, {gross} Bytes")


main()
