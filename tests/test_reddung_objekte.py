# -*- coding: utf-8 -*-
"""Havarist und Fackeln als Bruegge-Objekte (20.09.2026)."""
from __future__ import annotations

import pathlib

import pytest

from app.database import bruegge_soll_fuer, bruegge_soll_setzen, get_connection, init_db


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def test_ohne_simulator_gilt_ein_objekt_fuer_alle(conn):
    bruegge_soll_setzen(conn, "havarist-1", "flugzeug_echo", 53.7, 7.2)
    for sim in ("msfs2020", "msfs2024", "xplane12"):
        assert len(bruegge_soll_fuer(conn, 111, sim)) == 1


def test_mit_simulator_sieht_es_nur_dieser(conn):
    bruegge_soll_setzen(conn, "havarist-2020", "boot_klein", 53.7, 7.2, simulator="msfs2020")
    bruegge_soll_setzen(conn, "havarist-2024", "schiff_segel", 53.7, 7.2, simulator="msfs2024")
    ids_2020 = [o["id"] for o in bruegge_soll_fuer(conn, 111, "msfs2020")]
    ids_2024 = [o["id"] for o in bruegge_soll_fuer(conn, 111, "msfs2024")]
    assert ids_2020 == ["havarist-2020"] and ids_2024 == ["havarist-2024"]
    assert bruegge_soll_fuer(conn, 111, "xplane12") == []


def test_ohne_angabe_des_simulators_kommt_weiterhin_alles(conn):
    """Abwaertskompatibel: Wer den Parameter nicht angibt, bekommt wie bisher alles. Sonst
    verliert ein aelterer Aufrufer still Objekte."""
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator="msfs2020")
    assert len(bruegge_soll_fuer(conn, 111)) == 1


def test_der_simulator_laesst_sich_wieder_auf_alle_stellen(conn):
    """Das ON-CONFLICT muss die Spalte mitziehen -- sonst bleibt ein alter Filter stehen und
    das Objekt verschwindet fuer zwei Drittel der Piloten."""
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator="msfs2020")
    bruegge_soll_setzen(conn, "a", "flugzeug_echo", 53.7, 7.2, simulator=None)
    assert len(bruegge_soll_fuer(conn, 111, "xplane12")) == 1


def test_der_melde_endpunkt_filtert_nach_simulator():
    """Verankert am Quelltext: Wer den Parameter beim Aufruf wieder wegnimmt, liefert
    2020-Piloten Objekte aus, die sie nicht setzen koennen."""
    quelle = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "bruegge_soll_fuer(conn, cid, simulator)" in quelle


# --- Havarist, Fackeln, Grundhoehe ----------------------------------------

from app.database import (
    create_reddung_event, get_reddung_event, reddung_grund_lernen,
    reddung_objekte_abgleichen, set_reddung_aufgeloest, set_reddung_aufgenommen,
    set_reddung_gefunden,
)

SEKTOR = dict(sued=53.54, west=6.95, nord=53.90, ost=7.55)


def _art(conn, art, simulatoren, titel="T"):
    conn.execute("INSERT OR REPLACE INTO bruegge_art (art, bedeutung, status, angelegt_am) "
                 "VALUES (?,?,'aktiv','2026-09-20T00:00:00Z')", (art, art))
    for sim in simulatoren:
        conn.execute(
            "INSERT OR REPLACE INTO bruegge_katalog (simulator, titel, art, rang, status, quelle) "
            "VALUES (?,?,?,1,'aktiv','bord')", (sim, f"{titel}-{sim}", art))


def _ev(conn, **extra):
    eid = create_reddung_event(conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
                               dtend="2026-09-25T22:00:00Z", **SEKTOR,
                               havarist_lat=53.72, havarist_lon=7.25, **extra)
    return get_reddung_event(conn, eid)


def _arten_je_sim(conn, muster="%havarist%"):
    return dict(conn.execute("SELECT simulator, art FROM bruegge_soll WHERE id LIKE ?",
                             (muster,)).fetchall())


def test_eine_art_fuer_alle_simulatoren_gibt_eine_zeile(conn):
    """Der Normalfall -- flugzeug_echo laeuft ueberall."""
    _art(conn, "flugzeug_echo", ("msfs2020", "msfs2024", "xplane12"))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    zeilen = conn.execute("SELECT id, art, simulator, auf_boden, gilt_bis FROM bruegge_soll "
                          "ORDER BY id").fetchall()
    assert len(zeilen) == 1 and zeilen[0][0] in ids
    assert zeilen[0][1] == "flugzeug_echo"
    assert zeilen[0][2] is None, "eine Art fuer alle braucht keinen Simulatorfilter"
    assert zeilen[0][3] == 1, "OnGround wie bei den Booten (15.6.1)"
    assert zeilen[0][4] == "2026-09-25T22:00:00Z", "laeuft mit dtend von selbst ab"


def test_ohne_gesetzte_art_gilt_flugzeug_echo(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    reddung_objekte_abgleichen(conn, _ev(conn))
    assert list(_arten_je_sim(conn).values()) == ["flugzeug_echo"]


def test_die_beiden_MSFS_schoepfen_aus_einem_topf(conn):
    """⚠ Der Fall, den ich zuerst falsch hatte: `_BRUEGGE_TOPF` liefert MSFS 2020 und 2024
    aus EINEM Titelvorrat (`k.simulator IN ('msfs2020','msfs2024')`). Ein Titel, der nur
    unter msfs2020 im Katalog steht, geht deshalb auch an eine 2024er Bruegge -- zwischen den
    beiden MSFS gibt es keine Auslieferungsluecke, nur eine Katalogluecke.

    Folge fuer diese Funktion: EINE Zeile fuer alle, kein Simulatorfilter."""
    _art(conn, "boot_klein", ("msfs2020", "xplane12"))
    reddung_objekte_abgleichen(conn, _ev(conn, havarist_art="boot_klein"))
    zeilen = [tuple(r) for r in conn.execute(
        "SELECT simulator, art FROM bruegge_soll WHERE id LIKE '%havarist%'").fetchall()]
    assert zeilen == [(None, "boot_klein")]


def test_eine_art_ohne_xplane_wird_dort_ersetzt(conn):
    """Der echte Schnitt: MSFS gegen X-Plane. flugzeug_klassik hat keinen X-Plane-Titel --
    dort muss eine andere Art einspringen, sonst erscheint bei X-Plane-Piloten stumm nichts."""
    _art(conn, "flugzeug_klassik", ("msfs2020", "msfs2024"))
    _art(conn, "flugzeug_echo", ("msfs2024", "xplane12"))
    reddung_objekte_abgleichen(conn, _ev(conn, havarist_art="flugzeug_klassik"))
    je_sim = _arten_je_sim(conn)
    assert je_sim["xplane12"] == "flugzeug_echo"
    assert je_sim["msfs2020"] == "flugzeug_klassik" and je_sim["msfs2024"] == "flugzeug_klassik"


def test_gibt_es_gar_keinen_ersatz_bleibt_der_simulator_leer(conn):
    """Besser nichts als eine Zeile, die die Bruegge nicht setzen kann.

    ⚠ Die Testdatenbank ist NICHT leer: `init_db` belegt 41 Arten und 185 Katalogzeilen vor,
    darunter flugzeug_echo fuer X-Plane. Ein erster Anlauf nahm flugzeug_klassik und bekam
    deshalb den Ersatz flugzeug_echo gestellt statt der erwarteten Luecke. Hier steht deshalb
    eine erfundene Art ohne Ersatzkette."""
    _art(conn, "zzprobe", ("msfs2020",))
    reddung_objekte_abgleichen(conn, _ev(conn, havarist_art="zzprobe"))
    assert _arten_je_sim(conn) == {"msfs2020": "zzprobe", "msfs2024": "zzprobe"}


def test_ohne_fund_gibt_es_keine_fackel(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    reddung_objekte_abgleichen(conn, _ev(conn))
    assert conn.execute("SELECT count(*) FROM bruegge_soll "
                        "WHERE art LIKE 'rauch%'").fetchone()[0] == 0


def test_nach_dem_fund_steht_die_orange_fackel(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalorange", ("msfs2024",))
    ev = _ev(conn)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    arten = [r[0] for r in conn.execute(
        "SELECT art FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchall()]
    assert arten == ["rauch_signalorange"]


def test_die_fackel_steht_neben_dem_havaristen_nicht_in_ihm(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalorange", ("msfs2024",))
    ev = _ev(conn)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    lat = conn.execute("SELECT lat FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchone()[0]
    assert lat != 53.72 and abs(lat - 53.72) < 0.001


def test_nach_der_aufnahme_wechselt_die_fackel_auf_hellblau(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalorange", ("msfs2024",))
    _art(conn, "rauch_hellblau", ("msfs2024",))
    ev = _ev(conn)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    set_reddung_aufgenommen(conn, ev["id"], "2026-09-25T17:50:00Z", 222)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    arten = [r[0] for r in conn.execute(
        "SELECT art FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchall()]
    assert arten == ["rauch_hellblau"], "orange darf nicht daneben stehenbleiben"


def test_die_fackel_folgt_den_drei_stufen(conn):
    """orange = gefunden, hellblau = aufgenommen, rot = abgeschlossen. Die rote bleibt bis
    zum Eventende stehen und markiert die Stelle."""
    for art in ("flugzeug_echo", "rauch_signalorange", "rauch_hellblau", "rauch_signalrot"):
        _art(conn, art, ("msfs2024",))
    ev = _ev(conn)

    def fackel():
        reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
        r = conn.execute("SELECT art FROM bruegge_soll WHERE art LIKE 'rauch%'").fetchall()
        return [x[0] for x in r]

    assert fackel() == []
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    assert fackel() == ["rauch_signalorange"]
    set_reddung_aufgenommen(conn, ev["id"], "2026-09-25T17:50:00Z", 222)
    assert fackel() == ["rauch_hellblau"], "orange darf nicht daneben stehenbleiben"
    set_reddung_aufgeloest(conn, ev["id"], "2026-09-25T18:20:00Z")
    assert fackel() == ["rauch_signalrot"]


def test_nach_der_aufloesung_bleibt_alles_stehen(conn):
    """⚠ Hier stand zuerst das Gegenteil, und das war ein Fehler.

    Bei `aufnehmen_noetig = 0` loest der Fund die Lage im SELBEN Poller-Takt auf -- die
    hellblaue Fackel waere erschienen und verschwunden, ohne dass sie jemand gesehen haette.
    Wrack und Fackel stehen deshalb bis zum Eventende; `gilt_bis` laesst sie von selbst
    ablaufen.
    """
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalrot", ("msfs2024",))
    ev = _ev(conn, aufnehmen_noetig=0)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    set_reddung_aufgeloest(conn, ev["id"], "2026-09-25T17:30:00Z")
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    zeilen = conn.execute("SELECT art, gilt_bis FROM bruegge_soll ORDER BY art").fetchall()
    assert [r[0] for r in zeilen] == ["flugzeug_echo", "rauch_signalrot"]
    assert all(r[1] == "2026-09-25T22:00:00Z" for r in zeilen), "laufen mit dtend ab"


def test_nur_weg_raeumt_wirklich_auf(conn):
    """Der Weg beim Loeschen eines Events -- sonst stuende ein Wrack zu einem Event, das es
    nicht mehr gibt."""
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    reddung_objekte_abgleichen(conn, ev)
    assert conn.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] > 0
    reddung_objekte_abgleichen(conn, ev, weg=True)
    assert conn.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] == 0


def test_ohne_gesetzten_ort_wird_nichts_gestellt(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    ev = {**ev, "havarist_lat": None, "havarist_lon": None}
    assert reddung_objekte_abgleichen(conn, ev) == []
    assert conn.execute("SELECT count(*) FROM bruegge_soll").fetchone()[0] == 0


def _meldung(conn, obj_id, hoehe, gemessen, plat, plon, sim="msfs2024"):
    conn.execute("INSERT OR REPLACE INTO bruegge_positions (cid, lat, lon, gemeldet_am, "
                 "simulator) VALUES (111, ?, ?, '2026-09-25T17:05:00Z', ?)", (plat, plon, sim))
    conn.execute("INSERT OR REPLACE INTO bruegge_steht (kennung, id, cid, zustand, hoehe_ft, "
                 "hoehe_gemessen, gemeldet_am) VALUES ('k1', ?, 111, 'steht', ?, ?, "
                 "'2026-09-25T17:05:00Z')", (obj_id, hoehe, gemessen))


def test_die_grundhoehe_kommt_aus_einer_gemessenen_meldung(conn):
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    _meldung(conn, ids[0], 20.0, 1, 53.73, 7.26)
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is True
    ev2 = get_reddung_event(conn, ev["id"])
    assert ev2["havarist_grund_ft"] == 20.0 and ev2["havarist_grund_quelle"] == "gemessen"


def test_eine_UNGEMESSENE_meldung_setzt_nichts(conn):
    """⚠ Der X-Plane-Fall: Ohne geladenes Gelaende bekommt das Objekt Meereshoehe, und die
    Meldung sieht genau wie ein Wattobjekt auf 0,0 ft aus (PROTOKOLL, hoehe_gemessen)."""
    _art(conn, "flugzeug_echo", ("xplane12",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    _meldung(conn, ids[0], 0.0, 0, 53.73, 7.26, sim="xplane12")
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is False
    assert get_reddung_event(conn, ev["id"])["havarist_grund_ft"] is None


def test_eine_meldung_von_weit_weg_setzt_nichts(conn):
    """⚠ Am Bodensee gemessen: 2.106 ft statt 1.297 ft bei 691 km Abstand -- aus der Ferne
    antwortet der Simulator aus einer groben Gelaendestufe, nicht aus geladenem Terrain."""
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    _meldung(conn, ids[0], 2106.5, 1, 47.65, 9.18)
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is False


def test_eine_alte_meldung_ohne_das_feld_gilt_als_messung(conn):
    """MSFS sendet hoehe_gemessen nicht -- NULL darf nicht als 'geraten' gelesen werden."""
    _art(conn, "flugzeug_echo", ("msfs2024",))
    ev = _ev(conn)
    ids = reddung_objekte_abgleichen(conn, ev)
    _meldung(conn, ids[0], 20.0, None, 53.73, 7.26)
    assert reddung_grund_lernen(conn, get_reddung_event(conn, ev["id"])) is True


def test_die_meldung_traegt_hoehe_gemessen_in_die_tabelle(conn):
    """Ohne dieses Feld ist der X-Plane-Vorbehalt oben nicht pruefbar.

    Geprueft wird am Verhalten, nicht am Quelltext: `bruegge_steht_melden` bekommt die rohe
    Liste aus der Meldung (app/main.py:1641) und muss das Feld durchschreiben. Ein Plan-Test
    verankerte das zuerst an "hoehe_gemessen" in main.py -- dort steht es gar nicht, und das
    ist richtig so: main.py reicht die Liste unveraendert durch."""
    from app.database import bruegge_steht_melden
    bruegge_steht_melden(conn, "k9", 111, [
        {"id": "x", "zustand": "steht", "hoehe_ft": 12.5, "hoehe_gemessen": 0}])
    assert conn.execute("SELECT hoehe_gemessen FROM bruegge_steht WHERE id = 'x'"
                        ).fetchone()[0] == 0


def test_der_abgleich_ist_vollstaendig_und_raeumt_eine_ueberfluessige_fackel_weg(conn):
    """PROTOKOLL.md, Abschnitt 2: Der Sollzustand ist eine vollstaendige Liste, kein Strom von
    Befehlen. Diese Funktion muss deshalb auch WEGNEHMEN koennen, was nicht mehr hingehoert.

    ⚠ Der Fall ist im Normalbetrieb unerreichbar (ein Fund-Latch wird nie zurueckgenommen, und
    der Farbwechsel ueberschreibt dieselbe Zeile). Genau darum stand er ohne diesen Test auch
    ungeprueft da: Die Gegenprobe "else-Zweig entfernt" blieb gruen. Hier wird er von Hand
    herbeigefuehrt -- so, wie ein spaeterer Admin-Knopf "Fund zuruecknehmen" ihn erzeugen wuerde.
    """
    _art(conn, "flugzeug_echo", ("msfs2024",))
    _art(conn, "rauch_signalorange", ("msfs2024",))
    ev = _ev(conn)
    set_reddung_gefunden(conn, ev["id"], "2026-09-25T17:30:00Z", 111)
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    assert conn.execute("SELECT count(*) FROM bruegge_soll "
                        "WHERE art LIKE 'rauch%'").fetchone()[0] == 1
    conn.execute("UPDATE reddung_events SET gefunden_am = NULL, gefunden_von = NULL "
                 "WHERE id = ?", (ev["id"],))
    reddung_objekte_abgleichen(conn, get_reddung_event(conn, ev["id"]))
    assert conn.execute("SELECT count(*) FROM bruegge_soll "
                        "WHERE art LIKE 'rauch%'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM bruegge_soll "
                        "WHERE id LIKE '%havarist%'").fetchone()[0] == 1, \
        "der Havarist bleibt -- nur die Fackel ist weg"
