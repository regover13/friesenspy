# -*- coding: utf-8 -*-
"""Die Arten leben im Katalog, nicht mehr in der Bruegge (14.09.2026).

Was hier gebunden wird, ist absichtlich wenig: die REGELN, nicht der Inhalt. Welche Titel zu
`tier_gross` gehoeren, entscheidet der Admin und darf sich jederzeit aendern -- dass ein
nachweislich gescheiterter Titel nicht ausgeliefert wird, darf es nicht.
"""
import sqlite3

import pytest

from app import database as db
from app.bruegge_arten import ARTEN, erstbefuellung


@pytest.fixture()
def conn(tmp_path):
    """Eine Datenbank wie in der Produktion -- `init_db` hat also schon befuellt."""
    pfad = str(tmp_path / "t.db")
    db.init_db(pfad)
    c = db.get_connection(pfad)
    yield c
    c.close()


@pytest.fixture()
def leer(tmp_path):
    """Dieselbe Datenbank, aber OHNE Zuordnung -- fuer Tests, die das Befuellen selbst pruefen.

    ⚠ Ohne diese Fixture waren drei Tests gruen, ohne etwas zu pruefen: `init_db` fuehrt die
    Erstbefuellung aus, der zweite Aufruf wird uebersprungen, und die Zusicherungen trafen
    auf Zeilen, die schon vorher richtig standen. Genau der Fall, vor dem CLAUDE.md warnt --
    ein Regressionstest muss ohne den Fix ROT werden.
    """
    pfad = str(tmp_path / "leer.db")
    db.init_db(pfad)
    c = db.get_connection(pfad)
    c.execute("UPDATE bruegge_katalog SET art = NULL, rang = NULL, status = NULL")
    c.execute("DELETE FROM bruegge_katalog "
              "WHERE bemerkung = 'beim Arten-Umzug angelegt'")
    c.commit()
    yield c
    c.close()


def test_erstbefuellung_legt_fehlende_titel_an(leer):
    """Unser eigener Rauch entstand NACH dem letzten Sammellauf -- er fehlt im Katalog.

    Die Liste soll vollstaendig sein ("Das soll aber trotzdem alles in der Liste vorhanden
    sein!"), also legt die Erstbefuellung an, was sie nicht findet.
    """
    ergebnis = db.bruegge_arten_erstbefuellen(leer)
    assert ergebnis["uebersprungen"] is False
    assert ergebnis["angelegt"] == len(erstbefuellung())   # leerer Katalog: alles neu
    titel = db.bruegge_titel_fuer(leer, "msfs2024")
    assert "FrsRauch_Signalrot" in titel["rauch_signalrot"]


def test_erstbefuellung_faesst_handarbeit_nicht_an(conn):
    """Zweimal laufen darf nicht ueberschreiben -- im Admin Gepflegtes gewinnt.

    `conn` ist schon befuellt (durch `init_db`), genau wie in der Produktion nach dem ersten
    Start. Ein Neustart darf die Pflege nicht zuruecksetzen.
    """
    db.bruegge_katalog_setzen(conn, "msfs2020", "BlackBear", status="aus")
    zweiter = db.bruegge_arten_erstbefuellen(conn)
    assert zweiter["uebersprungen"] is True
    assert "BlackBear" not in db.bruegge_titel_fuer(conn, "msfs2024").get("tier_gross", [])


def test_gescheiterter_titel_wird_nicht_ausgeliefert(leer):
    """DER Grund fuer den ganzen Umzug.

    Die alte Bruegge-Tabelle fuehrte drei Titel, die seit dem 12.09.2026 mit EXCEPTION_22
    scheitern (`PolarBear`, `Bear_U_Maritimus`, `deer_o_hemionus`) -- sie probierte sie
    trotzdem bei jedem Fehlversuch durch. Eine Tabelle im Client kann das nicht wissen.

    Geprueft wird an `BlackBear`, weil der in der Zuordnung auf `aktiv` steht: Nur so wird
    der Test ohne die Automatik rot. Bei `PolarBear` waere er gruen, ohne etwas zu zeigen --
    der steht dort schon von Hand auf `aus`.
    """
    # Eine frische Testdatenbank hat keinen gesammelten Bestand -- die Zeile muss es geben,
    # sonst legt die Erstbefuellung sie neu an und findet natuerlich kein Pruefergebnis.
    db.katalog_eintragen(leer, [{"simulator": "msfs2020", "titel": "BlackBear",
                                 "quelle": "bord"}])
    db.katalog_ergebnis(leer, "msfs2020", "BlackBear", "fehlgeschlagen",
                        fehler="EXCEPTION_22", geprueft_in="msfs2024")
    db.bruegge_arten_erstbefuellen(leer)
    assert "BlackBear" not in db.bruegge_titel_fuer(leer, "msfs2024").get("tier_gross", [])
    # ... aber die Zeile bleibt stehen. Wer sie loescht, verliert den Befund.
    zeile = leer.execute(
        "SELECT art, status FROM bruegge_katalog WHERE titel = 'BlackBear'").fetchone()
    assert zeile["art"] == "tier_gross"
    assert zeile["status"] == "aus"


def test_msfs_bekommt_beide_bestaende_xplane_nur_seinen(conn):
    """`BlackBear` liegt im 2020er Bestand und laeuft in MSFS 2024 -- gemessen.

    Deshalb bilden msfs2020 und msfs2024 EINEN Topf. X-Plane bleibt getrennt: dort ist der
    Bezeichner ein Dateipfad, ein MSFS-Titel waere sinnlos.
    """
    db.bruegge_arten_erstbefuellen(conn)
    msfs = db.bruegge_titel_fuer(conn, "msfs2024")
    xp = db.bruegge_titel_fuer(conn, "xplane12")
    assert "BlackBear" in msfs["tier_gross"]          # aus dem 2020er Bestand
    assert "Windmill" in msfs["windrad"]              # 2020er Bestand
    assert "windmill" in msfs["windrad"]              # 2024er Bestand, derselbe Topf
    for titel in xp.values():
        assert not any(t.startswith(("Frs", "Boat", "Flag")) for t in titel)
    assert all(t.startswith("Resources/") for liste in xp.values() for t in liste)


def test_rang_bestimmt_die_reihenfolge(conn):
    """Scheitert Titel 1, rueckt Titel 2 nach -- die Reihenfolge ist Absicht, kein Zufall."""
    db.bruegge_arten_erstbefuellen(conn)
    boote = db.bruegge_titel_fuer(conn, "xplane12")["boot_klein"]
    assert boote[0].endswith("SailBoat.obj")   # im Bild gesehen, steht deshalb vorn


def test_ohne_art_ist_kein_status(conn):
    """Ein Titel ohne Art ist nicht zugeordnet -- das ist die Abwesenheit, kein Zustand.

    Dieselbe Unterscheidung wie `geprueft_am IS NULL` ("nie versucht") und wie
    `nicht_gefunden` bei den AIP-Blaettern. Nur so bleibt die Arbeitsliste abarbeitbar.
    """
    db.katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": "Irgendwas",
                                 "quelle": "community"}])
    db.bruegge_arten_erstbefuellen(conn)
    zeile = conn.execute(
        "SELECT art, rang, status FROM bruegge_katalog WHERE titel = 'Irgendwas'"
    ).fetchone()
    assert zeile["art"] is None and zeile["rang"] is None and zeile["status"] is None
    seite = db.bruegge_katalog_seite(conn, ohne_art=True)
    assert any(z["titel"] == "Irgendwas" for z in seite["zeilen"])


def test_art_wegnehmen_raeumt_rang_und_status_mit(conn):
    """Ohne Art sind Rang und Status gegenstandslos -- sonst behaupten sie eine Ordnung."""
    db.bruegge_arten_erstbefuellen(conn)
    db.bruegge_katalog_setzen(conn, "msfs2020", "BlackBear", art=None)
    zeile = conn.execute(
        "SELECT art, rang, status FROM bruegge_katalog WHERE titel = 'BlackBear'"
    ).fetchone()
    assert zeile["art"] is None and zeile["rang"] is None and zeile["status"] is None


def test_seite_sortiert_nur_nach_erlaubten_spalten(conn):
    """Der Spaltenname geht direkt in ORDER BY -- eine Positivliste ist Pflicht."""
    db.bruegge_arten_erstbefuellen(conn)
    s = db.bruegge_katalog_seite(conn, sortieren="titel; DROP TABLE bruegge_katalog")
    assert s["gesamt"] > 0
    assert conn.execute("SELECT COUNT(*) FROM bruegge_katalog").fetchone()[0] > 0


def test_woerterbuch_passt_in_den_antwortpuffer(conn):
    """ANTWORT_PUFFER in bruegge.cpp ist 16384, und ein Ueberlauf ist LAUTLOS.

    Deshalb gehen die Titel als Woerterbuch EINMAL je Antwort hinaus und nicht je Objekt:
    Zwanzig rote Saeulen kosten so eine Titelliste statt zwanzig. Der Test bindet die
    Groessenordnung, damit ein sorgloser Zuwachs auffaellt, bevor der Puffer reisst.
    """
    import json
    db.bruegge_arten_erstbefuellen(conn)
    for sim in ("msfs2024", "xplane12"):
        j = json.dumps(db.bruegge_titel_fuer(conn, sim), ensure_ascii=False,
                       separators=(",", ":"))
        assert len(j) < 4096, f"{sim}: {len(j)} Bytes -- ein Viertel des Puffers ist genug"


def test_jeder_titel_gehoert_zu_hoechstens_einer_art():
    """Vorher standen 13 von 91 Titeln in mehreren Arten -- der Katalog kann das nicht.

    Mit dem Wegfall der Fremdtitel und des Sammelbegriffs `rauch` loeste sich das auf. Wer
    eine Mehrfachzuordnung wieder einfuehrt, braucht eine zweite Tabelle; dieser Test sagt
    es ihm, bevor die Erstbefuellung still die letzte Zuordnung gewinnen laesst.
    """
    gesehen = {}
    for e in erstbefuellung():
        schluessel = (e["simulator"], e["titel"])
        assert schluessel not in gesehen, (
            f"{e['titel']} steht in {gesehen.get(schluessel)} UND {e['art']}")
        gesehen[schluessel] = e["art"]


def test_keine_fremdtitel_im_rauch():
    """"Wir nehmen nur unseren eigenen Rauch ... SayIntentions und Campout: alles raus!"

    Nutzerentscheidung vom 14.09.2026. Fremdtitel hier haetten zwei Folgen: ein Abo bzw. ein
    fremdes Paket als Voraussetzung, und eine Farbe, die nicht unsere ist.
    """
    for art, (_, je_sim) in ARTEN.items():
        if not art.startswith("rauch"):
            continue
        for titel in je_sim.values():
            for eintrag in titel:
                name = eintrag[0] if isinstance(eintrag, tuple) else eintrag
                assert name.startswith("FrsRauch_") or "FriesenBruegge" in name, name
