#!/usr/bin/env python3
"""Das Randband eines AIP-Blattes gross rendern, damit ein Mensch die Gradzahlen liest.

Aufruf:
    python scripts/aip_band_zeigen.py ETND L          # Laengenband (waagerecht)
    python scripts/aip_band_zeigen.py ETND B          # Breitenband (senkrecht)
    python scripts/aip_band_zeigen.py EDLS B --rahmen 132,215,839.5,922.5,108.5,191.5,863,946
    python scripts/aip_band_zeigen.py EDNY L --faktor 2 --breite 1400

Herausgeschrieben wird ``/tmp/aip_band_<ICAO>_<B|L>.png``. Die erkannten Tickpositionen
stehen als rote Linien im Bild und als Zahl darunter -- **diese Zahl ist es, die danach in
``aip_handpassung.py`` eingesetzt wird**, zusammen mit dem Gradwert, dessen Grad/Minuten-
Grenze auf der roten Linie liegt.

**Warum die Ticks eingezeichnet sein muessen.** Die Laengenbeschriftung steht als „13°|44'"
*um* den Strich herum und ragt bei feinem Raster in die Nachbarfenster. Ohne Marke ist nicht
zu sagen, zu welchem Tick eine Zahl gehoert -- ein Tick daneben sind schnell zwei Kilometer.

**Warum das Breitenband gedreht wird -- und in welche Richtung.** Es ist ein hoher, schmaler
Streifen; ungedreht ist er unlesbar. Gedreht wird mit ``rotate(90)``, also GEGEN den
Uhrzeigersinn: Damit waechst die Bildspalte mit der Bildzeile des Originals, und die roten
Marken sitzen auf ihren Ticks. Mit ``rotate(-90)`` sitzen sie gespiegelt dazu, und die
abgelesene Breite nimmt nach rechts scheinbar ZU statt ab -- am 25.08.2026 zuerst so gebaut
und erst am widersinnigen Verlauf bemerkt.

``--rahmen`` uebergibt einen Rahmen von Hand, wenn ``rahmen_finden`` scheitert; die acht
Zahlen sind dieselben wie in ``aip_handpassung.py``.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from app import aip_charts  # noqa: E402


def blatt_oeffnen(icao: str, pfad: str | None):
    """Das Blatt als Bild -- ueber ``--blatt`` oder ueber die Einstellungen.

    Der direkte Pfad ist nicht nur Bequemlichkeit: ``get_settings()`` verlangt ``SECRET_KEY``
    und die uebrigen Betriebsgeheimnisse, die nur im Container gesetzt sind. Ein
    Anzeige-Werkzeug soll auch auf einem Arbeitsplatz laufen, auf dem nur ein
    heruntergeladenes PNG liegt.
    """
    if pfad:
        return Image.open(pfad).convert("L")
    from app.config import get_settings
    return Image.open(aip_charts.blatt_pfad(get_settings().DB_PATH, icao)).convert("L")


def rahmen_holen(im, vorgabe: str | None):
    if vorgabe:
        werte = [float(x) for x in vorgabe.split(",")]
        if len(werte) != 8:
            raise SystemExit("--rahmen braucht acht Zahlen: l,o,r,u,bl,bo,br,bu")
        return aip_charts.Rahmen(*werte)
    return aip_charts.rahmen_finden(im)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("icao")
    ap.add_argument("achse", choices=("B", "L"), help="B = Breite (senkrecht), L = Laenge")
    ap.add_argument("--faktor", type=int, default=4, help="Vergroesserung (Vorgabe 4)")
    ap.add_argument("--breite", type=int, default=900, help="Zeilenbreite im Ausgabebild")
    ap.add_argument("--rahmen", default=None, help="l,o,r,u,bl,bo,br,bu von Hand")
    ap.add_argument("--blatt", default=None,
                    help="PNG direkt angeben, statt es ueber die Einstellungen zu suchen")
    a = ap.parse_args()

    icao = a.icao.upper()
    im = blatt_oeffnen(icao, a.blatt)
    r = rahmen_holen(im, a.rahmen)
    if r is None:
        raise SystemExit(f"{icao}: kein Rahmen gefunden -- mit --rahmen einen vorgeben")

    ty, band_y, tx, band_x = aip_charts.tick_positionen_mit_band(im, r)
    ticks, band = (ty, band_y) if a.achse == "B" else (tx, band_x)
    achse = "y" if a.achse == "B" else "x"
    innen, aussen = aip_charts.band_grenzen(r, achse, band)
    if innen is None or aussen is None:
        raise SystemExit(f"{icao}: Band {band!r} ist bei diesem Rahmen nicht bekannt")
    print(f"{icao} {a.achse}: Band={band}, {len(ticks)} Ticks, Bandgrenzen {innen}..{aussen}")

    if a.achse == "B":
        # rotate(90) = gegen den Uhrzeigersinn, s. Modul-Doku.
        aus = im.crop((int(innen), int(r.oben), int(aussen), int(r.unten)))
        aus = aus.rotate(90, expand=True)
        pos0 = r.oben
    else:
        aus = im.crop((int(r.links), int(innen), int(r.rechts), int(aussen)))
        pos0 = r.links

    aus = aus.resize((aus.size[0] * a.faktor, aus.size[1] * a.faktor), Image.LANCZOS)
    aus = aus.convert("RGB")
    d = ImageDraw.Draw(aus)
    for t in ticks:
        x = (t - pos0) * a.faktor
        d.line([(x, 0), (x, aus.size[1])], fill=(255, 0, 0), width=1)

    zeilen_hoehe = aus.size[1] + 22
    anzahl = (aus.size[0] + a.breite - 1) // a.breite
    blatt = Image.new("RGB", (a.breite, zeilen_hoehe * anzahl), "white")
    db = ImageDraw.Draw(blatt)
    for i in range(anzahl):
        teil = aus.crop((i * a.breite, 0, min((i + 1) * a.breite, aus.size[0]), aus.size[1]))
        blatt.paste(teil, (0, i * zeilen_hoehe))
        for t in ticks:
            x = (t - pos0) * a.faktor - i * a.breite
            if 0 <= x < a.breite:
                db.text((x - 14, i * zeilen_hoehe + aus.size[1] + 4),
                        f"{int(round(t))}", fill=(200, 0, 0))

    pfad = f"/tmp/aip_band_{icao}_{a.achse}.png"
    blatt.save(pfad)
    print(pfad, blatt.size)


if __name__ == "__main__":
    main()
