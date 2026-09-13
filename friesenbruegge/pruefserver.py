"""Der Prüfserver: spielt FriesenSpy, damit sich eine Brügge ohne VATSIM messen lässt.

WOZU ES IHN GIBT
================

Der echte Server liefert `soll` nur an einen Piloten, den er über die Position einem
VATSIM-Flug zuordnen konnte (PROTOKOLL.md, Abschnitt 5). Das ist richtig so — es heißt aber,
dass sich das **Objektsetzen** ohne VATSIM-Verbindung überhaupt nicht prüfen lässt.

Am 13.09.2026 hat genau das eine Stunde gekostet: Die X-Plane-Brügge lief nachweislich,
meldete sauber, bekam aber immer ein leeres `soll` — weil xPilot seinen eigenen Simulator
nicht fand. Eine Stunde in einem fremden Programm statt in unserem.

Dieser Server nimmt die Meldung entgegen, zeigt sie an und antwortet mit einem Sollzustand,
den man von Hand zusammenstellt. Er ist damit auch das bequemere Werkzeug für alles, was
NICHT die Zuordnung betrifft: Man sieht die volle Meldung im Klartext, statt sie aus der
Datenbank zu fischen.

⚠ **Er prüft nicht, was der Server prüft.** Zuordnung, Rechtefrage, Drosselung, `forum_callsign`
— davon steht hier nichts. Wer hier grün sieht, hat die Brügge geprüft, nicht das Zusammenspiel.

SO GEHT ES
==========

1. Diesen Server starten::

       py pruefserver.py

2. Die Brügge auf ihn umbiegen — eine Datei mit einer Zeile:

   X-Plane:  <X-Plane 12>\\Output\\preferences\\friesenbruegge.url
   Inhalt:   http://127.0.0.1:8099/api/bruegge/melden

3. Simulator neu starten. Im Log steht dann::

       [FriesenBruegge] Ziel UMGEBOGEN auf http://127.0.0.1:8099/api/bruegge/melden

4. Objekte anfordern — im laufenden Betrieb, ohne irgendetwas neu zu starten::

       py pruefserver.py --setzen tier_gross --neben 30
       py pruefserver.py --leeren

   Das schreibt ``soll.json`` neben dieses Skript; der laufende Server liest die Datei bei
   jeder Meldung neu. `--neben 30` heißt: 30 m östlich der zuletzt gemeldeten Position.

Die Meldungen laufen als Tabelle mit, eine Zeile je Takt.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HIER = Path(__file__).resolve().parent
SOLL_DATEI = HIER / "soll.json"
LAGE_DATEI = HIER / "letzte_lage.json"

# Was der Server der Brügge sagt. 1 s ist der Regeltakt aus dem Protokoll (Abschnitt 6).
TAKT_S = 1
GILT_BIS_S = 300


def _jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _versetzen(lat: float, lon: float, meter_ost: float, meter_nord: float = 0.0) -> tuple[float, float]:
    """Ein Punkt in der Nähe. Reicht für ein paar hundert Meter völlig."""
    grad_lat = meter_nord / 111_320.0
    grad_lon = meter_ost / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
    return lat + grad_lat, lon + grad_lon


class Brueggenempfang(BaseHTTPRequestHandler):
    # Die eigene Protokollzeile von BaseHTTPRequestHandler unterdrücken -- sie schriebe je
    # Meldung eine Zeile "POST ... 200 -", und bei Sekundentakt ersäuft darin alles andere.
    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802  (von der Basisklasse vorgegeben)
        laenge = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(laenge) if laenge else b""
        try:
            meldung = json.loads(roh.decode("utf-8"))
        except Exception as fehler:
            print(f"[{_jetzt()}] ⚠ unlesbare Meldung ({fehler}) — {roh[:120]!r}")
            self.send_response(400)
            self.end_headers()
            return

        self._zeigen(meldung)
        self._lage_merken(meldung)

        antwort = {
            "protokoll": 1,
            "naechste_frage_in_s": TAKT_S,
            "gilt_bis_s": GILT_BIS_S,
            "soll": self._soll_lesen(meldung),
        }
        rumpf = json.dumps(antwort).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    # ----------------------------------------------------------------- Anzeige
    def _zeigen(self, m: dict) -> None:
        lage = m.get("lage") or {}
        steht = m.get("steht") or []
        kopf = (f"[{_jetzt()}] {m.get('simulator','?'):9} {m.get('bruegge_version','?'):6} "
                f"{lage.get('lat', 0):9.5f} {lage.get('lon', 0):9.5f} "
                f"{lage.get('alt_msl_ft', 0):8.1f} ft  AGL {lage.get('alt_agl_ft', 0):7.1f}  "
                f"{lage.get('gs_kt', 0):5.1f} kt  {lage.get('kurs', 0):5.1f}°"
                f"{'  am Boden' if lage.get('am_boden') else ''}")
        print(kopf)

        if m.get("antwort_zu_gross"):
            print(f"           ⚠ die letzte Antwort passte nicht in ihren Puffer "
                  f"({m['antwort_zu_gross']} Bytes)")

        for o in steht:
            if o.get("zustand") == "steht":
                # `hoehe_gemessen` gibt es erst ab der X-Plane-Bruegge: Es unterscheidet eine
                # echte Gelaendeprobe von "Meereshoehe, weil das Gelaende nicht geladen war".
                gemessen = o.get("hoehe_gemessen")
                marke = "" if gemessen is None else ("  ✓gemessen" if gemessen else "  ~geraten")
                print(f"           ✅ {o['id']:12} steht auf {o.get('hoehe_ft', 0):9.1f} ft"
                      f"{marke}   seit {o.get('seit_s', 0)} s")
            elif o.get("zustand") == "fehlgeschlagen":
                print(f"           ❌ {o['id']:12} {o.get('fehler', '?')}")
            else:
                print(f"           ⚠  {o['id']:12} {o.get('zustand')} seit {o.get('seit_s', 0)} s")

    def _lage_merken(self, m: dict) -> None:
        lage = m.get("lage") or {}
        if not lage:
            return
        # `steht` gehoert mit in die Datei, nicht nur auf die Konsole: Laeuft der Server im
        # Hintergrund, ist seine Ausgabe nicht zu sehen -- die Rueckmeldung ist aber genau
        # das, was man beim Messen braucht.
        LAGE_DATEI.write_text(json.dumps({
            "zeit": _jetzt(),
            "lat": lage.get("lat"), "lon": lage.get("lon"),
            "alt_msl_ft": lage.get("alt_msl_ft"),
            "alt_agl_ft": lage.get("alt_agl_ft"),
            "kurs": lage.get("kurs"),
            "am_boden": lage.get("am_boden"),
            "kann": m.get("kann") or [],
            "steht": m.get("steht") or [],
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    # -------------------------------------------------------------------- soll
    def _soll_lesen(self, m: dict) -> list[dict]:
        """Der Sollzustand aus ``soll.json`` — bei JEDER Meldung frisch gelesen.

        Frisch gelesen, damit sich Objekte im laufenden Betrieb anfordern und wegnehmen
        lassen, ohne den Server anzufassen. Das ist derselbe Gedanke wie beim echten Server:
        `soll` ist ein Zustand, kein Befehlsstrom.
        """
        if not SOLL_DATEI.is_file():
            return []
        try:
            eintraege = json.loads(SOLL_DATEI.read_text(encoding="utf-8"))
        except Exception as fehler:
            print(f"           ⚠ soll.json unlesbar: {fehler}")
            return []

        lage = m.get("lage") or {}
        lat0, lon0 = lage.get("lat"), lage.get("lon")
        fertig = []
        for e in eintraege:
            o = dict(e)
            # `neben` heisst: soviele Meter oestlich von DIR, jetzt. Ohne das muesste man
            # Koordinaten abtippen, und das war am 12.09. die haeufigste Fehlerquelle.
            weite = o.pop("neben", None)
            if weite is not None and lat0 is not None:
                o["lat"], o["lon"] = _versetzen(lat0, lon0, float(weite))
            fertig.append(o)
        return fertig


# --------------------------------------------------------------------------- Steuerung

def soll_schreiben(eintraege: list[dict]) -> None:
    SOLL_DATEI.write_text(json.dumps(eintraege, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--setzen", metavar="GATTUNG",
                   help="ein Objekt dieser Gattung anfordern (tier_gross, boot_klein, marke …)")
    p.add_argument("--neben", type=float, default=30.0,
                   help="soviele Meter östlich der zuletzt gemeldeten Position (Vorgabe 30)")
    p.add_argument("--hoehe", type=float, default=None,
                   help="erwartete Höhe in ft MSL; ohne Angabe sucht die Brügge die Oberfläche")
    p.add_argument("--kurs", type=float, default=0.0)
    p.add_argument("--id", default=None, help="eigene Kennung statt einer laufenden Nummer")
    p.add_argument("--leeren", action="store_true", help="alles wieder abräumen lassen")
    p.add_argument("--zeigen", action="store_true", help="zeigt den aktuellen Sollzustand")
    a = p.parse_args()

    if a.leeren:
        soll_schreiben([])
        print("soll.json geleert — die Brügge räumt beim nächsten Takt ab.")
        return 0

    if a.zeigen:
        print(SOLL_DATEI.read_text(encoding="utf-8") if SOLL_DATEI.is_file() else "(kein soll.json)")
        if LAGE_DATEI.is_file():
            print("zuletzt gemeldet:", LAGE_DATEI.read_text(encoding="utf-8"))
        return 0

    if a.setzen:
        vorhanden = []
        if SOLL_DATEI.is_file():
            try:
                vorhanden = json.loads(SOLL_DATEI.read_text(encoding="utf-8"))
            except Exception:
                vorhanden = []
        eintrag = {
            "id": a.id or f"pruef-{len(vorhanden) + 1}",
            "art": a.setzen,
            "kurs": a.kurs,
            "neben": a.neben,
            "auf_boden": 1,
        }
        if a.hoehe is not None:
            eintrag["erwartete_hoehe_ft"] = a.hoehe
        vorhanden.append(eintrag)
        soll_schreiben(vorhanden)
        print(f"angefordert: {eintrag['id']} ({a.setzen}), {a.neben:.0f} m östlich von dir.")
        print("Der laufende Prüfserver liefert es beim nächsten Takt aus.")
        return 0

    # Ohne Befehl: den Server starten.
    server = HTTPServer(("127.0.0.1", a.port), Brueggenempfang)
    print(f"Prüfserver lauscht auf http://127.0.0.1:{a.port}/api/bruegge/melden")
    print(f"Sollzustand: {SOLL_DATEI}")
    print("Beenden mit Strg+C.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
