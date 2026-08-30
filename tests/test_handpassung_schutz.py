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
