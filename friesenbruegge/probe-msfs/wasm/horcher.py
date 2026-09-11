"""Nimmt entgegen, was das WASM-Modul meldet.

Das Modul im Simulator ruft http://127.0.0.1:8099/wasm?schritt=...&wert=... auf. Jede Zeile
hier ist ein Schritt, den es geschafft hat -- und die Zeile "ERFOLG_objekt_id" ist die
Antwort auf Spec 13.4, Frage 1.

Kommt gar nichts an, ist auch das ein Befund: dann darf ein WASM-Modul nicht ins Netz, und
MSFS_Network.h haelt nicht, was der Header verspricht.

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
}


class Ohr(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        frage = parse_qs(urlparse(self.path).query)
        schritt = frage.get("schritt", ["?"])[0]
        wert = frage.get("wert", ["?"])[0]
        uhr = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"{uhr}  {schritt:<20} {wert:>12}   {DEUTUNG.get(schritt, '')}", flush=True)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args) -> None:
        pass        # die eigene Zeile oben genuegt


if __name__ == "__main__":
    print("Horcher auf http://127.0.0.1:8099/wasm -- warte auf das Modul im Simulator.")
    print("(Strg-C beendet.)\n")
    HTTPServer(("127.0.0.1", 8099), Ohr).serve_forever()
