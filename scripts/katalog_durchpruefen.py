# -*- coding: utf-8 -*-
"""Jeden Titel des Katalogs einmal hinstellen und das Ergebnis vermerken (16.09.2026).

**Wozu.** Der Katalog führt 2928 X-Plane-Titel, von denen am 16.09.2026 **2924 nie versucht
worden waren** — auch 105 der 109, die bereits einer Art zugeordnet sind und damit an
Piloten ausgeliefert werden. Wer eine neue Art anlegt und ihr Titel zuordnet, weiß also
nicht, ob sie im Simulator etwas ergeben. Genau das war der Wunsch des Nutzers: *„ich will
sicher sein, dass auch alle Objekte im Katalog funktionieren würden, falls ich selbst eine
neue Art anlegen möchte"*.

**Wie.** Blockweise vor dem Piloten, damit er zusehen kann. Je Block bekommt jeder Titel
eine eigene Wegwerf-Art und ein eigenes Soll-Objekt; die Rückmeldung nennt die Objekt-``id``,
und über die ist der Titel eindeutig — der Lernweg des Servers
(``bruegge_katalog_ergebnis_melden``) wird hier NICHT benutzt, denn der kann nur zuordnen,
wenn eine Art genau einen aktiven Titel hat.

**Das Urteil gilt je Simulator** (``bruegge_titel_lauf``, seit 19.09.2026): Ein Lauf in
MSFS 2020 schreibt die 2020er Zeile und laesst die aus MSFS 2024 stehen. „Offen" heisst
deshalb: *fuer DIESEN Simulator noch nie versucht* -- unabhaengig davon, wo der Titel gefunden
wurde und was ein anderer Simulator sagt. Die Wegwerf-Art braucht keinen Partner im anderen
Simulator mehr: Die Beidseitig-Regel, die ihn erzwang, gibt es nicht mehr.

Ein Urteil **von Hand** (``quelle='hand'``, z. B. „Seehund ist rosa") wird nie ueberschrieben --
solche Titel lassen den Lauf aus.

⚠ **Vor dem Lauf muss 14.50.3 laufen.** Davor wertete der Server ``NOCH_NICHT_GESETZT`` und
``GATTUNG_UNBEKANNT`` als Fehlschlag und schaltete Titel ab — ein Prüflauf hätte den Katalog
zerstört, statt ihn zu vermessen.

    python katalog_durchpruefen.py --cid 1602713 --simulator xplane12
    python katalog_durchpruefen.py --cid 1602713 --simulator xplane12 --block 12 --sekunden 8
    python katalog_durchpruefen.py --cid 1602713 --simulator xplane12 --alle   # auch Geprüfte
    python katalog_durchpruefen.py --cid 1602713 --simulator msfs2020 --nur-zugeordnet
"""
from __future__ import annotations

import argparse
import math
import sys
import time

# Im Container liegt die App unter /opt/friesenspy -- das Arbeitsverzeichnis ist ein
# anderes, deshalb der ausdrueckliche Pfad.
sys.path.insert(0, "/opt/friesenspy")

# ⚠ DIESELBE Regel wie der Server, IMPORTIERT statt abgeschrieben. Der erste Probelauf
# (16.09.2026, sechs Titel) meldete 5 Fehlschlaege und 1 Erfolg bei sechs GLEICHARTIGEN
# Objekten -- kein Modellfehler, sondern Ladezeit: `NOCH_NICHT_GESETZT` wurde als Urteil
# geschrieben. Genau der Fehler, der eine Stunde vorher im Server behoben wurde. Wer die
# Liste hier als eigene Konstante fuehrt, baut ihn ein drittes Mal.
from app.main import _BRUEGGE_KEIN_URTEIL  # noqa: E402
from app.database import (  # noqa: E402
    bruegge_art_loeschen,
    bruegge_art_setzen,
    bruegge_katalog_setzen,
    bruegge_lauf_setzen,
    bruegge_soll_loeschen,
    bruegge_soll_setzen,
    get_connection,
    _BRUEGGE_TOPF,
)

DB = "/opt/friesenspy/data/friesenspy.db"

#: Präfix der Wegwerf-Arten. Wird am Ende jedes Blocks wieder entfernt -- und beim Start
#: eines Laufs vorsorglich auch, falls ein früherer Lauf abgebrochen ist.
VORSATZ = "zzpruef_"


def _offene_titel(conn, simulator: str, alle: bool,
                  nur_zugeordnet: bool) -> list[tuple[str, str]]:
    """(Fundort, Titel) -- EIN Eintrag je Titel, der in DIESEM Simulator zu pruefen ist.

    Massgeblich ist der Pruef-Simulator, nicht der Fundort: MSFS 2020 und 2024 schoepfen aus
    demselben Titelvorrat, ein 2024er Titel kann in 2020 laufen und umgekehrt (`BlackBear`).
    "Offen" ist, wofuer es in DIESEM Simulator noch kein Urteil gibt -- ein Urteil aus einem
    anderen zaehlt nicht.

    Titel mit Urteil von Hand bleiben draussen (die Automatik ueberschreibt sie nie), ebenso
    geratene Titel (gestreamte Pakete ohne entpackten Ordner: ein Fehlschlag, den man selbst
    verursacht haette).

    ``nur_zugeordnet``: nur, was eine Art traegt -- also das, was an Piloten hinausgeht. Der
    erste Lauf in einem neuen Simulator soll das zuerst wissen; der Rest des Katalogs (mehrere
    Tausend Titel) hat keine Eile.

    Steht ein Titel in beiden MSFS-Bestaenden, wird er einmal geprueft und bevorzugt ueber die
    Zeile, die eine Art traegt.
    """
    wo = ["(k.bemerkung IS NULL OR k.bemerkung NOT LIKE 'Titel unbekannt%')",
          "(l.quelle IS NULL OR l.quelle <> 'hand')", _BRUEGGE_TOPF[simulator]]
    if not alle:
        wo.append("l.titel IS NULL")
    if nur_zugeordnet:
        wo.append("k.art IS NOT NULL")
    rows = conn.execute(
        "SELECT k.simulator, k.titel FROM bruegge_katalog k "
        "LEFT JOIN bruegge_titel_lauf l ON l.titel = k.titel AND l.simulator = ? "
        "WHERE " + " AND ".join(wo) + " ORDER BY k.titel, (k.art IS NULL), k.simulator",
        (simulator,)).fetchall()
    je_titel: dict[str, str] = {}
    for fundort, titel in rows:
        je_titel.setdefault(titel, fundort)
    return [(f, t) for t, f in je_titel.items()]


def _raster(lat: float, lon: float, kurs: float, n: int, vor_m: float, abstand_m: float):
    """`n` Punkte quer vor der Nase, mittig -- dasselbe Muster wie `probe-msfs/titel_schau.py`."""
    v = math.radians(kurs)
    q = math.radians((kurs + 90.0) % 360.0)
    for i in range(n):
        quer = (i - (n - 1) / 2.0) * abstand_m
        dn = vor_m * math.cos(v) + quer * math.cos(q)
        de = vor_m * math.sin(v) + quer * math.sin(q)
        yield (round(lat + dn / 111320.0, 7),
               round(lon + de / (111320.0 * math.cos(math.radians(lat))), 7))


def _aufraeumen(conn) -> int:
    """Alle Wegwerf-Arten und ihre Objekte entfernen."""
    weg = 0
    for (art,) in conn.execute(
            "SELECT art FROM bruegge_art WHERE art LIKE ?", (VORSATZ + "%",)).fetchall():
        bruegge_soll_loeschen(conn, "p-" + art)
        # ⚠ `bruegge_art_loeschen` gibt die Titel frei (art/rang/status auf NULL) -- genau
        # richtig: Die Zuordnung war nur fuer diesen Lauf da, das PRUEFERGEBNIS bleibt.
        weg += bruegge_art_loeschen(conn, art)
    conn.commit()
    return weg


def _ergebnis_schreiben(conn, simulator: str, titel: str, zustand: str,
                        fehler: str | None, hoehe) -> None:
    """Das Urteil unter dem PRUEF-Simulator festhalten -- ohne Umweg ueber den Lernweg.

    ⚠ `status` wird NICHT angefasst, auch nicht bei einem Fehlschlag. Ein Prüflauf soll
    messen, nicht entscheiden: Ob ein gescheiterter Titel abgeschaltet gehört, sieht der
    Nutzer hinterher an der Liste -- und ein Fehlschlag kann auch an der Stelle liegen
    (Wasser, Gelände, Reality Bubble), nicht am Titel.
    """
    bruegge_lauf_setzen(conn, titel, simulator,
                        "steht" if zustand == "steht" else "fehlgeschlagen", fehler, hoehe)


def lauf(cid: int, simulator: str, block: int, sekunden: float, vor_m: float,
         abstand_m: float, alle: bool, grenze: int | None,
         nur_zugeordnet: bool = False) -> int:
    conn = get_connection(DB)
    try:
        weg = _aufraeumen(conn)
        if weg:
            print(f"  (aus einem frueheren Lauf aufgeraeumt: {weg} Arten)")

        titel = _offene_titel(conn, simulator, alle, nur_zugeordnet)
        if grenze:
            titel = titel[:grenze]
        if not titel:
            print("Nichts zu pruefen.")
            return 0
        print(f"{len(titel)} Titel in {simulator}, Bloecke zu {block}, je {sekunden:.0f} s")

        steht = fehl = stumm = 0
        for start in range(0, len(titel), block):
            teil = titel[start:start + block]          # [(Fundort, Titel), ...]
            # ⚠⚠ `AND simulator = ?` -- ohne das misst der Lauf den FALSCHEN SIMULATOR.
            #
            # Am 16.09.2026 passiert: Der Pilot hatte X-Plane geschlossen und MSFS gestartet,
            # dieselbe CID. Der Lauf schickte weiter X-Plane-Dateipfade, die MSFS-Bruegge
            # antwortete voellig korrekt mit `EXCEPTION_22` -- und 16 Titel, die zwanzig
            # Minuten vorher nachweislich gestanden hatten, galten als kaputt.
            #
            # Die Rueckmeldung traegt keine Simulator-Angabe (`bruegge_steht` hat nur `id`,
            # `kennung` und `cid`), also muss VORHER feststehen, wer da meldet.
            lage = conn.execute(
                "SELECT lat, lon, kurs FROM bruegge_positions WHERE cid = ? AND simulator = ?",
                (cid, simulator)).fetchone()
            if not lage:
                jetzt = conn.execute(
                    "SELECT simulator FROM bruegge_positions WHERE cid = ?", (cid,)).fetchone()
                print(f"Keine {simulator}-Bruegge fuer CID {cid}"
                      + (f" -- dort meldet gerade {jetzt[0]}." if jetzt else " -- sie meldet nicht.")
                      + " Lauf angehalten.")
                break
            punkte = list(_raster(lage[0], lage[1], lage[2], len(teil), vor_m, abstand_m))

            zu_id = {}
            # ⚠⚠ DIE URSPRUENGLICHE ZUORDNUNG MERKEN, SONST ZERSTOERT DER LAUF SIE.
            #
            # Am 16.09.2026 passiert, und es war der schwerste Fehler des Tages: Der Lauf
            # haengt jeden Titel an eine Wegwerf-Art, und `bruegge_art_loeschen` GIBT DIE
            # TITEL BEIM AUFRAEUMEN FREI (art/rang/status auf NULL). Was vorher `windrad`
            # oder `seehund_kuh` war, stand danach ohne Art da.
            #
            # Von 203 Zuordnungen waren 58 uebrig. Keine Art war mehr beidseitig, und ALLES
            # meldete `ART_UNBEKANNT` -- gerettet hat es die naechtliche Sicherung.
            #
            # Titel mit Art vom Lauf auszunehmen waere falsch: Gerade sie gehen an Piloten
            # hinaus und muessen geprueft sein. Also wird die Zuordnung gesichert und nach
            # dem Block zurueckgeschrieben.
            vorher = {}
            for fundort, t in teil:
                r = conn.execute(
                    "SELECT art, rang, status FROM bruegge_katalog "
                    "WHERE simulator = ? AND titel = ?", (fundort, t)).fetchone()
                if r and r[0]:
                    vorher[(fundort, t)] = tuple(r)

            # ⚠ Bei `--alle` steht fuer manche Titel schon ein Urteil -- und ein durchgefallener
            # Titel geht in DIESEM Simulator nicht mehr hinaus (`bruegge_titel_fuer`), die
            # Bruegge bekaeme ihn gar nicht und meldete `ART_UNBEKANNT`. Also vorher weg damit;
            # gemessen wird ohnehin neu. Urteile von Hand sind aussortiert (`_offene_titel`).
            if alle:
                for _, t in teil:
                    conn.execute(
                        "DELETE FROM bruegge_titel_lauf WHERE titel = ? AND simulator = ? "
                        "AND quelle <> 'hand'", (t, simulator))

            for nr, ((fundort, t), (zl, zo)) in enumerate(zip(teil, punkte)):
                art = VORSATZ + f"{nr:03d}"
                bruegge_art_setzen(conn, art, bedeutung="Pruefbetrieb",
                                   status="aktiv")
                bruegge_katalog_setzen(conn, fundort, t, art=art, rang=1, status="aktiv")
                oid = "p-" + art
                bruegge_soll_setzen(conn, oid, art, zl, zo, cid=cid, kurs=lage[2],
                                    auf_boden=True, bemerkung="Pruefbetrieb")
                zu_id[oid] = t
            conn.commit()

            time.sleep(sekunden)

            # Wer noch laedt, bekommt eine zweite Runde -- und wenn er dann immer noch
            # nicht da ist, gilt er als STUMM, nicht als gescheitert. Ein langsam ladendes
            # Objekt ist kein kaputtes.
            offen = dict(zu_id)
            for versuch in range(2):
                nachgefasst = {}
                for oid, t in offen.items():
                    r = conn.execute(
                        "SELECT zustand, fehler, hoehe_ft FROM bruegge_steht WHERE id = ?",
                        (oid,)).fetchone()
                    if not r or (r[0] != "steht" and (r[1] or "") in _BRUEGGE_KEIN_URTEIL):
                        nachgefasst[oid] = t
                        continue
                    _ergebnis_schreiben(conn, simulator, t, r[0], r[1], r[2])
                    if r[0] == "steht":
                        steht += 1
                    else:
                        fehl += 1
                offen = nachgefasst
                if not offen or versuch:
                    break
                time.sleep(max(4.0, sekunden / 2))
            stumm += len(offen)

            # Die gesicherte Zuordnung zurueckschreiben -- VOR dem Aufraeumen, sonst holt
            # `bruegge_art_loeschen` sie gleich wieder weg.
            for (fundort, t), (art, rang, status) in vorher.items():
                bruegge_katalog_setzen(conn, fundort, t, art=art, rang=rang, status=status)
            conn.commit()
            _aufraeumen(conn)
            fertig = min(start + block, len(titel))
            print(f"  {fertig:5d}/{len(titel)}   steht {steht}  fehlgeschlagen {fehl}  "
                  f"ohne Meldung {stumm}")

        print(f"\nFertig: {steht} stehen, {fehl} gescheitert, {stumm} ohne Rueckmeldung.")
        return 0
    finally:
        _aufraeumen(conn)
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cid", type=int, required=True, help="Pilot, vor dem geprueft wird")
    ap.add_argument("--simulator", default="xplane12", choices=["xplane12", "msfs2024",
                                                                "msfs2020"])
    ap.add_argument("--block", type=int, default=12, help="Titel je Durchgang")
    ap.add_argument("--sekunden", type=float, default=8.0, help="Standzeit je Durchgang")
    ap.add_argument("--vor", type=float, default=120.0, help="Meter vor dem Piloten")
    ap.add_argument("--abstand", type=float, default=25.0, help="Meter zwischen den Objekten")
    ap.add_argument("--alle", action="store_true", help="auch schon geprueste erneut")
    ap.add_argument("--grenze", type=int, help="nur die ersten N (zum Ausprobieren)")
    ap.add_argument("--nur-zugeordnet", action="store_true",
                    help="nur Titel, die eine Art tragen (das, was an Piloten hinausgeht)")
    a = ap.parse_args()
    return lauf(a.cid, a.simulator, a.block, a.sekunden, a.vor, a.abstand, a.alle, a.grenze,
                a.nur_zugeordnet)


if __name__ == "__main__":
    sys.exit(main())
