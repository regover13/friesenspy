"""Triage der Erkennungslücken-Liste (Skill ``track-diagnose``).

Liest den JSON-Export (siehe SKILL.md), misst je Fall das fragliche Ende und gruppiert nach
Schritt 0 und Schritt 1 der Prüfreihenfolge — beides reine Messungen. Schritt 2 braucht
Kontext und bleibt beim Assistenten.

**Sortiert, entscheidet aber nichts.** Auch ein Sammelbefund „126x Fall E" wird vom Nutzer
abgehakt, nicht von hier.

Rein: JSON rein, Gruppen raus. Kein DB-Zugriff, kein SSH.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.gps_legs import _GPS_FLYING_GS_KT, _GPS_GROUND_AGL_FT
from scripts.nearby_airports import (
    AirportRef,
    airportsdata_refs,
    find_code,
    load_ourairports,
    nearest,
)

GRUPPE_DUENN = "Zu dünn"
GRUPPE_ZZZZ = "ZZZZ"
GRUPPE_LUFT = "E"
GRUPPE_ANDERER = "D"
GRUPPE_KANDIDAT = "Kandidat"

# Der Detektor braucht mindestens einen Zustandswechsel (ON_GROUND -> AIRBORNE -> ON_GROUND).
# Bei weniger Samples ist jede Aussage über Start/Landung bedeutungslos.
MIN_TRACKPUNKTE = 3
# Flugplan-Platzhalter für „kein ICAO" — kein Platz, also nichts zu finden.
PLATZHALTER_CODE = "ZZZZ"
# Ab hier gilt ein Nachbarplatz als „der Punkt gehört dorthin" (Schritt 1).
NACHBAR_MAX_KM = 1.0


@dataclass(frozen=True)
class Ende:
    """Ein zu prüfendes Ende eines Falls. ``missing: "both"`` ergibt zwei davon."""

    statsim_id: int
    callsign: str
    seite: str            # "departure" | "arrival"
    soll: str | None
    punkt: dict
    punkte: int


@dataclass(frozen=True)
class Befund:
    ende: Ende
    gruppe: str
    begruendung: str


def enden_aus_export(faelle: Sequence[dict]) -> list[Ende]:
    """JSON-Export → zu prüfende Enden. ``both`` ergibt zwei (Start und Ziel)."""
    enden: list[Ende] = []
    for fall in faelle:
        missing = fall.get("missing")
        for seite, punkt_key, soll_key in (
            ("departure", "first", "plan_departure"),
            ("arrival", "last", "plan_arrival"),
        ):
            if missing not in (seite, "both"):
                continue
            enden.append(
                Ende(
                    statsim_id=fall["statsim_id"],
                    callsign=fall.get("callsign") or "",
                    seite=seite,
                    soll=(fall.get(soll_key) or None),
                    punkt=fall[punkt_key],
                    punkte=int(fall.get("punkte") or 0),
                )
            )
    return enden


def _in_der_luft(punkt: dict, basis: AirportRef | None) -> tuple[bool, str]:
    """Höhe führt, Groundspeed hilft — wie im Detektor (app/gps_legs.py:4).

    Groundspeed allein genügt NICHT: STOL/Heli fliegen langsam (Wilga ~40 kt Reise), eine
    gs-zentrierte Regel wertet sie als Bodenpunkt. Gemessen an 184 Enden: 13 erkennt nur die
    Höhe, 5 nur die Groundspeed — beide Signale sind nötig.
    """
    alt = punkt.get("alt")
    gs = punkt.get("gs") or 0
    if alt is not None and basis is not None and basis.elevation_ft is not None:
        agl = alt - basis.elevation_ft
        if agl > _GPS_GROUND_AGL_FT:
            return True, "AGL %.0f ft (> %d)" % (agl, _GPS_GROUND_AGL_FT)
    if gs >= _GPS_FLYING_GS_KT:
        return True, "gs %d kt (>= %d)" % (gs, _GPS_FLYING_GS_KT)
    return False, ""


def triagiere(
    ende: Ende,
    ad_refs: Sequence[AirportRef],
    oa_refs: Sequence[AirportRef],
) -> Befund:
    """Schritt 0 und Schritt 1 der Prüfreihenfolge. Erste greifende Gruppe gewinnt."""
    if ende.punkte < MIN_TRACKPUNKTE:
        return Befund(ende, GRUPPE_DUENN, "Track hat nur %d Punkt(e)" % ende.punkte)

    if (ende.soll or "").upper() == PLATZHALTER_CODE:
        return Befund(ende, GRUPPE_ZZZZ, "Flugplan-Platzhalter — kein Platz")

    # AGL-Basis: bevorzugt der Soll-Platz (aus BEIDER Quellen — Elevation ist Elevation),
    # sonst der nächstgelegene Platz bei ganz unbekanntem Code.
    lat, lon = ende.punkt["lat"], ende.punkt["lon"]
    # Die Nachbarsuche fragt BEWUSST NUR airportsdata, nicht OurAirports: Schritt 1 muss gegen
    # die Quelle prüfen, die der Detektor selbst benutzt. Ein Platz, den nur OurAirports kennt,
    # existiert für die Erkennung nicht — er ist ein Hinweis auf Fall A („fehlt in airportsdata"),
    # gerade KEIN Fall D („Punkt gehört zu einem anderen Platz").
    # Gemessen am Export vom 2026-07-15: Bezöge man OurAirports ein, würden 7 der 25 Kandidaten
    # zu Fall D — u. a. FRS21N, der ab EDSV startete und 0,07 km neben „DE-0047" steht. Das ist
    # mit hoher Wahrscheinlichkeit derselbe Platz (EDSV fehlt in airportsdata, OurAirports führt
    # ihn ohne ICAO-Code). Als Fall D wäre dieser Eintrags-Kandidat still wegsortiert worden.
    nachbarn = nearest(lat, lon, ad_refs, limit=1)
    basis = find_code(ende.soll or "", ad_refs) or find_code(ende.soll or "", oa_refs)
    if basis is None and nachbarn:
        basis = nachbarn[0].ref

    luft, warum = _in_der_luft(ende.punkt, basis)
    if luft:
        return Befund(ende, GRUPPE_LUFT, "kein Bodenpunkt: %s" % warum)

    if nachbarn:
        hit = nachbarn[0]
        if hit.ref.code != (ende.soll or "").upper() and hit.distance_km < NACHBAR_MAX_KM:
            return Befund(
                ende, GRUPPE_ANDERER,
                "Punkt liegt %.2f km an %s (Soll: %s)"
                % (hit.distance_km, hit.ref.code, ende.soll or "-"),
            )
        return Befund(ende, GRUPPE_KANDIDAT, "nächster Platz: %s %.2f km" % (hit.ref.code, hit.distance_km))
    return Befund(ende, GRUPPE_KANDIDAT, "kein Platz in Reichweite")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Triage der Erkennungslücken — sortiert, urteilt nicht.")
    parser.add_argument("export", type=Path, help="gaps.json (siehe SKILL.md)")
    parser.add_argument("--gruppe", default=None, help="nur diese Gruppe ausgeben")
    args = parser.parse_args(argv)

    faelle = json.loads(args.export.read_text(encoding="utf-8"))
    ad, oa = airportsdata_refs(), load_ourairports()
    befunde = [triagiere(e, ad, oa) for e in enden_aus_export(faelle)]

    zaehler = Counter(b.gruppe for b in befunde)
    print("%d Enden aus %d Fällen\n" % (len(befunde), len(faelle)))
    for gruppe, anzahl in zaehler.most_common():
        print("  %-10s %4d  (%4.1f%%)" % (gruppe, anzahl, 100.0 * anzahl / len(befunde)))
    mechanisch = len(befunde) - zaehler[GRUPPE_KANDIDAT]
    print("\n  mechanisch abgehakt: %d von %d" % (mechanisch, len(befunde)))

    zeigen = args.gruppe or GRUPPE_KANDIDAT
    print("\n--- %s ---" % zeigen)
    for b in befunde:
        if b.gruppe != zeigen:
            continue
        print("  %-9s %-8s %-9s soll=%-6s  %s"
              % (b.ende.statsim_id, b.ende.callsign, b.ende.seite, b.ende.soll or "-", b.begruendung))
    return 0


if __name__ == "__main__":
    sys.exit(main())
