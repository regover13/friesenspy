"""Probeflug fuer den FriesenKieker: Laesst sich ein SimObject zur Laufzeit setzen?

Das ist die EINE Frage, an der der ganze Eventtyp haengt (Spec Abschnitt 2). Wenn ein
mitgeliefertes Boot per SimConnect auf einer Sandbank landet und dort stehen bleibt, lohnt
sich alles Weitere. Wenn nicht, lassen wir es.

Laeuft auf dem Windows-Rechner mit dem Simulator, NICHT auf dem Server.

    py kieker_probe.py --titel "Boat01"

Ohne --titel sucht das Skript erst einmal, welche Boote der Simulator ueberhaupt kennt:

    py kieker_probe.py --titel-suche

STAND 11.09.2026 -- am Simulator-Rechner ueberarbeitet. Die Erstfassung kam vom Linux-Server
und war ungeprueft; was daran falsch war, steht als Kommentar an der jeweiligen Stelle. Alle
Enum-Werte und Signaturen sind jetzt gegen den echten SDK-Header gezaehlt:
C:\\MSFS 2024 SDK\\SimConnect SDK\\include\\SimConnect.h
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import math
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
#
# KORREKTUR: MSFS2024_SDK steht VOR MSFS_SDK. Auf diesem Rechner zeigt MSFS_SDK auf das
# 2020er SDK (D:\MSFS SDK) und MSFS2024_SDK auf C:\MSFS 2024 SDK -- die alte Reihenfolge
# haette also gegen MSFS 2024 die aeltere DLL genommen.
DLL_KANDIDATEN = [
    r"%MSFS2024_SDK%\SimConnect SDK\lib\SimConnect.dll",
    r"%MSFS_SDK%\SimConnect SDK\lib\SimConnect.dll",
    r"C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll",
    r"C:\MSFS SDK\SimConnect SDK\lib\SimConnect.dll",
]

# SIMCONNECT_RECV_ID -- am Header nachgezaehlt (Zeile 88 ff.): NULL=0, EXCEPTION=1, OPEN=2,
# QUIT=3, EVENT=4, EVENT_OBJECT_ADDREMOVE=5, EVENT_FILENAME=6, EVENT_FRAME=7,
# SIMOBJECT_DATA=8, SIMOBJECT_DATA_BYTYPE=9, WEATHER_OBSERVATION=10, CLOUD_STATE=11,
# ASSIGNED_OBJECT_ID=12. Die 12 war aus dem SDK uebernommen und stimmt.
RECV_EXCEPTION = 1
RECV_OPEN = 2
RECV_QUIT = 3
RECV_SIMOBJECT_DATA = 8
RECV_SIMOBJECT_DATA_BYTYPE = 9
RECV_ASSIGNED_OBJECT_ID = 12
RECV_CLIENT_DATA = 16          # Header Zeile 104, nachgezaehlt

# SIMCONNECT_SIMOBJECT_TYPE (Header Zeile 221 ff.): USER=0, ALL=1, AIRCRAFT=2,
# HELICOPTER=3, BOAT=4, GROUND=5.
TYP_BOAT = 4

# SIMCONNECT_EXCEPTION, vollstaendig am Header nachgezaehlt (Zeile 158 ff.).
#
# KORREKTUR -- hier lag die Erstfassung ab 12 daneben, und zwar so, dass ein Fehlschlag
# falsch benannt worden waere: sie hatte 12=ILLEGAL_OPERATION (ist 25), 28=OBJECT_CONTAINER
# (ist 34), 29=OBJECT_AI (ist 35), 30=OBJECT_ATC (ist 36), 31=OBJECT_SCHEDULE (ist 37).
# 0 bis 7 stimmten. Wichtigster Neuzugang fuer genau diese Messung ist die 33: ein Objekt
# zu weit vom Flugzeug weg wird abgelehnt, und das ist der wahrscheinlichste Fehlschlag,
# wenn der Flug nicht in Ostfriesland steht.
EXCEPTION_NAMEN = {
    0: "NONE",
    1: "ERROR (allgemeiner Fehler)",
    2: "SIZE_MISMATCH (Struktur passt nicht -- Aufrufproblem)",
    3: "UNRECOGNIZED_ID",
    4: "UNOPENED",
    5: "VERSION_MISMATCH",
    6: "TOO_MANY_GROUPS",
    7: "NAME_UNRECOGNIZED (der Container-Titel ist dem Sim unbekannt)",
    8: "TOO_MANY_EVENT_NAMES",
    9: "EVENT_ID_DUPLICATE",
    10: "TOO_MANY_MAPS",
    11: "TOO_MANY_OBJECTS",
    12: "TOO_MANY_REQUESTS",
    13: "WEATHER_INVALID_PORT",
    14: "WEATHER_INVALID_METAR",
    15: "WEATHER_UNABLE_TO_GET_OBSERVATION",
    16: "WEATHER_UNABLE_TO_CREATE_STATION",
    17: "WEATHER_UNABLE_TO_REMOVE_STATION",
    18: "INVALID_DATA_TYPE",
    19: "INVALID_DATA_SIZE",
    20: "DATA_ERROR",
    21: "INVALID_ARRAY",
    22: "CREATE_OBJECT_FAILED (der Sim konnte das Objekt nicht anlegen)",
    23: "LOAD_FLIGHTPLAN_FAILED",
    24: "OPERATION_INVALID_FOR_OBJECT_TYPE",
    25: "ILLEGAL_OPERATION",
    26: "ALREADY_SUBSCRIBED",
    27: "INVALID_ENUM",
    28: "DEFINITION_ERROR",
    29: "DUPLICATE_ID",
    30: "DATUM_ID",
    31: "OUT_OF_BOUNDS",
    32: "ALREADY_CREATED",
    33: "OBJECT_OUTSIDE_REALITY_BUBBLE (zu weit vom Flugzeug weg)",
    34: "OBJECT_CONTAINER (Container liess sich nicht erzeugen)",
    35: "OBJECT_AI (die KI-Engine hat abgelehnt)",
    36: "OBJECT_ATC",
    37: "OBJECT_SCHEDULE",
    38: "JETWAY_DATA",
    39: "ACTION_NOT_FOUND",
    40: "NOT_AN_ACTION",
    41: "INCORRECT_ACTION_PARAMS",
    42: "GET_INPUT_EVENT_FAILED",
    43: "SET_INPUT_EVENT_FAILED",
    44: "INTERNAL",
}

# SIMCONNECT_DATATYPE (Zeile 132 ff.) und SIMCONNECT_PERIOD (Zeile 230 ff.), nachgezaehlt.
DATATYPE_FLOAT64 = 4
PERIOD_ONCE = 1
PERIOD_SECOND = 4

DEF_LAGE = 1        # eigene Definitions-ID fuer die Lagemeldung
REQ_ERZEUGEN = 4711
REQ_LAGE = 4712
REQ_NACHPRUEFEN = 4713
REQ_EIGENE_LAGE = 4714
REQ_KONTROLLE = 4715   # Kontrollspur: die eigene Lage, waehrend das Objekt beobachtet wird

OBJEKT_USER = 0     # SIMCONNECT_OBJECT_ID_USER_AIRCRAFT, Header Zeile 26


class InitPosition(ctypes.Structure):
    """SIMCONNECT_DATA_INITPOSITION -- 6 Doubles, dann 2 DWORDs (56 Bytes).

    Am Header gegengeprueft (Zeile 759 ff.): Latitude, Longitude, Altitude (Fuss), Pitch,
    Bank, Heading als double, dann OnGround und Airspeed als DWORD. Stimmte.
    """

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


class RecvClientData(ctypes.Structure):
    """SIMCONNECT_RECV_CLIENT_DATA -- erbt von RECV_SIMOBJECT_DATA, gleiches Vorspann."""

    _fields_ = [
        ("dwSize", w.DWORD), ("dwVersion", w.DWORD), ("dwID", w.DWORD),
        ("dwRequestID", w.DWORD), ("dwObjectID", w.DWORD), ("dwDefineID", w.DWORD),
        ("dwFlags", w.DWORD), ("dwentrynumber", w.DWORD), ("dwoutof", w.DWORD),
        ("dwDefineCount", w.DWORD),
        ("werte", w.DWORD * 32),
    ]


class RecvSimObjectData(ctypes.Structure):
    """SIMCONNECT_RECV_SIMOBJECT_DATA (Header Zeile 566 ff.).

    Hinter dwDefineCount beginnen die Datenwerte. Bei drei FLOAT64 sind das drei Doubles
    unmittelbar im Anschluss -- deshalb steht hier ein Array der passenden Laenge statt
    des variablen SIMCONNECT_DATAV aus dem Header.
    """

    _fields_ = [
        ("dwSize", w.DWORD), ("dwVersion", w.DWORD), ("dwID", w.DWORD),
        ("dwRequestID", w.DWORD), ("dwObjectID", w.DWORD), ("dwDefineID", w.DWORD),
        ("dwFlags", w.DWORD), ("dwentrynumber", w.DWORD), ("dwoutof", w.DWORD),
        ("dwDefineCount", w.DWORD),
        ("werte", ctypes.c_double * 3),
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


def _paket_wurzeln() -> list[Path]:
    """Die Paketordner beider Simulatoren, aus UserCfg.opt gelesen.

    KORREKTUR: Die Erstfassung lief mit rglob ueber ganze Laufwerke. Das dauert nicht nur
    Minuten, es findet in MSFS 2024 auch NICHTS -- dort liegen die Pakete nicht als
    Ordnerbaum, sondern in "minimal.fsarchive"-Dateien (s. titel_suchen).
    """
    wurzeln: list[Path] = []
    lokal = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    for paket in ("Microsoft.Limitless_8wekyb3d8bbwe",          # MSFS 2024
                  "Microsoft.FlightSimulator_8wekyb3d8bbwe"):   # MSFS 2020
        cfg = lokal / paket / "LocalCache" / "UserCfg.opt"
        if not cfg.is_file():
            continue
        for zeile in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if zeile.strip().startswith("InstalledPackagesPath"):
                pfad = Path(zeile.split(None, 1)[1].strip().strip('"'))
                if pfad.is_dir():
                    wurzeln.append(pfad)
    return wurzeln


def titel_suchen() -> None:
    """Alle Container-Titel finden, die nach Booten aussehen.

    Zwei Quellen, weil die beiden Simulatoren ihre Pakete verschieden ablegen:

    * MSFS 2020 legt ``sim.cfg`` als Datei ab -- da steht ``title = ...`` im Klartext.
    * MSFS 2024 packt dieselben Pakete in ``content\\minimal.fsarchive``. Das Archiv ist
      NICHT verschluesselt (sein Kopf sagt woertlich ``"scheme":"none"``), die Titel stehen
      als lesbarer Text darin. Deshalb wird die Datei einfach nach ``title=`` durchsucht.
    """
    wurzeln = _paket_wurzeln()
    if not wurzeln:
        print("Keine UserCfg.opt gefunden -- laeuft hier ueberhaupt ein MSFS?")
        return

    gefunden: dict[str, str] = {}

    for wurzel in wurzeln:
        print(f"durchsuche {wurzel} ...")
        # MSFS 2020: sim.cfg als Datei
        for cfg in wurzel.rglob("SimObjects/**/sim.cfg"):
            try:
                text = cfg.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for zeile in text.splitlines():
                z = zeile.strip()
                if z.lower().startswith("title"):
                    titel = z.partition("=")[2].strip().strip('"')
                    if titel:
                        gefunden.setdefault(titel, str(cfg))

        # MSFS 2024: Klartext im Archiv
        for archiv in wurzel.rglob("*.fsarchive"):
            if "boat" not in str(archiv).lower() and "ship" not in str(archiv).lower():
                continue
            try:
                roh = archiv.read_bytes()
            except OSError:
                continue
            for stueck in roh.split(b"title"):
                kopf = stueck[:64]
                if not kopf.startswith(b"=") and not kopf.startswith(b" ="):
                    continue
                wert = kopf.partition(b"=")[2].split(b"\n")[0].split(b"\r")[0]
                titel = wert.decode("utf-8", "ignore").strip().strip('"')
                if titel and len(titel) < 60 and titel.isprintable():
                    gefunden.setdefault(titel, str(archiv))

    if not gefunden:
        print("Nichts gefunden. Dann bitte von Hand nachsehen, unter:")
        print(r"  ...\Packages\Official\...\SimObjects\Boats\<irgendwas>\sim.cfg")
        return

    boote = {t: p for t, p in gefunden.items()
             if "boat" in p.lower() or "boat" in t.lower() or "ship" in t.lower()
             or "yacht" in t.lower() or "cargo" in t.lower()}
    print(f"\n{len(gefunden)} Container-Titel gefunden, davon {len(boote)} bootartig.\n")
    for titel, pfad in sorted(boote.items()):
        print(f"  {titel}\n      {pfad}")
    if not boote:
        print("  (nichts Bootartiges -- hier die ersten 40 Titel ueberhaupt:)")
        for titel in sorted(gefunden)[:40]:
            print(f"  {titel}")


def _bindungen(sc: ctypes.WinDLL) -> None:
    """Signaturen setzen -- alle am SDK-Header (Zeile 924 ff., 954) gegengeprueft."""
    sc.SimConnect_Open.restype = ctypes.HRESULT
    sc.SimConnect_Open.argtypes = [
        ctypes.POINTER(w.HANDLE), ctypes.c_char_p, w.HWND, w.DWORD, w.HANDLE, w.DWORD,
    ]
    sc.SimConnect_AICreateSimulatedObject.restype = ctypes.HRESULT
    sc.SimConnect_AICreateSimulatedObject.argtypes = [
        w.HANDLE, ctypes.c_char_p, InitPosition, w.DWORD,
    ]
    # Die _EX1-Fassung nimmt zusaetzlich eine Livery. Sie ist die einzige, die ein
    # WASM-Modul benutzen kann -- und damit die Vergleichsgroesse, wenn sich WASM und
    # externes Programm unterschiedlich verhalten.
    sc.SimConnect_AICreateSimulatedObject_EX1.restype = ctypes.HRESULT
    sc.SimConnect_AICreateSimulatedObject_EX1.argtypes = [
        w.HANDLE, ctypes.c_char_p, ctypes.c_char_p, InitPosition, w.DWORD,
    ]
    sc.SimConnect_GetNextDispatch.restype = ctypes.HRESULT
    sc.SimConnect_GetNextDispatch.argtypes = [
        w.HANDLE, ctypes.POINTER(ctypes.POINTER(Recv)), ctypes.POINTER(w.DWORD),
    ]
    sc.SimConnect_AddToDataDefinition.restype = ctypes.HRESULT
    sc.SimConnect_AddToDataDefinition.argtypes = [
        w.HANDLE, w.DWORD, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
        ctypes.c_float, w.DWORD,
    ]
    sc.SimConnect_RequestDataOnSimObject.restype = ctypes.HRESULT
    sc.SimConnect_RequestDataOnSimObject.argtypes = [
        w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_int, w.DWORD, w.DWORD, w.DWORD,
        w.DWORD,
    ]
    # Hoehe NACHTRAEGLICH setzen -- der zweite Weg, wenn AICreateSimulatedObject die
    # Hoehe verschluckt (MSFS 2020 setzt alles auf 0,0 ft, egal was in der InitPosition
    # steht; extern wie aus WASM gemessen, 11.09.2026).
    sc.SimConnect_SetDataOnSimObject.restype = ctypes.HRESULT
    sc.SimConnect_SetDataOnSimObject.argtypes = [
        w.HANDLE, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p,
    ]
    sc.SimConnect_AIRemoveObject.restype = ctypes.HRESULT
    sc.SimConnect_AIRemoveObject.argtypes = [w.HANDLE, w.DWORD, w.DWORD]
    sc.SimConnect_Close.restype = ctypes.HRESULT
    sc.SimConnect_Close.argtypes = [w.HANDLE]


def _schliessen(sc: ctypes.WinDLL, handle) -> None:
    """Verbindung schliessen, ohne daran zu scheitern.

    Wird der Simulator waehrend eines Laufs beendet, wirft `SimConnect_Close` einen
    WinError -2147467259 ("Unbekannter Fehler") -- der Lauf endete dadurch mit einem
    Python-Stapelabzug statt mit seinem Messergebnis (11.09.2026, als MSFS 2020 mitten in
    einem 10-Minuten-Lauf geschlossen wurde). Das Schliessen ist der letzte Schritt; ob es
    gelingt, aendert am Gemessenen nichts.
    """
    try:
        sc.SimConnect_Close(handle)
    except OSError:
        print("  (Der Simulator war schon fort -- Verbindung nicht mehr zu schliessen.)")


def _verbinden(sc: ctypes.WinDLL, name: bytes) -> w.HANDLE | None:
    global _lage_definiert
    _lage_definiert = False   # Datendefinitionen gehoeren der Verbindung, nicht dem Prozess
    handle = w.HANDLE()
    try:
        sc.SimConnect_Open(ctypes.byref(handle), name, None, 0, None, 0)
    except OSError as e:
        print(f"FEHLSCHLAG: SimConnect_Open ging nicht durch ({e}).")
        print("  Laeuft der Simulator? Ist ein Flug geladen (nicht nur das Hauptmenue)?")
        return None
    return handle


_lage_definiert = False


def _lage_definition(sc: ctypes.WinDLL, handle) -> None:
    """Die Datendefinition fuer eine Lagemeldung -- GENAU EINMAL je Verbindung.

    ACHTUNG, hier lag ein eigener Messfehler (11.09.2026): Urspruenglich haben Definition
    und Anfrage in einer Funktion gesteckt, die je Objekt aufgerufen wurde. Bei EINEM Objekt
    faellt das nicht auf; beim Mengentest mit 25 Objekten hatte dieselbe Definition danach
    75 Eintraege statt 3, und die gemessene "Meldungsrate" sagte nichts ueber den Simulator
    aus, sondern nur ueber diesen Fehler. Eine Definition wird einmal angelegt und dann von
    beliebig vielen Anfragen benutzt -- das ist genau, wofuer die DefineID da ist.
    """
    global _lage_definiert
    if _lage_definiert:
        return
    for name, einheit in ((b"PLANE LATITUDE", b"degrees"),
                          (b"PLANE LONGITUDE", b"degrees"),
                          (b"PLANE ALTITUDE", b"feet")):
        sc.SimConnect_AddToDataDefinition(handle, DEF_LAGE, name, einheit,
                                          DATATYPE_FLOAT64, 0.0, 0xFFFFFFFF)
    _lage_definiert = True


def _lage_abonnieren(sc: ctypes.WinDLL, handle, objekt_id: int, req: int,
                     dauerhaft: bool) -> None:
    """Position eines Objekts anfordern.

    Das ist der Teil, der die eigentliche Frage beantwortet: eine vergebene Objekt-ID sagt
    nur, dass der Sim den Auftrag angenommen hat. Ob dort wirklich etwas STEHT und ob es
    dort BLEIBT, zeigt erst die Lagemeldung Sekunde fuer Sekunde.
    """
    _lage_definition(sc, handle)
    sc.SimConnect_RequestDataOnSimObject(
        handle, req, DEF_LAGE, objekt_id,
        PERIOD_SECOND if dauerhaft else PERIOD_ONCE, 0, 0, 0, 0,
    )


def _pakete(sc: ctypes.WinDLL, handle, sekunden: float):
    """Alle wartenden Meldungen fuer die naechsten <sekunden> ausliefern."""
    ende = time.time() + sekunden
    zeiger = ctypes.POINTER(Recv)()
    groesse = w.DWORD()
    while time.time() < ende:
        try:
            sc.SimConnect_GetNextDispatch(handle, ctypes.byref(zeiger),
                                          ctypes.byref(groesse))
        except OSError:
            # Leere Warteschlange meldet E_FAIL -- das ist keine Stoerung.
            time.sleep(0.05)
            continue
        if not zeiger:
            time.sleep(0.05)
            continue
        yield zeiger.contents.dwID, zeiger


def _abstand_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinie in Metern -- sagt beim Verschwinden, wie weit der Flieger weg war."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _eigene_lage(sc: ctypes.WinDLL, handle) -> tuple[float, float, float] | None:
    """Wo steht das Flugzeug gerade?

    Gebraucht fuer --neben-mir. Ein SimObject muss innerhalb der "reality bubble" um das
    Flugzeug entstehen, sonst kommt EXCEPTION 33 -- das ist der wahrscheinlichste
    Fehlschlag, wenn der geladene Flug nicht zufaellig am Zielort steht.
    """
    _lage_abonnieren(sc, handle, OBJEKT_USER, REQ_EIGENE_LAGE, dauerhaft=False)
    for art, zeiger in _pakete(sc, handle, 8):
        if art == RECV_SIMOBJECT_DATA:
            d = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
            if d.dwRequestID == REQ_EIGENE_LAGE:
                return d.werte[0], d.werte[1], d.werte[2]
        if art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            print(f"  Eigene Lage nicht lesbar: EXCEPTION {ex.dwException} -- "
                  f"{EXCEPTION_NAMEN.get(ex.dwException, 'unbekannt')}")
            return None
    return None


def probe(titel: str, lat: float, lon: float, hoehe: float, am_boden: bool,
          dll_pfad: Path, wartesekunden: int, halten: int, nachpruefen: bool,
          neben_mir: float | None, ex1: bool = False,
          setz_hoehe: float | None = None) -> int:
    print(f"SimConnect.dll: {dll_pfad}")
    sc = ctypes.WinDLL(str(dll_pfad))
    _bindungen(sc)

    handle = _verbinden(sc, b"FriesenKieker-Probe")
    if handle is None:
        return 2
    print("SimConnect_Open: verbunden.")

    if neben_mir is not None:
        lage = _eigene_lage(sc, handle)
        if lage is None:
            print("FEHLSCHLAG: --neben-mir braucht die eigene Position, die kam nicht.")
            _schliessen(sc, handle)
            return 2
        m_lat, m_lon, m_alt = lage
        print(f"  Flugzeug steht bei {m_lat:.5f} / {m_lon:.5f}, {m_alt:.0f} ft.")
        # Versatz nach Osten, in Grad. 1 Grad Laenge = 111320 m * cos(Breite).
        import math
        lon = m_lon + neben_mir / (111320.0 * math.cos(math.radians(m_lat)))
        lat = m_lat
        print(f"  Ziel {neben_mir:.0f} m oestlich davon: {lat:.5f} / {lon:.5f}")

    pos = InitPosition(
        Latitude=lat, Longitude=lon,
        Altitude=hoehe,
        Pitch=0.0, Bank=0.0, Heading=210.0,
        OnGround=1 if am_boden else 0,
        Airspeed=0,
    )
    print(f'AICreateSimulatedObject: titel="{titel}" bei {lat:.4f}/{lon:.4f}, '
          f'{hoehe:.0f} ft, OnGround={pos.OnGround} ...')
    try:
        if ex1:
            sc.SimConnect_AICreateSimulatedObject_EX1(handle, titel.encode("utf-8"), b"",
                                                      pos, REQ_ERZEUGEN)
        else:
            sc.SimConnect_AICreateSimulatedObject(handle, titel.encode("utf-8"), pos,
                                                  REQ_ERZEUGEN)
    except OSError as e:
        print(f"FEHLSCHLAG: Der Aufruf selbst wurde abgelehnt ({e}).")
        print("  Das hiesse: die DLL kennt die Funktion nicht -- falsche/zu alte SimConnect.dll.")
        _schliessen(sc, handle)
        return 2

    # Der Aufruf meldet fast immer Erfolg. Ob er WIRKLICH geklappt hat, kommt erst
    # nachtraeglich zurueck -- als ASSIGNED_OBJECT_ID (gut) oder EXCEPTION (schlecht).
    # Genau das ist die Falle, an der so ein Probeflug sonst als "hat funktioniert"
    # durchgeht, obwohl nichts entstanden ist.
    print(f"Warte {wartesekunden} s auf die Antwort des Simulators ...")
    objekt_id = None
    ergebnis = 3
    for art, zeiger in _pakete(sc, handle, wartesekunden):
        if art == RECV_ASSIGNED_OBJECT_ID:
            zu = ctypes.cast(zeiger, ctypes.POINTER(RecvAssignedObjectId)).contents
            objekt_id = zu.dwObjectID
            print(f"\n  ERFOLG: Objekt-ID {objekt_id} (Anfrage {zu.dwRequestID}).")
            print("  Der Simulator hat das Objekt angelegt.")
            ergebnis = 0
            break
        if art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            name = EXCEPTION_NAMEN.get(ex.dwException, "unbekannt")
            print(f"\n  ABGELEHNT: EXCEPTION {ex.dwException} -- {name}")
            if ex.dwException == 7:
                print('  Der Titel stimmt nicht. Mit "--titel-suche" die echten Namen holen.')
            if ex.dwException == 33:
                print("  Das Ziel liegt zu weit vom Flugzeug weg. Naeher heranfliegen oder")
                print("  mit --lat/--lon ein Ziel in Sichtweite waehlen.")
            ergebnis = 1
            break
        if art in (RECV_OPEN, RECV_QUIT):
            continue
        print(f"  (Nebenmeldung RECV_ID {art}, ignoriert)")
    else:
        print("\n  KEINE ANTWORT. Weder Objekt-ID noch Fehler.")
        print("  Das ist selbst ein Befund: der Aufruf verpufft folgenlos.")

    if ergebnis != 0 or objekt_id is None:
        _schliessen(sc, handle)
        return ergebnis

    # ---- Die Verbindung bleibt OFFEN, waehrend der Pilot hinsieht. ----------------
    # KORREKTUR gegenueber der Erstfassung: die schloss sofort nach dem Erfolg. SimConnect
    # raeumt beim Close die vom Client erzeugten AI-Objekte weg -- der Probeflug haette
    # also genau das weggeraeumt, was nachgesehen werden soll, und "nichts zu sehen"
    # gemeldet, ohne dass es am Simulator gelegen haette.
    print("\n" + "=" * 68)
    print(f"  JETZT HINSEHEN: per Slew nach {lat:.4f} / {lon:.4f}.")
    print(f"  Die Verbindung bleibt {halten} s offen -- solange kann das Objekt leben.")
    print("  Die Lagemeldung unten sagt, ob es noch da ist und auf welcher Hoehe.")
    print("=" * 68 + "\n")

    _lage_abonnieren(sc, handle, objekt_id, REQ_LAGE, dauerhaft=True)

    # KONTROLLSPUR -- ohne sie ist "keine Meldung mehr" mehrdeutig.
    # Am 11.09.2026 schwieg ein Kreuzfahrtschiff auf dem Bodensee ab t=+45s, und der Lauf
    # konnte nicht sagen, ob der Simulator das OBJEKT weggeraeumt hatte oder ob schlicht
    # die Verbindung tot war. Dieselbe Luecke hatte der untaugliche Chiemsee-Versuch: eine
    # Messung ohne Kontrolle misst auch das eigene Messmittel mit. Die eigene Lage laeuft
    # deshalb daneben mit -- kommt sie weiter, waehrend das Objekt schweigt, war es das
    # Objekt.
    _lage_abonnieren(sc, handle, OBJEKT_USER, REQ_KONTROLLE, dauerhaft=True)

    if setz_hoehe is not None:
        # Die Datendefinition DEF_LAGE enthaelt lat/lon/alt in genau dieser Reihenfolge --
        # sie laesst sich also auch zum SCHREIBEN benutzen.
        werte = (ctypes.c_double * 3)(lat, lon, setz_hoehe)
        hr_setz = None
        try:
            sc.SimConnect_SetDataOnSimObject(handle, DEF_LAGE, objekt_id, 0, 0,
                                             ctypes.sizeof(werte),
                                             ctypes.cast(werte, ctypes.c_void_p))
            hr_setz = "abgesetzt"
        except OSError as e:
            hr_setz = f"abgelehnt ({e})"
        print(f"  SetDataOnSimObject auf {setz_hoehe:.1f} ft: {hr_setz}")

    start = time.time()
    letzte_meldung = 0.0
    zuletzt_gesehen = None
    anzahl = 0
    kontroll_zuletzt = None
    kontroll_anzahl = 0
    entfernung_m = None
    for art, zeiger in _pakete(sc, handle, halten):
        t = time.time() - start
        if art == RECV_SIMOBJECT_DATA:
            d = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
            if d.dwRequestID == REQ_KONTROLLE:
                kontroll_anzahl += 1
                kontroll_zuletzt = t
                entfernung_m = _abstand_m(d.werte[0], d.werte[1], lat, lon)
                continue
            if d.dwRequestID != REQ_LAGE:
                continue
            anzahl += 1
            zuletzt_gesehen = t
            if t - letzte_meldung >= 10 or anzahl == 1:
                letzte_meldung = t
                weit = f"{entfernung_m / 1000:.1f} km" if entfernung_m is not None else "?"
                print(f"  t=+{t:6.1f}s  {d.werte[0]:.5f} / {d.werte[1]:.5f}  "
                      f"{d.werte[2]:7.1f} ft   (Objekt {d.dwObjectID} lebt, "
                      f"Flieger {weit} entfernt)")
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            name = EXCEPTION_NAMEN.get(ex.dwException, "unbekannt")
            print(f"  t=+{t:6.1f}s  EXCEPTION {ex.dwException} -- {name}")
        elif art == RECV_QUIT:
            print(f"  t=+{t:6.1f}s  Der Simulator wurde beendet.")
            break

    dauer = time.time() - start
    kontrolle_traegt = (kontroll_zuletzt is not None and dauer - kontroll_zuletzt <= 5)
    if kontroll_zuletzt is None:
        print("")
        print("  Kontrollspur (eigene Lage): KEINE EINZIGE Meldung.")
    else:
        print("")
        print(f"  Kontrollspur (eigene Lage): {kontroll_anzahl} Meldungen, "
              f"letzte bei t=+{kontroll_zuletzt:.1f}s.")

    if anzahl == 0:
        print("  KEINE EINZIGE LAGEMELDUNG. Die Objekt-ID gibt es, das Objekt nicht.")
        ergebnis = 4
    elif zuletzt_gesehen is not None and dauer - zuletzt_gesehen > 5:
        # Hier entscheidet die Kontrolle, was ueberhaupt gemessen wurde.
        if kontrolle_traegt:
            weit = (f", Flieger {entfernung_m / 1000:.1f} km entfernt"
                    if entfernung_m is not None else "")
            print(f"  ABGERAEUMT: das OBJEKT schwieg ab t=+{zuletzt_gesehen:.1f}s "
                  f"({dauer - zuletzt_gesehen:.0f}s Stille){weit} --")
            print("  die Kontrollspur lief die ganze Zeit weiter. Der Simulator hat es")
            print("  weggeraeumt, es lag NICHT an Verbindung oder Messmittel.")
            ergebnis = 5
        else:
            print(f"  MESSUNG UNGUELTIG: beide Spuren schwiegen ab etwa "
                  f"t=+{zuletzt_gesehen:.1f}s.")
            print("  Damit ist NICHT gezeigt, dass das Objekt verschwand -- ebenso gut")
            print("  war die Verbindung tot oder der Simulator pausiert. Wiederholen.")
            ergebnis = 6
    else:
        print(f"  DURCHGEHEND DA: {anzahl} Lagemeldungen ueber {dauer:.0f}s, "
              "bis zum Schluss.")

    _schliessen(sc, handle)
    print("  Verbindung geschlossen.")

    # ---- Ueberlebt das Objekt die Verbindung? ------------------------------------
    # Fuer den Kieker entscheidend: laeuft der Spawner spaeter kurz und geht wieder, oder
    # muss er die ganze Zeit mitlaufen? Das beantwortet nur ein zweiter Anlauf.
    if nachpruefen:
        print("\n  Nachprobe: neu verbinden und dieselbe Objekt-ID abfragen ...")
        time.sleep(3)
        handle2 = _verbinden(sc, b"FriesenKieker-Nachprobe")
        if handle2 is None:
            return ergebnis
        _lage_abonnieren(sc, handle2, objekt_id, REQ_NACHPRUEFEN, dauerhaft=False)
        antwort = False
        for art, zeiger in _pakete(sc, handle2, 8):
            if art == RECV_SIMOBJECT_DATA:
                d = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
                if d.dwRequestID != REQ_NACHPRUEFEN:
                    continue
                print(f"  UEBERLEBT: {d.werte[0]:.5f} / {d.werte[1]:.5f}  "
                      f"{d.werte[2]:.1f} ft -- das Objekt haengt NICHT an der Verbindung.")
                antwort = True
                break
            if art == RECV_EXCEPTION:
                ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
                name = EXCEPTION_NAMEN.get(ex.dwException, "unbekannt")
                print(f"  WEG: EXCEPTION {ex.dwException} -- {name}")
                print("  Das Objekt lebte nur, solange die Verbindung offen war.")
                antwort = True
                break
        if not antwort:
            print("  Keine Antwort auf die Nachfrage -- unklar.")
        _schliessen(sc, handle2)

    return ergebnis


def objekt_abfragen(dll_pfad: Path, objekt_id: int, sekunden: int) -> int:
    """Lebt das Objekt mit dieser ID -- und wo steht es?

    Gebaut am 11.09.2026 fuer einen Widerspruch: Das WASM-Modul meldete vier lebende Objekte
    mit fortlaufenden Lagemeldungen, waehrend --boote-zaehlen im selben Augenblick "kein
    einziges Boot" fand. Eines von beiden misst etwas anderes, als es zu messen glaubt.

    Die Typ-Suche (RequestDataOnSimObjectType) fragt nach Kategorie und Radius; diese hier
    fragt eine ID. Antwortet sie, existiert das Objekt fuer diesen Client -- dann ist die
    Typ-Suche der blinde Fleck. Antwortet sie mit EXCEPTION 3, existiert es fuer ihn nicht,
    und die Frage wird zu: Sieht der Pilot es trotzdem?
    """
    print(f"SimConnect.dll: {dll_pfad}")
    sc = ctypes.WinDLL(str(dll_pfad))
    _bindungen(sc)
    handle = _verbinden(sc, b"FriesenKieker-Objektfrage")
    if handle is None:
        return 2
    print("SimConnect_Open: verbunden.")

    eigene = _eigene_lage(sc, handle)
    print(f"\nFrage Objekt {objekt_id} ueber {sekunden}s ab ...\n")
    _lage_abonnieren(sc, handle, objekt_id, REQ_LAGE, dauerhaft=True)

    start = time.time()
    anzahl = 0
    for art, zeiger in _pakete(sc, handle, sekunden):
        t = time.time() - start
        if art == RECV_SIMOBJECT_DATA:
            d = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
            if d.dwRequestID != REQ_LAGE:
                continue
            anzahl += 1
            if anzahl <= 3 or anzahl % 10 == 0:
                weit = ""
                if eigene is not None:
                    m = _abstand_m(eigene[0], eigene[1], d.werte[0], d.werte[1])
                    weit = f"   {m:7.0f} m vom Flugzeug"
                print(f"  t=+{t:5.1f}s  {d.werte[0]:.5f} / {d.werte[1]:.5f}  "
                      f"{d.werte[2]:7.1f} ft{weit}")
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            name = EXCEPTION_NAMEN.get(ex.dwException, "unbekannt")
            print(f"  EXCEPTION {ex.dwException} -- {name}")
            if ex.dwException == 3:
                print("  Das Objekt existiert fuer DIESEN Client nicht.")
                _schliessen(sc, handle)
                return 1

    _schliessen(sc, handle)
    if anzahl == 0:
        print("  Keine Antwort und keine Exception -- unklar.")
        return 1
    print(f"\n  LEBT: {anzahl} Lagemeldungen. Das Objekt existiert auch fuer einen")
    print("  zweiten Client -- die Typ-Suche hat es nur nicht gefunden.")
    return 0


def status_lesen(dll_pfad: Path, sekunden: int) -> int:
    """Den Statusbereich auslesen, den das WASM-Modul beschreibt.

    Der dritte Rueckkanal, und der einzige, der in BEIDEN Simulatoren funktioniert:
    `fprintf` landet in MSFS 2020 nicht in der Konsole, und `fsNetworkHttpRequestGet`
    erreichte kein 127.0.0.1. ClientData ist ein gemeinsamer Speicherbereich zwischen
    Modul und externem Programm -- SPAD.neXt macht es auf demselben Rechner genauso.

    Kommt hier nichts an, ist das selbst aussagekraeftig: Dann hat das Modul nicht einmal
    SimConnect geoeffnet.
    """
    SCHRITTE = {
        0: "(noch nichts geschrieben)",
        1: "START",
        2: "SimConnect offen, ClientData eingerichtet",
        3: "Datendefinition angelegt",
        4: "System-Event abonniert",
        5: "Dispatch gesetzt",
        6: "Sim laeuft -- Event empfangen",
        7: "AICreateSimulatedObject gerufen",
        8: "*** OBJEKT ANGELEGT ***",
        9: "vom Simulator ABGELEHNT",
    }
    print(f"SimConnect.dll: {dll_pfad}")
    sc = ctypes.WinDLL(str(dll_pfad))
    _bindungen(sc)
    for name, argtypes in (
        ("SimConnect_MapClientDataNameToID", [w.HANDLE, ctypes.c_char_p, w.DWORD]),
        ("SimConnect_AddToClientDataDefinition",
         [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_float, w.DWORD]),
        ("SimConnect_RequestClientData",
         [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_int, w.DWORD, w.DWORD, w.DWORD,
          w.DWORD]),
    ):
        f = getattr(sc, name)
        f.restype = ctypes.HRESULT
        f.argtypes = argtypes

    handle = _verbinden(sc, b"FriesenKieker-Status")
    if handle is None:
        return 2
    print("SimConnect_Open: verbunden.")

    CD_ID, CD_DEF, WORTE = 1, 1, 32
    sc.SimConnect_MapClientDataNameToID(handle, b"FriesenBruegge.Status", CD_ID)
    sc.SimConnect_AddToClientDataDefinition(handle, CD_DEF, 0, WORTE * 4, 0.0, 0xFFFFFFFF)
    # PERIOD 2 = SIMCONNECT_CLIENT_DATA_PERIOD_ON_SET: melden, sobald das Modul schreibt.
    sc.SimConnect_RequestClientData(handle, CD_ID, REQ_LAGE + 800, CD_DEF, 2, 0, 0, 0, 0)

    print(f"Lausche {sekunden}s auf den Statusbereich des Moduls ...")
    print()
    gesehen = False
    for art, zeiger in _pakete(sc, handle, sekunden):
        if art == RECV_CLIENT_DATA:
            roh = ctypes.cast(zeiger, ctypes.POINTER(RecvClientData)).contents
            s, wert2, wert3 = roh.werte[0], roh.werte[1], roh.werte[2]
            zeile = f"  Schritt {s}: {SCHRITTE.get(s, 'unbekannt')}"
            if wert2:
                zeile += f"   Fehler/HR: {wert2}"
            if wert3:
                zeile += f"   Objekt-ID: {wert3}"
            print(zeile)

            # Die Messpunkte der Lage-Frage (Felder 3..8, s. modul.cpp). Sie beantworten,
            # ob ein WASM-Modul seine eigene Position lesen kann -- und daran haengt der
            # Auslieferungsweg: ein Modul, das seine Lage nicht liest, kann sie weder
            # melden noch pruefen, ob ein gesetztes Objekt noch steht.
            datadef, request = roh.werte[3], roh.werte[4]
            lagen, lat_e5, lon_e5, sek = (roh.werte[5], roh.werte[6],
                                          roh.werte[7], roh.werte[8])
            if datadef or request or lagen or sek:
                def _hr(v):
                    # HRESULT kommt als DWORD an; 0 ist S_OK, alles andere ist ein Fehler.
                    return "S_OK" if v == 0 else f"0x{v:08X}"

                def _grad(v):
                    # Als DWORD gelesen, gemeint war ein Vorzeichenwert.
                    g = v - 0x100000000 if v > 0x7FFFFFFF else v
                    return g / 100000.0

                print(f"      AddToDataDefinition: {_hr(datadef)}"
                      f"    RequestDataOnSimObject: {_hr(request)}")
                if lagen:
                    print(f"      *** LAGE GELESEN: {lagen} Meldungen, zuletzt "
                          f"{_grad(lat_e5):.5f} / {_grad(lon_e5):.5f} ***")
                elif sek >= 2:
                    print(f"      Noch keine Lagemeldung nach {sek} Sekunden.")

            # Leben die vom Modul gesetzten Objekte noch? Der Abstand zwischen der
            # letzten Meldesekunde einer Variante und der laufenden Sekunde ist die
            # Antwort -- nicht die vergebene Objekt-ID, die nur den angenommenen
            # Auftrag bestaetigt.
            #
            # Die vier Varianten unterscheiden sich in OnGround/Altitude:
            #   0: OnGround=1, Alt=0     1: OnGround=0, Alt=0
            #   2: OnGround=0, Alt=500   3: OnGround=1, Alt=500
            gesetzt_sek = roh.werte[11]
            if gesetzt_sek:
                zeilen = []
                for i, wie in enumerate(("OnGround=1 Alt=0  ", "OnGround=0 Alt=0  ",
                                         "OnGround=0 Alt=500", "OnGround=1 Alt=500")):
                    zuletzt = roh.werte[12 + i]
                    hoehe = roh.werte[16 + i]
                    if not zuletzt:
                        zeilen.append(f"        Variante {i} ({wie}): NIE gemeldet")
                        continue
                    stille = sek - zuletzt
                    h = (hoehe - 0x100000000 if hoehe > 0x7FFFFFFF else hoehe) / 10.0
                    zustand = ("lebt" if stille <= 3
                               else f"WEG seit {stille}s (lebte {zuletzt - gesetzt_sek}s)")
                    zeilen.append(f"        Variante {i} ({wie}): {h:7.1f} ft  {zustand}")
                # Womit gesetzt wurde -- NICHT die zuletzt gelesene Lage. Der
                # Unterschied hat am 11.09.2026 eine Stunde gekostet: vier Boote
                # standen im Indischen Ozean, waehrend der Statusbereich die korrekte
                # letzte Lage zeigte.
                setz_lat, setz_lon = roh.werte[22], roh.werte[23]
                verworfen = roh.werte[20]
                wo = ""
                if setz_lat or setz_lon:
                    wo = f" bei {_grad(setz_lat):.5f} / {_grad(setz_lon):.5f}"
                signale, seit = roh.werte[24], roh.werte[25]
                if signale:
                    print(f"      SimStart/FlightLoaded: {signale}x, zuletzt vor {seit}s.")
                else:
                    print("      KEIN SimStart/FlightLoaded empfangen.")
                if verworfen:
                    print(f"      {verworfen} Lagemeldung(en) verworfen "
                          "(Sprung oder Nullpunkt).")
                print(f"      Gesetzt in Sekunde {gesetzt_sek}{wo}, jetzt Sekunde {sek}:")
                for z in zeilen:
                    print(z)
            gesehen = True
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            print(f"  EXCEPTION {ex.dwException} -- "
                  f"{EXCEPTION_NAMEN.get(ex.dwException, 'unbekannt')}")
    if not gesehen:
        print("  NICHTS. Das Modul hat den Bereich nie beschrieben --")
        print("  es hat also nicht einmal SimConnect geoeffnet.")
    _schliessen(sc, handle)
    return 0 if gesehen else 1


def boote_zaehlen(dll_pfad: Path, radius_m: int) -> int:
    """Welche Boote stehen im Umkreis? -- unabhaengig davon, WER sie gesetzt hat.

    Gebaut, um eine Sichtpruefung zu ersetzen, die nichts taugt: Ein `Boat01` ist rund acht
    Meter lang, und "ich sehe keins" heisst auf 200 m Entfernung wenig (11.09.2026 in
    MSFS 2020 zweimal erlebt -- das Boot war da, gesehen wurde es erst als
    Kreuzfahrtschiff). Der Simulator weiss es besser als das Auge.

    Dient hier der Frage, ob das WASM-Modul ein Objekt gesetzt hat: Findet ein ZWEITER
    Client das Boot, dann laeuft das Modul, und es fehlt ihm nur der Netzzugang.
    """
    print(f"SimConnect.dll: {dll_pfad}")
    sc = ctypes.WinDLL(str(dll_pfad))
    _bindungen(sc)
    sc.SimConnect_RequestDataOnSimObjectType.restype = ctypes.HRESULT
    sc.SimConnect_RequestDataOnSimObjectType.argtypes = [
        w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_int,
    ]

    handle = _verbinden(sc, b"FriesenKieker-Zaehlung")
    if handle is None:
        return 2
    print("SimConnect_Open: verbunden.")

    lage = _eigene_lage(sc, handle)
    if lage is None:
        _schliessen(sc, handle)
        return 2
    m_lat, m_lon, m_alt = lage
    # Die Hoehe des Flugzeugs ist der beste verfuegbare Anhalt fuer die Gelaendehoehe --
    # es steht ja darauf. Gebraucht, um zu beurteilen, ob ein Objekt auf 0 ft (Meereshoehe)
    # sichtbar waere oder im Boden steckt.
    print(f"  Flugzeug steht bei {m_lat:.5f} / {m_lon:.5f}, {m_alt:.1f} ft")

    print(f"\nFrage alle Boote im Umkreis von {radius_m} m ab ...")
    sc.SimConnect_RequestDataOnSimObjectType(handle, REQ_LAGE + 900, DEF_LAGE,
                                             radius_m, TYP_BOAT)

    import math
    gefunden = []
    for art, zeiger in _pakete(sc, handle, 12):
        if art == RECV_SIMOBJECT_DATA_BYTYPE:
            d = ctypes.cast(zeiger, ctypes.POINTER(RecvSimObjectData)).contents
            if d.dwRequestID != REQ_LAGE + 900:
                continue
            # Ein leeres Ergebnis kommt trotzdem als Paket -- mit dwoutof = 0 und einer
            # Objekt-ID 0 bei 0/0. Ohne diese Pruefung meldet die Zaehlung "1 Boot
            # gefunden, 6010 km entfernt", was Unsinn ist.
            if d.dwoutof == 0 or d.dwObjectID == 0:
                break
            lat, lon, alt = d.werte[0], d.werte[1], d.werte[2]
            # grobe Entfernung, reicht zum Einordnen
            dx = (lon - m_lon) * 111320.0 * math.cos(math.radians(m_lat))
            dy = (lat - m_lat) * 111320.0
            gefunden.append((math.hypot(dx, dy), lat, lon, alt, d.dwObjectID))
            if d.dwentrynumber >= d.dwoutof:
                break
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            print(f"  EXCEPTION {ex.dwException} -- "
                  f"{EXCEPTION_NAMEN.get(ex.dwException, 'unbekannt')}")
            break

    if not gefunden:
        print("\n  KEIN EINZIGES BOOT im Umkreis.")
    else:
        print(f"\n  {len(gefunden)} Boot(e) gefunden:\n")
        for entf, lat, lon, alt, oid in sorted(gefunden):
            print(f"    {entf:8.0f} m   {lat:.5f} / {lon:.5f}   {alt:7.1f} ft   "
                  f"Objekt {oid}")
    _schliessen(sc, handle)
    return 0 if gefunden else 1


def mengentest(titel: str, anzahl: int, raster_m: float, dll_pfad: Path, halten: int,
               neben_mir: float | None, lat: float, lon: float) -> int:
    """Wie viele Objekte vertraegt der Simulator? (Spec 13.4, Frage 3)

    Zwei Messgroessen, und die zweite ist die ehrlichere:

    * **Nimmt der Sim sie an?** EXCEPTION 11 waere TOO_MANY_OBJECTS -- eine harte Grenze.
    * **Bleibt er gesund?** Jedes Objekt meldet seine Lage im Sekundentakt. Erwartet werden
      also <anzahl> Meldungen je Sekunde. Bricht die Rate ein, hat der Simulator zu tun --
      das ist ein Indikator, kein Bildratenmesser. Ob es *ruckelt*, sagt am Ende der Pilot;
      eine Bildrate gibt SimConnect nicht her.
    """
    import math

    print(f"SimConnect.dll: {dll_pfad}")
    sc = ctypes.WinDLL(str(dll_pfad))
    _bindungen(sc)
    handle = _verbinden(sc, b"FriesenKieker-Menge")
    if handle is None:
        return 2
    print("SimConnect_Open: verbunden.")

    if neben_mir is not None:
        lage = _eigene_lage(sc, handle)
        if lage is None:
            _schliessen(sc, handle)
            return 2
        lat, lon, _ = lage
        print(f"  Flugzeug steht bei {lat:.5f} / {lon:.5f}")

    # Quadratisches Raster um den Zielpunkt. Ein Gitter statt eines Haufens, damit die
    # Objekte nicht ineinanderstecken und der Pilot sie zaehlen kann.
    kante = max(1, int(math.ceil(math.sqrt(anzahl))))
    grad_lat = raster_m / 111320.0
    grad_lon = raster_m / (111320.0 * math.cos(math.radians(lat)))
    print(f"\n{anzahl}x \"{titel}\" im {kante}x{kante}-Raster, {raster_m:.0f} m Abstand ...")

    ids: list[int] = []
    fehler: dict[int, int] = {}
    begonnen = time.time()
    for i in range(anzahl):
        z, s = divmod(i, kante)
        pos = InitPosition(
            Latitude=lat + (z - kante / 2) * grad_lat,
            Longitude=lon + (s - kante / 2) * grad_lon,
            Altitude=0.0, Pitch=0.0, Bank=0.0, Heading=210.0,
            OnGround=1, Airspeed=0,
        )
        try:
            sc.SimConnect_AICreateSimulatedObject(handle, titel.encode("utf-8"), pos,
                                                  REQ_ERZEUGEN + i)
        except OSError as e:
            print(f"  Aufruf {i} abgelehnt: {e}")
            break

    # Erst ALLE Auftraege absetzen, dann die Antworten holen. Vorher stand hier eine Pause
    # von 80 ms je Objekt -- die floss in die gemessene "Zeit je Aufruf" ein und machte den
    # Simulator langsamer, als er ist.
    absetzen = time.time() - begonnen
    print(f"  {anzahl} Auftraege abgesetzt in {absetzen:.2f}s "
          f"({absetzen / max(1, anzahl) * 1000:.1f} ms je Aufruf).")

    for art, zeiger in _pakete(sc, handle, 15):
        if art == RECV_ASSIGNED_OBJECT_ID:
            zu = ctypes.cast(zeiger, ctypes.POINTER(RecvAssignedObjectId)).contents
            ids.append(zu.dwObjectID)
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            fehler[ex.dwException] = fehler.get(ex.dwException, 0) + 1

    dauer = time.time() - begonnen
    print(f"  {len(ids)} von {anzahl} angelegt, Antworten vollstaendig nach {dauer:.1f}s.")
    for nr, wie_oft in sorted(fehler.items()):
        print(f"  {wie_oft}x EXCEPTION {nr} -- {EXCEPTION_NAMEN.get(nr, 'unbekannt')}")
        if nr == 11:
            print("     Das ist die harte Grenze: der Simulator nimmt keine weiteren an.")
    if not ids:
        _schliessen(sc, handle)
        return 1

    print(f"\nLage aller {len(ids)} Objekte abonnieren; erwartet werden {len(ids)} Meldungen/s.")
    for i, oid in enumerate(ids):
        _lage_abonnieren(sc, handle, oid, REQ_LAGE + i, dauerhaft=True)

    print(f"Verbindung bleibt {halten}s offen -- JETZT HINSEHEN und auf Ruckeln achten.\n")
    start = time.time()
    letzte = 0.0
    zaehler = 0
    gesamt = 0
    for art, zeiger in _pakete(sc, handle, halten):
        if art == RECV_SIMOBJECT_DATA:
            zaehler += 1
            gesamt += 1
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            fehler[ex.dwException] = fehler.get(ex.dwException, 0) + 1
        t = time.time() - start
        if t - letzte >= 10:
            anteil = zaehler / (t - letzte) / len(ids) * 100
            print(f"  t=+{t:5.0f}s  {zaehler / (t - letzte):6.1f} Meldungen/s "
                  f"= {anteil:5.1f}% der erwarteten Rate")
            letzte, zaehler = t, 0

    print(f"\n  {gesamt} Lagemeldungen insgesamt ueber {time.time() - start:.0f}s.")
    _schliessen(sc, handle)
    print("  Verbindung geschlossen -- die Objekte verschwinden damit.")
    return 0


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Dieses Skript gehoert auf den Windows-Rechner mit dem Simulator.")
        return 2
    ap = argparse.ArgumentParser(description="FriesenKieker: SimObject-Probeflug")
    ap.add_argument("--titel", help='Container-Titel, z. B. "Boat01"')
    ap.add_argument("--titel-suche", action="store_true",
                    help="Nur nachsehen, welche Container der Sim kennt")
    ap.add_argument("--lat", type=float, default=STANDARD_LAT)
    ap.add_argument("--lon", type=float, default=STANDARD_LON)
    ap.add_argument("--hoehe", type=float, default=0.0, help="Fuss ueber MSL")
    ap.add_argument("--frei", action="store_true",
                    help="OnGround=0 statt 1 (dann zaehlt --hoehe wirklich)")
    ap.add_argument("--dll", help="Pfad zu SimConnect.dll")
    ap.add_argument("--warten", type=int, default=10, help="Sekunden auf die Antwort")
    ap.add_argument("--halten", type=int, default=180,
                    help="Sekunden, die die Verbindung offen bleibt (zum Hinsehen)")
    ap.add_argument("--ohne-nachprobe", action="store_true",
                    help="Nicht pruefen, ob das Objekt das Schliessen ueberlebt")
    ap.add_argument("--neben-mir", type=float, metavar="METER",
                    help="Ziel nicht aus --lat/--lon, sondern <METER> oestlich des "
                         "Flugzeugs (schliesst EXCEPTION 33 aus)")
    ap.add_argument("--setz-hoehe", type=float, metavar="FUSS",
                    help="Hoehe NACH dem Anlegen per SetDataOnSimObject setzen")
    ap.add_argument("--ex1", action="store_true",
                    help="AICreateSimulatedObject_EX1 statt der alten Fassung benutzen")
    ap.add_argument("--objekt-id", type=int, metavar="ID",
                    help="Eine bekannte Objekt-ID direkt abfragen (statt per Typ zu suchen)")
    ap.add_argument("--status", action="store_true",
                    help="Statusbereich des WASM-Moduls auslesen (ClientData)")
    ap.add_argument("--status-sekunden", type=int, default=20)
    ap.add_argument("--boote-zaehlen", action="store_true",
                    help="Nur nachsehen, welche Boote im Umkreis stehen (egal von wem)")
    ap.add_argument("--radius", type=int, default=20000, metavar="METER",
                    help="Umkreis fuer --boote-zaehlen (Vorgabe 20000 m)")
    ap.add_argument("--anzahl", type=int, metavar="N",
                    help="Mengentest: N Objekte im Raster setzen (Spec 13.4, Frage 3)")
    ap.add_argument("--raster", type=float, default=150.0, metavar="METER",
                    help="Abstand der Objekte im Mengentest (Vorgabe 150 m)")
    a = ap.parse_args()

    if a.titel_suche:
        titel_suchen()
        return 0
    if a.objekt_id:
        return objekt_abfragen(dll_finden(a.dll), a.objekt_id, a.status_sekunden)
    if a.status:
        return status_lesen(dll_finden(a.dll), a.status_sekunden)
    if a.boote_zaehlen:
        return boote_zaehlen(dll_finden(a.dll), a.radius)
    if not a.titel:
        ap.error('entweder --titel "..." oder --titel-suche')
    if a.anzahl:
        return mengentest(a.titel, a.anzahl, a.raster, dll_finden(a.dll), a.halten,
                          a.neben_mir, a.lat, a.lon)
    return probe(a.titel, a.lat, a.lon, a.hoehe, not a.frei, dll_finden(a.dll),
                 a.warten, a.halten, not a.ohne_nachprobe, a.neben_mir, a.ex1, a.setz_hoehe)


if __name__ == "__main__":
    raise SystemExit(main())
