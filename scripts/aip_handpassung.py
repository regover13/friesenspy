#!/usr/bin/env python3
"""Aus abgelesenen Tick-Werten eine geprüfte Passung rechnen und ablegen.

Aufruf:
    python scripts/aip_handpassung.py EDAH --breite 315=54:00,534=53:55 --laenge 764=14:20
    ... --schreiben          legt sie ab; ohne das Flag ist es ein Probelauf
    ... --rahmen l,o,r,u,bl,bo,br,bu   erzwingt einen Rahmen (s. unten)

Womit man die Zahlen findet: ``scripts/aip_band_zeigen.py`` rendert das Randband eines
Blattes gross und beziffert die erkannten Ticks -- die Positionen von dort kommen hier
als ``<pixel>=<grad>:<minute>`` herein.

**Wozu es das ueberhaupt gibt.** Die Automatik erkennt rund zwei Drittel der 446 Blaetter
(283 am 25.08.2026). Der Rest scheitert nicht am Prinzip, sondern an gedruckten
Einzelheiten: zu schwache Rahmenlinie, Gradnetz von Kartensymbolen ueberdeckt, Zahlen zu
klein gesetzt. Sie von Hand zu setzen ist Fleissarbeit, aber sie haelt: Der woechentliche
AIRAC-Lauf erhaelt eine Handpassung, solange sich die Blattgeometrie nicht aendert
(``hand_behalten`` in scripts/aip_bestand.py).

**Die Ablesung kommt vom Menschen, die Geometrie vom Code, und geprueft wird beides.** Vor
dem Schreiben laufen dieselben Proben wie in der Automatik plus zwei eigene -- eine falsch
abgelesene Ziffer soll hier genauso auffallen wie dort. In der Nacht zum 25.08.2026 haben
sie jeden einzelnen Fehler gefangen (sechs eigene Rechenfehler, dazu jede Fehlablesung der
Lese-Agenten); keine falsche Passung ist in die Datenbank gelangt.

Die Proben im Einzelnen:

1. **Skala gegen Raster** -- der aus den Zahlen folgende Pixelabstand je Bogenminute muss
   ein ganzzahliges Vielfaches des gemessenen Rasterabstands sein.
   *Ausnahme:* Liegen MINDESTENS DREI Ablesungen auf einer Geraden (Residuum < 2 px), tragen
   sie die Skala selbst und duerfen das gemessene Raster verwerfen -- das ist manchmal aus
   zwei Stoerstrichen entstanden und selbst der Fehler (EDUW mass 127 px statt 146, EDVI 41
   statt 146). Bei nur zwei Ablesungen bleibt die Probe zwingend: dort liegt die Gerade
   zwangslaeufig exakt und pruefte sich selbst.
2. **Residuen** -- ab drei Stuetzstellen faellt ein einzelner Ziffernfehler hier auf.
3. **cos-Probe** -- ``cos(Breite) = |m_lat| / |m_lon|``, gerechnet aus den ABGELEITETEN
   Maszstaeben, nicht aus den rohen Rasterabstaenden (die Achsen sind oft verschieden fein).
4. **Lagetest** -- der Platz muss im Kartenfeld liegen. Faellt er durch, wird die Koordinate
   gegen OpenAIP gegengeprueft, bevor verworfen wird: ``airportsdata`` liegt bei einzelnen
   Plaetzen daneben (EDGL 7 km, EDTK 30 km, EDSD 100 km).
5. **genordet** -- ``m_lat < 0 < m_lon``.

``--rahmen`` ist fuer Blaetter, bei denen ``rahmen_finden`` scheitert, weil eine Seite des
Doppelrahmens zu schwach gedruckt ist (EDLS, EDEL, EDMP, EDPS). Die acht Zahlen sind
``links,oben,rechts,unten,band_links,band_oben,band_rechts,band_unten``; die inneren stehen
in der Linienliste, die aeusseren liegen rund 24 px weiter aussen.
"""
import argparse, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app import aip_charts as A
from app import geo

def _openaip(code):
    """Koordinate aus OpenAIP. None, wenn kein Schluessel oder kein Treffer."""
    try:
        import httpx
        from app.config import get_settings
        schluessel = get_settings().OPENAIP_API_KEY
        if not schluessel: return None
        r = httpx.get("https://api.core.openaip.net/api/airports",
                      params={"search": code, "limit": 5},
                      headers={"x-openaip-api-key": schluessel,
                               "User-Agent": "FriesenSpy/AIP-Kartenabgleich"}, timeout=25.0)
        r.raise_for_status()
        for e in r.json().get("items", []):
            if (e.get("icaoCode") or "").upper() == code:
                g = e.get("geometry", {}).get("coordinates") or []
                if len(g) >= 2: return (float(g[1]), float(g[0]))
    except Exception:
        return None
    return None


def werte(text):
    out = []
    for teil in text.split(","):
        pos, wert = teil.split("=")
        g, m = wert.split(":")
        out.append((float(pos), int(g) + int(m) / 60.0))
    return sorted(out)

def gerade(paare, d_px, achse, vielfach=1.0):
    """Steigung und Achsenabschnitt. Bei EINEM Punkt kommt die Steigung aus dem Raster."""
    if len(paare) >= 2:
        (x1, y1), (x2, y2) = paare[0], paare[-1]
        # Zwei Ablesungen mit demselben Wert sind keine zwei Stuetzstellen. Das passiert,
        # wenn jemand (oder ein Lesemodell) die Beschriftung des Nachbarticks noch einmal
        # abliest, statt der roten Marke zu folgen -- am 24.08.2026 von einem Haiku-Agenten
        # dreimal in Folge geliefert. Ohne diese Pruefung teilt die Steigung durch null.
        if abs(y2 - y1) < 1e-9 or abs(x2 - x1) < 1e-9:
            return None, None, "zwei gleiche Werte -- keine gueltige Ablesung"
        m = (y2 - y1) / (x2 - x1)
        return m, y1 - m * x1, "aus zwei Ablesungen"
    (x1, y1), = paare
    # Das VORZEICHEN gehoert hierher, nicht hinter den Aufruf: Wer die Steigung erst danach
    # umdreht, laesst den Achsenabschnitt bei der alten stehen -- die Gerade passt dann nicht
    # mehr zusammen. Bei EDBC schob das die Karte 36 Bogenminuten nach Sueden (24.08.2026);
    # gefangen hat es der Lagetest, aber gerechnet war es falsch.
    #
    # ``vielfach`` ist, wie viele Bogenminuten EIN Tick traegt. Das ist nicht immer eine:
    # Auf gut einem Dutzend Blaettern steht alle fuenf Minuten ein Strich, und die Annahme
    # "ein Tick = eine Minute" macht die Steigung um denselben Faktor zu klein. Sichtbar
    # wurde das als cos-Probe mit `nan` -- das Achsenverhaeltnis lag dann ueber eins.
    m = (-1.0 if achse == "B" else 1.0) * vielfach / (60.0 * d_px)
    return m, y1 - m * x1, f"Steigung aus dem Rasterabstand ({vielfach:g}' je Tick)"

ap = argparse.ArgumentParser()
ap.add_argument("icao")
ap.add_argument("--breite", required=True)
ap.add_argument("--laenge", required=True)
ap.add_argument("--schreiben", action="store_true")
ap.add_argument("--blatt", default=None,
                help="PNG direkt angeben, statt es ueber die Einstellungen zu suchen "
                     "(nur fuer Probelaeufe -- --schreiben braucht ohnehin die Datenbank)")
ap.add_argument("--rahmen", default=None,
                help="links,oben,rechts,unten,band_links,band_oben,band_rechts,band_unten -- "
                     "erzwingt diesen Rahmen statt der Automatik (fuer Blaetter, bei denen "
                     "eine Seite des Doppelrahmens zu schwach gedruckt ist, um sie zu finden)")
a = ap.parse_args()
icao = a.icao.upper()

from app.config import get_settings as _gs
im = Image.open(a.blatt or A.blatt_pfad(_gs().DB_PATH, icao)).convert("L")
if a.rahmen:
    werte8 = [float(x) for x in a.rahmen.split(",")]
    r = A.Rahmen(*werte8)
else:
    r = A.rahmen_finden(im)
ty, _by, tx, _bx = A.tick_positionen_mit_band(im, r)  # beide Baender je Achse
dy, _n, _a = A.raster(ty); dx, _n2, _a2 = A.raster(tx)
bp, lp = werte(a.breite), werte(a.laenge)

# --- Rasterabstand gegenpruefen und noetigenfalls berichtigen ---------------------------
#
# `raster()` greift daneben, wenn es auf einer Achse nur zwei Ticks findet oder wenn das
# Gitter Luecken hat: Bei EDWE lieferte es 263 px, der echte Abstand ist 44 (263 = 6 x 44);
# bei EDUW 127 statt 146, bei EDCQ 181 statt 135. Eine einzelne Ablesung stuetzt ihre
# Steigung genau auf diesen Wert -- ist er falsch, ist die ganze Passung falsch.
#
# Berichtigt wird ueber die Physik, nicht ueber ein Raten: Eine Bogenminute Laenge ist um
# cos(Breite) kuerzer als eine Bogenminute Breite, also muss dx/dy = cos(Breite) gelten.
# Weicht das ab, wird geprueft, ob eine der beiden Groessen ein ganzzahliges Vielfaches der
# Wahrheit ist. Nur bei einem SAUBEREN ganzzahligen Faktor (unter zwei Prozent Abweichung)
# wird korrigiert -- sonst bleibt es beim gemessenen Wert und die Proben lehnen ab.
_k = geo.icao_to_coords(icao)
if _k:
    _cos = math.cos(math.radians(_k[0]))
    if dy and dx and abs(dx / dy - _cos) > 0.02:
        for _n in range(2, 13):
            if abs((dx / (dy / _n)) - _cos) < 0.02 * _cos:
                print(f"   BERICHTIGT  Breiten-Raster {dy:.1f} -> {dy/_n:.1f} px "
                      f"(gemessen war das {_n}-fache; cos-Beziehung zur Laenge)")
                dy = dy / _n
                break
            if abs(((dx / _n) / dy) - _cos) < 0.02 * _cos:
                print(f"   BERICHTIGT  Laengen-Raster {dx:.1f} -> {dx/_n:.1f} px "
                      f"(gemessen war das {_n}-fache; cos-Beziehung zur Breite)")
                dx = dx / _n
                break


m_lat, b_lat, wie_lat = gerade(bp, dy, "B")
if len(bp) < 2 and len(lp) >= 2:
    # Umgekehrt derselbe Fall: eine einzelne BREITEN-Ablesung, Vielfaches ueber die Laenge.
    (u1, v1), (u2, v2) = lp[0], lp[-1]
    if abs(u2 - u1) > 1e-9:
        ml = (v2 - v1) / (u2 - u1)
        koord = geo.icao_to_coords(icao)
        ziel = math.cos(math.radians(koord[0])) if koord else 1.0
        bester, fehler = 1.0, None
        for k in (1.0, 2.0, 5.0, 10.0):
            mk = k / (60.0 * dy)
            d = abs(mk / abs(ml) - ziel)
            if fehler is None or d < fehler:
                bester, fehler = k, d
        if bester != 1.0:
            m_lat, b_lat, wie_lat = gerade(bp, dy, "B", bester)
if m_lat is None:
    print(f"  Breite: {wie_lat}\n-> nicht geschrieben"); sys.exit(1)
m_lon, b_lon, wie_lon = gerade(lp, dx, "L")
if len(lp) < 2 and m_lat is not None:
    # Welches Vielfache macht die cos-Probe stimmig? cos(Breite) = |m_lat| / |m_lon|.
    # Geprueft wird gegen die PLATZbreite, also gegen eine unabhaengige Groesse -- das
    # Vielfache wird damit nicht geraten, sondern bestimmt.
    ziel = math.cos(math.radians(geo.icao_to_coords(icao)[0] if geo.icao_to_coords(icao)
                                 else lp[0][1]))
    bester, fehler = 1.0, None
    for k in (1.0, 2.0, 5.0, 10.0):
        mk = k / (60.0 * dx)
        d = abs(abs(m_lat) / mk - ziel)
        if fehler is None or d < fehler:
            bester, fehler = k, d
    if bester != 1.0:
        m_lon, b_lon, wie_lon = gerade(lp, dx, "L", bester)
if m_lon is None:
    print(f"  Laenge: {wie_lon}\n-> nicht geschrieben"); sys.exit(1)

fn, fs = m_lat * r.oben + b_lat, m_lat * r.unten + b_lat
fw, fo = m_lon * r.links + b_lon, m_lon * r.rechts + b_lon
# airportsdata kennt 29 der 446 Plaetze nicht -- dieselbe Luecke wie in
# scripts/aip_bestand.py, und derselbe Rueckfall: OpenAIP. Ohne Koordinate gibt es keinen
# Lagetest, und ohne Lagetest wird hier nichts geschrieben.
koord = geo.icao_to_coords(icao)
if koord is None:
    import httpx
    from app.config import get_settings
    schluessel = get_settings().OPENAIP_API_KEY
    if not schluessel:
        print(f"{icao}: keine Koordinate und kein OpenAIP-Schluessel -> nicht geschrieben")
        sys.exit(1)
    r2 = httpx.get("https://api.core.openaip.net/api/airports",
                   params={"search": icao, "limit": 5},
                   headers={"x-openaip-api-key": schluessel,
                            "User-Agent": "FriesenSpy/AIP-Kartenabgleich"}, timeout=25.0)
    r2.raise_for_status()
    for e in r2.json().get("items", []):
        if (e.get("icaoCode") or "").upper() == icao:
            g = e.get("geometry", {}).get("coordinates") or []
            if len(g) >= 2: koord = (float(g[1]), float(g[0]))
            break
    if koord is None:
        print(f"{icao}: OpenAIP kennt den Platz nicht -> nicht geschrieben"); sys.exit(1)
    print(f"  Koordinate ueber OpenAIP: {koord[0]:.4f}, {koord[1]:.4f}")
lat, lon = koord

print(f"{icao}  Rahmen {r.links:.0f},{r.oben:.0f} .. {r.rechts:.0f},{r.unten:.0f}  Blatt {im.size}")
print(f"  Breite: {wie_lat}, {len(bp)} Punkt(e)")
print(f"  Laenge: {wie_lon}, {len(lp)} Punkt(e)")
def _residuum(punkte, m, b):
    """Groesste Abweichung der Stuetzstellen von der Geraden, in PIXEL."""
    if not punkte or abs(m) < 1e-12:
        return None
    return max(abs((v - b) / m - u) for u, v in punkte)

proben = []
# (1) Passt die abgelesene Skala zum gemessenen Rasterabstand?
#
# **Wenn nicht, entscheidet die Zahl der Stuetzstellen, wer recht hat.** Der gemessene
# Rasterabstand stammt manchmal aus nur zwei oder drei erkannten Strichen und ist dann selbst
# der Fehler: Bei EDUW lieferte die Messung 127 px, bei EDVI 41 px, waehrend fuenf bzw. sieben
# fortlaufend beschriftete Ticks uebereinstimmend 145,6 px je Bogenminute ergaben und die
# cos-Probe das auf 0,13 Grad bestaetigte. Liegen MINDESTENS DREI Ablesungen auf einer
# Geraden (Residuum unter 2 px), tragen sie die Skala selbst -- die Rasterprobe darf dann
# nicht mehr veto einlegen. Bei nur zwei Ablesungen bleibt sie zwingend: dort liegt die
# Gerade zwangslaeufig exakt und pruefte sich selbst.
for name, m, d, punkte in (("Breite", m_lat, dy, bp), ("Laenge", m_lon, dx, lp)):
    behauptet = 1.0 / (60.0 * abs(m))
    res = _residuum(punkte, m, b_lat if name == "Breite" else b_lon)
    if d is None:
        # Kein Raster automatisch gefunden (der Tickstrich reicht nicht ueber die volle
        # Bandbreite -- so bei EDBX, EDOC, EDVC, EDWJ, EDXO). Ohne Gegenprobe traegt dann
        # allein die Geradengleichheit der Ablesungen; die verlangt mindestens drei.
        if len(punkte) >= 3 and res is not None and res <= 2.0:
            proben.append((f"{name}: Skala aus {len(punkte)} Ablesungen "
                           f"(Residuum {res:.2f} px); kein Raster automatisch gefunden, "
                           f"also ungegengeprueft", True))
        else:
            proben.append((f"{name}: kein Raster gefunden und zu wenige Ablesungen "
                           f"fuer eine Gegenprobe ({len(punkte)})", False))
        continue
    v = round(d / behauptet) if behauptet > 0 else 0
    ok = v >= 1 and abs(d - v * behauptet) <= 2.0
    if ok:
        proben.append((f"{name}: Skala passt zum Raster "
                       f"({d:.2f} px = {v} Bogenminute(n))", True))
    elif len(punkte) >= 3 and res is not None and res <= 2.0:
        proben.append((f"{name}: Skala aus {len(punkte)} Ablesungen "
                       f"(Residuum {res:.2f} px); gemessenes Raster {d:.2f} px passt NICHT "
                       f"und wird verworfen", True))
    else:
        proben.append((f"{name}: Skala passt zum Raster "
                       f"({d:.2f} px = {v} Bogenminute(n))", False))
# (1b) Residuen, wo genug Stuetzstellen da sind -- ein einzelner Ziffernfehler faellt hier auf.
for name, m, b, punkte in (("Breite", m_lat, b_lat, bp), ("Laenge", m_lon, b_lon, lp)):
    if len(punkte) >= 3:
        res = _residuum(punkte, m, b)
        proben.append((f"{name}: {len(punkte)} Stuetzstellen auf einer Geraden "
                       f"(groesste Abweichung {res:.2f} px)", res <= 2.0))
# (2) cos-Probe -- aus den ABGELEITETEN Maßstaeben, nicht aus den rohen Rasterabstaenden.
# Die beiden Achsen sind oft verschieden fein gerastert (eine Bogenminute je Tick auf der
# einen, fuenf auf der anderen); dx/dy roh ergibt dann Unsinn und bei dx > dy sogar nan.
# Physikalisch gilt: eine Bogenminute Laenge ist um cos(Breite) kuerzer als eine Bogenminute
# Breite -- also cos(Breite) = |m_lat| / |m_lon|, ganz ohne Vielfache.
v = abs(m_lat) / abs(m_lon) if m_lon else 0
winkel = math.degrees(math.acos(v)) if 0 < v < 1 else float("nan")
proben.append((f"cos-Probe: {winkel:.2f}° gegen Platz {lat:.2f}°", abs(winkel - lat) < 1.5))
# (3) Liegt der Platz im Kartenfeld?
#
# Faellt der Test durch, wird die Koordinate GEGENGEPRUEFT, bevor die Passung verworfen wird:
# airportsdata liegt bei einzelnen Plaetzen daneben. EDGL etwa ist der Hubschrauber-
# Landeplatz der BG-Unfallklinik Ludwigshafen; dort steht 49,413/8,352, tatsaechlich liegt er
# rund sieben Kilometer weiter nordoestlich (24.08.2026). Nicht das Blatt war falsch, sondern
# der Bezugspunkt. Zwei unabhaengige Quellen, und das Feld muss mindestens eine enthalten --
# die Probe behaelt damit ihre Kraft gegen eine verlesene Zahl.
drin = fs < lat < fn and fw < lon < fo
if not drin:
    zweit = _openaip(icao)
    if zweit and fs < zweit[0] < fn and fw < zweit[1] < fo:
        print(f"   HINWEIS  airportsdata nennt {lat:.4f},{lon:.4f} -- OpenAIP {zweit[0]:.4f},"
              f"{zweit[1]:.4f} liegt im Feld, damit wird gerechnet")
        lat, lon = zweit
        drin = True
proben.append((f"Platz im Feld ({fs:.4f}..{fn:.4f}, {fw:.4f}..{fo:.4f})", drin))
# (4) genordet
proben.append(("genordet", m_lat < 0 < m_lon))
for text, ok in proben:
    print(f"   {'OK ' if ok else 'NEIN'}  {text}")
if not all(ok for _, ok in proben):
    print("\n-> nicht geschrieben, mindestens eine Probe faellt durch")
    sys.exit(1)
p = A.handpassung(breite_px=im.size[0], hoehe_px=im.size[1],
                  links_px=r.links, oben_px=r.oben, rechts_px=r.rechts, unten_px=r.unten,
                  feld_nord=fn, feld_sued=fs, feld_west=fw, feld_ost=fo)
if p is None:
    print("\n-> handpassung() lehnt ab"); sys.exit(1)
print(f"\nBlattgrenzen: N {p.nord:.5f}  S {p.sued:.5f}  W {p.west:.5f}  O {p.ost:.5f}")
if not a.schreiben:
    print("(Probelauf -- mit --schreiben wird abgelegt)")
    sys.exit(0)
from app.database import get_connection, get_aip_chart, upsert_aip_chart
conn = get_connection("/opt/friesenspy/data/friesenspy.db")
alt_z = get_aip_chart(conn, icao)
if alt_z is None:
    print("kein Bestandseintrag -- nichts geschrieben"); sys.exit(1)
upsert_aip_chart(conn, icao, bild_hash=alt_z["bild_hash"],
                 nord=p.nord, sued=p.sued, west=p.west, ost=p.ost,
                 feld_nord=p.feld_nord, feld_sued=p.feld_sued,
                 feld_west=p.feld_west, feld_ost=p.feld_ost,
                 rahmen_px=p.rahmen_px, tick_px_lat=p.tick_px_lat,
                 tick_px_lon=p.tick_px_lon, quelle="hand",
                 airac=alt_z["airac"], status="gepasst")
conn.commit(); conn.close()
print("-> abgelegt als quelle=hand, status=gepasst")
