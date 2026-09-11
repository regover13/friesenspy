"""Nimmt entgegen, was die Proben im Simulator melden -- MSFS wie X-Plane.

Beide rufen http://127.0.0.1:8099/... auf, ein Schritt je Zeile:

* Das **WASM-Modul** (probe-msfs/wasm) meldet auf /wasm. Dass ueberhaupt etwas ankommt, ist
  dort schon die halbe Antwort: es beweist, dass ein WASM-Modul ins Netz darf. Kommt nichts,
  ist auch das ein Befund -- dann haelt MSFS_Network.h nicht, was der Header verspricht.
* Das **X-Plane-Plugin** (probe-xplane) meldet auf /xplane. Dort ist Netzzugriff keine
  offene Frage: ein Plugin ist ein normaler Prozess im Simulator.

Ein Horcher fuer beide, damit die Ausgaben vergleichbar nebeneinander stehen.

    py horcher.py
"""
from __future__ import annotations

import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DEUTUNG = {
    "module_init": "Das Modul wurde vom Simulator geladen und gestartet",
    "open_hr": "Rueckgabe von SimConnect_Open (0 = S_OK)",
    "open_bestaetigt": "Der Simulator hat die Verbindung bestaetigt (RECV_ID_OPEN)",
    "subscribe_hr": "Rueckgabe von SubscribeToSystemEvent",
    "calldispatch_hr": "Rueckgabe von CallDispatch",
    "fordere_lage_an": "Sim laeuft, Position des Flugzeugs angefordert",
    "lage_lat_e5": "Breite des Flugzeugs, mal 100000",
    "lage_lon_e5": "Laenge des Flugzeugs, mal 100000",
    "create_aufgerufen": "AICreateSimulatedObject aufgerufen (0 = S_OK)",
    "ERFOLG_objekt_id": "*** WASM KANN OBJEKTE SETZEN *** -- Objekt-ID",
    "exception": "Der Simulator hat abgelehnt -- Exception-Nummer",
    "module_deinit": "Das Modul wurde entladen",
    # --- X-Plane ---------------------------------------------------------
    "XPluginStart": "Das Plugin wurde von X-Plane geladen",
    "XPluginEnable": "Das Plugin wurde freigeschaltet",
    "datarefs": "Wurden die Positions-Datarefs gefunden?",
    "flugzeug_lat": "Breite des Flugzeugs",
    "flugzeug_lon": "Laenge des Flugzeugs",
    "pfad_fehlgeschlagen": "Dieses .obj gibt es nicht -- naechster Kandidat",
    "objekt_geladen": "*** DER PFAD TRAEGT *** -- dieses .obj hat geladen",
    "gelaende_y": "Gelaendehoehe an der Zielstelle (lokale Meter)",
    "probe_ergebnis": "Die Terrain-Probe hat NICHT getroffen",
    "instanz_erzeugt": "XPLMCreateInstance lieferte eine Instanz",
    "position_gesetzt": "Instanz an die Zielkoordinate gesetzt",
    "ERFOLG_autoshift_an": "*** X-PLANE KANN OBJEKTE SETZEN *** -- AutoShift aktiv",
    "laeuft_noch_sekunden": "Lebenszeichen -- die Instanz ueberdauert",
    "ABBRUCH": "Abgebrochen, Grund steht im Wert",
    "XPluginStop": "Das Plugin wurde entladen",
}


class Ohr(BaseHTTPRequestHandler):
    # Die Proben schliessen die Verbindung, ohne die Antwort zu lesen -- das ist in
    # Ordnung, sie wollen nur melden. http.server wirft dafuer sonst einen Traceback je
    # Meldung und macht das Protokoll unlesbar (11.09.2026: 30 KB Tracebacks um 14 echte
    # Zeilen herum).
    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        frage = parse_qs(urlparse(self.path).query)
        schritt = frage.get("schritt", ["?"])[0]
        wert = frage.get("wert", ["?"])[0]
        uhr = datetime.datetime.now().strftime("%H:%M:%S")
        # Lange Werte (Dateipfade) nicht in die Zahlenspalte quetschen.
        if len(wert) > 12:
            print(f"{uhr}  {schritt:<20}   {DEUTUNG.get(schritt, '')}\n"
                  f"          -> {wert}", flush=True)
        else:
            print(f"{uhr}  {schritt:<20} {wert:>12}   {DEUTUNG.get(schritt, '')}", flush=True)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args) -> None:
        pass        # die eigene Zeile oben genuegt


if __name__ == "__main__":
    print("Horcher auf 127.0.0.1:8099 (/wasm und /xplane) -- warte auf die Probe im Simulator.")
    print("(Strg-C beendet.)\n")
    HTTPServer(("127.0.0.1", 8099), Ohr).serve_forever()
