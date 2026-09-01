#!/usr/bin/env python3
"""Das gedruckte Gradnetz eines DFS-Blatts finden und vermessen.

Aufruf::

    python scripts/gradnetz.py EDDH rollkarte
    python scripts/gradnetz.py EDDH rollkarte --bild /tmp/netz.png

**Wozu.** Die Handpassung braucht zwei Bildpunkte mit Koordinaten. Der uebliche Weg nimmt
dafuer zwei Bahnschwellen und holt ihre Koordinaten bei OurAirports -- und scheitert genau
dann, wenn OurAirports fuer diesen Platz nicht stimmt. Von 43 offenen Blaettern lagen dreizehn
aus diesem Grund fest (EDRB: 3056 m stillgelegte Vollbahn statt 1230 m genutztem Abschnitt;
EDDN: airportsdata liegt um 775 m daneben).

Ein Blatt mit gedrucktem Gradnetz braucht davon nichts. Die Linien tragen ihre Koordinaten
selbst; zwei Schnittpunkte genuegen. EDDH, EDDS, EDDN und EDLP sind so gepasst worden, mit
0,08 bis 0,61 Prozent Abweichung gegen die gedruckte Massstabsleiste.

**Nur vier der 27 Blaetter hatten ueberhaupt eines.** Die kleinen Platzblaetter (875x1240)
tragen bloss die ARP-Koordinate im Kopf. Dieses Werkzeug ist also kein Ersatz fuer das
Schwellenverfahren, sondern der Weg fuer die grossen Blaetter.

**Drei Fallen, jede davon einmal zugeschnappt.**

1. *Das Winkelfenster.* EDLP ist um 57 Grad gedreht. Eine Suche ueber +-8 Grad findet dort
   nichts und meldet trotzdem einen Treffer -- irgendwelche Rollwege. Deshalb +-46 Grad.

2. *Welche Schar ist welche.* Bei EDLP sind die WAAGERECHTEREN Linien die LAENGEN, nicht die
   Breiten. Wer das verwechselt, bekommt ein Abstandsverhaeltnis, das nach einem Fehler im
   Blatt aussieht, und sucht ihn an der falschen Stelle. Die Probe steht in
   ``verhaeltnis_stimmt``: Sind beide Scharen 10 Sekunden, muss ihr Abstandsverhaeltnis
   gleich 1/cos(Breite) sein.

3. *Die Beschriftung.* Sie NICHT durch Zuschneiden an einer gerechneten Stelle ablesen --
   dabei erwischt man das Etikett der Nachbarlinie. Bei EDDS kostete das einen um eins
   verzaehlten Index und 8,28 Prozent Abweichung. ``--bild`` zeichnet die erkannten Linien
   nummeriert ins Blatt; erst danebengelegt ist die Zuordnung belegt.

**Die Leiste bleibt die Gegenprobe, nicht der Schiedsrichter.** Bei EDDN weicht sie um
3,4 Prozent vom Netz ab. Nachgeprueft hat das Netz recht: Es ist in sich stimmig, beide
Beschriftungen sind belegt, und die Bahnmitte aus den Schwellenkoordinaten landet 31 m neben
dem ARP-Symbol. Gedruckte Massstabsleisten koennen falsch sein (zweiter Fall nach EDBM).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import aip_charts  # noqa: E402

# Wie weit ein Blatt gedreht sein darf. EDLP liegt bei 33 Grad (in dieser Zaehlweise);
# darueber hinaus tauschen die beiden Scharen ihre Rollen und 46 Grad reichen wieder.
GRAD_FENSTER = 46.0
SCHRITT = 0.05


def blatt(icao: str, sorte: str, db_verzeichnis: str = "/opt/friesenspy/data") -> Image.Image:
    pfad = aip_charts.dfs_blatt_pfad(str(Path(db_verzeichnis) / "x.db"), icao, sorte, "roh")
    return Image.open(pfad).convert("RGB")


def maske(a: np.ndarray, achse: str, hell: int = 225, lo: int = 80, hi: int = 215,
          abstand: int = 3) -> np.ndarray:
    """Duenne, graue, freistehende Linienpixel.

    ``achse='h'`` sucht waagerechtere Linien (hell darueber UND darunter), ``'v'`` steilere.
    Text faellt weg, weil er nicht freisteht; Flaechen fallen weg, weil ihnen der helle Rand
    in drei Pixeln fehlt.
    """
    g = a.mean(axis=2)
    sat = a.max(axis=2).astype(int) - a.min(axis=2).astype(int)
    grau = (g > lo) & (g < hi) & (sat < 40)
    d = abstand
    if achse == "h":
        frei = (np.roll(g, d, axis=0) > hell) & (np.roll(g, -d, axis=0) > hell)
        frei[:d, :] = False
        frei[-d:, :] = False
    else:
        frei = (np.roll(g, d, axis=1) > hell) & (np.roll(g, -d, axis=1) > hell)
        frei[:, :d] = False
        frei[:, -d:] = False
    return grau & frei


def _r(xs: np.ndarray, ys: np.ndarray, achse: str, grad: float) -> np.ndarray:
    t = math.radians(grad)
    if achse == "h":
        return ys * math.cos(t) - xs * math.sin(t)
    return xs * math.cos(t) + ys * math.sin(t)


def schar(m: np.ndarray, achse: str, grad_von: float = -GRAD_FENSTER,
          grad_bis: float = GRAD_FENSTER, schritt: float = SCHRITT,
          min_treffer: int | None = None):
    """Die Schar paralleler Linien finden: Winkel und Abstaende vom Ursprung.

    Der Winkel wird ueber die Schaerfe des Abstands-Histogramms gesucht: Steht er richtig,
    faellt die ganze Schar in wenige Behaelter.
    """
    ys, xs = np.nonzero(m)
    if len(xs) < 200:
        return None
    if min_treffer is None:
        min_treffer = max(60, len(xs) // 400)
    bestes = None
    for grad in np.arange(grad_von, grad_bis + 1e-9, schritt):
        r = _r(xs, ys, achse, float(grad))
        hist, kanten = np.histogram(r, bins=int(r.max() - r.min()) + 1,
                                    range=(r.min(), r.max() + 1))
        wert = float((hist.astype(float) ** 2).sum())
        if bestes is None or wert > bestes[0]:
            bestes = (wert, float(grad), hist, kanten)
    _, grad, hist, kanten = bestes
    gipfel = []
    for i in range(1, len(hist) - 1):
        if hist[i] >= min_treffer and hist[i] >= hist[i - 1] and hist[i] >= hist[i + 1]:
            umfeld = hist[max(0, i - 2):i + 3].astype(float)
            mitte = kanten[max(0, i - 2):i + 3][:len(umfeld)]
            gipfel.append((float((umfeld * (mitte + 0.5)).sum() / umfeld.sum()),
                           int(umfeld.sum())))
    gipfel.sort()
    zusammen: list[tuple[float, int]] = []
    for r, n in gipfel:
        if zusammen and r - zusammen[-1][0] < 6:
            if n > zusammen[-1][1]:
                zusammen[-1] = (r, n)
        else:
            zusammen.append((r, n))
    return grad, zusammen


def gegenschar(a: np.ndarray, achse: str, winkel: float, spanne: float = 3.0):
    """Die zweite Schar bei bekanntem Gitterwinkel suchen.

    Ein geographisches Gitter ist rechtwinklig; steht die eine Schar bei ``winkel``, steht
    die andere in IHRER Parametrisierung beim gleichen Wert. Ohne diese Fesselung findet die
    freie Suche in einem vollen Blatt regelmaessig Rollwege statt Netzlinien -- bei EDDN,
    EDDS und EDLP war genau das der Fall.
    """
    return schar(maske(a, achse), achse, grad_von=winkel - spanne,
                 grad_bis=winkel + spanne, schritt=SCHRITT)


def punkt(grad_h: float, r_h: float, grad_v: float, r_v: float) -> tuple[float, float]:
    """Schnittpunkt einer Linie aus jeder Schar."""
    th, tv = math.radians(grad_h), math.radians(grad_v)
    A = np.array([[-math.sin(th), math.cos(th)],
                  [math.cos(tv), math.sin(tv)]])
    x, y = np.linalg.solve(A, np.array([r_h, r_v]))
    return float(x), float(y)


def verhaeltnis_stimmt(abstand_breiten: float, abstand_laengen: float,
                       breite_grad: float, toleranz: float = 0.02) -> bool:
    """Sind beide Scharen wirklich 10-Sekunden-Linien?

    Dann muss der Abstand der Breitenlinien zu dem der Laengenlinien stehen wie
    1/cos(Breite). Das ist die einzige Probe, die OHNE die Beschriftung auskommt -- und die,
    die bei EDLP zeigte, dass die waagerechtere Schar dort die der LAENGEN ist.
    """
    soll = 1.0 / math.cos(math.radians(breite_grad))
    return abs(abstand_breiten / abstand_laengen - soll) <= toleranz * soll


def netzbild(im: Image.Image, grad_h: float, rh, grad_v: float, rv, datei: str,
             breite: int | None = None) -> str:
    """Die erkannten Linien nummeriert ins Blatt zeichnen.

    Der einzige belastbare Weg, Linie und Beschriftung einander zuzuordnen. Ein Zuschnitt an
    einer gerechneten Stelle erwischt das Etikett der Nachbarlinie -- bei EDDS geschehen.
    """
    im = im.copy()
    W, H = im.size
    z = ImageDraw.Draw(im)
    th, tv = math.radians(grad_h), math.radians(grad_v)
    for i, r in enumerate(rh):
        p = [(0.0, r / math.cos(th)), (float(W), (r + W * math.sin(th)) / math.cos(th))]
        z.line(p, fill=(255, 0, 0), width=2)
        z.text((W * 0.06, p[0][1] + (p[1][1] - p[0][1]) * 0.06 - 26), f"H{i}", fill=(255, 0, 0))
    for i, r in enumerate(rv):
        p = [(r / math.cos(tv), 0.0), ((r - H * math.sin(tv)) / math.cos(tv), float(H))]
        z.line(p, fill=(0, 90, 255), width=2)
        z.text((p[0][0] + (p[1][0] - p[0][0]) * 0.05 + 4, H * 0.05), f"V{i}", fill=(0, 90, 255))
    if breite:
        im = im.resize((breite, int(H * breite / W)))
    im.save(datei)
    return datei


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("icao")
    a.add_argument("sorte")
    a.add_argument("--bild", help="Erkannte Linien nummeriert hierhin zeichnen")
    n = a.parse_args()

    im = blatt(n.icao, n.sorte)
    feld = np.asarray(im, dtype=np.uint8)
    print(f"{n.icao} {n.sorte}  {im.size[0]}x{im.size[1]}")

    erst = schar(maske(feld, "h"), "h")
    if not erst:
        print("  keine Linienschar gefunden -- dieses Blatt hat vermutlich kein Gradnetz")
        sys.exit(1)
    zweit = gegenschar(feld, "v", erst[0])
    if not zweit:
        print("  nur eine Schar gefunden")
        sys.exit(1)

    for name, (grad, gipfel) in (("H (waagerechter)", erst), ("V (steiler)", zweit)):
        d = [gipfel[i + 1][0] - gipfel[i][0] for i in range(len(gipfel) - 1)]
        print(f"  {name}: {grad:+.2f} Grad, {len(gipfel)} Linien")
        print("      r: " + " ".join(f"{r:.1f}" for r, _ in gipfel))
        if d:
            print("      d: " + " ".join(f"{x:.1f}" for x in d))
    print("\n  Welche Schar welche ist, entscheidet NICHT die Neigung, sondern die")
    print("  Beschriftung -- bei EDLP sind die waagerechteren Linien die der Laengen.")
    if n.bild:
        print("  Bild:", netzbild(im, erst[0], [r for r, _ in erst[1]],
                                  zweit[0], [r for r, _ in zweit[1]], n.bild))


if __name__ == "__main__":
    main()
