"""Prototyp des Stapel-Modells — rechnet die 4 abgeschlossenen Kutter neu und vergleicht
mit dem eingefrorenen Snapshot (= altes Modell).

Modell (Entscheidungen vom 15.07.):
  - Stapel: {ort: {frachtart: kg}}, initial = Manifest. Ziel/gestohlen/versenkt sind auch Stapel.
  - Ladung: {cid: {frachtart: kg}} — bleibt an Bord ueber Zwischenlandungen.
  - Abheben von einem Ladeplatz -> laden (auffuellen, soweit Platz; Manifest-Reihenfolge = oben zuerst).
    [aequivalent zu "beim Landen laden" fuer die Bilanz: wer laedt und sofort auslogged, gibt alles zurueck]
  - Landung am Ziel -> alles in den Ziel-Stapel (= geliefert).
  - Landung woanders -> nichts, Ladung bleibt.
  - Logout (Ende der Connection): Ladeplatz -> Stapel dort; fremder Platz -> gestohlen; Luft -> versenkt.
  - Wer zuerst kommt, laedt zuerst. Zweiter hat Pech.

REIN LESEND. Aendert nichts.
"""
import sqlite3, json
from collections import defaultdict
from app import geo, database as db

conn = sqlite3.connect("/opt/friesenspy/data/friesenspy.db")
conn.row_factory = sqlite3.Row
geo.set_custom_airports(db.list_custom_airports(conn))

payload_map = db.get_payload_map(conn)
default_kg = db.transport_default_payload_kg(conn)


def kap(f):
    tc = (f.get("aircraft_icao") or f.get("aircraft") or "").upper()
    return float(payload_map.get(tc) or default_kg or 0)


def rechne(ev):
    dest = (ev["destination"] or "").upper()
    route = {r.strip().upper() for r in (ev["route"] or "").split(",") if r.strip()}
    ladeplaetze = route - {dest}

    # Manifest = Anfangsbestand. Reihenfolge: wie im Admin (oben zuerst).
    cargo = db.get_transport_cargo(conn, ev["id"])
    stapel = defaultdict(lambda: defaultdict(float))
    reihenfolge = []
    cap_je_flug = {}                             # per_flight_max_kg (#63) — pro LADEVORGANG
    for c in cargo:
        name = c.get("name")
        reihenfolge.append(name)
        cap_je_flug[name] = c.get("per_flight_max_kg")
        deps = [d.strip().upper() for d in (c.get("departure") or "").split(",") if d.strip()]
        if not deps:
            deps = sorted(ladeplaetze)          # Altbestand ohne Bindung: geteilt
        kg = float(c.get("target_kg") or 0)
        for d in deps:                           # mehrere Startplaetze: Menge je Platz
            stapel[d][name] += kg / len(deps)

    legs = db.canonicalize_legs(conn, start=ev["dtstart"], end=ev["dtend"], callsign_prefix="FRS")
    legs = [f for f in legs if f.get("gps_departure") or f.get("gps_arrival")]
    legs.sort(key=lambda f: f.get("logon_time") or "")

    ladung = defaultdict(lambda: defaultdict(float))
    ziel = defaultdict(float)
    gestohlen = defaultdict(float)
    versenkt = defaultdict(float)
    letzter_ort = {}

    for f in legs:
        cid = f.get("cid")
        dep = (f.get("gps_departure") or "").upper()
        arr = (f.get("gps_arrival") or "").upper()

        # --- Abheben von einem Ladeplatz: auffuellen ---
        if dep in ladeplaetze:
            frei = kap(f) - sum(ladung[cid].values())
            for name in reihenfolge:
                if frei <= 0.01:
                    break
                da = stapel[dep].get(name, 0.0)
                if da <= 0.01:
                    continue
                nimm = min(da, frei)
                pfm = cap_je_flug.get(name)      # #63: Obergrenze je Flug/Ladevorgang
                if pfm:
                    nimm = min(nimm, float(pfm) - ladung[cid].get(name, 0.0))
                if nimm <= 0.01:
                    continue
                stapel[dep][name] -= nimm
                ladung[cid][name] += nimm
                frei -= nimm

        # --- Landung ---
        if arr == dest:
            for name, kg in list(ladung[cid].items()):
                ziel[name] += kg
            ladung[cid].clear()
            letzter_ort[cid] = dest
        elif arr:
            letzter_ort[cid] = arr           # Ladeplatz oder fremd: Ladung bleibt an Bord
        else:
            letzter_ort[cid] = None          # Leg endet in der Luft

    # --- Logout: was am Ende noch an Bord ist ---
    for cid, l in ladung.items():
        if not l:
            continue
        ort = letzter_ort.get(cid)
        ziel_stapel = (stapel[ort] if ort in ladeplaetze
                       else versenkt if ort is None else gestohlen)
        for name, kg in l.items():
            ziel_stapel[name] += kg

    return dest, reihenfolge, stapel, ziel, gestohlen, versenkt


evs = [dict(r) for r in conn.execute(
    "SELECT id, name, destination, route, dtstart, dtend FROM transport_events ORDER BY dtstart")]

print("=" * 92)
print("STAPEL-MODELL (Prototyp)  vs.  eingefrorener Snapshot (altes Modell)")
print("=" * 92)
for ev in evs:
    snap = db.get_progress_snapshot(conn, "kutter", ev["id"])
    dest, reihen, stapel, ziel, gestohlen, versenkt = rechne(ev)
    neu_total = sum(ziel.values())
    alt_total = float((snap or {}).get("total_kg") or 0)
    print("\n#%-4s %-32s Ziel=%s" % (ev["id"], (ev["name"] or "")[:32], dest))
    print("      %-24s %10s   %10s   %s" % ("Frachtart", "ALT (Snap)", "NEU (Stapel)", "Delta"))
    alt_cargo = {c.get("name"): float(c.get("delivered_kg") or 0)
                 for c in (snap or {}).get("cargo", [])}
    for name in reihen:
        a, n = alt_cargo.get(name, 0.0), ziel.get(name, 0.0)
        d = n - a
        print("      %-24s %10.0f   %10.0f   %+8.0f %s" % (
            name, a, n, d, "" if abs(d) < 1 else "  <-- weicht ab"))
    print("      %-24s %10.0f   %10.0f   %+8.0f  %s" % (
        "SUMME", alt_total, neu_total, neu_total - alt_total,
        "IDENTISCH" if abs(neu_total - alt_total) < 1 else "ABWEICHUNG"))
    if gestohlen:
        print("      gestohlen: %s" % dict(gestohlen))
    if versenkt:
        print("      versenkt : %s" % dict(versenkt))
    rest = {o: {k: round(v) for k, v in s.items() if v > 0.5}
            for o, s in stapel.items() if any(v > 0.5 for v in s.values())}
    if rest:
        print("      Rest auf Stapeln: %s" % rest)
