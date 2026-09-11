"""Probeflug fuer den FriesenKieker: Laesst sich ein SimObject zur Laufzeit setzen?

Das ist die EINE Frage, an der der ganze Eventtyp haengt (Spec Abschnitt 2). Wenn ein
mitgeliefertes Boot per SimConnect auf einer Sandbank landet und dort stehen bleibt, lohnt
sich alles Weitere. Wenn nicht, lassen wir es.

Laeuft auf dem Windows-Rechner mit dem Simulator, NICHT auf dem Server.

    py kieker_probe.py --titel "Boat_Small"

Ohne --titel sucht das Skript erst einmal, welche Boote der Simulator ueberhaupt kennt:

    py kieker_probe.py --titel-suche

WICHTIG -- diese Datei ist auf dem Linux-Server geschrieben und dort NICHT lauffaehig
gewesen. Sie ist nach der offiziellen SimConnect-Signatur gebaut und gibt bei jedem
Schritt aus, was sie tut; ein Fehlschlag ist deshalb aussagekraeftig und kein Raetsel.
Die Enum-Nummern (RECV_ID 1 = EXCEPTION, 2 = OPEN) sind gegen die eigenen Messungen aus
regover13/FSEconomy-SimConnect-Stub, PROTOCOL_NOTES.md, gegengeprueft.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import os
import sys
import time
from pathlib import Path

# Kachelotplate, Sandbank westlich von Juist -- flach, frei, gut anzufliegen von EDWR/EDWG.
STANDARD_LAT = 53.6600
STANDARD_LON = 6.9800

# Wo SimConnect.dll ueblicherweise liegt. Die Liste wird der Reihe nach probiert; mit
# --dll laesst sich ein eigener Pfad angeben, und eine DLL NEBEN diesem Skript gewinnt
# immer (dann braucht es gar keine Suche).
DLL_KANDIDATEN = [
    r"%MSFS_SDK%\SimConnect SDK\lib\SimConnect.dll",
    r"%MSFS2024_SDK%\SimConnect SDK\lib\SimConnect.dll",
    r"C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll",
    r"C:\MSFS SDK\SimConnect SDK\lib\SimConnect.dll",
]

# SIMCONNECT_RECV_ID -- nur die, die hier vorkommen koennen.
RECV_EXCEPTION = 1
RECV_OPEN = 2
RECV_ASSIGNED_OBJECT_ID = 12

# SIMCONNECT_EXCEPTION, Auszug. Unbekannte Nummern werden roh ausgegeben, damit auch ein
# hier nicht gelisteter Fall auswertbar bleibt.
EXCEPTION_NAMEN = {
    0: "NONE",
    1: "ERROR (allgemeiner Fehler)",
    2: "SIZE_MISMATCH (Struktur passt nicht -- Aufrufproblem)",
    3: "UNRECOGNIZED_ID",
    4: "UNOPENED",
    5: "VERSION_MISMATCH",
    7: "NAME_UNRECOGNIZED (der Container-Titel ist dem Sim unbekannt)",
    12: "ILLEGAL_OPERATION",
    28: "OBJECT_CONTAINER (Container liess sich nicht erzeugen)",
    29: "OBJECT_AI (die KI-Engine hat abgelehnt)",
    30: "OBJECT_ATC",
    31: "OBJECT_SCHEDULE",
}


class InitPosition(ctypes.Structure):
    """SIMCONNECT_DATA_INITPOSITION -- 6 Doubles, dann 2 DWORDs (56 Bytes)."""

    _fields_ = [
        ("Latitude", ctypes.c_double),
        ("Longitude", ctypes.c_double),
        ("Altitude", ctypes.c_double),   # Fuss ueber MSL
        ("Pitch", ctypes.c_double),
        ("Bank", ctypes.c_double),
        ("Heading", ctypes.c_double),
        ("OnGround", w.DWORD),
        ("Airspeed", w.DWORD),
    ]


class Recv(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("dwVersion", w.DWORD), ("dwID", w.DWORD)]


class RecvException(ctypes.Structure):
    _fields_ = [
        ("dwSize", w.DWORD), ("dwVersion", w.DWORD), ("dwID", w.DWORD),
        ("dwException", w.DWORD), ("dwSendID", w.DWORD), ("dwIndex", w.DWORD),
    ]


class RecvAssignedObjectId(ctypes.Structure):
    _fields_ = [
        ("dwSize", w.DWORD), ("dwVersion", w.DWORD), ("dwID", w.DWORD),
        ("dwRequestID", w.DWORD), ("dwObjectID", w.DWORD),
    ]


def dll_finden(eigener: str | None) -> Path:
    """SimConnect.dll suchen. Eine DLL neben dem Skript hat Vorrang vor jeder Suche."""
    if eigener:
        p = Path(eigener)
        if not p.is_file():
            raise SystemExit(f"FEHLER: --dll zeigt auf nichts: {p}")
        return p
    daneben = Path(__file__).with_name("SimConnect.dll")
    if daneben.is_file():
        return daneben
    for muster in DLL_KANDIDATEN:
        p = Path(os.path.expandvars(muster))
        if "%" not in str(p) and p.is_file():
            return p
    raise SystemExit(
        "FEHLER: SimConnect.dll nicht gefunden.\n"
        "  Entweder das SDK installieren (MSFS_SDK muss dann gesetzt sein),\n"
        "  oder die DLL neben dieses Skript legen,\n"
        "  oder --dll <pfad> angeben.\n"
        "  Gesucht wurde in:\n    " + "\n    ".join(DLL_KANDIDATEN)
    )


def titel_suchen() -> None:
    """Alle Container-Titel aus den SimObjects-Ordnern lesen.

    SimConnect hat keinen Aufruf 'zeig mir alle Container'. Die Titel stehen aber im
    Klartext in den ``sim.cfg``-Dateien, und die liegen auf der Platte -- das ist der
    sichere Weg, statt einen Namen zu raten.
    """
    wurzeln: list[Path] = []
    for umgeb in ("APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        basis = os.environ.get(umgeb)
        if basis:
            wurzeln.append(Path(basis))
    for laufwerk in ("C:", "D:", "E:"):
        wurzeln.append(Path(laufwerk + "\\"))

    gefunden: dict[str, Path] = {}
    gesehen: set[Path] = set()
    for wurzel in wurzeln:
        if not wurzel.exists() or wurzel in gesehen:
            continue
        gesehen.add(wurzel)
        try:
            for cfg in wurzel.rglob("SimObjects/**/sim.cfg"):
                try:
                    text = cfg.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for zeile in text.splitlines():
                    z = zeile.strip()
                    if z.lower().startswith("title"):
                        _, _, wert = z.partition("=")
                        titel = wert.strip().strip('"')
                        if titel:
                            gefunden.setdefault(titel, cfg)
        except (OSError, PermissionError):
            continue

    if not gefunden:
        print("Keine sim.cfg gefunden. Dann bitte von Hand nachsehen, unter:")
        print(r"  ...\Packages\Official\...\SimObjects\Boats\<irgendwas>\sim.cfg")
        print(r"  Die Zeile 'title = ...' ist der Wert fuer --titel.")
        return

    boote = {t: p for t, p in gefunden.items() if "boat" in str(p).lower()
             or "boat" in t.lower() or "ship" in t.lower()}
    print(f"{len(gefunden)} Container-Titel gefunden, davon {len(boote)} nach Booten aussehend.\n")
    for titel, pfad in sorted(boote.items()):
        print(f"  {titel}\n      {pfad}")
    if not boote:
        print("  (nichts Bootartiges -- hier die ersten 40 Titel ueberhaupt:)")
        for titel in sorted(gefunden)[:40]:
            print(f"  {titel}")


def probe(titel: str, lat: float, lon: float, dll_pfad: Path, wartesekunden: int) -> int:
    print(f"SimConnect.dll: {dll_pfad}")
    sc = ctypes.WinDLL(str(dll_pfad))

    handle = w.HANDLE()
    sc.SimConnect_Open.restype = ctypes.HRESULT
    sc.SimConnect_Open.argtypes = [
        ctypes.POINTER(w.HANDLE), ctypes.c_char_p, w.HWND, w.DWORD, w.HANDLE, w.DWORD,
    ]
    try:
        sc.SimConnect_Open(ctypes.byref(handle), b"FriesenKieker-Probe", None, 0, None, 0)
    except OSError as e:
        print(f"FEHLSCHLAG: SimConnect_Open ging nicht durch ({e}).")
        print("  Laeuft der Simulator? Ist ein Flug geladen (nicht nur das Hauptmenue)?")
        return 2
    print("SimConnect_Open: verbunden.")

    sc.SimConnect_AICreateSimulatedObject.restype = ctypes.HRESULT
    sc.SimConnect_AICreateSimulatedObject.argtypes = [
        w.HANDLE, ctypes.c_char_p, InitPosition, w.DWORD,
    ]
    sc.SimConnect_GetNextDispatch.restype = ctypes.HRESULT
    sc.SimConnect_GetNextDispatch.argtypes = [
        w.HANDLE, ctypes.POINTER(ctypes.POINTER(Recv)), ctypes.POINTER(w.DWORD),
    ]
    sc.SimConnect_Close.restype = ctypes.HRESULT
    sc.SimConnect_Close.argtypes = [w.HANDLE]

    pos = InitPosition(
        Latitude=lat, Longitude=lon,
        Altitude=0.0,          # Meereshoehe -- eine Sandbank liegt auf null
        Pitch=0.0, Bank=0.0, Heading=210.0,
        OnGround=1,            # Boot liegt auf, faellt nicht
        Airspeed=0,
    )
    anfrage_id = 4711
    print(f'AICreateSimulatedObject: titel="{titel}" bei {lat:.4f}/{lon:.4f} ...')
    try:
        sc.SimConnect_AICreateSimulatedObject(handle, titel.encode("utf-8"), pos, anfrage_id)
    except OSError as e:
        print(f"FEHLSCHLAG: Der Aufruf selbst wurde abgelehnt ({e}).")
        print("  Das hiesse: die DLL kennt die Funktion nicht -- falsche/zu alte SimConnect.dll.")
        sc.SimConnect_Close(handle)
        return 2

    # Der Aufruf meldet fast immer Erfolg. Ob er WIRKLICH geklappt hat, kommt erst
    # nachtraeglich zurueck -- als ASSIGNED_OBJECT_ID (gut) oder EXCEPTION (schlecht).
    # Genau das ist die Falle, an der so ein Probeflug sonst als "hat funktioniert"
    # durchgeht, obwohl nichts entstanden ist.
    print(f"Warte {wartesekunden} s auf die Antwort des Simulators ...")
    ergebnis = 1
    ende = time.time() + wartesekunden
    zeiger = ctypes.POINTER(Recv)()
    groesse = w.DWORD()
    while time.time() < ende:
        try:
            sc.SimConnect_GetNextDispatch(handle, ctypes.byref(zeiger), ctypes.byref(groesse))
        except OSError:
            time.sleep(0.05)
            continue
        if not zeiger:
            time.sleep(0.05)
            continue
        art = zeiger.contents.dwID
        if art == RECV_ASSIGNED_OBJECT_ID:
            zu = ctypes.cast(zeiger, ctypes.POINTER(RecvAssignedObjectId)).contents
            print(f"\n  ERFOLG: Objekt-ID {zu.dwObjectID} (Anfrage {zu.dwRequestID}).")
            print("  Der Simulator hat das Objekt angelegt.")
            ergebnis = 0
            break
        if art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            name = EXCEPTION_NAMEN.get(ex.dwException, "unbekannt")
            print(f"\n  ABGELEHNT: EXCEPTION {ex.dwException} -- {name}")
            if ex.dwException == 7:
                print('  Der Titel stimmt nicht. Mit "--titel-suche" die echten Namen holen.')
            ergebnis = 1
            break
        if art == RECV_OPEN:
            continue
        print(f"  (Nebenmeldung RECV_ID {art}, ignoriert)")
    else:
        print("\n  KEINE ANTWORT. Weder Objekt-ID noch Fehler.")
        print("  Das ist selbst ein Befund: der Aufruf verpufft folgenlos.")
        ergebnis = 3

    sc.SimConnect_Close(handle)

    if ergebnis == 0:
        print("\n" + "=" * 68)
        print("  JETZT NACHSEHEN -- die Objekt-ID beweist noch nichts Sichtbares.")
        print(f"  Per Slew oder Anflug nach {lat:.4f} / {lon:.4f} und schauen,")
        print("  ob das Boot dort liegt und liegen BLEIBT (auch nach 2 Minuten).")
        print("=" * 68)
    return ergebnis


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Dieses Skript gehoert auf den Windows-Rechner mit dem Simulator.")
        return 2
    ap = argparse.ArgumentParser(description="FriesenKieker: SimObject-Probeflug")
    ap.add_argument("--titel", help='Container-Titel, z. B. "Boat_Small"')
    ap.add_argument("--titel-suche", action="store_true",
                    help="Nur nachsehen, welche Container der Sim kennt")
    ap.add_argument("--lat", type=float, default=STANDARD_LAT)
    ap.add_argument("--lon", type=float, default=STANDARD_LON)
    ap.add_argument("--dll", help="Pfad zu SimConnect.dll")
    ap.add_argument("--warten", type=int, default=10, help="Sekunden auf die Antwort")
    a = ap.parse_args()

    if a.titel_suche:
        titel_suchen()
        return 0
    if not a.titel:
        ap.error('entweder --titel "..." oder --titel-suche')
    return probe(a.titel, a.lat, a.lon, dll_finden(a.dll), a.warten)


if __name__ == "__main__":
    raise SystemExit(main())
