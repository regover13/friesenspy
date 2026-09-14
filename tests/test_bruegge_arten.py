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


def _antwort_puffer() -> int:
    """`ANTWORT_PUFFER`, GELESEN aus den Bruegge-Quellen statt hier abgeschrieben.

    ⚠⚠ ABGESCHRIEBEN WAR ER FALSCH, und das ist der Grund fuer diese Funktion. Hier stand
    bis zum 15.09.2026 „ANTWORT_PUFFER in bruegge.cpp ist 16384"; im Quelltext stehen
    **49152**, in beiden Bruegge-Fassungen. Die Zahl war irgendwann verdreifacht worden, der
    Test zog nicht nach -- und band damit eine Grenze, die es nicht gab.

    Eine Zahl an zwei Orten laeuft auseinander. Jetzt gibt es nur noch einen.
    """
    from pathlib import Path
    import re
    wurzel = Path(__file__).resolve().parents[1] / "friesenbruegge"
    werte = {}
    for datei in (wurzel / "msfs" / "bruegge.cpp", wurzel / "xplane" / "netz.h"):
        m = re.search(r"#define\s+ANTWORT_PUFFER\s+(\d+)", datei.read_text(encoding="utf-8",
                                                                           errors="replace"))
        assert m, f"ANTWORT_PUFFER nicht gefunden in {datei.name}"
        werte[datei.name] = int(m.group(1))
    assert len(set(werte.values())) == 1, \
        f"die beiden Bruegge-Fassungen haben verschiedene Puffer: {werte}"
    return next(iter(werte.values()))


def test_woerterbuch_passt_in_den_antwortpuffer(conn):
    """Die Titelliste muss in `ANTWORT_PUFFER` passen -- mit Luft nach oben.

    Deshalb gehen die Titel als Woerterbuch EINMAL je Antwort hinaus und nicht je Objekt:
    Zwanzig rote Saeulen kosten so eine Titelliste statt zwanzig.

    ⚠ **X-Plane ist der teure Fall, um das Dreifache.** Dort ist der Bezeichner ein
    Dateipfad, und `Resources/default scenery/` allein wiederholt sich in jeder Zeile --
    bei 73 Titeln sind das 1,6 kB reine Wiederholung. MSFS kommt mit rund 66 Bytes je Art
    aus, X-Plane braucht 200.

    Die Grenze liegt bei der HAELFTE des Puffers, und das ist kein runder Daumenwert: Die
    andere Haelfte gehoert der `soll`-Liste, die in derselben Antwort steht und mit der Zahl
    gesetzter Objekte waechst (SOLL_MAX = 200). Reisst der Test, ist die naechste Massnahme
    NICHT, ihn hochzusetzen -- sondern den gemeinsamen Pfadstamm einmal statt 73-mal zu
    schicken. Das spart auf einen Schlag ein Viertel.
    """
    import json
    puffer = _antwort_puffer()
    db.bruegge_arten_erstbefuellen(conn)
    for sim in ("msfs2024", "xplane12"):
        j = json.dumps(db.bruegge_titel_fuer(conn, sim), ensure_ascii=False,
                       separators=(",", ":"))
        assert len(j) < puffer // 2, (
            f"{sim}: {len(j)} Bytes von {puffer} -- mehr als die Haelfte des Puffers. "
            f"Den Pfadstamm kuerzen, nicht die Grenze heben.")


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


def test_wer_nach_zuordnung_filtert_bekommt_auch_die_seitenzahl_dazu(conn):
    """Filtern und Zählen gehören zusammen — sonst lügt die Seitenzahl.

    Der erste Entwurf filterte „hat eine Art" nachträglich im Browser: Der Server schickte
    20 Zeilen je Seite, das JavaScript warf fast alle weg, und die Seitenzahl zählte den
    ungefilterten Bestand. Im Screenshot vom 14.09.2026 stand „Seite 18 / 71 · 1419 Titel"
    über ZWEI sichtbaren Zeilen — man blätterte durch 71 Seiten für eine Handvoll Treffer.

    Von 2953 Titeln tragen 87 eine Art. Wer danach filtert, sucht die Nadel; dann darf die
    Seitenrechnung nicht den Heuhaufen zählen.
    """
    db.katalog_eintragen(conn, [
        {"simulator": "msfs2024", "titel": f"ohne-art-{i}", "quelle": "community"}
        for i in range(50)
    ])
    conn.commit()

    mit = db.bruegge_katalog_seite(conn, mit_art=True, je_seite=20)
    ohne = db.bruegge_katalog_seite(conn, ohne_art=True, je_seite=20)
    alle = db.bruegge_katalog_seite(conn, je_seite=20)

    # Jede gelieferte Zeile trägt auch wirklich eine Art ...
    assert mit["zeilen"] and all(z["art"] for z in mit["zeilen"])
    assert ohne["zeilen"] and all(z["art"] is None for z in ohne["zeilen"])
    # ... und die Summen gehen auf. Ginge der Filter erst im Browser, stünde hier bei
    # `mit["gesamt"]` die Gesamtzahl.
    assert mit["gesamt"] + ohne["gesamt"] == alle["gesamt"]
    assert mit["gesamt"] < alle["gesamt"], "der Filter muss etwas wegnehmen"
    assert mit["seiten"] == max(1, (mit["gesamt"] + 19) // 20)


def test_der_admin_filtert_nicht_selbst_nach(conn):
    """Die Oberfläche darf keine geladene Seite nachträglich ausdünnen.

    Sie bindet damit die ABWESENHEIT des alten Fehlers: Wer wieder im Browser filtert, macht
    die Seitenzahl zur Lüge — und das fällt erst auf, wenn jemand 71 Seiten durchblättert.
    """
    from pathlib import Path
    s = (Path(__file__).resolve().parents[1] / "app" / "static" / "admin.html").read_text(
        encoding="utf-8")
    block = s[s.index("function bgTitelZeichnen"):s.index("function bgTitelZeile")]
    assert ".filter(" not in block, "bgTitelZeichnen zeichnet, es filtert nicht"
    assert "mit_art" in s, '„hat eine Art" muss als Server-Filter mitgehen'


def test_die_suche_findet_auch_ueber_die_art(conn):
    """Wer `windsack` sucht, kennt das Modell nicht — und soll es auch nicht müssen.

    Das MSFS-Modell heißt `Windsock_05`, das X-Plane-Modell
    `…/landscape/windsock_orange.obj`. Die Art ist die Bedeutung, das Modell nur ihr Träger;
    eine Suche, die nur Dateinamen kennt, verlangt Auswendiglernen (14.09.2026 gemeldet).
    """
    treffer = db.bruegge_katalog_seite(conn, suche="windsack", je_seite=50)
    assert treffer["gesamt"] > 0
    assert all(z["art"] == "windsack" for z in treffer["zeilen"])
    # ... und die Titelsuche bleibt, wie sie war.
    assert db.bruegge_katalog_seite(conn, suche="Windsock", je_seite=50)["gesamt"] > 0


# ---------------------------------------------------------------------------------------
# Beide Simulatoren muessen liefern koennen -- stehende Regel (Nutzer, 14.09.2026)
# ---------------------------------------------------------------------------------------
#
# ⚠ Diese Tests legen sich ihre EIGENE Art an, statt eine echte zu benutzen. Der erste
# Anlauf nahm `robbe`, und schon einen Tag spaeter zerfiel die in drei Arten -- vier Tests
# wurden rot, ohne dass an der Regel etwas falsch war. Der Docstring dieser Datei sagt es
# oben: gebunden werden die REGELN, nicht der Inhalt.


@pytest.fixture()
def probe(conn):
    """Eine kuenstliche Art mit je zwei Titeln -- unabhaengig vom echten Katalog."""
    db.bruegge_arten_erstbefuellen(conn)
    conn.execute("INSERT INTO bruegge_art (art, bedeutung, status, angelegt_am) "
                 "VALUES ('probe', 'Probeart fuer die Tests', 'aktiv', datetime('now'))")
    for sim, titel in (("msfs2024", ("ProbeM1", "ProbeM2")),
                       ("xplane12", ("Resources/probe/x1.obj", "Resources/probe/x2.obj"))):
        for rang, t in enumerate(titel, 1):
            conn.execute(
                "INSERT INTO bruegge_katalog (simulator, titel, quelle, art, rang, status) "
                "VALUES (?, ?, 'bord', 'probe', ?, 'aktiv')", (sim, t, rang))
    conn.commit()
    return conn
#
# "sollten innerhalb einer Art alle Entsprechungen eines Simulators nicht gesetzt werden
# koennen, wird die Art deaktiviert. Ich muss sichergehen koennen, dass beide SIM immer
# irgendwas aus der Art anzeigen koennen!"


def test_einseitige_art_geht_an_KEINE_bruegge(probe):
    """Der Kern der Regel -- und der Grund, warum sie nicht im Admin allein stehen darf.

    Eine Art, deren X-Plane-Titel alle ausfallen, darf auch die MSFS-Bruegge nicht mehr
    bekommen. Sonst zeigt eine Station zwei Dritteln der Gruppe etwas und dem letzten
    Drittel nichts -- und eine Zaehlaufgabe, bei der nicht alle dasselbe sehen, ist keine.
    """
    assert "probe" in db.bruegge_titel_fuer(probe, "msfs2024")
    assert "probe" in db.bruegge_titel_fuer(probe, "xplane12")

    # Alle X-Plane-Robben fallen aus -- die MSFS-Seite bleibt vollstaendig.
    probe.execute("UPDATE bruegge_katalog SET status = 'aus' "
                 "WHERE art = 'probe' AND simulator = 'xplane12'")
    probe.commit()

    assert "probe" not in db.bruegge_titel_fuer(probe, "xplane12")
    assert "probe" not in db.bruegge_titel_fuer(probe, "msfs2024"), \
        "einseitige Art darf auch der Simulator nicht bekommen, der sie noch koennte"


def test_ein_einziger_titel_je_seite_genuegt(probe):
    """Die Regel verlangt EINEN Titel je Simulator, nicht Gleichstand.

    Ohne das waere sie unbrauchbar: MSFS bringt zu `tier_gross` sechs Titel mit, X-Plane
    zwei. Gefordert ist, dass beide etwas zeigen koennen -- nicht, dass sie gleich viel
    mitbringen.

    ⚠ Dieser Test wird ohne den Fix NICHT rot, und das ist Absicht -- er bindet die
    GEGENRICHTUNG. Rot wird er, wenn jemand die Regel verschaerft und Gleichstand verlangt.
    Die beiden Nachbarn darueber und darunter sind die eigentlichen Regressionstests.
    """
    probe.execute("UPDATE bruegge_katalog SET status = 'aus' "
                 "WHERE art = 'probe' AND simulator = 'xplane12' "
                 "AND titel NOT LIKE '%x1.obj'")
    probe.commit()
    xp = db.bruegge_titel_fuer(probe, "xplane12")
    assert len(xp["probe"]) == 1
    assert "probe" in db.bruegge_titel_fuer(probe, "msfs2024")


def test_die_regel_heilt_sich_selbst(probe):
    """Kommt ein Titel zurueck, ist die Art sofort wieder da -- ohne Handgriff.

    Das ist der Grund, warum die Regel BERECHNET wird und nicht in `bruegge_art.status`
    gepflegt. Eine gepflegte Liste wuesste vom Ausfall nichts und von der Rueckkehr erst
    recht nicht.
    """
    probe.execute("UPDATE bruegge_katalog SET status = 'aus' "
                 "WHERE art = 'probe' AND simulator = 'xplane12'")
    probe.commit()
    assert "probe" not in db.bruegge_titel_fuer(probe, "msfs2024")

    probe.execute("UPDATE bruegge_katalog SET status = 'aktiv' "
                 "WHERE art = 'probe' AND simulator = 'xplane12' "
                 "AND titel LIKE '%x1.obj'")
    probe.commit()
    assert "probe" in db.bruegge_titel_fuer(probe, "msfs2024")
    assert "probe" in db.bruegge_titel_fuer(probe, "xplane12")


def test_admin_sagt_WARUM_eine_art_gesperrt_ist(probe):
    """Ohne Begruendung sucht jemand den Fehler bei sich.

    Der Admin zeigt drei verschiedene Gruende -- abgeschaltet, kein Titel, einseitig -- und
    sie sind nicht dasselbe: Der erste ist eine Entscheidung, der zweite eine Luecke, der
    dritte ein Ausfall im Betrieb.
    """
    probe.execute("UPDATE bruegge_katalog SET status = 'aus' "
                 "WHERE art = 'probe' AND simulator = 'xplane12'")
    probe.commit()
    u = {d["art"]: d for d in db.bruegge_arten_uebersicht(probe)}
    assert u["probe"]["anforderbar"] is False
    assert u["probe"]["beidseitig"] is False
    assert "X-Plane" in u["probe"]["gesperrt_weil"]
    # Eine gesunde Art traegt keine Begruendung.
    assert u["windsack"]["anforderbar"] is True
    assert u["windsack"]["gesperrt_weil"] is None


def test_die_regel_gibt_nichts_frei_was_der_nutzer_abgeschaltet_hat(probe):
    """Sie kann sperren, nie freigeben -- `bruegge_art.status` bleibt das letzte Wort."""
    db.bruegge_art_setzen(probe, "probe", status="aus")
    probe.commit()
    u = {d["art"]: d for d in db.bruegge_arten_uebersicht(probe)}
    assert u["probe"]["beidseitig"] is True       # die Titel stehen ja
    assert u["probe"]["anforderbar"] is False     # trotzdem gesperrt
    assert u["probe"]["gesperrt_weil"] == "vom Nutzer abgeschaltet"
