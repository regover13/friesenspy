"""Erzeugt die FriesenBrügge-Marken für X-Plane 12: Würfel, Lichtsäulen und ein einfaches Licht.

Eigenes Werk (devprops), keine Fremdlizenz, keine Installation beim Piloten. Sie liegen wie die
Rauchsäulen im Plugin unter `Resources/plugins/FriesenBruegge/objekte/` (`XP_EIGEN` in
`app/bruegge_arten.py`); der CI-Workflow `bruegge-xplane.yml` kopiert den ganzen Ordner `objekte/`,
neue Dateien kommen also von allein mit.

Was entsteht (Nutzerwunsch 20.09.2026: *„Würfel in den Friesenfarben. Säule in Weiß + Friesenfarben"*,
*„Würfel ca. 3 m, Säule ca. 100 m hoch und schmal"*, *„ein einfaches Licht"*):

| Datei                      | was                                                              |
|----------------------------|------------------------------------------------------------------|
| `wuerfel_<farbe>.obj` ×6   | massiver Würfel, Kante 3 m, Ursprung Mitte der Unterseite        |
| `saeule_<farbe>.obj` ×7    | schmale Achteck-Säule, 100 m hoch, 0,8 m breit, leuchtend, halbtransparent |
| `licht_warm.obj`           | ein Punktlicht, warmweiß, mit Glühpunkt und Lichtfleck           |
| `marken.png`               | 4×4 Weiß mit halbem Alpha — die einzige Textur, für die Säulen  |

Die Farben sind dieselben sechs wie beim Rauch (`FARBEN` aus `rauch_bauen.py`), die Säule gibt es
zusätzlich in Weiß. Bei Farben wird nie gewürfelt — die Farbe trägt Bedeutung.

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
Lichtfleck ausreicht, ob `ATTR_emission_rgb` bei Nacht sichtbar leuchtet und wie hell 500 cd am
Boden wirken. Die Stärke ist eine Stellschraube (`LICHT_CD`), keine Messung.
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
SAEULE_BREITE = 0.8

#: Wie stark der Würfel von selbst leuchtet (Vielfaches der Farbe) — „leichtes" Emissiv, damit er
#: nachts nicht schwarz wird, tagsüber aber wie ein Würfel und nicht wie eine Lampe aussieht.
WUERFEL_EMISSION = 0.35

#: Die Säule leuchtet in voller Farbe.
SAEULE_EMISSION = 1.0

#: Alpha der Textur für die Säule: halbtransparent, damit man durch sie hindurchsieht.
SAEULE_ALPHA = 140

#: Warmweiß und Stärke des Einfachlichts. 500 cd ist der Wert, den Laminars eigene Objekte für
#: `spot_params_bb_pm` benutzen; der Lichtfleck bekommt weniger (Stellschraube, ungemessen).
LICHT_RGB = (1.0, 0.84, 0.6)
LICHT_CD = 500
LICHTFLECK_CD = 1000
LICHT_HOEHE = 0.5

#: Alle sieben Säulenfarben: die sechs Friesenfarben und Weiß.
SAEULEN = {**FARBEN, "weiss": (255, 255, 255)}


def _f(farbe: tuple[int, int, int], faktor: float = 1.0) -> tuple[float, float, float]:
    return tuple(round(c / 255.0 * faktor, 4) for c in farbe)


# --------------------------------------------------------------------------- Geometrie

def _mesh(flaechen: list[tuple[tuple[float, float, float], list[tuple[float, float, float]]]],
          uv: tuple[float, float]) -> tuple[list[str], list[int]]:
    """Flächen (Normale, Ecken gegen den Uhrzeigersinn von außen gesehen) → VT-Zeilen und Indizes.

    Jede Fläche bekommt ihre EIGENEN Ecken, damit die Normalen je Fläche stimmen (harte Kanten).
    Eine Ecke gehört zu zwei oder drei Flächen mit verschiedenen Normalen.
    """
    vt, idx = [], []
    for normale, ecken in flaechen:
        basis = len(vt)
        for x, y, z in ecken:
            vt.append(f"VT\t{x:.4f}\t{y:.4f}\t{z:.4f}\t{normale[0]:.4f}\t{normale[1]:.4f}\t"
                      f"{normale[2]:.4f}\t{uv[0]:.4f}\t{uv[1]:.4f}")
        for i in range(1, len(ecken) - 1):          # Fächer: 4 Ecken → 2 Dreiecke, 8 → 6
            idx += [basis, basis + i, basis + i + 1]
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


def saeule_flaechen(breite: float, hoehe: float, ecken: int = 8) -> list:
    """Ein regelmäßiges n-Eck-Prisma (Vorgabe Achteck) mit Deckel, Ursprung Mitte der Unterseite.

    `breite` ist der Abstand zweier gegenüberliegender FLACHEN (die Breite, wie man sie misst).
    """
    apothem = breite / 2.0
    radius = apothem / math.cos(math.pi / ecken)
    flaechen = []
    # Ecken auf dem Kreis: Winkel i·360°/n, dazwischen liegt die Flächenmitte bei (i+0.5)·360°/n.
    ring = [(radius * math.cos(2 * math.pi * i / ecken), radius * math.sin(2 * math.pi * i / ecken))
            for i in range(ecken)]
    for i in range(ecken):
        (x0, z0), (x1, z1) = ring[i], ring[(i + 1) % ecken]
        mitte = 2 * math.pi * (i + 0.5) / ecken
        n = (math.cos(mitte), 0.0, math.sin(mitte))
        # Von außen gesehen gegen den Uhrzeigersinn: unten links → unten rechts → oben rechts → oben links.
        # In X-Plane (Rechtssystem mit +Y oben) ergibt Kreiswinkel steigend in der X-Z-Ebene die
        # Reihenfolge (x0,z0) → (x1,z1) von außen betrachtet als Uhrzeigersinn; darum getauscht.
        flaechen.append((n, [(x1, 0.0, z1), (x0, 0.0, z0), (x0, hoehe, z0), (x1, hoehe, z1)]))
    deckel = [(x, hoehe, z) for x, z in reversed(ring)]
    flaechen.append(((0.0, 1.0, 0.0), deckel))
    return flaechen


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
    pfad.write_text(_obj_text(
        "Die FriesenBruegge -- Lichtsaeule, 100 m, 0,8 m breit, leuchtend, halbtransparent.",
        saeule_flaechen(SAEULE_BREITE, SAEULE_HOEHE), (0.5, 0.5), TEXTUR,
        _f(farbe), _f(farbe, SAEULE_EMISSION), kulling=False),
        encoding="utf-8", newline="\n")


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
    """4×4 Weiß mit halbem Alpha, als PNG ohne Fremdbibliothek geschrieben (RGBA, 8 Bit)."""
    b, h = 4, 4
    roh = b"".join(b"\x00" + bytes([255, 255, 255, SAEULE_ALPHA]) * b for _ in range(h))

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
    for name, farbe in FARBEN.items():
        wuerfel_schreiben(ZIEL / f"wuerfel_{name}.obj", farbe)
        print(f"  wuerfel_{name}.obj".ljust(26) + f"#{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")
    for name, farbe in SAEULEN.items():
        saeule_schreiben(ZIEL / f"saeule_{name}.obj", farbe)
        print(f"  saeule_{name}.obj".ljust(26) + f"#{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")
    licht_schreiben(ZIEL / "licht_warm.obj")
    print("  licht_warm.obj")


if __name__ == "__main__":
    main()
