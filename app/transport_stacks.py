"""Stapel-Modell des FriesenKutter — Ladung als Bestand mit einem Ort.

Reine Zustandsmaschine, KEINE Datenbank (Vorbild: app/gps_legs.py). Die Funktion bekommt das
Manifest und eine chronologische Ereignisliste und liefert, wo welche Ware liegt.

Grundsatz (Spec docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md):
    Ware liegt auf Stapeln (Orte). Der Flieger trägt selbst einen Stapel, der eine Position hat.
    Ware wechselt nur zwischen Stapeln — sie entsteht nie und verschwindet nie:

        Summe Stapel + Summe Ladung == Summe Manifest      (Erhaltungssatz)

Dieser Satz ist die Kernzusage des Modells und als Test zu prüfen. Er macht #63 („der Balken
lügt nicht") von einer Zusicherung zu Arithmetik.
"""
from __future__ import annotations

# Virtuelle Orte. Das \x00-Präfix kann mit keinem ICAO kollidieren.
STOLEN = "\x00gestohlen"
SUNK = "\x00versenkt"

# kg-Schwelle. Zuladungen sind auf 0,1 kg gerundet — darunter ist nichts mehr zu verteilen.
_EPS = 0.01


def derive_stacks(
    *,
    manifest: list[dict],
    events: list[dict],
    destination: str,
    loading_airports: set[str],
) -> dict:
    """Wo liegt welche Ware, nachdem alle Ereignisse abgearbeitet sind?

    :param manifest: Frachtarten in LADEREIHENFOLGE (oben zuerst, Entscheidung 7). Je Zeile
        ``{"name", "target_kg", "departure", "per_flight_max_kg"}``; ``departure`` ist genau
        EIN Platz (Entscheidung 6).
    :param events: chronologisch, ``{"ts", "kind", "cid", "airport", "capacity_kg"}``.
    :param destination: Ziel-ICAO. Der Ziel-Stapel ist ein End-Stapel.
    :param loading_airports: die Ladeplätze (Route ohne Ziel).
    """
    order = [c["name"] for c in manifest]

    def _empty() -> dict[str, float]:
        return {n: 0.0 for n in order}

    # Anfangsbestand: jede Manifest-Zeile liegt an ihrem Platz. Ein leerer Stapel ist immer noch
    # ein Stapel (Entscheidung 3) — deshalb wird JEDER Ladeplatz angelegt, auch ohne Ware.
    stacks: dict[str, dict[str, float]] = {a: _empty() for a in loading_airports}
    for virtual in (destination, STOLEN, SUNK):
        stacks[virtual] = _empty()
    for c in manifest:
        dep = (c.get("departure") or "").upper()
        if dep:
            stacks.setdefault(dep, _empty())
            stacks[dep][c["name"]] += float(c.get("target_kg") or 0.0)

    return {
        "stacks": stacks,
        "onboard": {},
        "position": {},
        "last_ground": {},
        "movements": [],
    }
