# -*- coding: utf-8 -*-
"""Jeden Titel des Katalogs einmal hinstellen und das Ergebnis vermerken (16.09.2026,
neu gefasst am 20.09.2026).

**Wozu.** Der Katalog führt tausende Titel, von denen die meisten nie versucht worden waren --
auch solche, die einer Art zugeordnet sind und damit an Piloten ausgeliefert werden. Wer eine
neue Art anlegt und ihr Titel zuordnet, weiß also nicht, ob sie im Simulator etwas ergeben.
Genau das war der Wunsch des Nutzers: *„ich will sicher sein, dass auch alle Objekte im Katalog
funktionieren würden, falls ich selbst eine neue Art anlegen möchte"*.

**Wie.** Blockweise vor dem Piloten, damit er zusehen kann. Je Block bekommt jeder Titel eine
eigene Wegwerf-Art und ein eigenes Soll-Objekt; die Rückmeldung nennt die Objekt-``id``, und
über die ist der Titel eindeutig -- der Lernweg des Servers
(``bruegge_katalog_ergebnis_melden``) wird hier NICHT benutzt, denn der kann nur zuordnen,
wenn eine Art genau einen aktiven Titel hat.

**Das Urteil gilt je Simulator** (``bruegge_titel_lauf``, seit 19.09.2026): Ein Lauf in
MSFS 2020 schreibt die 2020er Zeile und laesst die aus MSFS 2024 stehen. „Offen" heisst
deshalb: *fuer DIESEN Simulator noch nie versucht* -- unabhaengig davon, wo der Titel gefunden
wurde und was ein anderer Simulator sagt.

Ein Urteil **von Hand** (``quelle='hand'``, z. B. „Seehund ist rosa") wird nie ueberschrieben --
solche Titel lassen den Lauf aus. **Community-Titel werden nie geprueft** (Nutzerregel
20.09.2026: fremde Pakete gehoeren nicht in den Lauf, und wer sie nicht installiert hat, sieht
ohnehin nichts).

⚠ **Was am 20.09.2026 geaendert wurde, und warum** (der alte Lauf war in MSFS 2020
unbrauchbar): Er meldete je 12er-Block genau drei Fehlschlaege, und zwar bei Titeln, die einzeln
nachweislich standen. Er benutzte in JEDEM Block dieselben Objekt-IDs (``p-zzpruef_000`` ...) und
las das Ergebnis nach einer festen Wartezeit, ohne zu pruefen, ob die Zeile frisch war. Ein Lauf
mit **eindeutiger ID je Titel**, **200er Bloecken** und **nur frischen Meldungen** ging in MSFS
2020 ohne einen solchen Fehler durch (2 700 Titel, rund vier Sekunden je Block). Bewiesen ist der
Zusammenhang, nicht der Mechanismus: Dass die Wiederverwendung der IDs die Ursache war, ist die
naheliegende, aber ungeprueft gebliebene Erklaerung.

⚠ **Vor dem Lauf muss 14.50.3 laufen.** Davor wertete der Server ``NOCH_NICHT_GESETZT`` und
``GATTUNG_UNBEKANNT`` als Fehlschlag und schaltete Titel ab.

⚠ **Nur EIN Simulator darf laufen.** Laufen MSFS 2020 und 2024 zugleich, meldet die 2024er
Bruegge sich als 2020er (20.09.2026 beobachtet) -- der Lauf misst dann den falschen Simulator.

    python katalog_durchpruefen.py --cid 1602713 --simulator msfs2020
    python katalog_durchpruefen.py --cid 1602713 --simulator msfs2020 --ohne-kategorie ships,Airplanes
    python katalog_durchpruefen.py --cid 1602713 --simulator msfs2020 --nur-kategorie ships --vor
    python katalog_durchpruefen.py --cid 1602713 --simulator xplane12 --block 100 --alle
    python katalog_durchpruefen.py --cid 1602713 --simulator msfs2020 --nur-zugeordnet

Abbruch von aussen: die Datei ``/opt/friesenspy/data/katalog_durchpruefen.stop`` anlegen; der
Lauf endet nach dem laufenden Block und raeumt auf.
"""
from __future__ import annotations

import argparse
import math
import os
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
    _now_utc,
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
STOP = "/opt/friesenspy/data/katalog_durchpruefen.stop"

#: Praefix der Wegwerf-Arten. Wird am Ende jedes Blocks wieder entfernt -- und beim Start
#: eines Laufs vorsorglich auch, falls ein frueherer Lauf abgebrochen ist.
#:
#: ⚠⚠ DER NAME DARF HOECHSTENS 23 ZEICHEN LANG SEIN. In der Bruegge steht `char art[24]`
#: (`SollObjekt` in friesenbruegge/msfs/bruegge.cpp): Ein laengerer Name wird beim Einlesen
#: ABGESCHNITTEN, findet sich dann nicht mehr im Woerterbuch, und jedes Objekt meldet
#: `ART_UNBEKANNT`. Am 20.09.2026 passiert: Die neu gefasste Fassung nannte ihre Arten
#: `zzpruef_260920101751_001_000` (28 Zeichen) -- 400 Titel ohne ein einziges Urteil, und der Test
#: mit der vorgetaeuschten Bruegge war gruen, weil die nichts abschneidet. Der alte Lauf hatte
#: `zzpruef_000` und ging. `tests/test_bruegge_titel_lauf.py` liest die Grenze aus dem
#: Quelltext beider Brueggen und haelt die Namen dagegen.
VORSATZ = "zzp"

#: Mehr nimmt die Bruegge nicht an: ``SOLL_MAX`` in ``friesenbruegge/msfs/bruegge.cpp``. Ein
#: groesserer Block wuerde lautlos abgeschnitten -- und die abgeschnittenen Titel gaelten als
#: stumm, ohne dass es jemand merkt.
BLOCK_MAX = 200


def _kennung(sekunden: int) -> str:
    """Fuenf Zeichen (Basis 36) aus der Uhrzeit: pro Lauf verschieden, ohne Namen zu verlaengern."""
    ziffern = "0123456789abcdefghijklmnopqrstuvwxyz"
    n = sekunden % (36 ** 5)
    z = ""
    for _ in range(5):
        n, r = divmod(n, 36)
        z = ziffern[r] + z
    return z


def _art_name(lauf_id: str, block_nr: int, n: int) -> str:
    """Name einer Wegwerf-Art -- hoechstens 23 Zeichen (s. VORSATZ)."""
    return f"{VORSATZ}{lauf_id}{block_nr:02d}{n:03d}"


def _offene_titel(conn, simulator: str, alle: bool, nur_zugeordnet: bool,
                  ohne_kategorie: tuple[str, ...] = (),
                  nur_kategorie: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """(Fundort, Titel) -- EIN Eintrag je Titel, der in DIESEM Simulator zu pruefen ist.

    Massgeblich ist der Pruef-Simulator, nicht der Fundort: MSFS 2020 und 2024 schoepfen aus
    demselben Titelvorrat, ein 2024er Titel kann in 2020 laufen und umgekehrt (`BlackBear`).
    "Offen" ist, wofuer es in DIESEM Simulator noch kein Urteil gibt -- ein Urteil aus einem
    anderen zaehlt nicht.

    Draussen bleiben: Titel mit Urteil von Hand (die Automatik ueberschreibt sie nie),
    geratene Titel (gestreamte Pakete ohne entpackten Ordner: ein Fehlschlag, den man selbst
    verursacht haette) und **Community-Titel** (Nutzerregel 20.09.2026).

    ``nur_zugeordnet``: nur, was eine Art traegt -- also das, was an Piloten hinausgeht.
    ``ohne_kategorie`` / ``nur_kategorie``: nach ``kategorie`` filtern. Boote und Schiffe
    brauchen See unter sich (MSFS 2020 ignoriert bei ``Boat`` jede Hoehe), Flugzeuge sind
    schwer und selten Teil eines ersten Laufs -- getrennt laesst sich beides mit dem passenden
    Standort pruefen.

    Steht ein Titel in beiden MSFS-Bestaenden, wird er einmal geprueft und bevorzugt ueber die
    Zeile, die eine Art traegt.
    """
    wo = ["(k.bemerkung IS NULL OR k.bemerkung NOT LIKE 'Titel unbekannt%')",
          "(l.quelle IS NULL OR l.quelle <> 'hand')",
          "k.quelle <> 'community'", _BRUEGGE_TOPF[simulator]]
    werte: list = [simulator]
    if not alle:
        wo.append("l.titel IS NULL")
    if nur_zugeordnet:
        wo.append("k.art IS NOT NULL")
    if ohne_kategorie:
        wo.append("COALESCE(k.kategorie, '-') NOT IN (%s)" % ",".join("?" * len(ohne_kategorie)))
        werte += list(ohne_kategorie)
    if nur_kategorie:
        wo.append("COALESCE(k.kategorie, '-') IN (%s)" % ",".join("?" * len(nur_kategorie)))
        werte += list(nur_kategorie)
    rows = conn.execute(
        "SELECT k.simulator, k.titel FROM bruegge_katalog k "
        "LEFT JOIN bruegge_titel_lauf l ON l.titel = k.titel AND l.simulator = ? "
        "WHERE " + " AND ".join(wo) + " ORDER BY k.titel, (k.art IS NULL), k.simulator",
        werte).fetchall()
    je_titel: dict[str, str] = {}
    for fundort, titel in rows:
        je_titel.setdefault(titel, fundort)
    return [(f, t) for t, f in je_titel.items()]


def _raster(lat: float, lon: float, kurs: float, n: int, abstand_m: float,
            vorlauf_m: float, spalten: int, vor: bool):
    """`n` Punkte in Reihen zu je `spalten`, HINTER dem Piloten (mit ``vor`` davor).

    Hinter ihm, weil er vorwaerts fliegt und rollt -- „Testobjekte direkt hinter den Piloten,
    eng zusammen" (Nutzer). Die Reihen laufen von ihm weg, jede Reihe ``abstand_m`` weiter;
    seitlich sind die Objekte um ``abstand_m`` versetzt und mittig verteilt. Bei 200 Titeln
    und 20 Spalten sind das zehn Reihen -- rund 130 m Tiefe.
    """
    richtung = math.radians(kurs % 360.0 if vor else (kurs + 180.0) % 360.0)
    quer = math.radians((kurs + 90.0) % 360.0)
    for i in range(n):
        reihe, spalte = divmod(i, spalten)
        tiefe = vorlauf_m + reihe * abstand_m
        seit = (spalte - (spalten - 1) / 2.0) * abstand_m
        dn = tiefe * math.cos(richtung) + seit * math.cos(quer)
        de = tiefe * math.sin(richtung) + seit * math.sin(quer)
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


def _urteil(meldung) -> str | None:
    """`steht`, `fehlgeschlagen` -- oder None, wenn die Meldung nichts ueber den TITEL sagt.

    Ein Objekt, das noch laedt, ein volles Modellbestand oder eine fehlende Instanz sagen
    nichts ueber den Titel (`_BRUEGGE_KEIN_URTEIL`); ein langsam ladendes Objekt ist kein
    kaputtes. Auch `verschwunden` ist kein Urteil.
    """
    zustand, fehler = meldung[0], (meldung[1] or "")
    if zustand == "steht":
        return "steht"
    if zustand == "fehlgeschlagen" and fehler not in _BRUEGGE_KEIN_URTEIL:
        return "fehlgeschlagen"
    return None


def _frische_meldungen(conn, praefix: str, seit: str) -> dict[str, tuple]:
    """id -> (zustand, fehler, hoehe_ft) fuer alle Objekte dieses Laufs, DIE NACH `seit`
    gemeldet wurden.

    ⚠ Die Frische ist der Punkt: Eine Zeile aus einem frueheren Block oder Lauf sagt nichts
    ueber den Titel, der HEUTE unter dieser id steht. (Der alte Lauf las ohne diese Pruefung.)
    """
    return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT id, zustand, fehler, hoehe_ft FROM bruegge_steht "
        "WHERE id LIKE ? AND gemeldet_am >= ?", (praefix + "%", seit)).fetchall()}


def lauf(cid: int, simulator: str, block: int, warten_s: float, hinten_m: float,
         abstand_m: float, spalten: int, vor: bool, alle: bool, grenze: int | None,
         nur_zugeordnet: bool = False, ohne_kategorie: tuple[str, ...] = (),
         nur_kategorie: tuple[str, ...] = (), takt_s: float = 4.0) -> int:
    block = max(1, min(block, BLOCK_MAX))
    conn = get_connection(DB)
    try:
        weg = _aufraeumen(conn)
        if weg:
            print(f"  (aus einem frueheren Lauf aufgeraeumt: {weg} Arten)")
        if os.path.exists(STOP):
            os.remove(STOP)

        titel = _offene_titel(conn, simulator, alle, nur_zugeordnet, ohne_kategorie,
                              nur_kategorie)
        if grenze:
            titel = titel[:grenze]
        if not titel:
            print("Nichts zu pruefen.")
            return 0
        # Eine Kennung je LAUF: Jede Objekt-id und jede Wegwerf-Art traegt sie, damit kein
        # Objekt eines frueheren Laufs oder Blocks mit einem heutigen verwechselt wird.
        # ⚠ KURZ, s. VORSATZ: 3 + 5 + 2 + 3 = 13 Zeichen je Art, hoechstens 23 erlaubt.
        lauf_id = _kennung(int(time.time()))
        print(f"{len(titel)} Titel in {simulator}, Bloecke zu {block}, "
              f"hoechstens {warten_s:.0f} s je Block")

        steht = fehl = stumm = 0
        for nr, start in enumerate(range(0, len(titel), block)):
            if os.path.exists(STOP):
                print("Stopp-Datei gefunden -- Lauf beendet.")
                break
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
            punkte = list(_raster(lage[0], lage[1], lage[2], len(teil), abstand_m, hinten_m,
                                  spalten, vor))

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
            # dem Block zurueckgeschrieben -- VOR dem Aufraeumen.
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

            seit = _now_utc()
            praefix = f"p-{VORSATZ}{lauf_id}{nr:02d}"
            zu_id: dict[str, str] = {}
            for n, ((fundort, t), (zl, zo)) in enumerate(zip(teil, punkte)):
                art = _art_name(lauf_id, nr, n)
                bruegge_art_setzen(conn, art, bedeutung="Pruefbetrieb", status="aktiv")
                bruegge_katalog_setzen(conn, fundort, t, art=art, rang=1, status="aktiv")
                oid = "p-" + art
                bruegge_soll_setzen(conn, oid, art, zl, zo, cid=cid, kurs=lage[2],
                                    auf_boden=True, bemerkung="Pruefbetrieb")
                zu_id[oid] = t
            conn.commit()

            # Warten, bis JEDE id frisch gemeldet hat -- oder die Zeit um ist. Wer bis dahin
            # nicht (oder nur mit `_BRUEGGE_KEIN_URTEIL`) gemeldet hat, gilt als STUMM, nicht
            # als gescheitert: Ein langsam ladendes Objekt ist kein kaputtes.
            ende = time.time() + warten_s
            meldungen: dict[str, tuple] = {}
            while True:
                time.sleep(takt_s)
                meldungen = _frische_meldungen(conn, praefix, seit)
                fertig = sum(1 for m in meldungen.values() if _urteil(m))
                if fertig >= len(zu_id) or time.time() >= ende:
                    break

            b_steht = b_fehl = b_stumm = 0
            for oid, t in zu_id.items():
                m = meldungen.get(oid)
                u = _urteil(m) if m else None
                if u == "steht":
                    bruegge_lauf_setzen(conn, t, simulator, "steht", None, m[2])
                    b_steht += 1
                elif u == "fehlgeschlagen":
                    # ⚠ `status` wird NICHT angefasst, auch nicht bei einem Fehlschlag. Ein
                    # Pruefdurchgang soll messen, nicht entscheiden: Ob ein gescheiterter Titel
                    # abgeschaltet gehoert, sieht der Nutzer hinterher an der Liste -- und ein
                    # Fehlschlag kann auch an der Stelle liegen (Wasser, Gelaende, Reality
                    # Bubble), nicht am Titel.
                    bruegge_lauf_setzen(conn, t, simulator, "fehlgeschlagen", m[1], m[2])
                    b_fehl += 1
                else:
                    b_stumm += 1
            steht += b_steht; fehl += b_fehl; stumm += b_stumm

            # Die gesicherte Zuordnung zurueckschreiben -- VOR dem Aufraeumen, sonst holt
            # `bruegge_art_loeschen` sie gleich wieder weg. Erst dann werden die Objekte
            # zurueckgenommen; die Bruegge raeumt sie beim naechsten Takt weg.
            for (fundort, t), (art, rang, status) in vorher.items():
                bruegge_katalog_setzen(conn, fundort, t, art=art, rang=rang, status=status)
            conn.commit()
            _aufraeumen(conn)
            print(f"  Block {nr + 1}: {len(teil)} Titel -> steht {b_steht}, "
                  f"fehlgeschlagen {b_fehl}, stumm {b_stumm}   "
                  f"(zusammen {min(start + block, len(titel))}/{len(titel)})")
            # Antwortet weniger als die Haelfte, stimmt etwas Grundsaetzliches nicht
            # (Bruegge nicht verbunden, falscher Simulator, Simulator haengt). Weitermachen
            # wuerde nur tausende „stumm" schreiben.
            if len(meldungen) < len(zu_id) * 0.5:
                print("ABBRUCH: weniger als die Haelfte hat gemeldet -- Bruegge/Simulator pruefen.")
                break
            time.sleep(max(takt_s, 12.0))     # die Bruegge nimmt die Objekte heraus

        print(f"\nFertig: {steht} stehen, {fehl} gescheitert, {stumm} ohne Rueckmeldung.")
        return 0
    finally:
        _aufraeumen(conn)
        conn.close()


def _liste(s: str | None) -> tuple[str, ...]:
    return tuple(x.strip() for x in (s or "").split(",") if x.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cid", type=int, required=True, help="Pilot, vor dem geprueft wird")
    ap.add_argument("--simulator", default="xplane12", choices=["xplane12", "msfs2024",
                                                                "msfs2020"])
    ap.add_argument("--block", type=int, default=BLOCK_MAX,
                    help=f"Titel je Durchgang (hoechstens {BLOCK_MAX}, mehr nimmt die Bruegge nicht)")
    ap.add_argument("--warten", type=float, default=100.0,
                    help="hoechstens so viele Sekunden je Block auf die Meldungen warten")
    ap.add_argument("--hinten", type=float, default=30.0,
                    help="Meter zwischen Pilot und erster Reihe (hinter ihm)")
    ap.add_argument("--abstand", type=float, default=12.0, help="Meter zwischen den Objekten")
    ap.add_argument("--spalten", type=int, default=20, help="Objekte je Reihe")
    ap.add_argument("--vor", action="store_true",
                    help="VOR den Piloten stellen statt dahinter (fuer Schiffe ueber See)")
    ap.add_argument("--alle", action="store_true", help="auch schon Gepruefte erneut")
    ap.add_argument("--grenze", type=int, help="nur die ersten N (zum Ausprobieren)")
    ap.add_argument("--nur-zugeordnet", action="store_true",
                    help="nur Titel, die eine Art tragen (das, was an Piloten hinausgeht)")
    ap.add_argument("--ohne-kategorie", help="Kategorien auslassen, kommagetrennt")
    ap.add_argument("--nur-kategorie", help="nur diese Kategorien, kommagetrennt")
    a = ap.parse_args()
    return lauf(a.cid, a.simulator, a.block, a.warten, a.hinten, a.abstand, a.spalten, a.vor,
                a.alle, a.grenze, a.nur_zugeordnet, _liste(a.ohne_kategorie),
                _liste(a.nur_kategorie))


if __name__ == "__main__":
    sys.exit(main())
