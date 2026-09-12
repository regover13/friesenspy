# -*- coding: utf-8 -*-
"""Stellt VIELE Titel nebeneinander vor das Flugzeug -- zum Mitschauen.

**Warum das neben `kieker_probe.py` steht und nicht darin:** Die Probe beantwortet eine Frage
je Lauf, baut dafuer eine eigene Verbindung auf und raeumt danach auf. Das ist fuer eine
einzelne Messung richtig, taugt aber nicht, um hundert Titel durchzugehen -- jeder Lauf kostet
Sekunden, und das Objekt ist wieder fort, bevor jemand hingesehen hat.

Hier laeuft es umgekehrt: **eine** Verbindung, alle Titel in einer Reihe, und sie bleibt offen,
solange jemand schaut. Denn Objekte sterben mit der SimConnect-Verbindung (11.09.2026
gemessen, `EXCEPTION 3` in der Nachprobe) -- wer sie sehen will, darf sie nicht schliessen.

Der Nutzer wollte mitschauen statt Tabellen zu lesen (12.09.2026), und das ist berechtigt:
Ob ein Titel angenommen wird, sagt die Objekt-ID. Ob das Modell etwas taugt -- Groesse, Form,
ob es im Boden steckt --, sagt nur das Auge.

    python titel_schau.py --datei titel.txt
    python titel_schau.py Seagull Flamingo Goose HumpbackWhale
    python titel_schau.py --datei titel.txt --ab 40 --anzahl 20

Die Reihe steht QUER vor der Nase, mittig, in `--abstand` Metern. Bei vielen Titeln wird sie
lang: 40 Objekte bei 25 m sind ein Kilometer. Dann lieber in Haeppchen (`--ab`/`--anzahl`).
"""

from __future__ import annotations

import argparse
import ctypes
import math
import sys
import time

from kieker_probe import (
    EXCEPTION_NAMEN,
    InitPosition,
    RecvAssignedObjectId,
    RecvException,
    RECV_ASSIGNED_OBJECT_ID,
    RECV_EXCEPTION,
    _bindungen,
    _eigene_lage,
    _pakete,
    _schliessen,
    _verbinden,
    dll_finden,
)

# Je Titel eine eigene Anfrage-Nummer -- nur so laesst sich eine Antwort zuordnen. Das ist
# derselbe Grund wie in bruegge.cpp (REQ_ERZEUGEN + i): Der Simulator schickt Objekt-IDs und
# Ausnahmen asynchron, und ohne eigene Nummer weiss niemand, wer gemeint ist.
REQ_BASIS = 5000


def _versetzt(lat, lon, kurs, vor_m, quer_m):
    """Ein Punkt relativ zur Flugzeugnase -- `vor` in Blickrichtung, `quer` nach rechts."""
    a = math.radians(kurs)
    q = math.radians((kurs + 90) % 360)
    dlat = (vor_m * math.cos(a) + quer_m * math.cos(q)) / 111320.0
    dlon = (vor_m * math.sin(a) + quer_m * math.sin(q)) / (111320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def schau(titel: list[str], vor_m: float, abstand_m: float, halten_s: int,
          dll_pfad=None) -> int:
    sc = ctypes.WinDLL(str(dll_pfad or dll_finden(None)))
    _bindungen(sc)
    handle = _verbinden(sc, b"FriesenBruegge-TitelSchau")
    if handle is None:
        return 2

    lage = _eigene_lage(sc, handle)
    if lage is None:
        _schliessen(sc, handle)
        return 2
    lat, lon, _alt = lage

    # Der Kurs steckt nicht in _eigene_lage -- die Reihe laeuft deshalb von West nach Ost
    # (quer = Ost). Fuer den Zweck genuegt das: Der Pilot dreht sich einmal um die eigene
    # Achse und sieht alles.
    kurs = 0.0

    print(f"Flugzeug bei {lat:.5f} / {lon:.5f}")
    print(f"{len(titel)} Titel, {abstand_m:.0f} m Abstand, {vor_m:.0f} m noerdlich.\n")

    # ALLE Auftraege zuerst raus, dann die Antworten einsammeln. Andersherum -- je Titel
    # senden und warten -- dauerte bei hundert Titeln eine Viertelstunde, und die Antworten
    # kommen ohnehin asynchron.
    mitte = (len(titel) - 1) / 2.0
    for i, t in enumerate(titel):
        zlat, zlon = _versetzt(lat, lon, kurs, vor_m, (i - mitte) * abstand_m)
        pos = InitPosition()
        pos.Latitude, pos.Longitude = zlat, zlon
        pos.Altitude = 0.0
        pos.Pitch = pos.Bank = pos.Heading = 0.0
        pos.OnGround = 1          # seit 12.09.2026 belegt: wirkt, der Sim setzt selbst auf
        pos.Airspeed = 0
        try:
            sc.SimConnect_AICreateSimulatedObject(handle, t.encode("utf-8"), pos,
                                                  REQ_BASIS + i)
        except OSError as e:
            print(f"  {t}: Aufruf abgelehnt ({e})")

    ergebnis: dict[int, str] = {}
    for art, zeiger in _pakete(sc, handle, max(6, len(titel) * 0.25)):
        if art == RECV_ASSIGNED_OBJECT_ID:
            z = ctypes.cast(zeiger, ctypes.POINTER(RecvAssignedObjectId)).contents
            ergebnis[z.dwRequestID - REQ_BASIS] = f"steht  (Objekt {z.dwObjectID})"
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            # dwSendID ordnet die Ausnahme dem Aufruf zu -- ohne sie waere nur zu raten,
            # welcher Titel gemeint ist (derselbe Fund wie in bruegge.cpp, 12.09.2026).
            ergebnis.setdefault(-1, "")
            name = EXCEPTION_NAMEN.get(ex.dwException, "unbekannt")
            ergebnis[-len(ergebnis) - 1] = f"EXCEPTION {ex.dwException} -- {name}"

    ging = []
    for i, t in enumerate(titel):
        stand = ergebnis.get(i)
        if stand:
            ging.append(t)
            print(f"  {t:<34} {stand}")
    fehlt = [t for i, t in enumerate(titel) if not ergebnis.get(i)]
    for t in fehlt:
        print(f"  {t:<34} -- keine Objekt-ID")

    print(f"\n{len(ging)} von {len(titel)} stehen.")
    if ging:
        print("Von WEST nach OST, in dieser Reihenfolge:")
        print("  " + "  |  ".join(ging))

    print(f"\nDie Verbindung bleibt {halten_s} s offen -- solange stehen die Objekte.")
    print("(Beim Schliessen raeumt SimConnect sie weg, gemessen 11.09.2026.)")
    for rest in range(halten_s, 0, -10):
        time.sleep(min(10, rest))
        print(f"  noch {max(0, rest - 10)} s")

    _schliessen(sc, handle)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("titel", nargs="*", help="Titel direkt auf der Kommandozeile")
    ap.add_argument("--datei", help="Datei mit einem Titel je Zeile")
    ap.add_argument("--ab", type=int, default=0, help="ab welchem Titel der Datei")
    ap.add_argument("--anzahl", type=int, help="wie viele daraus")
    ap.add_argument("--vor", type=float, default=120.0, metavar="METER",
                    help="wie weit noerdlich die Reihe steht (Vorgabe 120)")
    ap.add_argument("--abstand", type=float, default=25.0, metavar="METER",
                    help="Abstand zwischen zwei Objekten (Vorgabe 25)")
    ap.add_argument("--halten", type=int, default=120, metavar="SEKUNDEN",
                    help="wie lange die Verbindung offen bleibt (Vorgabe 120)")
    ap.add_argument("--dll", help="Pfad zu SimConnect.dll")
    a = ap.parse_args()

    titel = list(a.titel)
    if a.datei:
        with open(a.datei, encoding="utf-8") as f:
            aus_datei = [z.strip() for z in f if z.strip() and not z.startswith("#")]
        aus_datei = aus_datei[a.ab:]
        if a.anzahl:
            aus_datei = aus_datei[:a.anzahl]
        titel += aus_datei
    if not titel:
        ap.error("keine Titel -- weder als Argument noch ueber --datei")

    return schau(titel, a.vor, a.abstand, a.halten, a.dll)


if __name__ == "__main__":
    sys.exit(main())
