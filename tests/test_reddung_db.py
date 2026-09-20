# -*- coding: utf-8 -*-
"""Tabelle und Latches der FriesenReddung (20.09.2026)."""
from __future__ import annotations

import pytest

from app.database import (
    clear_reddung_aufnahme, create_reddung_event, delete_reddung_event, get_connection,
    get_reddung_event, init_db, list_reddung_events, reddung_grund_merken,
    set_reddung_aufgeloest, set_reddung_aufgenommen, set_reddung_eingeliefert,
    set_reddung_gefunden, update_reddung_event,
)

SEKTOR = dict(sued=53.54, west=6.95, nord=53.90, ost=7.55)


@pytest.fixture()
def conn(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    c = get_connection(p)
    yield c
    c.close()


def _ev(conn, **extra):
    return create_reddung_event(conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
                                **SEKTOR, **extra)


def test_anlegen_und_lesen(conn):
    eid = _ev(conn)
    ev = get_reddung_event(conn, eid)
    assert ev["name"] == "Reddung Probe"
    assert ev["sued"] == 53.54 and ev["ost"] == 7.55


def test_die_vorgaben_stehen_in_der_tabelle(conn):
    """Sie stehen in der DDL, damit eine von Hand angelegte Zeile brauchbar ist."""
    ev = get_reddung_event(conn, _ev(conn))
    assert ev["kante_km"] == 1.0 and ev["korridor_km"] == 1.0
    assert ev["hoehe_max_ft"] == 1000 and ev["gs_max_kt"] == 140 and ev["gs_min_kt"] == 30
    assert ev["aufnehmen_noetig"] == 1 and ev["landung_noetig"] == 1
    assert ev["aufnahme_verfaellt"] == 1
    assert ev["push_enabled"] == 1


def test_dtend_bekommt_den_mitternacht_standard(conn):
    ev = get_reddung_event(conn, _ev(conn))
    assert ev["dtend"] == "2026-09-26T00:00:00Z"


def test_aendern_und_loeschen(conn):
    eid = _ev(conn)
    update_reddung_event(conn, eid, havarist_lat=53.72, havarist_lon=7.25,
                         havarist_art="flugzeug_echo", landung_noetig=0)
    ev = get_reddung_event(conn, eid)
    assert ev["havarist_lat"] == 53.72 and ev["landung_noetig"] == 0
    delete_reddung_event(conn, eid)
    assert get_reddung_event(conn, eid) is None


def test_unbekanntes_feld_wird_abgewiesen(conn):
    """Sonst schreibt ein Tippfehler im Admin still ins Leere."""
    with pytest.raises(ValueError):
        update_reddung_event(conn, _ev(conn), havarost_lat=1.0)


def test_unbekanntes_feld_wird_auch_beim_anlegen_abgewiesen(conn):
    with pytest.raises(ValueError):
        _ev(conn, havarost_lat=1.0)


def test_latches_setzen_nur_beim_ersten_mal(conn):
    eid = _ev(conn)
    assert set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111) is True
    assert set_reddung_gefunden(conn, eid, "2026-09-25T17:45:00Z", 222) is False
    ev = get_reddung_event(conn, eid)
    assert ev["gefunden_von"] == 111 and ev["gefunden_am"] == "2026-09-25T17:30:00Z"


def test_der_aufnehmende_muss_nicht_der_finder_sein(conn):
    eid = _ev(conn)
    set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111)
    assert set_reddung_aufgenommen(conn, eid, "2026-09-25T17:50:00Z", 222) is True
    assert get_reddung_event(conn, eid)["aufgenommen_von"] == 222


def test_einliefern_merkt_den_platz(conn):
    eid = _ev(conn)
    assert set_reddung_eingeliefert(conn, eid, "2026-09-25T18:20:00Z", 222, "EDWF") is True
    ev = get_reddung_event(conn, eid)
    assert ev["eingeliefert_icao"] == "EDWF" and ev["eingeliefert_von"] == 222


def test_aufnahme_zuruecknehmen_macht_den_latch_wieder_frei(conn):
    """Bricht der Aufnehmende ab, muss ein anderer uebernehmen koennen."""
    eid = _ev(conn)
    set_reddung_aufgenommen(conn, eid, "2026-09-25T17:50:00Z", 222)
    clear_reddung_aufnahme(conn, eid)
    ev = get_reddung_event(conn, eid)
    assert ev["aufgenommen_am"] is None and ev["aufgenommen_von"] is None
    assert set_reddung_aufgenommen(conn, eid, "2026-09-25T18:05:00Z", 333) is True


def test_grundhoehe_merken_und_ihre_herkunft(conn):
    eid = _ev(conn)
    assert reddung_grund_merken(conn, eid, 20.0, "gemessen") is True
    ev = get_reddung_event(conn, eid)
    assert ev["havarist_grund_ft"] == 20.0 and ev["havarist_grund_quelle"] == "gemessen"


def test_eine_messung_ueberschreibt_eine_schaetzung_aber_nicht_umgekehrt(conn):
    """Die Messung der Bruegge ist die beste Quelle. Eine spaetere Platzhoehe darf sie
    nicht verdraengen -- sonst kippt die Hoehenschranke mitten im Abend, und niemand
    versteht, warum ein Ueberflug ploetzlich nicht mehr zaehlt."""
    eid = _ev(conn)
    reddung_grund_merken(conn, eid, 45.0, "platz")
    assert reddung_grund_merken(conn, eid, 20.0, "gemessen") is True
    assert get_reddung_event(conn, eid)["havarist_grund_ft"] == 20.0
    assert reddung_grund_merken(conn, eid, 45.0, "platz") is False
    assert get_reddung_event(conn, eid)["havarist_grund_ft"] == 20.0


def test_aufloesen_ist_ebenfalls_ein_latch(conn):
    eid = _ev(conn)
    assert set_reddung_aufgeloest(conn, eid, "2026-09-26T00:00:00Z") is True
    assert set_reddung_aufgeloest(conn, eid, "2026-09-26T00:05:00Z") is False


def test_liste_filtert_nach_zeit(conn):
    _ev(conn)
    assert len(list_reddung_events(conn)) == 1
    assert list_reddung_events(conn, since="2026-10-01T00:00:00Z") == []


# --- Stand einer FriesenReddung -------------------------------------------
#
# ⚠ `compute_reddung_stand` RECHNET den Fund nicht, sie LIEST ihn aus der Tabelle. Der Fund
# wird im Poller gegen `havarist_ziel(ev)` gerechnet und gelatcht. Der Grund ist nicht
# Bequemlichkeit: So fasst diese Funktion die Koordinate nie an, und die Zusicherung "kein
# Ort im Ergebnis" ist eine Eigenschaft des Aufbaus statt eine Frage der Sorgfalt. Die
# Fundtests stehen deshalb in tests/test_reddung_poller.py.

import math

from app.database import compute_reddung_stand, reddung_spuren, upsert_pilot

LAT, LON = 53.72, 7.25
GRAD_KM_LAT = 1.0 / 111.32
GRAD_KM_LON = 1.0 / (111.32 * math.cos(math.radians(LAT)))


def _kleiner_sektor(conn, **extra):
    """4 x 4 km, damit die Tests wenige Zellen haben und lesbar bleiben."""
    return create_reddung_event(
        conn, name="Reddung Probe", dtstart="2026-09-25T17:00:00Z",
        dtend="2026-09-25T20:00:00Z",
        sued=LAT - 2 * GRAD_KM_LAT, west=LON - 2 * GRAD_KM_LON,
        nord=LAT + 2 * GRAD_KM_LAT, ost=LON + 2 * GRAD_KM_LON,
        havarist_lat=LAT, havarist_lon=LON, havarist_grund_ft=10.0, **extra)


def _spur(conn, cid, punkte, alt=900, gs=110):
    upsert_pilot(conn, cid, f"Pilot {cid}")
    for lat, lon, ts in punkte:
        conn.execute(
            "INSERT INTO position_history (cid, callsign, latitude, longitude, altitude, "
            "groundspeed, heading, ts) VALUES (?,?,?,?,?,?,?,?)",
            (cid, f"FRS{cid}", lat, lon, alt, gs, 90, ts))


def _quer(ts_start=0):
    """Ein Ost-West-Flug durch die Sektormitte, 1 km je 15 s."""
    return [(LAT, LON + k * GRAD_KM_LON,
             f"2026-09-25T17:{10 + (ts_start + k * 15) // 60:02d}:{(ts_start + k * 15) % 60:02d}Z")
            for k in (-2, -1, 0, 1)]


def test_ohne_spuren_ist_nichts_abgedeckt(conn):
    ev = get_reddung_event(conn, _kleiner_sektor(conn))
    stand = compute_reddung_stand(conn, ev)
    assert stand["anteil"] == 0.0 and stand["abgedeckt"] == 0
    assert stand["zellen"] > 0 and stand["gefunden"] is None


def test_ein_ueberflug_deckt_zellen_ab(conn):
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer())
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    assert stand["abgedeckt"] > 0 and 0 < stand["anteil"] <= 1
    assert stand["je_pilot"][0]["cid"] == 111
    assert stand["je_pilot"][0]["name"] == "Pilot 111"
    assert stand["je_pilot"][0]["zellen"] > 0


def test_zu_hoch_deckt_nichts_ab(conn):
    """1000 ft AGL bei 10 ft Gelaende -- 2000 ft MSL ist darueber."""
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer(), alt=2000)
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["abgedeckt"] == 0


def test_die_grundhoehe_verschiebt_die_schranke(conn):
    """Dieselbe Spur, dieselbe Hoehe -- nur die Unglueckstelle liegt hoeher. Das ist der Kern
    der AGL-Umstellung: ueber einem Berg gilt eine andere MSL-Schranke."""
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer(), alt=1800)
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["abgedeckt"] == 0
    update_reddung_event(conn, eid, havarist_grund_ft=1000.0)
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["abgedeckt"] > 0


def test_ein_geparktes_flugzeug_deckt_seine_zelle_nicht_ab(conn):
    """Dafuer ist die Untergrenze des Suchfensters da."""
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer(), gs=0)
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["abgedeckt"] == 0


def test_der_stand_enthaelt_NIEMALS_die_koordinate_des_havaristen(conn):
    """⚠ Die Kernanforderung aus #21. Dieser Test ist der Riegel: Was hier durchkommt, geht
    spaeter in eine API-Antwort."""
    import json
    eid = _kleiner_sektor(conn)
    _spur(conn, 111, _quer())
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    text = json.dumps(stand)
    for zahl in (f"{LAT:.4f}", f"{LON:.4f}", f"{LAT:.3f}", f"{LON:.3f}"):
        assert zahl not in text, f"Koordinate {zahl} steht im Stand"
    assert "havarist" not in text
    # Der Sektor dagegen IST oeffentlich -- ohne ihn weiss niemand, wo zu suchen ist.
    assert stand["sektor"]["sued"] < stand["sektor"]["nord"]


def test_der_fundradius_steht_im_stand(conn):
    """Er ist oeffentlich und gehoert in die Anzeige -- er verraet nichts ueber den Ort."""
    ev = get_reddung_event(conn, _kleiner_sektor(conn))
    assert compute_reddung_stand(conn, ev)["fundradius_km"] == pytest.approx(1.707, abs=0.001)


def test_die_dauer_zaehlt_vom_fund_bis_zur_einlieferung(conn):
    eid = _kleiner_sektor(conn)
    upsert_pilot(conn, 111, "Pilot 111")
    upsert_pilot(conn, 222, "Pilot 222")
    set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111)
    set_reddung_eingeliefert(conn, eid, "2026-09-25T18:12:00Z", 222, "EDWF")
    stand = compute_reddung_stand(conn, get_reddung_event(conn, eid))
    assert stand["dauer_min"] == 42
    assert stand["eingeliefert"]["icao"] == "EDWF"
    assert stand["eingeliefert"]["name"] == "Pilot 222"
    assert stand["gefunden"]["name"] == "Pilot 111"


def test_ohne_einlieferung_gibt_es_keine_dauer(conn):
    eid = _kleiner_sektor(conn)
    set_reddung_gefunden(conn, eid, "2026-09-25T17:30:00Z", 111)
    assert compute_reddung_stand(conn, get_reddung_event(conn, eid))["dauer_min"] is None


def test_spuren_beginnen_erst_ab_einem_zeitpunkt_wenn_verlangt(conn):
    """Fuers Aufnehmen zaehlen nur Punkte NACH dem Fund."""
    _spur(conn, 111, [(LAT, LON, "2026-09-25T17:10:00Z"),
                      (LAT, LON, "2026-09-25T17:40:00Z")])
    alle = reddung_spuren(conn, "2026-09-25T17:00:00Z", "2026-09-25T20:00:00Z")
    danach = reddung_spuren(conn, "2026-09-25T17:00:00Z", "2026-09-25T20:00:00Z",
                            ab="2026-09-25T17:30:00Z")
    assert len(alle[0][1]) == 2 and len(danach[0][1]) == 1
