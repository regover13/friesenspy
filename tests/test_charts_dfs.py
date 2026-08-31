"""Eine Tabelle fuer beide Kartentypen -- Migration und Zugriff.

Bis zum 31.08.2026 lagen Sichtflugkarten in ``aip_charts`` und Flugplatz-/Rollkarten in
``aip_ground_charts``: zwei Tabellen, zwei Oberflaechen, zwei Automatiken. Beide Automatiken
sind zurueckgebaut (Nutzerentscheidung 31.08.2026), die Passungen bleiben.

Spec: docs/superpowers/specs/2026-08-31-aip-charts-dfs-design.md
"""
from __future__ import annotations

import sqlite3

import pytest

from app.database import (
    get_chart_dfs,
    get_charts_dfs,
    get_connection,
    init_db,
    migration_charts_dfs,
    upsert_chart_dfs,
)

# Eine vollstaendige Lage, wie sie aus einer Handpassung faellt.
LAGE = dict(nord=51.32, sued=51.25, west=6.71, ost=6.82,
            feld_nord=51.31, feld_sued=51.26, feld_west=6.72, feld_ost=6.81,
            drehung=322.8, mps=1.69)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)                       # nimmt einen PFAD, keine Verbindung
    c = get_connection(db)
    yield c
    c.close()


def _alt_sichtflug(conn, icao="EDDL", quelle="hand", status="gepasst"):
    """Eine Zeile im ALTEN Schema anlegen, so wie sie heute in aip_charts steht.

    ``rahmen_px`` traegt echte Werte, weil die Migration daraus die Klickpunkte gewinnt --
    die Zahlen sind der Bestandswert von EDWE. ``seite_url`` ist leer, weil sie es im
    Bestand in ALLEN 446 Zeilen ist (gemessen 31.08.2026).
    """
    conn.execute(
        """INSERT INTO aip_charts (icao, bild_hash, nord, sued, west, ost,
                                   feld_nord, feld_sued, feld_west, feld_ost,
                                   rahmen_px, tick_px_lat, tick_px_lon,
                                   quelle, airac, status, seite_url, geprueft_am)
           VALUES (?, 'a', 51.32, 51.25, 6.71, 6.82, 51.31, 51.26, 6.72, 6.81,
                   '85.0,238.0,1147.0,818.0', 0, 0, ?, '2026AUG20', ?, '',
                   '2026-08-30T12:00:00Z')""",
        (icao, quelle, status))


def _alt_ground(conn, icao="EDDL", sorte="rollkarte", status="gepasst"):
    conn.execute(
        """INSERT INTO aip_ground_charts (icao, sorte, seite_url, quell_hash, bild_hash,
                                          nord, sued, west, ost,
                                          feld_nord, feld_sued, feld_west, feld_ost,
                                          drehung, mps, rest_max, bahnen,
                                          quelle, airac, status, geprueft_am)
           VALUES (?, ?, 'https://x/g.html', 'q', 'b', 51.30, 51.27, 6.74, 6.80,
                   51.295, 51.275, 6.745, 6.795, 353.4, 2.58, 0, 0,
                   'hand', '2026AUG20', ?, '2026-08-31T09:00:00Z')""",
        (icao, sorte, status))


# --------------------------------------------------------------------------- Migration
def test_beide_kartentypen_desselben_platzes_ueberleben(conn):
    """Alle 110 Ground-ICAOs haben auch eine Sichtflugkarte -- gemessen am 31.08.2026.

    Mit einem Schluessel auf icao allein kollidieren genau diese 110 Zeilen.
    """
    _alt_sichtflug(conn, "EDDL")
    _alt_ground(conn, "EDDL", "rollkarte")
    conn.commit()
    assert migration_charts_dfs(conn) == 2
    sorten = {k["sorte"] for k in get_charts_dfs(conn) if k["icao"] == "EDDL"}
    assert sorten == {"sichtflug", "rollkarte"}


def test_status_wird_richtig_abgebildet(conn):
    """hand -> gepasst, auto -> auto, ungepasst -> offen. Und die Ground-Passungen fallen
    auf auto zurueck: Sie sind von Claude gesetzt, nicht vom Nutzer geprueft."""
    _alt_sichtflug(conn, "EDAA", quelle="hand")
    _alt_sichtflug(conn, "EDAB", quelle="auto")
    _alt_ground(conn, "EDAC", "flugplatzkarte", "gepasst")
    _alt_ground(conn, "EDAD", "rollkarte", "ungepasst")
    conn.commit()
    migration_charts_dfs(conn)
    status = {(k["icao"], k["sorte"]): k["status"] for k in get_charts_dfs(conn)}
    assert status[("EDAA", "sichtflug")] == "gepasst"
    assert status[("EDAB", "sichtflug")] == "auto"
    assert status[("EDAC", "flugplatzkarte")] == "auto"
    assert status[("EDAD", "rollkarte")] == "offen"


def test_verwaist_bleibt_verwaist(conn):
    """Der Link ist verschwunden, die Passung nicht. Sie kehrt zurueck, sobald der Link
    wieder auftaucht -- ein AIRAC-Wechsel benennt Kapitelseiten um. Wer sie hier auf
    'gepasst' hebt, verliert die Information."""
    _alt_sichtflug(conn, "EDDL", quelle="hand", status="verwaist")
    conn.commit()
    migration_charts_dfs(conn)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["status"] == "verwaist"


def test_migration_laeuft_genau_einmal(conn):
    """init_db laeuft bei JEDEM Containerstart. Eine Migration, die dabei zweimal
    ausgefuehrt wird, wuerde Nutzerarbeit ueberschreiben -- genau der Fehler, gegen den die
    ganze Vorgaengerspec geschrieben wurde."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    assert migration_charts_dfs(conn) == 1
    assert migration_charts_dfs(conn) == 0


def test_nach_der_migration_geaenderte_zeilen_bleiben_geaendert(conn):
    """Der eigentliche Schaden waere nicht das Doppeln, sondern das Zuruecksetzen.

    Zweite Sicherung neben dem Merker: ON CONFLICT DO NOTHING. Selbst wenn jemand den
    Merker loescht, ueberschreibt der erneute Lauf keine bearbeitete Zeile.
    """
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst",
                     hand_ueberschreiben=True, **{**LAGE, "drehung": 12.5})
    conn.execute("DELETE FROM job_laeufe WHERE name = 'migration_charts_dfs'")
    migration_charts_dfs(conn)                     # zweiter Lauf, Merker fort
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["drehung"] == pytest.approx(12.5)


def test_die_alten_tabellen_bleiben_stehen(conn):
    """Damit die Migration ohne Datenverlust wiederholbar ist, solange der neue Stand nicht
    geprueft wurde."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    assert conn.execute("SELECT COUNT(*) FROM aip_charts").fetchone()[0] == 1


def test_die_migration_laeuft_auch_ohne_row_factory(conn, tmp_path):
    """init_db oeffnet seine Verbindung mit sqlite3.connect() -- OHNE row_factory. Dort
    liefert eine Abfrage Tupel, und ein Namenszugriff wie r["icao"] wirft TypeError.

    Genau daran ist v8.14.0 schon einmal gescheitert (Kommentar in app/database.py bei der
    transport_cargo-Migration). Die Migration muss sich ihren eigenen Cursor mit
    row_factory holen, statt sich auf die Verbindung des Aufrufers zu verlassen.
    """
    _alt_sichtflug(conn, "EDDL")
    _alt_ground(conn, "EDDL", "rollkarte")
    conn.commit()
    conn.close()

    nackt = sqlite3.connect(str(tmp_path / "t.db"))   # kein row_factory
    try:
        assert migration_charts_dfs(nackt) == 2
    finally:
        nackt.close()


# --------------------------------------------------------------------- Was mitwandert
def test_die_klickpunkte_der_sichtflugkarten_wandern_mit(conn):
    """rahmen_px IST bei den Sichtflugkarten das Klickprotokoll, keine Innerei.

    Gemessen am Bestand: EDWE traegt rahmen_px = '85.0,238.0,1147.0,818.0', und
    feld_nord/feld_west bzw. feld_sued/feld_ost sind genau die Koordinaten dieser beiden
    Ecken. Alle 446 Zeilen sind wohlgeformt.

    Wer die Spalte als Automatikrest verwirft, zerstoert die Eingabe, die er aufheben will.
    """
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    k = get_chart_dfs(conn, "EDDL", "sichtflug")
    assert (k["p1_x"], k["p1_y"]) == pytest.approx((85.0, 238.0))
    assert (k["p2_x"], k["p2_y"]) == pytest.approx((1147.0, 818.0))
    assert k["p1_lat"] == pytest.approx(51.31)      # feld_nord
    assert k["p1_lon"] == pytest.approx(6.72)       # feld_west
    assert k["p2_lat"] == pytest.approx(51.26)      # feld_sued
    assert k["p2_lon"] == pytest.approx(6.81)       # feld_ost


def test_kaputtes_rahmen_px_bricht_die_migration_nicht(conn):
    """Im Bestand kommt das nicht vor -- aber eine Migration, die an einer einzigen
    unlesbaren Zeile abbricht, laesst die anderen 445 liegen."""
    conn.execute(
        """INSERT INTO aip_charts (icao, bild_hash, nord, sued, west, ost,
                                   feld_nord, feld_sued, feld_west, feld_ost,
                                   rahmen_px, tick_px_lat, tick_px_lon,
                                   quelle, airac, status, seite_url, geprueft_am)
           VALUES ('EDXX', 'a', 51.32, 51.25, 6.71, 6.82, 51.31, 51.26, 6.72, 6.81,
                   'kaputt', 0, 0, 'hand', '2026AUG20', 'gepasst', '', NULL)""")
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    assert migration_charts_dfs(conn) == 2
    assert get_chart_dfs(conn, "EDXX", "sichtflug")["p1_x"] is None
    assert get_chart_dfs(conn, "EDXX", "sichtflug")["status"] == "gepasst"


def test_sichtflugkarten_starten_ohne_gesehenen_hash(conn):
    """Einen Startwert, den wir nicht haben, traegt man nicht ein.

    Naheliegend waere bild_hash -- fuer 439 der 446 Zeilen sogar richtig, denn
    genordet_rechnen gibt die DFS-Bytes unveraendert zurueck, wenn nicht gedreht wird
    (app/aip_charts.py, letzte Zeile: 'return roh, ...'), ohne Pillow-Re-Encode. Fuer die
    SIEBEN quer gedruckten Blaetter aber nicht: dort ist bild_hash der Hash des gedrehten,
    neu kodierten Blatts (app/main.py:4671) -- ein Wert, den die DFS nie geliefert hat.

    Leer heisst 'noch nie gesehen': Der erste Joblauf traegt den echten Rohbytes-Hash ein
    und meldet nichts. Die Regel haengt an einem leeren Feld statt an einem Vergleich mit
    dem AIRAC der Migration -- was in sechs Monaten niemand mehr versteht, fliegt beim
    naechsten Umbau heraus.
    """
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    k = get_chart_dfs(conn, "EDDL", "sichtflug")
    assert k["gesehener_hash"] == ""
    assert k["bild_hash"] == "a"          # der bleibt -- er ist der Cache-Schluessel


def test_die_ground_zeilen_behalten_ihren_hash(conn):
    """aip_ground_charts.quell_hash IST der echte Rohbytes-Hash --
    scripts/ground_chart_bestand.py:153 hasht ``roh``, vor jedem Drehen. Alle 110 Zeilen
    tragen 64 Zeichen (gemessen 31.08.2026 an der Produktionsdatenbank).

    Sie wegzuwerfen kostete nichts, brachte aber auch nichts: So haben diese 110 Karten ab
    dem ersten Tag eine gueltige Aenderungserkennung.
    """
    _alt_ground(conn, "EDDL", "rollkarte")
    conn.commit()
    migration_charts_dfs(conn)
    assert get_chart_dfs(conn, "EDDL", "rollkarte")["gesehener_hash"] == "q"


def test_die_seitennummer_bleibt_leer(conn):
    """seite_url ist im Bestand in ALLEN 446 Zeilen leer -- es gibt nichts zu uebernehmen.
    Die Nummer traegt der erste Joblauf nach.

    Und sie waere ohnehin unbrauchbar: seite_url enthaelt den AIRAC
    (https://aip.dfs.de/BasicVFR/2026AUG20/pages/8E6E....html) und liefert nach dem
    naechsten Zyklus 404.
    """
    _alt_sichtflug(conn, "EDDL")
    _alt_ground(conn, "EDDL", "rollkarte")
    conn.commit()
    migration_charts_dfs(conn)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["seite_nr"] is None
    assert get_chart_dfs(conn, "EDDL", "rollkarte")["seite_nr"] is None


def test_die_urspruenglichen_spalten_wandern_nicht_mit(conn):
    """tick_px_*, rest_max und bahnen waren Innereien der Passungsrechnung -- rahmen_px
    ausdruecklich NICHT, dessen Inhalt wandert (s. o.). seite_url faellt, weil sie den
    AIRAC enthaelt und den naechsten Zyklus nicht ueberlebt."""
    _alt_sichtflug(conn, "EDDL")
    conn.commit()
    migration_charts_dfs(conn)
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(aip_charts_dfs)")}
    assert not spalten & {"rahmen_px", "tick_px_lat", "tick_px_lon", "rest_max", "bahnen",
                          "quelle", "seite_url", "quell_hash"}
    assert {"p1_x", "p2_lon", "seite_nr", "status_vorher", "gesehener_hash"} <= spalten


def test_eine_leere_datenbank_verbraucht_die_migration_nicht(tmp_path):
    """init_db laeuft auf einer frischen Datenbank, BEVOR irgendetwas in den alten Tabellen
    steht -- und rief die Migration schon mit.

    Wuerde sie dabei den Merker setzen, waere sie verbraucht, ohne je gearbeitet zu haben:
    Ein spaeter eingespielter Bestand blieb dann liegen. Der Merker wird deshalb nur bei
    tatsaechlich uebernommenen Zeilen gesetzt; ist nichts zu tun, kostet ein erneuter Lauf
    zwei Abfragen auf leere Tabellen.

    Gefunden beim Anschluss an init_db (Task 1, 31.08.2026) -- vorher gruen, danach zehn
    Fehlschlaege.
    """
    db = str(tmp_path / "leer.db")
    init_db(db)                              # ruft migration_charts_dfs auf leeren Tabellen
    c = get_connection(db)
    try:
        assert c.execute(
            "SELECT COUNT(*) FROM job_laeufe WHERE name = 'migration_charts_dfs'"
        ).fetchone()[0] == 0
        _alt_sichtflug(c, "EDDL")            # Bestand kommt erst jetzt
        c.commit()
        assert migration_charts_dfs(c) == 1
    finally:
        c.close()


# ------------------------------------------------------------------- Task 2: Zugriff, Sperre
def test_status_muss_bekannt_sein(conn):
    """Ein Tippfehler im Status waere sonst eine Zeile, die kein Filter je findet."""
    with pytest.raises(ValueError):
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="halbgepasst", **LAGE)


def test_sorte_muss_bekannt_sein(conn):
    with pytest.raises(ValueError):
        upsert_chart_dfs(conn, "EDDL", "anflugkarte", status="offen", **LAGE)


def test_unbekannte_felder_werden_abgewiesen(conn):
    """Ein Tippfehler im Feldnamen fiele sonst still unter den Tisch -- der Aufrufer
    glaubte zu schreiben, und nichts geschieht."""
    with pytest.raises(ValueError):
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="offen", drehnung=1.0)


def test_filter_nach_status_und_sorte(conn):
    from app.database import get_charts_dfs

    upsert_chart_dfs(conn, "EDAA", "sichtflug", status="gepasst", **LAGE)
    upsert_chart_dfs(conn, "EDAB", "sichtflug", status="offen", **LAGE)
    upsert_chart_dfs(conn, "EDAC", "rollkarte", status="offen", **LAGE)
    assert len(get_charts_dfs(conn, status=["offen"])) == 2
    assert len(get_charts_dfs(conn, status=["offen"], sorte=["rollkarte"])) == 1
    assert len(get_charts_dfs(conn, status=["gepasst", "offen"])) == 3
    assert len(get_charts_dfs(conn)) == 3


def test_eine_gepasste_karte_wird_nicht_stillschweigend_ueberschrieben(conn):
    """Die Sperre bleibt -- nur ihr Praedikat wechselt von quelle='hand' auf
    status='gepasst'.

    Der Rueckbau nimmt zwar dem JOB die Faehigkeit, eine Passung zu rechnen. Der
    Seitenwaehler bleibt aber und schreibt bei gescheiterter Passung alle Lagefelder auf 0
    (app/main.py:4694). Nach dem Rueckbau ist ``passung`` dort IMMER None -- der nullende
    Zweig waere der einzige. Genau das ist am 25.08.2026 schon einmal passiert: EDAZ stand
    danach auf 0/0/0/0.
    """
    from app.database import PassungGesperrt

    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
    with pytest.raises(PassungGesperrt):
        upsert_chart_dfs(conn, "EDDL", "sichtflug", status="auto",
                         **{**LAGE, "nord": 0, "sued": 0, "west": 0, "ost": 0})


def test_mit_ausdruecklicher_ansage_geht_es_doch(conn):
    """Der Nutzer selbst muss eine gepasste Karte neu passen koennen -- die Sperre richtet
    sich gegen stillschweigendes Ueberschreiben, nicht gegen ihn."""
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst",
                     **{**LAGE, "drehung": 7.5}, hand_ueberschreiben=True)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["drehung"] == pytest.approx(7.5)


def test_der_status_allein_darf_ohne_ansage_wechseln(conn):
    """Der Job setzt status='pruefen' und gesehener_hash auf einer gepassten Karte -- er
    ruehrt die Lage nicht an. Wuerde die Sperre auch das abweisen, koennte er nichts
    melden."""
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="gepasst", **LAGE)
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="pruefen",
                     status_vorher="gepasst", gesehener_hash="n" * 64)
    k = get_chart_dfs(conn, "EDDL", "sichtflug")
    assert k["status"] == "pruefen" and k["status_vorher"] == "gepasst"
    assert k["nord"] == pytest.approx(LAGE["nord"])


def test_die_sperre_greift_nicht_auf_einer_neuen_zeile(conn):
    """Es gibt noch nichts zu ueberschreiben -- eine ganz neue Karte darf mit gesetzter
    Lage direkt auf 'gepasst' gehen, ohne hand_ueberschreiben."""
    upsert_chart_dfs(conn, "EDXX", "sichtflug", status="gepasst", **LAGE)
    assert get_chart_dfs(conn, "EDXX", "sichtflug")["status"] == "gepasst"


def test_geprueft_am_wird_bei_jedem_schreiben_gesetzt(conn):
    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="offen", **LAGE)
    assert get_chart_dfs(conn, "EDDL", "sichtflug")["geprueft_am"]


def test_icao_wird_normalisiert(conn):
    upsert_chart_dfs(conn, "eddl", "sichtflug", status="offen", **LAGE)
    assert get_chart_dfs(conn, "EDDL", "sichtflug") is not None


def test_delete_chart_dfs_entfernt_genau_eine_sorte(conn):
    """Der Schluessel ist (icao, sorte) -- ein DELETE darf die andere Sorte desselben
    Platzes nicht mitreissen."""
    from app.database import delete_chart_dfs

    upsert_chart_dfs(conn, "EDDL", "sichtflug", status="offen", **LAGE)
    upsert_chart_dfs(conn, "EDDL", "rollkarte", status="offen", **LAGE)
    assert delete_chart_dfs(conn, "EDDL", "sichtflug") == 1
    assert get_chart_dfs(conn, "EDDL", "sichtflug") is None
    assert get_chart_dfs(conn, "EDDL", "rollkarte") is not None
