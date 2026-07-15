"""Messwerkzeug für die Track-Diagnose (Skill ``track-diagnose``).

Punkt rein, Messwerte raus: nächste Flugplätze laut airportsdata und OurAirports,
Abweichung beider Quellen, Distanz zum Soll-Code aus dem Flugplan.

**Dieses Werkzeug fällt kein Urteil.** Es meldet „außerhalb", nicht „also Radius-Override".
Die Fallunterscheidung steht in ``.claude/skills/track-diagnose/SKILL.md``.

Rein und offline: kein DB-Zugriff, kein SSH, keine ``custom_airports``.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


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
