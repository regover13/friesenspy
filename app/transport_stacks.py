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

    onboard: dict[int, dict[str, float]] = {}
    position: dict[int, str | None] = {}
    last_ground: dict[int, str | None] = {}   # letzter Bodenkontakt (Sichtbarkeit, Entscheidung 14)
    since: dict[int, str] = {}                # seit wann steht er dort (Ankunftsreihenfolge)
    capacity: dict[int, float] = {}
    movements: list[dict] = []

    state = {
        "manifest": manifest, "order": order, "stacks": stacks, "onboard": onboard,
        "position": position, "since": since, "capacity": capacity, "empty": _empty,
        "loading_airports": loading_airports, "destination": destination, "movements": movements,
    }

    for e in events:
        cid = int(e["cid"])
        kind = e["kind"]
        ts = e["ts"]
        if e.get("capacity_kg") is not None:
            capacity[cid] = float(e["capacity_kg"])

        if kind == "login":
            # Ein frisch eingeloggter Pilot trägt nichts: die Ladung ist eine Ableitung, kein
            # Speicher — beim letzten Logout hat sie einen End-Stapel gefunden.
            onboard[cid] = _empty()
            position[cid] = e.get("airport")     # None = in der Luft eingeloggt
            since[cid] = ts
            if e.get("airport"):
                last_ground[cid] = e["airport"]
        elif kind == "takeoff":
            position[cid] = None                 # unterwegs. Lädt NICHT.
        elif kind == "landing":
            airport = e.get("airport")
            position[cid] = airport
            since[cid] = ts
            if e.get("airport"):
                last_ground[cid] = e["airport"]
            if airport == destination:
                # Landung am Ziel: der GESAMTE Flieger-Stapel geht in den Ziel-Stapel, sofort.
                # Kein Disconnect nötig — genau die Frage, die früher der Latch beantwortete.
                load = onboard.get(cid) or {}
                for name, kg in list(load.items()):
                    if kg <= _EPS:
                        continue
                    stacks[destination][name] += kg
                    movements.append({"ts": ts, "cid": cid, "kind": "deliver",
                                      "airport": destination, "name": name, "kg": kg})
                onboard[cid] = _empty()
            # Landung woanders: NICHTS. Die Ladung bleibt an Bord (Milchmann/Zwischenlandung).
        elif kind == "logout":
            position.pop(cid, None)
            since.pop(cid, None)
            onboard.pop(cid, None)

        _load_standing(state, ts)

    return {
        "stacks": stacks,
        "onboard": onboard,
        "position": position,
        "last_ground": last_ground,
        "movements": movements,
    }


def _load_standing(state: dict, ts: str) -> None:
    """Alle, die gerade an einem Ladeplatz stehen, laden auf — in Ankunftsreihenfolge.

    Wird nach JEDEM Ereignis aufgerufen. Das trägt zwei Entscheidungen ohne eigene Regel:
    'Laden ist ein Zustand' (4) und 'der Wartende lädt nach' (13) — kommt Ware auf einen Stapel,
    an dem jemand steht, nimmt er sie beim nächsten Durchlauf mit.
    """
    standing = [c for c, p in state["position"].items() if p in state["loading_airports"]]
    for cid in sorted(standing, key=lambda c: (state["since"].get(c, ""), c)):
        _take(state, cid, state["position"][cid], ts)


def _take(state: dict, cid: int, airport: str, ts: str) -> None:
    """Vom Stapel dieses Platzes nehmen, soweit Platz im Flieger ist — Manifest-Reihenfolge."""
    stack = state["stacks"].get(airport)
    if not stack:
        return
    load = state["onboard"].setdefault(cid, state["empty"]())
    free = state["capacity"].get(cid, 0.0) - sum(load.values())
    for c in state["manifest"]:
        if free <= _EPS:
            break
        name = c["name"]
        available = stack.get(name, 0.0)
        if available <= _EPS:
            continue
        take = min(available, free)
        if take <= _EPS:
            continue
        stack[name] -= take
        load[name] = load.get(name, 0.0) + take
        free -= take
        state["movements"].append(
            {"ts": ts, "cid": cid, "kind": "load", "airport": airport, "name": name, "kg": take}
        )
