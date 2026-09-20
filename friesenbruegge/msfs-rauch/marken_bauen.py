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

  * ⭐ **Lichtknoten UND sichtbares Mesh im selben glTF ist bei Asobo der Normalfall** (ausgezählt
    20.09.2026): 24 der 111 Modelle mit Lichtknoten tragen im selben glTF auch Meshes (alle 24); KEIN
    Lichtknoten trägt selbst ein Mesh. Bei der Seilwinde `ESW_2B` steht es so: Wurzelknoten `Light` MIT
    Mesh und den Lichtern als Kindern (`Point`, `Point.001`, `Spot`, `Spot.001`, selbst ohne Mesh), daneben
    die Wurzelknoten der Karosserie. Genau so ist `FrsLicht_Warm` aufgebaut: Wurzelknoten `Light` trägt
    den sichtbaren Leuchtkern, das Punktlicht `Point` hängt als Kind darunter.
  * Ebenso NICHT belegt: welche `intensity` dem Nachtbild entspricht. Gestartet mit 5,0 (häufigster
    Wert der Scheinwerfer bei Asobo, eine ANNAHME), dann 8,0, 50,0, 400,0 und zuletzt 1600,0 — die Werte
    in Asobos Modellen reichen nur bis 50, der Regler ist also weit außerhalb dessen, was belegt ist
    (gemessen im 2024er Nachttest: der Lichtfleck wird mit der Stärke heller, s. Testrunde 2 unten).

**DER LEUCHTKERN (Testrunde 2, 20.09.2026).** Der Lichtfleck des `ASOBO_macro_light` allein ist der
schwächste Punkt (Nutzer nach dem 2024-Nachttest: „das hellste Licht (I100) ist noch nicht hell genug,
viel dunkler als die Runway-Feuer"; gemessen: Halo Luminanz ~42, Runway-Feuer ~162). Die Runway-Feuer
wirken als heller PUNKT. Deshalb trägt `FrsLicht_Warm` zusätzlich einen kleinen sichtbaren Kern: einen
0,2-m-Würfel in Warmweiß (1,0 / 0,84 / 0,6), `emissiveFactor` voll, mit `ASOBO_material_emissive`
(`emissiveNightMultiplier` = `LICHT_KERN_NACHT`). Er ersetzt den unsichtbaren 5-cm-Träger; der Kern sitzt
mit seiner Mitte 0,3 m über dem Boden, das Punktlicht in seiner Mitte.

DIE HELLIGKEIT IN MSFS 2024 — `ASOBO_material_emissive` (Nachttest 2024, 20.09.2026)
-----------------------------------------------------------------------------------
Dasselbe Paket rendert in MSFS 2024 nachts viel dunkler als in 2020 (gemessen aus den Nachtbildern:
Orange-Würfel 2020 (249, 145, 54), 2024 nur (46, 16, 6) — etwa ein Fünftel bis ein Zehntel). Nutzer:
„das muss alles mindestens so hell sein wie die Feuer an der Runway im Hintergrund".

Der Regler dafür ist die glTF-Erweiterung **`ASOBO_material_emissive`** mit `emissiveDayMultiplier` und
`emissiveNightMultiplier`. WAS BELEGT IST, und woher:

  * Es gibt sie im **2024er SDK** (`C:/MSFS 2024 SDK/Schemas/ASOBO_material_emissive/
    gltf.ASOBO_material_emissive.schema.json`: zwei Felder, beide `number`, ohne Grenzen), im **2020er
    SDK nicht** (`D:/MSFS SDK/Schemas` kennt sie nicht).
  * **Vorgabe 1,0 für beide.** Der 3ds-Max-Exporter (`FlightSimMaterialExporter.cs`, `Defaults`) und das
    Blender-Addon (`MSFS2024_MaterialProperties`) setzen 1.0; Asobos mitgeliefertes Bären-Beispiel
    (`Samples/DevmodeProjects/SimObjects/Animals/Bears`) schreibt `{"emissiveDayMultiplier": 1.0,
    "emissiveNightMultiplier": 1.0}` an jedes Material und führt die Erweiterung in `extensionsUsed`,
    NICHT in `extensionsRequired`. Genau so machen wir es.
  * ⚠ **NICHT belegt:** was der Wert im Simulator genau tut. Das 2024er SDK enthält keine Dokumentation
    (nur Schemas, Samples und Werkzeuge), im 2020er steht die Erweiterung nirgends. Nach Name und
    Vorgabe ist es ein Faktor auf `emissiveFactor`, getrennt für Tag und Nacht — Wertebereich und
    Wirkung im Renderer sind ungemessen. Deshalb die Testtitel (`MIT_TESTTITELN`): Der Nutzer misst
    im 2024-Nachtflug, welcher Wert trifft.
  * ⚠ **Ungemessen:** ob der 2020er Compiler eine unbekannte, nicht geforderte Erweiterung
    toleriert. Sie steht nur in `extensionsUsed`; ein 2020er Bau zeigt es.

**Testrunde 1 (2024, feste Kamera, nachts): Der Multiplikator WIRKT** — das 2024er SDK behält ihn —,
aber auch 12 ist zu dunkel. Gemessen: Runway-Feuer (hellste 200 Pixel) Luminanz ~162, RGB (224, 157, 26);
unsere Würfel bei 12 nur ~74, RGB ~(161, 55, 7); Säulen bis ~97 („A85 hat kaum Einfluss"); Licht-Halo ~42.
Also Testrunde 2 mit 20/40/80/160 und einem Leuchtkern am Licht.

**Testrunde 2 (2024, feste Kamera, nachts): Luminanz der hellsten Pixel**, Maßstab die Runway-Feuer = 144.

    Nacht-Multiplikator     20    40    80   160        Licht (K = Kern-Multiplikator, I = Stärke)
    Würfel (Signalorange)   85   112   142   173        K100_I100   38     K400_I400    97
    Säule  (Alpha unten     111  138   168   195        K100_I400   99     K400_I1600  176
            0,85)

Das Ziel „mindestens so hell wie die Feuer" trifft bei Würfeln ab etwa 80, bei Säulen schon knapp darunter.
Beim Licht trägt die STÄRKE die Helligkeit: bei I = 400 ergab der Kern-Multiplikator 100 → 400 keinen
messbaren Unterschied (99 gegen 97), von I = 400 auf 1600 stieg der Wert von 97 auf 176.

**Endgültige Vorgabewerte:** `EMISSIVE_NACHT` = 80, `SAEULE_ALPHA_UNTEN` = 0,85, `LICHT_KERN_NACHT` = 400,
`LICHT_STAERKE` = 1600. `EMISSIVE_TAG` bleibt 1,0. Die Vorgabe stand zuerst auf 120 (etwas über dem Ziel);
nach der Endabnahme in MSFS 2024 und 2020 (alle 15 Marken laden, Bild gut) war der Nutzer der Meinung „fast
ein bisschen zu hell, vielleicht reicht der 80er-Wert auch" — **80 ist gewählt**, es liegt bei den Runway-
Feuern (Würfel 142, Säule 168 gegen 144). Die Stufen 120 und 160 sind nur gemessen (160) bzw. aus den
Stufen gefolgert (120), nicht gewählt. Das Licht bleibt bei K400/I1600 („lass das Licht wie es ist, ist
okay dass es in 2020 heller ist"). Die Testtitel sind mit `MIT_TESTTITELN = False` abgeschaltet und bleiben
im Generator für eine spätere Nachmessung.

⚠ **Die Friesenfarben bleiben Friesenfarben.** Ein Farbkanal kann nicht über 1,0 hinaus: Signalorange
(255, 106, 19) hat im R-Kanal schon 1,0 (linear), und `emissiveFactor` wird auf 1,0 geklemmt. Mehr
Helligkeit kann bei solchen Farben nur über den Multiplikator kommen, den der Simulator als Bloom/
Tone-Mapping auf dem Bildschirm sichtbar macht — der Farbton wandert dabei Richtung Weiß. Die Farbwerte
selbst werden nicht verändert; der Multiplikator hebt nur die Helligkeit.

DIE SÄULE — EIN SCHEINWERFERSTRAHL AUS 100 STAPELN (Flugtest MSFS 2020, 20.09.2026)
------------------------------------------------------------------------------------
Die erste Fassung (0,8 m breit, überall gleich hell) lud und stand; der Nutzer wollte sie breiter und
wie einen Scheinwerferstrahl: unten hell, nach oben stetig schwächer, oben praktisch ausgeblendet.

⚠ **Der Verlauf steckt in den MATERIALIEN, nicht in Vertexfarben.** `COLOR_0` kommt in Asobos
Modellen vor (z. B. `ASO_Aircraft_Caddy`), aber dass ein Vertex-Alpha in einem `BLEND`-Material
zuverlässig wirkt, ist damit NICHT belegt — und ein Fehlschlag wäre still (die Säule stünde einfach
überall gleich deckend da). Also: **100 Segmente zu je 1 m**, jedes eine eigene Primitive mit eigenem
Material, dessen `baseColorFactor`-Alpha und `emissiveFactor` je Segment abgestuft sind.

Die erste Fassung hatte 25 Segmente zu je 4 m; in MSFS 2024 waren die **waagerechten Stufen sichtbar**
(Endabnahme 20.09.2026). Deshalb 100 × 1 m — Regler `SAEULE_SEGMENTE`. Die Größe je Säule wächst dabei
etwa auf das Vierfache (gemessen in der Ausgabe: s. Test/Bericht). ⚠ **Was zum Compiler belegt ist und was
nicht** (ausgezählt an 130 Asobo-`*LOD00.gltf` im MSFS-2020-Bestand): Asobo-Modelle haben bis zu 437
Primitiven je glTF, aber verteilt auf viele Knoten (höchstens 22 je Mesh) und höchstens 42 Materialien.
Eine Säule mit 100 Primitiven in EINEM Mesh und 100 Materialien liegt darüber; ob der 2024er Compiler das
klaglos annimmt, ist UNGEMESSEN (mit 25 tat er es). Fällt es durch, wäre der nächste Schritt ein Knoten je
Segment (wie bei Asobo: etwa ein Knoten je Primitive) oder weniger Materialstufen.

Der Verlauf, mit t = Höhe der Segmentmitte / 100 m:

    Alpha     = ALPHA_UNTEN + (ALPHA_OBEN − ALPHA_UNTEN) · t        linear, 0,85 → 0,02
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
import os
import stat
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
#: Stapel: 100 Segmente à 1 m, je eine Primitive mit eigenem Material (s. Kopfkommentar). Vorher 25 × 4 m:
#: In MSFS 2024 waren die waagerechten Stufen sichtbar.
SAEULE_SEGMENTE = 100
#: Deckkraft unten und oben (linear dazwischen) und der Exponent des Eigenlichts.
#: Alpha unten 0,85 (vorher 0,55): Nach dem 2024-Nachttest sind die Säulen zu dunkel; mehr Deckkraft
#: bringt mehr Leuchtfläche. Der Nutzer korrigiert den Wert nach der Messung (`FrsTestSaeule_*_A85`).
SAEULE_ALPHA_UNTEN = 0.85
SAEULE_ALPHA_OBEN = 0.02
SAEULE_EMISSIV_EXPONENT = 1.2
#: Wie stark der Würfel von selbst leuchtet, damit er nachts nicht schwarz ist (Anteil der Farbe).
WUERFEL_EIGENLICHT = 0.35

#: `ASOBO_material_emissive` (nur MSFS 2024 wertet sie aus; 2020 kennt sie nicht): Multiplikatoren auf
#: das Eigenlicht bei Tag und bei Nacht. 80 nach Testrunde 2 und der Endabnahme (Würfel 80 → Luminanz 142,
#: Säule 168; Runway-Feuer 144; Nutzer: 120 sei „fast ein bisschen zu hell, vielleicht reicht der 80er-Wert
#: auch"). 120 und 160 sind nur gemessen. Die Farbwerte bleiben Friesenfarben — bei R-Kanal nahe 1,0 wirkt
#: mehr Helligkeit nur über Bloom und Tone-Mapping (s. Kopfkommentar).
EMISSIVE_TAG = 1.0
EMISSIVE_NACHT = 80.0

#: Das Punktlicht: warmweiß wie die Lichter im Nachtbild, Rundumstrahler, nur nachts.
LICHT_FARBE = (1.0, 0.84, 0.6)
#: Lichtstärke des `ASOBO_macro_light`: 5,0 → 8,0 (2020er Nachttest) → 50,0 (2024er Nachttest) → 400,0
#: (Testrunde 1: „auch I100 noch viel dunkler als die Runway-Feuer") → 1600,0 (Testrunde 2: K400_I400
#: Luminanz 97, K400_I1600 176 gegen 144 bei den Runway-Feuern).
LICHT_STAERKE = 1600.0
LICHT_KEGEL = 360            # Rundumstrahler, wie `Point.NNN` bei Asobo
LICHT_HOEHE = 0.3            # Meter über dem Boden: Mitte des Leuchtkerns und Ort des Punktlichts
#: Der Leuchtkern: 0,2-m-Würfel, warmweiß wie das Licht, `emissiveFactor` voll; `LICHT_KERN_NACHT` ist sein
#: `emissiveNightMultiplier`. 400 ist der Wert der Testrunde 2; bei I = 400 machte K 100 → 400 keinen
#: messbaren Unterschied (99 gegen 97), die Helligkeit kommt vom Lichtfleck (`LICHT_STAERKE`).
LICHT_KERN_KANTE = 0.2
LICHT_KERN_NACHT = 400.0
#: Unterkante des Kerns über dem Boden, sodass seine MITTE auf `LICHT_HOEHE` liegt.
LICHT_KERN_UNTEN = round(LICHT_HOEHE - LICHT_KERN_KANTE / 2.0, 6)

HERSTELLER_ORDNER = "FrsMarke"

#: ⭐ TESTTITEL für den Helligkeitsabgleich in MSFS 2024 — mit EINEM Wort abschaltbar. An: `sim.cfg` führt
#: hinter den 15 endgültigen Titeln zusätzlich die Titel aus `testtitel()`; aus: nur die 15, und die
#: Ordner der Testtitel werden gelöscht, damit der Paketbau sie nicht als Beiwerk mitnimmt.
MIT_TESTTITELN = False
#: Testrunde 2 (nach Runde 1: Multiplikator wirkt, aber 12 ist zu dunkel): Würfel und Säulen mit 20/40/80/160,
#: die Säulen mit Alpha unten 0,85 (unabhängig vom endgültigen `SAEULE_ALPHA_UNTEN`, damit die Reihe
#: vergleichbar bleibt). Das Licht als Paare `(Kern-Multiplikator K, Lichtstärke I)`.
TEST_ALPHA = 0.85
TEST_MULTIPLIKATOREN = (20, 40, 80, 160)
TEST_LICHTER = ((100, 100), (100, 400), (400, 400), (400, 1600))
TEST_FARBE = "signalorange"

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
    """Die ENDGÜLTIGEN Titel in der Reihenfolge der sim.cfg: erst Würfel, dann Säulen, dann das Licht."""
    return ([titel_wuerfel(n) for n in WUERFEL_FARBEN] + [titel_saeule(n) for n in SAEULEN_FARBEN]
            + [TITEL_LICHT])


def testtitel() -> list[tuple[str, str, dict]]:
    """Die Testtitel: `(Titel, Ordner, Parameter)`, in der Reihenfolge der sim.cfg hinter den endgültigen.

    Würfel und Säulen in Signalorange mit `nacht` = Nacht-Multiplikator 20/40/80/160, die Säule dazu mit
    `alpha` unten 0,85; das Licht mit `kern` (Nacht-Multiplikator des Leuchtkerns, K) und `staerke`
    (Lichtstärke des Macro-Lights, I).
    """
    raus = []
    for m in TEST_MULTIPLIKATOREN:
        raus.append((f"FrsTestWuerfel_M{m}", f"test_wuerfel_m{m}", {"art": "wuerfel", "nacht": float(m)}))
    for m in TEST_MULTIPLIKATOREN:
        raus.append((f"FrsTestSaeule_M{m}", f"test_saeule_m{m}",
                     {"art": "saeule", "nacht": float(m), "alpha": TEST_ALPHA}))
    for k, i in TEST_LICHTER:
        raus.append((f"FrsTestLicht_K{k}_I{i}", f"test_licht_k{k}_i{i}",
                     {"art": "licht", "kern": float(k), "staerke": float(i)}))
    return raus


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


def saeule_stufen(alpha_unten: float | None = None) -> list[tuple[float, float, float, float]]:
    """Die Stapel der Säule: `(y0, y1, alpha, eigenlicht)` je Segment, von unten nach oben.

    `t` ist die Höhe der Segmentmitte im Verhältnis zur Säulenhöhe.
    """
    h = SAEULE_HOEHE / SAEULE_SEGMENTE
    unten = SAEULE_ALPHA_UNTEN if alpha_unten is None else alpha_unten
    raus = []
    for i in range(SAEULE_SEGMENTE):
        t = (i + 0.5) / SAEULE_SEGMENTE
        alpha = unten + (SAEULE_ALPHA_OBEN - unten) * t
        raus.append((i * h, (i + 1) * h, round(alpha, 6), round((1.0 - t) ** SAEULE_EMISSIV_EXPONENT, 6)))
    return raus


# --------------------------------------------------------------------------- glTF

def _gltf(knoten: str, bin_datei: str, gruppen: list, *,
          licht: dict | None = None, lichtposition: tuple | None = None,
          knotenposition: tuple | None = None) -> tuple[str, bytes]:
    """Baut das glTF: ein Mesh-Knoten; mit `licht` heißt er `Light` und trägt das Punktlicht als Kind.
    Gibt (JSON, Rohpuffer).

    Mit `licht` folgt der Aufbau Asobos Seilwinde `ESW_2B`: Wurzelknoten `Light` MIT Mesh (hier der
    Leuchtkern), darunter der Lichtknoten `Point` (ohne Mesh). `knotenposition` verschiebt den Wurzelknoten,
    `lichtposition` liegt relativ dazu.

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
    for erweiterung in ("ASOBO_material_emissive", "ASOBO_material_invisible"):
        if any(erweiterung in m.get("extensions", {}) for m in materialien):
            verwendet.append(erweiterung)
    if licht is not None:
        # Wie bei Asobos Seilwinde: Wurzelknoten `Light` MIT Mesh, darunter das Licht als `Point`.
        knoten_liste = [
            {"mesh": 0, "name": "Light", "translation": list(knotenposition or (0.0, 0.0, 0.0)),
             "children": [1]},
            {"name": "Point", "translation": list(lichtposition or (0.0, 0.0, 0.0)),
             "extensions": {"ASOBO_macro_light": licht}},
        ]
        verwendet.append("ASOBO_macro_light")
    wurzeln = [0]

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
                   alpha: float = 1.0, nacht: float | None = None) -> dict:
    """Ein Farbmaterial. `nacht` ist der `emissiveNightMultiplier` (Vorgabe `EMISSIVE_NACHT`).

    Die Erweiterung `ASOBO_material_emissive` steht an JEDEM Material dieser Funktion (Würfel und
    Säulen); das unsichtbare Trägermaterial des Lichts hat sie nicht.
    """
    lin = farbe_linear(rgb)
    m = {
        "name": name,
        "pbrMetallicRoughness": {"baseColorFactor": lin + [alpha], "metallicFactor": 0.0,
                                 "roughnessFactor": 0.85},
        "emissiveFactor": [round(min(1.0, k * eigenlicht), 6) for k in lin],
        "doubleSided": alpha < 1.0,
        "extensions": {"ASOBO_material_emissive": {
            "emissiveDayMultiplier": EMISSIVE_TAG,
            "emissiveNightMultiplier": EMISSIVE_NACHT if nacht is None else nacht}},
    }
    if alpha < 1.0:
        m["alphaMode"] = "BLEND"
    return m


MATERIAL_UNSICHTBAR = {"name": "Invisible", "extensions": {"ASOBO_material_invisible": {}}}


def material_kern(name: str, nacht: float | None = None) -> dict:
    """Das Material des Leuchtkerns: Warmweiß (`LICHT_FARBE`), `emissiveFactor` VOLL, deckend.

    Die Farbe steht als Faktor (0–1, linear), wie sie auch im Macro-Light steht. `nacht` ist der
    `emissiveNightMultiplier` (Vorgabe `LICHT_KERN_NACHT`).
    """
    return {
        "name": name,
        "pbrMetallicRoughness": {"baseColorFactor": list(LICHT_FARBE) + [1.0], "metallicFactor": 0.0,
                                 "roughnessFactor": 0.85},
        "emissiveFactor": list(LICHT_FARBE),
        "doubleSided": False,
        "extensions": {"ASOBO_material_emissive": {
            "emissiveDayMultiplier": EMISSIVE_TAG,
            "emissiveNightMultiplier": LICHT_KERN_NACHT if nacht is None else nacht}},
    }


def licht_erweiterung(staerke: float | None = None) -> dict:
    """Der Eintrag `ASOBO_macro_light` des Punktlichts — die Form stammt von Asobos `Point.NNN`."""
    return {
        "color": list(LICHT_FARBE),
        "intensity": LICHT_STAERKE if staerke is None else staerke,
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


def _wuerfel(wurzel: Path, kennung: str, ordner: str, rgb, nacht: float | None = None) -> None:
    j, p = _gltf(f"frs_{ordner}", f"{kennung}.bin",
                 [(wuerfel_flaechen(WUERFEL_KANTE),
                   material_farbe(kennung, rgb, eigenlicht=WUERFEL_EIGENLICHT, nacht=nacht))])
    _modell_schreiben(wurzel, ordner, kennung, j, p)


def _saeule(wurzel: Path, kennung: str, ordner: str, rgb, nacht: float | None = None,
            alpha_unten: float | None = None) -> None:
    gruppen = [(segment_flaechen(SAEULE_ECKEN, y0, y1),
                material_farbe(f"{kennung}_{i:02d}", rgb, eigenlicht=licht_anteil, alpha=alpha, nacht=nacht))
               for i, (y0, y1, alpha, licht_anteil) in enumerate(saeule_stufen(alpha_unten))]
    j, p = _gltf(f"frs_{ordner}", f"{kennung}.bin", gruppen)
    _modell_schreiben(wurzel, ordner, kennung, j, p)


def _licht(wurzel: Path, kennung: str, ordner: str, staerke: float | None = None,
           kern: float | None = None) -> None:
    """Das Punktlicht mit Leuchtkern: `Light` (0,2-m-Würfel, warmweiß, emissiv) trägt `Point` als Kind.

    Der Kern hat seinen Ursprung in der Mitte der Unterseite; der Wurzelknoten hebt ihn so an, dass seine
    MITTE auf `LICHT_HOEHE` (0,3 m) liegt, und das Punktlicht sitzt relativ dazu in dieser Mitte.
    """
    j, p = _gltf(f"frs_{ordner}", f"{kennung}.bin",
                 [(wuerfel_flaechen(LICHT_KERN_KANTE), material_kern(f"{kennung}_Kern", kern))],
                 licht=licht_erweiterung(staerke),
                 knotenposition=(0.0, LICHT_KERN_UNTEN, 0.0),
                 lichtposition=(0.0, round(LICHT_KERN_KANTE / 2.0, 6), 0.0))
    _modell_schreiben(wurzel, ordner, kennung, j, p)


def _testordner_loeschen(wurzel: Path, behalten: set[str] = frozenset()) -> None:
    """Räumt Testordner weg: alle `model.test_*` außer den `behalten`. Nie ein endgültiger Ordner.

    Aus (Schalter aus): `behalten` ist leer, alle Testordner gehen. An: Es bleiben die der aktuellen
    Testreihe; die einer FRÜHEREN Reihe (Testrunde 1 → 2) gehen, sonst nähme der Paketbau sie als
    Beiwerk mit, obwohl die sim.cfg sie nicht mehr nennt.

    Nicht per `rmtree` auf den ganzen Baum (OneDrive verweigerte das am 20.09.2026 mitten im Löschen,
    `paket_bauen.seehund_schreiben`): Datei für Datei, dann der leere Ordner; ein Fehler bleibt stehen.
    """
    for d in sorted(wurzel.glob("model.test_*")):
        if d.name in behalten:
            continue
        for f in d.iterdir():
            _loesche(f.unlink, f)
        _loesche(d.rmdir, d)


def _loesche(aktion, pfad: Path) -> None:
    """Führt `unlink`/`rmdir` aus; verweigert Windows es wegen `ReadOnly` (OneDrive, 20.09.2026: ein
    Ordner der vorigen Testreihe ließ sich nur nach `Remove-Item -Force` löschen), wird das Attribut
    aufgehoben und es folgt ein zweiter Versuch."""
    try:
        aktion()
    except PermissionError:
        os.chmod(pfad, stat.S_IREAD | stat.S_IWRITE)
        aktion()


def marken_schreiben(wurzel: Path, mit_testtiteln: bool | None = None) -> int:
    """Schreibt alle Marken-SimObjects nach `wurzel` (= `…/SimObjects/Misc/FrsMarke`).

    `mit_testtiteln` (Vorgabe `MIT_TESTTITELN`) hängt die Testtitel an die sim.cfg hinter die
    endgültigen; die Dateien der endgültigen Titel sind davon unabhängig. Gibt die Zahl der Titel zurück.
    """
    if mit_testtiteln is None:
        mit_testtiteln = MIT_TESTTITELN
    wurzel.mkdir(parents=True, exist_ok=True)
    teile = ["[VERSION]", "Major=1", "Minor=0", ""]
    n = 0

    def eintrag(titel: str, ordner: str) -> None:
        nonlocal n
        teile.extend([f"[fltsim.{n}]", f"title={titel}", f"model={ordner}", "texture=", ""])
        n += 1

    for name, rgb in WUERFEL_FARBEN.items():
        kennung, ordner = titel_wuerfel(name), f"wuerfel_{name}"
        _wuerfel(wurzel, kennung, ordner, rgb)
        eintrag(kennung, ordner)

    for name, rgb in SAEULEN_FARBEN.items():
        kennung, ordner = titel_saeule(name), f"saeule_{name}"
        _saeule(wurzel, kennung, ordner, rgb)
        eintrag(kennung, ordner)

    _licht(wurzel, TITEL_LICHT, "licht_warm")
    eintrag(TITEL_LICHT, "licht_warm")

    if mit_testtiteln:
        rgb = MARKEN_FARBEN[TEST_FARBE]
        for kennung, ordner, par in testtitel():
            if par["art"] == "wuerfel":
                _wuerfel(wurzel, kennung, ordner, rgb, nacht=par["nacht"])
            elif par["art"] == "saeule":
                _saeule(wurzel, kennung, ordner, rgb, nacht=par["nacht"], alpha_unten=par["alpha"])
            else:
                _licht(wurzel, kennung, ordner, staerke=par["staerke"], kern=par["kern"])
            eintrag(kennung, ordner)
    _testordner_loeschen(wurzel, {f"model.{o}" for _t, o, _p in testtitel()} if mit_testtiteln else set())

    # Ohne diesen Block erkennt der Package Builder gar nichts (`paket_bauen.simobjects_schreiben`).
    # Gleiche Werte wie beim Rauch: `StaticObject`, und die Animationsentfernung so groß, dass ein
    # Marker nicht von weitem stehen bleibt.
    teile += ["[General]", "category=StaticObject", "DistanceToNotAnimate=15000", ""]
    (wurzel / "sim.cfg").write_text("\n".join(teile), encoding="utf-8", newline="\r\n")
    return n


if __name__ == "__main__":
    ziel = Path(__file__).resolve().parent / "PackageSources" / "SimObjects" / "Misc" / HERSTELLER_ORDNER
    print(f"{marken_schreiben(ziel)} Titel nach {ziel}")
