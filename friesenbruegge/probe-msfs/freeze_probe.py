# -*- coding: utf-8 -*-
"""Haelt `FREEZE_ALTITUDE_SET` ein gesetztes Objekt in der Luft? (16.09.2026)

**Die Frage, und warum sie hier steht und nicht in `bruegge.cpp`.** Ein Objekt, das die
Bruegge mit `auf_boden=false` und einer Hoehe setzt, faellt: gemessen am 16.09.2026 fiel ein
`HotAirBalloon Passengers` von 3000 ft in 15 Sekunden auf Gelaendehoehe und blieb dort
liegen. Ein Windrad an derselben Stelle stand exakt auf 3000,0 ft -- **statische SimObjects
haben keine Physik, Flugzeuge schon.**

Der naheliegende Ausweg sind die Freeze-Ereignisse aus dem SDK
(`WASM/include/MSFS/Types/MSFS_EventsEnum.h:1220 ff.`). Ob sie auf ein Objekt aus
`AICreateSimulatedObject` wirken, steht **nirgends** -- und ein Versuch im WASM-Modul kostet
einen Build und eine Verteilung an 61 Piloten.

**Hier kostet er dreissig Sekunden.** Extern, ueber dieselbe SimConnect-DLL, ohne
Sim-Neustart und ohne dass jemand etwas herunterladen muss.

⚠ **A/B, nicht nur A.** Der Lauf setzt ZWEI Objekte desselben Titels nebeneinander -- eines
mit Freeze, eines ohne -- und misst beide Sekunde fuer Sekunde. Ein Einzellauf koennte auch
dann gut aussehen, wenn der Simulator das Objekt aus einem ganz anderen Grund haelt (Wetter,
Windstille, Reality Bubble). Der Unterschied zwischen den beiden ist die Messung, nicht der
Absolutwert.

    python freeze_probe.py                                   # HotAirBalloon Passengers
    python freeze_probe.py --titel "C172SP G1000 Passengers"
    python freeze_probe.py --hoehe 3000 --dauer 30

Die Objekte sterben mit der Verbindung (11.09.2026 gemessen) -- der Lauf raeumt also selbst
auf, und es bleibt nichts stehen.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import math
import sys
import time

from kieker_probe import (
    EXCEPTION_NAMEN,
    InitPosition,
    OBJEKT_USER,
    RECV_ASSIGNED_OBJECT_ID,
    RECV_EXCEPTION,
    RECV_SIMOBJECT_DATA,
    Recv,
    RecvAssignedObjectId,
    RecvException,
    RecvSimObjectData,
    _bindungen,
    _eigene_lage,
    _lage_abonnieren,
    _pakete,
    _schliessen,
    _verbinden,
    dll_finden,
)

#: Die drei Freeze-Ereignisse. ALTITUDE allein genuegt fuer „faellt nicht" -- ohne die
#: beiden anderen treibt das Objekt im Wind ab und kippt, was beim Messen wie ein
#: Teilerfolg aussieht. Sie werden deshalb zusammen gesetzt und einzeln protokolliert.
FREEZE = (
    ("FREEZE_ALTITUDE_SET", 9001),
    ("FREEZE_ATTITUDE_SET", 9002),
    ("FREEZE_LATITUDE_LONGITUDE_SET", 9003),
)

GRUPPE_HOECHSTE = 1            # SIMCONNECT_GROUP_PRIORITY_HIGHEST, Header Zeile 36
FLAG_GRUPPE_IST_PRIORITAET = 0x00000010   # Header Zeile 406

REQ_FROST = 5001               # Lagemeldung des eingefrorenen Objekts
REQ_FREI = 5002                # ... und des freien danebenstehenden


def _event_bindungen(sc: ctypes.WinDLL) -> None:
    """Die zwei Signaturen, die `kieker_probe._bindungen` nicht kennt (Header 1020/1021)."""
    sc.SimConnect_MapClientEventToSimEvent.restype = ctypes.HRESULT
    sc.SimConnect_MapClientEventToSimEvent.argtypes = [w.HANDLE, w.DWORD, ctypes.c_char_p]
    sc.SimConnect_TransmitClientEvent.restype = ctypes.HRESULT
    sc.SimConnect_TransmitClientEvent.argtypes = [
        w.HANDLE, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
    ]


def _versetzt(lat: float, lon: float, kurs_grad: float, vor_m: float, quer_m: float):
    """Ein Punkt relativ zum Piloten -- `vor_m` in Blickrichtung, `quer_m` nach rechts."""
    v = math.radians(kurs_grad)
    q = math.radians((kurs_grad + 90.0) % 360.0)
    dn = vor_m * math.cos(v) + quer_m * math.cos(q)
    de = vor_m * math.sin(v) + quer_m * math.sin(q)
    return (lat + dn / 111320.0,
            lon + de / (111320.0 * math.cos(math.radians(lat))))


def _erzeugen(sc, handle, titel: str, lat: float, lon: float, hoehe_ft: float,
              anfrage: int) -> tuple[int | None, str | None]:
    """Ein Objekt setzen und auf seine Objekt-ID warten. `(id, fehler)`."""
    pos = InitPosition()
    pos.Latitude, pos.Longitude, pos.Altitude = lat, lon, hoehe_ft
    pos.Pitch = pos.Bank = 0.0
    pos.Heading = 0.0
    pos.OnGround = 0            # in der Luft -- darum geht es hier
    pos.Airspeed = 0
    sc.SimConnect_AICreateSimulatedObject(handle, titel.encode("utf-8"), pos, anfrage)

    # `_pakete` liefert `(dwID, zeiger)` -- nicht die Struktur selbst.
    objekt_id, fehler = None, None
    for art, zeiger in _pakete(sc, handle, 4.0):
        if art == RECV_ASSIGNED_OBJECT_ID:
            z = ctypes.cast(zeiger, ctypes.POINTER(RecvAssignedObjectId)).contents
            if z.dwRequestID == anfrage:
                objekt_id = int(z.dwObjectID)
                break
        elif art == RECV_EXCEPTION:
            e = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            fehler = EXCEPTION_NAMEN.get(int(e.dwException), f"EXCEPTION_{e.dwException}")
    return objekt_id, fehler


def _einfrieren(sc, handle, objekt_id: int) -> list[str]:
    """Die drei Freeze-Ereignisse an ein Objekt schicken. Liefert die, die scheiterten."""
    _event_bindungen(sc)
    schlecht = []
    for name, eid in FREEZE:
        hr = sc.SimConnect_MapClientEventToSimEvent(handle, eid, name.encode("ascii"))
        if hr != 0:
            schlecht.append(f"{name}: MAP_HR_{hr:08X}")
            continue
        # dwData = 1 heisst „einfrieren" (die `_SET`-Fassungen nehmen den Zustand als Wert;
        # `_TOGGLE` braeuchte keinen, waere aber nicht idempotent).
        hr = sc.SimConnect_TransmitClientEvent(
            handle, objekt_id, eid, 1, GRUPPE_HOECHSTE, FLAG_GRUPPE_IST_PRIORITAET)
        if hr != 0:
            schlecht.append(f"{name}: SEND_HR_{hr:08X}")
    return schlecht


def probe(titel: str, hoehe_ft: float, dauer_s: float, dll_pfad=None) -> int:
    sc = ctypes.WinDLL(str(dll_pfad or dll_finden(None)))
    _bindungen(sc)
    handle = _verbinden(sc, b"FreezeProbe")
    if handle is None:
        print("Keine Verbindung zum Simulator.")
        return 2

    try:
        eigene = _eigene_lage(sc, handle)
        if eigene is None:
            print("Eigene Lage nicht zu ermitteln -- laeuft ein Flug?")
            return 2
        lat, lon, _ = eigene
        # Kurs kennt `_eigene_lage` nicht; nach Norden versetzen genuegt fuer die Messung.
        frost_lat, frost_lon = _versetzt(lat, lon, 0.0, 600.0, -150.0)
        frei_lat, frei_lon = _versetzt(lat, lon, 0.0, 600.0, +150.0)

        print(f"Titel: {titel!r}   Hoehe: {hoehe_ft:.0f} ft   Dauer: {dauer_s:.0f} s")
        id_frost, f1 = _erzeugen(sc, handle, titel, frost_lat, frost_lon, hoehe_ft, 7001)
        id_frei, f2 = _erzeugen(sc, handle, titel, frei_lat, frei_lon, hoehe_ft, 7002)
        print(f"  eingefroren -> id={id_frost} {f1 or ''}")
        print(f"  frei        -> id={id_frei} {f2 or ''}")
        if id_frost is None or id_frei is None:
            print("Mindestens ein Objekt kam nicht zustande -- kein Vergleich moeglich.")
            return 1

        schlecht = _einfrieren(sc, handle, id_frost)
        print("  Freeze gesendet" + (f" -- FEHLER: {', '.join(schlecht)}" if schlecht
                                     else " (alle drei angenommen)"))

        _lage_abonnieren(sc, handle, id_frost, REQ_FROST, True)
        _lage_abonnieren(sc, handle, id_frei, REQ_FREI, True)

        letzte = {REQ_FROST: None, REQ_FREI: None}
        begonnen = time.time()
        print("\n   t     eingefroren        frei")
        while time.time() - begonnen < dauer_s:
            for art, zeiger in _pakete(sc, handle, 1.0):
                if art != RECV_SIMOBJECT_DATA:
                    continue
                z = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
                if int(z.dwRequestID) not in letzte:
                    continue
                letzte[int(z.dwRequestID)] = (z.werte[0], z.werte[1], z.werte[2])
            t = time.time() - begonnen
            a = letzte[REQ_FROST]
            b = letzte[REQ_FREI]
            print(f"  {t:4.0f}s  {a[2]:10.1f} ft   {b[2]:10.1f} ft" if a and b
                  else f"  {t:4.0f}s  (noch keine Meldung)")

        a, b = letzte[REQ_FROST], letzte[REQ_FREI]
        print()
        if a and b:
            print(f"ERGEBNIS nach {dauer_s:.0f} s: eingefroren {a[2]:.1f} ft, "
                  f"frei {b[2]:.1f} ft, angefordert {hoehe_ft:.0f} ft")
            # Die Schwelle ist grob mit Absicht: Es geht um „haelt" gegen „faellt", nicht um
            # Fuesse. Ein Objekt, das 100 ft verloren hat, haelt nicht.
            haelt = abs(a[2] - hoehe_ft) < 100.0
            faellt = (hoehe_ft - b[2]) > 100.0
            if haelt and faellt:
                print("=> FREEZE WIRKT: das eingefrorene haelt, das freie faellt.")
            elif haelt and not faellt:
                print("=> UNENTSCHIEDEN: beide halten -- der Titel faellt hier gar nicht. "
                      "Mit einem Titel wiederholen, der nachweislich faellt.")
            else:
                print("=> FREEZE WIRKT NICHT auf ein Objekt aus AICreateSimulatedObject.")
        return 0
    finally:
        _schliessen(sc, handle)


def halten(titel: str, ueber_ft: float, vor_m: float, quer_m: float,
           dauer_s: float, dll_pfad=None) -> int:
    """EIN Objekt relativ zum Piloten hinstellen und festhalten -- zum Hinsehen.

    ⚠ **Es lebt nur, solange dieser Lauf laeuft.** Objekte sterben mit der
    SimConnect-Verbindung (11.09.2026 gemessen). Das ist hier kein Mangel, sondern der
    Grund, warum die Probe nichts hinterlaesst -- wer es dauerhaft will, braucht die
    Bruegge, und die kann noch nicht einfrieren.
    """
    sc = ctypes.WinDLL(str(dll_pfad or dll_finden(None)))
    _bindungen(sc)
    handle = _verbinden(sc, b"FreezeHalten")
    if handle is None:
        print("Keine Verbindung zum Simulator.")
        return 2
    try:
        eigene = _eigene_lage(sc, handle)
        if eigene is None:
            print("Eigene Lage nicht zu ermitteln -- laeuft ein Flug?")
            return 2
        lat, lon, eigene_ft = eigene
        zl, zo = _versetzt(lat, lon, 0.0, vor_m, quer_m)
        hoehe = eigene_ft + ueber_ft
        print(f"Du: {lat:.5f} {lon:.5f} {eigene_ft:.0f} ft")
        print(f"{titel!r} -> {zl:.5f} {zo:.5f} auf {hoehe:.0f} ft "
              f"({ueber_ft:+.0f} ft ueber dir)")
        oid, fehler = _erzeugen(sc, handle, titel, zl, zo, hoehe, 7101)
        if oid is None:
            print(f"Kam nicht zustande: {fehler or 'keine Objekt-ID'}")
            return 1
        schlecht = _einfrieren(sc, handle, oid)
        print(f"  id={oid}, Freeze " + (", ".join(schlecht) if schlecht else "gesetzt"))

        _lage_abonnieren(sc, handle, oid, REQ_FROST, True)
        begonnen = time.time()
        letzte = None
        while time.time() - begonnen < dauer_s:
            for art, zeiger in _pakete(sc, handle, 10.0):
                if art != RECV_SIMOBJECT_DATA:
                    continue
                z = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
                if int(z.dwRequestID) == REQ_FROST:
                    letzte = (z.werte[0], z.werte[1], z.werte[2])
            if letzte:
                print(f"  {time.time()-begonnen:5.0f}s  steht auf {letzte[2]:.1f} ft")
        print("Lauf zu Ende -- das Objekt verschwindet mit der Verbindung.")
        return 0
    finally:
        _schliessen(sc, handle)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--titel", default="HotAirBalloon Passengers")
    ap.add_argument("--hoehe", type=float, default=3000.0, help="ft MSL (A/B-Messung)")
    ap.add_argument("--dauer", type=float, default=25.0, help="Sekunden")
    ap.add_argument("--dll", help="Pfad zu SimConnect.dll")
    ap.add_argument("--halten", action="store_true",
                    help="statt der A/B-Messung EIN Objekt relativ zum Piloten festhalten")
    ap.add_argument("--ueber", type=float, default=1000.0, help="ft ueber dem Piloten")
    ap.add_argument("--vor", type=float, default=0.0, help="Meter nach Norden")
    ap.add_argument("--quer", type=float, default=0.0, help="Meter nach Osten")
    a = ap.parse_args()
    if a.halten:
        return halten(a.titel, a.ueber, a.vor, a.quer, a.dauer, a.dll)
    return probe(a.titel, a.hoehe, a.dauer, a.dll)


if __name__ == "__main__":
    sys.exit(main())
