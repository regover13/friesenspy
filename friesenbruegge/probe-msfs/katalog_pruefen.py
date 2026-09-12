# -*- coding: utf-8 -*-
"""Geht den Objektkatalog im laufenden Simulator durch und trägt ein, was wirklich geht.

    python katalog_pruefen.py --passwort GEHEIM
    python katalog_pruefen.py --passwort GEHEIM --anzahl 200 --gruppe 25
    python katalog_pruefen.py --passwort GEHEIM --trocken     # ohne Server, nur zeigen

**Läuft unbeaufsichtigt.** Es holt sich die ungeprüften Titel vom Server, setzt sie in
Gruppen, liest die Antwort des Simulators und meldet das Ergebnis zurück. Bei rund 1400
Titeln dauert das etwa eine Dreiviertelstunde — deshalb ist nichts daran zum Hinsehen
gedacht; dafür gibt es `titel_schau.py`.

## Warum das überhaupt sein muss

Von 45 Tiertiteln des MSFS-2020-Bestands funktionieren in MSFS 2024 nur sieben (12.09.2026
gemessen). Welche das sind, verrät weder der Dateiname noch die SDK-Doku noch eine
Community-Seite — **nur der Versuch.** Und ein Versuch, der nicht festgehalten wird, ist beim
nächsten Mal wieder fällig.

## Wie es misst

`SimConnect_AICreateSimulatedObject` meldet fast immer Erfolg zurück. Ob wirklich etwas
entstand, kommt **asynchron** als `ASSIGNED_OBJECT_ID` (gut) oder `EXCEPTION` (schlecht).
Genau daran geht eine naive Prüfung vorbei — sie hielte alles für gelungen.

Zugeordnet wird über die **Anfrage-Nummer**: je Titel eine eigene, und die Exception nennt in
`dwSendID` das auslösende Paket. Ohne diese Zuordnung landet die Ausnahme eines Titels beim
falschen — derselbe Fehler steckte bis zum 12.09.2026 in `bruegge.cpp` und ließ einen
sichtbar dastehenden Bären als „fehlgeschlagen" gelten.

⚠ **Die Objekte werden weit weg gesetzt** (`--entfernung`, Vorgabe 3 km) und die Verbindung
nach jeder Gruppe geschlossen — das räumt sie weg (gemessen 11.09.2026). Sonst stünden nach
einem Durchlauf tausend Objekte um den Piloten herum.
"""

from __future__ import annotations

import argparse
import ctypes
import http.cookiejar
import json
import math
import sys
import time
import urllib.error
import urllib.request

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

REQ_BASIS = 7000


def anmelden(server: str, passwort: str):
    """Erst anmelden, dann arbeiten.

    ⚠ Das Passwort als Cookie zu schicken reicht NICHT: `require_admin` prueft ein SIGNIERTES
    Token, nicht das Passwort (12.09.2026: `401 Admin-Login erforderlich`). Der Login-Endpunkt
    setzt das Token als httponly-Cookie, ein `CookieJar` nimmt es entgegen.
    """
    jar = http.cookiejar.CookieJar()
    oeffner = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        server.rstrip("/") + "/api/admin/login",
        data=json.dumps({"password": passwort}).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"})
    with oeffner.open(req, timeout=30) as r:
        r.read()
    return oeffner


def _holen(oeffner, server: str, anzahl: int) -> list[dict]:
    url = (server.rstrip("/")
           + f"/api/admin/bruegge/katalog?simulator=msfs2024&offen=true&grenze={anzahl}")
    with oeffner.open(urllib.request.Request(url), timeout=60) as r:
        return json.load(r).get("eintraege", [])


def _melden(oeffner, server: str, ergebnisse: list[dict]) -> int:
    rumpf = json.dumps({"ergebnisse": ergebnisse}).encode("utf-8")
    req = urllib.request.Request(server.rstrip("/") + "/api/admin/bruegge/katalog/ergebnis",
                                 data=rumpf, method="POST",
                                 headers={"Content-Type": "application/json"})
    with oeffner.open(req, timeout=60) as r:
        return json.load(r).get("vermerkt", 0)


def _gruppe_setzen(sc, handle, lat, lon, titel: list[str], entfernung_m: float,
                   warten_s: float) -> dict[int, dict]:
    """Eine Gruppe setzen und die Antworten einsammeln. Schlüssel ist der Listenindex."""
    # Alle Aufträge zuerst raus, dann die Antworten lesen: Sie kommen ohnehin asynchron, und
    # je Titel zu warten dauerte bei 1400 Titeln Stunden statt Minuten.
    sende_zu_index: dict[int, int] = {}
    for i, t in enumerate(titel):
        # Im Kreis um den Piloten, damit sich die Objekte nicht gegenseitig überlagern --
        # überlappende Modelle können der Grund für ein CREATE_OBJECT_FAILED sein, und das
        # wäre ein Messfehler, kein Befund über den Titel.
        w = 2 * math.pi * i / max(1, len(titel))
        zlat = lat + (entfernung_m * math.cos(w)) / 111320.0
        zlon = lon + (entfernung_m * math.sin(w)) / (111320.0 * math.cos(math.radians(lat)))
        pos = InitPosition()
        pos.Latitude, pos.Longitude = zlat, zlon
        pos.Altitude = 0.0
        pos.Pitch = pos.Bank = pos.Heading = 0.0
        pos.OnGround = 1
        pos.Airspeed = 0
        try:
            sc.SimConnect_AICreateSimulatedObject(handle, t.encode("utf-8"), pos, REQ_BASIS + i)
        except OSError:
            continue
        # Die Paketnummer merken -- nur damit lässt sich eine Exception dem Titel zuordnen.
        sende = ctypes.c_ulong(0)
        try:
            if sc.SimConnect_GetLastSentPacketID(handle, ctypes.byref(sende)) == 0:
                sende_zu_index[sende.value] = i
        except OSError:
            pass

    raus: dict[int, dict] = {}
    for art, zeiger in _pakete(sc, handle, warten_s):
        if art == RECV_ASSIGNED_OBJECT_ID:
            z = ctypes.cast(zeiger, ctypes.POINTER(RecvAssignedObjectId)).contents
            i = z.dwRequestID - REQ_BASIS
            if 0 <= i < len(titel):
                raus[i] = {"ergebnis": "steht"}
        elif art == RECV_EXCEPTION:
            ex = ctypes.cast(zeiger, ctypes.POINTER(RecvException)).contents
            i = sende_zu_index.get(ex.dwSendID)
            if i is not None:
                raus[i] = {"ergebnis": "fehlgeschlagen",
                           "fehler": "EXCEPTION_%d — %s" % (
                               ex.dwException,
                               EXCEPTION_NAMEN.get(ex.dwException, "unbekannt"))}
    return raus


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--passwort", required=True, help="ADMIN_PASSWORD")
    ap.add_argument("--server", default="https://friesenspy.devprops.de")
    ap.add_argument("--anzahl", type=int, default=1500, help="wie viele Titel insgesamt")
    ap.add_argument("--gruppe", type=int, default=25, help="Titel je Durchgang")
    ap.add_argument("--warten", type=float, default=5.0, help="Sekunden je Gruppe")
    ap.add_argument("--entfernung", type=float, default=3000.0, metavar="METER",
                    help="wie weit vom Flugzeug gesetzt wird (Vorgabe 3000)")
    ap.add_argument("--trocken", action="store_true", help="nichts an den Server melden")
    ap.add_argument("--dll", help="Pfad zu SimConnect.dll")
    a = ap.parse_args()

    try:
        oeffner = anmelden(a.server, a.passwort)
    except urllib.error.HTTPError as e:
        print(f"Anmeldung fehlgeschlagen: HTTP {e.code} — {e.read()[:200]!r}")
        return 1
    offen = _holen(oeffner, a.server, a.anzahl)
    if not offen:
        print("Nichts Offenes im Katalog — alles geprüft oder noch nichts eingetragen.")
        return 0
    print(f"{len(offen)} ungeprüfte Titel, in Gruppen zu {a.gruppe}\n")

    dll = dll_finden(a.dll)
    geht = geht_nicht = stumm = 0
    begonnen = time.time()

    for start in range(0, len(offen), a.gruppe):
        teil = offen[start:start + a.gruppe]
        titel = [e["titel"] for e in teil]

        # JE GRUPPE eine eigene Verbindung: Beim Schließen räumt SimConnect die Objekte weg
        # (gemessen 11.09.2026). Sonst stünden nach 1400 Titeln tausend Objekte herum, und
        # spätere Gruppen scheiterten an der Menge statt am Titel.
        sc = ctypes.WinDLL(str(dll))
        _bindungen(sc)
        handle = _verbinden(sc, b"FriesenBruegge-KatalogPruefung")
        if handle is None:
            print("Keine Verbindung zum Simulator. Läuft er?")
            return 2
        lage = _eigene_lage(sc, handle)
        if lage is None:
            _schliessen(sc, handle)
            print("Eigene Position nicht lesbar — steht ein Flug?")
            return 2
        lat, lon, _ = lage

        antwort = _gruppe_setzen(sc, handle, lat, lon, titel, a.entfernung, a.warten)
        _schliessen(sc, handle)

        ergebnisse = []
        for i, e in enumerate(teil):
            r = antwort.get(i)
            if r is None:
                # Weder Objekt-ID noch Ausnahme. Das ist selbst ein Befund -- aber ein
                # schwacher: Vielleicht ging die Antwort in der Menge unter. Deshalb NICHT
                # als "fehlgeschlagen" vermerken, sondern offen lassen; ein zweiter Lauf
                # nimmt den Titel dann erneut.
                stumm += 1
                continue
            ergebnisse.append({"simulator": e["simulator"], "titel": e["titel"], **r})
            if r["ergebnis"] == "steht":
                geht += 1
            else:
                geht_nicht += 1

        if ergebnisse and not a.trocken:
            try:
                _melden(oeffner, a.server, ergebnisse)
            except urllib.error.URLError as ex:
                print(f"  Melden ging nicht: {ex} — Lauf geht weiter, Ergebnis ist verloren.")

        fertig = start + len(teil)
        rest = (time.time() - begonnen) / max(1, fertig) * (len(offen) - fertig)
        print(f"  {fertig:5d}/{len(offen)}   {geht:5d} gehen   {geht_nicht:5d} nicht   "
              f"{stumm:4d} stumm   noch rund {rest/60:.0f} min")

    print(f"\nFertig: {geht} gehen, {geht_nicht} nicht, {stumm} ohne Antwort.")
    if stumm:
        print("Die stummen bleiben ungeprüft — einfach noch einmal laufen lassen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
