"""DFS-Flugplatzkarten: Bildanalyse und Passung ueber die Bahngeometrie.

Anders als bei den Sichtflugkarten (``app/aip_charts.py``) wird hier **kein einziges Zeichen
gelesen**. Flugplatzkarten haben kein Gradnetz, keine Ticks und keine Grad-Beschriftung; die
ganze Kette dort hat nichts zu greifen. Stattdessen werden die grauen Bahnflaechen im Bild
vermessen und gegen die Schwellenkoordinaten aus ``app/runway_ref.py`` gerechnet.

Reines Pillow. numpy, scipy und OpenCV sind im Projekt nicht vorhanden und werden es nicht.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md
"""
from __future__ import annotations

import collections
import io
import itertools
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app import runway_ref

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- Schwellwerte
TON_TIEF, TON_HOCH = 100, 210      # in diesem Bereich liegt die Bahnfarbe
TON_MINDESTANTEIL = 0.006          # sonst ist das Blatt keine Flugplatzkarte
TON_SPIEL = 6
FLAECHE_MINDEST = 8000             # Pixel
SCHLANKHEIT_MINDEST = 8            # Laenge zu Breite

# Beim Abtasten der Bahnenden: erlaubte Luecke und geforderte Querabdeckung.
LUECKE_M = 100.0
QUERDECKUNG = 0.70
RANDSAUM_M = 75.0

# Prueffkette
REST_SCHRANKE_M = 15.0             # ein Drittel Bahnbreite, weniger als eine Rollwegbreite
PASSPUNKTE_MINDEST = 4
NORDUNG_VERWERFEN = (100.0, 260.0)
SKALA_GRUNDFEHLER_M = 140.0        # additiver Malfehler je Bahn (Stopways, Blast Pads)
SKALA_MINDESTSPIEL = 0.04          # auch bei sehr langen Bahnen mindestens 4 Prozent
FELD_SAUM_M = 1000.0


@dataclass
class Achse:
    """Eine laengliche Flaeche in Bahnfarbe, mit Laengsachse und abgetasteten Enden."""
    cx: float
    cy: float
    winkel_rad: float
    laenge: float
    breite: float
    u0: float
    u1: float
    ua: float = 0.0           # getastetes Ende, Achskoordinate
    ub: float = 0.0
    pa: tuple = (0.0, 0.0)    # getastete Enden in Bildkoordinaten
    pb: tuple = (0.0, 0.0)
    ra: bool = False          # Ende liegt am Blattrand, also abgeschnitten
    rb: bool = False
    gueltig: bool = True

    @property
    def voll(self) -> float:
        return self.ub - self.ua


@dataclass
class GroundPassung:
    drehung: float            # Grad; siehe norden() zur Vorzeichenkonvention
    mps: float                # Meter je Pixel im ROHblatt
    rest_max: float
    bahnen: int
    punkte: int
    koeff: tuple              # (a, b, e, f) der Aehnlichkeit, auf gespiegeltem y
    bezug: tuple              # (lat, lon) des Nullpunkts der Meterrechnung
    huelle_m: tuple           # (ost_min, ost_max, nord_min, nord_max) der benutzten Bahnen


# --------------------------------------------------------------------------- Bahnfarbe
def bahnfarbe(im: Image.Image) -> int | None:
    """Der dominante mittelgraue Ton -- gemessen, nicht festgelegt.

    Flugplatzkarten nutzen 153/154, Rollkarten 179/180. Eine feste Zahl waere bei der
    naechsten Kartenausgabe falsch. Gemessen an EDDL: Der Ton macht 3,7 Prozent der Flaeche
    aus, waehrend jeder Nachbarwert bei 0,2 bis 0,4 Prozent liegt -- der Peak ist eindeutig.

    ``None``, wenn kein solcher Ton da ist. Dann ist das Blatt keine Flugplatzkarte.
    """
    breite, hoehe = im.size
    px = im.load()
    haeufig: collections.Counter = collections.Counter()
    for y in range(0, hoehe, 3):
        for x in range(0, breite, 3):
            wert = px[x, y]
            if TON_TIEF <= wert <= TON_HOCH:
                haeufig[wert] += 1
    if not haeufig:
        return None
    ton, anzahl = haeufig.most_common(1)[0]
    stichprobe = (breite // 3 + 1) * (hoehe // 3 + 1)
    return ton if anzahl / stichprobe >= TON_MINDESTANTEIL else None


# --------------------------------------------------------------------------- Flaechen
def bahnflaechen(im: Image.Image, ton: int,
                 mindest: int = FLAECHE_MINDEST) -> list[list[tuple[int, int, int]]]:
    """Zusammenhaengende Flaechen in Bahnfarbe, je als Liste von Laeufen ``(y, x0, x1)``.

    Union-Find ueber zeilenweise Laeufe -- das ist in reinem Python schnell genug (rund
    zwei Sekunden fuer ein 3101x1754-Blatt) und braucht kein numpy.
    """
    tief, hoch = ton - TON_SPIEL, ton + TON_SPIEL
    breite, hoehe = im.size
    px = im.load()
    laeufe: list[tuple[int, int, int]] = []
    zeile_von: list[int] = []
    for y in range(hoehe):
        zeile_von.append(len(laeufe))
        x = 0
        while x < breite:
            if tief <= px[x, y] <= hoch:
                x0 = x
                while x < breite and tief <= px[x, y] <= hoch:
                    x += 1
                if x - x0 >= 3:
                    laeufe.append((y, x0, x - 1))
            else:
                x += 1
    zeile_von.append(len(laeufe))

    eltern = list(range(len(laeufe)))

    def finde(i: int) -> int:
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    for y in range(1, hoehe):
        i, j = zeile_von[y], zeile_von[y - 1]
        ende_i, ende_j = zeile_von[y + 1], zeile_von[y]
        while i < ende_i and j < ende_j:
            _, a0, a1 = laeufe[i]
            _, b0, b1 = laeufe[j]
            if a1 >= b0 and b1 >= a0:
                ra, rb = finde(i), finde(j)
                if ra != rb:
                    eltern[rb] = ra
            if a1 < b1:
                i += 1
            else:
                j += 1

    gruppen: dict[int, list] = {}
    for i, lauf in enumerate(laeufe):
        gruppen.setdefault(finde(i), []).append(lauf)
    return [g for g in gruppen.values()
            if sum(x1 - x0 + 1 for _, x0, x1 in g) >= mindest]


def hauptachse(flaeche: list[tuple[int, int, int]]) -> Achse:
    """Laengsachse aus den zweiten Momenten.

    Der Winkel ist die verlaesslichste Groesse der ganzen Kette: Gemessen stimmten die
    Achsen zweier Parallelbahnen desselben Blattes auf 0,01 bis 0,06 Grad ueberein.
    """
    n = sx = sy = 0
    for y, x0, x1 in flaeche:
        k = x1 - x0 + 1
        n += k
        sy += y * k
        sx += (x0 + x1) * k / 2.0
    cx, cy = sx / n, sy / n
    mxx = myy = mxy = 0.0
    for y, x0, x1 in flaeche:
        dy = y - cy
        for x in range(x0, x1 + 1):
            dx = x - cx
            mxx += dx * dx
            myy += dy * dy
            mxy += dx * dy
    mxx /= n
    myy /= n
    mxy /= n
    th = 0.5 * math.atan2(2 * mxy, mxx - myy)
    ca, sa = math.cos(th), math.sin(th)
    lo = hi = qlo = qhi = None
    for y, x0, x1 in flaeche:
        for x in (x0, x1):
            u = (x - cx) * ca + (y - cy) * sa
            v = -(x - cx) * sa + (y - cy) * ca
            lo = u if lo is None else min(lo, u)
            hi = u if hi is None else max(hi, u)
            qlo = v if qlo is None else min(qlo, v)
            qhi = v if qhi is None else max(qhi, v)
    return Achse(cx=cx, cy=cy, winkel_rad=th, laenge=hi - lo, breite=qhi - qlo,
                 u0=lo, u1=hi)


# --------------------------------------------------------------------------- Enden
def enden_tasten(im: Image.Image, ton: int, a: Achse, mps_grob: float) -> None:
    """Die echten Bahnenden entlang der Achse suchen und in ``a`` eintragen.

    **Warum ueberhaupt getastet wird.** Rollwegabzweige und Markierungen trennen die
    Flaeche; gemessene Laengen fielen bis zu 24 Prozent zu kurz aus. Bei EDDL hob das
    Abtasten die Laenge von 1414 auf die richtigen 1769 px.

    **Toleranzen in Metern, nicht in Pixeln.** Eine feste Luecke von 60 px sind bei
    1,6 m/px rund 96 m, bei 2,6 m/px rund 156 m -- dieselbe Zahl bedeutet je nach Blatt
    etwas voellig anderes. Umgerechnet wird ueber die Grobskala, die vor dem Abtasten aus
    Komponentenlaenge und laengster Referenzbahn schaetzbar ist.

    **Die Notbremse liefert kein Ergebnis.** Laeuft der Scan bis an die Abbruchgrenze, ist
    die Achse unbrauchbar und wird verworfen -- der Prototyp gab dort einen Wert mitten im
    Nirgendwo als "Ende" zurueck.
    """
    breite, hoehe = im.size
    px = im.load()
    ca, sa = math.cos(a.winkel_rad), math.sin(a.winkel_rad)
    halb = max(3.0, a.breite / 2.0 - 2)
    luecke_px = max(10.0, LUECKE_M / max(mps_grob, 1e-6))
    grenze = 4.0 * max(breite, hoehe)

    def bahn_bei(u: float) -> bool:
        treffer = gesamt = 0
        v = -halb
        while v <= halb:
            x = int(round(a.cx + u * ca - v * sa))
            y = int(round(a.cy + u * sa + v * ca))
            if 0 <= x < breite and 0 <= y < hoehe:
                gesamt += 1
                if ton - TON_SPIEL <= px[x, y] <= ton + TON_SPIEL:
                    treffer += 1
            v += 1.0
        # 70 Prozent, nicht 55: Ein 23-m-Rollweg quer ueber die verlaengerte Achse einer
        # 45-m-Bahn deckt 51 Prozent. Bei 55 stuende die Schwelle ohne Sicherheitsabstand
        # direkt neben dem haeufigsten Stoerer.
        return gesamt > 0 and treffer / gesamt >= QUERDECKUNG

    enden = []
    for richtung in (-1, 1):
        u = a.u0 if richtung < 0 else a.u1
        leer = 0.0
        gerissen = False
        while leer < luecke_px:
            u += richtung
            if bahn_bei(u):
                leer = 0.0
            else:
                leer += 1.0
            if abs(u) > grenze:
                gerissen = True
                break
        if gerissen:
            a.gueltig = False
            return
        enden.append(u - richtung * leer)
    a.ua, a.ub = enden[0], enden[1]
    a.pa = (a.cx + a.ua * ca, a.cy + a.ua * sa)
    a.pb = (a.cx + a.ub * ca, a.cy + a.ub * sa)
    saum = max(20.0, RANDSAUM_M / max(mps_grob, 1e-6))
    a.ra = _am_rand(a.pa, breite, hoehe, saum)
    a.rb = _am_rand(a.pb, breite, hoehe, saum)


def _am_rand(p: tuple[float, float], breite: int, hoehe: int, saum: float) -> bool:
    """Liegt der Punkt so dicht am Blattrand, dass die Bahn dort nur abgeschnitten ist?

    Ein solches Ende ist KEIN Passpunkt. Mehrblattrige Rollkarten zeigen Ausschnitte; ihr
    Bahnende am Papierrand hat mit der echten Schwelle nichts zu tun. Die Achsrichtung geht
    trotzdem ein.
    """
    x, y = p
    return x < saum or y < saum or x > breite - saum or y > hoehe - saum


def achsen_zusammenfassen(achsen: list[Achse], mps_grob: float) -> list[Achse]:
    """Praktisch gleiche Achsen zu einer machen.

    Eine durch Abzweige zerteilte Bahn liefert mehrere Komponenten, deren Abtasten alle auf
    dieselben Vollenden zieht. Uebrig bleiben zwei fast deckungsgleiche Achsen, welche die
    Zuordnung auf zwei VERSCHIEDENE Parallelbahnen legen kann -- und der Restfehler faengt
    das nur bei unsymmetrischen Layouts sicher ab.
    """
    behalten: list[Achse] = []
    naehe = max(5.0, 60.0 / max(mps_grob, 1e-6))
    for a in sorted(achsen, key=lambda x: -x.voll):
        doppelt = False
        for b in behalten:
            if abs(_winkeldiff(a.winkel_rad, b.winkel_rad)) > math.radians(2.0):
                continue
            # Querabstand der Achsmitten: gleiche Richtung UND gleiche Lage heisst gleiche Bahn.
            dx, dy = a.cx - b.cx, a.cy - b.cy
            quer = abs(-dx * math.sin(b.winkel_rad) + dy * math.cos(b.winkel_rad))
            if quer < naehe:
                doppelt = True
                break
        if not doppelt:
            behalten.append(a)
    return behalten


def _winkeldiff(a: float, b: float) -> float:
    d = (a - b) % math.pi
    return d if d <= math.pi / 2 else d - math.pi


# --------------------------------------------------------------------------- Passung
def aehnlich(paare: list[tuple[tuple[float, float], tuple[float, float]]]):
    """Drehung, Massstab und Verschiebung nach kleinsten Quadraten.

    Modell: ``X = a*x - b*y + e``, ``Y = b*x + a*y + f``. Vier Unbekannte.

    **Aehnlichkeit, nicht Affinitaet.** Eine Karte ist nicht geschert. Die affine Rechnung
    mit sechs Unbekannten hat in der Vorabprobe 1,7 m ausgewiesen, wo tatsaechlich 5,7 m
    standen -- sie hat nur zwei statt vier Freiheitsgrade und schmeichelt sich selbst;
    zusaetzlich absorbiert ihre Scherung genau die Anisotropie, die ein falscher
    Meridiangrad erzeugt, und verdeckt damit einen echten Modellfehler.

    Der Aufrufer muss die y-Achse VORHER spiegeln: Die Matrix [[a,-b],[b,a]] hat die
    Determinante a^2+b^2 > 0, ist also immer orientierungserhaltend -- die wahre Abbildung
    Bild (y nach unten) auf Nordmeter (y nach oben) ist es nicht und laege ohne Spiegelung
    gar nicht im Suchraum.
    """
    n = len(paare)
    if n < 2:
        return None
    sx = sy = sxx = syy = 0.0
    sgx = sgy = sxgx = sygy = sxgy = sygx = 0.0
    for (x, y), (gx, gy) in paare:
        sx += x
        sy += y
        sgx += gx
        sgy += gy
        sxgx += x * gx
        sygy += y * gy
        sxgy += x * gy
        sygx += y * gx
        sxx += x * x
        syy += y * y
    nenner = n * (sxx + syy) - sx * sx - sy * sy
    if abs(nenner) < 1e-9:
        return None
    a = (n * (sxgx + sygy) - sx * sgx - sy * sgy) / nenner
    b = (n * (sxgy - sygx) - sx * sgy + sy * sgx) / nenner
    e = (sgx - a * sx + b * sy) / n
    f = (sgy - b * sx - a * sy) / n
    return a, b, e, f


def _reste(paare, koeff) -> list[float]:
    a, b, e, f = koeff
    return [math.hypot(a * x - b * y + e - gx, b * x + a * y + f - gy)
            for (x, y), (gx, gy) in paare]


def passung_rechnen(im: Image.Image, bahnen: list, ton: int | None = None
                    ) -> GroundPassung | None:
    """Die vollstaendige Kette. ``None``, wenn eine Pruefung nicht besteht.

    **Eine Karte, die eine Pruefung nicht besteht, wird nicht angezeigt** -- dieselbe Regel
    wie bei den Sichtflugkarten. Eine falsch liegende Flugplatzkarte ist schlimmer als gar
    keine, weil sie im Rollverkehr geglaubt wird.
    """
    if not bahnen:
        return None
    if ton is None:
        ton = bahnfarbe(im)
    if ton is None:
        return None

    flaechen = bahnflaechen(im, ton)
    if not flaechen:
        return None

    # Grobskala fuer die Meter-Toleranzen: laengste Referenzbahn gegen laengste Flaeche.
    roh_achsen = [hauptachse(f) for f in flaechen]
    roh_achsen = [a for a in roh_achsen
                  if a.breite >= 4 and a.laenge / max(a.breite, 1e-6) >= SCHLANKHEIT_MINDEST]
    if not roh_achsen:
        return None
    laengste_px = max(a.laenge for a in roh_achsen)
    laengste_m = max(b.laenge for b in bahnen)
    mps_grob = laengste_m / max(laengste_px, 1.0)

    for a in roh_achsen:
        enden_tasten(im, ton, a, mps_grob)
    achsen = achsen_zusammenfassen([a for a in roh_achsen if a.gueltig], mps_grob)
    achsen.sort(key=lambda a: -a.voll)
    achsen = achsen[:5]
    if not achsen:
        return None

    bezug = bahnen[0].le
    ziel = {b.name: (runway_ref.meter(bezug, b.le), runway_ref.meter(bezug, b.he))
            for b in bahnen}

    bestes = None
    # **Beide Seiten permutieren.** Der Prototyp nahm auf der Bildseite immer die laengsten
    # Achsen; eine lange Nicht-Bahn im Bahnton (Vorfeldkante, auf Rollkarten ein
    # Rollleitlinien-Band) verdraengte dann eine echte Bahn, und keine Permutation der
    # anderen Seite konnte das heilen.
    for anzahl in range(min(len(achsen), len(bahnen)), 0, -1):
        for bild_wahl in itertools.combinations(range(len(achsen)), anzahl):
            for ref_wahl in itertools.permutations(range(len(bahnen)), anzahl):
                for drehungen in itertools.product((False, True), repeat=anzahl):
                    for getrimmt in (False, True):
                        ergebnis = _versuch(achsen, bahnen, ziel, bild_wahl, ref_wahl,
                                            drehungen, getrimmt)
                        if ergebnis is None:
                            continue
                        if bestes is None or ergebnis[0] < bestes[0]:
                            bestes = ergebnis
        if bestes is not None:
            break            # mit der groesstmoeglichen Zahl von Bahnen zufrieden geben

    if bestes is None:
        return None
    rest_max, koeff, punkte, benutzte = bestes
    if rest_max > REST_SCHRANKE_M:
        logger.info("Flugplatzkarte: Restfehler %.1f m ueber der Schranke von %.1f m",
                    rest_max, REST_SCHRANKE_M)
        return None

    a, b, _e, _f = koeff
    mps = math.hypot(a, b)
    drehung = (-math.degrees(math.atan2(b, a))) % 360.0
    ost = [v for i in benutzte for v in (ziel[bahnen[i].name][0][0], ziel[bahnen[i].name][1][0])]
    nord = [v for i in benutzte for v in (ziel[bahnen[i].name][0][1], ziel[bahnen[i].name][1][1])]
    return GroundPassung(drehung=drehung, mps=mps, rest_max=rest_max,
                         bahnen=len(benutzte), punkte=punkte, koeff=koeff, bezug=bezug,
                         huelle_m=(min(ost), max(ost), min(nord), max(nord)))


def _versuch(achsen, bahnen, ziel, bild_wahl, ref_wahl, drehungen, getrimmt=False):
    """Eine konkrete Zuordnung durchrechnen. ``None``, wenn eine Pruefung sie abweist.

    ``getrimmt=True`` setzt die Passpunkte auf **Mitte plus/minus halbe Referenzlaenge**
    statt auf die abgetasteten Enden.

    **Wofuer das gebraucht wird.** Stopways und Blast Pads schliessen gleichfarbig an die
    Bahn an und werden immer mitgemessen -- bei EDDV 2784 m fuer eine 2340-m-Bahn, bei EDDS
    6759 m fuer 3345 m. Die ACHSE ist davon unberuehrt (Parallelbahnen stimmen auf 0,01
    Grad), und die Trimmung ist an beiden Enden aehnlich, also bleibt auch die MITTE
    brauchbar. Nur die Laenge ist es nicht -- und die steht in der Referenz.

    Das ist kein Freibrief: Der Restfehler prueft danach weiterhin die Lage der Bahnen
    ZUEINANDER, und die kann eine erzwungene Laenge nicht schoenrechnen.
    """
    paare = []
    skalen = []
    # Skala des ganzen Satzes: die groesste der einzelnen Bahnskalen (siehe unten, warum).
    kandidaten = [bahnen[ri].laenge / achsen[bi].voll
                  for bi, ri in zip(bild_wahl, ref_wahl)
                  if achsen[bi].voll > 1 and not achsen[bi].ra and not achsen[bi].rb]
    mps_satz = max(kandidaten) if kandidaten else None
    if getrimmt and mps_satz is None:
        return None
    for k, (bi, ri) in enumerate(zip(bild_wahl, ref_wahl)):
        a = achsen[bi]
        name = bahnen[ri].name
        m_le, m_he = ziel[name]
        z_a, z_b = (m_he, m_le) if drehungen[k] else (m_le, m_he)
        if getrimmt:
            if a.ra or a.rb or a.voll <= 1:
                continue          # an einem Rand abgeschnitten: die Mitte sagt nichts
            # Die Skala muss von der am WENIGSTEN verfaelschten Bahn kommen, nicht von
            # dieser. Ein Malfehler macht die gemessene Laenge zu gross und damit die
            # Skala (Referenz durch Bild) zu klein -- die groesste Skala im Satz ist also
            # die verlaesslichste. Der erste Anlauf leitete sie aus derselben Bahn ab und
            # war damit zirkulaer: halb_px kam wieder auf a.voll/2 heraus und die Trimmung
            # aenderte nichts.
            halb_px = (bahnen[ri].laenge / mps_satz) / 2.0
            mitte_u = (a.ua + a.ub) / 2.0
            ca, sa = math.cos(a.winkel_rad), math.sin(a.winkel_rad)
            p_a = (a.cx + (mitte_u - halb_px) * ca, a.cy + (mitte_u - halb_px) * sa)
            p_b = (a.cx + (mitte_u + halb_px) * ca, a.cy + (mitte_u + halb_px) * sa)
            paare.append((p_a, z_a))
            paare.append((p_b, z_b))
            continue
        if not a.ra:
            paare.append((a.pa, z_a))
        if not a.rb:
            paare.append((a.pb, z_b))
        if not a.ra and not a.rb and a.voll > 1:
            skalen.append((bahnen[ri].laenge / a.voll, bahnen[ri].laenge))

    # Pruefung 1: mindestens vier Passpunkte. Zwei bestimmen die Passung exakt und lassen
    # keinen Restfehler uebrig -- sie ist dann unpruefbar, nicht richtig.
    if len(paare) < PASSPUNKTE_MINDEST:
        return None

    # Pruefung 3: y-Spiegelung. Bildkoordinaten laufen nach unten, Nordmeter nach oben.
    gespiegelt = [((x, -y), z) for (x, y), z in paare]
    koeff = aehnlich(gespiegelt)
    if koeff is None:
        return None
    a_, b_, _, _ = koeff

    # Pruefung 4: Nordung. Verworfen wird nur (100, 260) -- nicht (90, 270). EDDH liegt bei
    # gemessenen 89,97 Grad, also 0,03 neben der strengen Kante, bei einem Achsrauschen von
    # 0,01 bis 0,06. Ob die richtige Passung durchkaeme, entschiede dort der Zufall. Der
    # Zweck ist allein, die 180-Grad-Alternative auszuschliessen; dafuer genuegt jede Marge.
    nordung = (-math.degrees(math.atan2(b_, a_))) % 360.0
    if NORDUNG_VERWERFEN[0] < nordung < NORDUNG_VERWERFEN[1]:
        return None

    # Pruefung 5: Massstabskonsistenz -- gegen den Fit, nicht nur untereinander. Ein
    # Vergleich der Bahnskalen miteinander schaltet sich still ab, sobald nur EINE Bahn
    # unverstuemmelt ist. Die Schranke ist ueber die Bahnlaenge gestaffelt: Der Malfehler
    # an den Enden (Stopways, Blast Pads) ist additiv, sein Anteil also umgekehrt
    # proportional zur Laenge -- eine feste Prozentzahl verwirft bevorzugt richtige
    # Passungen kurzer Bahnen.
    fit_skala = math.hypot(a_, b_)
    for skala, laenge in skalen:
        erlaubt = max(SKALA_MINDESTSPIEL, SKALA_GRUNDFEHLER_M / max(laenge, 1.0))
        if abs(skala - fit_skala) / max(fit_skala, 1e-9) > erlaubt:
            return None

    reste = _reste(gespiegelt, koeff)
    return max(reste), koeff, len(paare), list(ref_wahl)


# --------------------------------------------------------------------------- Nordung
def norden(roh: bytes, p: GroundPassung) -> tuple[bytes, dict] | None:
    """Blatt genordet ablegen und seine Grenzen ausrechnen.

    ``L.imageOverlay`` kann nicht rotieren, die DFS-Blaetter sind aber nach der
    Bahnrichtung gesetzt (EDDL um 37 Grad, EDDM um 6,5). Gedreht wird deshalb hier, einmal
    beim Ablegen.

    **Die Fuellflaeche ist durchsichtig, nicht weiss.** ``expand=True`` laesst an den Ecken
    Flaeche frei; bei 37 Grad ist das rund die Haelfte des abgelegten Rechtecks. Weiss
    gefuellt laege ein grosses Dreieckspaar halbdeckend ueber der Umgebung des Platzes. Die
    quer gedruckten Sichtflugkarten kennen das Problem nicht -- 90 Grad drehen laesst nichts
    frei.

    **Das Blatt waechst erheblich:** bei 37,2 Grad um 102 bis 171 Prozent, je nach
    Seitenverhaeltnis.

    **Vorzeichen:** ``Image.rotate(w)`` dreht gegen den Uhrzeigersinn. Das Blatt ist um
    ``drehung`` im Uhrzeigersinn gegen Nord verdreht, also wird ``-drehung`` uebergeben --
    was hier als ``360 - drehung`` erscheint. Die Gegenprobe steht im Test.
    """
    try:
        quelle = Image.open(io.BytesIO(roh)).convert("RGBA")
    except Exception:
        return None
    breite, hoehe = quelle.size
    gedreht = quelle.rotate(-p.drehung, resample=Image.BICUBIC, expand=True,
                            fillcolor=(0, 0, 0, 0))
    puffer = io.BytesIO()
    gedreht.save(puffer, "PNG")

    # Die vier Blattecken durch die Passung schicken und die Huellbox bilden. Nicht die
    # ideale Formel annehmen: PIL rundet Groesse und Versatz, und eine Abweichung von
    # einem Pixel sind hier rund 1,6 m.
    a, b, e, f = p.koeff
    ecken_m = []
    for x, y in ((0, 0), (breite, 0), (0, hoehe), (breite, hoehe)):
        ys = -y
        ecken_m.append((a * x - b * ys + e, b * x + a * ys + f))
    ost = [q[0] for q in ecken_m]
    nord = [q[1] for q in ecken_m]
    grenzen = _grenzen_in_grad(p.bezug, min(ost), max(ost), min(nord), max(nord))

    o0, o1, n0, n1 = p.huelle_m
    feld = _grenzen_in_grad(p.bezug, o0 - FELD_SAUM_M, o1 + FELD_SAUM_M,
                            n0 - FELD_SAUM_M, n1 + FELD_SAUM_M)
    grenzen.update({f"feld_{k}": v for k, v in feld.items()})
    return puffer.getvalue(), grenzen


def _grenzen_in_grad(bezug, ost_min, ost_max, nord_min, nord_max) -> dict:
    m_lon, m_lat = runway_ref.meter_je_grad(bezug[0])
    return {"sued": bezug[0] + nord_min / m_lat, "nord": bezug[0] + nord_max / m_lat,
            "west": bezug[1] + ost_min / m_lon, "ost": bezug[1] + ost_max / m_lon}


# --------------------------------------------------------------------------- Kartensorte
# --------------------------------------------------------------------------- Kartensorte
# Die Sorte steckt im Bahnton selbst. Gemessen am 31.08.2026 ueber 30 Blaetter von 14
# Verkehrsflughaefen:
#
#   153/154 -> 15 Blaetter, darunter beide belegten Flugplatzkarten (EDDL, EDDM)
#   179/180 ->  8 Blaetter, darunter beide belegten Rollkarten (EDDM, EDDV)
#   194-210 ->  4 Blaetter anderer Art (Anflugkarten und dergleichen)
#
# Keine einzige Ueberschneidung. Das ist belegbar und kostet nichts -- der Ton wird ohnehin
# gemessen.
#
# Der zuerst gebaute Weg ueber den Titelkasten oben links traegt NICHT: Der Kopf steht nicht
# bei allen Blaettern an derselben Stelle (EDDL, EDDM, EDDB bei y 53; EDDV bei y 149), und
# es gibt mindestens zwei Setzungsvarianten. Das war die als offen vermerkte Schwaeche aus
# Abschnitt 4.2 der Spec -- sie ist damit nicht behoben, sondern umgangen.
SORTE_TON = {
    "flugplatzkarte": (150, 158),
    "rollkarte": (176, 184),
}


def sorte_aus_ton(ton: int | None) -> str | None:
    """Welche Kartensorte dieser Bahnton bedeutet. ``None`` heisst: keine von beiden."""
    if ton is None:
        return None
    for name, (tief, hoch) in SORTE_TON.items():
        if tief <= ton <= hoch:
            return name
    return None


def sorte_erkennen(im: Image.Image) -> str | None:
    """Kartensorte eines Blattes -- ohne ein Zeichen zu lesen."""
    return sorte_aus_ton(bahnfarbe(im))
