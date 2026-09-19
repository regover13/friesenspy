# -*- coding: utf-8 -*-
"""Ein Urteil je (Titel, Simulator) -- `bruegge_titel_lauf` (19.09.2026).

Vorher fuehrte `bruegge_katalog` je Titel EIN `geprueft_in`/`ergebnis`. Eine Pruefung in
MSFS 2020 haette das Urteil aus MSFS 2024 ueberschrieben, und der Unterschied zwischen den
Simulatoren ist genau das, was der Katalog wissen soll: `BlackBear` liegt im 2020er Bestand
und laeuft in 2024, waehrend 38 seiner Nachbarn es nicht tun.

Nutzerregel dazu: *"wir brauchen ein Urteil fuer MSFS2024 und eines fuer MSFS2020. Nach der
2020er Pruefung muss das neue Ergebnis in 2020 stehen und das alte bei 2024 bleiben!"*
"""
import pytest

from app import database as db


@pytest.fixture()
def conn(tmp_path):
    pfad = str(tmp_path / "t.db")
    db.init_db(pfad)
    c = db.get_connection(pfad)
    yield c
    c.close()


def _urteile(conn, titel):
    return {r["simulator"]: (r["ergebnis"], r["fehler"], r["quelle"]) for r in conn.execute(
        "SELECT * FROM bruegge_titel_lauf WHERE titel = ?", (titel,)).fetchall()}


# ---- der Kern: je Simulator ein Urteil ---------------------------------------------------

def test_ein_2020er_urteil_laesst_das_2024er_stehen(conn):
    """DER Punkt der ganzen Tabelle."""
    db.bruegge_lauf_setzen(conn, "BlackBear", "msfs2024", "steht", hoehe_ft=3.0)
    db.bruegge_lauf_setzen(conn, "BlackBear", "msfs2020", "fehlgeschlagen",
                           fehler="EXCEPTION_22")
    conn.commit()
    u = _urteile(conn, "BlackBear")
    assert u["msfs2024"][0] == "steht", "das alte Urteil aus MSFS 2024 muss bleiben"
    assert u["msfs2020"][:2] == ("fehlgeschlagen", "EXCEPTION_22")


def test_ein_neues_urteil_im_selben_simulator_ersetzt_das_alte(conn):
    db.bruegge_lauf_setzen(conn, "X", "msfs2020", "fehlgeschlagen", fehler="EXCEPTION_22")
    db.bruegge_lauf_setzen(conn, "X", "msfs2020", "steht")
    assert _urteile(conn, "X")["msfs2020"][0] == "steht"


@pytest.mark.parametrize("simulator", ["msfs", "", None, "msfs2019", "xplane11"])
def test_ohne_bekannten_simulator_wird_nichts_geschrieben(conn, simulator):
    """Eine Bruegge vor 1.14.0 sagt nur `msfs`. Wer nicht weiss, WO gemessen wurde, misst nichts."""
    assert db.bruegge_lauf_setzen(conn, "X", simulator, "steht") is False
    assert not _urteile(conn, "X")


def test_die_rueckmeldung_einer_alten_bruegge_urteilt_nicht(conn):
    assert db.bruegge_titel_fuer(conn, "msfs2024")["windrad"], "der Test braucht eine Art mit Titeln"
    n = db.bruegge_katalog_ergebnis_melden(conn, "msfs", "windrad", "fehlgeschlagen",
                                           fehler="KEIN_TITEL_GING", alle=True)
    assert n == 0
    assert conn.execute("SELECT COUNT(*) FROM bruegge_titel_lauf").fetchone()[0] == 0


def test_eine_alte_bruegge_wird_wie_msfs_2024_bedient(conn):
    """Sie bekommt weiter Titel -- sonst legte das Update einen Piloten still."""
    alt = db.bruegge_titel_fuer(conn, "msfs")
    assert alt == db.bruegge_titel_fuer(conn, "msfs2024")
    assert alt, "der Grundkatalog liefert MSFS-Titel"


# ---- Urteil von Hand -----------------------------------------------------------------------

def test_ein_urteil_von_hand_ueberlebt_die_automatik(conn):
    """Nur das Auge weiss, dass ein Seehund rosa ist -- die Bruegge meldet `steht`."""
    db.bruegge_lauf_setzen(conn, "Seehund", "msfs2020", "fehlgeschlagen",
                           fehler="rosa (Textur fehlt)", quelle="hand")
    assert db.bruegge_lauf_setzen(conn, "Seehund", "msfs2020", "steht") is False
    conn.commit()
    e, fehler, quelle = _urteile(conn, "Seehund")["msfs2020"]
    assert (e, fehler, quelle) == ("fehlgeschlagen", "rosa (Textur fehlt)", "hand")


def test_ein_urteil_von_hand_ueberschreibt_die_automatik(conn):
    db.bruegge_lauf_setzen(conn, "Rauch", "msfs2020", "steht")
    assert db.bruegge_lauf_setzen(conn, "Rauch", "msfs2020", "fehlgeschlagen",
                                  fehler="unsichtbar", quelle="hand") is True
    assert _urteile(conn, "Rauch")["msfs2020"][::2] == ("fehlgeschlagen", "hand")


def test_das_urteil_von_hand_gilt_nur_fuer_seinen_simulator(conn):
    db.bruegge_lauf_setzen(conn, "Seehund", "msfs2020", "fehlgeschlagen", quelle="hand")
    db.bruegge_lauf_setzen(conn, "Seehund", "msfs2024", "steht")
    u = _urteile(conn, "Seehund")
    assert u["msfs2024"][0] == "steht"


def test_die_rueckmeldung_kann_ein_urteil_von_hand_nicht_kippen(conn):
    """Der Weg, auf dem es im Betrieb passieren wuerde: Die Bruegge sagt `steht` zu einem
    rosa Seehund, und der Server lernt aus dieser Rueckmeldung."""
    db.bruegge_arten_erstbefuellen(conn)
    titel = db.bruegge_titel_fuer(conn, "msfs2020")["seehund_bulle"]
    assert len(titel) == 1, "der Test setzt eine Art mit genau einem Titel voraus"
    db.bruegge_lauf_setzen(conn, titel[0], "msfs2020", "fehlgeschlagen",
                           fehler="rosa", quelle="hand")
    # Der Titel geht wegen des Urteils gar nicht mehr hinaus ...
    assert "seehund_bulle" not in db.bruegge_titel_fuer(conn, "msfs2020")
    # ... und eine `steht`-Rueckmeldung findet ihn folglich nicht (kein Titel geliefert).
    assert db.bruegge_katalog_ergebnis_melden(conn, "msfs2020", "seehund_bulle",
                                              "steht") == 0
    assert _urteile(conn, titel[0])["msfs2020"][0] == "fehlgeschlagen"


# ---- Migration ---------------------------------------------------------------------------------

def _altbestand(conn, zeilen):
    """Ein Katalog, wie er vor dem 19.09.2026 aussah: Urteil an der Katalogzeile."""
    conn.execute("DELETE FROM bruegge_titel_lauf")
    for sim, titel, gepr_in, erg, am in zeilen:
        conn.execute(
            "INSERT OR REPLACE INTO bruegge_katalog (simulator, titel, quelle, geprueft_in, "
            "ergebnis, geprueft_am) VALUES (?, ?, 'bord', ?, ?, ?)",
            (sim, titel, gepr_in, erg, am))
    conn.commit()


def _migration_erneut(conn):
    """Genau die Anweisungen, die `init_db` beim Start ausfuehrt."""
    stmt = [m for m in db._BRUEGGE_MIGRATIONS if m.startswith("INSERT INTO bruegge_titel_lauf")]
    assert len(stmt) == 1
    conn.execute(stmt[0])
    conn.commit()


def test_migration_uebernimmt_das_urteil_unter_dem_pruefsimulator(conn):
    """Der Fundort ist msfs2020, geprueft wurde in msfs2024 -- der Schluessel ist der zweite."""
    _altbestand(conn, [("msfs2020", "BlackBear", "msfs2024", "steht", "2026-09-12T10:00:00Z"),
                       ("xplane12", "a.obj", "xplane12", "fehlgeschlagen",
                        "2026-09-16T10:00:00Z")])
    _migration_erneut(conn)
    assert _urteile(conn, "BlackBear") == {"msfs2024": ("steht", None, "bruegge")}
    assert _urteile(conn, "a.obj")["xplane12"][0] == "fehlgeschlagen"


def test_migration_nimmt_bei_zwei_fundorten_das_neuere_urteil(conn):
    """Derselbe Titel in BEIDEN MSFS-Bestaenden: beide Zeilen wurden in 2024 geprueft."""
    _altbestand(conn, [("msfs2020", "Doppelt", "msfs2024", "fehlgeschlagen",
                        "2026-09-12T10:00:00Z"),
                       ("msfs2024", "Doppelt", "msfs2024", "steht", "2026-09-14T10:00:00Z")])
    _migration_erneut(conn)
    assert _urteile(conn, "Doppelt")["msfs2024"][0] == "steht"
    assert "msfs2020" not in _urteile(conn, "Doppelt"), \
        "ein 2020er Urteil gab es nie -- es darf nicht erfunden werden"


def test_migration_ist_wiederholbar_und_kippt_kein_neueres_urteil(conn):
    """`init_db` fuehrt sie bei JEDEM Start aus."""
    _altbestand(conn, [("msfs2024", "T", "msfs2024", "steht", "2026-09-12T10:00:00Z")])
    _migration_erneut(conn)
    db.bruegge_lauf_setzen(conn, "T", "msfs2024", "fehlgeschlagen", fehler="EXCEPTION_22")
    conn.commit()
    _migration_erneut(conn)
    _migration_erneut(conn)
    assert _urteile(conn, "T")["msfs2024"][:2] == ("fehlgeschlagen", "EXCEPTION_22"), \
        "ein spaeteres Urteil wurde durch den Altbestand zurueckgesetzt"


def test_migration_laesst_ein_urteil_von_hand_in_ruhe(conn):
    _altbestand(conn, [("msfs2024", "T", "msfs2024", "steht", "2999-01-01T00:00:00Z")])
    db.bruegge_lauf_setzen(conn, "T", "msfs2024", "fehlgeschlagen", fehler="rosa",
                           quelle="hand")
    conn.commit()
    _migration_erneut(conn)
    assert _urteile(conn, "T")["msfs2024"][::2] == ("fehlgeschlagen", "hand")


# ---- Abfragen --------------------------------------------------------------------------------------

def test_offen_fuer_2020_meldet_was_nur_in_2024_geprueft_wurde(conn):
    """Das Gegenstueck zu `test_katalog_trennt_fundort_von_pruefort` (die fragt nach 2024):
    Ein Urteil aus MSFS 2024 erledigt den Titel fuer MSFS 2020 NICHT."""
    db.katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": "NurIn2024",
                                 "quelle": "bord"},
                                {"simulator": "msfs2024", "titel": "BeiderseitsFertig",
                                 "quelle": "bord"}])
    db.bruegge_lauf_setzen(conn, "NurIn2024", "msfs2024", "steht")
    db.bruegge_lauf_setzen(conn, "BeiderseitsFertig", "msfs2024", "steht")
    db.bruegge_lauf_setzen(conn, "BeiderseitsFertig", "msfs2020", "steht")
    conn.commit()
    offen20 = {z["titel"] for z in db.katalog_lesen(conn, offen_fuer="msfs2020", grenze=5000)}
    offen24 = {z["titel"] for z in db.katalog_lesen(conn, offen_fuer="msfs2024", grenze=5000)}
    assert "NurIn2024" in offen20
    assert "BeiderseitsFertig" not in offen20
    assert "NurIn2024" not in offen24


def test_offen_fuer_zeigt_keine_xplane_pfade_im_msfs_lauf(conn):
    offen = db.katalog_lesen(conn, offen_fuer="msfs2020", grenze=5000)
    assert offen and all(not z["titel"].startswith("Resources/") for z in offen)


def test_die_katalogseite_traegt_die_urteile_aller_drei_simulatoren(conn):
    db.katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": "Zeuge", "quelle": "bord"}])
    db.bruegge_lauf_setzen(conn, "Zeuge", "msfs2024", "steht")
    db.bruegge_lauf_setzen(conn, "Zeuge", "msfs2020", "fehlgeschlagen", fehler="rosa",
                           quelle="hand")
    conn.commit()
    z = db.bruegge_katalog_seite(conn, suche="Zeuge")["zeilen"][0]
    assert z["ergebnis_msfs2024"] == "steht"
    assert z["ergebnis_msfs2020"] == "fehlgeschlagen"
    assert z["fehler_msfs2020"] == "rosa" and z["quelle_msfs2020"] == "hand"
    assert z["ergebnis_xplane12"] is None


def test_die_katalogseite_filtert_je_pruefsimulator(conn):
    db.katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": "ZeugeA", "quelle": "bord"},
                                {"simulator": "msfs2024", "titel": "ZeugeB", "quelle": "bord"}])
    db.bruegge_lauf_setzen(conn, "ZeugeA", "msfs2024", "steht")     # nur in 2024
    db.bruegge_lauf_setzen(conn, "ZeugeB", "msfs2020", "steht")     # nur in 2020
    conn.commit()

    def titel(**kw):
        return {z["titel"] for z in db.bruegge_katalog_seite(
            conn, suche="Zeuge", ergebnis="steht", **kw)["zeilen"]}

    assert titel(geprueft_in="msfs2024") == {"ZeugeA"}
    assert titel(geprueft_in="msfs2020") == {"ZeugeB"}
    assert titel() == {"ZeugeA", "ZeugeB"}, "ohne Angabe gilt: in irgendeinem"
    nie = {z["titel"] for z in db.bruegge_katalog_seite(
        conn, suche="Zeuge", ergebnis="offen", geprueft_in="msfs2020")["zeilen"]}
    assert nie == {"ZeugeA"}


def test_die_zusammenfassung_zaehlt_je_pruefsimulator(conn):
    db.katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": "Z1", "quelle": "bord"},
                                {"simulator": "msfs2024", "titel": "Z2", "quelle": "bord"}])
    db.bruegge_lauf_setzen(conn, "Z1", "msfs2024", "steht")
    db.bruegge_lauf_setzen(conn, "Z2", "msfs2020", "fehlgeschlagen")
    conn.commit()
    z = {(d["simulator"], d["quelle"]): d for d in db.katalog_zusammenfassung(conn)}
    assert z[("msfs2024", "bord")]["geht"] >= 1
    assert z[("msfs2020", "bord")]["geht_nicht"] >= 1
    # Ein Titel, der in BEIDEN MSFS-Zeilen steht, wird einmal gezaehlt.
    assert z[("msfs2020", "bord")]["gesamt"] == z[("msfs2024", "bord")]["gesamt"]


# ---- Der Weg ueber den Admin ------------------------------------------------------------------------

def test_der_admin_kann_ein_urteil_von_hand_setzen(klient_admin):
    klient, kekse, db_pfad = klient_admin
    r = klient.post("/api/admin/bruegge/katalog/ergebnis", cookies=kekse, json={"ergebnisse": [
        {"simulator": "msfs2024", "titel": "Hand1", "geprueft_in": "msfs2020",
         "ergebnis": "fehlgeschlagen", "fehler": "rosa (Textur fehlt)", "quelle": "hand"},
        {"simulator": "msfs2024", "titel": "Auto1", "geprueft_in": "msfs2020",
         "ergebnis": "steht"},
        {"simulator": "msfs2024", "titel": "Unbekannt", "geprueft_in": "msfs", "ergebnis": "steht"},
    ]})
    assert r.status_code == 200
    assert r.json()["vermerkt"] == 2, "das Urteil ohne bekannten Simulator zaehlt nicht"
    c = db.get_connection(db_pfad)
    try:
        assert _urteile(c, "Hand1")["msfs2020"][::2] == ("fehlgeschlagen", "hand")
        assert _urteile(c, "Auto1")["msfs2020"][::2] == ("steht", "bruegge")
    finally:
        c.close()


@pytest.fixture()
def klient_admin(klient, tmp_path):
    """Der Klient der Endpunkt-Tests, dazu Admin-Kekse und der Pfad seiner Datenbank."""
    from tests.test_bruegge_endpunkt import _admin_kekse
    # `klient` legt seine Datenbank selbst an; ihr Pfad steht in den (vorbeigeschobenen)
    # Einstellungen von `app.main`.
    import app.main as main
    return klient, _admin_kekse(), main.get_settings().DB_PATH


from tests.test_bruegge_endpunkt import klient  # noqa: E402,F401  (Fixture)


# ---- Das Pruefwerkzeug (laeuft im Container, importiert aber dieselbe App) ----------------------

def _werkzeug():
    import importlib.util
    import pathlib
    pfad = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "katalog_durchpruefen.py"
    spez = importlib.util.spec_from_file_location("katalog_durchpruefen_t", pfad)
    modul = importlib.util.module_from_spec(spez)
    spez.loader.exec_module(modul)
    return modul


def test_das_werkzeug_prueft_was_in_diesem_simulator_offen_ist(conn):
    """Ein Urteil aus MSFS 2024 erledigt den Titel fuer MSFS 2020 NICHT -- das ist der ganze Sinn
    des ersten 2020er Laufs. Ein Urteil von Hand schliesst ihn dagegen aus."""
    w = _werkzeug()
    db.katalog_eintragen(conn, [
        {"simulator": "msfs2024", "titel": "WT_Nur24", "quelle": "bord"},
        {"simulator": "msfs2024", "titel": "WT_Fertig", "quelle": "bord"},
        {"simulator": "msfs2024", "titel": "WT_Hand", "quelle": "bord"},
        {"simulator": "msfs2020", "titel": "WT_Zweimal", "quelle": "bord"},
        {"simulator": "msfs2024", "titel": "WT_Zweimal", "quelle": "bord"},
    ])
    db.bruegge_lauf_setzen(conn, "WT_Nur24", "msfs2024", "steht")
    db.bruegge_lauf_setzen(conn, "WT_Fertig", "msfs2020", "steht")
    db.bruegge_lauf_setzen(conn, "WT_Hand", "msfs2020", "fehlgeschlagen", quelle="hand")
    conn.commit()

    liste = w._offene_titel(conn, "msfs2020", False, False)
    offen = {t for _, t in liste}
    assert "WT_Nur24" in offen, "nur in 2024 geprueft -- fuer 2020 offen"
    assert "WT_Fertig" not in offen
    assert "WT_Hand" not in offen, "ein Urteil von Hand ist tabu"
    assert [t for _, t in liste].count("WT_Zweimal") == 1, \
        "ein Titel aus beiden MSFS-Bestaenden wird einmal geprueft"
    assert all(not t.startswith("Resources/") for t in offen), "keine X-Plane-Pfade in MSFS"

    # Mit `--alle` kommen die schon Geprueften wieder dran, nie aber die von Hand.
    alle = {t for _, t in w._offene_titel(conn, "msfs2020", True, False)}
    assert "WT_Fertig" in alle and "WT_Hand" not in alle


def test_das_werkzeug_kann_sich_auf_zugeordnete_titel_beschraenken(conn):
    """Der erste Lauf in einem neuen Simulator soll das wissen, was an Piloten hinausgeht --
    nicht mehrere Tausend Titel, die keine Art tragen."""
    w = _werkzeug()
    db.katalog_eintragen(conn, [{"simulator": "msfs2024", "titel": "WT_OhneArt",
                                 "quelle": "bord"}])
    conn.commit()
    alle = w._offene_titel(conn, "msfs2020", False, False)
    zugeordnet = w._offene_titel(conn, "msfs2020", False, True)
    assert 0 < len(zugeordnet) < len(alle)
    tragen = {r[0] for r in conn.execute(
        "SELECT titel FROM bruegge_katalog WHERE art IS NOT NULL").fetchall()}
    assert all(t in tragen for _, t in zugeordnet)
    assert "WT_OhneArt" not in {t for _, t in zugeordnet}
