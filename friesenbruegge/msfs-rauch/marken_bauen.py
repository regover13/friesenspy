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

    FrsWuerfel_<Farbe>   7 Stück   Würfel, 3 m Kante: die sechs Friesenfarben (`rauch_bauen.FARBEN`)
                                   und Scheinwerferweiß
    FrsSaeule_<Farbe>    7 Stück   Lichtsäule wie ein Scheinwerferstrahl, 100 m hoch, unten 4 m,
                                   oben 6 m breit, nach oben ausblendend: dieselben sieben Farben
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
  belegt: welche `intensity` dem Nachtbild entspricht. Gestartet mit 5,0 (häufigster Wert der
  Scheinwerfer bei Asobo, eine ANNAHME); nach dem 2020er Nachttest wollte der Nutzer es „etwas
  heller, sagen wir 8.0" — der Wert steht seither auf 8,0 und bleibt der Regler für den Flugtest.

DIE SÄULE — EIN SCHEINWERFERSTRAHL AUS 25 STAPELN (Flugtest MSFS 2020, 20.09.2026)
-----------------------------------------------------------------------------------
Die erste Fassung (0,8 m breit, überall gleich hell) lud und stand; der Nutzer wollte sie breiter und
wie einen Scheinwerferstrahl: unten hell, nach oben stetig schwächer, oben praktisch ausgeblendet.

⚠ **Der Verlauf steckt in den MATERIALIEN, nicht in Vertexfarben.** `COLOR_0` kommt in Asobos
Modellen vor (z. B. `ASO_Aircraft_Caddy`), aber dass ein Vertex-Alpha in einem `BLEND`-Material
zuverlässig wirkt, ist damit NICHT belegt — und ein Fehlschlag wäre still (die Säule stünde einfach
überall gleich deckend da). Also: **25 Segmente zu je 4 m**, jedes eine eigene Primitive mit eigenem
Material, dessen `baseColorFactor`-Alpha und `emissiveFactor` je Segment abgestuft sind. Ungemessen
bleibt, wie sichtbar die 4-m-Stufen im Flug sind; der Regler dafür ist `SAEULE_SEGMENTE`.

Der Verlauf, mit t = Höhe der Segmentmitte / 100 m:

    Alpha     = ALPHA_UNTEN + (ALPHA_OBEN − ALPHA_UNTEN) · t        linear, 0,55 → 0,02
    Emissive  = Farbe · (1 − t)^1,2                                 oben fast nichts mehr

Die Breite wächst gleichmäßig von 4 m (unten) auf 6 m (oben), gemessen über die Ecken des
Achtecks; jedes Segment ist ein Kegelstumpf, seine Normalen kippen entsprechend leicht.
`alphaMode BLEND` und `doubleSided` bleiben.

**SCHEINWERFERWEISS.** Das Weiß ist nicht reinweiß, sondern `WEISS` = sRGB (255, 240, 200): warmes,
leicht gelbliches Weiß wie ein Scheinwerfer (Nutzer, 20.09.2026). EINE Konstante, benutzt von der
weißen Säule und vom weißen Würfel; die X-Plane-Seite nimmt dieselbe Farbe.

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
#: Scheinwerferweiß: warmes, leicht gelbliches Weiß, sRGB (255, 240, 200) (Nutzer, 20.09.2026).
#: EINE Konstante für die weiße Säule UND den weißen Würfel — und dieselbe Farbe wie in X-Plane.
WEISS = (255, 240, 200)

#: Höhe der Säule in Metern; Breite über die Ecken des Achtecks unten und oben (Nutzer, nach dem
#: Flugtest: „unten 4 m, oben 6 m", leicht aufweitend wie ein Strahl).
SAEULE_HOEHE = 100.0
SAEULE_BREITE_UNTEN = 4.0
SAEULE_BREITE_OBEN = 6.0
SAEULE_ECKEN = 8
#: Stapel: 25 Segmente à 4 m, je eine Primitive mit eigenem Material (s. Kopfkommentar).
SAEULE_SEGMENTE = 25
#: Deckkraft unten und oben (linear dazwischen) und der Exponent des Eigenlichts.
SAEULE_ALPHA_UNTEN = 0.55
SAEULE_ALPHA_OBEN = 0.02
SAEULE_EMISSIV_EXPONENT = 1.2
#: Wie stark der Würfel von selbst leuchtet, damit er nachts nicht schwarz ist (Anteil der Farbe).
WUERFEL_EIGENLICHT = 0.35

#: Das Punktlicht: warmweiß wie die Lichter im Nachtbild, Rundumstrahler, nur nachts.
LICHT_FARBE = (1.0, 0.84, 0.6)
LICHT_STAERKE = 8.0          # Nutzerwunsch nach dem 2020er Nachttest (vorher 5,0) — der Regler für den Flugtest
LICHT_KEGEL = 360            # Rundumstrahler, wie `Point.NNN` bei Asobo
LICHT_HOEHE = 0.3            # Meter über dem Boden

HERSTELLER_ORDNER = "FrsMarke"

#: Würfel- und Säulenfarben: die Friesenfarben und Scheinwerferweiß.
MARKEN_FARBEN = {**FARBEN, "weiss": WEISS}
WUERFEL_FARBEN = MARKEN_FARBEN
SAEULEN_FARBEN = MARKEN_FARBEN


def titel_wuerfel(name: str) -> str:
    return f"FrsWuerfel_{name.capitalize()}"


def titel_saeule(name: str) -> str:
    return f"FrsSaeule_{name.capitalize()}"


TITEL_LICHT = "FrsLicht_Warm"


def alle_titel() -> list[str]:
    """Die Titel in der Reihenfolge der sim.cfg: erst Würfel, dann Säulen, dann das Licht."""
    return ([titel_wuerfel(n) for n in WUERFEL_FARBEN] + [titel_saeule(n) for n in SAEULEN_FARBEN]
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


def saeule_radius(y: float) -> float:
    """Umkreisradius der Säule in der Höhe `y` (linear von unten nach oben)."""
    r0, r1 = SAEULE_BREITE_UNTEN / 2.0, SAEULE_BREITE_OBEN / 2.0
    return r0 + (r1 - r0) * (y / SAEULE_HOEHE)


def segment_flaechen(ecken: int, y0: float, y1: float) -> list:
    """Ein Kegelstumpf-Mantel ohne Deckel von `y0` bis `y1`, Ursprung Mitte der Unterseite der SÄULE.

    Jede Seite hat ihre eigenen vier Ecken und ihre eigene Normale (flache Schattierung, wie beim
    Würfel). Weil die Säule oben breiter ist, kippt die Normale leicht nach unten. Die Vierecke laufen
    gegen den Uhrzeigersinn von außen gesehen; die Säule ist ohnehin `doubleSided`.
    """
    r0, r1 = saeule_radius(y0), saeule_radius(y1)
    winkel = [2.0 * math.pi * k / ecken for k in range(ecken + 1)]
    # Die Seitenfläche liegt im Abstand r·cos(π/n) von der Achse; ihre Steigung bestimmt die Kippung.
    steigung = (r1 - r0) * math.cos(math.pi / ecken) / (y1 - y0)
    laenge = math.sqrt(1.0 + steigung * steigung)
    raus = []
    for k in range(ecken):
        mitte = (winkel[k] + winkel[k + 1]) / 2.0
        normale = (round(math.cos(mitte) / laenge, 6), round(-steigung / laenge, 6),
                   round(math.sin(mitte) / laenge, 6))
        a, b = winkel[k], winkel[k + 1]
        raus.append((normale, [(r0 * math.cos(a), y0, r0 * math.sin(a)),
                               (r1 * math.cos(a), y1, r1 * math.sin(a)),
                               (r1 * math.cos(b), y1, r1 * math.sin(b)),
                               (r0 * math.cos(b), y0, r0 * math.sin(b))]))
    return raus


def saeule_stufen() -> list[tuple[float, float, float, float]]:
    """Die Stapel der Säule: `(y0, y1, alpha, eigenlicht)` je Segment, von unten nach oben.

    `t` ist die Höhe der Segmentmitte im Verhältnis zur Säulenhöhe.
    """
    h = SAEULE_HOEHE / SAEULE_SEGMENTE
    raus = []
    for i in range(SAEULE_SEGMENTE):
        t = (i + 0.5) / SAEULE_SEGMENTE
        alpha = SAEULE_ALPHA_UNTEN + (SAEULE_ALPHA_OBEN - SAEULE_ALPHA_UNTEN) * t
        raus.append((i * h, (i + 1) * h, round(alpha, 6), round((1.0 - t) ** SAEULE_EMISSIV_EXPONENT, 6)))
    return raus


# --------------------------------------------------------------------------- glTF

def _gltf(knoten: str, bin_datei: str, gruppen: list, *,
          licht: dict | None = None, lichtposition: tuple | None = None) -> tuple[str, bytes]:
    """Baut das glTF: ein Mesh-Knoten, optional dazu ein Lichtknoten. Gibt (JSON, Rohpuffer).

    `gruppen` ist eine Liste `(flaechen, material)` — je Gruppe EINE Primitive mit eigenem Material
    (so entsteht die abgestufte Säule; Würfel und Licht haben genau eine). Jede Primitive hat ihre
    eigenen vier Accessoren (POSITION, NORMAL, TEXCOORD_0, Indizes) und BufferViews, in dieser
    Reihenfolge: Primitive p liegt bei den Accessoren 4p … 4p+3.

    Die Zahlen liegen in einer ECHTEN `.bin` daneben, nicht als Base64 (der MSFS-Modellcompiler
    schreibt ein `data:`-URI still auf eine externe Datei um, ohne sie zu erzeugen —
    `paket_bauen.wuerfel_gltf`).

    Zu jeder Ecke gehört ein `TEXCOORD_0` (0, 0): Ein Material ohne Textur braucht keine
    Koordinaten, aber die Shader des Simulators lesen sie, und ein Mesh ohne sie ist der eine
    Unterschied zu Asobos Modellen, den wir uns sparen können. (Ungemessen, ob es nötig ist.)
    """
    puffer = b""
    accessoren, sichten, primitiven, materialien = [], [], [], []
    for pi, (flaechen, material) in enumerate(gruppen):
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
        ende = (-(len(index_roh))) % 4
        start = len(puffer)
        o_norm = start + len(ecken_roh)
        o_uv = o_norm + len(normal_roh)
        o_idx = o_uv + len(uv_roh) + fuell
        puffer += ecken_roh + normal_roh + uv_roh + b"\x00" * fuell + index_roh + b"\x00" * ende

        sichten += [
            {"buffer": 0, "byteOffset": start, "byteLength": len(ecken_roh), "target": 34962},
            {"buffer": 0, "byteOffset": o_norm, "byteLength": len(normal_roh), "target": 34962},
            {"buffer": 0, "byteOffset": o_uv, "byteLength": len(uv_roh), "target": 34962},
            {"buffer": 0, "byteOffset": o_idx, "byteLength": len(index_roh), "target": 34963},
        ]
        v0 = 4 * pi
        accessoren += [
            # Die Bounding Box MUSS zur Geometrie passen — der Simulator liest sie für die
            # Größenprüfung, nicht die Eckpunkte.
            {"bufferView": v0, "componentType": 5126, "count": anzahl, "type": "VEC3",
             "min": [round(v, 6) for v in unten], "max": [round(v, 6) for v in oben]},
            {"bufferView": v0 + 1, "componentType": 5126, "count": anzahl, "type": "VEC3",
             "min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
            {"bufferView": v0 + 2, "componentType": 5126, "count": anzahl, "type": "VEC2",
             "min": [0.0, 0.0], "max": [0.0, 0.0]},
            {"bufferView": v0 + 3, "componentType": 5123, "count": len(indizes), "type": "SCALAR"},
        ]
        primitiven.append({"attributes": {"POSITION": v0, "NORMAL": v0 + 1, "TEXCOORD_0": v0 + 2},
                           "indices": v0 + 3, "material": pi, "mode": 4})
        materialien.append(material)

    knoten_liste = [{"mesh": 0, "name": knoten}]
    verwendet = ["ASOBO_normal_map_convention"]
    if any("ASOBO_material_invisible" in m.get("extensions", {}) for m in materialien):
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
        "meshes": [{"primitives": primitiven}],
        "materials": materialien,
        "accessors": accessoren,
        "bufferViews": sichten,
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

    for name, rgb in WUERFEL_FARBEN.items():
        kennung, ordner = titel_wuerfel(name), f"wuerfel_{name}"
        j, p = _gltf(f"frs_wuerfel_{name}", f"{kennung}.bin",
                     [(wuerfel_flaechen(WUERFEL_KANTE),
                       material_farbe(kennung, rgb, eigenlicht=WUERFEL_EIGENLICHT))])
        _modell_schreiben(wurzel, ordner, kennung, j, p)
        eintrag(kennung, ordner)

    for name, rgb in SAEULEN_FARBEN.items():
        kennung, ordner = titel_saeule(name), f"saeule_{name}"
        gruppen = [(segment_flaechen(SAEULE_ECKEN, y0, y1),
                    material_farbe(f"{kennung}_{i:02d}", rgb, eigenlicht=licht_anteil, alpha=alpha))
                   for i, (y0, y1, alpha, licht_anteil) in enumerate(saeule_stufen())]
        j, p = _gltf(f"frs_saeule_{name}", f"{kennung}.bin", gruppen)
        _modell_schreiben(wurzel, ordner, kennung, j, p)
        eintrag(kennung, ordner)

    # Das Punktlicht: ein winziger unsichtbarer Träger (5 cm) und der Lichtknoten darüber.
    j, p = _gltf("frs_licht_warm", f"{TITEL_LICHT}.bin", [(wuerfel_flaechen(0.05), MATERIAL_UNSICHTBAR)],
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
