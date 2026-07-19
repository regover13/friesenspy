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

    # Pro-Flug-Kappung gilt pro FRACHT-NAME, nicht pro Manifest-Zeile (#4). Dieselbe Ware darf
    # aus zwei Startplätzen kommen (Nutzer 16.07.: Sonnenschirme aus EDWG UND EDDW), aber die
    # Bordladung dieses Namens darf die Kappung nie überschreiten. Tragen zwei Zeilen desselben
    # Namens UNTERSCHIEDLICHE Kappungen, gilt die STRENGSTE (kleinster Wert) — sonst nähme der
    # Pilot am zweiten Platz gegen die lockerere Grenze nach. Ohne gesetzte Kappung: unbegrenzt.
    name_cap: dict[str, float] = {}
    for c in manifest:
        cap = c.get("per_flight_max_kg")
        if cap is not None and cap > 0:
            cur = name_cap.get(c["name"])
            name_cap[c["name"]] = float(cap) if cur is None else min(cur, float(cap))

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
    # Bordladung beim Abheben je Leg, Schlüssel (cid, takeoff-ts). Das ist die Modell-Wahrheit
    # „was trug er auf DIESEM Leg". Der Feed zeigt damit auch DURCHGETRAGENE Ware auf Zwischenlegs
    # eines Milchmanns (nicht nur Geliefertes) — ohne sie sah ein beladenes Zwischenleg „leer" aus
    # (Fund Michael 19.07.). Reine Anzeige-Quelle: an Stapeln/Bilanz ändert sie nichts.
    carried: dict[tuple[int, str], dict[str, float]] = {}

    state = {
        "manifest": manifest, "order": order, "stacks": stacks, "onboard": onboard,
        "position": position, "since": since, "capacity": capacity, "empty": _empty,
        "loading_airports": loading_airports, "destination": destination, "movements": movements,
        "name_cap": name_cap,
    }

    for e in events:
        cid = int(e["cid"])
        kind = e["kind"]
        ts = e["ts"]
        if e.get("capacity_kg") is not None:
            capacity[cid] = float(e["capacity_kg"])

        if kind == "login":
            # Trägt er noch etwas (zwei logins ohne logout dazwischen — ungracefuler Disconnect
            # + Reconnect, close_stale_flights räumt erst nach 8 h auf), fällt es hier ab wie
            # bei einem Logout. Ein bloßes onboard[cid] = {} würde die Ware aus dem Universum
            # löschen und den Erhaltungssatz brechen (Fable-Review 16.07.).
            _drop_load(state, cid, ts)
            onboard[cid] = _empty()
            position[cid] = e.get("airport")     # None = in der Luft eingeloggt
            since[cid] = ts
            if e.get("airport"):
                last_ground[cid] = e["airport"]
        elif kind == "takeoff":
            position[cid] = None                 # unterwegs. Lädt NICHT.
            # Was liegt beim Abheben an Bord? = die auf DIESEM Leg getragene Ladung (nach dem Laden
            # im Stand, vor dem nächsten Ladeort). Ein Snapshot pro Leg für die Feed-Anzeige.
            carried[(cid, ts)] = {n: kg for n, kg in (onboard.get(cid) or {}).items() if kg > _EPS}
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
            _drop_load(state, cid, ts)
            position.pop(cid, None)
            since.pop(cid, None)

        _load_standing(state, ts)

    return {
        "stacks": stacks,
        "onboard": onboard,
        "position": position,
        "last_ground": last_ground,
        "movements": movements,
        "carried": carried,
    }


def _drop_load(state: dict, cid: int, ts: str) -> None:
    """Die Bordladung abgeben — dorthin, wo der Pilot gerade ist (Entscheidung 2).

    Wer ausloggt, beendet seine Tour: Was dann an Bord ist, bleibt liegen, wo er ist. Das gilt
    auch beim unfreiwilligen Verbindungsabbruch — ein Netzausfall in der Luft ist im Track nicht
    von einem bewussten Ausstieg zu unterscheiden ("Ja. Ist halt so.", Nutzer 15.07.).

    Der Ort braucht keine Sonderregel: `position` ist bereits richtig, weil `takeoff` sie auf
    None gesetzt hat. Ein Logout zwischen Takeoff und Landung findet None vor -> versenkt. Genau
    der Fall S8 (Logout in der Luft, Sekunden später Login am Platz), bei dem der Detektor EIN
    durchgehendes Leg mit sauberer Landung sieht — eine Regel "letzter Leg -> gps_arrival"
    ergäbe dort fälschlich 'zurück'.
    """
    load = state["onboard"].pop(cid, None) or {}
    if not any(kg > _EPS for kg in load.values()):
        return
    where = state["position"].get(cid)
    if where == state["destination"]:
        return                                   # bei der Landung längst geliefert
    if where in state["loading_airports"]:
        target, kind_name = where, "returned"
    elif where:
        target, kind_name = STOLEN, "stolen"
    else:
        target, kind_name = SUNK, "sunk"
    for name, kg in load.items():
        if kg <= _EPS:
            continue
        state["stacks"][target][name] += kg
        state["movements"].append({"ts": ts, "cid": cid, "kind": kind_name,
                                   "airport": where, "name": name, "kg": kg})


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
        # #63: `per_flight_max_kg` begrenzt, was AN BORD ist — nicht, was je Ladevorgang
        # aufgenommen wird. Sonst wäre die Kappung durch mehrfaches Landen am selben Platz
        # umgehbar (zehn Platzrunden = zehnmal die Kappungsmenge in EINER Lieferung).
        # #4: Die Kappung ist eine Eigenschaft des Namens (Katalog), nicht der Manifest-ZEILE —
        # sonst nähme derselbe Name aus zwei Startplätzen gegen die lockerere Kappung nach und
        # die Bordladung überschritte die strengere. `name_cap` ist die pro Name gültige (bei
        # Uneinigkeit strengste) Kappung; die Bordladung ist ohnehin name-keyed.
        cap = state["name_cap"].get(name)
        if cap is not None:
            take = min(take, cap - load.get(name, 0.0))
        if take <= _EPS:
            continue
        stack[name] -= take
        load[name] = load.get(name, 0.0) + take
        free -= take
        state["movements"].append(
            {"ts": ts, "cid": cid, "kind": "load", "airport": airport, "name": name, "kg": take}
        )
