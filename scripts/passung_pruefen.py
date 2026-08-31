#!/usr/bin/env python3
"""Eine vorgeschlagene Handpassung gegen eine UNABHAENGIGE Messung pruefen.

Aufruf:
    python scripts/passung_pruefen.py EDVM rollkarte \\
        --schwellen 120,300 640,880 \\
        --leiste 100,1150 400,1150 --leiste-m 500

**Warum das noetig ist.** Beim Passen klickt man zwei Bahnschwellen an. Der haeufigste
Fehler ist, statt der Schwelle das Ende der grauen Flaeche zu treffen: Stopways und Blast
Pads sind in derselben Abstufung gezeichnet. Genau daran ist die alte Bahnvermessung
gescheitert -- bei EDDV mass sie 2784 m fuer eine 2340-m-Bahn. Der Fehler verschiebt und
skaliert das Blatt, und nichts an der Passung selbst verraet ihn.

**Warum die naheliegende Probe NICHT funktioniert.** Der erste Anlauf hier rechnete den
Pixelabstand mal dem Massstab und verglich das Ergebnis mit der Bahnlaenge aus OurAirports.
Das besteht IMMER mit 0,00 Prozent -- auch ein absichtlich um 71 px danebengesetzter Klick
(gemessen 01.09.2026). Der Grund ist ein Zirkelschluss: ``handpassung`` leitet den Massstab
AUS denselben zwei Punkten und ihren Koordinaten ab. Die Rechnung prueft sich selbst.

**Was wirklich unabhaengig ist: die gedruckte Massstabsleiste.** Sie steht auf jedem
DFS-Blatt (km- und NM-Skala neben der Massstabsangabe) und weiss nichts von den Schwellen.
Zwei Messungen desselben Massstabs, die auf verschiedenen Wegen entstehen -- weichen sie
voneinander ab, stimmt eine von beiden nicht.

Zwei Faelle, in denen die Schranke zu Recht anschlaegt und der Schwellen-Klick trotzdem
stimmt: verlegte Schwellen (displaced threshold) und ein veralteter OurAirports-Eintrag.
Beide sind Einzelfaelle und gehoeren angesehen, nicht weggedrueckt.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ground_charts, runway_ref  # noqa: E402

# Klickunsicherheit je Messung, in Pixeln. Wer eine Kante im Bild anklickt, trifft sie auf
# wenige Pixel genau -- drei ist grosszuegig gerechnet.
KLICK_PX = 3.0

# Die Schranke wird NICHT festgeschrieben, sondern aus den tatsaechlichen Messlaengen
# abgeleitet. Der Grund: Sie haengt fast ganz an der Leiste. Bei einer 295 px langen Leiste
# sind drei Pixel ein volles Prozent, bei den 1770 px zwischen zwei Schwellen nur 0,17 --
# eine feste Schranke von drei Prozent liesse deshalb einen 60-m-Stopway durch (gemessen
# 01.09.2026: 1,96 Prozent), waehrend sie bei einer langen Leiste unnoetig grob waere.
#
# Wer eine laengere Leiste misst, bekommt also eine schaerfere Pruefung. Das ist die
# richtige Richtung: Es belohnt die sorgfaeltigere Messung, statt sie zu bestrafen.
SICHERHEIT = 3.0     # wieviele Standardabweichungen noch als "in Ordnung" gelten
SCHRANKE_MIN = 0.008  # darunter wird es Rauschen, egal wie lang gemessen wurde

# Grobes Plausibilitaetsband, gemessen an den 68 bereits gepassten Blaettern (01.09.2026):
# 1,10 bis 4,61 m/px. Das faengt Faktor-2-Fehler, nicht mehr -- es ersetzt die Leiste NICHT.
MPS_MIN, MPS_MAX = 0.8, 6.0


def massstab_aus_leiste(a: tuple[float, float], b: tuple[float, float],
                        meter: float) -> float:
    """Meter je Pixel aus der gedruckten Massstabsleiste -- ohne jeden Bezug zur Bahn."""
    px = leiste_px(a, b)
    return meter / px


def leiste_px(a: tuple[float, float], b: tuple[float, float]) -> float:
    px = math.hypot(b[0] - a[0], b[1] - a[1])
    if px < 20:
        raise ValueError("Leiste zu kurz gemessen -- unter 20 px ist der Wert Rauschen")
    return px


def pruefe(p1_px, p1_geo, p2_px, p2_geo, mps_leiste: float | None,
           px_leiste: float = 0.0) -> dict:
    """Passung aus zwei Schwellen bilden und gegen die Leiste halten.

    ``mps_leiste=None`` heisst: keine Leiste gefunden. Dann bleibt nur das grobe Band, und
    das Ergebnis wird ausdruecklich als ungeprueft gekennzeichnet.
    """
    p = ground_charts.handpassung(p1_px, p1_geo, p2_px, p2_geo)
    if p is None:
        return {"ok": False, "grund": "Die beiden Punkte ergeben keine Passung"}

    px_schwellen = math.hypot(p2_px[0] - p1_px[0], p2_px[1] - p1_px[1])
    aus = {"mps_bahn": round(p.mps, 4), "drehung": round(p.drehung, 2),
           "im_band": MPS_MIN <= p.mps <= MPS_MAX}
    if mps_leiste is None:
        aus.update(ok=False, geprueft=False,
                   grund="keine Massstabsleiste gemessen -- Passung ist UNGEPRUEFT")
        return aus
    abw = abs(p.mps - mps_leiste) / mps_leiste
    schranke = _schranke(px_schwellen, px_leiste)
    aus.update(geprueft=True, mps_leiste=round(mps_leiste, 4),
               abweichung_prozent=round(abw * 100, 2),
               schranke_prozent=round(schranke * 100, 2),
               ok=bool(abw <= schranke and aus["im_band"]))
    if not aus["ok"]:
        aus["grund"] = ("Massstab aus den Schwellen weicht von der Leiste ab -- vermutlich "
                        "Stopway statt Schwelle getroffen, oder verlegte Schwelle")
    return aus


def _schranke(px_schwellen: float, px_leiste: float) -> float:
    """Wieviel Abweichung diese beiden Messungen ueberhaupt aufloesen koennen.

    Beide Laengen tragen ihre Klickunsicherheit relativ bei; die Fehler sind unabhaengig,
    also quadratisch addiert.
    """
    rel = math.hypot(KLICK_PX / px_schwellen, KLICK_PX / px_leiste)
    return max(SCHRANKE_MIN, SICHERHEIT * rel)


def bahnen_holen(icao: str, db_verzeichnis: str = "/opt/friesenspy/data"):
    datei = Path(db_verzeichnis) / "runways.csv"
    if not datei.is_file():
        datei = Path("/tmp/runways.csv")
        runway_ref.datei_holen(datei)
    return runway_ref.bahnen(icao, datei)


def _punkt(text: str) -> tuple[float, float]:
    x, y = text.split(",")
    return (float(x), float(y))


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("icao")
    a.add_argument("sorte")
    a.add_argument("--schwellen", nargs=2, type=_punkt, required=True,
                   metavar=("P1", "P2"), help="Bildpunkte der beiden Schwellen, z.B. 120,300")
    a.add_argument("--bahn", default="", help="Bahnname, sonst die laengste")
    a.add_argument("--leiste", nargs=2, type=_punkt, metavar=("A", "B"),
                   help="Bildpunkte der Enden der Massstabsleiste")
    a.add_argument("--leiste-m", type=float, help="Laenge der gemessenen Leiste in Metern")
    n = a.parse_args()

    bahnen = bahnen_holen(n.icao)
    if not bahnen:
        print(f"{n.icao}: keine Schwellenkoordinaten bei OurAirports -- Werte am Gradnetz "
              f"des Blatts ablesen, diese Pruefung greift nicht.")
        sys.exit(2)
    if n.bahn:
        treffer = [b for b in bahnen if b.name == n.bahn]
        if not treffer:
            print(f"{n.icao}: Bahn {n.bahn} unbekannt. Vorhanden: "
                  + ", ".join(b.name for b in bahnen))
            sys.exit(2)
        bahn = treffer[0]
    else:
        bahn = max(bahnen, key=lambda b: b.laenge)

    mps_leiste, px_leiste = None, 0.0
    if n.leiste and n.leiste_m:
        mps_leiste = massstab_aus_leiste(n.leiste[0], n.leiste[1], n.leiste_m)
        px_leiste = leiste_px(n.leiste[0], n.leiste[1])

    p1_px, p2_px = n.schwellen
    # BEIDE Zuordnungen probieren: Welche Schwelle zuerst angeklickt wurde, weiss nur der
    # Klickende -- die falsche ergibt eine um 180 Grad verdrehte Karte. Der Massstab ist in
    # beiden Faellen gleich, die Drehung nicht.
    ergebnisse = [pruefe(p1_px, bahn.le, p2_px, bahn.he, mps_leiste, px_leiste),
                  pruefe(p1_px, bahn.he, p2_px, bahn.le, mps_leiste, px_leiste)]

    print(f"{n.icao} {n.sorte} -- Bahn {bahn.name}, {bahn.laenge:.0f} m, "
          f"Kurs {bahn.kurs:.1f} Grad")
    e = ergebnisse[0]
    print(f"  Massstab aus den Schwellen: {e['mps_bahn']} m/px")
    if e.get("geprueft"):
        print(f"  Massstab aus der Leiste:    {e['mps_leiste']} m/px")
        print(f"  Abweichung:                 {e['abweichung_prozent']} % "
              f"(Schranke {e['schranke_prozent']} %, aus den Messlaengen abgeleitet)")
    print(f"  Drehung: {ergebnisse[0]['drehung']} Grad (bei umgekehrter Zuordnung "
          f"{ergebnisse[1]['drehung']} Grad)")
    if not e["im_band"]:
        print(f"  ACHTUNG: {e['mps_bahn']} m/px liegt ausserhalb von {MPS_MIN}-{MPS_MAX} "
              f"-- vermutlich ein Faktor-Fehler")
    if e["ok"]:
        print("  BESTANDEN")
        sys.exit(0)
    print(f"  DURCHGEFALLEN -- {e.get('grund', '')}")
    print("  NICHT speichern, sondern ansehen.")
    sys.exit(1)


if __name__ == "__main__":
    main()
