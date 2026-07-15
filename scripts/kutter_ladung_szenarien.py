"""Ladungs-Szenarien des FriesenKutter — die Faelle, an denen sich das Modell entscheidet.

Spielt mit ECHTEN GPS-Tracks (In-Memory-DB, Produktionscode) durch, was die Wertung aus einem
Ladungs-Ablauf macht. Grundlage der Spec `docs/superpowers/specs/2026-07-15-kutter-stapel-modell-design.md`
und Vorlage fuer die Tests des Umbaus.

Manifest bewusst mit ZWEI Ladeplaetzen und VERSCHIEDENER Fracht, damit sichtbar wird, welcher
Startplatz die Zuordnung bestimmt:
    EDWG -> Fischbroetchen 800 kg  |  EDWZ -> Friesen Tee 500 kg  |  Ziel EDXH  |  Zuladung 1000 kg

Szenarien:
    S1   EDWG -> EDXH                      Normalfall
    S2   EDWG -> EDWZ -> EDXH              MILCHMANN (heute: erste Ladung verschwindet)
    S3   EDWG -> EDDW(fremd) -> EDXH       Zwischenlandung (heute ohne Latch: 0 kg)
    S3b  dasselbe mit Latch                heute: 1000 kg — Tee, der nie an Bord war
    S4   EDWG -> EDWZ, Logout              heute: `returned` in den EDWG-Topf statt nach EDWZ
    S5   EDWG -> EDDW(fremd), Logout       heute: `stolen`
    S8   Logout IN DER LUFT, 60 s spaeter  Nutzer-Fund 15.07.: der Detektor macht daraus EIN Leg
         Login am selben Platz             mit sauberer Landung — der Logout ist fuer ihn unsichtbar.
                                           Heute korrekt `sunk`, weil detect_transport_losses die
                                           VATSIM-Session fragt, nicht den Track.

Erwartung im Stapel-Modell (Spec, Abschnitt D des Artifacts):
    S2 -> 800 Fisch + 200 Tee   S3/S3b -> 800 Fisch   S4 -> EDWZ-Stapel: 500 Tee + 800 Fisch

REIN LESEND / In-Memory. Aendert nichts. Start: python -m scripts.kutter_ladung_szenarien
"""
from __future__ import annotations
import sys, sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, r"D:\User\Tobias\OneDrive\Claude\FriesenSpy")

from app.database import (
    init_db, get_connection, _DDL, create_transport_event, get_transport_event,
    set_transport_cargo, upsert_payload, compute_transport_progress,
    set_transport_live_arrival, detect_transport_losses, get_transport_losses,
)
from app import geo

START = "2026-07-01T09:00:00Z"
END   = "2026-07-01T23:00:00Z"
AC    = "C208"          # Zuladung wird unten fix gesetzt
PAYLOAD = 1000.0        # kg, damit die Zahlen leicht lesbar sind


def conn_new():
    init_db(":memory:")
    c = get_connection(":memory:")
    c.executescript(_DDL)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_flights_session "
              "ON flights(cid, logon_time) WHERE superseded_by IS NULL")
    c.execute("INSERT OR IGNORE INTO pilots (cid, name, added_at) VALUES (1, 'Testpilot', ?)", (START,))
    upsert_payload(c, type_code=AC, payload_kg=PAYLOAD)
    c.commit()
    return c


def shift(ts, minutes):
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def coords(icao):
    c = geo.icao_to_coords(icao)
    e = geo.airport_elevation_ft(icao)
    assert c, f"{icao} unbekannt"
    return c[0], c[1], (e if e is not None else 0)


def pos(c, ts, lat, lon, alt, gs):
    c.execute("INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, groundspeed, ts) "
              "VALUES (1,'FRS01',?,?,?,?,?)", (lat, lon, alt, gs, ts))


def leg(c, von, nach, t0, dauer=20):
    """Erzeugt einen erkennbaren GPS-Flug von 'von' nach 'nach'. Rueckgabe: Endzeit."""
    la, lo, ea = coords(von)
    lb, lb2, eb = coords(nach)
    pos(c, t0,             la, lo, ea,        0)      # am Boden
    pos(c, shift(t0, 1),   la, lo, ea + 250,  70)     # abgehoben (gs>50 + steigend)
    pos(c, shift(t0, 2),   la, lo, ea + 2500, 120)    # steigt (agl>500)
    mid_la, mid_lo = (la + lb) / 2, (lo + lb2) / 2
    pos(c, shift(t0, dauer // 2), mid_la, mid_lo, 3000, 130)
    pos(c, shift(t0, dauer - 2),  lb, lb2, eb + 2000, 120)
    pos(c, shift(t0, dauer - 1),  lb, lb2, eb + 200,  60)
    pos(c, shift(t0, dauer),      lb, lb2, eb,        0)   # Vollstopp am Platz
    c.commit()
    return shift(t0, dauer)


def flight_row(c, dep, arr, logon, logoff):
    c.execute("INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, "
              "logon_time, logoff_time, duration_min, distance_nm) "
              "VALUES (1,'FRS01',?,?,?,?,?,30,20.0)", (AC, dep, arr, logon, logoff))
    c.commit()


def event(c):
    eid = create_transport_event(
        c, name="Helgoland", route="EDWG,EDWZ,EDXH", dtstart=START, dtend=END, destination="EDXH")
    set_transport_cargo(c, eid, [
        {"name": "Fischbroetchen", "target_kg": 800, "departure": "EDWG"},
        {"name": "Friesen Tee",    "target_kg": 500, "departure": "EDWZ"},
    ])
    return get_transport_event(c, eid)


def zeige(titel, c, ev, *, verluste=False):
    p = compute_transport_progress(c, ev, shift(START, 300), callsign_prefix="FRS")
    print("\n" + "=" * 78)
    print(titel)
    print("=" * 78)
    for cg in p.get("cargo", []):
        print("   %-16s %5.0f / %-5.0f kg   (Startplatz %s)" % (
            cg.get("name"), cg.get("delivered_kg") or 0, cg.get("target_kg") or 0,
            cg.get("departure") or "— (geteilt)"))
    print("   %-16s %5.0f kg gesamt" % ("SUMME", p.get("total_kg") or 0))
    for f in p.get("flights", []):
        print("      Feed: %s->%s  %s kg  %s" % (
            f.get("departure") or "?", f.get("arrival") or "?",
            f.get("tonnage_kg") or 0, f.get("cargo_label") or f.get("status") or ""))
    if verluste:
        n = detect_transport_losses(c, ev, callsign_prefix="FRS")
        ls = get_transport_losses(c, ev["id"])
        print("   Verlust-Erkennung: %d neu, %d gesamt" % (n, len(ls)))
        for l in ls:
            print("      VERLUST: kind=%-9s kg=%-6s %s" % (
                l.get("kind"), l.get("kg") if l.get("kg") is not None else "?", l.get("type_code") or ""))
        if not ls:
            print("      (kein Verlust erkannt)")
    return p


# ---------------------------------------------------------------- S1: Normalfall
c = conn_new(); ev = event(c)
t_end = leg(c, "EDWG", "EDXH", START)
flight_row(c, "EDWG", "EDXH", START, t_end)
zeige("S1  EDWG -> EDXH   (Normalfall: ein Ladeplatz, direkt zum Ziel)", c, ev)

# ---------------------------------------------------------------- S2: Milchmann
c = conn_new(); ev = event(c)
t1 = leg(c, "EDWG", "EDWZ", START)                 # laedt in EDWG, landet in EDWZ (Ladeplatz)
t2 = leg(c, "EDWZ", "EDXH", shift(t1, 10))         # laedt Tee nach, dann zum Ziel
flight_row(c, "EDWG", "EDWZ", START, t1)
flight_row(c, "EDWZ", "EDXH", shift(t1, 10), t2)
zeige("S2  EDWG -> EDWZ -> EDXH   (MILCHMANN: zwei Ladeplaetze, dann Ziel)", c, ev)

# ---------------------------------------------------------------- S3: Zwischenlandung fremder Platz
c = conn_new(); ev = event(c)
t1 = leg(c, "EDWG", "EDDW", START)                 # laedt EDWG, Zwischenlandung Bremen (fremd)
t2 = leg(c, "EDDW", "EDXH", shift(t1, 10))         # weiter zum Ziel — Ladung ist an Bord!
flight_row(c, "EDWG", "EDDW", START, t1)
flight_row(c, "EDDW", "EDXH", shift(t1, 10), t2)
zeige("S3  EDWG -> EDDW(fremd) -> EDXH   (Zwischenlandung an fremdem Platz)", c, ev)

# ---------------------------------------------------------------- S4: Logout an anderem Ladeplatz
c = conn_new(); ev = event(c)
t1 = leg(c, "EDWG", "EDWZ", START)                 # laedt EDWG, landet EDWZ, LOGOUT dort
flight_row(c, "EDWG", "EDWZ", START, t1)
zeige("S4  EDWG -> EDWZ, LOGOUT   (Ware muesste in EDWZ liegen und neu ladbar sein)",
      c, ev, verluste=True)

# ---------------------------------------------------------------- S5: Logout fremder Platz
c = conn_new(); ev = event(c)
t1 = leg(c, "EDWG", "EDDW", START)
flight_row(c, "EDWG", "EDDW", START, t1)
zeige("S5  EDWG -> EDDW(fremd), LOGOUT", c, ev, verluste=True)

# ------------------------------------------------ S3b: wie S3, aber MIT Latch (echter Betrieb)
c = conn_new(); ev = event(c)
t1 = leg(c, "EDWG", "EDDW", START)
t2 = leg(c, "EDDW", "EDXH", shift(t1, 10))
flight_row(c, "EDWG", "EDDW", START, t1)
flight_row(c, "EDDW", "EDXH", shift(t1, 10), t2)
# Der Poller haette beim Vollstopp in EDXH gelatcht:
set_transport_live_arrival(c, 1, shift(t1, 10), ev["id"], t2)
zeige("S3b EDWG -> EDDW(fremd) -> EDXH  MIT Live-Ankunfts-Latch (= echter Betrieb)", c, ev)

# ------------------------------------------------ S2b: Milchmann MIT Latch
c = conn_new(); ev = event(c)
t1 = leg(c, "EDWG", "EDWZ", START)
t2 = leg(c, "EDWZ", "EDXH", shift(t1, 10))
flight_row(c, "EDWG", "EDWZ", START, t1)
flight_row(c, "EDWZ", "EDXH", shift(t1, 10), t2)
set_transport_live_arrival(c, 1, shift(t1, 10), ev["id"], t2)
zeige("S2b MILCHMANN MIT Latch (= echter Betrieb)", c, ev)

# ---- S8: Start EDWG, Logout kurz nach dem Abheben IN DER LUFT, 30 s spaeter Login am Platz ----
from app.gps_legs import detect_gps_legs, collapse_same_airport
c = conn_new(); ev = event(c)
la, lo, ea = coords("EDWG")
# durchgehender Track: Boden -> abgehoben -> [Logout] -> [Login 30 s spaeter] -> zurueck am Boden
pos(c, START,               la, lo, ea,        0)     # am Boden EDWG
pos(c, shift(START, 1),     la, lo, ea + 250,  70)    # abgehoben
pos(c, shift(START, 2),     la, lo, ea + 1200, 90)    # in der Luft  <-- hier LOGOUT
# --- 30 s Luecke (Verbindung weg), dann neu eingeloggt am Platz ---
pos(c, shift(START, 3),     la, lo, ea,        0)     # steht wieder in EDWG
c.commit()
# zwei getrennte VATSIM-Sessions:
flight_row(c, "EDWG", "EDXH", START, shift(START, 2))          # Session 1: endet in der Luft
c.execute("INSERT INTO flights (cid, callsign, aircraft_short, departure, arrival, logon_time) "
          "VALUES (1,'FRS01',?,?,'',?)", (AC, "EDWG", shift(START, 3)))   # Session 2: offen
c.commit()

na, el = geo.nearest_airport_icao, geo.airport_elevation_ft
K = dict(nearest_airport=na, airport_elev_ft=el, radius_km=4.0, rescue_before=None)
allp = [dict(r) for r in c.execute(
    "SELECT ts, latitude, longitude, altitude, groundspeed FROM position_history "
    "WHERE cid=1 ORDER BY ts")]
print("\n" + "=" * 78)
print("S8  Logout IN DER LUFT kurz nach dem Start, 30 s spaeter Login am selben Platz")
print("=" * 78)
print("  Track (durchgehend, Luecke nur 60 s):")
for p in allp:
    print("     %s  alt=%-5s gs=%-3s" % (p["ts"][11:19], p["altitude"], p["groundspeed"]))
legs = detect_gps_legs(allp, **K)
print("\n  Was der GPS-Detektor daraus macht:")
for l in legs:
    print("     seg=%s  %s -> %s  complete=%s  takeoff=%s landing=%s" % (
        l["segment"], l["dep_icao"], l["arr_icao"], l["complete"],
        (l["takeoff_ts"] or "")[11:19], (l["landing_ts"] or "")[11:19]))
print("\n  canonicalize_legs (was die Kutter-Logik sieht):")
for f in db.canonicalize_legs(c, cids=[1], callsign_prefix="FRS"):
    print("     %s -> %s  logon=%s logoff=%s  connection_closed=%s" % (
        f.get("gps_departure"), f.get("gps_arrival"), (f.get("logon_time") or "")[11:19],
        (f.get("logoff_time") or "")[11:19], f.get("connection_closed")))
print("\n  VATSIM-Sessions (flights-Tabelle) — hier steht der ECHTE Logout:")
for r in c.execute("SELECT logon_time, logoff_time FROM flights WHERE cid=1 ORDER BY logon_time"):
    print("     logon=%s  logoff=%s" % (r[0][11:19], (r[1] or "(offen)")[11:19] if r[1] else "(offen)"))
zeige("S8  -> was die HEUTIGE Wertung sagt", c, ev, verluste=True)
