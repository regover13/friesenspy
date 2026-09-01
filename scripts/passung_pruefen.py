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

# Sehr grobes Plausibilitaetsband -- es faengt nur noch groben Unfug, und das mit Absicht.
#
# Es stand zuerst bei 0,8 bis 6,0, gemessen an den 68 damals gepassten Blaettern
# (1,10 bis 4,61 m/px). Beide Grenzen waren falsch, und beide haben am 01.09.2026 eine
# richtige Passung abgewiesen: EDLP im Massstab 1:3000 mit 0,51 m/px (0,61 Prozent
# Abweichung zur Leiste) und ETSI im Massstab 1:40000 mit 6,82 (0,54 Prozent). Eine an
# vorhandenen Faellen geeichte Schranke kennt eben nur die vorhandenen Faelle.
#
# Die tatsaechliche Spanne der DFS-Blaetter reicht von 1:3000 bis 1:40000, also ueber den
# Faktor dreizehn. Ein Band darueber kann einen Faktor-2-Fehler grundsaetzlich nicht mehr
# fangen -- diesen Anspruch gibt es hier also nicht mehr. Die Arbeit macht die Leiste; das
# Band ist nur noch der Notnagel gegen eine Passung, die um Groessenordnungen danebenliegt.
MPS_MIN, MPS_MAX = 0.3, 12.0


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


# ---------------------------------------------------------------------------
# Verfahren ARP: passen ohne brauchbare Schwellenkoordinaten
# ---------------------------------------------------------------------------
#
# Zwoelf der offenen Blaetter liegen daran fest, dass die OurAirports-Schwellen nicht zum
# Blatt passen -- mal laenger (EDRB: 3056 m stillgelegte Vollbahn gegen 1230 m genutzten
# Abschnitt), mal kuerzer (EDWH: 536 gegen 778 m). Auf den betroffenen Blaettern stimmt
# aber alles andere:
#
#   * die ARP-Koordinate im Blattkopf (auf 0,01 Bogenminute, also rund 15 m),
#   * das ARP-Symbol auf der Karte,
#   * die gedruckte Massstabsleiste,
#   * und die BAHNRICHTUNG aus OurAirports -- die bleibt auch dann richtig, wenn die Laenge
#     falsch ist, weil ein veralteter Eintrag dieselbe Achse beschreibt. Gemessen am
#     01.09.2026 liegt sie fuer 19 der 23 offenen Plaetze unter 0,7 Grad genau; nur EDPH,
#     EDQA und EDQC sind mit 7 bis 41 Grad zu grob gerundet, und EDKB hat gar keine Daten.
#
# Daraus laesst sich die Passung vollstaendig bauen. Die Gegenprobe ist dann NICHT mehr die
# Leiste (die steckt ja schon im Massstab), sondern die gezeichnete Bahnlaenge gegen die auf
# dem Blatt GEDRUCKTE -- zwei Angaben desselben Blatts, die nichts voneinander wissen.

def aus_arp(arp_px, arp_geo, mps: float, drehung: float, abstand_px: float = 500.0):
    """Zwei Punktpaare aus ARP, Massstab und Blattdrehung bauen.

    ``drehung`` ist die Drehung des Blattes in Grad: wahre Peilung = Schirmpeilung +
    Drehung. Der zweite Punkt wird auf dem Blatt senkrecht nach oben gesetzt; auf dem Boden
    liegt er damit unter der Peilung ``drehung``.

    Rueckgabe ``(p1_px, p1_geo, p2_px, p2_geo)`` -- direkt fuer ``handpassung`` und fuer den
    Speicheraufruf.
    """
    strecke = abstand_px * mps
    t = math.radians(drehung)
    nord, ost = strecke * math.cos(t), strecke * math.sin(t)
    m_lon, m_lat = runway_ref.meter_je_grad(arp_geo[0])
    p2_geo = (arp_geo[0] + nord / m_lat, arp_geo[1] + ost / m_lon)
    return (tuple(arp_px), tuple(arp_geo),
            (arp_px[0], arp_px[1] - abstand_px), p2_geo)


def blattdrehung(bahn_px_a, bahn_px_b, wahrer_kurs: float) -> float:
    """Blattdrehung aus der gezeichneten Bahn und ihrer wahren Peilung.

    ``bahn_px_a`` -> ``bahn_px_b`` muss dieselbe Richtung meinen wie ``wahrer_kurs``
    (also von der Schwelle mit der kleineren Kennzahl zur groesseren).
    """
    schirm = math.degrees(math.atan2(bahn_px_b[0] - bahn_px_a[0],
                                     -(bahn_px_b[1] - bahn_px_a[1])))
    return (wahrer_kurs - schirm) % 360.0


def probe_bahnlaenge(bahn_px_a, bahn_px_b, mps: float, gedruckte_laenge: float) -> dict:
    """Die Gegenprobe des ARP-Verfahrens: gezeichnete Bahn gegen gedruckte Laenge.

    Sie ist unabhaengig von ARP und von OurAirports -- misst also wirklich etwas anderes als
    das, woraus die Passung gebaut wurde. Die Schranke ist mit drei Prozent bewusst weiter
    als bei der Leiste: Die gedruckte Laenge ist gerundet (EDBM nennt 1000 m fuer 1001,6).
    """
    gemessen = math.hypot(bahn_px_b[0] - bahn_px_a[0],
                          bahn_px_b[1] - bahn_px_a[1]) * mps
    abw = abs(gemessen - gedruckte_laenge) / gedruckte_laenge
    return {"gemessen_m": round(gemessen, 1), "gedruckt_m": gedruckte_laenge,
            "abweichung_prozent": round(abw * 100, 2), "ok": bool(abw <= 0.03)}
