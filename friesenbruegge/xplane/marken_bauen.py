"""Erzeugt die FriesenBrügge-Marken für X-Plane 12: Würfel, Lichtsäulen und ein einfaches Licht.

Eigenes Werk (devprops), keine Fremdlizenz, keine Installation beim Piloten. Sie liegen wie die
Rauchsäulen im Plugin unter `Resources/plugins/FriesenBruegge/objekte/` (`XP_EIGEN` in
`app/bruegge_arten.py`); der CI-Workflow `bruegge-xplane.yml` kopiert den ganzen Ordner `objekte/`,
neue Dateien kommen also von allein mit.

Was entsteht (Nutzerwunsch 20.09.2026: *„Würfel in den Friesenfarben. Säule in Weiß + Friesenfarben"*,
*„Würfel ca. 3 m"*, *„ein einfaches Licht"*; nach dem MSFS-Flugtest die Säule als Scheinwerferstrahl):

| Datei                        | was                                                              |
|------------------------------|------------------------------------------------------------------|
| `wuerfel_<farbe>.obj` ×7     | massiver Würfel, Kante 3 m, Ursprung Mitte der Unterseite        |
| `saeule_<farbe>.obj` ×7      | Scheinwerferstrahl: 100 m, Achteck 4 m → 6 m breit, unten hell, oben ausgeblendet |
| `licht_warm.obj`             | ein Punktlicht, warmweiß, mit Glühpunkt und Lichtfleck           |
| `marken.png`                 | 4×256, weiß, senkrechter Alpha-Verlauf 0,55 → 0,02 (Albedo der Säulen) |
| `marken_weiss.png`           | 4×4, opak weiß (Albedo der Würfel; die Farbe kommt aus `ATTR_diffuse_rgb`) |
| `wuerfel_<farbe>_LIT.png` ×7 | 4×4, die Leuchtfarbe (Nacht)                                     |
| `saeule_<farbe>_LIT.png` ×7  | 4×256, Leuchtfarbe mit Verlauf `(1 − t)^1,2` (Nacht)             |
| `test_*.obj`                 | Testleiter für die Nachthelligkeit (`MIT_TESTOBJEKTEN`)          |

Die Farben sind dieselben sechs wie beim Rauch (`FARBEN` aus `rauch_bauen.py`) plus `WEISS`
(„Scheinwerferweiß", warmes, leicht gelbliches Weiß, identisch zur MSFS-Seite). Bei Farben wird nie
gewürfelt — die Farbe trägt Bedeutung.

WARUM SIE NACHTS DUNKEL WAREN (Flug 20.09.2026) — was belegt ist und was nicht
==============================================================================

**Belegt:** `ATTR_emission_rgb` ist in X-Plane 12 veraltet. Die OBJ8-Spezifikation
(developer.x-plane.com/article/obj8-file-format-specification/) führt es als
*„[deprecated] ATTR_emission_rgb <r> <g> <b>"* (Ambient und Specular sogar als *„deprecated and
ignored"*). Das Leuchten bei Nacht kommt aus der **LIT-Textur**: *„The '_LIT' (emissive) texture for the
object, specified via the TEXTURE_LIT command"* (ebd.), und sie wird zum Tageslicht **addiert**:
*„albedo texture * external light level + emissive texture * internal light level"*
(developer.x-plane.com/article/additive-lighting/). Die bisherigen Objekte hatten **keine**
`TEXTURE_LIT` — bei Nacht war da nichts, was leuchten konnte.

**Belegt:** Die Helligkeit der LIT-Textur setzt `GLOBAL_luminance`: *„Sets the nits value for the lit
texture used for rendering."* und *„The baseline luminance for the LIT texture, in nts. Value is
clamped at 65530."* (OBJ8-Spezifikation). Alle 149 Objekte unter `Resources/default scenery/sim objects/`,
die `GLOBAL_luminance` setzen, haben auch eine `TEXTURE_LIT` (nachgezählt, keines ohne). Werte dort:
1000 (119×), 150 (12×), 500 (5×), 2000 (3×), 120 (3×), 30 (3×), 75 (2×), 100, **2500** (1×,
`landscape/apron_light.obj` — der höchste, den Laminar selbst setzt).

**Belegt:** Eine Normalentextur (PBR) ist für die LIT-Textur nicht nötig: 89 der 637 Laminar-Objekte
mit `TEXTURE_LIT` haben keine `TEXTURE_NORMAL` (nachgezählt).

**Belegt (Flug):** Bei Tag sind die Säulen in Ordnung (weiße Albedo-Textur × `ATTR_diffuse_rgb`), die
Würfel waren ohne Textur fast schwarz. Darum haben die Würfel jetzt dieselbe Albedo (`marken_weiss.png`)
und dieselbe Farbgebung wie die Säulen — was dort tagsüber funktioniert, wird nicht neu erfunden.

**Gemessen (Testleiter im X-Plane-Flug, nachts, 20.09.2026 — Nutzer und Bildmessung):** Jede Stufe
`GLOBAL_luminance` ≥ 2500 **überbelichtet** und der Bloom flutet die Umgebung. Ohne `GLOBAL_luminance` trifft die
LIT-Textur die Friesenfarbe genau.

| Stufe (Signalorange-Säule/-Würfel) | Luminanz im Bild | Farbe                 | Aufhellung neben der Säule |
|------------------------------------|------------------|-----------------------|----------------------------|
| `Lstd` (**ohne** `GLOBAL_luminance`) | **125**          | (233, 104, 15) — echt | **49**                     |
| `L2500`                            | ~250             | gelb-weiß, überbelichtet | 73                      |
| `L40000`                           | ~250             | gelb-weiß, überbelichtet | 220                     |
| Bezug: Runway-Feuer des Nutzers    | ~144–153         | orange Punkte         | —                          |
| Bezug: Hintergrund                 | —                | —                     | 24                         |

Der Nutzer wählte die dunkelste Stufe („wahrscheinlich reicht das dunkelste von allen dreien"), beim Licht
„höchstens das zweitdunkelste". **Endgültig:** Würfel und Säulen **ohne** `GLOBAL_luminance` (die Leuchtwirkung kommt
allein aus den LIT-Texturen), das Licht mit 4500 cd (Laminars Randfeuer `edge_w`, zweitdunkelste Stufe der
Lichtleiter) und 9000 cd im Lichtfleck. **Die Standardhelligkeit ohne `GLOBAL_luminance` ist also die richtige** — die
frühere Vermutung „10000 Nits" war falsch. Die Testleiter ist mit `MIT_TESTOBJEKTEN = False` abgeschaltet und
im Repo gelöscht; wer sie braucht, setzt den Schalter auf `True` und lässt den Generator laufen.

**Weiterhin unbelegt:** ob die halbtransparente Säule (`ATTR_blend`) das Leuchten mit dem Albedo-Alpha multipliziert
(dann fällt sie nach oben doppelt ab) und ob PNG-Farben der LIT-Textur als sRGB gelesen werden — der Flug zeigte
die Farbe als korrekt, also genügt der Stand.

WIE DIE SÄULE NACH OBEN AUSBLENDET
==================================

OBJ8 kennt keine Eckpunktfarben und kein Alpha je Eckpunkt. Die `v`-Koordinate jedes Eckpunkts ist seine
Höhe (0 unten, 1 oben), und zwei Texturen tragen den Verlauf: `marken.png` das Alpha (0,55 → 0,02), die
`saeule_<farbe>_LIT.png` das Leuchten (`(1 − t)^1,2`). Blenden ist der Vorgabezustand (*„Blending (default on)"*,
OBJ8-Spezifikation); `ATTR_blend` stellt ihn ausdrücklich her, so wie `ships/Whaler_470_01.obj`
(`ATTR_no_blend` / `TRIS` / `ATTR_blend` / `TRIS`, Zeilen 4536–4539). Die frühere Abstufung mit zwanzig
Abschnitten und `ATTR_emission_rgb` je Abschnitt (Vorbild `vr/holodeck/hangar.obj`) ist mit dem veralteten
Attribut entfallen — der Verlauf steckt jetzt in der Textur, die Säule ist ein einziger Körper.

⚠ **Die Breite ist der Abstand gegenüberliegender FLÄCHEN** (Flach-zu-flach), nicht der Ecken.

WOHER DIE LICHTZEILE STAMMT (nachgesehen, nicht geraten)
========================================================

X-Plane kennt seine Lichter über `Resources/bitmaps/world/lites/lights.txt`. Dort stehen zwei
parametrisierbare Vorlagen, die genau das leisten, was hier gebraucht wird:

    LIGHT_PARAM_DEF  spot_params_bb_pm  8   R G B  INTENSITY  DX DY DZ  WIDTH      (Zeile 1235)
    BILLBOARD_HW     spot_params_bb_pm      R G B 1.0 INTENSITY 2 5 2 DX DY DZ WIDTH 0 0 0 0
    LIGHT_PARAM_DEF  spot_params_sp_pm  9   R G B A INTENSITY  DX DY DZ  WIDTH      (Zeile 1233)
    SPILL_HW_DIR     spot_params_sp_pm      R G B A INTENSITY DX DY DZ WIDTH  0

Die erste ist ein Glühpunkt (Billboard), die zweite ein echter Lichtfleck. Laminars eigene Objekte
benutzen die erste in genau der Form `LIGHT_PARAM spot_params_bb_pm x y z 1 0 0 500cd 0 0 0 1` —
Richtung `0 0 0` und `WIDTH 1` heißt: ringsum sichtbar (omni). Die zweite in derselben Zählweise
wie die `*_uplight_*m.obj` unter `default scenery/sim objects/custom_spills/`, deren Spill
`WIDTH 0.5` trägt. Die Zahl der Parameter je Zeile stimmt mit der `LIGHT_PARAM_DEF` überein —
das prüft `tests/test_xplane_marken.py` gegen die `lights.txt` der Installation, wenn sie da ist.

**Maßstab für die Stärke (belegt, `lights.txt` Zeile 572):** Laminars weißes Pistenrandfeuer
`BILLBOARD_HW edge_w 1.39 0.91 0.77 1 4500cd …`, dazu die Hindernisfeuer `wind_turbine_obs` (3000 cd) und
`smokestack_obs` (2500 cd); Flutlichter `spot_params_bb_day_pm` 20000 cd, die Vorfeldlampe
`apron_light_billboard` 150000 cd. Die Leiter (2000 … 128000 cd) überdeckte genau diese Spanne, mit dem
Randfeuer (4500) als Bezugsrung. **Endgültig 4500 cd** (Glühpunkt), der Lichtfleck 9000 cd: Der Nutzer wählte in der
Nachtprüfung „höchstens das zweitdunkelste" — genau das Randfeuer.
"""

from __future__ import annotations

import importlib.util
import math
import struct
import zlib
from pathlib import Path

HIER = Path(__file__).resolve().parent


def _friesenfarben() -> dict[str, tuple[int, int, int]]:
    """Dieselben Friesenfarben wie beim Rauch — über die Dateispezifikation geladen.

    ⚠ NICHT `from rauch_bauen import ...`: Es gibt zwei Dateien dieses Namens (hier und in
    `msfs-rauch/`), und welche in `sys.modules` steckt, hängt vom Aufrufer ab.
    """
    spec = importlib.util.spec_from_file_location("xplane_rauch_bauen", HIER / "rauch_bauen.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return dict(modul.FARBEN)


FARBEN = _friesenfarben()
ZIEL = HIER / "objekte"

#: Albedo der Säulen (mit Alpha-Verlauf) und der Würfel (opak weiß).
TEXTUR = "marken.png"
TEXTUR_WEISS = "marken_weiss.png"

#: Kanten in Metern (Nutzer, 20.09.2026).
WUERFEL_KANTE = 3.0
SAEULE_HOEHE = 100.0

#: Scheinwerferweiß: warmes, leicht gelbliches Weiß, sRGB (Vorgabe des Koordinators, identisch zur
#: MSFS-Seite). EINE Konstante für die weiße Säule UND den weißen Würfel.
WEISS = (255, 240, 200)

#: Säulenbreite (Abstand gegenüberliegender Flächen): unten 4 m, oben 6 m — leicht aufweitend.
SAEULE_BREITE_UNTEN = 4.0
SAEULE_BREITE_OBEN = 6.0

#: Die Säule ist EIN Körper; der Verlauf steckt in den Texturen (kein Emissiv je Abschnitt mehr).
SAEULE_SEGMENTE = 1

#: Deckkraft der Textur unten und oben (Vorgabe des Koordinators) und Abfall des Leuchtens.
SAEULE_ALPHA_UNTEN = 0.55
SAEULE_ALPHA_OBEN = 0.02
SAEULE_EMISSION_EXP = 1.2

#: Höhe der Textur in Pixeln — je feiner, desto glatter der Verlauf; 4 breit genügt, er ist waagerecht gleich.
TEXTUR_HOEHE = 256

#: ⭐ NACHTHELLIGKEIT: KEINE `GLOBAL_luminance`-ZEILE (`None`). Gemessen in der Testleiter: Jede Stufe ab 2500 Nits
#: überbelichtet und flutet die Umgebung mit Bloom; ohne die Zeile trifft die LIT-Textur die Friesenfarbe (Luminanz 125,
#: Runway-Feuer ~150). Die Leuchtwirkung kommt allein aus den LIT-Texturen. Ein Wert hier schaltet die Zeile wieder ein.
WUERFEL_NITS = None
SAEULE_NITS = None

#: Warmweiß und Stärke des Einfachlichts. Maßstab: Laminars weißes Pistenrandfeuer `edge_w` hat 4500 cd
#: (`lights.txt` Zeile 572). Nach der Nachtprüfung (Nutzer: „höchstens das zweitdunkelste") genau dieser Wert;
#: der Lichtfleck doppelt.
LICHT_RGB = (1.0, 0.84, 0.6)
LICHT_CD = 4500
LICHTFLECK_FAKTOR = 2
LICHTFLECK_CD = LICHT_CD * LICHTFLECK_FAKTOR
LICHT_HOEHE = 0.5

#: ⭐ Die Testleiter für die Nachthelligkeit — mit einem Wort abschaltbar. Ist der Schalter `False` (Stand nach der
#: Nachtprüfung), schreibt der Generator keine `test_*`-Dateien und löscht vorhandene.
MIT_TESTOBJEKTEN = False
TEST_NITS = (2500, 5000, 10000, 20000, 40000)
#: Lichtleiter in Candela: 2000 (Hindernisfeuer-Klasse) … 128000 (Vorfeldlampe); 4500 ist Laminars Randfeuer.
TEST_CD = (2000, 4500, 8000, 32000, 128000)
TEST_FARBE = "signalorange"

#: Alle sieben Farben: die sechs Friesenfarben und Scheinwerferweiß — für Würfel und Säulen.
SAEULEN = {**FARBEN, "weiss": WEISS}
WUERFEL = dict(SAEULEN)


def _f(farbe: tuple[int, int, int], faktor: float = 1.0) -> tuple[float, float, float]:
    return tuple(round(c / 255.0 * faktor, 4) for c in farbe)


def lit_farbe(farbe: tuple[int, int, int]) -> tuple[int, int, int]:
    """Die Leuchtfarbe: der Farbton der Friesenfarbe, hochgezogen auf volle Helligkeit (größter Kanal = 255).

    Ein Leuchtkörper ist nachts nicht so dunkel wie sein Lack — Navy (25, 29, 83) als Emission wäre schwarz.
    Die Nits (`GLOBAL_luminance`) sagen, WIE hell; die Textur sagt nur, WELCHE Farbe.
    """
    m = max(farbe)
    return tuple(round(c * 255.0 / m) for c in farbe)


def saeule_emission(t: float) -> float:
    """Leuchten einer Säulenstelle in Höhe t (0 unten, 1 oben): (1 − t)^1,2."""
    return (1.0 - t) ** SAEULE_EMISSION_EXP


def saeule_alpha(t: float) -> float:
    """Deckkraft in Höhe t: linear von unten nach oben."""
    return SAEULE_ALPHA_UNTEN + (SAEULE_ALPHA_OBEN - SAEULE_ALPHA_UNTEN) * t


# --------------------------------------------------------------------------- Geometrie

def _mesh(flaechen: list, uv: tuple[float, float] = (0.5, 0.5), *, basis: int = 0,
          hoehe: float | None = None) -> tuple[list[str], list[int]]:
    """Flächen (Normale, Ecken gegen den Uhrzeigersinn von außen gesehen) → VT-Zeilen und Indizes.

    Jede Fläche bekommt ihre EIGENEN Ecken, damit die Normalen je Fläche stimmen (harte Kanten).
    Eine Ecke gehört zu zwei oder drei Flächen mit verschiedenen Normalen.

    Ohne `hoehe` tragen alle Ecken dieselbe UV (`uv`). Mit `hoehe` läuft `v` mit der Höhe der Ecke
    (0 unten, 1 oben) — der Anker des Verlaufs der Säule. `basis` ist der Index, ab dem
    gezählt wird (mehrere Abschnitte teilen sich eine Eckpunktliste).
    """
    vt, idx = [], []
    for normale, ecken in flaechen:
        erste = basis + len(vt)
        for x, y, z in ecken:
            v = uv[1] if hoehe is None else y / hoehe
            vt.append(f"VT\t{x:.4f}\t{y:.4f}\t{z:.4f}\t{normale[0]:.4f}\t{normale[1]:.4f}\t"
                      f"{normale[2]:.4f}\t{uv[0]:.4f}\t{v:.4f}")
        for i in range(1, len(ecken) - 1):          # Fächer: 4 Ecken → 2 Dreiecke, 8 → 6
            idx += [erste, erste + i, erste + i + 1]
    return vt, idx


def wuerfel_flaechen(kante: float) -> list:
    """Ein Würfel, Ursprung Mitte der Unterseite; X-Plane: +Y oben, -Z Norden."""
    h = kante / 2.0
    k = kante
    return [
        ((0.0, 0.0, 1.0),  [(-h, 0, h), (h, 0, h), (h, k, h), (-h, k, h)]),     # Süden (+Z)
        ((0.0, 0.0, -1.0), [(h, 0, -h), (-h, 0, -h), (-h, k, -h), (h, k, -h)]),  # Norden (-Z)
        ((1.0, 0.0, 0.0),  [(h, 0, h), (h, 0, -h), (h, k, -h), (h, k, h)]),      # Osten (+X)
        ((-1.0, 0.0, 0.0), [(-h, 0, -h), (-h, 0, h), (-h, k, h), (-h, k, -h)]),  # Westen (-X)
        ((0.0, 1.0, 0.0),  [(-h, k, h), (h, k, h), (h, k, -h), (-h, k, -h)]),    # oben
        ((0.0, -1.0, 0.0), [(-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h)]),    # unten
    ]


def saeule_abschnitte(hoehe: float = SAEULE_HOEHE, unten: float = SAEULE_BREITE_UNTEN,
                      oben: float = SAEULE_BREITE_OBEN, segmente: int = SAEULE_SEGMENTE,
                      ecken: int = 8) -> list[tuple[float, list]]:
    """Die Säule als Abschnitte: `[(t, flächen), …]`, t = Höhe der Mitte (0…1).

    Ein regelmäßiges n-Eck-Prisma (Vorgabe Achteck), das nach oben leicht aufweitet; Ursprung Mitte der
    Unterseite. `unten`/`oben` sind Abstände gegenüberliegender FLÄCHEN. Der letzte Abschnitt ist der
    Deckel (t = 1).

    Die Flächennormale steht nicht mehr waagerecht: Weitet die Säule auf, neigt sich jede Seitenfläche
    minimal nach unten — n = (cos m, −Steigung, sin m), normiert.
    """
    steigung = (oben - unten) / 2.0 / hoehe            # Zuwachs des Abstands zur Achse je Meter Höhe

    def ring(h: float) -> list[tuple[float, float]]:
        apothem = (unten + (oben - unten) * h / hoehe) / 2.0
        r = apothem / math.cos(math.pi / ecken)
        return [(r * math.cos(2 * math.pi * i / ecken), r * math.sin(2 * math.pi * i / ecken))
                for i in range(ecken)]

    abschnitte = []
    for k in range(segmente):
        h0, h1 = hoehe * k / segmente, hoehe * (k + 1) / segmente
        r0, r1 = ring(h0), ring(h1)
        flaechen = []
        for i in range(ecken):
            j = (i + 1) % ecken
            mitte = 2 * math.pi * (i + 0.5) / ecken
            n = (math.cos(mitte), -steigung, math.sin(mitte))
            laenge = math.sqrt(sum(c * c for c in n))
            n = tuple(c / laenge for c in n)
            # Von außen gesehen gegen den Uhrzeigersinn (Kreiswinkel steigt in X-Z im Uhrzeigersinn,
            # darum j vor i): unten j → unten i → oben i → oben j.
            flaechen.append((n, [(r0[j][0], h0, r0[j][1]), (r0[i][0], h0, r0[i][1]),
                                 (r1[i][0], h1, r1[i][1]), (r1[j][0], h1, r1[j][1])]))
        abschnitte.append(((k + 0.5) / segmente, flaechen))
    deckel = [(x, hoehe, z) for x, z in reversed(ring(hoehe))]
    abschnitte.append((1.0, [((0.0, 1.0, 0.0), deckel)]))
    return abschnitte


# --------------------------------------------------------------------------- Dateien

def _indexzeilen(idx: list[int]) -> list[str]:
    zeilen = []
    for i in range(0, len(idx), 10):                  # zehn Indizes je Zeile, der Rest einzeln
        stueck = idx[i:i + 10]
        if len(stueck) == 10:
            zeilen.append("IDX10\t" + " ".join(map(str, stueck)))
        else:
            zeilen += [f"IDX\t{j}" for j in stueck]
    return zeilen


def _kopf(titel: str, textur: str, lit: str, nits: int | None) -> list[str]:
    """Kopf mit Albedo, LIT-Textur und — wenn gesetzt — der Helligkeit in Nits.

    Ohne `nits` (`None`) steht KEINE `GLOBAL_luminance`-Zeile: dann gilt die Standardhelligkeit des Simulators —
    die gemessen richtige (s. Kopfkommentar).
    """
    zeilen = ["I", "800", "OBJ", f"# {titel}", "", f"TEXTURE\t{textur}", f"TEXTURE_LIT\t{lit}"]
    if nits is not None:
        zeilen.append(f"GLOBAL_luminance\t{nits}")
    return zeilen


def wuerfel_text(name: str, farbe: tuple[int, int, int], nits: int | None) -> str:
    vt, idx = _mesh(wuerfel_flaechen(WUERFEL_KANTE))
    zeilen = _kopf("Die FriesenBruegge -- Wuerfel, Kante 3 m, Friesenfarbe.", TEXTUR_WEISS,
                   f"wuerfel_{name}_LIT.png", nits)
    zeilen += [f"POINT_COUNTS\t{len(vt)} 0 0 {len(idx)}", ""] + vt + [""] + _indexzeilen(idx)
    zeilen += ["", "ATTR_diffuse_rgb\t{:.4f} {:.4f} {:.4f}".format(*_f(farbe)), f"TRIS\t0 {len(idx)}", ""]
    return "\n".join(zeilen)


def saeule_text(name: str, farbe: tuple[int, int, int], nits: int | None) -> str:
    """Ein Scheinwerferstrahl: ein Körper, `v` = Höhe; Alpha (Albedo) und Leuchten (LIT) laufen mit der Höhe aus."""
    vt, idx = [], []
    for _, flaechen in saeule_abschnitte():
        v, i = _mesh(flaechen, basis=len(vt), hoehe=SAEULE_HOEHE)
        vt += v
        idx += i
    zeilen = _kopf("Die FriesenBruegge -- Lichtstrahl, 100 m, unten 4 m, oben 6 m breit, nach oben ausgeblendet.",
                   TEXTUR, f"saeule_{name}_LIT.png", nits)
    zeilen += [f"POINT_COUNTS\t{len(vt)} 0 0 {len(idx)}", ""] + vt + [""] + _indexzeilen(idx)
    zeilen += ["", "ATTR_no_cull", "ATTR_blend", "ATTR_diffuse_rgb\t{:.4f} {:.4f} {:.4f}".format(*_f(farbe)),
               f"TRIS\t0 {len(idx)}", ""]
    return "\n".join(zeilen)


def licht_text(cd: int = LICHT_CD, fleck_cd: int | None = None) -> str:
    """Ein Punktlicht — Glühpunkt und Lichtfleck. Keine Geometrie (wie Laminars `elevated_edge_*`)."""
    r, g, b = LICHT_RGB
    fleck = cd * LICHTFLECK_FAKTOR if fleck_cd is None else fleck_cd
    return "\n".join([
        "I", "800", "OBJ",
        "# Die FriesenBruegge -- einfaches Licht, warmweiss. Kein Modell, nur zwei Lichtzeilen.",
        "# spot_params_bb_pm = Glueh-Punkt (Billboard), spot_params_sp_pm = Lichtfleck; beide aus",
        "# Resources/bitmaps/world/lites/lights.txt (LIGHT_PARAM_DEF), Zeilenform wie in Laminars Objekten.",
        "",
        "TEXTURE\t",
        "POINT_COUNTS\t0 0 0 0",
        "",
        "ATTR_LOD\t0 10000",
        # R G B INTENSITY DX DY DZ WIDTH -- Richtung 0 0 0 und WIDTH 1 = ringsum sichtbar.
        f"LIGHT_PARAM\tspot_params_bb_pm\t0 {LICHT_HOEHE} 0 {r} {g} {b} {cd}cd 0 0 0 1",
        # R G B A INTENSITY DX DY DZ WIDTH -- nach unten, Kegel von 120 Grad (WIDTH = cos des halben Winkels).
        f"LIGHT_PARAM\tspot_params_sp_pm\t0 {LICHT_HOEHE} 0 {r} {g} {b} 1 {fleck}cd 0 -1 0 0.5",
        "",
    ])


def _nits(wert: int | None) -> str:
    return "ohne GLOBAL_luminance" if wert is None else f"{wert} nits"


def _schreiben(pfad: Path, text: str) -> None:
    pfad.write_text(text, encoding="utf-8", newline="\n")


def _png(pfad: Path, breite: int, hoehe: int, pixel, rgba: bool) -> None:
    """Ein PNG ohne Fremdbibliothek. `pixel(x, y)` gibt (r, g, b[, a]) zurück; Zeile 0 ist OBEN."""
    zeilen = [b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(breite)) for y in range(hoehe)]
    roh = b"".join(zeilen)

    def chunk(art: bytes, daten: bytes) -> bytes:
        c = struct.pack(">I", len(daten)) + art + daten
        return c + struct.pack(">I", zlib.crc32(art + daten) & 0xFFFFFFFF)

    pfad.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 6 if rgba else 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(roh, 9))
                     + chunk(b"IEND", b""))


def _t(y: int, hoehe: int) -> float:
    """Höhe t einer Bildzeile: OBJ8-Texturen haben ihren Ursprung unten links — die letzte Zeile ist v = 0."""
    return (hoehe - 1 - y) / (hoehe - 1)


def textur_schreiben(pfad: Path) -> None:
    """4×256, weiß, mit senkrechtem Alpha-Verlauf 0,55 (unten) → 0,02 (oben) — die Albedo der Säulen."""
    _png(pfad, 4, TEXTUR_HOEHE,
         lambda x, y: (255, 255, 255, round(saeule_alpha(_t(y, TEXTUR_HOEHE)) * 255)), rgba=True)


def weiss_schreiben(pfad: Path) -> None:
    """4×4, opak weiß — die Albedo der Würfel (die Farbe kommt aus `ATTR_diffuse_rgb`, wie bei den Säulen)."""
    _png(pfad, 4, 4, lambda x, y: (255, 255, 255), rgba=False)


def wuerfel_lit_schreiben(pfad: Path, farbe: tuple[int, int, int]) -> None:
    """4×4, die Leuchtfarbe (Nacht)."""
    f = lit_farbe(farbe)
    _png(pfad, 4, 4, lambda x, y: f, rgba=False)


def saeule_lit_schreiben(pfad: Path, farbe: tuple[int, int, int]) -> None:
    """4×256, Leuchtfarbe mit dem Verlauf (1 − t)^1,2 — unten voll, oben null."""
    f = lit_farbe(farbe)
    _png(pfad, 4, TEXTUR_HOEHE,
         lambda x, y: tuple(round(c * saeule_emission(_t(y, TEXTUR_HOEHE))) for c in f), rgba=False)


def testobjekte_schreiben() -> list[str]:
    """Die Testleiter: Würfel und Säule in Signalorange bei 2500 … 40000 Nits, dazu `Lstd` ohne `GLOBAL_luminance`
    (die Standardhelligkeit), und das Licht bei 2000 … 128000 cd. Sie benutzen die Texturen der echten Objekte."""
    farbe = FARBEN[TEST_FARBE]
    namen = []
    for nits in (*TEST_NITS, None):
        kennung = "Lstd" if nits is None else f"L{nits}"
        _schreiben(ZIEL / f"test_wuerfel_{kennung}.obj", wuerfel_text(TEST_FARBE, farbe, nits))
        _schreiben(ZIEL / f"test_saeule_{kennung}.obj", saeule_text(TEST_FARBE, farbe, nits))
        namen += [f"test_wuerfel_{kennung}.obj", f"test_saeule_{kennung}.obj"]
    for cd in TEST_CD:
        _schreiben(ZIEL / f"test_licht_L{cd}.obj", licht_text(cd))
        namen.append(f"test_licht_L{cd}.obj")
    return namen


def main() -> None:
    ZIEL.mkdir(exist_ok=True)
    textur_schreiben(ZIEL / TEXTUR)
    weiss_schreiben(ZIEL / TEXTUR_WEISS)
    print(f"  {TEXTUR:24} {(ZIEL / TEXTUR).stat().st_size:7} Bytes")
    for name, farbe in WUERFEL.items():
        _schreiben(ZIEL / f"wuerfel_{name}.obj", wuerfel_text(name, farbe, WUERFEL_NITS))
        wuerfel_lit_schreiben(ZIEL / f"wuerfel_{name}_LIT.png", farbe)
        print(f"  wuerfel_{name}.obj".ljust(26) + f"#{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}  {_nits(WUERFEL_NITS)}")
    for name, farbe in SAEULEN.items():
        _schreiben(ZIEL / f"saeule_{name}.obj", saeule_text(name, farbe, SAEULE_NITS))
        saeule_lit_schreiben(ZIEL / f"saeule_{name}_LIT.png", farbe)
        print(f"  saeule_{name}.obj".ljust(26) + f"#{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}  {_nits(SAEULE_NITS)}")
    _schreiben(ZIEL / "licht_warm.obj", licht_text())
    print(f"  licht_warm.obj".ljust(26) + f"{LICHT_CD} cd / Fleck {LICHTFLECK_CD} cd")
    # Die Testleiter: ein Wort steuert sie. Abgeschaltet werden vorhandene test_*-Dateien gelöscht.
    if MIT_TESTOBJEKTEN:
        for n in testobjekte_schreiben():
            print(f"  {n}")
    else:
        for p in ZIEL.glob("test_*.obj"):
            p.unlink()
            print(f"  {p.name} gelöscht")


if __name__ == "__main__":
    main()
