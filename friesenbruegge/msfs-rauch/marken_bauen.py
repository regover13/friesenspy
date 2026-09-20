"""Die Markierungen der FriesenBrügge für MSFS 2020 UND 2024: Würfel, Lichtsäulen, ein Punktlicht.

Teil drei von `paket_bauen.py` (neben Rauch und Seehund). Entstanden am 20.09.2026 aus dem
Nachttest in MSFS 2024, bei dem der Nutzer die offiziellen Streaming-Titel nebeneinander sah:

    Peace_Tower_Light                 eine sehr helle weiße Säule            -- „gut", auch tagsüber
    wENLK_lightdummy                  zwei kleine rote Würfel                -- „gut für tagsüber"
    (zwei warme Lichtpunkte auf der Wiese, von keinem unserer Objekte)       -- „ein einfaches Licht"

Alle drei gibt es in MSFS 2020 nicht (`EXCEPTION_22`), und der Nutzer will überall Vergleichbares
(„ich brauche auch immer Vergleichbares in den anderen beiden Sims"). Deshalb eigene Modelle, die
in BEIDEN MSFS-Fassungen aus derselben Quelle laufen — wie der Rauch und der Seehund.

Was entsteht (alles unter `PackageSources/SimObjects/Misc/FrsMarke/`)
=====================================================================

    FrsWuerfel_<Farbe>   6 Stück   Würfel, 3 m Kante, in den Friesenfarben (`rauch_bauen.FARBEN`)
    FrsSaeule_<Farbe>    7 Stück   schmale Lichtsäule, 100 m hoch, 0,8 m breit: die sechs
                                   Friesenfarben und Weiß
    FrsLicht_Warm        1 Stück   Punktlicht, nachts warmweiß, wie die Lichter im Nachtbild

KEINE TEXTUREN — und das ist Absicht
------------------------------------
Die Modelle tragen nur `baseColorFactor` und `emissiveFactor`. Damit gibt es weder eine `.KTX2`
(2024-Toolchain, MSFS 2020 liest sie nicht: rosa Seehunde am 20.09.2026) noch eine `.DDS`
(2020-Toolchain) und keine `.png.xml` daneben, die man vergessen könnte (`paket_bauen.py`,
Kopfkommentar, zwei stille Fallen). Eine Farbfläche braucht keine.

DAS PUNKTLICHT — WAS BELEGT IST, UND WORAUF ES SICH STÜTZT
----------------------------------------------------------
Die SDK-Doku nennt `ASOBO_macro_light` nur als Name (`Documentation/html/Asset_Creation/
3DS_Max_Plugin`), beschrieben ist allein das Schema (`Schemas/ASOBO_macro_light/
gltf.ASOBO_macro_light.schema.json`): color[3], intensity, cone_angle, has_simmetry,
flash_frequency, flash_duration, flash_phase, rotation_speed, day_night_cycle.

Wie ein solcher Knoten AUSSIEHT, steht in Asobos eigenen, kompilierten Modellen auf der Platte
(MSFS 2020, `Official/OneStore/asobo-simobjects-vehicles/SimObjects/GroundVehicles/…`,
137 `*LOD00.gltf` ausgezählt am 20.09.2026):

  * Ein Licht ist ein **Knoten OHNE Mesh**, dessen `extensions` den Eintrag `ASOBO_macro_light`
    tragen; er hängt unter einem Wurzelknoten (bei der Seilwinde `ESW_2B`: Knoten `Light` mit
    den Kindern `Point`, `Point.001`, `Spot`, `Spot.001`). Name, Position und Drehung sind
    ganz gewöhnliche Knotenfelder.
  * Das **Punktlicht** heißt bei Asobo `Point.NNN` und hat **`cone_angle: 360`** (16 von 256
    Lichtern; Spots haben 60–130), **`day_night_cycle: true`** (dann brennt es nur nachts;
    42 von 252), `intensity` meist 1 (Winden) bis 5 (Scheinwerfer), `flash_*` und
    `rotation_speed` 0, `has_simmetry: false`. Die Farbe ist RGB 0–1.
  * `extensionsUsed` führt `ASOBO_macro_light`. `extensionsRequired` enthält es NICHT (dort steht
    nur `MSFT_texture_dds`).
  * Das Modell-XML braucht **nichts** — bei der Winde steht dort nur `<LODS>`; kein
    `<Behaviors>`, kein FX. Bei `day_night_cycle: true` schaltet der Simulator selbst.

  ⚠ NICHT BELEGT: Ein Modell aus NUR einem Lichtknoten (ohne Mesh) ist bei Asobo nirgends
  gefunden worden — jedes Modell trägt auch Geometrie. Deshalb trägt `FrsLicht_Warm` ein
  winziges unsichtbares Trägermesh (`ASOBO_material_invisible`, wie der Rauch). Ebenso NICHT
  belegt: welche `intensity` dem Nachtbild entspricht. Die 5,0 hier sind der häufigste Wert der
  Scheinwerfer und eine ANNAHME; sie ist der Regler für den Flugtest.

DIE SÄULE
---------
`alphaMode: BLEND`, `doubleSided`, kräftig emissiv. Ein Achteck ohne Deckel, weil ein Lichtstrahl
keinen hat. Ob MSFS ein `BLEND`-Material mit `emissiveFactor` nachts leuchten lässt wie
`Peace_Tower_Light`, ist UNGEMESSEN (s. Bericht am Ende von `paket_bauen.py`/Commit) — die
Alternative wäre `ASOBO_material_day_night_switch`.

Eine unsichtbare Falle vom Rauch gilt auch hier: MSFS blendet ein Modell aus, dessen
Bildschirmgröße unter `minSize` fällt — beim Rauch half `minSize="0"` NICHT, erst ein 90 m hoher
Träger. Die Säule ist 100 m hoch (also unkritisch); der 3-m-Würfel verschwindet aus der Ferne
womöglich trotzdem. Das ist gewollt hinzunehmen: Er ist ein Nahmarker.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from rauch_bauen import FARBEN

#: Kante des Würfels in Metern (Nutzer, 20.09.2026: „Würfel ca. 3 m").
WUERFEL_KANTE = 3.0
#: Höhe der Säule in Metern und Breite über die Ecken des Achtecks (Nutzer: „ca. 100 m hoch und
#: schmal").
SAEULE_HOEHE = 100.0
SAEULE_BREITE = 0.8
SAEULE_ECKEN = 8
#: Wie stark der Würfel von selbst leuchtet, damit er nachts nicht schwarz ist (Anteil der Farbe).
WUERFEL_EIGENLICHT = 0.35
#: Sichtbarkeit der Säule: Alpha der Grundfarbe.
SAEULE_ALPHA = 0.55

#: Das Punktlicht: warmweiß wie die Lichter im Nachtbild, Rundumstrahler, nur nachts.
LICHT_FARBE = (1.0, 0.84, 0.6)
LICHT_STAERKE = 5.0          # ANNAHME (häufigster Scheinwerferwert bei Asobo) — der Regler für den Flugtest
LICHT_KEGEL = 360            # Rundumstrahler, wie `Point.NNN` bei Asobo
LICHT_HOEHE = 0.3            # Meter über dem Boden

HERSTELLER_ORDNER = "FrsMarke"

#: Alle Säulenfarben: die Friesenfarben und Weiß.
SAEULEN_FARBEN = {**FARBEN, "weiss": (0xFF, 0xFF, 0xFF)}


def titel_wuerfel(name: str) -> str:
    return f"FrsWuerfel_{name.capitalize()}"


def titel_saeule(name: str) -> str:
    return f"FrsSaeule_{name.capitalize()}"


TITEL_LICHT = "FrsLicht_Warm"


def alle_titel() -> list[str]:
    """Die Titel in der Reihenfolge der sim.cfg: erst Würfel, dann Säulen, dann das Licht."""
    return ([titel_wuerfel(n) for n in FARBEN] + [titel_saeule(n) for n in SAEULEN_FARBEN]
            + [TITEL_LICHT])


# --------------------------------------------------------------------------- Farben

def _linear(kanal_0_255: int) -> float:
    """sRGB (0–255) nach linear (0–1). glTF rechnet Faktoren linear, Hex-Farben sind sRGB."""
    c = kanal_0_255 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def farbe_linear(rgb: tuple[int, int, int]) -> list[float]:
    return [round(_linear(k), 6) for k in rgb]


# --------------------------------------------------------------------------- Geometrie

def wuerfel_flaechen(kante: float) -> list:
    """Sechs Flächen `(normale, [vier Ecken])`, Ursprung Mitte der Unterseite (y = 0 … kante).

    Vierundzwanzig Ecken, nicht acht: Der glTF-Compiler des SDK rechnet Normalen nicht selbst aus
    (`paket_bauen.wuerfel_gltf`), und eine Würfelecke gehört zu drei Flächen.
    """
    h, b = kante, kante / 2.0
    return [
        ((0.0, 0.0, -1.0), [(-b, 0, -b), (-b, h, -b), (b, h, -b), (b, 0, -b)]),
        ((0.0, 0.0, 1.0), [(b, 0, b), (b, h, b), (-b, h, b), (-b, 0, b)]),
        ((0.0, -1.0, 0.0), [(-b, 0, -b), (b, 0, -b), (b, 0, b), (-b, 0, b)]),
        ((0.0, 1.0, 0.0), [(-b, h, b), (b, h, b), (b, h, -b), (-b, h, -b)]),
        ((-1.0, 0.0, 0.0), [(-b, 0, b), (-b, h, b), (-b, h, -b), (-b, 0, -b)]),
        ((1.0, 0.0, 0.0), [(b, 0, -b), (b, h, -b), (b, h, b), (b, 0, b)]),
    ]


def prisma_flaechen(ecken: int, breite: float, hoehe: float) -> list:
    """Ein regelmäßiges n-Eck als Mantel ohne Deckel, Ursprung Mitte der Unterseite.

    `breite` ist der Abstand zweier gegenüberliegender ECKEN (Umkreisdurchmesser). Jede Seite
    hat ihre eigenen vier Ecken und ihre eigene Normale (flache Schattierung, wie beim Würfel).
    Die Vierecke laufen gegen den Uhrzeigersinn von außen gesehen; die Säule ist ohnehin
    `doubleSided`.
    """
    r = breite / 2.0
    winkel = [2.0 * math.pi * k / ecken for k in range(ecken)]
    punkte = [(r * math.cos(w), r * math.sin(w)) for w in winkel]
    raus = []
    for k in range(ecken):
        (x0, z0), (x1, z1) = punkte[k], punkte[(k + 1) % ecken]
        mitte = (winkel[k] + winkel[(k + 1) % ecken]) / 2.0
        if (k + 1) % ecken == 0:            # letzte Seite: der Winkel läuft über 2π hinaus
            mitte = (winkel[k] + 2.0 * math.pi) / 2.0
        normale = (round(math.cos(mitte), 6), 0.0, round(math.sin(mitte), 6))
        raus.append((normale, [(x0, 0.0, z0), (x0, hoehe, z0), (x1, hoehe, z1), (x1, 0.0, z1)]))
    return raus


# --------------------------------------------------------------------------- glTF

def _gltf(knoten: str, bin_datei: str, flaechen: list, material: dict, *,
          licht: dict | None = None, lichtposition: tuple | None = None) -> tuple[str, bytes]:
    """Baut das glTF: ein Mesh-Knoten, optional dazu ein Lichtknoten. Gibt (JSON, Rohpuffer).

    Die Zahlen liegen in einer ECHTEN `.bin` daneben, nicht als Base64 (der MSFS-Modellcompiler
    schreibt ein `data:`-URI still auf eine externe Datei um, ohne sie zu erzeugen —
    `paket_bauen.wuerfel_gltf`).

    Zu jeder Ecke gehört ein `TEXCOORD_0` (0, 0): Ein Material ohne Textur braucht keine
    Koordinaten, aber die Shader des Simulators lesen sie, und ein Mesh ohne sie ist der eine
    Unterschied zu Asobos Modellen, den wir uns sparen können. (Ungemessen, ob es nötig ist.)
    """
    ecken_roh = b""
    normal_roh = b""
    uv_roh = b""
    indizes: list[int] = []
    unten = [1e9, 1e9, 1e9]
    oben = [-1e9, -1e9, -1e9]
    for i, (normale, ecken) in enumerate(flaechen):
        for e in ecken:
            ecken_roh += struct.pack("<fff", *(float(v) for v in e))
            normal_roh += struct.pack("<fff", *(float(v) for v in normale))
            uv_roh += struct.pack("<ff", 0.0, 0.0)
            for a in range(3):
                unten[a] = min(unten[a], float(e[a]))
                oben[a] = max(oben[a], float(e[a]))
        b = i * 4
        indizes += [b, b + 1, b + 2, b, b + 2, b + 3]

    anzahl = 4 * len(flaechen)
    index_roh = b"".join(struct.pack("<H", i) for i in indizes)
    fuell = (-(len(ecken_roh) + len(normal_roh) + len(uv_roh))) % 4
    puffer = ecken_roh + normal_roh + uv_roh + b"\x00" * fuell + index_roh

    knoten_liste = [{"mesh": 0, "name": knoten}]
    verwendet = ["ASOBO_normal_map_convention"]
    if "ASOBO_material_invisible" in material.get("extensions", {}):
        verwendet.append("ASOBO_material_invisible")
    if licht is not None:
        # Wie bei Asobos Seilwinde: ein Knoten `Light` ohne Mesh, darunter das Licht als `Point`.
        knoten_liste += [
            {"name": "Light", "children": [2]},
            {"name": "Point", "translation": list(lichtposition or (0.0, 0.0, 0.0)),
             "extensions": {"ASOBO_macro_light": licht}},
        ]
        verwendet.append("ASOBO_macro_light")
    wurzeln = [0] if licht is None else [0, 1]

    gltf = {
        "asset": {"version": "2.0", "generator": "FriesenBruegge marken_bauen",
                  "copyright": "devprops",
                  "extensions": {"ASOBO_normal_map_convention": {"tangent_space_convention": "DirectX"}}},
        "extensionsUsed": verwendet,
        "scene": 0,
        "scenes": [{"nodes": wurzeln, "name": "Scene"}],
        "nodes": knoten_liste,
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                                    "indices": 3, "material": 0, "mode": 4}]}],
        "materials": [material],
        "accessors": [
            # Die Bounding Box MUSS zur Geometrie passen — der Simulator liest sie für die
            # Größenprüfung, nicht die Eckpunkte.
            {"bufferView": 0, "componentType": 5126, "count": anzahl, "type": "VEC3",
             "min": [round(v, 6) for v in unten], "max": [round(v, 6) for v in oben]},
            {"bufferView": 1, "componentType": 5126, "count": anzahl, "type": "VEC3",
             "min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
            {"bufferView": 2, "componentType": 5126, "count": anzahl, "type": "VEC2",
             "min": [0.0, 0.0], "max": [0.0, 0.0]},
            {"bufferView": 3, "componentType": 5123, "count": len(indizes), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(ecken_roh), "target": 34962},
            {"buffer": 0, "byteOffset": len(ecken_roh), "byteLength": len(normal_roh), "target": 34962},
            {"buffer": 0, "byteOffset": len(ecken_roh) + len(normal_roh), "byteLength": len(uv_roh),
             "target": 34962},
            {"buffer": 0, "byteOffset": len(ecken_roh) + len(normal_roh) + len(uv_roh) + fuell,
             "byteLength": len(index_roh), "target": 34963},
        ],
        "buffers": [{"byteLength": len(puffer), "uri": bin_datei}],
    }
    return json.dumps(gltf, indent=1), puffer


def material_farbe(name: str, rgb: tuple[int, int, int], *, eigenlicht: float,
                   alpha: float = 1.0) -> dict:
    lin = farbe_linear(rgb)
    m = {
        "name": name,
        "pbrMetallicRoughness": {"baseColorFactor": lin + [alpha], "metallicFactor": 0.0,
                                 "roughnessFactor": 0.85},
        "emissiveFactor": [round(min(1.0, k * eigenlicht), 6) for k in lin],
        "doubleSided": alpha < 1.0,
    }
    if alpha < 1.0:
        m["alphaMode"] = "BLEND"
    return m


MATERIAL_UNSICHTBAR = {"name": "Invisible", "extensions": {"ASOBO_material_invisible": {}}}


def licht_erweiterung() -> dict:
    """Der Eintrag `ASOBO_macro_light` des Punktlichts — die Form stammt von Asobos `Point.NNN`."""
    return {
        "color": list(LICHT_FARBE),
        "intensity": LICHT_STAERKE,
        "cone_angle": LICHT_KEGEL,
        "has_simmetry": False,
        "flash_frequency": 0.0,
        "flash_duration": 0.0,
        "flash_phase": 0.0,
        "rotation_speed": 0.0,
        "day_night_cycle": True,
    }


# --------------------------------------------------------------------------- Dateien

def _modell_xml(kennung: str) -> str:
    """Das Modell-XML: nur die LOD-Zeile. `minSize="0"` — nie wegen Bildschirmgröße ausblenden."""
    return ('<ModelInfo>\n\t<LODS>\n'
            f'\t\t<LOD minSize="0" ModelFile="{kennung}.gltf"/>\n'
            '\t</LODS>\n</ModelInfo>\n')


def _modell_schreiben(wurzel: Path, ordner: str, kennung: str, gltf_json: str, puffer: bytes) -> None:
    ziel = wurzel / f"model.{ordner}"
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "model.CFG").write_text(f"[models]\nnormal={kennung}.xml\n", encoding="utf-8", newline="\r\n")
    (ziel / f"{kennung}.xml").write_text(_modell_xml(kennung), encoding="utf-8", newline="\r\n")
    (ziel / f"{kennung}.gltf").write_text(gltf_json, encoding="utf-8", newline="\n")
    (ziel / f"{kennung}.bin").write_bytes(puffer)


def marken_schreiben(wurzel: Path) -> int:
    """Schreibt alle Marken-SimObjects nach `wurzel` (= `…/SimObjects/Misc/FrsMarke`).

    Gibt die Zahl der Titel zurück.
    """
    wurzel.mkdir(parents=True, exist_ok=True)
    teile = ["[VERSION]", "Major=1", "Minor=0", ""]
    n = 0

    def eintrag(titel: str, ordner: str) -> None:
        nonlocal n
        teile.extend([f"[fltsim.{n}]", f"title={titel}", f"model={ordner}", "texture=", ""])
        n += 1

    for name, rgb in FARBEN.items():
        kennung, ordner = titel_wuerfel(name), f"wuerfel_{name}"
        j, p = _gltf(f"frs_wuerfel_{name}", f"{kennung}.bin", wuerfel_flaechen(WUERFEL_KANTE),
                     material_farbe(kennung, rgb, eigenlicht=WUERFEL_EIGENLICHT))
        _modell_schreiben(wurzel, ordner, kennung, j, p)
        eintrag(kennung, ordner)

    for name, rgb in SAEULEN_FARBEN.items():
        kennung, ordner = titel_saeule(name), f"saeule_{name}"
        j, p = _gltf(f"frs_saeule_{name}", f"{kennung}.bin",
                     prisma_flaechen(SAEULE_ECKEN, SAEULE_BREITE, SAEULE_HOEHE),
                     material_farbe(kennung, rgb, eigenlicht=1.0, alpha=SAEULE_ALPHA))
        _modell_schreiben(wurzel, ordner, kennung, j, p)
        eintrag(kennung, ordner)

    # Das Punktlicht: ein winziger unsichtbarer Träger (5 cm) und der Lichtknoten darüber.
    j, p = _gltf("frs_licht_warm", f"{TITEL_LICHT}.bin", wuerfel_flaechen(0.05), MATERIAL_UNSICHTBAR,
                 licht=licht_erweiterung(), lichtposition=(0.0, LICHT_HOEHE, 0.0))
    _modell_schreiben(wurzel, "licht_warm", TITEL_LICHT, j, p)
    eintrag(TITEL_LICHT, "licht_warm")

    # Ohne diesen Block erkennt der Package Builder gar nichts (`paket_bauen.simobjects_schreiben`).
    # Gleiche Werte wie beim Rauch: `StaticObject`, und die Animationsentfernung so groß, dass ein
    # Marker nicht von weitem stehen bleibt.
    teile += ["[General]", "category=StaticObject", "DistanceToNotAnimate=15000", ""]
    (wurzel / "sim.cfg").write_text("\n".join(teile), encoding="utf-8", newline="\r\n")
    return n


if __name__ == "__main__":
    ziel = Path(__file__).resolve().parent / "PackageSources" / "SimObjects" / "Misc" / HERSTELLER_ORDNER
    print(f"{marken_schreiben(ziel)} Titel nach {ziel}")
