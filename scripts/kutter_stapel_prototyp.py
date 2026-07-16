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
import sqlite3, json, sys
from collections import defaultdict
from app import geo, database as db
from app.database import _stack_inputs
from app.transport_stacks import derive_stacks, STOLEN, SUNK

# Pfad zur KOPIE als Argument — niemals die Original-Prod-DB.
db_pfad = sys.argv[1] if len(sys.argv) > 1 else "/tmp/friesenspy-kopie.db"
if db_pfad.startswith("/opt/friesenspy/"):
    raise SystemExit("Das ist die Produktions-DB. Bitte eine Kopie angeben.")
# mode=ro erzwingt Lesen auf DB-Ebene — nicht nur per Vorsatz.
conn = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
geo.set_custom_airports(db.list_custom_airports(conn))


def rechne(ev):
    """Jetzt mit der ECHTEN Ableitung statt der Skript-eigenen Kopie."""
    inp = _stack_inputs(conn, ev, ev["dtend"], callsign_prefix="FRS")
    r = derive_stacks(
        manifest=inp["manifest"], events=inp["events"],
        destination=inp["destination"], loading_airports=inp["loading_airports"],
    )
    dest = inp["destination"]
    reihenfolge = [c["name"] for c in inp["manifest"]]
    return (dest, reihenfolge, r["stacks"], r["stacks"][dest],
            r["stacks"][STOLEN], r["stacks"][SUNK])


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

    # --- Erhaltungssatz: nichts darf beim Umbau verschwinden oder sich vermehren ---
    cargo = db.get_transport_cargo(conn, ev["id"])
    summe_stapel = sum(sum(s.values()) for s in stapel.values())
    summe_manifest = sum(float(c.get("target_kg") or 0) for c in cargo)
    print("      Erhaltungssatz: Stapel %.1f == Manifest %.1f  %s" % (
        summe_stapel, summe_manifest,
        "OK" if abs(summe_stapel - summe_manifest) < 0.5 else "<-- GEBROCHEN"))
