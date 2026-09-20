# -*- coding: utf-8 -*-
"""Den MSFS-2024-Simulator selbst nach seinen SimObject-Titeln fragen (20.09.2026).

**Wozu.** Die Titel gestreamter MSFS-2024-Pakete lassen sich von der Platte nicht lesen: Im
Ordner `StreamedPackages` liegen nur wenige Dateien, die Virtual File System zeigt den Rest als
leere Platzhalter (manche mit Schloss, „Access Denied"), und Standard-Flugzeuge sind
verschluesselt (MSFS-SDK-Doku „The Virtual File System"; DevSupport-Thread „Using Streamed
Default Aircraft as a Base"). Beispiel: `fs24-microsoft-simobjects-animals-hippo` enthaelt
auf der Platte eine einzige Sounddatei. Damit kennt der Katalog fuer die 41 neuen Tierpakete
keine echten Titel -- und `AfricanElephant` u. a. (die 2020er Titel) gibt es in 2024 nicht.

**Was der Simulator anbietet.** `SimConnect_EnumerateSimObjectsAndLiveries(hSimConnect,
RequestID, SIMCONNECT_SIMOBJECT_TYPE)` -- nur MSFS 2024 (laut DevSupport seit 1.6.19.0). Der
Typ darf ALL, AIRCRAFT, HELICOPTER, BOAT, GROUND, HOT_AIR_BALLOON oder ANIMAL sein
(`SimConnect.h` des 2024er SDK); zurueck kommt je Eintrag `AircraftTitle[256]` und
`LiveryName[256]`, seitenweise (`dwEntryNumber` von `dwOutOf`).

⚠ **OFFEN, wofuer dieses Programm da ist:** Die einzige gefundene Verwendung nutzt den Typ
AIRCRAFT. Ob ANIMAL und GROUND tatsaechlich die Titel der Tiere und Fahrzeuge liefern, ist
ungeprueft. Erst wenn das hier Titel zeigt, lohnt der Umbau der Bruegge.

Kein Kompilieren noetig: reines ``ctypes`` gegen die ``SimConnect.dll`` des 2024er SDK.
**Nur MSFS 2024 darf laufen** (bei zwei Simulatoren antwortet der falsche).

    python titel_aufzaehlen.py                      # ANIMAL, GROUND, ALL -> Ausgabe + JSON
    python titel_aufzaehlen.py --typ ANIMAL --suche Elephant
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
from ctypes import POINTER, byref, c_char_p, c_int, c_void_p, c_ulong

SDK_DLL = r"C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll"
SDK_HEADER = r"C:\MSFS 2024 SDK\SimConnect SDK\include\SimConnect.h"

#: Aus `SimConnect.h` (SIMCONNECT_SIMOBJECT_TYPE) -- beim Start gegen den Header geprueft.
TYPEN = {"USER": 0, "ALL": 1, "AIRCRAFT": 2, "HELICOPTER": 3, "BOAT": 4, "GROUND": 5,
         "HOT_AIR_BALLOON": 6, "ANIMAL": 7, "USER_AVATAR": 8}
#: Aus `SimConnect.h` (SIMCONNECT_RECV_ID): Reihenfolge des Enums, beim Start geprueft.
RECV_EXCEPTION = 1
RECV_OPEN = 2
RECV_QUIT = 3
RECV_LIVERY_LIST = 38


def _enum_aus_header(name: str) -> list[str]:
    """Die Namen eines Enums in Deklarationsreihenfolge -- oder [] ohne Header."""
    if not os.path.exists(SDK_HEADER):
        return []
    text = open(SDK_HEADER, encoding="utf-8", errors="replace").read()
    a = text.find("SIMCONNECT_ENUM " + name)
    if a < 0:
        return []
    b = text.find("};", a)
    namen = []
    for zeile in text[a:b].splitlines()[2:]:
        zeile = zeile.split("//")[0].strip().rstrip(",")
        if zeile and "=" not in zeile:
            namen.append(zeile)
    return namen


def pruefe_konstanten() -> None:
    """Die abgeschriebenen Zahlen gegen den Header halten -- ein falscher Index waere still."""
    ids = _enum_aus_header("SIMCONNECT_RECV_ID")
    if ids:
        assert ids.index("SIMCONNECT_RECV_ID_ENUMERATE_SIMOBJECT_AND_LIVERY_LIST") == RECV_LIVERY_LIST
        assert ids.index("SIMCONNECT_RECV_ID_EXCEPTION") == RECV_EXCEPTION
        assert ids.index("SIMCONNECT_RECV_ID_OPEN") == RECV_OPEN
    if os.path.exists(SDK_HEADER):
        text = open(SDK_HEADER, encoding="utf-8", errors="replace").read()
        a = text.find("SIMCONNECT_ENUM SIMCONNECT_SIMOBJECT_TYPE")
        block = text[a:text.find("};", a)]
        zaehl = 0
        for zeile in block.splitlines()[2:]:
            z = zeile.split("//")[0].strip().rstrip(",")
            if not z:
                continue
            if "=" in z:
                zaehl = int(z.split("=")[1].strip())
                name = z.split("=")[0].strip()
            else:
                name = z
            kurz = name.replace("SIMCONNECT_SIMOBJECT_TYPE_", "")
            if kurz in TYPEN and kurz != "USER_AIRCRAFT":
                assert TYPEN[kurz] == zaehl, (kurz, TYPEN[kurz], zaehl)
            zaehl += 1


def oeffnen():
    dll = ctypes.WinDLL(SDK_DLL)
    dll.SimConnect_Open.argtypes = [POINTER(c_void_p), c_char_p, c_void_p, c_ulong, c_void_p, c_ulong]
    dll.SimConnect_Open.restype = ctypes.c_long
    dll.SimConnect_Close.argtypes = [c_void_p]
    dll.SimConnect_Close.restype = ctypes.c_long
    dll.SimConnect_GetNextDispatch.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_ulong)]
    dll.SimConnect_GetNextDispatch.restype = ctypes.c_long
    dll.SimConnect_EnumerateSimObjectsAndLiveries.argtypes = [c_void_p, c_ulong, c_int]
    dll.SimConnect_EnumerateSimObjectsAndLiveries.restype = ctypes.c_long
    h = c_void_p()
    hr = dll.SimConnect_Open(byref(h), b"FriesenSpy Titel-Aufzaehlung", None, 0, None, 0)
    if hr != 0:
        raise SystemExit(f"SimConnect_Open fehlgeschlagen (HRESULT {hr & 0xFFFFFFFF:#010x}) -- "
                         "laeuft MSFS 2024, und ist ein Flug geladen?")
    return dll, h


def naechste(dll, h):
    """(dwID, Rohbytes) der naechsten Nachricht -- oder None, wenn gerade keine da ist."""
    p = c_void_p()
    n = c_ulong()
    if dll.SimConnect_GetNextDispatch(h, byref(p), byref(n)) != 0 or not p.value:
        return None
    roh = ctypes.string_at(p.value, n.value)
    return struct.unpack_from("<III", roh, 0)[2], roh


def _text(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def aufzaehlen(dll, h, typ: str, anfrage: int, warten_s: float = 20.0) -> tuple[list[dict], str | None]:
    """Alle Seiten eines Typs einsammeln. Zweiter Rueckgabewert: eine Ausnahme des Simulators."""
    hr = dll.SimConnect_EnumerateSimObjectsAndLiveries(h, anfrage, TYPEN[typ])
    if hr != 0:
        return [], f"Aufruf abgelehnt (HRESULT {hr & 0xFFFFFFFF:#010x})"
    eintraege: list[dict] = []
    gesehen = set()
    ende = time.time() + warten_s
    while time.time() < ende:
        m = naechste(dll, h)
        if not m:
            time.sleep(0.05)
            continue
        kennung, roh = m
        if kennung == RECV_EXCEPTION:
            _, _, _, exc, sendid, idx = struct.unpack_from("<6I", roh, 0)
            return eintraege, f"Ausnahme {exc} (SendID {sendid}, Index {idx})"
        if kennung == RECV_QUIT:
            return eintraege, "Simulator hat die Verbindung beendet"
        if kennung != RECV_LIVERY_LIST:
            continue
        req, groesse, nummer, von = struct.unpack_from("<4I", roh, 12)
        if req != anfrage:
            continue
        for i in range(groesse):
            off = 28 + i * 512
            eintraege.append({"titel": _text(roh[off:off + 256]),
                              "livery": _text(roh[off + 256:off + 512])})
        gesehen.add(nummer)
        if len(gesehen) >= von:
            return eintraege, None
    return eintraege, f"Zeit um: {len(gesehen)} Seite(n) erhalten"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--typ", action="append", choices=sorted(TYPEN),
                    help="Objekttyp (mehrfach moeglich); Vorgabe ANIMAL, GROUND, ALL")
    ap.add_argument("--suche", help="Teilstring, der in den Titeln vorkommen soll (nur Anzeige)")
    ap.add_argument("--aus", default=".", help="Ordner fuer die JSON-Dateien")
    a = ap.parse_args()
    pruefe_konstanten()
    dll, h = oeffnen()
    try:
        # Auf OPEN warten: erst danach nimmt der Simulator Anfragen an.
        ende = time.time() + 15
        offen = False
        while time.time() < ende and not offen:
            m = naechste(dll, h)
            if not m:
                time.sleep(0.05)
            elif m[0] == RECV_OPEN:
                offen = True
                # dwApplicationName[256], dwApplicationVersionMajor/Minor, ...Build
                v = struct.unpack_from("<4I", m[1], 12 + 256)
                print(f"Verbunden mit: {_text(m[1][12:12 + 256])}  Fassung {v[0]}.{v[1]}.{v[2]}.{v[3]}")
        if not offen:
            raise SystemExit("Keine OPEN-Nachricht -- laeuft ein Simulator?")
        for n, typ in enumerate(a.typ or ["ANIMAL", "GROUND", "ALL"], start=1):
            liste, fehler = aufzaehlen(dll, h, typ, 1000 + n)
            titel = sorted({e["titel"] for e in liste})
            print(f"\n{typ}: {len(liste)} Eintraege, {len(titel)} verschiedene Titel"
                  + (f"  --  {fehler}" if fehler else ""))
            for t in titel[:25]:
                print("   ", t)
            if len(titel) > 25:
                print(f"    ... und {len(titel) - 25} weitere")
            if a.suche:
                treffer = [t for t in titel if a.suche.lower() in t.lower()]
                print(f"  Treffer fuer '{a.suche}': {treffer}")
            pfad = os.path.join(a.aus, f"titel_{typ.lower()}.json")
            with open(pfad, "w", encoding="utf-8") as f:
                json.dump({"typ": typ, "fehler": fehler, "eintraege": liste}, f,
                          ensure_ascii=False, indent=1)
            print("  ->", pfad)
        return 0
    finally:
        dll.SimConnect_Close(h)


if __name__ == "__main__":
    sys.exit(main())
