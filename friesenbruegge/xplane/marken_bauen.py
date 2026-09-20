"""Erzeugt die FriesenBrügge-Marken für X-Plane 12: Würfel, Lichtsäulen und ein einfaches Licht.

Eigenes Werk (devprops), keine Fremdlizenz, keine Installation beim Piloten. Sie liegen wie die
Rauchsäulen im Plugin unter `Resources/plugins/FriesenBruegge/objekte/` (`XP_EIGEN` in
`app/bruegge_arten.py`); der CI-Workflow `bruegge-xplane.yml` kopiert den ganzen Ordner `objekte/`,
neue Dateien kommen also von allein mit.

Was entsteht (Nutzerwunsch 20.09.2026: *„Würfel in den Friesenfarben. Säule in Weiß + Friesenfarben"*,
*„Würfel ca. 3 m"*, *„ein einfaches Licht"*; nach dem MSFS-Flugtest die Säule als Scheinwerferstrahl):

| Datei                      | was                                                              |
|----------------------------|------------------------------------------------------------------|
| `wuerfel_<farbe>.obj` ×7   | massiver Würfel, Kante 3 m, Ursprung Mitte der Unterseite        |
| `saeule_<farbe>.obj` ×7    | Scheinwerferstrahl: 100 m, Achteck 4 m → 6 m breit, unten hell, oben ausgeblendet |
| `licht_warm.obj`           | ein Punktlicht, warmweiß, mit Glühpunkt und Lichtfleck           |
| `marken.png`               | 4×256, weiß, senkrechter Alpha-Verlauf 0,55 → 0,02 (nur die Säulen) |

Die Farben sind dieselben sechs wie beim Rauch (`FARBEN` aus `rauch_bauen.py`) plus `WEISS`
(„Scheinwerferweiß", warmes, leicht gelbliches Weiß, identisch zur MSFS-Seite). Bei Farben wird nie
gewürfelt — die Farbe trägt Bedeutung.

WIE DIE SÄULE NACH OBEN AUSBLENDET (belegt, nicht geraten)
==========================================================

OBJ8 kennt keine Eckpunktfarben und kein Alpha je Eckpunkt. Zwei Mittel bleiben, und beide sind
in Laminars eigenen Objekten nachzulesen (`Resources/default scenery/sim objects/`):

1. **Höhengradient in der Textur.** Die `v`-Koordinate jedes Eckpunkts ist seine Höhe (0 unten, 1 oben),
   `marken.png` trägt den Alpha-Verlauf. Blenden ist der Vorgabezustand; `ATTR_blend` stellt ihn
   ausdrücklich her — so benutzt es `ships/Whaler_470_01.obj` (`ATTR_no_blend` / `TRIS` /
   `ATTR_blend` / `TRIS`, Zeilen 4536–4539).
2. **Gestapelte Segmente mit abgestuftem `ATTR_emission_rgb`.** Attribute gelten für das folgende
   `TRIS`; Laminars `vr/holodeck/hangar.obj` (Zeilen 56155–56161) setzt genau so je `TRIS`-Abschnitt
   ein eigenes `ATTR_diffuse_rgb`/`ATTR_emission_rgb`. Zwanzig Segmente zu je 5 m, Leuchten je Segment
   `(1 − t)^1,2` mit `t` = Höhe der Segmentmitte / 100 m; der Deckel steht bei `t = 1` und leuchtet nicht.

Die `*_uplight_*m.obj` unter `custom_spills/` sind KEIN Vorbild für die Form: Sie tragen keine
Geometrie, nur ein `LIGHT_PARAM spot_params_sp` (Lichtfleck), und beleuchten damit ihre Umgebung,
statt selbst einen Strahl zu zeichnen. Sie belegen nur, dass ein Objekt ohne Netz ein Licht sein darf.

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

⚠ **Im X-Plane-Flug noch nicht gesehen** (nur gebaut, der Simulator wurde nicht gestartet): ob der
Lichtfleck ausreicht, ob `ATTR_emission_rgb` bei Nacht sichtbar leuchtet, ob der Alpha-Verlauf der
Säule nach oben wirklich ausblendet (Richtung von `v`!) und wie hell 800 cd am Boden wirken. Die
Stärken sind Stellschrauben (`LICHT_CD`, `LICHTFLECK_CD`), keine Messung.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

import importlib.util

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

TEXTUR = "marken.png"

#: Kanten in Metern (Nutzer, 20.09.2026).
WUERFEL_KANTE = 3.0
SAEULE_HOEHE = 100.0

#: Scheinwerferweiß: warmes, leicht gelbliches Weiß, sRGB (Vorgabe des Koordinators, identisch zur
#: MSFS-Seite). EINE Konstante für die weiße Säule UND den weißen Würfel.
WEISS = (255, 240, 200)

#: Säulenbreite (Abstand gegenüberliegender Flächen): unten 4 m, oben 6 m — leicht aufweitend.
SAEULE_BREITE_UNTEN = 4.0
SAEULE_BREITE_OBEN = 6.0

#: Zwanzig Segmente zu 5 m; das Leuchten steht je Segment fest (OBJ8 hat keinen Verlauf im Attribut).
SAEULE_SEGMENTE = 20

#: Deckkraft der Textur unten und oben (Vorgabe des Koordinators) und Abfall des Leuchtens.
SAEULE_ALPHA_UNTEN = 0.55
SAEULE_ALPHA_OBEN = 0.02
SAEULE_EMISSION_EXP = 1.2

#: Höhe der Textur in Pixeln — je feiner, desto glatter der Verlauf; 4 breit genügt, er ist waagerecht gleich.
TEXTUR_HOEHE = 256

#: Wie stark der Würfel von selbst leuchtet (Vielfaches der Farbe) — „leichtes" Emissiv, damit er
#: nachts nicht schwarz wird, tagsüber aber wie ein Würfel und nicht wie eine Lampe aussieht.
WUERFEL_EMISSION = 0.35

#: Warmweiß und Stärke des Einfachlichts. Beide Candela-Werte sind UNGEMESSEN: 500 cd ist, was Laminars
#: eigene Objekte für `spot_params_bb_pm` benutzen; nach dem 2020er Nachttest auf der MSFS-Seite ×1,6
#: heller (5,0 → 8,0), hier gleich skaliert: 500 → 800 und 1000 → 1600. Stellschrauben, keine Messung.
LICHT_RGB = (1.0, 0.84, 0.6)
LICHT_CD = 800
LICHTFLECK_CD = 1600
LICHT_HOEHE = 0.5

#: Alle sieben Farben: die sechs Friesenfarben und Scheinwerferweiß — für Würfel und Säulen.
SAEULEN = {**FARBEN, "weiss": WEISS}
WUERFEL = dict(SAEULEN)


def saeule_emission(t: float) -> float:
    """Leuchten einer Säulenstelle in Höhe t (0 unten, 1 oben): (1 − t)^1,2."""
    return (1.0 - t) ** SAEULE_EMISSION_EXP


def saeule_alpha(t: float) -> float:
    """Deckkraft in Höhe t: linear von unten nach oben."""
    return SAEULE_ALPHA_UNTEN + (SAEULE_ALPHA_OBEN - SAEULE_ALPHA_UNTEN) * t


def _f(farbe: tuple[int, int, int], faktor: float = 1.0) -> tuple[float, float, float]:
    return tuple(round(c / 255.0 * faktor, 4) for c in farbe)


# --------------------------------------------------------------------------- Geometrie

def _mesh(flaechen: list, uv: tuple[float, float] = (0.5, 0.5), *, basis: int = 0,
          hoehe: float | None = None) -> tuple[list[str], list[int]]:
    """Flächen (Normale, Ecken gegen den Uhrzeigersinn von außen gesehen) → VT-Zeilen und Indizes.

    Jede Fläche bekommt ihre EIGENEN Ecken, damit die Normalen je Fläche stimmen (harte Kanten).
    Eine Ecke gehört zu zwei oder drei Flächen mit verschiedenen Normalen.

    Ohne `hoehe` tragen alle Ecken dieselbe UV (`uv`). Mit `hoehe` läuft `v` mit der Höhe der Ecke
    (0 unten, 1 oben) — der Anker des Alpha-Verlaufs der Säule. `basis` ist der Index, ab dem
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
    """Die Säule als gestapelte Abschnitte: `[(t, flächen), …]`, t = Höhe der Mitte (0…1).

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

def _obj_text(titel: str, flaechen: list, uv: tuple[float, float], textur: str | None,
              diffuse: tuple[float, float, float], emission: tuple[float, float, float],
              kulling: bool) -> str:
    vt, idx = _mesh(flaechen, uv)
    zeilen = ["I", "800", "OBJ", f"# {titel}", "", f"TEXTURE\t{textur}" if textur else "TEXTURE\t",
              f"POINT_COUNTS\t{len(vt)} 0 0 {len(idx)}", ""]
    zeilen += vt
    zeilen.append("")
    for i in range(0, len(idx), 10):                  # zehn Indizes je Zeile, der Rest einzeln
        stueck = idx[i:i + 10]
        if len(stueck) == 10:
            zeilen.append("IDX10\t" + " ".join(map(str, stueck)))
        else:
            zeilen += [f"IDX\t{j}" for j in stueck]
    zeilen.append("")
    if not kulling:
        zeilen.append("ATTR_no_cull")
    zeilen.append("ATTR_diffuse_rgb\t{:.4f} {:.4f} {:.4f}".format(*diffuse))
    zeilen.append("ATTR_emission_rgb\t{:.4f} {:.4f} {:.4f}".format(*emission))
    zeilen.append(f"TRIS\t0 {len(idx)}")
    zeilen.append("")
    return "\n".join(zeilen)


def wuerfel_schreiben(pfad: Path, farbe: tuple[int, int, int]) -> None:
    pfad.write_text(_obj_text(
        "Die FriesenBruegge -- Wuerfel, Kante 3 m, Friesenfarbe.",
        wuerfel_flaechen(WUERFEL_KANTE), (0.5, 0.5), None,
        _f(farbe), _f(farbe, WUERFEL_EMISSION), kulling=True),
        encoding="utf-8", newline="\n")


def saeule_schreiben(pfad: Path, farbe: tuple[int, int, int]) -> None:
    """Ein Scheinwerferstrahl: 21 `TRIS`-Abschnitte, `v` = Höhe, Leuchten je Abschnitt abgestuft."""
    vt, idx, tris = [], [], []
    for t, flaechen in saeule_abschnitte():
        v, i = _mesh(flaechen, basis=len(vt), hoehe=SAEULE_HOEHE)
        tris.append((len(idx), len(i), t))
        vt += v
        idx += [x for x in i]
    zeilen = ["I", "800", "OBJ",
              "# Die FriesenBruegge -- Lichtstrahl, 100 m, unten 4 m, oben 6 m breit, nach oben ausgeblendet.",
              "# v = Hoehe (0 unten, 1 oben): marken.png traegt den Alpha-Verlauf; ATTR_emission_rgb stuft je Abschnitt ab.",
              "", f"TEXTURE\t{TEXTUR}", f"POINT_COUNTS\t{len(vt)} 0 0 {len(idx)}", ""]
    zeilen += vt
    zeilen.append("")
    for i in range(0, len(idx), 10):
        stueck = idx[i:i + 10]
        if len(stueck) == 10:
            zeilen.append("IDX10\t" + " ".join(map(str, stueck)))
        else:
            zeilen += [f"IDX\t{j}" for j in stueck]
    zeilen += ["", "ATTR_no_cull", "ATTR_blend", "ATTR_diffuse_rgb\t{:.4f} {:.4f} {:.4f}".format(*_f(farbe))]
    for start, anzahl, t in tris:
        zeilen.append("ATTR_emission_rgb\t{:.4f} {:.4f} {:.4f}".format(*_f(farbe, saeule_emission(t))))
        zeilen.append(f"TRIS\t{start} {anzahl}")
    zeilen.append("")
    pfad.write_text("\n".join(zeilen), encoding="utf-8", newline="\n")


def licht_schreiben(pfad: Path) -> None:
    """Ein Punktlicht — Glühpunkt und Lichtfleck. Keine Geometrie (wie Laminars `elevated_edge_*`)."""
    r, g, b = LICHT_RGB
    pfad.write_text("\n".join([
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
        f"LIGHT_PARAM\tspot_params_bb_pm\t0 {LICHT_HOEHE} 0 {r} {g} {b} {LICHT_CD}cd 0 0 0 1",
        # R G B A INTENSITY DX DY DZ WIDTH -- nach unten, Kegel von 120 Grad (WIDTH = cos des halben Winkels).
        f"LIGHT_PARAM\tspot_params_sp_pm\t0 {LICHT_HOEHE} 0 {r} {g} {b} 1 {LICHTFLECK_CD}cd 0 -1 0 0.5",
        "",
    ]), encoding="utf-8", newline="\n")


def textur_schreiben(pfad: Path) -> None:
    """4×256, weiß, mit senkrechtem Alpha-Verlauf 0,55 (unten) → 0,02 (oben); PNG ohne Fremdbibliothek.

    OBJ8-Texturen haben ihren Ursprung unten links: die letzte Bildzeile ist `v = 0`, die erste `v = 1`.
    """
    b, h = 4, TEXTUR_HOEHE
    zeilen = []
    for y in range(h):
        t = (h - 1 - y) / (h - 1)                       # Zeile 0 = oben = t 1
        alpha = round(saeule_alpha(t) * 255)
        zeilen.append(b"\x00" + bytes([255, 255, 255, alpha]) * b)
    roh = b"".join(zeilen)

    def chunk(art: bytes, daten: bytes) -> bytes:
        c = struct.pack(">I", len(daten)) + art + daten
        return c + struct.pack(">I", zlib.crc32(art + daten) & 0xFFFFFFFF)

    pfad.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", b, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(roh, 9))
                     + chunk(b"IEND", b""))


def main() -> None:
    ZIEL.mkdir(exist_ok=True)
    textur_schreiben(ZIEL / TEXTUR)
    print(f"  {TEXTUR:24} {(ZIEL / TEXTUR).stat().st_size:7} Bytes")
    for name, farbe in WUERFEL.items():
        wuerfel_schreiben(ZIEL / f"wuerfel_{name}.obj", farbe)
        print(f"  wuerfel_{name}.obj".ljust(26) + f"#{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")
    for name, farbe in SAEULEN.items():
        saeule_schreiben(ZIEL / f"saeule_{name}.obj", farbe)
        print(f"  saeule_{name}.obj".ljust(26) + f"#{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")
    licht_schreiben(ZIEL / "licht_warm.obj")
    print("  licht_warm.obj")


if __name__ == "__main__":
    main()
