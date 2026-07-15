"""Messwerkzeug für die Track-Diagnose (Skill ``track-diagnose``).

Punkt rein, Messwerte raus: nächste Flugplätze laut airportsdata und OurAirports,
Abweichung beider Quellen, Distanz zum Soll-Code aus dem Flugplan.

**Dieses Werkzeug fällt kein Urteil.** Es meldet „außerhalb", nicht „also Radius-Override".
Die Fallunterscheidung steht in ``.claude/skills/track-diagnose/SKILL.md``.

Rein und offline: kein DB-Zugriff, kein SSH, keine ``custom_airports``.
"""
from __future__ import annotations

import airportsdata
import argparse
import csv
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.database import _BUMMEL_AIRPORT_RADIUS_KM
from app.geo import haversine
from app.gps_legs import _GPS_GROUND_AGL_FT, _GPS_SPAWN_MAX_AGL_FT


@dataclass(frozen=True)
class AirportRef:
    """Ein Flugplatz aus einer Referenzquelle.

    ``code`` ist der Anzeige-Code. ``codes`` enthält ALLE Codes, unter denen der Platz
    auffindbar ist — bei OurAirports sind das ``ident``, ``icao_code`` und ``gps_code``,
    die auseinanderfallen können (EDHX/EBMO haben ein leeres ``icao_code``).
    """

    code: str
    name: str
    lat: float
    lon: float
    elevation_ft: float | None
    codes: frozenset[str]


def parse_ourairports(rows: Iterable[dict]) -> list[AirportRef]:
    """OurAirports-CSV-Zeilen (DictReader) → AirportRef-Liste.

    Zeilen ohne brauchbare Koordinate oder ganz ohne Code werden übersprungen.
    """
    refs: list[AirportRef] = []
    for row in rows:
        try:
            lat = float(row["latitude_deg"])
            lon = float(row["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            continue
        codes = {
            str(row.get(field) or "").strip().upper()
            for field in ("ident", "icao_code", "gps_code")
        }
        codes.discard("")
        if not codes:
            continue
        try:
            elevation_ft: float | None = float(row["elevation_ft"])
        except (KeyError, TypeError, ValueError):
            elevation_ft = None
        refs.append(
            AirportRef(
                code=str(row.get("ident") or "").strip().upper(),
                name=str(row.get("name") or "").strip(),
                lat=lat,
                lon=lon,
                elevation_ft=elevation_ft,
                codes=frozenset(codes),
            )
        )
    return refs


def load_ourairports(path: Path | str | None = None) -> list[AirportRef]:
    """OurAirports laden. ``path`` gesetzt → genau diese Datei (Tests: Fixture, kein Netz)."""
    if path is None:
        raise NotImplementedError("Cache/Download folgt in Task 4")
    with open(path, encoding="utf-8", newline="") as handle:
        return parse_ourairports(csv.DictReader(handle))


def find_code(code: str, refs: Sequence[AirportRef]) -> AirportRef | None:
    """Platz per Code suchen (case-insensitiv, über alle Alias-Codes). None = nicht vorhanden."""
    want = (code or "").strip().upper()
    if not want:
        return None
    for ref in refs:
        if want in ref.codes:
            return ref
    return None


@dataclass(frozen=True)
class Hit:
    """Ein Platz mit gemessener Distanz zum untersuchten Punkt."""

    ref: AirportRef
    distance_km: float
    agl_ft: float | None


@dataclass(frozen=True)
class Measurement:
    """Reines Messergebnis — enthält bewusst KEINE Bewertung und keine Empfehlung.

    ``ad_target``/``oa_target`` sind ``None``, wenn der Soll-Code in der jeweiligen Quelle
    fehlt. Das ist Alltag, kein Fehler: EDHX steht nur in OurAirports, ETUO nur in
    airportsdata.
    """

    lat: float
    lon: float
    alt_ft: float | None
    icao: str | None
    ad_nearest: list[Hit]
    oa_nearest: list[Hit]
    ad_target: Hit | None
    oa_target: Hit | None
    source_delta_km: dict[str, float]
    oa_available: bool


def airportsdata_refs() -> list[AirportRef]:
    """Alle Plätze aus ``airportsdata``.

    Bewusst die Rohquelle: sie kennt keine ``custom_airports``. Über ``icao_to_coords()`` zu
    gehen wäre ein Fehler — das bezieht Overrides ein und macht jeden Vergleich „weicht der
    Override ab?" zu 0 km.
    """
    return [
        AirportRef(
            code=code,
            name=str(entry.get("name") or ""),
            lat=entry["lat"],
            lon=entry["lon"],
            elevation_ft=entry.get("elevation"),
            codes=frozenset({code}),
        )
        for code, entry in airportsdata.load("ICAO").items()
    ]


def _hit(lat: float, lon: float, alt_ft: float | None, ref: AirportRef) -> Hit:
    agl = None
    if alt_ft is not None and ref.elevation_ft is not None:
        agl = alt_ft - ref.elevation_ft
    return Hit(ref=ref, distance_km=haversine(lat, lon, ref.lat, ref.lon), agl_ft=agl)


def nearest(
    lat: float,
    lon: float,
    refs: Sequence[AirportRef],
    *,
    alt_ft: float | None = None,
    limit: int = 5,
) -> list[Hit]:
    """Die ``limit`` nächsten Plätze, aufsteigend nach Distanz. DIE Umkehrfrage."""
    hits = [_hit(lat, lon, alt_ft, ref) for ref in refs]
    hits.sort(key=lambda h: h.distance_km)
    return hits[:limit]


def measure(
    lat: float,
    lon: float,
    *,
    alt_ft: float | None = None,
    icao: str | None = None,
    ad_refs: Sequence[AirportRef] | None = None,
    oa_refs: Sequence[AirportRef] | None = None,
) -> Measurement:
    """Punkt gegen beide Referenzquellen messen. Ohne ``ad_refs``/``oa_refs`` werden sie geladen."""
    ad = list(ad_refs) if ad_refs is not None else airportsdata_refs()
    oa = list(oa_refs) if oa_refs is not None else load_ourairports()

    # Soll-Code in BEIDEN Quellen unabhängig suchen: ein Code kann in einer fehlen und in der
    # anderen stehen (EDHX nur OurAirports, ETUO nur airportsdata). None heißt „diese Quelle
    # kennt ihn nicht" — kein Fehler, sondern selbst ein Befund.
    ad_target = oa_target = None
    if icao:
        found_ad = find_code(icao, ad)
        if found_ad is not None:
            ad_target = _hit(lat, lon, alt_ft, found_ad)
        found_oa = find_code(icao, oa)
        if found_oa is not None:
            oa_target = _hit(lat, lon, alt_ft, found_oa)

    # Quellen-Abweichung für alle Codes, die in dieser Messung vorkommen.
    codes = {h.ref.code for h in nearest(lat, lon, ad, limit=5)}
    codes |= {h.ref.code for h in nearest(lat, lon, oa, limit=5)}
    if icao:
        codes.add(icao.strip().upper())
    delta: dict[str, float] = {}
    for code in codes:
        in_ad = find_code(code, ad)
        in_oa = find_code(code, oa)
        if in_ad is not None and in_oa is not None:
            delta[code] = haversine(in_ad.lat, in_ad.lon, in_oa.lat, in_oa.lon)

    return Measurement(
        lat=lat,
        lon=lon,
        alt_ft=alt_ft,
        icao=(icao or "").strip().upper() or None,
        ad_nearest=nearest(lat, lon, ad, alt_ft=alt_ft),
        oa_nearest=nearest(lat, lon, oa, alt_ft=alt_ft),
        ad_target=ad_target,
        oa_target=oa_target,
        source_delta_km=delta,
        oa_available=bool(oa),
    )


def _threshold_notes(hit: Hit) -> list[str]:
    """Messwert gegen Detektor-Schwelle stellen — beschreibend, NICHT bewertend.

    Die Schwellen werden importiert, nie abgeschrieben: ändert jemand den Detektor,
    ändert sich diese Ausgabe mit.
    """
    notes = []
    inside = hit.distance_km <= _BUMMEL_AIRPORT_RADIUS_KM
    notes.append(
        "Standardradius %.1f km — %s" % (_BUMMEL_AIRPORT_RADIUS_KM, "innerhalb" if inside else "außerhalb")
    )
    if hit.agl_ft is not None:
        notes.append(
            "Spawn-Grenze %d ft — %s"
            % (_GPS_SPAWN_MAX_AGL_FT, "darunter" if hit.agl_ft < _GPS_SPAWN_MAX_AGL_FT else "überschritten")
        )
        notes.append(
            "Bodengrenze %d ft — %s"
            % (_GPS_GROUND_AGL_FT, "darunter" if hit.agl_ft < _GPS_GROUND_AGL_FT else "darüber")
        )
    return notes


def _format_hits(hits: Sequence[Hit]) -> list[str]:
    lines = []
    for hit in hits:
        agl = "  AGL %6.0f ft" % hit.agl_ft if hit.agl_ft is not None else " " * 14
        lines.append(
            "  %-8s %9.2f km%s   elev %6s ft   %s"
            % (hit.ref.code, hit.distance_km, agl, _fmt_elev(hit.ref.elevation_ft), hit.ref.name[:38])
        )
    return lines


def _fmt_elev(value: float | None) -> str:
    return "?" if value is None else "%.0f" % value


def format_report(m: Measurement) -> str:
    """Messergebnis als Text. Reine Darstellung — kein Urteil, keine Empfehlung."""
    out: list[str] = []
    alt = "" if m.alt_ft is None else "  (alt %.0f ft MSL)" % m.alt_ft
    out.append("Punkt: %.5f, %.5f%s" % (m.lat, m.lon, alt))

    if m.icao:
        out.append("")
        out.append("Soll-Code laut Flugplan: %s" % m.icao)
        for label, hit in (("airportsdata", m.ad_target), ("OurAirports", m.oa_target)):
            if hit is None:
                out.append("  %-13s in dieser Quelle nicht vorhanden" % label)
                continue
            out.append("  %-13s %9.2f km   %s" % (label, hit.distance_km, hit.ref.name[:40]))
            for note in _threshold_notes(hit):
                out.append("  %-13s   (%s)" % ("", note))

    out.append("")
    out.append("Nächste Plätze laut airportsdata:")
    out.extend(_format_hits(m.ad_nearest))

    out.append("")
    if not m.oa_available:
        out.append("Nächste Plätze laut OurAirports: -- nicht geladen (kein Netz/Cache)")
    else:
        out.append("Nächste Plätze laut OurAirports:")
        out.extend(_format_hits(m.oa_nearest))

    if m.source_delta_km:
        out.append("")
        out.append("Abweichung airportsdata <-> OurAirports:")
        for code, delta in sorted(m.source_delta_km.items(), key=lambda kv: -kv[1]):
            out.append("  %-8s %9.2f km" % (code, delta))

    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Messwerkzeug für die Track-Diagnose — misst, urteilt nicht.",
    )
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("--alt", type=float, default=None, help="Höhe in ft MSL (für AGL)")
    parser.add_argument("--icao", default=None, help="Soll-Code aus dem Flugplan")
    args = parser.parse_args(argv)

    print(format_report(measure(args.lat, args.lon, alt_ft=args.alt, icao=args.icao)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
