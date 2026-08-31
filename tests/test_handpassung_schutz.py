"""Eine von Hand gesetzte Passung darf nie automatisch ueberschrieben werden.

Festlegung des Nutzers vom 30.08.2026:

    "Eine manuell durchgefuehrte Korrektur darf nicht einfach ueberschrieben werden! Wenn es
    eine neue Version gibt, kann diese zur Pruefung angezeigt werden. Aber keinesfalls
    erneut verzerrt werden!"

Es geht um 171 handgepasste Sichtflugkarten. Sie sind bis heute nur deshalb heil, weil der
woechentliche Auffrischlauf seit seiner Einfuehrung kein einziges Mal gelaufen ist.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md, Abschnitt 7
Plan: docs/superpowers/plans/2026-08-30-handpassung-schutz.md
"""
from __future__ import annotations

import collections

import pytest

from app.database import (
    HandpassungGesperrt,
    get_aip_chart,
    get_connection,
    init_db,
    upsert_aip_chart,
)

BOUNDS = dict(nord=54.24, sued=54.19, west=9.55, ost=9.65,
              feld_nord=54.235, feld_sued=54.195, feld_west=9.56, feld_ost=9.64)
GEO = dict(rahmen_px="132,180,817,865", tick_px_lat=219.0, tick_px_lon=128.4)
# Eine Handpassung legt Nullen in den Rasterfeldern ab -- app/aip_charts.py:1620. Genau
# deshalb kann geometrie_gleich() sie nie wiedererkennen: Sie vergleicht mit einer Toleranz
# von 0,5 px gegen gemessene ~219. Das ist die Ursache der ersten Luecke.
GEO_HAND = dict(rahmen_px="132,180,817,865", tick_px_lat=0.0, tick_px_lon=0.0)


@pytest.fixture()
def conn(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)                       # nimmt einen PFAD, keine Verbindung
    c = get_connection(db)
    yield c
    c.close()


def _hand(conn, icao="EDDL", **abweichend):
    """Eine Handpassung anlegen -- so, wie admin_set_aip_chart sie schreibt."""
    werte = {**BOUNDS, **GEO_HAND, "bild_hash": "a" * 64, "quelle": "hand",
             "airac": "2026AUG20", "status": "gepasst", **abweichend}
    return upsert_aip_chart(conn, icao, **werte)


def test_automatik_darf_handpassung_nicht_ueberschreiben(conn):
    _hand(conn)
    with pytest.raises(HandpassungGesperrt):
        upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0},
                         **GEO, quelle="auto", airac="2026SEP17", status="gepasst")
    k = get_aip_chart(conn, "EDDL")
    assert k["nord"] == pytest.approx(54.24)
    assert k["quelle"] == "hand"


def test_ein_mensch_darf_seine_eigene_passung_ersetzen(conn):
    """admin_set_aip_chart und scripts/aip_handpassung.py schreiben beide hand ueber hand.

    Eine Sperre, die jede Handzeile schuetzt statt nur den Automatikzugriff, machte die
    Korrektur einer verungluecken Handpassung unmoeglich -- also genau das, was der Nutzer
    am 30.08.2026 bei EDDL tun musste.
    """
    _hand(conn)
    _hand(conn, **{**BOUNDS, "nord": 55.0})
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(55.0)


def test_bildauffrischung_unter_bestehender_handpassung_bleibt_erlaubt(conn):
    """Regel 4 aus scripts/aip_bestand.py darf nicht kaputtgehen.

    ``_handblatt_auffrischen`` zieht das BILD nach, nachdem ``zeigt_denselben_ausschnitt``
    nachgewiesen hat, dass es dieselbe Karte ist, und schreibt dabei quelle=alt["quelle"],
    also 'hand'. Ohne diesen Pfad fror jede handgepasste Karte auf dem Stand ihrer
    Handarbeit ein und bekam nie wieder neue Hindernisse oder geaenderte Lufträume.
    """
    _hand(conn)
    _hand(conn, bild_hash="c" * 64, airac="2026SEP17")
    k = get_aip_chart(conn, "EDDL")
    assert k["bild_hash"] == "c" * 64
    assert k["nord"] == pytest.approx(54.24)


def test_ausdrueckliches_ueberschreiben_ist_moeglich(conn):
    """Der Admin uebernimmt einen Vorschlag -- ein Handgriff, kein Automatismus.

    ``hand_ueberschreiben=True`` ist ausschliesslich dafuer da. Kein automatischer Pfad
    setzt es; das ist in Task 3 und 7 des Plans nachzuhalten.
    """
    _hand(conn)
    upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0}, **GEO,
                     quelle="auto", airac="2026SEP17", status="gepasst",
                     hand_ueberschreiben=True)
    assert get_aip_chart(conn, "EDDL")["nord"] == pytest.approx(55.0)


def test_ohne_bestehende_zeile_greift_die_sperre_nicht(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    assert get_aip_chart(conn, "EDWJ")["quelle"] == "auto"


def test_auto_darf_auto_ueberschreiben(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    upsert_aip_chart(conn, "EDWJ", bild_hash="b" * 64, **{**BOUNDS, "nord": 55.0}, **GEO,
                     quelle="auto", airac="y", status="gepasst")
    assert get_aip_chart(conn, "EDWJ")["nord"] == pytest.approx(55.0)


def test_auch_eine_ungepasste_handzeile_ist_geschuetzt(conn):
    """Die Sperre haengt NICHT am status.

    Der Seitenwaehler schrieb bis 30.08.2026 ``quelle="auto" if passung else "hand"``
    (app/main.py) und erzeugte damit Zeilen mit quelle='hand' und status='ungepasst'. Waere
    die Sperre an status='gepasst' gebunden, fielen genau diese durch -- das ist die dritte
    Luecke. Task 2 behebt die Fehlbenennung an der Wurzel; die Sperre deckt beide Faelle
    unabhaengig davon ab.
    """
    _hand(conn, status="ungepasst")
    with pytest.raises(HandpassungGesperrt):
        upsert_aip_chart(conn, "EDDL", bild_hash="b" * 64, **BOUNDS, **GEO,
                         quelle="auto", airac="y", status="gepasst")


# ---------------------------------------------------------------------------
# Aufgabe 2 und 3: die Schreibpfade selbst
# ---------------------------------------------------------------------------
import inspect  # noqa: E402
import re  # noqa: E402


def _ohne_kommentare(text: str) -> str:
    """Python-Kommentare entfernen.

    Ohne das trifft eine Suche nach einer verbotenen Wendung die ERKLAERUNG, warum sie
    verboten ist -- der Test war dann gruen, obwohl der Code sie noch enthielt, oder rot,
    obwohl nur der Kommentar sie nannte. Beim ersten Lauf am 31.08.2026 der zweite Fall.
    """
    return re.sub(r"#[^\n]*", "", text)


def test_seitenwaehler_existiert_in_der_alten_form_nicht_mehr():
    """admin_aip_seite_waehlen ist mit dem Rueckbau (31.08.2026) entfallen -- Nachfolgerin
    ist admin_dfs_seite_waehlen, die kein Lagefeld mehr anfasst (Task 5) und darum die
    alte quelle/Sperre-Unterscheidung nicht mehr braucht, um eine Handpassung zu schuetzen.

    Die vollstaendige Ablösung dieser Datei steht noch aus (Task 9): Bis dahin testet sie
    weiterhin die ALTE Sperre auf den ALTEN Tabellen, die erst mit dem Rueckbau der
    Automatik (Task 3/4/6) verschwinden.
    """
    from app import main

    assert not hasattr(main, "admin_aip_seite_waehlen")
    assert hasattr(main, "admin_dfs_seite_waehlen")


def test_lauf_und_karte_schreiben_existieren_in_der_alten_form_nicht_mehr():
    """scripts.aip_bestand._karte_schreiben() war die Passungs-Schreibfunktion von lauf()
    (Erstbefuellung) -- beide sind mit dem Rueckbau (31.08.2026) entfallen. Was den
    Kernbefund dieser beiden Tests ersetzt (kein Bildtausch unter einer alten Passung,
    kein Abbruch mitten im Durchgang) ist heute Aufgabe der Sperre in upsert_chart_dfs
    (Task 2) -- getestet in tests/test_charts_dfs.py."""
    import scripts.aip_bestand as bestand

    assert not hasattr(bestand, "lauf")
    assert not hasattr(bestand, "_karte_schreiben")


# ---------------------------------------------------------------------------
# Aufgabe 4: Loeschen ist kein Ueberschreiben -- und trifft die Sperre nicht
# ---------------------------------------------------------------------------

def test_verwaiste_handpassung_wird_nicht_geloescht(conn):
    """Verschwindet der Link aus airport_links, verliert eine Automatikkarte Zeile und
    Blatt -- das ist richtig, sie ist in Minuten neu gerechnet.

    Eine Handpassung ist Arbeit eines Menschen. Sie wird nur aus der Anzeige genommen.
    Die Sperre in upsert_aip_chart hilft hier nicht: Sie sitzt im Schreibpfad, das
    Aufraeumen laeuft ueber delete_aip_chart.
    """
    from app.database import get_aip_charts, verwaisen

    _hand(conn, icao="EDDL")
    assert verwaisen(conn, "EDDL") == 1
    k = get_aip_chart(conn, "EDDL")
    assert k is not None
    assert k["status"] == "verwaist" and k["quelle"] == "hand"
    assert "EDDL" not in [x["icao"] for x in get_aip_charts(conn)]


def test_verwaiste_karte_kann_zurueckkehren(conn):
    """Taucht der Link wieder auf -- ein AIRAC-Wechsel benennt Kapitelseiten um --, muss die
    Handpassung wieder greifen, ohne dass jemand sie neu setzt."""
    from app.database import get_aip_charts, verwaisen

    _hand(conn, icao="EDDL")
    verwaisen(conn, "EDDL")
    _hand(conn, icao="EDDL", status="gepasst")
    assert "EDDL" in [x["icao"] for x in get_aip_charts(conn)]


def test_automatikkarte_wird_weiterhin_geloescht(conn):
    from app.database import delete_aip_chart

    upsert_aip_chart(conn, "EDWJ", bild_hash="a" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    assert delete_aip_chart(conn, "EDWJ") == 1
    assert get_aip_chart(conn, "EDWJ") is None


def test_lauf_existiert_in_der_alten_form_nicht_mehr():
    """scripts.aip_bestand.lauf() -- die automatische Erstbefuellung mit
    Automatik-vs-Hand-Aufraeumzweig -- ist mit dem Rueckbau (31.08.2026) entfallen.

    Ein Platz ohne Zeile wird nicht mehr automatisch befuellt; er erscheint im Admin als
    'nicht nachgesehen' und wartet auf eine bewusste Seitenauswahl (Spec 4.2). Was bleibt,
    ist ausschliesslich melden() -- der Hash-Vergleich des Wochenjobs."""
    import scripts.aip_bestand as bestand

    assert not hasattr(bestand, "lauf")
    assert hasattr(bestand, "melden")


# ---------------------------------------------------------------------------
# Aufgabe 5: die Seitenwahl geht ohne jedes Ueberschreiben verloren
# ---------------------------------------------------------------------------

def test_seitenwahl_wird_gespeichert(conn):
    """Bei EDDK enthaelt das Kapitel sechs Seiten, und die automatisch gewaehlte war die
    falsche (Nutzer, 24.08.2026)."""
    _hand(conn, icao="EDDK",
          seite_url="https://aip.dfs.de/BasicVFR/2026AUG20/pages/s4.html")
    assert get_aip_chart(conn, "EDDK")["seite_url"].endswith("s4.html")


def test_ein_lauf_ohne_seitenangabe_loescht_die_wahl_nicht(conn):
    """Das ist der eigentliche Fallstrick.

    Der Auffrischlauf kennt seite_url nicht und gibt sie nicht mit. Wuerde sie dabei auf ''
    zurueckfallen, ginge die Handkorrektur verloren -- und zwar OHNE jedes Ueberschreiben
    einer Passung, also an der Sperre aus Aufgabe 1 vorbei.
    """
    _hand(conn, icao="EDDK",
          seite_url="https://aip.dfs.de/BasicVFR/2026AUG20/pages/s4.html")
    _hand(conn, icao="EDDK", bild_hash="c" * 64)          # ohne seite_url
    assert get_aip_chart(conn, "EDDK")["seite_url"].endswith("s4.html")


def test_neue_karte_ohne_seitenwahl_bekommt_leeren_wert(conn):
    upsert_aip_chart(conn, "EDWJ", bild_hash="a" * 64, **BOUNDS, **GEO,
                     quelle="auto", airac="x", status="gepasst")
    assert get_aip_chart(conn, "EDWJ")["seite_url"] == ""


# ---------------------------------------------------------------------------
# Aufgabe 6: Vorschlaege mit Grabstein
# ---------------------------------------------------------------------------

def test_verworfener_vorschlag_kommt_nicht_wieder(conn):
    """Ein DELETE waere wirkungslos: UNIQUE verhindert Doppel nur, solange die Zeile
    existiert. Der naechste Wochenlauf faende denselben unveraenderten quell_hash und legte
    den Vorschlag sofort neu an -- die Liste waere dauerhaft unaufraeumbar."""
    from app.database import get_vorschlaege, vorschlag_anlegen, vorschlag_verwerfen

    vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "weicht ab")
    assert vorschlag_verwerfen(conn, vid) == 1
    assert get_vorschlaege(conn) == []
    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "weicht ab")
    assert get_vorschlaege(conn) == []


def test_ein_neues_rohblatt_ist_ein_neuer_vorschlag(conn):
    from app.database import get_vorschlaege, vorschlag_anlegen, vorschlag_verwerfen

    vid = vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {"nord": 55.0}, "weicht ab")
    vorschlag_verwerfen(conn, vid)
    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h2", {"nord": 56.0}, "weicht ab")
    assert len(get_vorschlaege(conn)) == 1


def test_beide_kartentypen_koennen_gleichzeitig_offen_sein(conn):
    """Der Dateiname des Vorschlagsbilds muss art UND quell_hash tragen -- sonst
    ueberschreiben sich zwei offene Vorschlaege zu EDDL gegenseitig."""
    from app.database import get_vorschlaege, vorschlag_anlegen

    vorschlag_anlegen(conn, "sichtflug", "EDDL", "h1", {}, "a")
    vorschlag_anlegen(conn, "ground", "EDDL", "h1", {}, "b")
    assert len(get_vorschlaege(conn)) == 2
    assert len(get_vorschlaege(conn, art="ground")) == 1


def test_passung_kommt_als_dict_zurueck(conn):
    from app.database import get_vorschlaege, vorschlag_anlegen

    vorschlag_anlegen(conn, "ground", "EDDM", "h1", {"drehung": 353.5}, "neu")
    assert get_vorschlaege(conn, art="ground")[0]["passung"]["drehung"] == pytest.approx(353.5)


# ---------------------------------------------------------------------------
# Aufgabe 8: Der Job muss ueberhaupt laufen -- aber nicht bei jedem Deploy
# ---------------------------------------------------------------------------

def test_job_laeuft_nach_deploy_nur_wenn_wirklich_faellig(conn):
    """Zwoelf Deploys an einem Tag duerfen nicht zwoelf Vollcrawls der DFS ausloesen.

    Der Lauf holt ueber 1000 Seiten: zwei je Platz, dazu bei jedem Blatt mit gescheiterter
    Passung ein kompletter Kapiteldurchlauf ueber 4 bis 12 weitere Seiten.
    """
    from app.database import job_erledigt, job_faellig

    assert job_faellig(conn, "aip_auffrischen", 7 * 24 * 3600) is True
    job_erledigt(conn, "aip_auffrischen")
    assert job_faellig(conn, "aip_auffrischen", 7 * 24 * 3600) is False
    assert job_faellig(conn, "aip_auffrischen", 0) is True
    assert job_faellig(conn, "anderer_job", 7 * 24 * 3600) is True


def test_aip_auffrischen_existiert_in_der_alten_form_nicht_mehr():
    """Nachfolgerin ist poller.VatsimPoller._aip_hash_pruefen -- getestet in
    tests/test_charts_dfs.py (test_es_gibt_genau_einen_kartenjob,
    test_der_job_haengt_am_faelligkeitsmerker)."""
    from app import poller

    assert not hasattr(poller.VatsimPoller, "_aip_auffrischen")
    assert not hasattr(poller.VatsimPoller, "_ground_charts_melden")
    assert hasattr(poller.VatsimPoller, "_aip_hash_pruefen")


# ---------------------------------------------------------------------------
# Die Sperre gilt fuer BEIDE Kartentypen -- eine Fassung, nicht zwei
# ---------------------------------------------------------------------------

_GROUND = dict(sorte="flugplatzkarte", quell_hash="b" * 64, bild_hash="c" * 64,
               nord=51.30, sued=51.27, west=6.74, ost=6.80,
               feld_nord=51.295, feld_sued=51.275, feld_west=6.745, feld_ost=6.795,
               drehung=322.8, mps=1.69, rest_max=5.7, bahnen=2,
               airac="2026AUG20", status="gepasst")


def test_ground_handpassung_ist_ebenso_gesperrt(conn):
    from app.database import get_ground_chart, upsert_ground_chart

    upsert_ground_chart(conn, "EDDL", quelle="hand", **_GROUND)
    with pytest.raises(HandpassungGesperrt):
        upsert_ground_chart(conn, "EDDL", quelle="auto", **{**_GROUND, "drehung": 0.0})
    assert get_ground_chart(conn, "EDDL")["drehung"] == pytest.approx(322.8)


def test_ground_mensch_darf_sich_selbst_korrigieren(conn):
    from app.database import get_ground_chart, upsert_ground_chart

    upsert_ground_chart(conn, "EDDL", quelle="hand", **_GROUND)
    upsert_ground_chart(conn, "EDDL", quelle="hand", **{**_GROUND, "drehung": 320.0})
    assert get_ground_chart(conn, "EDDL")["drehung"] == pytest.approx(320.0)


def test_ground_admin_darf_ausdruecklich_ueberschreiben(conn):
    from app.database import get_ground_chart, upsert_ground_chart

    upsert_ground_chart(conn, "EDDL", quelle="hand", **_GROUND)
    upsert_ground_chart(conn, "EDDL", quelle="auto", hand_ueberschreiben=True,
                        **{**_GROUND, "drehung": 10.0})
    assert get_ground_chart(conn, "EDDL")["drehung"] == pytest.approx(10.0)


def test_die_sperre_existiert_nur_einmal():
    """Zwei Fassungen derselben Regel laufen auseinander. Beide upsert-Funktionen rufen
    denselben Helfer -- das ist der Kern von Abschnitt 7.1 der Spec."""
    import inspect

    from app import database

    for fn in (database.upsert_aip_chart, database.upsert_ground_chart):
        quelle = _ohne_kommentare(inspect.getsource(fn))
        assert "_handpassung_pruefen(" in quelle
        assert "raise HandpassungGesperrt" not in quelle


def test_ground_karte_nur_gepasste_in_der_liste(conn):
    from app.database import get_ground_charts, upsert_ground_chart, verwaisen_ground

    upsert_ground_chart(conn, "EDDL", quelle="hand", **_GROUND)
    upsert_ground_chart(conn, "EDDM", quelle="auto", **{**_GROUND, "status": "ungepasst"})
    assert [k["icao"] for k in get_ground_charts(conn)] == ["EDDL"]
    assert len(get_ground_charts(conn, nur_gepasst=False)) == 2
    verwaisen_ground(conn, "EDDL")
    assert get_ground_charts(conn) == []
